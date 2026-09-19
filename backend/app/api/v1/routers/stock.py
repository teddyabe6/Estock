"""Stock levels, movements, adjustments, transfers and counts (PRD 9)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.core.deps import Ctx, DbSession, WritableCtx
from app.core.permissions import Permission
from app.core.tenancy import get_tenant_object, tenant_query
from app.models.catalogue import Product, ProductVariant
from app.models.inventory import (
    StockBalance,
    StockCount,
    StockMovement,
    StockTransfer,
)
from app.models.organisation import Branch
from app.schemas.common import Page
from app.schemas.operations import (
    CountLineIn,
    CountOut,
    CountStartIn,
    MovementOut,
    StockAdjustIn,
    StockLevelOut,
    TransferIn,
    TransferOut,
    TransferReceiveIn,
)
from app.services.inventory import (
    adjust_stock,
    classify_stock_level,
    create_transfer,
    dispatch_transfer,
    low_stock_items,
    post_count,
    receive_transfer,
    reconcile_balances,
    record_count_line,
    start_count,
)

router = APIRouter(prefix="/stock", tags=["stock"])


@router.get("/levels", response_model=Page[StockLevelOut])
def stock_levels(
    ctx: Ctx,
    db: DbSession,
    branch_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[StockLevelOut]:
    ctx.require(Permission.STOCK_VIEW)
    allowed = ctx.visible_branch_ids(db)
    if branch_id is not None:
        ctx.require_branch(branch_id)
        allowed = [branch_id]

    stmt = (
        select(
            StockBalance.product_id,
            StockBalance.variant_id,
            StockBalance.branch_id,
            func.sum(StockBalance.quantity).label("quantity"),
            Product.name,
            ProductVariant.name.label("variant_name"),
            ProductVariant.min_stock,
            ProductVariant.reorder_level,
            Branch.name.label("branch_name"),
        )
        .join(Product, Product.id == StockBalance.product_id)
        .join(ProductVariant, ProductVariant.id == StockBalance.variant_id)
        .join(Branch, Branch.id == StockBalance.branch_id)
        .where(StockBalance.tenant_id == ctx.tenant_id, StockBalance.branch_id.in_(allowed))
        .group_by(
            StockBalance.product_id,
            StockBalance.variant_id,
            StockBalance.branch_id,
            Product.name,
            ProductVariant.name,
            ProductVariant.min_stock,
            ProductVariant.reorder_level,
            Branch.name,
        )
    )
    if q:
        stmt = stmt.where(func.lower(Product.name).like(f"%{q.strip().lower()}%"))

    rows = db.execute(stmt.order_by(Product.name)).all()
    items = [
        StockLevelOut(
            product_id=row.product_id,
            variant_id=row.variant_id,
            name=f"{row.name} — {row.variant_name}" if row.variant_name else row.name,
            branch_id=row.branch_id,
            branch_name=row.branch_name,
            quantity=Decimal(row.quantity or 0),
            min_stock=row.min_stock,
            reorder_level=row.reorder_level,
            status=classify_stock_level(
                Decimal(row.quantity or 0), row.min_stock, row.reorder_level
            ),
        )
        for row in rows
    ]
    return Page(items=items[offset : offset + limit], total=len(items), limit=limit, offset=offset)


@router.get("/low", response_model=list[StockLevelOut])
def low_stock(ctx: Ctx, db: DbSession, branch_id: uuid.UUID | None = None) -> list[StockLevelOut]:
    """Warning, critical and out-of-stock items (PRD 9)."""
    ctx.require(Permission.STOCK_VIEW)
    branch_ids = ctx.visible_branch_ids(db)
    if branch_id is not None:
        ctx.require_branch(branch_id)
        branch_ids = [branch_id]
    return [
        StockLevelOut(
            product_id=item.product_id,
            variant_id=item.variant_id,
            name=item.name,
            branch_id=item.branch_id,
            quantity=item.quantity,
            min_stock=item.min_stock,
            reorder_level=item.reorder_level,
            status=item.severity,
        )
        for item in low_stock_items(db, ctx.tenant_id, branch_ids)
    ]


@router.get("/movements", response_model=Page[MovementOut])
def movements(
    ctx: Ctx,
    db: DbSession,
    product_id: uuid.UUID | None = None,
    variant_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[MovementOut]:
    """The stock ledger — every change, with who, when and why (PRD 9)."""
    ctx.require(Permission.STOCK_VIEW)
    allowed = ctx.visible_branch_ids(db)
    if branch_id is not None:
        ctx.require_branch(branch_id)
        allowed = [branch_id]

    stmt = tenant_query(StockMovement, ctx.tenant_id).where(
        StockMovement.branch_id.in_(allowed)
    )
    if product_id is not None:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if variant_id is not None:
        stmt = stmt.where(StockMovement.variant_id == variant_id)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(StockMovement.occurred_at.desc()).limit(limit).offset(offset)
    ).scalars()
    return Page(
        items=[MovementOut.model_validate(m) for m in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/adjust", response_model=MovementOut, status_code=status.HTTP_201_CREATED)
def adjust(payload: StockAdjustIn, ctx: WritableCtx, db: DbSession) -> MovementOut:
    movement = adjust_stock(
        db,
        ctx,
        variant_id=payload.variant_id,
        location_id=payload.location_id,
        quantity=payload.quantity,
        reason=payload.reason,
        note=payload.note,
    )
    return MovementOut.model_validate(movement)


# --------------------------------------------------------------------------- #
# Transfers
# --------------------------------------------------------------------------- #


@router.get("/transfers", response_model=list[TransferOut])
def list_transfers(ctx: Ctx, db: DbSession, limit: int = 50) -> list[TransferOut]:
    ctx.require(Permission.STOCK_VIEW)
    rows = db.execute(
        tenant_query(StockTransfer, ctx.tenant_id)
        .order_by(StockTransfer.created_at.desc())
        .limit(min(limit, 200))
    ).scalars()
    return [TransferOut.model_validate(t) for t in rows]


@router.post("/transfers", response_model=TransferOut, status_code=status.HTTP_201_CREATED)
def new_transfer(payload: TransferIn, ctx: WritableCtx, db: DbSession) -> TransferOut:
    transfer = create_transfer(
        db,
        ctx,
        from_location_id=payload.from_location_id,
        to_location_id=payload.to_location_id,
        lines=[(line.variant_id, line.quantity) for line in payload.lines],
        note=payload.note,
    )
    return TransferOut.model_validate(transfer)


@router.post("/transfers/{transfer_id}/dispatch", response_model=TransferOut)
def dispatch(transfer_id: uuid.UUID, ctx: WritableCtx, db: DbSession) -> TransferOut:
    return TransferOut.model_validate(dispatch_transfer(db, ctx, transfer_id))


@router.post("/transfers/{transfer_id}/receive", response_model=TransferOut)
def receive(
    transfer_id: uuid.UUID, payload: TransferReceiveIn, ctx: WritableCtx, db: DbSession
) -> TransferOut:
    return TransferOut.model_validate(
        receive_transfer(db, ctx, transfer_id, payload.received)
    )


# --------------------------------------------------------------------------- #
# Counts
# --------------------------------------------------------------------------- #


@router.post("/counts", response_model=CountOut, status_code=status.HTTP_201_CREATED)
def begin_count(payload: CountStartIn, ctx: WritableCtx, db: DbSession) -> CountOut:
    count = start_count(db, ctx, location_id=payload.location_id, note=payload.note)
    return _count_out(count)


@router.get("/counts/{count_id}", response_model=CountOut)
def get_count(count_id: uuid.UUID, ctx: Ctx, db: DbSession) -> CountOut:
    ctx.require(Permission.STOCK_COUNT)
    count = get_tenant_object(db, StockCount, count_id, ctx.tenant_id, label="Stock count")
    return _count_out(count)


@router.post("/counts/{count_id}/lines", response_model=CountOut)
def add_count_line(
    count_id: uuid.UUID, payload: CountLineIn, ctx: WritableCtx, db: DbSession
) -> CountOut:
    """Record a counted quantity and show the variance before posting (PRD A5)."""
    record_count_line(
        db,
        ctx,
        count_id,
        variant_id=payload.variant_id,
        counted_quantity=payload.counted_quantity,
        reason=payload.reason,
        note=payload.note,
    )
    count = get_tenant_object(db, StockCount, count_id, ctx.tenant_id, label="Stock count")
    return _count_out(count)


@router.post("/counts/{count_id}/post", response_model=CountOut)
def finish_count(count_id: uuid.UUID, ctx: WritableCtx, db: DbSession) -> CountOut:
    return _count_out(post_count(db, ctx, count_id))


def _count_out(count: StockCount) -> CountOut:
    payload = CountOut.model_validate(count)
    for line_out, line in zip(payload.lines, count.lines, strict=False):
        line_out.variance = line.variance
    return payload


@router.get("/reconciliation")
def reconciliation(ctx: Ctx, db: DbSession) -> dict:
    """Prove the cached balances still match the movement ledger (PRD 19)."""
    ctx.require(Permission.STOCK_VIEW, Permission.AUDIT_VIEW)
    discrepancies = reconcile_balances(db, ctx.tenant_id)
    return {"in_balance": not discrepancies, "discrepancies": discrepancies}
