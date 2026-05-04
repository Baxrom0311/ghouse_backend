from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_current_user, get_db
from app.models.tenant import (
    PlanRead,
    SubscriptionRead,
    TenantOverview,
    TenantRead,
    TenantRole,
)
from app.models.user import User
from app.services.tenant_service import (
    ai_usage_for_subscription_period,
    ensure_personal_tenant,
    ensure_tenant_subscription,
    get_plan_for_subscription,
    get_tenant_member_role,
    greenhouse_count_for_tenant,
)

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("/current", response_model=TenantOverview)
def get_current_tenant_overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = ensure_personal_tenant(db, current_user)
    subscription = ensure_tenant_subscription(db, tenant)
    plan = get_plan_for_subscription(db, subscription)
    role = (
        get_tenant_member_role(db, tenant.id, current_user.id)
        if current_user.id is not None
        else None
    ) or TenantRole.OWNER
    overview = TenantOverview(
        tenant=TenantRead.model_validate(tenant),
        role=role,
        plan=PlanRead.model_validate(plan),
        subscription=SubscriptionRead.model_validate(subscription),
        greenhouse_count=greenhouse_count_for_tenant(db, tenant.id),
        ai_messages_used=ai_usage_for_subscription_period(db, tenant.id, subscription),
    )
    db.commit()
    return overview
