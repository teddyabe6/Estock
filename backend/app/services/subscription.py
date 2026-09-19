"""Trial and subscription state (PRD 17).

A lapsed trial makes the account read-only.  Nothing is deleted, altered or
silently changed because a trial expired.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, record_audit
from app.core.errors import NotFoundError
from app.models.platform import (
    Subscription,
    SubscriptionStatus,
    Tenant,
    TenantStatus,
)
from app.models.system import Notification, NotificationKind

#: Days before expiry at which the business is warned.
EXPIRY_WARNING_DAYS = (7, 3, 1)


@dataclass(slots=True)
class SubscriptionState:
    status: TenantStatus
    subscription_status: SubscriptionStatus | None
    trial_ends_on: date | None
    days_remaining: int | None
    is_read_only: bool
    message: str | None = None

    def as_dict(self) -> dict:
        return {
            "tenant_status": str(self.status),
            "subscription_status": (
                str(self.subscription_status) if self.subscription_status else None
            ),
            "trial_ends_on": self.trial_ends_on.isoformat() if self.trial_ends_on else None,
            "days_remaining": self.days_remaining,
            "read_only": self.is_read_only,
            "message": self.message,
        }


def describe(db: Session, tenant: Tenant, *, today: date | None = None) -> SubscriptionState:
    today = today or date.today()
    subscription = db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant.id)
    ).scalar_one_or_none()

    ends_on = subscription.trial_ends_on if subscription else None
    days = (ends_on - today).days if ends_on else None
    message = None
    if tenant.status == TenantStatus.RESTRICTED:
        message = (
            "Your trial has ended. Your data is safe and still visible; "
            "subscribe to record new sales and stock again."
        )
    elif days is not None and 0 <= days <= 7:
        message = f"Your trial ends in {days} day(s)."

    return SubscriptionState(
        status=tenant.status,
        subscription_status=subscription.status if subscription else None,
        trial_ends_on=ends_on,
        days_remaining=days,
        is_read_only=tenant.is_read_only,
        message=message,
    )


def expire_lapsed_trials(db: Session, *, today: date | None = None) -> list[uuid.UUID]:
    """Apply the restricted state to businesses whose trial has ended.

    Data is retained; only new posting is blocked (PRD 17).
    """
    today = today or date.today()
    expired: list[uuid.UUID] = []

    rows = db.execute(
        select(Subscription, Tenant)
        .join(Tenant, Tenant.id == Subscription.tenant_id)
        .where(
            Subscription.status == SubscriptionStatus.TRIALING,
            Subscription.trial_ends_on.is_not(None),
            Subscription.trial_ends_on < today,
        )
    ).all()

    for subscription, tenant in rows:
        subscription.status = SubscriptionStatus.EXPIRED
        tenant.status = TenantStatus.RESTRICTED
        expired.append(tenant.id)
        record_audit(
            db,
            action=AuditAction.SUBSCRIPTION_CHANGED,
            tenant_id=tenant.id,
            actor_label="system",
            entity_type="subscription",
            entity_id=subscription.id,
            summary="Trial expired; account set to read-only. No data was deleted.",
        )
        _notify_owners(
            db,
            tenant,
            title="Your trial has ended",
            body=(
                "Your business data is safe and still visible. Subscribe to record "
                "new sales, stock and credit again."
            ),
        )
    db.flush()
    return expired


def warn_expiring_trials(db: Session, *, today: date | None = None) -> int:
    """Warn businesses whose trial ends soon (PRD 17)."""
    today = today or date.today()
    warned = 0
    rows = db.execute(
        select(Subscription, Tenant)
        .join(Tenant, Tenant.id == Subscription.tenant_id)
        .where(
            Subscription.status == SubscriptionStatus.TRIALING,
            Subscription.trial_ends_on.is_not(None),
        )
    ).all()

    for subscription, tenant in rows:
        days = (subscription.trial_ends_on - today).days
        if days not in EXPIRY_WARNING_DAYS:
            continue
        _notify_owners(
            db,
            tenant,
            title=f"Your trial ends in {days} day(s)",
            body="Subscribe to keep recording sales, stock and credit without interruption.",
        )
        warned += 1
    db.flush()
    return warned


def _notify_owners(db: Session, tenant: Tenant, *, title: str, body: str) -> None:
    from app.core.permissions import Permission
    from app.services.notifications import recipients_for

    for membership in recipients_for(db, tenant.id, Permission.BUSINESS_MANAGE):
        db.add(
            Notification(
                tenant_id=tenant.id,
                user_id=membership.user_id,
                kind=NotificationKind.TRIAL_EXPIRY,
                title=title,
                body=body,
                link="/settings/subscription",
            )
        )


def set_tenant_status(
    db: Session,
    tenant_id: uuid.UUID,
    status: TenantStatus,
    *,
    admin_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> Tenant:
    """Platform-admin control over tenant access (PRD 5.2, 17)."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFoundError("Business not found")
    previous = tenant.status
    tenant.status = status
    record_audit(
        db,
        action=AuditAction.TENANT_STATUS_CHANGED,
        tenant_id=tenant.id,
        actor_platform_admin_id=admin_id,
        actor_label="platform_admin",
        entity_type="tenant",
        entity_id=tenant.id,
        summary=f"Status {previous} → {status}",
        payload={"reason": reason},
    )
    db.flush()
    return tenant
