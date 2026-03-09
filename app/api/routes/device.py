from enum import Enum
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import get_authorized_greenhouse, get_db
from app.models.device import Device, DeviceRead
from app.models.greenhouse import Greenhouse
from app.services.device_registry import ensure_greenhouse_devices
from app.services.mqtt_service import mqtt_service

router = APIRouter(prefix="/{greenhouse_id}/devices", tags=["devices"])


class DeviceSettingsModel(BaseModel):
    min: float
    max: float


class SwitchableDeviceName(str, Enum):
    SOIL_WATER_PUMP = "soil_water_pump"
    AIR_WATER_PUMP = "air_water_pump"
    LED = "led"
    FAN = "fan"


class ConfigurableDeviceName(str, Enum):
    AIR = "air"
    HUMIDITY = "humidity"
    TEMPERATURE = "temperature"
    MOISTURE = "moisture"
    LIGHT = "light"


class ResponseOK(BaseModel):
    ok: bool = True


def get_device_topic_root(
    db: Session, greenhouse: Greenhouse, device_name: str
) -> tuple[str, dict[str, Device], Device]:
    devices = ensure_greenhouse_devices(db, greenhouse)
    device = devices.get(device_name)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    return device.topic_root, devices, device


@router.get("", response_model=list[DeviceRead])
def list_devices(
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    db: Session = Depends(get_db),
) -> list[DeviceRead]:
    devices = ensure_greenhouse_devices(db, greenhouse)
    return [DeviceRead.model_validate(device) for device in devices.values()]


@router.post("/{device_name}/switch/{device_state}", response_model=ResponseOK)
def device_switch_on_off(
    device_name: SwitchableDeviceName,
    device_state: Literal["off", "on"],
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    db: Session = Depends(get_db),
):
    rev = {"off": "0", "on": "1"}
    if greenhouse.ai_mode:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Disable AI mode before manual device control",
        )

    topic_root, _, _ = get_device_topic_root(db, greenhouse, device_name.value)
    ok = mqtt_service.publish_device_command(
        f"{topic_root}/control", rev[device_state]
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MQTT broker unavailable",
        )

    return {"ok": True}


@router.post("/{device_name}/settings", response_model=ResponseOK)
def device_settings(
    device_name: ConfigurableDeviceName,
    settings_payload: DeviceSettingsModel,
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    db: Session = Depends(get_db),
):
    """Update device settings."""
    topic_root, _, device = get_device_topic_root(db, greenhouse, device_name.value)
    ok = mqtt_service.publish_device_command(
        f"{topic_root}/settings",
        settings_payload.model_dump(),
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MQTT broker unavailable",
        )

    device.min_value = settings_payload.min
    device.max_value = settings_payload.max
    db.add(device)
    db.commit()

    return {"ok": True}
