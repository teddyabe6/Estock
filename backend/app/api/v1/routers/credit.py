"""Receivables, payables, payments, reminders and follow-up (PRD 11)."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse

from app.api.v1.serializers import credit_out
from app.core.clock import local_today
from app.core.deps import Ctx, DbSession, WritableCtx
from app.core.permissions import Permission
from app.core.tenancy import get_tenant_object, in_branches, tenant_query
from app.models.contacts import Customer, Supplier
from app.models.credit import CreditKind, CreditStatus, CreditTransaction
from app.schemas.common import Page
from app.schemas.operations import (
    CancelCreditIn,
    CreditPaymentIn,
    CreditTransactionOut,
    DueDateChangeIn,
    FollowUpIn,
    FollowUpOut,
    PaymentOut,
    ReversePaymentIn,
)
from app.services import reports as report_service
from app.services.credit import (
    DUE_DATE_PRESETS,
    add_follow_up,
    cancel_transaction,
    change_due_date,
    is_overdue,
    record_payment,
    resolve_due_date,
    reverse_payment,
)
from app.services.storage import escape_for_spreadsheet

router = APIRouter(prefix="/credit", tags=["credit"])

#: Views the credit screens offer (PRD 11.5).
VIEWS = ("all", "due_today", "due_soon", "overdue", "outstanding", "partially_paid", "paid")


def _counterparty_name(db, transaction: CreditTransaction) -> str | None:
    if transaction.customer_id:
        customer = db.get(Customer, transaction.customer_id)
        return customer.name if customer else None
    if transaction.supplier_id:
        supplier = db.get(Supplier, transaction.supplier_id)
        return supplier.name if supplier else None
    return None


def _load(db, ctx, transaction_id: uuid.UUID) -> CreditTransaction:
    """One transaction the caller may see: their tenant, their branch, and
    purchasing data only with purchase:view."""
    ctx.require(Permission.CREDIT_VIEW)
    transaction = get_tenant_object(
        db, CreditTransaction, transaction_id, ctx.tenant_id, label="Credit transaction"
    )
    if transaction.kind == CreditKind.PAYABLE:
        ctx.require(Permission.PURCHASE_VIEW)
    ctx.require_branch(transaction.branch_id)
    return transaction


def _out(db, ctx, transaction: CreditTransaction) -> CreditTransactionOut:
    return credit_out(
        transaction,
        counterparty_name=_counterparty_name(db, transaction),
        tz_name=ctx.tenant.timezone,
    )


@router.get("/summary")
def summary(
    ctx: Ctx, db: DbSession, kind: CreditKind = CreditKind.RECEIVABLE
) -> dict:
    """The dashboard cards: total, due today, due within 7 days, overdue (PRD 11.5)."""
    if kind == CreditKind.PAYABLE:
        ctx.require(Permission.PURCHASE_VIEW)
    return report_service.credit_summary(db, ctx, kind).as_dict()


@router.get("/transactions", response_model=Page[CreditTransactionOut])
def list_transactions(
    ctx: Ctx,
    db: DbSession,
    kind: CreditKind = CreditKind.RECEIVABLE,
    view: str = Query("all", pattern="^(all|due_today|due_soon|overdue|outstanding|partially_paid|paid)$"),
    customer_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[CreditTransactionOut]:
    ctx.require(Permission.CREDIT_VIEW)
    if kind == CreditKind.PAYABLE:
        ctx.require(Permission.PURCHASE_VIEW)

    allowed = ctx.visible_branch_ids(db)
    if branch_id is not None:
        ctx.require_branch(branch_id)
        allowed = [branch_id]

    stmt = tenant_query(CreditTransaction, ctx.tenant_id).where(
        CreditTransaction.kind == kind,
        in_branches(CreditTransaction.branch_id, allowed),
    )
    if customer_id is not None:
        stmt = stmt.where(CreditTransaction.customer_id == customer_id)
    if supplier_id is not None:
        stmt = stmt.where(CreditTransaction.supplier_id == supplier_id)

    today = local_today(ctx.tenant.timezone)
    rows = db.execute(stmt.order_by(CreditTransaction.issued_on.desc())).scalars().all()
    filtered = [t for t in rows if _matches_view(t, view, today)]

    page = filtered[offset : offset + limit]
    return Page(
        items=[
            credit_out(t, counterparty_name=_counterparty_name(db, t), today=today)
            for t in page
        ],
        total=len(filtered),
        limit=limit,
        offset=offset,
    )


@router.get("/transactions/export")
def export_transactions(
    ctx: Ctx,
    db: DbSession,
    kind: CreditKind = CreditKind.RECEIVABLE,
    view: str = Query("outstanding", pattern="^(all|due_today|due_soon|overdue|outstanding|partially_paid|paid)$"),
) -> StreamingResponse:
    """The same list as a spreadsheet, with formula characters neutralised (PRD 15, 20)."""
    ctx.require(Permission.CREDIT_VIEW, Permission.REPORT_CREDIT)
    if kind == CreditKind.PAYABLE:
        ctx.require(Permission.PURCHASE_VIEW)
    allowed = ctx.visible_branch_ids(db)
    today = local_today(ctx.tenant.timezone)
    rows = db.execute(
        tenant_query(CreditTransaction, ctx.tenant_id)
        .where(CreditTransaction.kind == kind, in_branches(CreditTransaction.branch_id, allowed))
        .order_by(CreditTransaction.issued_on.desc())
    ).scalars()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["Reference", "Counterparty", "Issued", "Due", "Total", "Paid", "Balance", "Status", "Currency"]
    )
    for t in rows:
        if not _matches_view(t, view, today):
            continue
        payload = credit_out(t, counterparty_name=_counterparty_name(db, t), today=today)
        writer.writerow(
            [
                escape_for_spreadsheet(t.reference),
                escape_for_spreadsheet(payload.counterparty_name or ""),
                t.issued_on.isoformat(),
                t.due_date.isoformat() if t.due_date else "",
                str(t.original_amount),
                str(t.amount_paid),
                str(t.balance),
                payload.status,
                t.currency,
            ]
        )
    return _csv_response(buffer, f"estock-{kind.value}s-{today.isoformat()}.csv")


def _csv_response(buffer: io.StringIO, filename: str) -> StreamingResponse:
    # A byte-order mark so Excel opens Amharic text as UTF-8.
    content = ("\ufeff" + buffer.getvalue()).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _matches_view(transaction: CreditTransaction, view: str, today: date) -> bool:
    if view == "all":
        return True
    if view == "paid":
        return transaction.status == CreditStatus.PAID
    if transaction.status in (CreditStatus.PAID, CreditStatus.CANCELLED):
        return False
    if view == "overdue":
        return is_overdue(transaction, today=today)
    if view == "due_today":
        return transaction.due_date == today
    if view == "due_soon":
        return (
            transaction.due_date is not None
            and 0 <= (transaction.due_date - today).days <= 7
        )
    if view == "partially_paid":
        return transaction.amount_paid > 0 and transaction.balance > 0
    if view == "outstanding":
        return transaction.balance > 0
    return True


@router.get("/transactions/{transaction_id}", response_model=CreditTransactionOut)
def get_transaction(
    transaction_id: uuid.UUID, ctx: Ctx, db: DbSession
) -> CreditTransactionOut:
    return _out(db, ctx, _load(db, ctx, transaction_id))


@router.get("/transactions/{transaction_id}/payments", response_model=list[PaymentOut])
def list_payments(
    transaction_id: uuid.UUID, ctx: Ctx, db: DbSession
) -> list[PaymentOut]:
    transaction = _load(db, ctx, transaction_id)
    return [
        PaymentOut.model_validate(p)
        for p in sorted(transaction.payments, key=lambda p: p.paid_at, reverse=True)
    ]


@router.post(
    "/transactions/{transaction_id}/payments",
    response_model=CreditTransactionOut,
    status_code=status.HTTP_201_CREATED,
)
def add_payment(
    transaction_id: uuid.UUID, payload: CreditPaymentIn, ctx: WritableCtx, db: DbSession
) -> CreditTransactionOut:
    """Record a partial or final payment (PRD 11.6)."""
    record_payment(
        db,
        ctx,
        transaction_id,
        amount=payload.amount,
        method=payload.method,
        paid_on=payload.paid_on,
        reference=payload.reference,
        note=payload.note,
        idempotency_key=payload.idempotency_key,
        allow_overpayment=payload.allow_overpayment,
    )
    transaction = get_tenant_object(
        db, CreditTransaction, transaction_id, ctx.tenant_id, label="Credit transaction"
    )
    return _out(db, ctx, transaction)


@router.post("/payments/{payment_id}/reverse", response_model=PaymentOut)
def reverse(
    payment_id: uuid.UUID, payload: ReversePaymentIn, ctx: WritableCtx, db: DbSession
) -> PaymentOut:
    """Correct a mistaken payment.  The original row is kept (PRD 11.7)."""
    payment = reverse_payment(db, ctx, payment_id, reason=payload.reason)
    return PaymentOut.model_validate(payment)


@router.patch("/transactions/{transaction_id}/due-date", response_model=CreditTransactionOut)
def set_due_date(
    transaction_id: uuid.UUID, payload: DueDateChangeIn, ctx: WritableCtx, db: DbSession
) -> CreditTransactionOut:
    """Change the due date; reminders and overdue state follow (PRD 11.3)."""
    due_date = resolve_due_date(
        payload.due_date_preset, payload.due_date, today=local_today(ctx.tenant.timezone)
    )
    transaction = change_due_date(
        db, ctx, transaction_id, due_date=due_date, note=payload.note
    )
    return _out(db, ctx, transaction)


@router.post("/transactions/{transaction_id}/cancel", response_model=CreditTransactionOut)
def cancel(
    transaction_id: uuid.UUID, payload: CancelCreditIn, ctx: WritableCtx, db: DbSession
) -> CreditTransactionOut:
    transaction = cancel_transaction(db, ctx, transaction_id, reason=payload.reason)
    return _out(db, ctx, transaction)


@router.get("/transactions/{transaction_id}/activities", response_model=list[FollowUpOut])
def list_activities(
    transaction_id: uuid.UUID, ctx: Ctx, db: DbSession
) -> list[FollowUpOut]:
    transaction = _load(db, ctx, transaction_id)
    return [
        FollowUpOut.model_validate(a)
        for a in sorted(transaction.activities, key=lambda a: a.occurred_at, reverse=True)
    ]


@router.post(
    "/transactions/{transaction_id}/activities",
    response_model=FollowUpOut,
    status_code=status.HTTP_201_CREATED,
)
def log_activity(
    transaction_id: uuid.UUID, payload: FollowUpIn, ctx: WritableCtx, db: DbSession
) -> FollowUpOut:
    """Log a call or message.  This never changes a balance (PRD 11.6)."""
    activity = add_follow_up(
        db,
        ctx,
        transaction_id,
        kind=payload.kind,
        note=payload.note,
        promised_amount=payload.promised_amount,
        promised_date=payload.promised_date,
        outcome=payload.outcome,
    )
    return FollowUpOut.model_validate(activity)


@router.get("/aging")
def aging(ctx: Ctx, db: DbSession, kind: CreditKind = CreditKind.RECEIVABLE) -> list[dict]:
    return report_service.credit_aging(db, ctx, kind)


@router.get("/due-date-presets")
def due_date_presets(ctx: Ctx) -> dict:
    """Quick due-date choices offered in the UI (PRD 11.3)."""
    today = local_today(ctx.tenant.timezone)
    return {
        "presets": [
            {"key": key, "label": key.replace("_", " ").title(), "date": str(resolve_due_date(key, None, today=today))}
            for key in DUE_DATE_PRESETS
        ],
        "note": "A due date is optional. Without one a balance stays outstanding but never becomes overdue.",
    }
