from datetime import datetime
from enum import Enum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time import utc_now_naive


class TenantRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class SubscriptionStatus(str, Enum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"


class Tenant(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    owner_id: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=utc_now_naive, index=True)


class TenantMember(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenant.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    role: TenantRole = Field(default=TenantRole.OWNER, index=True)
    created_at: datetime = Field(default_factory=utc_now_naive, index=True)


class Plan(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)
    name: str
    max_greenhouses: int | None = None
    ai_monthly_message_limit: int | None = None
    telemetry_retention_days: int | None = None
    price_monthly_cents: int = 0
    is_active: bool = True


class Subscription(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenant.id", index=True)
    plan_id: int = Field(foreign_key="plan.id", index=True)
    status: SubscriptionStatus = Field(default=SubscriptionStatus.TRIALING, index=True)
    current_period_start: datetime = Field(default_factory=utc_now_naive, index=True)
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    created_at: datetime = Field(default_factory=utc_now_naive, index=True)
    updated_at: datetime = Field(default_factory=utc_now_naive)


class UsageEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenant.id", index=True)
    user_id: int | None = Field(default=None, foreign_key="user.id", index=True)
    event_type: str = Field(index=True)
    quantity: int = 1
    metadata_json: str | None = None
    created_at: datetime = Field(default_factory=utc_now_naive, index=True)


class PlanRead(SQLModel):
    id: int
    code: str
    name: str
    max_greenhouses: int | None
    ai_monthly_message_limit: int | None
    telemetry_retention_days: int | None
    price_monthly_cents: int
    is_active: bool


class SubscriptionRead(SQLModel):
    id: int
    tenant_id: int
    plan_id: int
    status: SubscriptionStatus
    current_period_start: datetime
    current_period_end: datetime | None
    cancel_at_period_end: bool
    created_at: datetime
    updated_at: datetime


class TenantRead(SQLModel):
    id: int
    name: str
    owner_id: int
    created_at: datetime


class TenantOverview(SQLModel):
    tenant: TenantRead
    role: TenantRole
    plan: PlanRead
    subscription: SubscriptionRead
    greenhouse_count: int
    ai_messages_used: int
