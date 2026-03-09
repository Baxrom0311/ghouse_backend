from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, delete, func
from sqlmodel import Session, select

from app.api.deps import get_authorized_greenhouse, get_current_user, get_db
from app.core.config import settings
from app.core.db import build_unique_topic_id
from app.models.device import Device
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
from app.services.device_registry import ensure_greenhouse_devices
from app.services.mqtt_service import mqtt_service

router = APIRouter(prefix="/greenhouses", tags=["greenhouses"])


def resolve_mqtt_topic_id(
    db: Session, requested_topic_id: str | None, greenhouse_id: int | None = None
) -> str:
    topic_id = (requested_topic_id or "").strip()
    if not topic_id:
        greenhouses = db.exec(select(Greenhouse).order_by(Greenhouse.id)).all()
        used_topic_ids = {
            existing.mqtt_topic_id.strip()
            for existing in greenhouses
            if existing.mqtt_topic_id and existing.mqtt_topic_id.strip()
        }
        next_greenhouse_id = max((existing.id or 0 for existing in greenhouses), default=0) + 1
        return build_unique_topic_id(
            used_topic_ids,
            next_greenhouse_id,
            prefer_default=not used_topic_ids,
        )

    statement = select(Greenhouse).where(Greenhouse.mqtt_topic_id == topic_id)
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
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
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
        created_at=greenhouse.created_at,
        stats=telemetry_to_stats(greenhouse, telemetry),
    )


@router.post("", response_model=GreenhouseRead, status_code=status.HTTP_201_CREATED)
def create_greenhouse(
    greenhouse_data: GreenhouseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new greenhouse."""
    mqtt_topic_id = resolve_mqtt_topic_id(db, greenhouse_data.mqtt_topic_id)
    db_greenhouse = Greenhouse(
        name=greenhouse_data.name,
        ai_mode=greenhouse_data.ai_mode,
        mqtt_topic_id=mqtt_topic_id,
        owner_id=current_user.id,
    )
    db.add(db_greenhouse)
    db.commit()
    db.refresh(db_greenhouse)
    ensure_greenhouse_devices(db, db_greenhouse)
    return serialize_greenhouse(db_greenhouse)


@router.get("", response_model=list[GreenhouseRead])
def list_greenhouses(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[GreenhouseRead]:
    """List all greenhouses owned by the current user."""

    statement = select(Greenhouse).where(Greenhouse.owner_id == current_user.id)
    greenhouses: list[Greenhouse] = db.exec(statement).all()
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


@router.patch("/{greenhouse_id}", response_model=GreenhouseRead)
def edit_greenhouse(
    greenhouse_update: GreenhouseUpdate,
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    db: Session = Depends(get_db),
):
    update_data = greenhouse_update.model_dump(exclude_unset=True)
    if "mqtt_topic_id" in update_data:
        update_data["mqtt_topic_id"] = resolve_mqtt_topic_id(
            db, update_data["mqtt_topic_id"], greenhouse.id
        )

    for key, value in update_data.items():
        setattr(greenhouse, key, value)

    db.add(greenhouse)
    db.commit()
    db.refresh(greenhouse)
    ensure_greenhouse_devices(db, greenhouse)

    latest_by_greenhouse = latest_telemetry_by_greenhouse(db, [greenhouse.id])
    return serialize_greenhouse(greenhouse, latest_by_greenhouse.get(greenhouse.id))


@router.delete("/{greenhouse_id}")
def delete_greenhouse(
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    db: Session = Depends(get_db),
):
    db.exec(delete(Device).where(Device.greenhouse_id == greenhouse.id))
    db.exec(delete(Plant).where(Plant.greenhouse_id == greenhouse.id))
    db.exec(delete(Telemetry).where(Telemetry.greenhouse_id == greenhouse.id))
    db.delete(greenhouse)
    db.commit()
    return {"ok": True}


class ResponseOK(BaseModel):
    ok: bool = True

@router.post("/{greenhouse_id}/ai/switch/{state}", response_model=ResponseOK)
def switch_mode_ai_control(
    state: Literal["on", "off"],
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    db: Session = Depends(get_db),
):
    rev = {"off": "0", "on": "1"}
    mqtt_topic_id = greenhouse.mqtt_topic_id or settings.DEFAULT_MQTT_TOPIC_ID
    ok = mqtt_service.publish_device_command(f"{mqtt_topic_id}/mode/ai", rev[state])
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MQTT broker unavailable",
        )

    greenhouse.ai_mode = state == "on"
    db.add(greenhouse)
    db.commit()

    return {"ok": True}


from .device import router as device_router

router.include_router(device_router)
