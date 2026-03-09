from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class DeviceType(str, Enum):
    SENSOR = "SENSOR"
    ACTUATOR = "ACTUATOR"


class DeviceBase(SQLModel):
    greenhouse_id: int = Field(foreign_key="greenhouse.id")
    type: DeviceType
    name: str
    topic_root: str  # MQTT topic root for this device
    min_value: float | None = None
    max_value: float | None = None


class Device(DeviceBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class DeviceCreate(DeviceBase):
    pass


class DeviceRead(DeviceBase):
    id: int
