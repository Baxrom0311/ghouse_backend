# telemetry.py
from datetime import datetime
from enum import Enum

from sqlalchemy import Index
from sqlmodel import Field, Relationship, SQLModel

from app.core.time import utc_now_naive


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
    __table_args__ = (
        Index("ix_telemetry_greenhouse_time_id", "greenhouse_id", "time", "id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    time: datetime = Field(
        default_factory=utc_now_naive,
        index=True,
    )
    greenhouse_id: int = Field(foreign_key="greenhouse.id", index=True)

    # Relationships
    # device: "Device" = Relationship(back_populates="telemetry")
    greenhouse: "Greenhouse" = Relationship(back_populates="telemetries")


class TelemetryCreate(TelemetryBase):
    time: datetime | None = None


class TelemetryRead(TelemetryBase):
    time: datetime | None
