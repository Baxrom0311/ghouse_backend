import json
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.time import utc_now_naive
from app.models.greenhouse import Greenhouse
from app.models.tenant import (
    Plan,
    Subscription,
    SubscriptionStatus,
    Tenant,
    TenantMember,
    TenantRole,
    UsageEvent,
)
from app.models.user import User

FREE_PLAN_CODE = "free"


def ensure_free_plan(db: Session) -> Plan:
    plan = db.exec(select(Plan).where(Plan.code == FREE_PLAN_CODE)).first()
    if plan is not None:
        return plan

    plan = Plan(
        code=FREE_PLAN_CODE,
        name="Free",
        max_greenhouses=3,
        ai_monthly_message_limit=100,
        telemetry_retention_days=30,
        price_monthly_cents=0,
        is_active=True,
    )
    db.add(plan)
    db.flush()
    return plan


def ensure_tenant_subscription(db: Session, tenant: Tenant) -> Subscription:
    subscription = db.exec(
        select(Subscription)
        .where(Subscription.tenant_id == tenant.id)
        .order_by(Subscription.created_at.desc())
    ).first()
    if subscription is not None:
        return subscription

    plan = ensure_free_plan(db)
    now = utc_now_naive()
    subscription = Subscription(
        tenant_id=tenant.id,
        plan_id=plan.id,
        status=SubscriptionStatus.TRIALING,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )
    db.add(subscription)
    db.flush()
    return subscription


def ensure_personal_tenant(db: Session, user: User) -> Tenant:
    if user.id is None:
        raise ValueError("User must be persisted before tenant creation")

    tenant = db.exec(select(Tenant).where(Tenant.owner_id == user.id)).first()
    if tenant is None:
        display_name = user.first_name.strip() if user.first_name else user.email
        tenant = Tenant(name=f"{display_name} workspace", owner_id=user.id)
        db.add(tenant)
        db.flush()

    member = db.exec(
        select(TenantMember)
        .where(TenantMember.tenant_id == tenant.id)
        .where(TenantMember.user_id == user.id)
    ).first()
    if member is None:
        db.add(
            TenantMember(
                tenant_id=tenant.id,
                user_id=user.id,
                role=TenantRole.OWNER,
            )
        )
        db.flush()

    ensure_tenant_subscription(db, tenant)
    return tenant


def get_user_tenant_ids(db: Session, user_id: int) -> list[int]:
    member_ids = db.exec(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user_id)
    ).all()
    owned_ids = db.exec(select(Tenant.id).where(Tenant.owner_id == user_id)).all()
    return sorted({tenant_id for tenant_id in [*member_ids, *owned_ids] if tenant_id})


def get_tenant_member_role(
    db: Session, tenant_id: int, user_id: int
) -> TenantRole | None:
    member = db.exec(
        select(TenantMember)
        .where(TenantMember.tenant_id == tenant_id)
        .where(TenantMember.user_id == user_id)
    ).first()
    if member is not None:
        return member.role

    tenant = db.get(Tenant, tenant_id)
    if tenant is not None and tenant.owner_id == user_id:
        return TenantRole.OWNER

    return None


def user_can_access_greenhouse(db: Session, user_id: int, greenhouse: Greenhouse) -> bool:
    if greenhouse.owner_id == user_id:
        return True
    if greenhouse.tenant_id is None:
        return False
    return get_tenant_member_role(db, greenhouse.tenant_id, user_id) is not None


def get_greenhouse_tenant(db: Session, greenhouse: Greenhouse, user: User) -> Tenant:
    if greenhouse.tenant_id is not None:
        tenant = db.get(Tenant, greenhouse.tenant_id)
        if tenant is not None:
            return tenant

    tenant = ensure_personal_tenant(db, user)
    greenhouse.tenant_id = tenant.id
    db.add(greenhouse)
    db.flush()
    return tenant


def get_plan_for_subscription(db: Session, subscription: Subscription) -> Plan:
    plan = db.get(Plan, subscription.plan_id)
    if plan is None:
        plan = ensure_free_plan(db)
        subscription.plan_id = plan.id
        db.add(subscription)
        db.flush()
    return plan


def greenhouse_count_for_tenant(db: Session, tenant_id: int) -> int:
    count = db.exec(
        select(func.count(Greenhouse.id)).where(Greenhouse.tenant_id == tenant_id)
    ).one()
    return int(count or 0)


def ai_usage_for_subscription_period(
    db: Session, tenant_id: int, subscription: Subscription
) -> int:
    statement = (
        select(func.coalesce(func.sum(UsageEvent.quantity), 0))
        .where(UsageEvent.tenant_id == tenant_id)
        .where(UsageEvent.event_type == "ai_chat_message")
        .where(UsageEvent.created_at >= subscription.current_period_start)
    )
    if subscription.current_period_end is not None:
        statement = statement.where(UsageEvent.created_at < subscription.current_period_end)
    count = db.exec(statement).one()
    return int(count or 0)


def enforce_greenhouse_limit(db: Session, tenant: Tenant) -> None:
    subscription = ensure_tenant_subscription(db, tenant)
    plan = get_plan_for_subscription(db, subscription)
    if plan.max_greenhouses is None:
        return

    if greenhouse_count_for_tenant(db, tenant.id) >= plan.max_greenhouses:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Greenhouse limit reached for the current subscription plan",
        )


def enforce_ai_message_limit(db: Session, tenant: Tenant) -> None:
    subscription = ensure_tenant_subscription(db, tenant)
    plan = get_plan_for_subscription(db, subscription)
    if plan.ai_monthly_message_limit is None:
        return

    used = ai_usage_for_subscription_period(db, tenant.id, subscription)
    if used >= plan.ai_monthly_message_limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="AI message limit reached for the current subscription plan",
        )


def record_usage_event(
    db: Session,
    *,
    tenant_id: int,
    user_id: int | None,
    event_type: str,
    quantity: int = 1,
    metadata: dict | None = None,
) -> UsageEvent:
    event = UsageEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        event_type=event_type,
        quantity=quantity,
        metadata_json=json.dumps(metadata, sort_keys=True) if metadata else None,
    )
    db.add(event)
    db.flush()
    return event
