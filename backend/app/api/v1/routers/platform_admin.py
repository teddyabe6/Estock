"""Platform administration (PRD 5.2, 17).

A separate identity and permission boundary from tenant users.  There is no
hidden impersonation: support access to a tenant is explicit, time-bound and
audited.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.core.audit import AuditAction, record_audit
from app.core.config import settings
from app.core.db import utcnow
from app.core.deps import DbSession, PlatformAdminUser, client_ip, login_limiter
from app.core.errors import AuthenticationError, NotFoundError, ValidationError
from app.core.security import create_access_token, verify_password
from app.models.access import MembershipStatus, TenantMembership
from app.models.catalogue import Product
from app.models.platform import (
    AuditEvent,
    FeatureFlag,
    PlatformAdmin,
    Subscription,
    SubscriptionInvoice,
    SubscriptionInvoiceStatus,
    SubscriptionPlan,
    Tenant,
    TenantStatus,
)
from app.models.sales import PaymentMethod, Sale
from app.services import billing, platform_settings
from app.services import subscription as subscription_service

router = APIRouter(prefix="/platform", tags=["platform admin"])

#: Support access grants are short-lived by design (PRD 5.2).
SUPPORT_TOKEN_MINUTES = 60


class AdminLogin(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
def login(payload: AdminLogin, db: DbSession, request: Request) -> dict:
    login_limiter.check(client_ip(request), "platform", payload.email.strip().lower())
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


class TenantPlanIn(BaseModel):
    plan_id: uuid.UUID
    reason: str | None = None


@router.patch("/tenants/{tenant_id}/plan")
def set_tenant_plan(
    tenant_id: uuid.UUID, payload: TenantPlanIn, admin: PlatformAdminUser, db: DbSession
) -> dict:
    """Move a business onto a plan.

    This is what gives it a price to be billed and ceilings to be held to.
    Changing plan never takes data away: a business pushed over a ceiling by a
    smaller plan keeps everything it has and is only refused the next addition
    (``services/subscription.check_limit``).
    """
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFoundError("Business not found")
    plan = db.get(SubscriptionPlan, payload.plan_id)
    if plan is None:
        raise NotFoundError("Plan not found")

    subscription = db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if subscription is None:
        subscription = Subscription(tenant_id=tenant_id)
        db.add(subscription)
    previous = subscription.plan_id
    subscription.plan_id = plan.id

    record_audit(
        db,
        action=AuditAction.SUBSCRIPTION_CHANGED,
        tenant_id=tenant_id,
        actor_platform_admin_id=admin.id,
        actor_label=admin.email,
        entity_type="subscription",
        entity_id=subscription.id,
        summary=f"Plan set to {plan.code} ({plan.monthly_price} {plan.currency})",
        payload={"reason": payload.reason, "previous_plan_id": str(previous) if previous else None},
    )
    db.flush()
    return {
        "tenant_id": str(tenant_id),
        "plan": {
            "id": str(plan.id),
            "code": plan.code,
            "name": plan.name,
            "monthly_price": str(plan.monthly_price),
            "currency": plan.currency,
        },
        "limits": [
            limit.as_dict() for limit in subscription_service.limits(db, tenant_id)
        ],
    }


class FeatureFlagIn(BaseModel):
    """A switch to turn, named from the ones the system actually reads."""

    key: str = Field(min_length=2, max_length=64)
    enabled: bool
    #: Set for one business only; left out, it is the platform-wide setting.
    tenant_id: uuid.UUID | None = None
    reason: str | None = None


@router.get("/settings")
def platform_switches(admin: PlatformAdminUser, db: DbSession) -> dict:
    """The switches the platform owner controls, and where each one stands.

    Only switches something enforces are listed.  A flag nothing reads is
    worse than no flag, because it looks like control and is not.
    """
    return {"settings": platform_settings.describe(db)}


@router.put("/settings")
def set_platform_switch(
    payload: FeatureFlagIn, admin: PlatformAdminUser, db: DbSession
) -> dict:
    """Turn a switch, platform-wide or for one business.

    An unknown key is refused with the list of real ones rather than quietly
    stored, which is how the old endpoint let a typo look like a setting.
    """
    flag = platform_settings.known(payload.key)
    if payload.tenant_id is not None and not flag.per_tenant:
        raise ValidationError(
            f"'{flag.key}' is a platform-wide switch; it cannot be set for one business."
        )
    if payload.tenant_id is not None and db.get(Tenant, payload.tenant_id) is None:
        raise NotFoundError("Business not found")

    # The effective value before this change, not the column's: a switch that
    # has never been set is at its default, and an audit line reading
    # "None → False" would say it was unset rather than on.
    was = platform_settings.is_enabled(db, payload.key, tenant_id=payload.tenant_id)

    row = db.execute(
        select(FeatureFlag).where(
            FeatureFlag.key == payload.key, FeatureFlag.tenant_id == payload.tenant_id
        )
    ).scalar_one_or_none()
    if row is None:
        row = FeatureFlag(key=payload.key, tenant_id=payload.tenant_id)
        db.add(row)
    row.enabled = payload.enabled
    row.description = flag.description

    record_audit(
        db,
        action=AuditAction.PLATFORM_SETTING_CHANGED,
        tenant_id=payload.tenant_id,
        actor_platform_admin_id=admin.id,
        actor_label=admin.email,
        entity_type="feature_flag",
        entity_id=row.id,
        summary=(
            f"{flag.key}: {'on' if was else 'off'} → "
            f"{'on' if payload.enabled else 'off'}"
        ),
        payload={"reason": payload.reason, "scope": "tenant" if payload.tenant_id else "platform"},
    )
    db.flush()
    return {
        "key": row.key,
        "enabled": row.enabled,
        "tenant_id": str(row.tenant_id) if row.tenant_id else None,
        "description": flag.description,
    }


class SupportAccessIn(BaseModel):
    tenant_id: uuid.UUID
    reason: str = Field(min_length=10, max_length=500)
    minutes: int = Field(SUPPORT_TOKEN_MINUTES, ge=5, le=480)


@router.post("/support-access")
def grant_support_access(
    payload: SupportAccessIn, admin: PlatformAdminUser, db: DbSession
) -> dict:
    """Issue a short-lived, audited, read-only token for one business.

    The token carries a ``support`` claim: the API strips every permission
    that changes anything, refuses posting routes outright, and pins the
    session to this one business.  The grant is recorded before the token is
    returned, so support access is always explained and always traceable
    (PRD 5.2).
    """
    tenant = db.get(Tenant, payload.tenant_id)
    if tenant is None:
        raise NotFoundError("Business not found")

    # Look through the owner's eyes where possible: the widest *view* of the
    # business, still with nothing writable.
    memberships = db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant.id,
            TenantMembership.status == MembershipStatus.ACTIVE,
        )
    ).scalars().all()
    membership = next((m for m in memberships if m.role.is_owner_role), None) or (
        memberships[0] if memberships else None
    )
    if membership is None:
        raise NotFoundError("This business has no active users to act on behalf of")

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
        "notice": (
            "This access is read-only, time-bound and recorded in the business's audit log."
        ),
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
    # Bill before lapsing, so a shop is asked for the next period while it
    # still has service rather than after it is cut off.
    raised = billing.run_billing_cycle(db)
    lapsed = billing.expire_lapsed_subscriptions(db)
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
        "invoices_raised": len(raised.raised),
        "subscriptions_lapsed": len(lapsed),
    }


# --------------------------------------------------------------------------- #
# Billing: invoices and payments
# --------------------------------------------------------------------------- #


class InvoiceIn(BaseModel):
    """Charge one shop for one period.

    Everything but the business is optional: left alone, the period follows on
    from whatever the shop has already paid for and the amount comes from its
    plan.  All of it can be set, because a platform owner negotiates.
    """

    tenant_id: uuid.UUID
    period_start: date | None = None
    period_end: date | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    due_on: date | None = None
    terms_days: int = Field(billing.DEFAULT_TERMS_DAYS, ge=0, le=365)
    note: str | None = None
    #: False raises it as a draft: recorded, editable, not yet owed.
    issue: bool = True


@router.get("/invoices")
def list_invoices(
    admin: PlatformAdminUser,
    db: DbSession,
    tenant_id: uuid.UUID | None = None,
    status_filter: SubscriptionInvoiceStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """Every shop's invoices, or one shop's, filterable by derived status."""
    rows, total = billing.list_invoices(
        db, tenant_id=tenant_id, status=status_filter, limit=limit, offset=offset
    )
    names = _tenant_names(db, [row.invoice.tenant_id for row in rows])
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {**row.as_dict(), "tenant_name": names.get(row.invoice.tenant_id)}
            for row in rows
        ],
    }


@router.post("/invoices", status_code=status.HTTP_201_CREATED)
def raise_invoice(payload: InvoiceIn, admin: PlatformAdminUser, db: DbSession) -> dict:
    invoice = billing.raise_invoice(
        db,
        payload.tenant_id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        amount=payload.amount,
        due_on=payload.due_on,
        terms_days=payload.terms_days,
        note=payload.note,
        issue=payload.issue,
        admin_id=admin.id,
        actor_label=admin.email,
    )
    return billing.invoice_as_dict(invoice)


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: uuid.UUID, admin: PlatformAdminUser, db: DbSession) -> dict:
    invoice = db.get(SubscriptionInvoice, invoice_id)
    if invoice is None:
        raise NotFoundError("Invoice not found")
    return billing.invoice_as_dict(invoice)


@router.post("/invoices/{invoice_id}/issue")
def issue_invoice(invoice_id: uuid.UUID, admin: PlatformAdminUser, db: DbSession) -> dict:
    """Turn a draft into something the shop owes."""
    invoice = billing.issue_invoice(
        db, invoice_id, admin_id=admin.id, actor_label=admin.email
    )
    return billing.invoice_as_dict(invoice)


class VoidInvoiceIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/invoices/{invoice_id}/void")
def void_invoice(
    invoice_id: uuid.UUID, payload: VoidInvoiceIn, admin: PlatformAdminUser, db: DbSession
) -> dict:
    """Cancel an invoice raised in error.  It is kept, never deleted."""
    invoice = billing.void_invoice(
        db, invoice_id, reason=payload.reason, admin_id=admin.id, actor_label=admin.email
    )
    return billing.invoice_as_dict(invoice)


class SubscriptionPaymentIn(BaseModel):
    amount: Decimal = Field(gt=0)
    method: PaymentMethod
    paid_on: date | None = None
    #: The telebirr transaction number, the bank slip, the deposit reference.
    reference: str | None = Field(default=None, max_length=120)
    note: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=160)


@router.post("/invoices/{invoice_id}/payments", status_code=status.HTTP_201_CREATED)
def record_subscription_payment(
    invoice_id: uuid.UUID,
    payload: SubscriptionPaymentIn,
    admin: PlatformAdminUser,
    db: DbSession,
) -> dict:
    """Record money received, and renew the service if it settles the invoice."""
    result = billing.record_payment(
        db,
        invoice_id,
        amount=payload.amount,
        method=payload.method,
        paid_on=payload.paid_on,
        reference=payload.reference,
        note=payload.note,
        idempotency_key=payload.idempotency_key,
        admin_id=admin.id,
        actor_label=admin.email,
    )
    return {
        "payment": billing.payment_as_dict(result.payment),
        "invoice": billing.invoice_as_dict(result.invoice),
        "renewed": result.renewed,
        "tenant_status": str(result.tenant_status) if result.tenant_status else None,
        "warnings": result.warnings,
    }


class ReversePaymentIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/payments/{payment_id}/reverse")
def reverse_subscription_payment(
    payment_id: uuid.UUID,
    payload: ReversePaymentIn,
    admin: PlatformAdminUser,
    db: DbSession,
) -> dict:
    """Undo a payment recorded in error, keeping the original row."""
    payment = billing.reverse_payment(
        db, payment_id, reason=payload.reason, admin_id=admin.id, actor_label=admin.email
    )
    return {
        "payment": billing.payment_as_dict(payment),
        "invoice": billing.invoice_as_dict(payment.invoice) if payment.invoice else None,
    }


@router.get("/billing/summary")
def billing_summary(admin: PlatformAdminUser, db: DbSession) -> dict:
    """What the platform has billed, taken and is owed, across every shop."""
    return billing.billing_summary(db).as_dict()


@router.get("/tenants/{tenant_id}/billing")
def tenant_billing(
    tenant_id: uuid.UUID,
    admin: PlatformAdminUser,
    db: DbSession,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """One shop's billing history, and what it currently owes."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFoundError("Business not found")
    return _tenant_billing_payload(db, tenant, limit=limit, offset=offset)


@router.post("/billing/run")
def run_billing(admin: PlatformAdminUser, db: DbSession) -> dict:
    """Raise the next invoice for every shop whose period is nearly up.

    Safe to run twice: a shop already billed for its next period is skipped.
    """
    return billing.run_billing_cycle(db).as_dict()


def _tenant_names(db: DbSession, tenant_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Named once for the whole page rather than once per row."""
    if not tenant_ids:
        return {}
    rows = db.execute(select(Tenant).where(Tenant.id.in_(set(tenant_ids)))).scalars()
    return {tenant.id: tenant.name for tenant in rows}


def _tenant_billing_payload(db, tenant: Tenant, *, limit: int, offset: int) -> dict:
    # One shop's own screen: show what it actually paid, and when.
    rows, total = billing.invoices_for_tenant(
        db, tenant.id, limit=limit, offset=offset, with_payments=True
    )
    subscription = db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant.id)
    ).scalar_one_or_none()
    owing = [
        billing.balance_due(row.invoice, paid=row.paid)
        for row in rows
        if row.invoice.issued_at
        and not row.invoice.voided_at
        and billing.balance_due(row.invoice, paid=row.paid) > 0
    ]
    plan = (
        db.get(SubscriptionPlan, subscription.plan_id)
        if subscription and subscription.plan_id
        else None
    )
    return {
        "tenant_id": str(tenant.id),
        "tenant_name": tenant.name,
        "tenant_status": str(tenant.status),
        "currency": tenant.currency,
        # What it is on now, so the screen can say so rather than offering a
        # change against an unknown starting point.
        "plan": (
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
            if plan
            else None
        ),
        "subscription_status": str(subscription.status) if subscription else None,
        "trial_ends_on": (
            subscription.trial_ends_on.isoformat()
            if subscription and subscription.trial_ends_on
            else None
        ),
        # So one shop's screen does not have to page through every shop to
        # show three numbers about this one.
        "usage": {
            "users": db.execute(
                select(func.count())
                .select_from(TenantMembership)
                .where(TenantMembership.tenant_id == tenant.id)
            ).scalar_one(),
            "products": db.execute(
                select(func.count())
                .select_from(Product)
                .where(Product.tenant_id == tenant.id)
            ).scalar_one(),
            "sales": db.execute(
                select(func.count()).select_from(Sale).where(Sale.tenant_id == tenant.id)
            ).scalar_one(),
        },
        "paid_until": (
            subscription.current_period_ends_on.isoformat()
            if subscription and subscription.current_period_ends_on
            else None
        ),
        "balance_due": str(sum(owing, Decimal("0.00"))),
        "unpaid_count": len(owing),
        "total": total,
        "limit": limit,
        "offset": offset,
        "invoices": [row.as_dict(include_payments=True) for row in rows],
    }
