from datetime import datetime

from sqlalchemy import JSON, Index
from sqlmodel import Column, Field, SQLModel

from app.core.time import utc_now_naive


class VisionEvent(SQLModel, table=True):
    __tablename__ = "vision_event"
    __table_args__ = (
        Index("ix_vision_event_greenhouse_created", "greenhouse_id", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    greenhouse_id: int = Field(foreign_key="greenhouse.id", index=True)
    device_id: str
    class_name: str  # healthy, early_blight, etc.
    confidence: float
    health_status: str  # HEALTHY, ENV_STRESS, DISEASE, CRITICAL
    risk_score: float
    latency_ms: float
    image_url: str | None = None
    sensor_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now_naive)


class VisionEventRead(SQLModel):
    id: int
    greenhouse_id: int
    device_id: str
    class_name: str
    confidence: float
    health_status: str
    risk_score: float
    latency_ms: float
    image_url: str | None
    sensor_snapshot: dict
    created_at: datetime


class VisionStats(SQLModel):
    date: str
    total: int
    healthy: int
    diseased: int
    critical: int
    avg_confidence: float
