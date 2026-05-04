from datetime import datetime
from enum import Enum

from sqlalchemy import Column, Text
from sqlmodel import Field, Relationship, SQLModel

from app.core.time import utc_now_naive


class ChatScope(str, Enum):
    GLOBAL = "global"
    GREENHOUSE = "greenhouse"


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatSession(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    greenhouse_id: int | None = Field(default=None, foreign_key="greenhouse.id", index=True)
    scope: ChatScope = Field(default=ChatScope.GLOBAL, index=True)
    title: str | None = Field(default=None, max_length=120)
    created_at: datetime = Field(default_factory=utc_now_naive, index=True)
    updated_at: datetime = Field(default_factory=utc_now_naive)

    messages: list["ChatMessage"] = Relationship(back_populates="session")


class ChatMessage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="chatsession.id", index=True)
    role: ChatRole = Field(index=True)
    content: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=utc_now_naive, index=True)

    session: ChatSession = Relationship(back_populates="messages")


class ChatSessionRead(SQLModel):
    id: int
    owner_id: int
    greenhouse_id: int | None
    scope: ChatScope
    title: str | None
    created_at: datetime
    updated_at: datetime


class ChatMessageRead(SQLModel):
    id: int
    session_id: int
    role: ChatRole
    content: str
    created_at: datetime
