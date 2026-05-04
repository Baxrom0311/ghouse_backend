from enum import Enum
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, model_validator
from sqlmodel import Session

from app.api.deps import assert_can_modify_greenhouse, get_authorized_greenhouse, get_current_user, get_db
from app.core.config import settings as app_settings
from app.models.command import CommandResponse, CommandStatus
from app.models.device import Device, DeviceRead
from app.models.greenhouse import Greenhouse
from app.models.user import User
from app.services.command_service import publish_tracked_command
from app.services.device_registry import ensure_greenhouse_devices

router = APIRouter(prefix="/{greenhouse_id}/devices", tags=["devices"])


class DeviceSettingsModel(BaseModel):
    min: float
    max: float

    @model_validator(mode="after")
    def validate_bounds(self) -> "DeviceSettingsModel":
        if self.max <= self.min:
            raise ValueError("max must be greater than min")
        return self


class BulkDeviceSettingsModel(BaseModel):
    air: DeviceSettingsModel | None = None
    humidity: DeviceSettingsModel | None = None
    temperature: DeviceSettingsModel | None = None
    moisture: DeviceSettingsModel | None = None
    light: DeviceSettingsModel | None = None

    @model_validator(mode="after")
    def validate_non_empty(self) -> "BulkDeviceSettingsModel":
        if not any(
            (
                self.air,
                self.humidity,
                self.temperature,
                self.moisture,
                self.light,
            )
        ):
            raise ValueError("At least one device setting must be provided")
        return self


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


DEVICE_SETTING_LIMITS: dict[str, tuple[int, int]] = {
    ConfigurableDeviceName.AIR.value: (0, 10000),
    ConfigurableDeviceName.HUMIDITY.value: (0, 100),
    ConfigurableDeviceName.TEMPERATURE.value: (-20, 80),
    ConfigurableDeviceName.MOISTURE.value: (0, 100),
    ConfigurableDeviceName.LIGHT.value: (0, 100),
}


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


def normalize_device_settings(
    device_name: str,
    settings_payload: DeviceSettingsModel,
) -> dict[str, int]:
    normalized_min = int(round(settings_payload.min))
    normalized_max = int(round(settings_payload.max))
    if normalized_max <= normalized_min:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="max must be greater than min after integer normalization",
        )
    lower_limit, upper_limit = DEVICE_SETTING_LIMITS[device_name]
    if normalized_min < lower_limit or normalized_max > upper_limit:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{device_name} settings must be between {lower_limit} and {upper_limit}",
        )
    return {"min": normalized_min, "max": normalized_max}


@router.get("", response_model=list[DeviceRead])
def list_devices(
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    db: Session = Depends(get_db),
) -> list[DeviceRead]:
    devices = ensure_greenhouse_devices(db, greenhouse)
    return [DeviceRead.model_validate(device) for device in devices.values()]


@router.post("/{device_name}/switch/{device_state}", response_model=CommandResponse)
def device_switch_on_off(
    device_name: SwitchableDeviceName,
    device_state: Literal["off", "on"],
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_can_modify_greenhouse(db, current_user, greenhouse)
    rev = {"off": "0", "on": "1"}
    if greenhouse.ai_mode:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Disable AI mode before manual device control",
        )

    topic_root, _, _ = get_device_topic_root(db, greenhouse, device_name.value)
    command = publish_tracked_command(
        db,
        greenhouse_id=greenhouse.id,
        command_type=f"{device_name.value}_switch",
        topic=f"{topic_root}/control",
        payload=rev[device_state],
    )
    if command.status == CommandStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=command.error or "MQTT broker unavailable",
        )

    return CommandResponse(command_id=command.id, status=command.status)


@router.post("/{device_name}/settings", response_model=CommandResponse)
def device_settings(
    device_name: ConfigurableDeviceName,
    settings_payload: DeviceSettingsModel,
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_can_modify_greenhouse(db, current_user, greenhouse)
    """Update device settings."""
    topic_root, _, device = get_device_topic_root(db, greenhouse, device_name.value)
    normalized_settings = normalize_device_settings(device_name.value, settings_payload)
    command = publish_tracked_command(
        db,
        greenhouse_id=greenhouse.id,
        command_type=f"{device_name.value}_settings",
        topic=f"{topic_root}/settings",
        payload=normalized_settings,
        retain=True,
    )
    if command.status == CommandStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=command.error or "MQTT broker unavailable",
        )

    device.min_value = normalized_settings["min"]
    device.max_value = normalized_settings["max"]
    db.add(device)
    db.commit()

    return CommandResponse(command_id=command.id, status=command.status)


@router.post("/settings", response_model=CommandResponse)
def bulk_device_settings(
    settings_payload: BulkDeviceSettingsModel,
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_can_modify_greenhouse(db, current_user, greenhouse)
    """Update multiple sensor thresholds as one settings operation."""
    devices = ensure_greenhouse_devices(db, greenhouse)
    normalized_by_name: dict[str, dict[str, int]] = {}

    for device_name in ConfigurableDeviceName:
        payload = getattr(settings_payload, device_name.value)
        if payload is None:
            continue
        if device_name.value not in devices:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Device not found: {device_name.value}",
            )
        normalized_by_name[device_name.value] = normalize_device_settings(
            device_name.value,
            payload,
        )

    topic_prefix = greenhouse.mqtt_topic_id
    if not topic_prefix:
        topic_prefix = app_settings.DEFAULT_MQTT_TOPIC_ID

    command = publish_tracked_command(
        db,
        greenhouse_id=greenhouse.id,
        command_type="bulk_settings",
        topic=f"{topic_prefix}/settings",
        payload=normalized_by_name,
        retain=True,
    )
    if command.status == CommandStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=command.error or "MQTT broker unavailable",
        )

    for device_name, normalized_settings in normalized_by_name.items():
        device = devices[device_name]
        device.min_value = normalized_settings["min"]
        device.max_value = normalized_settings["max"]
        db.add(device)

    db.commit()

    return CommandResponse(command_id=command.id, status=command.status)
