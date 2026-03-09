# telemetry.py
from datetime import datetime, timezone
from enum import Enum

from sqlmodel import Field, Relationship, SQLModel


class DeviceName(str, Enum):
    # Sensors
    AIR = "AIR"
    LIGHT = "LIGHT"
    HUMIDITY = "HUMIDITY"
    TEMPERATURE = "TEMPERATURE"
    MOISTURE = "MOISTURE"
    # Actuators
    SOIL_WATER_PUMP = "SOIL_WATER_PUMP"
    AIR_WATER_PUMP = "AIR_WATER_PUMP"
    LED = "LED"
    FAN = "FAN"


class TelemetryBase(SQLModel):
    # device_name: DeviceName

    # Sensor Stats
    air: float | None = None
    light: float | None = None
    humidity: float | None = None
    temperature: float | None = None
    moisture: float | None = None

    # Actuator States
    soil_water_pump: bool | None = None
    air_water_pump: bool | None = None
    led: bool | None = None
    fan: bool | None = None

    # Others
    ai_mode: bool | None = None


class Telemetry(TelemetryBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    time: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    greenhouse_id: int = Field(foreign_key="greenhouse.id")

    # Relationships
    # device: "Device" = Relationship(back_populates="telemetry")
    greenhouse: "Greenhouse" = Relationship(back_populates="telemetries")


class TelemetryCreate(TelemetryBase):
    time: datetime | None = None


class TelemetryRead(TelemetryBase):
    time: datetime | None
