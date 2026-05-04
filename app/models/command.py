from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, field_validator
from sqlmodel import Field, SQLModel

from app.core.time import utc_now_naive


class CommandStatus(str, Enum):
    PENDING = "pending"
    PUBLISHED = "published"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class DeviceCommand(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    greenhouse_id: int = Field(foreign_key="greenhouse.id", index=True)
    command_type: str
    topic: str
    payload_json: str
    status: CommandStatus = Field(default=CommandStatus.PENDING, index=True)
    error: str | None = None
    ack_payload_json: str | None = None
    created_at: datetime = Field(default_factory=utc_now_naive, index=True)
    published_at: datetime | None = None
    acknowledged_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now_naive)


class CommandRead(BaseModel):
    id: str
    greenhouse_id: int
    command_type: str
    topic: str
    status: CommandStatus
    error: str | None = None
    payload: dict[str, Any]
    ack_payload: dict[str, Any] | None = None
    created_at: datetime
    published_at: datetime | None = None
    acknowledged_at: datetime | None = None
    updated_at: datetime


class CommandResponse(BaseModel):
    ok: bool = True
    command_id: str
    status: CommandStatus


class CommandAckPayload(BaseModel):
    command_id: str
    status: CommandStatus = CommandStatus.ACKNOWLEDGED
    topic: str | None = None
    message: str | None = None

    @field_validator("status")
    @classmethod
    def status_must_be_terminal(cls, status: CommandStatus) -> CommandStatus:
        if status not in {
            CommandStatus.ACKNOWLEDGED,
            CommandStatus.FAILED,
            CommandStatus.TIMED_OUT,
        }:
            raise ValueError("ack status must be acknowledged, failed, or timed_out")
        return status
