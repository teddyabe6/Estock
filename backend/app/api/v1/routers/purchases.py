"""Stock receiving and supplier credit (PRD 11.2, A3)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.core.deps import Ctx, DbSession, WritableCtx
from app.core.permissions import Permission
from app.core.tenancy import get_tenant_object, tenant_query
from app.models.purchasing import Purchase
from app.schemas.common import Page
from app.schemas.operations import PurchaseIn, PurchaseOut, PurchaseResponse
from app.services.purchasing import (
    PurchaseInput,
    PurchaseLineInput,
    receive_purchase,
)

router = APIRouter(prefix="/purchases", tags=["purchasing"])


@router.post("", response_model=PurchaseResponse, status_code=status.HTTP_201_CREATED)
def receive(payload: PurchaseIn, ctx: WritableCtx, db: DbSession) -> PurchaseResponse:
    """Receive stock, allocate shared costs and open a payable if unpaid."""
    result = receive_purchase(
        db,
        ctx,
        PurchaseInput(
            lines=[
                PurchaseLineInput(
                    variant_id=line.variant_id,
                    quantity=line.quantity,
                    unit_cost=line.unit_cost,
                )
                for line in payload.lines
            ],
            supplier_id=payload.supplier_id,
            branch_id=payload.branch_id,
            location_id=payload.location_id,
            transport_cost=payload.transport_cost,
            other_costs=payload.other_costs,
            cost_allocation_method=payload.cost_allocation_method,
            amount_paid=payload.amount_paid,
            payment_method=payload.payment_method,
            supplier_invoice_ref=payload.supplier_invoice_ref,
            note=payload.note,
            due_date=payload.due_date,
            due_date_preset=payload.due_date_preset,
            credit_note=payload.credit_note,
            reprice_from_cost=payload.reprice_from_cost,
            idempotency_key=payload.idempotency_key,
        ),
    )
    return PurchaseResponse(
        purchase=PurchaseOut.model_validate(result.purchase),
        credit_transaction_id=(
            result.credit_transaction.id if result.credit_transaction else None
        ),
        repriced_variant_ids=result.repriced,
    )


@router.get("", response_model=Page[PurchaseOut])
def list_purchases(
    ctx: Ctx,
    db: DbSession,
    supplier_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[PurchaseOut]:
    ctx.require(Permission.PURCHASE_VIEW)
    allowed = ctx.visible_branch_ids(db)
    if branch_id is not None:
        ctx.require_branch(branch_id)
        allowed = [branch_id]

    stmt = tenant_query(Purchase, ctx.tenant_id).where(Purchase.branch_id.in_(allowed))
    if supplier_id is not None:
        stmt = stmt.where(Purchase.supplier_id == supplier_id)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(Purchase.received_at.desc()).limit(limit).offset(offset)
    ).scalars()
    return Page(
        items=[PurchaseOut.model_validate(p) for p in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{purchase_id}", response_model=PurchaseOut)
def get_purchase(purchase_id: uuid.UUID, ctx: Ctx, db: DbSession) -> PurchaseOut:
    ctx.require(Permission.PURCHASE_VIEW)
    purchase = get_tenant_object(db, Purchase, purchase_id, ctx.tenant_id, label="Purchase")
    ctx.require_branch(purchase.branch_id)
    return PurchaseOut.model_validate(purchase)
