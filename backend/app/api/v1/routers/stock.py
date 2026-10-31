"""Stock levels, movements, adjustments, transfers and counts (PRD 9)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.core.clock import local_today
from app.core.deps import Ctx, DbSession, WritableCtx
from app.core.permissions import Permission
from app.core.tenancy import get_tenant_object, tenant_query
from app.models.access import User
from app.models.catalogue import Product, ProductVariant
from app.models.inventory import (
    StockBalance,
    StockCount,
    StockMovement,
    StockTransfer,
    TransferStatus,
)
from app.models.organisation import Branch, StockLocation
from app.schemas.common import Page
from app.schemas.operations import (
    BranchStockSetupOut,
    CountLineIn,
    CountOut,
    CountStartIn,
    MovementOut,
    OpeningSheetOut,
    OpeningSheetRowOut,
    OpeningStockIn,
    OpeningStockOut,
    StockAdjustIn,
    StockLevelOut,
    StockOverviewBranch,
    StockOverviewOut,
    StockOverviewRow,
    TransferBranchOut,
    TransferDecisionIn,
    TransferIn,
    TransferLineOut,
    TransferOut,
    TransferReceiveIn,
    TransferRequestIn,
)
from app.services.inventory import (
    accept_transfer,
    adjust_stock,
    approve_transfer,
    branches_awaiting_opening_stock,
    cancel_transfer,
    classify_stock_level,
    create_transfer,
    dispatch_transfer,
    low_stock_items,
    opening_sheet,
    post_count,
    receive_transfer,
    reconcile_balances,
    record_count_line,
    record_opening_stock,
    reject_transfer,
    request_transfer,
    start_count,
    stock_overview,
    transfer_branches,
    visible_transfers,
)

router = APIRouter(prefix="/stock", tags=["stock"])


def _levels(db, ctx, branch_id: uuid.UUID | None, q: str | None) -> list[StockLevelOut]:
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
    return [
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


@router.get("/levels", response_model=Page[StockLevelOut])
def stock_levels(
    ctx: Ctx,
    db: DbSession,
    branch_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[StockLevelOut]:
    items = _levels(db, ctx, branch_id, q)
    return Page(items=items[offset : offset + limit], total=len(items), limit=limit, offset=offset)


@router.get("/levels/export")
def export_levels(
    ctx: Ctx, db: DbSession, branch_id: uuid.UUID | None = None
) -> StreamingResponse:
    """Stock on hand as a spreadsheet, for a count sheet or a reorder list (PRD 15)."""
    from app.api.v1.routers.reports import csv_response

    ctx.require(Permission.REPORT_INVENTORY)
    rows: list[list] = [["Product", "Branch", "On hand", "Minimum", "Reorder at", "Status"]]
    for item in _levels(db, ctx, branch_id, None):
        rows.append(
            [
                item.name,
                item.branch_name or "",
                str(item.quantity),
                str(item.min_stock) if item.min_stock is not None else "",
                str(item.reorder_level) if item.reorder_level is not None else "",
                item.status,
            ]
        )
    return csv_response(rows, f"estock-stock-{local_today(ctx.tenant.timezone).isoformat()}.csv")


@router.get("/overview", response_model=StockOverviewOut)
def overview(
    ctx: Ctx,
    db: DbSession,
    branch_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> StockOverviewOut:
    """Stock across every branch at once, with each branch's and the combined total.

    ``/levels`` answers "what is on hand", one row per product and branch.
    This answers "where is it", one row per product and a column per branch,
    so a shop with stock in the wrong place can see that at a glance.
    """
    result = stock_overview(db, ctx, branch_id=branch_id, q=q, limit=limit, offset=offset)
    return StockOverviewOut(
        branches=[
            StockOverviewBranch(
                branch_id=column.branch_id,
                name=column.name,
                is_default=column.is_default,
                total=column.total,
            )
            for column in result.branches
        ],
        rows=[
            StockOverviewRow(
                product_id=row.product_id,
                variant_id=row.variant_id,
                name=row.name,
                sku=row.sku,
                unit=row.unit,
                min_stock=row.min_stock,
                reorder_level=row.reorder_level,
                quantities=row.quantities,
                total=row.total,
                status=row.status,
            )
            for row in result.rows
        ],
        grand_total=result.grand_total,
        total=result.total_rows,
        limit=limit,
        offset=offset,
    )


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
# Opening stock for a new branch
# --------------------------------------------------------------------------- #


@router.get("/setup", response_model=list[BranchStockSetupOut])
def setup_needed(ctx: Ctx, db: DbSession) -> list[BranchStockSetupOut]:
    """Branches with nothing recorded against them yet (PRD 6, 9).

    A new branch starts holding nothing, which is true but not useful: the
    products are there, the quantities are not.  This is what the home screen
    and the stock page use to offer the guide, and it empties itself as soon
    as the first quantity is recorded.
    """
    ctx.require(Permission.STOCK_VIEW)
    return [
        BranchStockSetupOut(
            branch_id=branch.branch_id,
            branch_name=branch.branch_name,
            location_id=branch.location_id,
            product_count=branch.product_count,
        )
        for branch in branches_awaiting_opening_stock(db, ctx)
    ]


@router.get("/opening", response_model=OpeningSheetOut)
def opening_stock_sheet(
    ctx: Ctx,
    db: DbSession,
    branch_id: uuid.UUID,
    q: str | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> OpeningSheetOut:
    """The count sheet for one branch: every product, with what it holds now."""
    sheet = opening_sheet(db, ctx, branch_id=branch_id, q=q, limit=limit, offset=offset)
    return OpeningSheetOut(
        branch_id=sheet.branch_id,
        branch_name=sheet.branch_name,
        location_id=sheet.location_id,
        location_name=sheet.location_name,
        rows=[
            OpeningSheetRowOut(
                product_id=row.product_id,
                variant_id=row.variant_id,
                name=row.name,
                sku=row.sku,
                unit=row.unit,
                quantity=row.quantity,
            )
            for row in sheet.rows
        ],
        total=sheet.total_rows,
        limit=limit,
        offset=offset,
        recorded=sheet.recorded,
        product_count=sheet.product_count,
    )


@router.post("/opening", response_model=OpeningStockOut, status_code=status.HTTP_201_CREATED)
def record_opening(
    payload: OpeningStockIn, ctx: WritableCtx, db: DbSession
) -> OpeningStockOut:
    """Record counted quantities for a branch, posting only what changed."""
    movements = record_opening_stock(
        db,
        ctx,
        branch_id=payload.branch_id,
        counted=[(line.variant_id, line.quantity) for line in payload.lines],
        note=payload.note,
        idempotency_key=payload.idempotency_key,
    )
    return OpeningStockOut(
        branch_id=payload.branch_id,
        recorded=len(movements),
        unchanged=len(payload.lines) - len(movements),
        movements=[MovementOut.model_validate(m) for m in movements],
    )


# --------------------------------------------------------------------------- #
# Transfers
# --------------------------------------------------------------------------- #


@router.get("/branches", response_model=list[TransferBranchOut])
def transfer_targets(ctx: Ctx, db: DbSession) -> list[TransferBranchOut]:
    """Branch names a transfer or a request could involve, with no quantities.

    The branch that has run out needs to be able to name the branch it is
    asking, which is by definition one it does not run itself — so this is
    wider than ``/branches``, and deliberately carries nothing but names.
    """
    return [
        TransferBranchOut(
            branch_id=branch.branch_id,
            branch_name=branch.branch_name,
            location_id=branch.location_id,
            is_mine=branch.is_mine,
        )
        for branch in transfer_branches(db, ctx)
    ]


@router.get("/transfers", response_model=list[TransferOut])
def list_transfers(
    ctx: Ctx,
    db: DbSession,
    transfer_status: list[TransferStatus] | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
) -> list[TransferOut]:
    """Transfers and requests together: one record of what was asked for, allowed,
    refused and actually moved (PRD 9)."""
    rows = visible_transfers(db, ctx, statuses=transfer_status, limit=limit)
    return _transfers_out(db, ctx, rows)


@router.post("/transfers", response_model=TransferOut, status_code=status.HTTP_201_CREATED)
def new_transfer(payload: TransferIn, ctx: WritableCtx, db: DbSession) -> TransferOut:
    """Send stock a branch has to spare: it leaves on dispatch, arrives on receipt."""
    transfer = create_transfer(
        db,
        ctx,
        from_location_id=payload.from_location_id,
        to_location_id=payload.to_location_id,
        lines=[(line.variant_id, line.quantity) for line in payload.lines],
        note=payload.note,
    )
    return _transfer_out(db, ctx, transfer)


@router.post("/requests", response_model=TransferOut, status_code=status.HTTP_201_CREATED)
def new_request(payload: TransferRequestIn, ctx: WritableCtx, db: DbSession) -> TransferOut:
    """Ask another branch for stock.  Nothing moves until it is approved and accepted."""
    transfer = request_transfer(
        db,
        ctx,
        from_location_id=payload.from_location_id,
        to_location_id=payload.to_location_id,
        lines=[(line.variant_id, line.quantity) for line in payload.lines],
        note=payload.note,
    )
    return _transfer_out(db, ctx, transfer)


@router.post("/transfers/{transfer_id}/approve", response_model=TransferOut)
def approve(
    transfer_id: uuid.UUID, payload: TransferDecisionIn, ctx: WritableCtx, db: DbSession
) -> TransferOut:
    return _transfer_out(db, ctx, approve_transfer(db, ctx, transfer_id, note=payload.note))


@router.post("/transfers/{transfer_id}/reject", response_model=TransferOut)
def reject(
    transfer_id: uuid.UUID, payload: TransferDecisionIn, ctx: WritableCtx, db: DbSession
) -> TransferOut:
    return _transfer_out(
        db, ctx, reject_transfer(db, ctx, transfer_id, note=payload.note or "")
    )


@router.post("/transfers/{transfer_id}/accept", response_model=TransferOut)
def accept(transfer_id: uuid.UUID, ctx: WritableCtx, db: DbSession) -> TransferOut:
    """Take up an approved request: the stock moves now, both legs at once."""
    return _transfer_out(db, ctx, accept_transfer(db, ctx, transfer_id))


@router.post("/transfers/{transfer_id}/cancel", response_model=TransferOut)
def cancel(
    transfer_id: uuid.UUID, payload: TransferDecisionIn, ctx: WritableCtx, db: DbSession
) -> TransferOut:
    return _transfer_out(db, ctx, cancel_transfer(db, ctx, transfer_id, note=payload.note))


@router.post("/transfers/{transfer_id}/dispatch", response_model=TransferOut)
def dispatch(transfer_id: uuid.UUID, ctx: WritableCtx, db: DbSession) -> TransferOut:
    return _transfer_out(db, ctx, dispatch_transfer(db, ctx, transfer_id))


@router.post("/transfers/{transfer_id}/receive", response_model=TransferOut)
def receive(
    transfer_id: uuid.UUID, payload: TransferReceiveIn, ctx: WritableCtx, db: DbSession
) -> TransferOut:
    return _transfer_out(db, ctx, receive_transfer(db, ctx, transfer_id, payload.received))


def _transfer_out(db, ctx, transfer: StockTransfer) -> TransferOut:
    return _transfers_out(db, ctx, [transfer])[0]


def _transfers_out(db, ctx, transfers: list[StockTransfer]) -> list[TransferOut]:
    """Resolve the names a transfer refers to, in one pass over the whole list.

    A branch asking for stock cannot look up the product it has none of, nor
    name a branch it has no access to, so the answer carries both rather than
    leaving the caller to join them.
    """
    if not transfers:
        return []

    location_ids = {t.from_location_id for t in transfers} | {
        t.to_location_id for t in transfers
    }
    places = {
        row.id: (row.location_name, row.branch_id, row.branch_name)
        for row in db.execute(
            select(
                StockLocation.id,
                StockLocation.name.label("location_name"),
                Branch.id.label("branch_id"),
                Branch.name.label("branch_name"),
            )
            .join(Branch, Branch.id == StockLocation.branch_id)
            .where(
                StockLocation.tenant_id == ctx.tenant_id,
                StockLocation.id.in_(location_ids),
            )
        )
    }

    actor_ids = {t.requested_by_id for t in transfers} | {t.decided_by_id for t in transfers}
    actor_ids.discard(None)
    actors = (
        {
            row.id: row.full_name
            for row in db.execute(select(User.id, User.full_name).where(User.id.in_(actor_ids)))
        }
        if actor_ids
        else {}
    )

    variant_ids = {line.variant_id for t in transfers for line in t.lines}
    products = (
        {
            row.id: (
                f"{row.product_name} — {row.variant_name}"
                if row.variant_name
                else row.product_name
            )
            for row in db.execute(
                select(
                    ProductVariant.id,
                    Product.name.label("product_name"),
                    ProductVariant.name.label("variant_name"),
                )
                .join(Product, Product.id == ProductVariant.product_id)
                .where(
                    ProductVariant.tenant_id == ctx.tenant_id,
                    ProductVariant.id.in_(variant_ids),
                )
            )
        }
        if variant_ids
        else {}
    )

    out: list[TransferOut] = []
    for transfer in transfers:
        source = places.get(transfer.from_location_id, (None, None, None))
        destination = places.get(transfer.to_location_id, (None, None, None))
        out.append(
            TransferOut(
                id=transfer.id,
                reference=transfer.reference,
                from_location_id=transfer.from_location_id,
                from_location_name=source[0],
                from_branch_id=source[1],
                from_branch_name=source[2],
                to_location_id=transfer.to_location_id,
                to_location_name=destination[0],
                to_branch_id=destination[1],
                to_branch_name=destination[2],
                status=str(transfer.status),
                requested_at=transfer.requested_at,
                requested_by_name=actors.get(transfer.requested_by_id),
                decided_at=transfer.decided_at,
                decided_by_name=actors.get(transfer.decided_by_id),
                decision_note=transfer.decision_note,
                accepted_at=transfer.accepted_at,
                dispatched_at=transfer.dispatched_at,
                received_at=transfer.received_at,
                note=transfer.note,
                lines=[
                    TransferLineOut(
                        id=line.id,
                        product_id=line.product_id,
                        variant_id=line.variant_id,
                        name=products.get(line.variant_id),
                        quantity_sent=line.quantity_sent,
                        quantity_received=line.quantity_received,
                        note=line.note,
                    )
                    for line in transfer.lines
                ],
            )
        )
    return out


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
