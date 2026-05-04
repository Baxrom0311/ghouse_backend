import secrets
import asyncio
import logging
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, status
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from starlette.websockets import WebSocketDisconnect
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, delete, func, or_
from sqlmodel import Session, select

from app.api.deps import (
    assert_can_modify_greenhouse,
    get_authorized_greenhouse,
    get_current_user,
    get_db,
)
from app.core.config import settings
from app.core.db import build_unique_topic_id
from app.core.db import engine
from app.core.security import decode_access_token
from app.core.time import utc_now_naive
from app.models.chat import ChatMessage, ChatSession
from app.models.command import CommandRead, CommandResponse, CommandStatus, DeviceCommand
from app.models.device import Device, DeviceRead
from app.models.greenhouse import (
    Greenhouse,
    GreenhouseCreate,
    GreenhouseRead,
    GreenhouseStats,
    GreenhouseUpdate,
)
from app.models.plant import Plant
from app.models.telemetry import Telemetry, TelemetryRead
from app.models.user import User
from app.services.command_service import publish_tracked_command, serialize_command
from app.services.device_registry import ensure_greenhouse_devices
from app.services.mqtt_service import mqtt_service
from app.services.tenant_service import (
    enforce_greenhouse_limit,
    ensure_personal_tenant,
    get_user_tenant_ids,
)

router = APIRouter(prefix="/greenhouses", tags=["greenhouses"])
logger = logging.getLogger(__name__)
INVALID_MQTT_TOPIC_ID_CHARS = {"/", "+", "#"}
TOPIC_ID_UPDATE_SUFFIX = "/system/topic_id"
MAX_AUTO_TOPIC_RETRIES = 3
GREENHOUSE_STREAM_INTERVAL_SECONDS = 3


def collect_reserved_topic_ids(greenhouses: list[Greenhouse]) -> set[str]:
    reserved_topic_ids: set[str] = set()
    for greenhouse in greenhouses:
        for topic_id in (greenhouse.mqtt_topic_id, greenhouse.pending_mqtt_topic_id):
            normalized_topic_id = (topic_id or "").strip()
            if normalized_topic_id:
                reserved_topic_ids.add(normalized_topic_id)
    return reserved_topic_ids


def is_topic_integrity_error(exc: IntegrityError) -> bool:
    details = str(exc).lower()
    return any(
        marker in details
        for marker in (
            "mqtt_topic_id",
            "pending_mqtt_topic_id",
            "ix_greenhouse_mqtt_topic_id",
            "ix_greenhouse_pending_mqtt_topic_id",
            "uq_greenhouse_mqtt_topic_id",
            "uq_greenhouse_pending_mqtt_topic_id",
        )
    )


def commit_greenhouse_or_raise(db: Session, greenhouse: Greenhouse) -> None:
    db.add(greenhouse)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if is_topic_integrity_error(exc):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="mqtt_topic_id already in use",
            ) from exc
        raise
    db.refresh(greenhouse)


def resolve_mqtt_topic_id(
    db: Session, requested_topic_id: str | None, greenhouse_id: int | None = None
) -> str:
    topic_id = (requested_topic_id or "").strip()
    if not topic_id:
        # Optimization: Only fetch the IDs and Topic IDs, not full objects
        results = db.exec(select(Greenhouse.id, Greenhouse.mqtt_topic_id, Greenhouse.pending_mqtt_topic_id)).all()
        used_topic_ids = set()
        max_id = 0
        for g_id, tid, ptid in results:
            if tid: used_topic_ids.add(tid.strip())
            if ptid: used_topic_ids.add(ptid.strip())
            if g_id > max_id: max_id = g_id
        
        next_greenhouse_id = max_id + 1
        return build_unique_topic_id(
            used_topic_ids,
            next_greenhouse_id,
            prefer_default=settings.DEFAULT_MQTT_TOPIC_ID not in used_topic_ids,
        )

    if any(char in topic_id for char in INVALID_MQTT_TOPIC_ID_CHARS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="mqtt_topic_id must be a single MQTT topic segment",
        )

    statement = select(Greenhouse).where(
        (Greenhouse.mqtt_topic_id == topic_id)
        | (Greenhouse.pending_mqtt_topic_id == topic_id)
    )
    existing = db.exec(statement).first()
    if existing and existing.id != greenhouse_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="mqtt_topic_id already in use",
        )

    return topic_id


def telemetry_to_stats(
    greenhouse: Greenhouse, telemetry: Telemetry | None
) -> GreenhouseStats:
    if telemetry is None:
        return GreenhouseStats(ai_mode=greenhouse.ai_mode)

    return GreenhouseStats(
        air=telemetry.air,
        light=telemetry.light,
        humidity=telemetry.humidity,
        temperature=telemetry.temperature,
        moisture=telemetry.moisture,
        soil_water_pump=telemetry.soil_water_pump,
        air_water_pump=telemetry.air_water_pump,
        led=telemetry.led,
        fan=telemetry.fan,
        ai_mode=telemetry.ai_mode
        if telemetry.ai_mode is not None
        else greenhouse.ai_mode,
    )


def latest_telemetry_by_greenhouse(
    db: Session, greenhouse_ids: list[int]
) -> dict[int, Telemetry]:
    if not greenhouse_ids:
        return {}

    latest_times_subquery = (
        select(
            Telemetry.greenhouse_id.label("greenhouse_id"),
            func.max(Telemetry.time).label("latest_time"),
        )
        .where(Telemetry.greenhouse_id.in_(greenhouse_ids))
        .group_by(Telemetry.greenhouse_id)
        .subquery()
    )

    statement = (
        select(Telemetry)
        .join(
            latest_times_subquery,
            and_(
                Telemetry.greenhouse_id == latest_times_subquery.c.greenhouse_id,
                Telemetry.time == latest_times_subquery.c.latest_time,
            ),
        )
        .where(Telemetry.greenhouse_id.in_(greenhouse_ids))
    )

    latest_by_greenhouse: dict[int, Telemetry] = {}
    for telemetry in db.exec(statement).all():
        current = latest_by_greenhouse.get(telemetry.greenhouse_id)
        if current is None or telemetry.time > current.time or (
            telemetry.time == current.time and (telemetry.id or 0) > (current.id or 0)
        ):
            latest_by_greenhouse[telemetry.greenhouse_id] = telemetry

    return latest_by_greenhouse


def telemetry_history_for_greenhouse(
    db: Session, greenhouse_id: int, hours: int, limit: int
) -> list[Telemetry]:
    statement = select(Telemetry).where(Telemetry.greenhouse_id == greenhouse_id)
    if hours > 0:
        cutoff = utc_now_naive() - timedelta(hours=hours)
        statement = statement.where(Telemetry.time >= cutoff)

    statement = statement.order_by(Telemetry.time.desc()).limit(limit)
    return list(reversed(db.exec(statement).all()))


def serialize_greenhouse(
    greenhouse: Greenhouse, telemetry: Telemetry | None = None
) -> GreenhouseRead:
    return GreenhouseRead(
        id=greenhouse.id,
        name=greenhouse.name,
        ai_mode=greenhouse.ai_mode,
        mqtt_topic_id=greenhouse.mqtt_topic_id,
        tenant_id=greenhouse.tenant_id,
        created_at=greenhouse.created_at,
        stats=telemetry_to_stats(greenhouse, telemetry),
    )


def accessible_greenhouses_statement(user_id: int, tenant_ids: list[int]):
    if tenant_ids:
        return select(Greenhouse).where(
            or_(Greenhouse.owner_id == user_id, Greenhouse.tenant_id.in_(tenant_ids))
        )
    return select(Greenhouse).where(Greenhouse.owner_id == user_id)


def greenhouse_snapshot_payload(db: Session, user_id: int) -> dict:
    tenant_ids = get_user_tenant_ids(db, user_id)
    statement = accessible_greenhouses_statement(user_id, tenant_ids)
    greenhouses: list[Greenhouse] = db.exec(statement).all()
    gh_ids = [greenhouse.id for greenhouse in greenhouses]
    
    latest_by_greenhouse = latest_telemetry_by_greenhouse(db, gh_ids)
    
    # Batch fetch devices for all greenhouses to avoid N+1
    all_devices_statement = select(Device).where(Device.greenhouse_id.in_(gh_ids))
    all_devices = db.exec(all_devices_statement).all()
    devices_by_gh: dict[int, list[Device]] = {}
    for device in all_devices:
        devices_by_gh.setdefault(device.greenhouse_id, []).append(device)

    return {
        "greenhouses": [
            {
                "greenhouse": serialize_greenhouse(
                    greenhouse,
                    latest_by_greenhouse.get(greenhouse.id),
                ),
                "devices": [
                    DeviceRead.model_validate(device)
                    for device in devices_by_gh.get(greenhouse.id, [])
                ],
            }
            for greenhouse in greenhouses
        ]
    }


def websocket_user_id(token: str | None) -> int | None:
    if not token:
        return None
    payload = decode_access_token(token)
    if payload is None:
        return None
    try:
        return int(payload.get("sub"))
    except (TypeError, ValueError):
        return None


def websocket_protocol_token(websocket: WebSocket) -> str | None:
    protocol_header = websocket.headers.get("sec-websocket-protocol")
    if not protocol_header:
        return None
    protocols = [item.strip() for item in protocol_header.split(",")]
    if "agroai.auth" not in protocols:
        return None
    for protocol in protocols:
        if protocol != "agroai.auth":
            return protocol
    return None


@router.websocket("/ws")
async def greenhouses_ws(websocket: WebSocket, token: str | None = Query(default=None)):
    protocol_token = websocket_protocol_token(websocket)
    auth_token = protocol_token or token
    user_id = websocket_user_id(auth_token)
    if user_id is None:
        await websocket.close(code=1008)
        return

    await websocket.accept(subprotocol="agroai.auth" if protocol_token else None)

    def _get_snapshot_if_active(uid: int):
        with Session(engine) as db:
            user = db.get(User, uid)
            if user is None or not user.is_active:
                return None
            return greenhouse_snapshot_payload(db, uid)

    try:
        while True:
            snapshot = await run_in_threadpool(_get_snapshot_if_active, user_id)
            if snapshot is None:
                await websocket.close(code=1008)
                return
            await websocket.send_json(jsonable_encoder(snapshot))
            await asyncio.sleep(GREENHOUSE_STREAM_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        return


@router.post("", response_model=GreenhouseRead, status_code=status.HTTP_201_CREATED)
def create_greenhouse(
    greenhouse_data: GreenhouseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new greenhouse."""
    tenant = ensure_personal_tenant(db, current_user)
    enforce_greenhouse_limit(db, tenant)

    for attempt in range(MAX_AUTO_TOPIC_RETRIES):
        mqtt_topic_id = resolve_mqtt_topic_id(db, greenhouse_data.mqtt_topic_id)
        db_greenhouse = Greenhouse(
            name=greenhouse_data.name,
            ai_mode=greenhouse_data.ai_mode,
            mqtt_topic_id=mqtt_topic_id,
            owner_id=current_user.id,
            tenant_id=tenant.id,
        )
        db.add(db_greenhouse)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            if greenhouse_data.mqtt_topic_id:
                if is_topic_integrity_error(exc):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="mqtt_topic_id already in use",
                    ) from exc
                raise
            if attempt == MAX_AUTO_TOPIC_RETRIES - 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Failed to allocate unique mqtt_topic_id. Retry the request.",
                ) from exc
            continue

        db.refresh(db_greenhouse)
        ensure_greenhouse_devices(db, db_greenhouse)
        return serialize_greenhouse(db_greenhouse)

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Failed to allocate unique mqtt_topic_id. Retry the request.",
    )


@router.get("", response_model=list[GreenhouseRead])
def list_greenhouses(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    """List all greenhouses owned by the current user."""

    tenant_ids = get_user_tenant_ids(db, current_user.id)
    statement = accessible_greenhouses_statement(current_user.id, tenant_ids)
    greenhouses: list[Greenhouse] = db.exec(statement.offset(skip).limit(limit)).all()
    latest_by_greenhouse = latest_telemetry_by_greenhouse(
        db, [greenhouse.id for greenhouse in greenhouses]
    )

    return [
        serialize_greenhouse(
            greenhouse,
            latest_by_greenhouse.get(greenhouse.id),
        )
        for greenhouse in greenhouses
    ]


@router.get("/{greenhouse_id}", response_model=GreenhouseRead)
def get_greenhouse(
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    db: Session = Depends(get_db),
):
    ensure_greenhouse_devices(db, greenhouse)
    latest_by_greenhouse = latest_telemetry_by_greenhouse(db, [greenhouse.id])
    return serialize_greenhouse(greenhouse, latest_by_greenhouse.get(greenhouse.id))


@router.get("/{greenhouse_id}/telemetry", response_model=list[TelemetryRead])
def list_greenhouse_telemetry(
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    db: Session = Depends(get_db),
    hours: int = Query(default=24, ge=1, le=24 * 30),
    limit: int = Query(default=500, ge=1, le=1000),
) -> list[TelemetryRead]:
    telemetry = telemetry_history_for_greenhouse(db, greenhouse.id, hours, limit)
    return [TelemetryRead.model_validate(point) for point in telemetry]


@router.get("/{greenhouse_id}/commands/{command_id}", response_model=CommandRead)
def get_device_command(
    command_id: str,
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    db: Session = Depends(get_db),
):
    command = db.get(DeviceCommand, command_id)
    if command is None or command.greenhouse_id != greenhouse.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Command not found",
        )

    return serialize_command(command)


@router.patch("/{greenhouse_id}", response_model=GreenhouseRead)
def edit_greenhouse(
    greenhouse_update: GreenhouseUpdate,
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_can_modify_greenhouse(db, current_user, greenhouse)
    update_data = greenhouse_update.model_dump(exclude_unset=True)
    topic_update_payload: dict[str, str] | None = None
    current_topic_id = (greenhouse.mqtt_topic_id or settings.DEFAULT_MQTT_TOPIC_ID).strip()
    regular_updates = {
        key: value for key, value in update_data.items() if key != "mqtt_topic_id"
    }

    if "mqtt_topic_id" in update_data:
        new_topic_id = resolve_mqtt_topic_id(
            db, update_data["mqtt_topic_id"], greenhouse.id
        )
        if new_topic_id != current_topic_id:
            greenhouse.pending_mqtt_topic_id = new_topic_id
            greenhouse.mqtt_topic_update_token = secrets.token_urlsafe(16)
            topic_update_payload = {
                "topic_id": new_topic_id,
                "token": greenhouse.mqtt_topic_update_token,
            }
            commit_greenhouse_or_raise(db, greenhouse)
        else:
            greenhouse.pending_mqtt_topic_id = None
            greenhouse.mqtt_topic_update_token = None
            regular_updates["mqtt_topic_id"] = new_topic_id

    if topic_update_payload is not None:
        ok = mqtt_service.publish_device_command(
            f"{current_topic_id}{TOPIC_ID_UPDATE_SUFFIX}",
            topic_update_payload,
            retain=True,
        )
        if not ok:
            greenhouse.pending_mqtt_topic_id = None
            greenhouse.mqtt_topic_update_token = None
            commit_greenhouse_or_raise(db, greenhouse)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="MQTT broker unavailable",
            )

    if regular_updates:
        for key, value in regular_updates.items():
            setattr(greenhouse, key, value)
        commit_greenhouse_or_raise(db, greenhouse)

    ensure_greenhouse_devices(db, greenhouse)

    latest_by_greenhouse = latest_telemetry_by_greenhouse(db, [greenhouse.id])
    return serialize_greenhouse(greenhouse, latest_by_greenhouse.get(greenhouse.id))


@router.delete("/{greenhouse_id}")
def delete_greenhouse(
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_can_modify_greenhouse(db, current_user, greenhouse)
    try:
        chat_sessions = db.exec(
            select(ChatSession).where(ChatSession.greenhouse_id == greenhouse.id)
        ).all()
        for chat_session in chat_sessions:
            db.exec(delete(ChatMessage).where(ChatMessage.session_id == chat_session.id))
            db.delete(chat_session)
        db.exec(delete(Device).where(Device.greenhouse_id == greenhouse.id))
        db.exec(delete(Plant).where(Plant.greenhouse_id == greenhouse.id))
        db.exec(delete(Telemetry).where(Telemetry.greenhouse_id == greenhouse.id))
        db.exec(delete(DeviceCommand).where(DeviceCommand.greenhouse_id == greenhouse.id))
        db.delete(greenhouse)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Failed to delete greenhouse id=%s", greenhouse.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete greenhouse",
        ) from e
    return {"ok": True}


@router.post("/{greenhouse_id}/ai/switch/{state}", response_model=CommandResponse)
def switch_mode_ai_control(
    state: Literal["on", "off"],
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_can_modify_greenhouse(db, current_user, greenhouse)
    rev = {"off": "0", "on": "1"}
    mqtt_topic_id = greenhouse.mqtt_topic_id or settings.DEFAULT_MQTT_TOPIC_ID
    command = publish_tracked_command(
        db,
        greenhouse_id=greenhouse.id,
        command_type="ai_mode_switch",
        topic=f"{mqtt_topic_id}/mode/ai",
        payload=rev[state],
    )
    if command.status == CommandStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=command.error or "MQTT broker unavailable",
        )

    greenhouse.ai_mode = state == "on"
    db.add(greenhouse)
    db.commit()

    return CommandResponse(command_id=command.id, status=command.status)


from .device import router as device_router

router.include_router(device_router)
