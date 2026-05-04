import json
import logging
from typing import Any

from sqlmodel import Session

from app.core.time import utc_now_naive
from app.models.command import CommandRead, CommandStatus, DeviceCommand
from app.services.mqtt_service import mqtt_service

logger = logging.getLogger(__name__)


def serialize_command(command: DeviceCommand) -> CommandRead:
    ack_payload = None
    if command.ack_payload_json:
        try:
            ack_payload = json.loads(command.ack_payload_json)
        except json.JSONDecodeError:
            ack_payload = {"raw": command.ack_payload_json}

    try:
        payload = json.loads(command.payload_json)
    except json.JSONDecodeError:
        payload = {"raw": command.payload_json}

    return CommandRead(
        id=command.id,
        greenhouse_id=command.greenhouse_id,
        command_type=command.command_type,
        topic=command.topic,
        status=command.status,
        error=command.error,
        payload=payload,
        ack_payload=ack_payload,
        created_at=command.created_at,
        published_at=command.published_at,
        acknowledged_at=command.acknowledged_at,
        updated_at=command.updated_at,
    )


def create_pending_command(
    db: Session,
    *,
    greenhouse_id: int,
    command_type: str,
    topic: str,
    payload: dict[str, Any] | str,
) -> tuple[DeviceCommand, dict[str, Any] | str]:
    command = DeviceCommand(
        greenhouse_id=greenhouse_id,
        command_type=command_type,
        topic=topic,
        payload_json=json.dumps(payload) if not isinstance(payload, str) else payload,
    )
    db.add(command)
    db.commit()
    db.refresh(command)

    if isinstance(payload, str):
        publish_payload: dict[str, Any] | str = {
            "value": payload,
            "command_id": command.id,
        }
    else:
        publish_payload = {**payload, "command_id": command.id}

    return command, publish_payload


def publish_tracked_command(
    db: Session,
    *,
    greenhouse_id: int,
    command_type: str,
    topic: str,
    payload: dict[str, Any] | str,
    retain: bool = False,
) -> DeviceCommand:
    command, publish_payload = create_pending_command(
        db,
        greenhouse_id=greenhouse_id,
        command_type=command_type,
        topic=topic,
        payload=payload,
    )

    ok = mqtt_service.publish_device_command(topic, publish_payload, retain=retain)
    now = utc_now_naive()
    if ok:
        command.status = CommandStatus.PUBLISHED
        command.published_at = now
        command.error = None
    else:
        command.status = CommandStatus.FAILED
        command.error = "MQTT broker unavailable"

    command.updated_at = now
    db.add(command)
    db.commit()
    db.refresh(command)
    return command


def apply_command_ack(
    db: Session,
    *,
    command_id: str,
    status: CommandStatus,
    ack_payload: dict[str, Any],
) -> DeviceCommand | None:
    command = db.get(DeviceCommand, command_id)
    if command is None:
        logger.warning("Ignoring ack for unknown command_id=%s", command_id)
        return None

    now = utc_now_naive()
    command.status = status
    command.ack_payload_json = json.dumps(ack_payload)
    command.updated_at = now
    if status == CommandStatus.ACKNOWLEDGED:
        command.acknowledged_at = now
        command.error = None
    else:
        command.error = ack_payload.get("message") or status.value

    db.add(command)
    db.commit()
    db.refresh(command)
    return command
