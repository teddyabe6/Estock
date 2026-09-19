"""Platform administration (PRD 5.2, 17).

A separate identity and permission boundary from tenant users.  There is no
hidden impersonation: support access to a tenant is explicit, time-bound and
audited.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.core.audit import AuditAction, record_audit
from app.core.config import settings
from app.core.db import utcnow
from app.core.deps import DbSession, PlatformAdminUser
from app.core.errors import AuthenticationError, NotFoundError
from app.core.security import create_access_token, verify_password
from app.models.access import TenantMembership
from app.models.catalogue import Product
from app.models.platform import (
    AuditEvent,
    FeatureFlag,
    PlatformAdmin,
    Subscription,
    SubscriptionPlan,
    Tenant,
    TenantStatus,
)
from app.models.sales import Sale
from app.services import subscription as subscription_service

router = APIRouter(prefix="/platform", tags=["platform admin"])

#: Support access grants are short-lived by design (PRD 5.2).
SUPPORT_TOKEN_MINUTES = 60


class AdminLogin(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
def login(payload: AdminLogin, db: DbSession) -> dict:
    admin = db.execute(
        select(PlatformAdmin).where(PlatformAdmin.email == payload.email.strip().lower())
    ).scalar_one_or_none()
    if admin is None or not verify_password(payload.password, admin.password_hash):
        raise AuthenticationError("Email or password is incorrect")
    if not admin.is_active:
        raise AuthenticationError("This administrator account is disabled")
    admin.last_login_at = utcnow()
    token = create_access_token(subject=admin.id, tenant_id=None, is_platform_admin=True)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_minutes": settings.access_token_ttl_minutes,
        "admin": {"id": str(admin.id), "email": admin.email, "full_name": admin.full_name},
    }


@router.get("/tenants")
def list_tenants(
    admin: PlatformAdminUser,
    db: DbSession,
    q: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    stmt = select(Tenant)
    if q:
        stmt = stmt.where(func.lower(Tenant.name).like(f"%{q.strip().lower()}%"))
    if status_filter:
        stmt = stmt.where(Tenant.status == status_filter)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    tenants = db.execute(
        stmt.order_by(Tenant.created_at.desc()).limit(limit).offset(offset)
    ).scalars().all()

    items = []
    for tenant in tenants:
        subscription = db.execute(
            select(Subscription).where(Subscription.tenant_id == tenant.id)
        ).scalar_one_or_none()
        items.append(
            {
                "id": str(tenant.id),
                "name": tenant.name,
                "slug": tenant.slug,
                "status": str(tenant.status),
                "created_at": tenant.created_at.isoformat(),
                "trial_ends_on": (
                    subscription.trial_ends_on.isoformat()
                    if subscription and subscription.trial_ends_on
                    else None
                ),
                "subscription_status": (
                    str(subscription.status) if subscription else None
                ),
                "user_count": db.execute(
                    select(func.count())
                    .select_from(TenantMembership)
                    .where(TenantMembership.tenant_id == tenant.id)
                ).scalar_one(),
                "product_count": db.execute(
                    select(func.count())
                    .select_from(Product)
                    .where(Product.tenant_id == tenant.id)
                ).scalar_one(),
                "sale_count": db.execute(
                    select(func.count()).select_from(Sale).where(Sale.tenant_id == tenant.id)
                ).scalar_one(),
            }
        )
    return {"total": total, "limit": limit, "offset": offset, "items": items}


class TenantStatusIn(BaseModel):
    status: TenantStatus
    reason: str | None = None


@router.patch("/tenants/{tenant_id}/status")
def set_status(
    tenant_id: uuid.UUID, payload: TenantStatusIn, admin: PlatformAdminUser, db: DbSession
) -> dict:
    """Change tenant access.  Never deletes or alters business data (PRD 17)."""
    tenant = subscription_service.set_tenant_status(
        db, tenant_id, payload.status, admin_id=admin.id, reason=payload.reason
    )
    return {"id": str(tenant.id), "status": str(tenant.status)}


class TrialIn(BaseModel):
    trial_days: int = Field(ge=0, le=365)
    reason: str | None = None


@router.patch("/tenants/{tenant_id}/trial")
def set_trial(
    tenant_id: uuid.UUID, payload: TrialIn, admin: PlatformAdminUser, db: DbSession
) -> dict:
    subscription = db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if subscription is None:
        raise NotFoundError("This business has no subscription record")
    start = subscription.trial_started_on or date.today()
    subscription.trial_ends_on = start + timedelta(days=payload.trial_days)
    tenant = db.get(Tenant, tenant_id)
    if tenant and tenant.status == TenantStatus.RESTRICTED and subscription.trial_ends_on >= date.today():
        tenant.status = TenantStatus.TRIAL
        subscription.status = subscription.status.__class__.TRIALING

    record_audit(
        db,
        action=AuditAction.SUBSCRIPTION_CHANGED,
        tenant_id=tenant_id,
        actor_platform_admin_id=admin.id,
        actor_label=admin.email,
        entity_type="subscription",
        entity_id=subscription.id,
        summary=f"Trial set to {payload.trial_days} days (ends {subscription.trial_ends_on})",
        payload={"reason": payload.reason},
    )
    db.flush()
    return {
        "tenant_id": str(tenant_id),
        "trial_ends_on": subscription.trial_ends_on.isoformat(),
        "status": str(subscription.status),
    }


class PlanIn(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    monthly_price: float = Field(0, ge=0)
    currency: str = "ETB"
    max_branches: int | None = None
    max_users: int | None = None
    max_products: int | None = None


@router.get("/plans")
def list_plans(admin: PlatformAdminUser, db: DbSession) -> list[dict]:
    rows = db.execute(select(SubscriptionPlan).order_by(SubscriptionPlan.monthly_price)).scalars()
    return [
        {
            "id": str(plan.id),
            "code": plan.code,
            "name": plan.name,
            "monthly_price": str(plan.monthly_price),
            "currency": plan.currency,
            "max_branches": plan.max_branches,
            "max_users": plan.max_users,
            "max_products": plan.max_products,
            "is_active": plan.is_active,
        }
        for plan in rows
    ]


@router.post("/plans", status_code=status.HTTP_201_CREATED)
def create_plan(payload: PlanIn, admin: PlatformAdminUser, db: DbSession) -> dict:
    plan = SubscriptionPlan(**payload.model_dump())
    db.add(plan)
    db.flush()
    return {"id": str(plan.id), "code": plan.code}


class FeatureFlagIn(BaseModel):
    key: str = Field(min_length=2, max_length=64)
    enabled: bool
    tenant_id: uuid.UUID | None = None
    description: str | None = None


@router.put("/feature-flags")
def set_feature_flag(payload: FeatureFlagIn, admin: PlatformAdminUser, db: DbSession) -> dict:
    flag = db.execute(
        select(FeatureFlag).where(
            FeatureFlag.key == payload.key, FeatureFlag.tenant_id == payload.tenant_id
        )
    ).scalar_one_or_none()
    if flag is None:
        flag = FeatureFlag(key=payload.key, tenant_id=payload.tenant_id)
        db.add(flag)
    flag.enabled = payload.enabled
    flag.description = payload.description
    db.flush()
    return {"key": flag.key, "enabled": flag.enabled, "tenant_id": str(flag.tenant_id) if flag.tenant_id else None}


class SupportAccessIn(BaseModel):
    tenant_id: uuid.UUID
    reason: str = Field(min_length=10, max_length=500)
    minutes: int = Field(SUPPORT_TOKEN_MINUTES, ge=5, le=480)


@router.post("/support-access")
def grant_support_access(
    payload: SupportAccessIn, admin: PlatformAdminUser, db: DbSession
) -> dict:
    """Issue a short-lived, audited, read-scoped token for one business.

    The grant is recorded before the token is returned, so support access is
    always explained and always traceable (PRD 5.2).
    """
    tenant = db.get(Tenant, payload.tenant_id)
    if tenant is None:
        raise NotFoundError("Business not found")

    membership = db.execute(
        select(TenantMembership).where(TenantMembership.tenant_id == tenant.id)
    ).scalars().first()
    if membership is None:
        raise NotFoundError("This business has no users to act on behalf of")

    record_audit(
        db,
        action=AuditAction.PLATFORM_SUPPORT_ACCESS,
        tenant_id=tenant.id,
        actor_platform_admin_id=admin.id,
        actor_label=admin.email,
        entity_type="tenant",
        entity_id=tenant.id,
        summary=f"Support access granted for {payload.minutes} minutes",
        payload={"reason": payload.reason},
    )
    db.flush()

    token = create_access_token(
        subject=membership.user_id,
        tenant_id=tenant.id,
        expires_minutes=payload.minutes,
        extra_claims={"support": True, "granted_by": str(admin.id)},
    )
    return {
        "access_token": token,
        "tenant_id": str(tenant.id),
        "expires_in_minutes": payload.minutes,
        "notice": "This access is time-bound and recorded in the business's audit log.",
    }


@router.get("/audit-events")
def audit_events(
    admin: PlatformAdminUser,
    db: DbSession,
    tenant_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    if tenant_id is not None:
        stmt = stmt.where(AuditEvent.tenant_id == tenant_id)
    return [
        {
            "id": str(event.id),
            "created_at": event.created_at.isoformat(),
            "tenant_id": str(event.tenant_id) if event.tenant_id else None,
            "action": event.action,
            "summary": event.summary,
            "actor_label": event.actor_label,
        }
        for event in db.execute(stmt).scalars()
    ]


@router.post("/jobs/run-daily")
def run_daily_jobs(admin: PlatformAdminUser, db: DbSession) -> dict:
    """Trigger the scheduled maintenance the worker normally runs."""
    from app.services.notifications import run_due_reminders, run_low_stock_alerts

    reminders = run_due_reminders(db)
    low_stock = run_low_stock_alerts(db)
    expired = subscription_service.expire_lapsed_trials(db)
    warned = subscription_service.warn_expiring_trials(db)
    return {
        "reminders": {
            "considered": reminders.considered,
            "delivered": reminders.delivered,
            "skipped_settled": reminders.skipped_settled,
            "failed": reminders.failed,
        },
        "low_stock_alerts": low_stock.alerts_created,
        "trials_expired": len(expired),
        "trials_warned": warned,
    }
