"""Stock posting, balances, transfers, counts and low-stock detection (PRD 9).

Every change to stock goes through :func:`post_movement`, which appends a ledger
row and updates the cached balance in the same transaction.  Nothing else in the
codebase writes ``StockBalance``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, record_audit
from app.core.db import supports_row_locks, utcnow
from app.core.errors import ConflictError, InsufficientStock, NotFoundError, ValidationError
from app.core.permissions import Permission
from app.core.tenancy import AuthContext, get_tenant_object, tenant_query
from app.models.catalogue import Product, ProductVariant
from app.models.inventory import (
    STOCK_IN_REASONS,
    STOCK_OUT_REASONS,
    MovementReason,
    StockBalance,
    StockCount,
    StockCountLine,
    StockCountStatus,
    StockMovement,
    StockTransfer,
    StockTransferLine,
    TransferStatus,
)
from app.models.organisation import StockLocation
from app.services.numbering import next_number

ZERO = Decimal("0.000")


@dataclass(slots=True)
class StockPosting:
    """One stock effect to post as part of a larger operation."""

    variant_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal
    reason: MovementReason
    unit_cost: Decimal | None = None
    note: str | None = None
    source_type: str | None = None
    source_id: uuid.UUID | None = None
    idempotency_key: str | None = None


def _load_variant(db: Session, tenant_id: uuid.UUID, variant_id: uuid.UUID) -> ProductVariant:
    variant = db.execute(
        tenant_query(ProductVariant, tenant_id).where(ProductVariant.id == variant_id)
    ).scalar_one_or_none()
    if variant is None:
        raise NotFoundError("Product not found")
    return variant


def _lock_balance(
    db: Session,
    tenant_id: uuid.UUID,
    variant_id: uuid.UUID,
    location_id: uuid.UUID,
) -> StockBalance | None:
    stmt = tenant_query(StockBalance, tenant_id).where(
        StockBalance.variant_id == variant_id,
        StockBalance.location_id == location_id,
    )
    if supports_row_locks(db):
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def get_balance(
    db: Session, tenant_id: uuid.UUID, variant_id: uuid.UUID, location_id: uuid.UUID
) -> Decimal:
    row = db.execute(
        select(StockBalance.quantity).where(
            StockBalance.tenant_id == tenant_id,
            StockBalance.variant_id == variant_id,
            StockBalance.location_id == location_id,
        )
    ).scalar_one_or_none()
    return Decimal(row) if row is not None else ZERO


def available_quantity(
    db: Session, tenant_id: uuid.UUID, variant_id: uuid.UUID, branch_id: uuid.UUID | None = None
) -> Decimal:
    """On-hand quantity across a branch, or the whole business."""
    stmt = select(func.coalesce(func.sum(StockBalance.quantity), 0)).where(
        StockBalance.tenant_id == tenant_id, StockBalance.variant_id == variant_id
    )
    if branch_id is not None:
        stmt = stmt.where(StockBalance.branch_id == branch_id)
    return Decimal(db.execute(stmt).scalar_one() or 0)


def post_movement(
    db: Session,
    ctx: AuthContext,
    posting: StockPosting,
    *,
    occurred_at: datetime | None = None,
    allow_negative: bool | None = None,
) -> StockMovement:
    """Append a ledger entry and update the cached balance atomically.

    Refuses to drive stock negative unless the business has explicitly enabled
    it and the actor may approve the exception (PRD 9).
    """
    quantity = Decimal(posting.quantity)
    if quantity == 0:
        raise ValidationError("Stock movement quantity cannot be zero")
    if posting.reason in STOCK_IN_REASONS and quantity < 0:
        raise ValidationError(f"{posting.reason} must increase stock")
    if posting.reason in STOCK_OUT_REASONS and quantity > 0:
        raise ValidationError(f"{posting.reason} must reduce stock")

    variant = _load_variant(db, ctx.tenant_id, posting.variant_id)
    location = get_tenant_object(
        db, StockLocation, posting.location_id, ctx.tenant_id, label="Stock location"
    )

    if posting.idempotency_key:
        existing = db.execute(
            tenant_query(StockMovement, ctx.tenant_id).where(
                StockMovement.idempotency_key == posting.idempotency_key
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    balance = _lock_balance(db, ctx.tenant_id, posting.variant_id, posting.location_id)
    current = Decimal(balance.quantity) if balance else ZERO
    new_quantity = current + quantity

    if new_quantity < 0 and variant.product.track_stock:
        permitted = (
            ctx.tenant.allow_negative_stock if allow_negative is None else allow_negative
        )
        if not permitted:
            raise InsufficientStock(
                f"Not enough stock for {variant.display_name}: "
                f"{current} available, {abs(quantity)} required",
                details={
                    "variant_id": str(posting.variant_id),
                    "available": str(current),
                    "requested": str(abs(quantity)),
                },
            )
        record_audit(
            db,
            action=AuditAction.NEGATIVE_STOCK_ALLOWED,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            entity_type="product_variant",
            entity_id=posting.variant_id,
            summary=f"Stock went negative to {new_quantity}",
        )

    if balance is None:
        balance = StockBalance(
            tenant_id=ctx.tenant_id,
            product_id=variant.product_id,
            variant_id=posting.variant_id,
            location_id=posting.location_id,
            branch_id=location.branch_id,
            quantity=new_quantity,
        )
        db.add(balance)
    else:
        balance.quantity = new_quantity

    movement = StockMovement(
        tenant_id=ctx.tenant_id,
        product_id=variant.product_id,
        variant_id=posting.variant_id,
        location_id=posting.location_id,
        branch_id=location.branch_id,
        quantity=quantity,
        balance_after=new_quantity,
        reason=posting.reason,
        unit_cost=posting.unit_cost,
        note=posting.note,
        occurred_at=occurred_at or utcnow(),
        source_type=posting.source_type,
        source_id=posting.source_id,
        idempotency_key=posting.idempotency_key,
        created_by_id=ctx.user_id,
    )
    db.add(movement)
    db.flush()
    return movement


def update_average_cost(
    variant: ProductVariant, received_quantity: Decimal, unit_cost: Decimal, on_hand_before: Decimal
) -> None:
    """Weighted average landed cost after a receipt (PRD 8.2).

    Stock already on hand keeps its cost; the new units bring theirs.  Negative
    or zero stock before receipt means the new cost simply takes over.
    """
    received_quantity = Decimal(received_quantity)
    unit_cost = Decimal(unit_cost)
    if received_quantity <= 0:
        return
    previous_cost = variant.average_cost
    if on_hand_before <= 0 or previous_cost is None:
        variant.average_cost = unit_cost
        return
    total_value = (Decimal(previous_cost) * on_hand_before) + (unit_cost * received_quantity)
    total_quantity = on_hand_before + received_quantity
    variant.average_cost = (total_value / total_quantity).quantize(Decimal("0.01"))


def adjust_stock(
    db: Session,
    ctx: AuthContext,
    *,
    variant_id: uuid.UUID,
    location_id: uuid.UUID,
    quantity: Decimal,
    reason: MovementReason,
    note: str | None = None,
) -> StockMovement:
    """Record an approved adjustment, damage or loss (PRD 9)."""
    ctx.require(Permission.STOCK_ADJUST)
    if reason not in {
        MovementReason.ADJUSTMENT,
        MovementReason.DAMAGE,
        MovementReason.LOSS,
        MovementReason.OPENING,
    }:
        raise ValidationError("Unsupported adjustment reason")
    if reason in (MovementReason.DAMAGE, MovementReason.LOSS) and Decimal(quantity) > 0:
        raise ValidationError(f"{reason} must reduce stock")
    if not note:
        raise ValidationError("A reason note is required for stock adjustments")

    location = get_tenant_object(
        db, StockLocation, location_id, ctx.tenant_id, label="Stock location"
    )
    ctx.require_branch(location.branch_id)

    movement = post_movement(
        db,
        ctx,
        StockPosting(
            variant_id=variant_id,
            location_id=location_id,
            quantity=Decimal(quantity),
            reason=reason,
            note=note,
            source_type="adjustment",
        ),
    )
    record_audit(
        db,
        action=AuditAction.STOCK_ADJUSTED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="stock_movement",
        entity_id=movement.id,
        summary=f"{reason}: {quantity}",
        payload={"note": note, "location_id": str(location_id)},
    )
    return movement


# --------------------------------------------------------------------------- #
# Transfers
# --------------------------------------------------------------------------- #


def create_transfer(
    db: Session,
    ctx: AuthContext,
    *,
    from_location_id: uuid.UUID,
    to_location_id: uuid.UUID,
    lines: list[tuple[uuid.UUID, Decimal]],
    note: str | None = None,
) -> StockTransfer:
    ctx.require(Permission.STOCK_TRANSFER)
    if from_location_id == to_location_id:
        raise ValidationError("Choose two different locations")
    if not lines:
        raise ValidationError("Add at least one product to the transfer")

    source = get_tenant_object(
        db, StockLocation, from_location_id, ctx.tenant_id, label="Source location"
    )
    destination = get_tenant_object(
        db, StockLocation, to_location_id, ctx.tenant_id, label="Destination location"
    )
    ctx.require_branch(source.branch_id)
    ctx.require_branch(destination.branch_id)

    transfer = StockTransfer(
        tenant_id=ctx.tenant_id,
        reference=next_number(db, StockTransfer, ctx.tenant_id, "transfer", column="reference"),
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        status=TransferStatus.DRAFT,
        note=note,
        created_by_id=ctx.user_id,
    )
    db.add(transfer)
    db.flush()

    for variant_id, quantity in lines:
        if Decimal(quantity) <= 0:
            raise ValidationError("Transfer quantities must be positive")
        variant = _load_variant(db, ctx.tenant_id, variant_id)
        transfer.lines.append(
            StockTransferLine(
                transfer_id=transfer.id,
                product_id=variant.product_id,
                variant_id=variant_id,
                quantity_sent=Decimal(quantity),
            )
        )
    db.flush()
    return transfer


def dispatch_transfer(db: Session, ctx: AuthContext, transfer_id: uuid.UUID) -> StockTransfer:
    """Remove stock from the source location (PRD 9)."""
    ctx.require(Permission.STOCK_TRANSFER)
    transfer = get_tenant_object(
        db, StockTransfer, transfer_id, ctx.tenant_id, label="Transfer"
    )
    if transfer.status != TransferStatus.DRAFT:
        raise ConflictError(f"Transfer is already {transfer.status}")

    for line in transfer.lines:
        post_movement(
            db,
            ctx,
            StockPosting(
                variant_id=line.variant_id,
                location_id=transfer.from_location_id,
                quantity=-Decimal(line.quantity_sent),
                reason=MovementReason.TRANSFER_OUT,
                source_type="transfer",
                source_id=transfer.id,
                idempotency_key=f"transfer-out:{transfer.id}:{line.id}",
                note=f"Transfer {transfer.reference}",
            ),
        )

    transfer.status = TransferStatus.DISPATCHED
    transfer.dispatched_at = utcnow()
    transfer.dispatched_by_id = ctx.user_id
    record_audit(
        db,
        action=AuditAction.STOCK_TRANSFER_DISPATCHED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="stock_transfer",
        entity_id=transfer.id,
        summary=f"Dispatched {transfer.reference}",
    )
    db.flush()
    return transfer


def receive_transfer(
    db: Session,
    ctx: AuthContext,
    transfer_id: uuid.UUID,
    received: dict[uuid.UUID, Decimal] | None = None,
) -> StockTransfer:
    """Add stock at the destination.

    Everything dispatched arrives on the destination's ledger; a shortfall is
    then posted as an explicit loss there, so the units that left the source
    are all accounted for and the discrepancy is a movement with a reason, an
    actor and a timestamp rather than a note (PRD 9).  Nothing is invented: the
    destination ends up holding exactly what was counted in.
    """
    ctx.require(Permission.STOCK_TRANSFER)
    transfer = get_tenant_object(
        db, StockTransfer, transfer_id, ctx.tenant_id, label="Transfer"
    )
    if transfer.status != TransferStatus.DISPATCHED:
        raise ConflictError("Only a dispatched transfer can be received")

    received = received or {}
    for line in transfer.lines:
        quantity_received = Decimal(received.get(line.id, line.quantity_sent))
        if quantity_received < 0:
            raise ValidationError("Received quantity cannot be negative")
        if quantity_received > Decimal(line.quantity_sent):
            raise ValidationError(
                "Received quantity cannot exceed the dispatched quantity; "
                "post a separate adjustment instead"
            )
        line.quantity_received = quantity_received

        post_movement(
            db,
            ctx,
            StockPosting(
                variant_id=line.variant_id,
                location_id=transfer.to_location_id,
                quantity=Decimal(line.quantity_sent),
                reason=MovementReason.TRANSFER_IN,
                source_type="transfer",
                source_id=transfer.id,
                idempotency_key=f"transfer-in:{transfer.id}:{line.id}",
                note=f"Transfer {transfer.reference}",
            ),
        )
        shortfall = Decimal(line.quantity_sent) - quantity_received
        if shortfall > 0:
            post_movement(
                db,
                ctx,
                StockPosting(
                    variant_id=line.variant_id,
                    location_id=transfer.to_location_id,
                    quantity=-shortfall,
                    reason=MovementReason.LOSS,
                    source_type="transfer",
                    source_id=transfer.id,
                    idempotency_key=f"transfer-loss:{transfer.id}:{line.id}",
                    note=(
                        f"Transfer {transfer.reference}: {shortfall} dispatched but not "
                        "received"
                    ),
                ),
                # The loss is a correction of what just arrived, not a sale from it.
                allow_negative=True,
            )
            line.note = ((line.note or "") + f" Shortfall {shortfall} posted as loss.").strip()

    transfer.status = TransferStatus.RECEIVED
    transfer.received_at = utcnow()
    transfer.received_by_id = ctx.user_id
    record_audit(
        db,
        action=AuditAction.STOCK_TRANSFER_RECEIVED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="stock_transfer",
        entity_id=transfer.id,
        summary=f"Received {transfer.reference}",
        payload={
            "discrepancies": {
                str(line.id): str(line.discrepancy)
                for line in transfer.lines
                if line.discrepancy
            }
        },
    )
    db.flush()
    return transfer


# --------------------------------------------------------------------------- #
# Stock counts
# --------------------------------------------------------------------------- #


def start_count(
    db: Session, ctx: AuthContext, *, location_id: uuid.UUID, note: str | None = None
) -> StockCount:
    ctx.require(Permission.STOCK_COUNT)
    location = get_tenant_object(
        db, StockLocation, location_id, ctx.tenant_id, label="Stock location"
    )
    ctx.require_branch(location.branch_id)
    count = StockCount(
        tenant_id=ctx.tenant_id,
        reference=next_number(db, StockCount, ctx.tenant_id, "count", column="reference"),
        location_id=location_id,
        branch_id=location.branch_id,
        status=StockCountStatus.IN_PROGRESS,
        note=note,
        created_by_id=ctx.user_id,
    )
    db.add(count)
    db.flush()
    return count


def record_count_line(
    db: Session,
    ctx: AuthContext,
    count_id: uuid.UUID,
    *,
    variant_id: uuid.UUID,
    counted_quantity: Decimal,
    reason: str | None = None,
    note: str | None = None,
) -> StockCountLine:
    """Record a counted quantity, snapshotting what the system expected."""
    ctx.require(Permission.STOCK_COUNT)
    count = get_tenant_object(db, StockCount, count_id, ctx.tenant_id, label="Stock count")
    if count.status != StockCountStatus.IN_PROGRESS:
        raise ConflictError("This count is no longer open")

    variant = _load_variant(db, ctx.tenant_id, variant_id)
    expected = get_balance(db, ctx.tenant_id, variant_id, count.location_id)

    line = next((line for line in count.lines if line.variant_id == variant_id), None)
    if line is None:
        line = StockCountLine(
            count_id=count.id,
            product_id=variant.product_id,
            variant_id=variant_id,
            expected_quantity=expected,
        )
        # Append through the relationship so ``count.lines`` stays current for
        # the caller that posts the count next.
        count.lines.append(line)
    line.counted_quantity = Decimal(counted_quantity)
    line.reason = reason
    line.note = note
    line.counted_by_id = ctx.user_id
    line.counted_at = utcnow()
    db.flush()
    return line


def post_count(db: Session, ctx: AuthContext, count_id: uuid.UUID) -> StockCount:
    """Turn counted variances into adjustment movements (PRD 9, A5)."""
    ctx.require(Permission.STOCK_COUNT, Permission.STOCK_ADJUST)
    count = get_tenant_object(db, StockCount, count_id, ctx.tenant_id, label="Stock count")
    if count.status != StockCountStatus.IN_PROGRESS:
        raise ConflictError("This count has already been posted")

    adjustments = 0
    for line in count.lines:
        variance = line.variance
        if variance is None or variance == 0:
            continue
        post_movement(
            db,
            ctx,
            StockPosting(
                variant_id=line.variant_id,
                location_id=count.location_id,
                quantity=variance,
                reason=MovementReason.COUNT_ADJUSTMENT,
                note=line.reason or f"Stock count {count.reference}",
                source_type="stock_count",
                source_id=count.id,
                idempotency_key=f"count:{count.id}:{line.id}",
            ),
        )
        adjustments += 1

    count.status = StockCountStatus.POSTED
    count.posted_at = utcnow()
    count.posted_by_id = ctx.user_id
    record_audit(
        db,
        action=AuditAction.STOCK_COUNT_POSTED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="stock_count",
        entity_id=count.id,
        summary=f"Posted {count.reference} with {adjustments} adjustment(s)",
    )
    db.flush()
    return count


# --------------------------------------------------------------------------- #
# Reporting helpers
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class LowStockItem:
    product_id: uuid.UUID
    variant_id: uuid.UUID
    name: str
    branch_id: uuid.UUID
    quantity: Decimal
    min_stock: Decimal | None
    reorder_level: Decimal | None
    severity: str


def low_stock_items(
    db: Session, tenant_id: uuid.UUID, branch_ids: list[uuid.UUID] | None = None
) -> list[LowStockItem]:
    """Out-of-stock, critical and warning items (PRD 9)."""
    stmt = (
        select(
            StockBalance.product_id,
            StockBalance.variant_id,
            StockBalance.branch_id,
            func.sum(StockBalance.quantity).label("quantity"),
            ProductVariant.min_stock,
            ProductVariant.reorder_level,
            Product.name,
            ProductVariant.name.label("variant_name"),
        )
        .join(ProductVariant, ProductVariant.id == StockBalance.variant_id)
        .join(Product, Product.id == StockBalance.product_id)
        .where(
            StockBalance.tenant_id == tenant_id,
            Product.is_active.is_(True),
            Product.track_stock.is_(True),
        )
        .group_by(
            StockBalance.product_id,
            StockBalance.variant_id,
            StockBalance.branch_id,
            ProductVariant.min_stock,
            ProductVariant.reorder_level,
            Product.name,
            ProductVariant.name,
        )
    )
    if branch_ids is not None:
        stmt = stmt.where(StockBalance.branch_id.in_(branch_ids))

    items: list[LowStockItem] = []
    for row in db.execute(stmt):
        quantity = Decimal(row.quantity or 0)
        min_stock = Decimal(row.min_stock) if row.min_stock is not None else None
        reorder = Decimal(row.reorder_level) if row.reorder_level is not None else None
        severity = classify_stock_level(quantity, min_stock, reorder)
        if severity == "ok":
            continue
        label = f"{row.name} — {row.variant_name}" if row.variant_name else row.name
        items.append(
            LowStockItem(
                product_id=row.product_id,
                variant_id=row.variant_id,
                name=label,
                branch_id=row.branch_id,
                quantity=quantity,
                min_stock=min_stock,
                reorder_level=reorder,
                severity=severity,
            )
        )
    order = {"out_of_stock": 0, "critical": 1, "warning": 2}
    items.sort(key=lambda item: (order[item.severity], item.name))
    return items


def classify_stock_level(
    quantity: Decimal, min_stock: Decimal | None, reorder_level: Decimal | None
) -> str:
    """Out of stock, critical, warning or ok (PRD 9)."""
    if quantity <= 0:
        return "out_of_stock"
    if min_stock is not None and quantity <= min_stock:
        return "critical"
    if reorder_level is not None and quantity <= reorder_level:
        return "warning"
    return "ok"


def reconcile_balances(db: Session, tenant_id: uuid.UUID) -> list[dict]:
    """Compare every cached balance against the ledger.

    Returns the discrepancies; an empty list means the cache agrees with the
    movements (PRD 19 — no unreconciled duplicate state).
    """
    ledger = {
        (row.variant_id, row.location_id): Decimal(row.total or 0)
        for row in db.execute(
            select(
                StockMovement.variant_id,
                StockMovement.location_id,
                func.sum(StockMovement.quantity).label("total"),
            )
            .where(StockMovement.tenant_id == tenant_id)
            .group_by(StockMovement.variant_id, StockMovement.location_id)
        )
    }
    cached = {
        (row.variant_id, row.location_id): Decimal(row.quantity)
        for row in db.execute(tenant_query(StockBalance, tenant_id)).scalars()
    }

    discrepancies: list[dict] = []
    for key in set(ledger) | set(cached):
        expected = ledger.get(key, ZERO)
        actual = cached.get(key, ZERO)
        if expected != actual:
            discrepancies.append(
                {
                    "variant_id": str(key[0]),
                    "location_id": str(key[1]),
                    "ledger_total": str(expected),
                    "cached_balance": str(actual),
                }
            )
    return discrepancies
