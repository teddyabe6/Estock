"""The sales workflow (PRD 10)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.api.v1.serializers import sale_out
from app.core.clock import day_end, day_start
from app.core.deps import Ctx, DbSession, WritableCtx
from app.core.permissions import Permission
from app.core.tenancy import get_tenant_object, tenant_query
from app.models.sales import Sale, SaleStatus
from app.schemas.common import Page
from app.schemas.operations import (
    SaleIn,
    SaleOut,
    SaleResponse,
    VoidSaleIn,
)
from app.services.sales import (
    PaymentInput,
    SaleInput,
    SaleLineInput,
    create_sale,
    void_sale,
)

router = APIRouter(prefix="/sales", tags=["sales"])


@router.post("", response_model=SaleResponse, status_code=status.HTTP_201_CREATED)
def record_sale(payload: SaleIn, ctx: WritableCtx, db: DbSession) -> SaleResponse:
    """Post a sale.  Lines, stock, payments and any receivable happen together."""
    result = create_sale(
        db,
        ctx,
        SaleInput(
            lines=[
                SaleLineInput(
                    variant_id=line.variant_id,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    discount_amount=line.discount_amount,
                    discount_percent=line.discount_percent,
                    tax_rate=line.tax_rate,
                )
                for line in payload.lines
            ],
            payments=[
                PaymentInput(
                    method=p.method, amount=p.amount, reference=p.reference, note=p.note
                )
                for p in payload.payments
            ],
            branch_id=payload.branch_id,
            location_id=payload.location_id,
            customer_id=payload.customer_id,
            note=payload.note,
            due_date=payload.due_date,
            due_date_preset=payload.due_date_preset,
            credit_note=payload.credit_note,
            override_credit_limit=payload.override_credit_limit,
            idempotency_key=payload.idempotency_key,
        ),
    )
    return SaleResponse(
        sale=sale_out(ctx, result.sale),
        credit_transaction_id=(
            result.credit_transaction.id if result.credit_transaction else None
        ),
        warnings=result.warnings,
    )


@router.get("", response_model=Page[SaleOut])
def list_sales(
    ctx: Ctx,
    db: DbSession,
    branch_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_voided: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[SaleOut]:
    ctx.require(Permission.SALE_VIEW)
    allowed = ctx.visible_branch_ids(db)
    if branch_id is not None:
        ctx.require_branch(branch_id)
        allowed = [branch_id]

    stmt = tenant_query(Sale, ctx.tenant_id).where(Sale.branch_id.in_(allowed))
    if not include_voided:
        stmt = stmt.where(Sale.status == SaleStatus.COMPLETED)
    if customer_id is not None:
        stmt = stmt.where(Sale.customer_id == customer_id)
    # Day boundaries follow the business's clock, not the server's.
    if date_from is not None:
        stmt = stmt.where(Sale.sold_at >= day_start(date_from, ctx.tenant.timezone))
    if date_to is not None:
        stmt = stmt.where(Sale.sold_at <= day_end(date_to, ctx.tenant.timezone))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(Sale.sold_at.desc()).limit(limit).offset(offset)
    ).scalars()
    return Page(
        items=[sale_out(ctx, sale) for sale in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{sale_id}", response_model=SaleOut)
def get_sale(sale_id: uuid.UUID, ctx: Ctx, db: DbSession) -> SaleOut:
    ctx.require(Permission.SALE_VIEW)
    sale = get_tenant_object(db, Sale, sale_id, ctx.tenant_id, label="Sale")
    ctx.require_branch(sale.branch_id)
    return sale_out(ctx, sale)


@router.get("/{sale_id}/receipt")
def receipt(sale_id: uuid.UUID, ctx: Ctx, db: DbSession) -> dict:
    """Receipt data for printing, download or sharing (PRD 10)."""
    ctx.require(Permission.SALE_VIEW)
    sale = get_tenant_object(db, Sale, sale_id, ctx.tenant_id, label="Sale")
    ctx.require_branch(sale.branch_id)
    from app.models.contacts import Customer
    from app.models.organisation import Branch

    branch = db.get(Branch, sale.branch_id)
    customer = db.get(Customer, sale.customer_id) if sale.customer_id else None
    return {
        "business": {
            "name": ctx.tenant.name,
            "phone": ctx.tenant.phone,
            "address": ctx.tenant.address,
            "tin": ctx.tenant.tin,
        },
        "branch": {"name": branch.name if branch else None},
        "sale": {
            "number": sale.number,
            "sold_at": sale.sold_at.isoformat(),
            "status": str(sale.status),
            "currency": sale.currency,
            "subtotal": str(sale.subtotal),
            "discount_total": str(sale.discount_total),
            "tax_total": str(sale.tax_total),
            "total_amount": str(sale.total_amount),
            "amount_paid": str(sale.amount_paid),
            "balance_due": str(sale.balance_due),
        },
        "customer": {"name": customer.name, "phone": customer.phone} if customer else None,
        "lines": [
            {
                "description": line.description,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "discount_amount": str(line.discount_amount),
                "line_total": str(line.line_total),
            }
            for line in sale.lines
        ],
        "payments": [
            {"method": str(p.method), "amount": str(p.amount)}
            for p in sale.payments
            if not p.is_reversed
        ],
    }


@router.post("/{sale_id}/void", response_model=SaleOut)
def void(sale_id: uuid.UUID, payload: VoidSaleIn, ctx: WritableCtx, db: DbSession) -> SaleOut:
    """Reverse a sale with compensating stock movements.  Nothing is deleted."""
    sale = void_sale(db, ctx, sale_id, reason=payload.reason)
    return sale_out(ctx, sale)
