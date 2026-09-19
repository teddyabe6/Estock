"""Credit receivables, payables, payments and internal reminders (PRD 11).

Balances are always ``original_amount - sum(payments)``.  Status is always
derived, never set by hand, so a transaction with a remaining balance can never
be marked paid.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, record_audit
from app.core.db import utcnow
from app.core.errors import ConflictError, ValidationError
from app.core.permissions import Permission
from app.core.tenancy import AuthContext, get_tenant_object, tenant_query
from app.models.contacts import Customer
from app.models.credit import (
    CreditKind,
    CreditStatus,
    CreditTransaction,
    FollowUpActivity,
    FollowUpKind,
    Reminder,
    ReminderChannel,
    ReminderKind,
    ReminderStatus,
)
from app.models.sales import Payment, PaymentDirection, PaymentMethod
from app.services.numbering import next_number

ZERO = Decimal("0.00")

#: Quick due-date choices offered in the UI (PRD 11.3).
DUE_DATE_PRESETS: dict[str, int] = {
    "today": 0,
    "tomorrow": 1,
    "7_days": 7,
    "15_days": 15,
    "30_days": 30,
}


def resolve_due_date(preset: str | None, custom: date | None, *, today: date | None = None) -> date | None:
    """Turn a quick choice or a custom date into a due date.  Optional (PRD 11.3)."""
    if custom is not None:
        return custom
    if not preset:
        return None
    if preset not in DUE_DATE_PRESETS:
        raise ValidationError(
            f"Unknown due-date choice '{preset}'",
            details={"allowed": sorted(DUE_DATE_PRESETS)},
        )
    return (today or date.today()) + timedelta(days=DUE_DATE_PRESETS[preset])


def derive_status(
    transaction: CreditTransaction, *, today: date | None = None
) -> CreditStatus:
    """Status from balance, due date and cancellation state (PRD 11.7).

    A balance with no due date stays outstanding however long it has been open;
    elapsed time alone never makes it overdue (PRD 11.3).
    """
    if transaction.cancelled_at is not None:
        return CreditStatus.CANCELLED
    balance = transaction.balance
    if balance <= ZERO:
        return CreditStatus.PAID
    today = today or date.today()
    if transaction.due_date is not None and transaction.due_date < today:
        return CreditStatus.OVERDUE
    if Decimal(transaction.amount_paid) > ZERO:
        return CreditStatus.PARTIALLY_PAID
    return CreditStatus.OUTSTANDING


def is_overdue(transaction: CreditTransaction, *, today: date | None = None) -> bool:
    """Overdue only once the due date has passed with an amount still unpaid."""
    if transaction.cancelled_at is not None or transaction.due_date is None:
        return False
    return transaction.due_date < (today or date.today()) and transaction.balance > ZERO


def recalculate(db: Session, transaction: CreditTransaction, *, today: date | None = None) -> None:
    """Refresh the cached ``amount_paid`` from the payment ledger, then status."""
    total_paid = db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.credit_transaction_id == transaction.id,
            Payment.is_reversed.is_(False),
        )
    ).scalar_one()
    transaction.amount_paid = Decimal(total_paid or 0)
    transaction.status = derive_status(transaction, today=today)
    transaction.settled_at = (
        utcnow() if transaction.status == CreditStatus.PAID else None
    )


def create_credit_transaction(
    db: Session,
    ctx: AuthContext,
    *,
    kind: CreditKind,
    amount: Decimal,
    branch_id: uuid.UUID | None,
    customer_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    sale_id: uuid.UUID | None = None,
    purchase_id: uuid.UUID | None = None,
    due_date: date | None = None,
    issued_on: date | None = None,
    agreement_note: str | None = None,
) -> CreditTransaction:
    """Open a receivable or payable for the unpaid part of a transaction."""
    amount = Decimal(amount)
    if amount <= ZERO:
        raise ValidationError("A credit transaction needs a positive amount")

    transaction = CreditTransaction(
        tenant_id=ctx.tenant_id,
        reference=next_number(db, CreditTransaction, ctx.tenant_id, "credit", column="reference"),
        kind=kind,
        branch_id=branch_id,
        customer_id=customer_id,
        supplier_id=supplier_id,
        sale_id=sale_id,
        purchase_id=purchase_id,
        original_amount=amount,
        amount_paid=ZERO,
        currency=ctx.tenant.currency,
        issued_on=issued_on or date.today(),
        due_date=due_date,
        agreement_note=agreement_note,
        created_by_id=ctx.user_id,
    )
    transaction.status = derive_status(transaction)
    db.add(transaction)
    db.flush()
    schedule_reminders(db, ctx, transaction)
    return transaction


def record_payment(
    db: Session,
    ctx: AuthContext,
    transaction_id: uuid.UUID,
    *,
    amount: Decimal,
    method: PaymentMethod,
    paid_on: date | None = None,
    reference: str | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
    allow_overpayment: bool = False,
) -> Payment:
    """Record a partial or final payment against a credit transaction.

    Overpayment is refused by default and reported with the exact balance; a
    caller that means it must pass ``allow_overpayment`` explicitly, and only
    with the credit-override permission (PRD 11.6).
    """
    ctx.require(Permission.CREDIT_PAYMENT_RECORD)
    transaction = get_tenant_object(
        db, CreditTransaction, transaction_id, ctx.tenant_id, label="Credit transaction"
    )
    ctx.require_branch(transaction.branch_id)

    amount = Decimal(amount)
    if amount <= ZERO:
        raise ValidationError("Payment amount must be positive")
    if transaction.cancelled_at is not None:
        raise ConflictError("This transaction has been cancelled")

    if idempotency_key:
        existing = db.execute(
            tenant_query(Payment, ctx.tenant_id).where(
                Payment.idempotency_key == idempotency_key
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    balance = transaction.balance
    if amount > balance:
        if not allow_overpayment:
            raise ValidationError(
                f"Payment of {amount} exceeds the outstanding balance of {balance}",
                code="overpayment",
                details={"balance": str(balance), "amount": str(amount)},
            )
        ctx.require(Permission.CREDIT_LIMIT_OVERRIDE)

    payment = Payment(
        tenant_id=ctx.tenant_id,
        direction=(
            PaymentDirection.IN
            if transaction.kind == CreditKind.RECEIVABLE
            else PaymentDirection.OUT
        ),
        method=method,
        amount=amount,
        currency=transaction.currency,
        paid_at=utcnow() if paid_on is None else _as_datetime(paid_on),
        branch_id=transaction.branch_id,
        sale_id=transaction.sale_id,
        purchase_id=transaction.purchase_id,
        credit_transaction_id=transaction.id,
        customer_id=transaction.customer_id,
        supplier_id=transaction.supplier_id,
        reference=reference,
        note=note,
        idempotency_key=idempotency_key,
        created_by_id=ctx.user_id,
    )
    db.add(payment)
    db.flush()

    recalculate(db, transaction)
    _cancel_reminders_if_settled(db, transaction)
    record_audit(
        db,
        action=AuditAction.PAYMENT_RECORDED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="credit_transaction",
        entity_id=transaction.id,
        summary=f"Payment {amount} on {transaction.reference}",
        payload={"payment_id": str(payment.id), "balance_after": str(transaction.balance)},
    )
    db.flush()
    return payment


def reverse_payment(
    db: Session, ctx: AuthContext, payment_id: uuid.UUID, *, reason: str
) -> Payment:
    """Mark a payment reversed.  The row stays; history is never deleted (PRD 11.7)."""
    ctx.require(Permission.CREDIT_PAYMENT_RECORD)
    payment = get_tenant_object(db, Payment, payment_id, ctx.tenant_id, label="Payment")
    if payment.is_reversed:
        raise ConflictError("This payment has already been reversed")
    if not reason:
        raise ValidationError("A reason is required to reverse a payment")

    payment.is_reversed = True
    payment.reversed_at = utcnow()
    payment.reversed_by_id = ctx.user_id
    payment.reversal_reason = reason
    db.flush()

    if payment.credit_transaction_id:
        transaction = db.get(CreditTransaction, payment.credit_transaction_id)
        if transaction is not None:
            recalculate(db, transaction)
            schedule_reminders(db, ctx, transaction)

    record_audit(
        db,
        action=AuditAction.PAYMENT_REVERSED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="payment",
        entity_id=payment.id,
        summary=f"Reversed payment of {payment.amount}",
        payload={"reason": reason},
    )
    db.flush()
    return payment


def change_due_date(
    db: Session,
    ctx: AuthContext,
    transaction_id: uuid.UUID,
    *,
    due_date: date | None,
    note: str | None = None,
) -> CreditTransaction:
    """Change a due date, rescheduling reminders and overdue state (PRD 11.3)."""
    ctx.require(Permission.CREDIT_DUEDATE_CHANGE)
    transaction = get_tenant_object(
        db, CreditTransaction, transaction_id, ctx.tenant_id, label="Credit transaction"
    )
    ctx.require_branch(transaction.branch_id)
    previous = transaction.due_date
    transaction.due_date = due_date
    transaction.status = derive_status(transaction)

    _clear_scheduled_reminders(db, transaction)
    schedule_reminders(db, ctx, transaction)

    record_audit(
        db,
        action=AuditAction.CREDIT_DUE_DATE_CHANGED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="credit_transaction",
        entity_id=transaction.id,
        summary=f"Due date {previous} → {due_date}",
        payload={"note": note},
    )
    db.flush()
    return transaction


def cancel_transaction(
    db: Session, ctx: AuthContext, transaction_id: uuid.UUID, *, reason: str
) -> CreditTransaction:
    """Void a credit balance without deleting its history (PRD 11.7)."""
    ctx.require(Permission.CREDIT_CANCEL)
    transaction = get_tenant_object(
        db, CreditTransaction, transaction_id, ctx.tenant_id, label="Credit transaction"
    )
    if not reason:
        raise ValidationError("A reason is required to cancel a credit transaction")
    if transaction.cancelled_at is not None:
        raise ConflictError("This transaction is already cancelled")

    transaction.cancelled_at = utcnow()
    transaction.cancelled_by_id = ctx.user_id
    transaction.cancel_reason = reason
    transaction.status = CreditStatus.CANCELLED
    _clear_scheduled_reminders(db, transaction)

    record_audit(
        db,
        action=AuditAction.CREDIT_CANCELLED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="credit_transaction",
        entity_id=transaction.id,
        summary=f"Cancelled {transaction.reference}",
        payload={"reason": reason, "balance_at_cancellation": str(transaction.balance)},
    )
    db.flush()
    return transaction


def add_follow_up(
    db: Session,
    ctx: AuthContext,
    transaction_id: uuid.UUID,
    *,
    kind: FollowUpKind,
    note: str | None = None,
    promised_amount: Decimal | None = None,
    promised_date: date | None = None,
    outcome: str | None = None,
) -> FollowUpActivity:
    """Log that someone followed up.  Balances are untouched (PRD 11.6)."""
    ctx.require(Permission.CREDIT_FOLLOWUP)
    transaction = get_tenant_object(
        db, CreditTransaction, transaction_id, ctx.tenant_id, label="Credit transaction"
    )
    ctx.require_branch(transaction.branch_id)
    activity = FollowUpActivity(
        tenant_id=ctx.tenant_id,
        credit_transaction_id=transaction.id,
        kind=kind,
        occurred_at=utcnow(),
        note=note,
        promised_amount=promised_amount,
        promised_date=promised_date,
        outcome=outcome,
        created_by_id=ctx.user_id,
    )
    db.add(activity)
    db.flush()
    return activity


# --------------------------------------------------------------------------- #
# Reminders — internal only.  Nothing here messages a customer (PRD 11.4).
# --------------------------------------------------------------------------- #


def schedule_reminders(
    db: Session,
    ctx: AuthContext,
    transaction: CreditTransaction,
    *,
    channels: tuple[ReminderChannel, ...] = (ReminderChannel.IN_APP, ReminderChannel.EMAIL),
    today: date | None = None,
) -> list[Reminder]:
    """Schedule due-soon, due-today and overdue reminders for staff."""
    if transaction.due_date is None or transaction.cancelled_at is not None:
        return []
    if transaction.balance <= ZERO:
        return []

    today = today or date.today()
    lead_days = ctx.tenant.reminder_lead_days or 3
    wanted: list[tuple[ReminderKind, date]] = [
        (ReminderKind.DUE_SOON, transaction.due_date - timedelta(days=lead_days)),
        (ReminderKind.DUE_TODAY, transaction.due_date),
        (ReminderKind.OVERDUE, transaction.due_date + timedelta(days=1)),
    ]

    existing = {
        (reminder.kind, reminder.channel, reminder.scheduled_for)
        for reminder in transaction.reminders
    }
    created: list[Reminder] = []
    for kind, scheduled_for in wanted:
        if scheduled_for < today and kind != ReminderKind.OVERDUE:
            # Nothing to schedule in the past except the standing overdue notice.
            continue
        for channel in channels:
            key = (kind, channel, scheduled_for)
            if key in existing:
                continue
            reminder = Reminder(
                tenant_id=transaction.tenant_id,
                credit_transaction_id=transaction.id,
                kind=kind,
                channel=channel,
                status=ReminderStatus.SCHEDULED,
                scheduled_for=max(scheduled_for, today),
            )
            # Append through the relationship so the duplicate check above sees
            # reminders added earlier in this same transaction.
            transaction.reminders.append(reminder)
            existing.add((kind, channel, reminder.scheduled_for))
            created.append(reminder)
    db.flush()
    return created


def _clear_scheduled_reminders(db: Session, transaction: CreditTransaction) -> None:
    for reminder in transaction.reminders:
        if reminder.status == ReminderStatus.SCHEDULED:
            reminder.status = ReminderStatus.CANCELLED
    db.flush()


def _cancel_reminders_if_settled(db: Session, transaction: CreditTransaction) -> None:
    if transaction.balance <= ZERO:
        _clear_scheduled_reminders(db, transaction)


def due_reminders(db: Session, *, on: date | None = None) -> list[Reminder]:
    """Reminders that the worker should deliver today or earlier."""
    on = on or date.today()
    return list(
        db.execute(
            select(Reminder).where(
                Reminder.status == ReminderStatus.SCHEDULED,
                Reminder.scheduled_for <= on,
            )
        ).scalars()
    )


# --------------------------------------------------------------------------- #
# Credit limits
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class CreditLimitCheck:
    allowed: bool
    requires_approval: bool
    limit: Decimal | None
    outstanding: Decimal
    projected: Decimal
    message: str | None = None


def customer_outstanding(db: Session, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> Decimal:
    total = db.execute(
        select(
            func.coalesce(
                func.sum(CreditTransaction.original_amount - CreditTransaction.amount_paid), 0
            )
        ).where(
            CreditTransaction.tenant_id == tenant_id,
            CreditTransaction.customer_id == customer_id,
            CreditTransaction.kind == CreditKind.RECEIVABLE,
            CreditTransaction.cancelled_at.is_(None),
        )
    ).scalar_one()
    return Decimal(total or 0)


def check_credit_limit(
    db: Session, ctx: AuthContext, customer_id: uuid.UUID | None, additional_amount: Decimal
) -> CreditLimitCheck:
    """Warn, require approval or block, per the customer's setting (PRD 11.7)."""
    outstanding = (
        customer_outstanding(db, ctx.tenant_id, customer_id) if customer_id else ZERO
    )
    projected = outstanding + Decimal(additional_amount)
    if customer_id is None:
        return CreditLimitCheck(True, False, None, outstanding, projected)

    customer = get_tenant_object(
        db, Customer, customer_id, ctx.tenant_id, label="Customer", required=False
    )
    if customer is None or customer.credit_limit is None:
        return CreditLimitCheck(True, False, None, outstanding, projected)

    limit = Decimal(customer.credit_limit)
    if projected <= limit:
        return CreditLimitCheck(True, False, limit, outstanding, projected)

    behaviour = (customer.credit_limit_behaviour or "warn").lower()
    message = (
        f"{customer.name} would owe {projected}, above the credit limit of {limit}"
    )
    if behaviour == "block":
        return CreditLimitCheck(False, False, limit, outstanding, projected, message)
    if behaviour == "require_approval":
        return CreditLimitCheck(
            ctx.has(Permission.CREDIT_LIMIT_OVERRIDE), True, limit, outstanding, projected, message
        )
    return CreditLimitCheck(True, False, limit, outstanding, projected, message)


def _as_datetime(value: date):
    from datetime import datetime, time

    return datetime.combine(value, time(12, 0), tzinfo=UTC)
