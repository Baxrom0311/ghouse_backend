# models/greenhouse.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.core.time import utc_now_naive

from .plant import Plant
from .telemetry import Telemetry

class GreenhouseBase(SQLModel):
    name: str
    ai_mode: bool | None = None
    mqtt_topic_id: str | None = None


class GreenhouseStats(BaseModel):
    # Sensor stats
    air: float | None = None
    light: float | None = None
    humidity: float | None = None
    temperature: float | None = None
    moisture: float | None = None

    # Actuator states
    soil_water_pump: bool | None = None
    air_water_pump: bool | None = None
    led: bool | None = None
    fan: bool | None = None

    # Others
    ai_mode: bool | None = None


class Greenhouse(GreenhouseBase, table=True):
    __table_args__ = (
        UniqueConstraint("mqtt_topic_id"),
        UniqueConstraint("pending_mqtt_topic_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(
        default_factory=utc_now_naive,
        index=True,
    )
    owner_id: int = Field(foreign_key="user.id", index=True)
    tenant_id: int | None = Field(default=None, foreign_key="tenant.id", index=True)
    pending_mqtt_topic_id: str | None = None
    mqtt_topic_update_token: str | None = None

    telemetries: list["Telemetry"] = Relationship(back_populates="greenhouse")
    plants: list["Plant"] = Relationship(back_populates="greenhouse")

    @property
    def stats(self) -> GreenhouseStats:
        return GreenhouseStats(ai_mode=self.ai_mode)


class GreenhouseCreate(GreenhouseBase):
    pass


class GreenhouseRead(GreenhouseBase):
    id: int
    tenant_id: int | None = None
    created_at: datetime
    stats: GreenhouseStats


class GreenhouseUpdate(SQLModel):
    name: str | None = None
    ai_mode: bool | None = None
    mqtt_topic_id: str | None = None
