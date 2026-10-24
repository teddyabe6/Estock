"""What a shop was charged for the software, and what it paid (PRD 17).

A subscription says which plan a shop is on and when its period ends.  That is
enough to decide whether to let it in, and not enough to run the business:
"which shops have paid, which owe me, and how much is overdue" has no answer
without a record of invoices and payments.  This module is that record.

Three rules shape it, and each one is a decision rather than an accident:

* **Nothing about the money is cached.**  What an invoice has been paid, what
  it still owes and where it stands are all summed from its payment rows on
  read.  A shop gets one invoice a month, so there is nothing to optimise, and
  a derived figure cannot disagree with the rows it came from.  The same
  reasoning as the derived credit status.
* **A correction keeps the original.**  A payment recorded in error is
  reversed, not deleted, and an invoice raised in error is voided, not
  removed.  What the platform owner recorded, and then corrected, stays
  readable (PRD 11.6, 20).
* **Billing decides access, but only in one direction.**  Paying in full can
  bring a shop back from read-only; it can never lift a suspension, because a
  suspension is a deliberate decision about conduct and not a bill.  Letting
  money undo it would make the platform's one real sanction purchasable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, raiseload, selectinload

from app.core.audit import AuditAction, record_audit
from app.core.clock import local_today
from app.core.db import utcnow
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.platform import (
    Subscription,
    SubscriptionInvoice,
    SubscriptionInvoiceStatus,
    SubscriptionPayment,
    SubscriptionPlan,
    SubscriptionStatus,
    Tenant,
    TenantStatus,
)
from app.models.sales import PaymentMethod
from app.services.numbering import next_number
from app.services.pricing import quantize_money

ZERO = Decimal("0.00")

#: A shop is billed for a month at a time unless told otherwise.
DEFAULT_PERIOD_DAYS = 30
#: How long a shop has to pay before an invoice counts as overdue.
DEFAULT_TERMS_DAYS = 14
#: How far ahead the billing run raises the next invoice, so a shop is asked
#: before its period runs out rather than after.
RAISE_AHEAD_DAYS = 7

#: Settling a software subscription means money actually arriving.  A credit
#: note offsets a receivable inside a shop's own books and has no meaning
#: between the platform and the shop, so it is refused rather than silently
#: counted as payment.
UNSUPPORTED_METHODS = (PaymentMethod.CREDIT_NOTE,)


# --------------------------------------------------------------------------- #
# Derived figures
# --------------------------------------------------------------------------- #


def amount_paid(invoice: SubscriptionInvoice) -> Decimal:
    """Summed from the payment rows, skipping reversals.  Never cached."""
    return quantize_money(
        sum(
            (Decimal(payment.amount) for payment in invoice.payments if not payment.is_reversed),
            ZERO,
        )
    )


def balance_due(invoice: SubscriptionInvoice, *, paid: Decimal | None = None) -> Decimal:
    """What is still owed.  A void invoice owes nothing.

    As with :func:`derive_status`, ``paid`` may be supplied by a caller that
    totalled the payments in SQL.
    """
    if invoice.voided_at is not None:
        return ZERO
    paid = amount_paid(invoice) if paid is None else paid
    return quantize_money(Decimal(invoice.amount) - paid)


def derive_status(
    invoice: SubscriptionInvoice,
    *,
    today: date | None = None,
    paid: Decimal | None = None,
) -> SubscriptionInvoiceStatus:
    """Status from the payments, the dates and the void state.

    An invoice with no due date is never overdue, however long it has been
    open — the same promise customer credit makes (PRD 11.3).  Overpayment
    still reads as paid rather than inventing a status for it; the overpaid
    amount shows as a negative balance, which is the honest figure.

    ``paid`` lets a caller that has already totalled the payments in SQL pass
    the figure in rather than have it walked off the relationship.  The rules
    stay here either way: a second copy of them in a WHERE clause is exactly
    how a derived status starts disagreeing with itself.
    """
    if invoice.voided_at is not None:
        return SubscriptionInvoiceStatus.VOID
    if invoice.issued_at is None:
        return SubscriptionInvoiceStatus.DRAFT

    paid = amount_paid(invoice) if paid is None else paid
    if paid >= Decimal(invoice.amount):
        return SubscriptionInvoiceStatus.PAID
    if invoice.due_on is not None and invoice.due_on < (today or date.today()):
        return SubscriptionInvoiceStatus.OVERDUE
    if paid > ZERO:
        return SubscriptionInvoiceStatus.PART_PAID
    return SubscriptionInvoiceStatus.OPEN


def is_settled(invoice: SubscriptionInvoice) -> bool:
    """Whether this invoice still stands between the shop and its service."""
    return derive_status(invoice) in (
        SubscriptionInvoiceStatus.PAID,
        SubscriptionInvoiceStatus.VOID,
    )


def invoice_as_dict(
    invoice: SubscriptionInvoice,
    *,
    today: date | None = None,
    include_payments: bool = True,
    paid: Decimal | None = None,
) -> dict:
    """One invoice as the platform screen and the shop's own screen show it.

    ``paid`` lets a list of invoices be priced from one aggregate instead of
    each row reaching back for its own payments.  Leaving it out walks the
    relationship, which is what a single invoice should do.
    """
    paid = amount_paid(invoice) if paid is None else paid
    payload = {
        "id": str(invoice.id),
        "tenant_id": str(invoice.tenant_id),
        "number": invoice.number,
        "status": str(derive_status(invoice, today=today, paid=paid)),
        "plan_code": invoice.plan_code,
        "plan_name": invoice.plan_name,
        "period_start": invoice.period_start.isoformat(),
        "period_end": invoice.period_end.isoformat(),
        "amount": str(quantize_money(Decimal(invoice.amount))),
        "amount_paid": str(paid),
        "balance_due": str(balance_due(invoice, paid=paid)),
        "currency": invoice.currency,
        "due_on": invoice.due_on.isoformat() if invoice.due_on else None,
        "issued_at": invoice.issued_at.isoformat() if invoice.issued_at else None,
        "voided_at": invoice.voided_at.isoformat() if invoice.voided_at else None,
        "void_reason": invoice.void_reason,
        "note": invoice.note,
    }
    if include_payments:
        payload["payments"] = [payment_as_dict(p) for p in _ordered(invoice.payments)]
    return payload


def payment_as_dict(payment: SubscriptionPayment) -> dict:
    return {
        "id": str(payment.id),
        "invoice_id": str(payment.invoice_id),
        "tenant_id": str(payment.tenant_id),
        "method": str(payment.method),
        "amount": str(quantize_money(Decimal(payment.amount))),
        "currency": payment.currency,
        "paid_on": payment.paid_on.isoformat(),
        "reference": payment.reference,
        "note": payment.note,
        "is_reversed": payment.is_reversed,
        "reversed_at": payment.reversed_at.isoformat() if payment.reversed_at else None,
        "reversal_reason": payment.reversal_reason,
    }


def _ordered(payments: list[SubscriptionPayment]) -> list[SubscriptionPayment]:
    """Oldest first, so a shop's payment history reads forwards."""
    return sorted(payments, key=lambda p: (p.paid_on, p.created_at or utcnow()))


# --------------------------------------------------------------------------- #
# Raising invoices
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class InvoicePeriod:
    start: date
    end: date


def next_period(
    subscription: Subscription | None, *, today: date, days: int = DEFAULT_PERIOD_DAYS
) -> InvoicePeriod:
    """The period a shop should be billed for next.

    It follows on from whatever it has already paid for, so periods meet
    end-to-end instead of overlapping or leaving a gap.  A shop with no paid
    period yet — a trial, or a new account — is billed from today.
    """
    paid_until = subscription.current_period_ends_on if subscription else None
    start = max(paid_until + timedelta(days=1), today) if paid_until else today
    return InvoicePeriod(start=start, end=start + timedelta(days=days - 1))


def raise_invoice(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    amount: Decimal | None = None,
    due_on: date | None = None,
    terms_days: int = DEFAULT_TERMS_DAYS,
    note: str | None = None,
    issue: bool = True,
    admin_id: uuid.UUID | None = None,
    actor_label: str | None = None,
    today: date | None = None,
) -> SubscriptionInvoice:
    """Charge one shop for one period.

    The amount defaults to the shop's current plan price, and the period to
    the one following whatever it has already paid for.  Both can be set
    explicitly, because a platform owner negotiates: a discount for a year up
    front, a part month on signup, a goodwill credit.  What is agreed is what
    is recorded.

    ``issue=False`` leaves it a draft — raised, editable, and not yet
    something the shop owes.
    """
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFoundError("Business not found")
    today = today or local_today(tenant.timezone)

    subscription = _subscription_for(db, tenant_id)
    plan = _plan_for(db, subscription)

    if period_start is None or period_end is None:
        period = next_period(subscription, today=today)
        period_start = period_start or period.start
        period_end = period_end or period.end
    if period_end < period_start:
        raise ValidationError("A billing period cannot end before it starts")

    if amount is None:
        if plan is None:
            raise ValidationError(
                "This business is on no plan, so there is no price to charge. "
                "Put it on a plan first, or give the amount explicitly."
            )
        amount = Decimal(plan.monthly_price)
    amount = quantize_money(Decimal(amount))
    if amount < ZERO:
        raise ValidationError("An invoice cannot be for a negative amount")

    clash = db.execute(
        select(SubscriptionInvoice).where(
            SubscriptionInvoice.tenant_id == tenant_id,
            SubscriptionInvoice.period_start == period_start,
            SubscriptionInvoice.period_end == period_end,
            SubscriptionInvoice.voided_at.is_(None),
        )
    ).scalars().first()
    if clash is not None:
        raise ConflictError(
            f"{tenant.name} already has invoice {clash.number} for "
            f"{period_start} to {period_end}.",
            details={"invoice_id": str(clash.id), "number": clash.number},
        )

    invoice = SubscriptionInvoice(
        tenant_id=tenant_id,
        number=next_number(db, SubscriptionInvoice, tenant_id, "subscription_invoice"),
        plan_id=plan.id if plan else None,
        plan_code=plan.code if plan else None,
        plan_name=plan.name if plan else None,
        period_start=period_start,
        period_end=period_end,
        amount=amount,
        currency=(plan.currency if plan else tenant.currency) or "ETB",
        due_on=due_on if due_on is not None else (today + timedelta(days=terms_days)),
        issued_at=utcnow() if issue else None,
        note=note,
        raised_by_admin_id=admin_id,
    )
    db.add(invoice)
    db.flush()

    if issue:
        record_audit(
            db,
            action=AuditAction.SUBSCRIPTION_INVOICE_ISSUED,
            tenant_id=tenant_id,
            actor_platform_admin_id=admin_id,
            actor_label=actor_label or "platform_admin",
            entity_type="subscription_invoice",
            entity_id=invoice.id,
            summary=(
                f"Invoice {invoice.number} for {amount} {invoice.currency} "
                f"covering {period_start} to {period_end}"
            ),
            payload={"due_on": invoice.due_on.isoformat() if invoice.due_on else None},
        )
    db.flush()
    return invoice


def issue_invoice(
    db: Session,
    invoice_id: uuid.UUID,
    *,
    admin_id: uuid.UUID | None = None,
    actor_label: str | None = None,
) -> SubscriptionInvoice:
    """Turn a draft into something the shop owes."""
    invoice = _invoice(db, invoice_id)
    if invoice.voided_at is not None:
        raise ConflictError("This invoice was voided and cannot be issued")
    if invoice.issued_at is not None:
        return invoice
    invoice.issued_at = utcnow()
    record_audit(
        db,
        action=AuditAction.SUBSCRIPTION_INVOICE_ISSUED,
        tenant_id=invoice.tenant_id,
        actor_platform_admin_id=admin_id,
        actor_label=actor_label or "platform_admin",
        entity_type="subscription_invoice",
        entity_id=invoice.id,
        summary=f"Invoice {invoice.number} issued",
    )
    db.flush()
    return invoice


def void_invoice(
    db: Session,
    invoice_id: uuid.UUID,
    *,
    reason: str,
    admin_id: uuid.UUID | None = None,
    actor_label: str | None = None,
) -> SubscriptionInvoice:
    """Cancel an invoice raised in error.  It is kept, never deleted.

    An invoice with money against it is refused: voiding it would make that
    payment belong to nothing.  Reverse the payments first, which leaves both
    corrections on the record and in the right order.
    """
    invoice = _invoice(db, invoice_id)
    if invoice.voided_at is not None:
        return invoice
    if amount_paid(invoice) > ZERO:
        raise ConflictError(
            f"Invoice {invoice.number} has payments against it. Reverse them "
            "first, so the correction is recorded in the order it happened."
        )
    invoice.voided_at = utcnow()
    invoice.void_reason = reason
    record_audit(
        db,
        action=AuditAction.SUBSCRIPTION_INVOICE_VOIDED,
        tenant_id=invoice.tenant_id,
        actor_platform_admin_id=admin_id,
        actor_label=actor_label or "platform_admin",
        entity_type="subscription_invoice",
        entity_id=invoice.id,
        summary=f"Invoice {invoice.number} voided",
        payload={"reason": reason},
    )
    db.flush()
    return invoice


# --------------------------------------------------------------------------- #
# Recording payment
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class PaymentResult:
    payment: SubscriptionPayment
    invoice: SubscriptionInvoice
    #: True when this payment settled the invoice and extended the service.
    renewed: bool
    #: What the shop's access became, when the payment changed it.
    tenant_status: TenantStatus | None = None
    warnings: list[str] = field(default_factory=list)


def record_payment(
    db: Session,
    invoice_id: uuid.UUID,
    *,
    amount: Decimal,
    method: PaymentMethod,
    paid_on: date | None = None,
    reference: str | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
    admin_id: uuid.UUID | None = None,
    actor_label: str | None = None,
    today: date | None = None,
) -> PaymentResult:
    """Record money the platform received, and renew the service if it settles.

    Part payment is allowed: a shop paying half now and half next week is
    ordinary, and refusing it would leave the platform owner recording nothing
    at all until the rest arrived.  Only paying in full renews.
    """
    invoice = _invoice(db, invoice_id)
    if invoice.voided_at is not None:
        raise ConflictError(f"Invoice {invoice.number} was voided")
    if invoice.issued_at is None:
        raise ConflictError(
            f"Invoice {invoice.number} is still a draft. Issue it before "
            "recording payment against it."
        )
    if method in UNSUPPORTED_METHODS:
        raise ValidationError(
            f"'{method}' is not a way of paying the platform. A credit note "
            "settles a balance inside a shop's own books.",
            details={
                "allowed": [
                    str(m) for m in PaymentMethod if m not in UNSUPPORTED_METHODS
                ]
            },
        )

    amount = quantize_money(Decimal(amount))
    if amount <= ZERO:
        raise ValidationError("A payment must be for more than nothing")

    tenant = db.get(Tenant, invoice.tenant_id)
    today = today or local_today(tenant.timezone if tenant else None)
    paid_on = paid_on or today
    if paid_on > today:
        raise ValidationError("A payment cannot be dated in the future")

    if idempotency_key:
        existing = db.execute(
            select(SubscriptionPayment).where(
                SubscriptionPayment.invoice_id == invoice.id,
                SubscriptionPayment.idempotency_key == idempotency_key,
            )
        ).scalars().first()
        if existing is not None:
            # The same submission arriving twice records one payment.
            return PaymentResult(payment=existing, invoice=invoice, renewed=False)

    warnings: list[str] = []
    overpaid = amount - balance_due(invoice)
    if overpaid > ZERO:
        warnings.append(
            f"This is {overpaid} {invoice.currency} more than invoice "
            f"{invoice.number} was for. It is recorded as paid; the extra "
            "shows as a negative balance."
        )

    payment = SubscriptionPayment(
        invoice_id=invoice.id,
        tenant_id=invoice.tenant_id,
        method=method,
        amount=amount,
        currency=invoice.currency,
        paid_on=paid_on,
        reference=reference,
        note=note,
        idempotency_key=idempotency_key,
        recorded_by_admin_id=admin_id,
    )
    # Appended through the relationship: the invoice's payments are eagerly
    # loaded, so attaching by foreign key alone would leave the collection
    # stale and every derived figure below reading the old total.
    invoice.payments.append(payment)
    db.flush()

    record_audit(
        db,
        action=AuditAction.SUBSCRIPTION_PAYMENT_RECORDED,
        tenant_id=invoice.tenant_id,
        actor_platform_admin_id=admin_id,
        actor_label=actor_label or "platform_admin",
        entity_type="subscription_payment",
        entity_id=payment.id,
        summary=(
            f"{amount} {invoice.currency} by {method} against invoice "
            f"{invoice.number}"
        ),
        payload={"reference": reference, "paid_on": paid_on.isoformat()},
    )

    renewed = False
    status_after = None
    if derive_status(invoice, today=today) == SubscriptionInvoiceStatus.PAID:
        renewed, status_after = _renew(
            db, invoice, admin_id=admin_id, actor_label=actor_label
        )
    db.flush()
    return PaymentResult(
        payment=payment,
        invoice=invoice,
        renewed=renewed,
        tenant_status=status_after,
        warnings=warnings,
    )


def reverse_payment(
    db: Session,
    payment_id: uuid.UUID,
    *,
    reason: str,
    admin_id: uuid.UUID | None = None,
    actor_label: str | None = None,
) -> SubscriptionPayment:
    """Undo a payment recorded in error, keeping the original row.

    Reversing does not take a shop's access away.  The invoice goes back to
    owing, which is the honest state, but deciding what to do about a shop
    that has stopped paying is the platform owner's call — and the daily lapse
    run makes it on the period's own terms, not on the strength of a
    bookkeeping correction.
    """
    payment = db.get(SubscriptionPayment, payment_id)
    if payment is None:
        raise NotFoundError("Payment not found")
    if payment.is_reversed:
        return payment
    payment.is_reversed = True
    payment.reversed_at = utcnow()
    payment.reversed_by_admin_id = admin_id
    payment.reversal_reason = reason
    record_audit(
        db,
        action=AuditAction.SUBSCRIPTION_PAYMENT_REVERSED,
        tenant_id=payment.tenant_id,
        actor_platform_admin_id=admin_id,
        actor_label=actor_label or "platform_admin",
        entity_type="subscription_payment",
        entity_id=payment.id,
        summary=(
            f"Reversed {payment.amount} {payment.currency} against invoice "
            f"{payment.invoice.number if payment.invoice else ''}".strip()
        ),
        payload={"reason": reason},
    )
    db.flush()
    return payment


# --------------------------------------------------------------------------- #
# Access: renewal and lapse
# --------------------------------------------------------------------------- #


def _renew(
    db: Session,
    invoice: SubscriptionInvoice,
    *,
    admin_id: uuid.UUID | None = None,
    actor_label: str | None = None,
) -> tuple[bool, TenantStatus | None]:
    """Extend the paid-for period, and restore access if billing was what stopped it.

    A suspended shop stays suspended.  Suspension is a decision about conduct,
    and a platform whose sanctions can be paid off has no sanctions.  The
    platform owner lifts it deliberately, through the status endpoint, where it
    is audited as the judgement it is.
    """
    subscription = _subscription_for(db, invoice.tenant_id)
    if subscription is None:
        return False, None

    current = subscription.current_period_ends_on
    if current is None or invoice.period_end > current:
        subscription.current_period_ends_on = invoice.period_end
    subscription.status = SubscriptionStatus.ACTIVE

    tenant = db.get(Tenant, invoice.tenant_id)
    status_after = None
    if tenant is not None and tenant.status in (
        TenantStatus.TRIAL,
        TenantStatus.RESTRICTED,
    ):
        tenant.status = TenantStatus.ACTIVE
        status_after = tenant.status

    record_audit(
        db,
        action=AuditAction.SUBSCRIPTION_RENEWED,
        tenant_id=invoice.tenant_id,
        actor_platform_admin_id=admin_id,
        actor_label=actor_label or "platform_admin",
        entity_type="subscription",
        entity_id=subscription.id,
        summary=(
            f"Invoice {invoice.number} paid in full; service runs to "
            f"{subscription.current_period_ends_on}"
        ),
        payload={
            "tenant_status": str(tenant.status) if tenant else None,
            "suspension_kept": bool(tenant and tenant.status == TenantStatus.SUSPENDED),
        },
    )
    db.flush()
    return True, status_after


def expire_lapsed_subscriptions(db: Session, *, today: date | None = None) -> list[uuid.UUID]:
    """Make a paying shop read-only once the period it paid for has run out.

    Trial expiry already does this for shops that never paid
    (``subscription.expire_lapsed_trials``).  Without the same rule for paid
    subscriptions, a shop that stops paying keeps the service for good, which
    is not a business.

    The promise is identical, and it is the one that matters: the account goes
    read-only, every figure stays visible, and nothing is deleted or altered
    because of a bill (PRD 17).
    """
    lapsed: list[uuid.UUID] = []
    rows = db.execute(
        select(Subscription, Tenant)
        .join(Tenant, Tenant.id == Subscription.tenant_id)
        .where(
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.current_period_ends_on.is_not(None),
            Tenant.status == TenantStatus.ACTIVE,
        )
    ).all()

    for subscription, tenant in rows:
        # The period runs to the end of its last day where the shop is.
        if subscription.current_period_ends_on >= (today or local_today(tenant.timezone)):
            continue
        subscription.status = SubscriptionStatus.EXPIRED
        tenant.status = TenantStatus.RESTRICTED
        lapsed.append(tenant.id)
        record_audit(
            db,
            action=AuditAction.SUBSCRIPTION_LAPSED,
            tenant_id=tenant.id,
            actor_label="system",
            entity_type="subscription",
            entity_id=subscription.id,
            summary=(
                f"Paid period ended {subscription.current_period_ends_on}; "
                "account set to read-only. No data was deleted."
            ),
        )
        _notify_lapse(db, tenant)
    db.flush()
    return lapsed


def _notify_lapse(db: Session, tenant: Tenant) -> None:
    """Tell the shop's owners, making the same promise trial expiry makes."""
    from app.models.system import NotificationKind
    from app.services.subscription import notify_owners

    notify_owners(
        db,
        tenant,
        title="Your subscription has ended",
        body=(
            "Your business data is safe and still visible. Pay the latest "
            "invoice to record new sales, stock and credit again."
        ),
        kind=NotificationKind.SUBSCRIPTION_EXPIRY,
    )


# --------------------------------------------------------------------------- #
# Reading: one shop, and the platform's own books
# --------------------------------------------------------------------------- #


def _paid_per_invoice():
    """Each invoice's non-reversed payments, totalled in SQL.

    Used wherever a page of invoices needs its money without loading every
    payment row behind them.
    """
    return (
        select(
            SubscriptionPayment.invoice_id.label("invoice_id"),
            func.coalesce(func.sum(SubscriptionPayment.amount), 0).label("paid"),
        )
        .where(SubscriptionPayment.is_reversed.is_(False))
        .group_by(SubscriptionPayment.invoice_id)
        .subquery()
    )


def invoices_for_tenant(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
    with_payments: bool = False,
) -> tuple[list[InvoiceRow], int]:
    """One shop's invoices, newest period first, each with what it is paid.

    ``with_payments`` loads the payment rows behind each one, for a screen that
    shows a shop what it actually paid and when.  It is bounded by ``limit``,
    unlike the platform-wide list, which is why it is offered here.
    """
    paid = _paid_per_invoice()
    total = db.execute(
        select(func.count())
        .select_from(SubscriptionInvoice)
        .where(SubscriptionInvoice.tenant_id == tenant_id)
    ).scalar_one()
    rows = db.execute(
        select(SubscriptionInvoice, func.coalesce(paid.c.paid, 0))
        .outerjoin(paid, paid.c.invoice_id == SubscriptionInvoice.id)
        .options(_payments_option(with_payments))
        .where(SubscriptionInvoice.tenant_id == tenant_id)
        .order_by(SubscriptionInvoice.period_start.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [_row(invoice, total_paid) for invoice, total_paid in rows], int(total or 0)


@dataclass(slots=True)
class InvoiceRow:
    """An invoice and what it has been paid, totalled alongside it.

    A page of invoices needs each one's money to show a status and a balance.
    Carrying the figure next to the invoice means one aggregate prices the
    whole page, instead of every row reaching back through its payments
    relationship — which, being ``selectin``, would pull every payment row of
    every invoice into memory to print fifty lines.
    """

    invoice: SubscriptionInvoice
    paid: Decimal

    def as_dict(self, *, today: date | None = None, include_payments: bool = False) -> dict:
        """``include_payments`` needs the row to have come from a query that
        asked for them (``with_payments=True``); otherwise reaching for them
        raises rather than quietly reporting none."""
        return invoice_as_dict(
            self.invoice,
            today=today,
            include_payments=include_payments,
            paid=self.paid,
        )


def _payments_option(with_payments: bool):
    """Load the payment rows, or make touching them an error.

    A list priced from the aggregate has no need of them, and ``raiseload``
    turns a caller that reaches for them anyway into a loud failure instead of
    an invoice that silently reports no payments.
    """
    return (
        selectinload(SubscriptionInvoice.payments)
        if with_payments
        else raiseload(SubscriptionInvoice.payments)
    )


def list_invoices(
    db: Session,
    *,
    tenant_id: uuid.UUID | None = None,
    status: SubscriptionInvoiceStatus | None = None,
    limit: int = 50,
    offset: int = 0,
    today: date | None = None,
    with_payments: bool = False,
) -> tuple[list[InvoiceRow], int]:
    """The platform's invoice list, newest first, with each invoice's money.

    Filtering by status runs in Python, because status is derived and the rules
    live in :func:`derive_status` and nowhere else — a second copy of them in a
    WHERE clause is how a derived status starts disagreeing with itself.  The
    money does not run in Python: one aggregate totals the payments, so neither
    the filter nor the output reaches through the payments relationship.
    """
    paid = _paid_per_invoice()
    stmt = (
        select(SubscriptionInvoice, func.coalesce(paid.c.paid, 0))
        .outerjoin(paid, paid.c.invoice_id == SubscriptionInvoice.id)
        .options(_payments_option(with_payments))
        .order_by(SubscriptionInvoice.created_at.desc())
    )
    if tenant_id is not None:
        stmt = stmt.where(SubscriptionInvoice.tenant_id == tenant_id)

    if status is None:
        counted = select(func.count()).select_from(
            select(SubscriptionInvoice.id)
            .where(*([SubscriptionInvoice.tenant_id == tenant_id] if tenant_id else []))
            .subquery()
        )
        total = db.execute(counted).scalar_one()
        rows = db.execute(stmt.limit(limit).offset(offset)).all()
        return [_row(invoice, total_paid) for invoice, total_paid in rows], int(total or 0)

    matching = [
        _row(invoice, total_paid)
        for invoice, total_paid in db.execute(stmt).all()
        if derive_status(invoice, today=today, paid=quantize_money(Decimal(total_paid or 0)))
        == status
    ]
    return matching[offset : offset + limit], len(matching)


def _row(invoice: SubscriptionInvoice, paid_total) -> InvoiceRow:
    return InvoiceRow(invoice=invoice, paid=quantize_money(Decimal(paid_total or 0)))


@dataclass(slots=True)
class BillingSummary:
    """The platform owner's own numbers, across every shop."""

    billed: Decimal
    collected: Decimal
    outstanding: Decimal
    overdue: Decimal
    overdue_count: int
    paying_shops: int
    shops_in_arrears: int
    currency: str = "ETB"

    def as_dict(self) -> dict:
        return {
            "billed": str(self.billed),
            "collected": str(self.collected),
            "outstanding": str(self.outstanding),
            "overdue": str(self.overdue),
            "overdue_count": self.overdue_count,
            "paying_shops": self.paying_shops,
            "shops_in_arrears": self.shops_in_arrears,
            "currency": self.currency,
        }


def billing_summary(db: Session, *, today: date | None = None) -> BillingSummary:
    """What the platform has billed, taken and is owed.

    Void and draft invoices are left out of every total: a cancelled charge was
    never owed and an unissued one is not yet owed, so counting either would
    overstate both what was billed and what is outstanding.

    This is the one figure that is read on every visit to the platform's own
    screen and grows for as long as the platform runs, so it is one query
    returning one row per invoice with its payments already summed — not the
    invoice objects with their payment rows attached, which would pull every
    payment ever recorded into memory to add up a handful of totals.
    """
    today = today or date.today()

    paid_per_invoice = _paid_per_invoice()
    rows = db.execute(
        select(
            SubscriptionInvoice.tenant_id,
            SubscriptionInvoice.amount,
            SubscriptionInvoice.due_on,
            func.coalesce(paid_per_invoice.c.paid, 0),
        )
        .outerjoin(
            paid_per_invoice, paid_per_invoice.c.invoice_id == SubscriptionInvoice.id
        )
        .where(
            SubscriptionInvoice.voided_at.is_(None),
            SubscriptionInvoice.issued_at.is_not(None),
        )
    ).all()

    billed = collected = outstanding = overdue = ZERO
    overdue_count = 0
    paying: set[uuid.UUID] = set()
    arrears: set[uuid.UUID] = set()

    for tenant_id, amount, due_on, paid_raw in rows:
        amount = Decimal(amount)
        paid = quantize_money(Decimal(paid_raw or 0))
        due = quantize_money(amount - paid)
        billed += amount
        collected += paid
        if paid > ZERO:
            paying.add(tenant_id)
        if due > ZERO:
            outstanding += due
            arrears.add(tenant_id)
            # Overdue on the same terms as derive_status: something still
            # owing, and a due date that has passed.  No due date, never late.
            if due_on is not None and due_on < today:
                overdue += due
                overdue_count += 1

    return BillingSummary(
        billed=quantize_money(billed),
        collected=quantize_money(collected),
        outstanding=quantize_money(outstanding),
        overdue=quantize_money(overdue),
        overdue_count=overdue_count,
        paying_shops=len(paying),
        shops_in_arrears=len(arrears),
    )


# --------------------------------------------------------------------------- #
# The billing run
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class BillingRun:
    raised: list[uuid.UUID]
    skipped_no_plan: int
    skipped_already_billed: int

    def as_dict(self) -> dict:
        return {
            "invoices_raised": len(self.raised),
            "invoice_ids": [str(i) for i in self.raised],
            "skipped_no_plan": self.skipped_no_plan,
            "skipped_already_billed": self.skipped_already_billed,
        }


def run_billing_cycle(
    db: Session, *, today: date | None = None, ahead_days: int = RAISE_AHEAD_DAYS
) -> BillingRun:
    """Raise the next invoice for every shop whose period is nearly up.

    This is what makes the thing scale past a handful of shops: the platform
    owner does not hand-write an invoice a month per shop.  It is safe to run
    twice in a day — a shop already billed for its next period is skipped, and
    the unique constraint on (shop, period) is the backstop.

    A shop on no plan is skipped rather than guessed at.  There is no price to
    charge, and inventing one would be worse than raising nothing.
    """
    raised: list[uuid.UUID] = []
    no_plan = already = 0

    rows = db.execute(
        select(Subscription, Tenant)
        .join(Tenant, Tenant.id == Subscription.tenant_id)
        .where(
            Subscription.status.in_(
                [SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING]
            ),
            Tenant.status.in_([TenantStatus.ACTIVE, TenantStatus.TRIAL]),
        )
    ).all()

    for subscription, tenant in rows:
        shop_today = today or local_today(tenant.timezone)
        if subscription.plan_id is None:
            no_plan += 1
            continue

        # Bill a trial as its trial runs out, and a paying shop as its paid
        # period runs out.
        runs_out = (
            subscription.current_period_ends_on
            if subscription.status == SubscriptionStatus.ACTIVE
            else subscription.trial_ends_on
        )
        if runs_out is not None and (runs_out - shop_today).days > ahead_days:
            continue

        period = next_period(subscription, today=shop_today)
        if _has_invoice_covering(db, tenant.id, period):
            already += 1
            continue

        invoice = raise_invoice(
            db,
            tenant.id,
            period_start=period.start,
            period_end=period.end,
            actor_label="system",
            today=shop_today,
        )
        raised.append(invoice.id)

    db.flush()
    return BillingRun(
        raised=raised, skipped_no_plan=no_plan, skipped_already_billed=already
    )


def _has_invoice_covering(db: Session, tenant_id: uuid.UUID, period: InvoicePeriod) -> bool:
    """Whether a live invoice already covers any of this period.

    Overlap rather than an exact match: a shop billed for a fortnight by hand
    should not then be billed for the month that contains it.
    """
    return (
        db.execute(
            select(SubscriptionInvoice.id).where(
                SubscriptionInvoice.tenant_id == tenant_id,
                SubscriptionInvoice.voided_at.is_(None),
                SubscriptionInvoice.period_start <= period.end,
                SubscriptionInvoice.period_end >= period.start,
            )
        ).first()
        is not None
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _invoice(db: Session, invoice_id: uuid.UUID) -> SubscriptionInvoice:
    invoice = db.get(SubscriptionInvoice, invoice_id)
    if invoice is None:
        raise NotFoundError("Invoice not found")
    return invoice


def _subscription_for(db: Session, tenant_id: uuid.UUID) -> Subscription | None:
    return db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    ).scalar_one_or_none()


def _plan_for(db: Session, subscription: Subscription | None) -> SubscriptionPlan | None:
    if subscription is None or subscription.plan_id is None:
        return None
    return db.get(SubscriptionPlan, subscription.plan_id)
