"""In-app and email notifications, and reminder delivery (PRD 9, 11.4, 17).

Reminders here are internal to the business.  Nothing in this module messages a
customer or supplier, and a delivered reminder is never proof that one was
contacted.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import day_start, local_today
from app.core.db import utcnow
from app.core.permissions import Permission
from app.models.access import MembershipStatus, TenantMembership
from app.models.credit import (
    CreditKind,
    CreditTransaction,
    Reminder,
    ReminderChannel,
    ReminderKind,
    ReminderStatus,
)
from app.models.platform import Tenant
from app.models.system import Notification, NotificationKind

logger = logging.getLogger(__name__)


class EmailSender:
    """Email transport seam.

    The default implementation logs instead of sending, so development and CI
    never depend on a provider.  Configure a real transport in deployment
    (PRD open decision 25).
    """

    def send(self, *, to: str, subject: str, body: str) -> bool:
        logger.info("email.not_configured to=%s subject=%s", to, subject)
        return False


_email_sender = EmailSender()


def set_email_sender(sender: EmailSender) -> None:
    global _email_sender
    _email_sender = sender


def send_email(*, to: str, subject: str, body: str) -> bool:
    """Send through whichever transport is configured."""
    return _email_sender.send(to=to, subject=subject, body=body)


def recipients_for(
    db: Session, tenant_id: uuid.UUID, permission: Permission
) -> list[TenantMembership]:
    """Active members holding a permission — who may be told about this."""
    memberships = db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.status == MembershipStatus.ACTIVE,
        )
    ).scalars()
    return [m for m in memberships if permission in m.effective_permissions()]


def already_notified_today(
    db: Session,
    *,
    tenant: Tenant,
    user_id: uuid.UUID,
    kind: NotificationKind,
    title: str | None = None,
) -> bool:
    """Whether this person already got this notice today, in their business's day.

    The worker runs hourly; the daily digests (low stock, trial warnings) must
    not repeat every hour.
    """
    since = day_start(local_today(tenant.timezone), tenant.timezone)
    stmt = select(Notification.id).where(
        Notification.tenant_id == tenant.id,
        Notification.user_id == user_id,
        Notification.kind == kind,
        Notification.created_at >= since,
    )
    if title is not None:
        stmt = stmt.where(Notification.title == title)
    return db.execute(stmt.limit(1)).first() is not None


def notify(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    kind: NotificationKind,
    title: str,
    body: str | None = None,
    link: str | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
) -> Notification:
    notification = Notification(
        tenant_id=tenant_id,
        user_id=user_id,
        kind=kind,
        title=title,
        body=body,
        link=link,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.add(notification)
    return notification


@dataclass(slots=True)
class ReminderRunResult:
    considered: int = 0
    delivered: int = 0
    skipped_settled: int = 0
    failed: int = 0


def _reminder_text(transaction: CreditTransaction, kind: ReminderKind) -> tuple[str, str]:
    who = "customer" if transaction.kind == CreditKind.RECEIVABLE else "supplier"
    direction = "owes you" if transaction.kind == CreditKind.RECEIVABLE else "you owe"
    amount = f"{transaction.balance} {transaction.currency}"
    if kind == ReminderKind.DUE_TODAY:
        headline = f"{transaction.reference} is due today"
    elif kind == ReminderKind.OVERDUE:
        headline = f"{transaction.reference} is overdue"
    else:
        headline = f"{transaction.reference} is due on {transaction.due_date}"
    body = (
        f"{amount} {direction} on this {who} balance. "
        "This is an internal note — no message has been sent to them."
    )
    return headline, body


def run_due_reminders(db: Session, *, on: date | None = None) -> ReminderRunResult:
    """Deliver scheduled reminders to authorised staff (PRD 11.4).

    A reminder falls due on a calendar date in the business's own timezone,
    so "today" is worked out per business rather than from the server clock.
    """
    result = ReminderRunResult()
    # Fetch one day ahead of the server date so a business east of UTC is not
    # kept waiting; the per-business check below decides what is really due.
    horizon = (on or date.today()) + timedelta(days=1)
    reminders = db.execute(
        select(Reminder).where(
            Reminder.status == ReminderStatus.SCHEDULED, Reminder.scheduled_for <= horizon
        )
    ).scalars().all()
    zones: dict[uuid.UUID, str] = {}

    for reminder in reminders:
        if reminder.tenant_id not in zones:
            tenant = db.get(Tenant, reminder.tenant_id)
            zones[reminder.tenant_id] = tenant.timezone if tenant else "UTC"
        due_today = on if on is not None else local_today(zones[reminder.tenant_id])
        if reminder.scheduled_for > due_today:
            continue
        result.considered += 1
        transaction = db.get(CreditTransaction, reminder.credit_transaction_id)
        if transaction is None or transaction.cancelled_at is not None or transaction.balance <= 0:
            reminder.status = ReminderStatus.CANCELLED
            result.skipped_settled += 1
            continue

        title, body = _reminder_text(transaction, reminder.kind)
        # Deep links into the web app (web/src/app/credit, web/src/app/stock).
        link = f"/credit?kind={transaction.kind.value}&open={transaction.id}"
        staff = recipients_for(db, transaction.tenant_id, Permission.CREDIT_VIEW)
        if not staff:
            reminder.status = ReminderStatus.FAILED
            reminder.failure_reason = "No staff member holds the credit:view permission"
            result.failed += 1
            continue

        for membership in staff:
            if reminder.channel == ReminderChannel.IN_APP:
                notify(
                    db,
                    tenant_id=transaction.tenant_id,
                    user_id=membership.user_id,
                    kind=NotificationKind.CREDIT_REMINDER,
                    title=title,
                    body=body,
                    link=link,
                    entity_type="credit_transaction",
                    entity_id=transaction.id,
                )
            elif reminder.channel == ReminderChannel.EMAIL and membership.user.email:
                _email_sender.send(to=membership.user.email, subject=title, body=body)

        reminder.status = ReminderStatus.SENT
        reminder.sent_at = utcnow()
        result.delivered += 1

    db.flush()
    return result


@dataclass(slots=True)
class LowStockRunResult:
    tenants_checked: int = 0
    alerts_created: int = 0


def run_low_stock_alerts(db: Session) -> LowStockRunResult:
    """Notify authorised users about warning, critical and out-of-stock items."""
    from app.services.inventory import low_stock_items

    result = LowStockRunResult()
    tenants = db.execute(select(Tenant)).scalars().all()

    for tenant in tenants:
        result.tenants_checked += 1
        items = low_stock_items(db, tenant.id)
        if not items:
            continue
        urgent = [item for item in items if item.severity in ("out_of_stock", "critical")]
        if not urgent:
            continue
        staff = recipients_for(db, tenant.id, Permission.STOCK_VIEW)
        headline = f"{len(urgent)} product(s) need restocking"
        body = ", ".join(item.name for item in urgent[:5])
        if len(urgent) > 5:
            body += f" and {len(urgent) - 5} more"
        for membership in staff:
            # One digest per person per day, however often the worker runs.
            if already_notified_today(
                db, tenant=tenant, user_id=membership.user_id, kind=NotificationKind.LOW_STOCK
            ):
                continue
            notify(
                db,
                tenant_id=tenant.id,
                user_id=membership.user_id,
                kind=NotificationKind.LOW_STOCK,
                title=headline,
                body=body,
                link="/stock?view=low",
            )
            result.alerts_created += 1
    db.flush()
    return result


def mark_read(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, notification_id: uuid.UUID) -> None:
    notification = db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.tenant_id == tenant_id,
            Notification.user_id == user_id,
        )
    ).scalar_one_or_none()
    if notification is not None and notification.read_at is None:
        notification.read_at = utcnow()
        db.flush()
