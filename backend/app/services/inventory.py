"""Stock posting, balances, transfers, counts and low-stock detection (PRD 9).

Every change to stock goes through :func:`post_movement`, which appends a ledger
row and updates the cached balance in the same transaction.  Nothing else in the
codebase writes ``StockBalance``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.audit import AuditAction, record_audit
from app.core.db import supports_row_locks, utcnow
from app.core.errors import (
    ConflictError,
    InsufficientStock,
    NotFoundError,
    PermissionDenied,
    ValidationError,
)
from app.core.permissions import Permission
from app.core.tenancy import AuthContext, get_tenant_object, tenant_query
from app.models.catalogue import Product, ProductVariant
from app.models.inventory import (
    OPEN_TRANSFER_STATUSES,
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
from app.models.organisation import Branch, StockLocation
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


def _variant_query(tenant_id: uuid.UUID):
    """Variants with their product joined in.

    ``track_stock`` and ``is_active`` live on the product, so every caller
    reaches for it; joining beats a lazy load per row.  ``product`` is
    many-to-one, so the join adds no duplicate rows.
    """
    return tenant_query(ProductVariant, tenant_id).options(
        joinedload(ProductVariant.product)
    )


def load_variant(db: Session, tenant_id: uuid.UUID, variant_id: uuid.UUID) -> ProductVariant:
    """One variant, or :class:`NotFoundError`."""
    variant = db.execute(
        _variant_query(tenant_id).where(ProductVariant.id == variant_id)
    ).scalar_one_or_none()
    if variant is None:
        raise NotFoundError("Product not found")
    return variant


class MovementRefs:
    """Variants and locations resolved once for an operation posting many movements.

    :func:`post_movement` needs the variant on every call (for ``track_stock``
    and the product id) and the location (for its branch).  An operation that
    posts one movement per line — a sale, a purchase, a transfer, a count —
    was resolving both again for every line, against the same location each
    time, and lazy-loading the variant's product on top of that.

    Prefetching turns that into two queries for the whole operation.  Every
    object still comes through :func:`tenant_query`, so the tenant check is
    exactly where it was; it just happens once instead of once per line.

    Passing no ids keeps the old behaviour: each object is fetched on first
    use and then reused, so callers that post a single movement are unaffected.
    """

    __slots__ = ("_db", "_tenant_id", "_variants", "_locations")

    def __init__(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        *,
        variant_ids: Iterable[uuid.UUID] = (),
        location_ids: Iterable[uuid.UUID] = (),
    ):
        self._db = db
        self._tenant_id = tenant_id
        self._variants: dict[uuid.UUID, ProductVariant] = {}
        self._locations: dict[uuid.UUID, StockLocation] = {}

        wanted_variants = {vid for vid in variant_ids if vid is not None}
        if wanted_variants:
            rows = db.execute(
                _variant_query(tenant_id).where(ProductVariant.id.in_(wanted_variants))
            ).scalars()
            self._variants = {row.id: row for row in rows}

        wanted_locations = {lid for lid in location_ids if lid is not None}
        if wanted_locations:
            rows = db.execute(
                tenant_query(StockLocation, tenant_id).where(
                    StockLocation.id.in_(wanted_locations)
                )
            ).scalars()
            self._locations = {row.id: row for row in rows}

    def get_variant(self, variant_id: uuid.UUID) -> ProductVariant | None:
        """The variant, or ``None`` — for callers that raise their own error."""
        if variant_id not in self._variants:
            found = self._db.execute(
                _variant_query(self._tenant_id).where(ProductVariant.id == variant_id)
            ).scalar_one_or_none()
            if found is None:
                return None
            self._variants[variant_id] = found
        return self._variants[variant_id]

    def variant(self, variant_id: uuid.UUID) -> ProductVariant:
        variant = self.get_variant(variant_id)
        if variant is None:
            raise NotFoundError("Product not found")
        return variant

    def location(self, location_id: uuid.UUID) -> StockLocation:
        if location_id not in self._locations:
            self._locations[location_id] = get_tenant_object(
                self._db,
                StockLocation,
                location_id,
                self._tenant_id,
                label="Stock location",
            )
        return self._locations[location_id]


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
    refs: MovementRefs | None = None,
) -> StockMovement:
    """Append a ledger entry and update the cached balance atomically.

    Refuses to drive stock negative unless the business has explicitly enabled
    it and the actor may approve the exception (PRD 9).

    An operation posting several movements should pass a :class:`MovementRefs`
    prefetched with its variants and locations, so they are resolved once for
    the operation rather than once per movement.
    """
    quantity = Decimal(posting.quantity)
    if quantity == 0:
        raise ValidationError("Stock movement quantity cannot be zero")
    if posting.reason in STOCK_IN_REASONS and quantity < 0:
        raise ValidationError(f"{posting.reason} must increase stock")
    if posting.reason in STOCK_OUT_REASONS and quantity > 0:
        raise ValidationError(f"{posting.reason} must reduce stock")

    refs = refs or MovementRefs(db, ctx.tenant_id)
    variant = refs.variant(posting.variant_id)
    location = refs.location(posting.location_id)

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
    idempotency_key: str | None = None,
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
            idempotency_key=idempotency_key,
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

    refs = MovementRefs(db, ctx.tenant_id, variant_ids=[variant_id for variant_id, _ in lines])
    for variant_id, quantity in lines:
        if Decimal(quantity) <= 0:
            raise ValidationError("Transfer quantities must be positive")
        variant = refs.variant(variant_id)
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


@dataclass(slots=True)
class TransferBranch:
    branch_id: uuid.UUID
    branch_name: str
    #: Where a request to this branch would be filled from.
    location_id: uuid.UUID | None
    #: The caller may operate here, so it can be the receiving end.
    is_mine: bool


def transfer_branches(db: Session, ctx: AuthContext) -> list[TransferBranch]:
    """Every active branch a transfer or a request could involve.

    Names, and nothing else.  A branch cannot ask another for stock without
    knowing that it exists, and within one business a branch's name is not a
    secret — but what it holds is, so no quantity comes back from here
    (PRD 15: no unauthorised cross-branch visibility).
    """
    ctx.require(Permission.STOCK_TRANSFER)
    branches = db.execute(
        tenant_query(Branch, ctx.tenant_id)
        .where(Branch.is_active.is_(True))
        .order_by(Branch.is_default.desc(), Branch.name)
    ).scalars()
    return [
        TransferBranch(
            branch_id=branch.id,
            branch_name=branch.name,
            location_id=(
                branch.default_location.id if branch.default_location is not None else None
            ),
            is_mine=ctx.can_access_branch(branch.id),
        )
        for branch in branches
    ]


def request_transfer(
    db: Session,
    ctx: AuthContext,
    *,
    from_location_id: uuid.UUID,
    to_location_id: uuid.UUID,
    lines: list[tuple[uuid.UUID, Decimal]],
    note: str | None = None,
) -> StockTransfer:
    """Ask another branch for stock, for the owner to allow or refuse (PRD 9).

    The mirror image of :func:`create_transfer`: there, a branch with stock to
    spare sends it; here, a branch that has run out asks for it.  The asking
    branch needs no authority over the branch it is asking — that is the whole
    point — so only the destination is checked against its own assignments.
    Nothing moves yet.
    """
    ctx.require(Permission.STOCK_TRANSFER)
    if not lines:
        raise ValidationError("Add at least one product to the request")

    source = get_tenant_object(
        db, StockLocation, from_location_id, ctx.tenant_id, label="Source location"
    )
    destination = get_tenant_object(
        db, StockLocation, to_location_id, ctx.tenant_id, label="Destination location"
    )
    if source.branch_id == destination.branch_id:
        raise ValidationError(
            "Ask a different branch — stock already in your own branch needs a "
            "transfer, not a request"
        )
    # Only the receiving end: a branch asks for its own shelves.
    ctx.require_branch(destination.branch_id)

    transfer = StockTransfer(
        tenant_id=ctx.tenant_id,
        reference=next_number(db, StockTransfer, ctx.tenant_id, "transfer", column="reference"),
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        status=TransferStatus.REQUESTED,
        note=note,
        requested_at=utcnow(),
        requested_by_id=ctx.user_id,
        created_by_id=ctx.user_id,
    )
    db.add(transfer)
    db.flush()

    refs = MovementRefs(db, ctx.tenant_id, variant_ids=[variant_id for variant_id, _ in lines])
    for variant_id, quantity in lines:
        if Decimal(quantity) <= 0:
            raise ValidationError("Requested quantities must be positive")
        variant = refs.variant(variant_id)
        transfer.lines.append(
            StockTransferLine(
                transfer_id=transfer.id,
                product_id=variant.product_id,
                variant_id=variant_id,
                quantity_sent=Decimal(quantity),
            )
        )
    db.flush()

    record_audit(
        db,
        action=AuditAction.STOCK_TRANSFER_REQUESTED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="stock_transfer",
        entity_id=transfer.id,
        summary=f"Requested {transfer.reference} from {source.name}",
        payload={"lines": len(transfer.lines)},
    )
    _notify_approvers(db, ctx, transfer, source=source, destination=destination)
    return transfer


def approve_transfer(
    db: Session, ctx: AuthContext, transfer_id: uuid.UUID, *, note: str | None = None
) -> StockTransfer:
    """Allow a request, without moving anything (PRD 9).

    Approval and movement are deliberately apart.  Days can pass between the
    two, and only the branch that asked knows whether it still needs the goods
    when the answer finally comes, so it has to accept before the stock leaves
    the shelf it is counted on.
    """
    transfer = _decidable(db, ctx, transfer_id)
    transfer.status = TransferStatus.APPROVED
    transfer.decided_at = utcnow()
    transfer.decided_by_id = ctx.user_id
    transfer.decision_note = (note or "").strip() or None
    record_audit(
        db,
        action=AuditAction.STOCK_TRANSFER_APPROVED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="stock_transfer",
        entity_id=transfer.id,
        summary=f"Approved {transfer.reference}",
        payload={"note": transfer.decision_note},
    )
    _notify_requester(
        db,
        transfer,
        title=f"Stock request {transfer.reference} was approved",
        body=(
            (transfer.decision_note + " · " if transfer.decision_note else "")
            + "Accept it to bring the stock across."
        ),
    )
    db.flush()
    return transfer


def reject_transfer(
    db: Session, ctx: AuthContext, transfer_id: uuid.UUID, *, note: str
) -> StockTransfer:
    """Refuse a request, with the reason the branch that asked will read."""
    if not (note or "").strip():
        raise ValidationError("Say why the request is being refused")
    transfer = _decidable(db, ctx, transfer_id)
    transfer.status = TransferStatus.REJECTED
    transfer.decided_at = utcnow()
    transfer.decided_by_id = ctx.user_id
    transfer.decision_note = note.strip()
    record_audit(
        db,
        action=AuditAction.STOCK_TRANSFER_REJECTED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="stock_transfer",
        entity_id=transfer.id,
        summary=f"Rejected {transfer.reference}",
        payload={"note": transfer.decision_note},
    )
    _notify_requester(
        db,
        transfer,
        title=f"Stock request {transfer.reference} was turned down",
        body=transfer.decision_note,
    )
    db.flush()
    return transfer


def accept_transfer(db: Session, ctx: AuthContext, transfer_id: uuid.UUID) -> StockTransfer:
    """Take up an approved request, moving the stock in one step (PRD 9).

    Both legs post together: the source gives up exactly what the destination
    gains, so no quantity is ever in flight and in nobody's count.  A push
    transfer has a dispatch and a receipt because the goods spend time on a
    lorry; here the branch that asked is saying "yes, now", and the two
    moments are the same one.

    If the source has sold the stock in the meantime, this refuses and the
    request stays approved — the goods simply are not there to take.
    """
    ctx.require(Permission.STOCK_TRANSFER)
    transfer = get_tenant_object(db, StockTransfer, transfer_id, ctx.tenant_id, label="Transfer")
    if transfer.status != TransferStatus.APPROVED:
        raise ConflictError(
            f"Only an approved request can be accepted; this one is {transfer.status}"
        )
    destination = get_tenant_object(
        db, StockLocation, transfer.to_location_id, ctx.tenant_id, label="Destination location"
    )
    # The branch that asked is the branch that accepts.
    ctx.require_branch(destination.branch_id)

    refs = MovementRefs(
        db,
        ctx.tenant_id,
        variant_ids=[line.variant_id for line in transfer.lines],
        location_ids=[transfer.from_location_id, transfer.to_location_id],
    )

    # The whole request is checked before any of it is posted, so a shortfall
    # on the third line cannot leave the first two already moved.  A transfer
    # is one decision and it either happens or it does not.  post_movement
    # refuses each line on its own as well; this only brings the refusal
    # forward, and names the branch that is short.
    if not ctx.tenant.allow_negative_stock:
        source = refs.location(transfer.from_location_id)
        for line in transfer.lines:
            variant = refs.variant(line.variant_id)
            if not variant.product.track_stock:
                continue
            available = get_balance(
                db, ctx.tenant_id, line.variant_id, transfer.from_location_id
            )
            if available < Decimal(line.quantity_sent):
                raise InsufficientStock(
                    f"{source.name} has {available} of {variant.display_name} left, "
                    f"and the request is for {line.quantity_sent}",
                    details={
                        "variant_id": str(line.variant_id),
                        "available": str(available),
                        "requested": str(line.quantity_sent),
                    },
                )

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
            refs=refs,
        )
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
            refs=refs,
        )
        # Nothing was counted in: what was approved is what moved.  A shortfall
        # found afterwards is the destination's own adjustment to make.
        line.quantity_received = Decimal(line.quantity_sent)

    moment = utcnow()
    transfer.status = TransferStatus.RECEIVED
    transfer.accepted_at = moment
    transfer.accepted_by_id = ctx.user_id
    # The same person caused both legs, so both carry their name.
    transfer.dispatched_at = moment
    transfer.dispatched_by_id = ctx.user_id
    transfer.received_at = moment
    transfer.received_by_id = ctx.user_id
    record_audit(
        db,
        action=AuditAction.STOCK_TRANSFER_RECEIVED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="stock_transfer",
        entity_id=transfer.id,
        summary=f"Accepted and completed {transfer.reference}",
    )
    db.flush()
    return transfer


def cancel_transfer(
    db: Session, ctx: AuthContext, transfer_id: uuid.UUID, *, note: str | None = None
) -> StockTransfer:
    """Call off a transfer or request before anything has moved.

    The branch that asked may change its mind, which matters most once a
    request has been approved: "accept" has to have an answer other than yes,
    or an approval nobody wants sits there looking like stock on its way.
    """
    ctx.require(Permission.STOCK_TRANSFER)
    transfer = get_tenant_object(db, StockTransfer, transfer_id, ctx.tenant_id, label="Transfer")
    if transfer.status not in OPEN_TRANSFER_STATUSES:
        raise ConflictError(f"A {transfer.status} transfer cannot be cancelled")

    source = get_tenant_object(
        db, StockLocation, transfer.from_location_id, ctx.tenant_id, label="Source location"
    )
    destination = get_tenant_object(
        db, StockLocation, transfer.to_location_id, ctx.tenant_id, label="Destination location"
    )
    # Either end may call it off, as may anybody who could have decided it.
    if not (
        ctx.can_access_branch(destination.branch_id)
        or ctx.can_access_branch(source.branch_id)
        or ctx.has(Permission.STOCK_TRANSFER_APPROVE)
    ):
        raise PermissionDenied("You do not have access to this transfer")

    transfer.status = TransferStatus.CANCELLED
    if (note or "").strip():
        transfer.decision_note = note.strip()
    record_audit(
        db,
        action=AuditAction.STOCK_TRANSFER_CANCELLED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="stock_transfer",
        entity_id=transfer.id,
        summary=f"Cancelled {transfer.reference}",
        payload={"note": transfer.decision_note},
    )
    db.flush()
    return transfer


def _decidable(db: Session, ctx: AuthContext, transfer_id: uuid.UUID) -> StockTransfer:
    """The request to decide, once the caller is allowed to decide it."""
    ctx.require(Permission.STOCK_TRANSFER_APPROVE)
    transfer = get_tenant_object(db, StockTransfer, transfer_id, ctx.tenant_id, label="Transfer")
    if transfer.status != TransferStatus.REQUESTED:
        raise ConflictError(
            f"Only a request awaiting a decision can be decided; this one is {transfer.status}"
        )
    source = get_tenant_object(
        db, StockLocation, transfer.from_location_id, ctx.tenant_id, label="Source location"
    )
    # The decision spends the source branch's stock, so it belongs to whoever
    # has charge of that branch — not to whoever happens to hold the permission.
    ctx.require_branch(source.branch_id)
    return transfer


def _notify_approvers(
    db: Session,
    ctx: AuthContext,
    transfer: StockTransfer,
    *,
    source: StockLocation,
    destination: StockLocation,
) -> None:
    from app.models.system import NotificationKind
    from app.services.notifications import notify, recipients_for

    for membership in recipients_for(db, ctx.tenant_id, Permission.STOCK_TRANSFER_APPROVE):
        notify(
            db,
            tenant_id=ctx.tenant_id,
            user_id=membership.user_id,
            kind=NotificationKind.STOCK_REQUEST,
            title=f"{destination.name} is asking {source.name} for stock",
            body=(
                f"Request {transfer.reference} · {len(transfer.lines)} item(s)"
                + (f" · {transfer.note}" if transfer.note else "")
            ),
            link="/stock?tab=transfers",
            entity_type="stock_transfer",
            entity_id=transfer.id,
        )
    db.flush()


def _notify_requester(
    db: Session, transfer: StockTransfer, *, title: str, body: str | None
) -> None:
    """Tell whoever asked what came of it.  A request nobody answers is worse
    than a refusal, and a decision nobody hears about is the same thing."""
    if transfer.requested_by_id is None:
        return
    from app.models.system import NotificationKind
    from app.services.notifications import notify

    notify(
        db,
        tenant_id=transfer.tenant_id,
        user_id=transfer.requested_by_id,
        kind=NotificationKind.STOCK_REQUEST_DECIDED,
        title=title,
        body=body,
        link="/stock?tab=transfers",
        entity_type="stock_transfer",
        entity_id=transfer.id,
    )


def visible_transfers(
    db: Session,
    ctx: AuthContext,
    *,
    statuses: list[TransferStatus] | None = None,
    limit: int = 50,
) -> list[StockTransfer]:
    """Transfers and requests the caller has a part in.

    Whoever may decide requests sees all of them, because the decision is
    theirs wherever it is asked for.  Everybody else sees what their own
    branches sent, asked for or were asked for.
    """
    ctx.require(Permission.STOCK_VIEW)
    stmt = tenant_query(StockTransfer, ctx.tenant_id)
    if not ctx.has(Permission.STOCK_TRANSFER_APPROVE):
        mine = (
            select(StockLocation.id)
            .where(
                StockLocation.tenant_id == ctx.tenant_id,
                StockLocation.branch_id.in_(ctx.visible_branch_ids(db)),
            )
            .scalar_subquery()
        )
        stmt = stmt.where(
            or_(
                StockTransfer.from_location_id.in_(mine),
                StockTransfer.to_location_id.in_(mine),
            )
        )
    if statuses:
        stmt = stmt.where(StockTransfer.status.in_(statuses))
    rows = db.execute(
        stmt.order_by(StockTransfer.created_at.desc()).limit(min(limit, 200))
    ).scalars()
    return list(rows)


def dispatch_transfer(db: Session, ctx: AuthContext, transfer_id: uuid.UUID) -> StockTransfer:
    """Remove stock from the source location (PRD 9)."""
    ctx.require(Permission.STOCK_TRANSFER)
    transfer = get_tenant_object(
        db, StockTransfer, transfer_id, ctx.tenant_id, label="Transfer"
    )
    if transfer.status != TransferStatus.DRAFT:
        raise ConflictError(f"Transfer is already {transfer.status}")

    refs = MovementRefs(
        db,
        ctx.tenant_id,
        variant_ids=[line.variant_id for line in transfer.lines],
        location_ids=[transfer.from_location_id],
    )
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
            refs=refs,
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
    refs = MovementRefs(
        db,
        ctx.tenant_id,
        variant_ids=[line.variant_id for line in transfer.lines],
        location_ids=[transfer.to_location_id],
    )
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
            refs=refs,
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
                refs=refs,
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

    variant = load_variant(db, ctx.tenant_id, variant_id)
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
    refs = MovementRefs(
        db,
        ctx.tenant_id,
        variant_ids=[line.variant_id for line in count.lines],
        location_ids=[count.location_id],
    )
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
            refs=refs,
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


# --------------------------------------------------------------------------- #
# Opening stock for a branch that has just been created
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class BranchStockSetup:
    """A branch where nothing has been recorded yet, and the size of the job."""

    branch_id: uuid.UUID
    branch_name: str
    location_id: uuid.UUID | None
    #: Stocked products in the catalogue, all of them waiting to be counted.
    product_count: int


def branches_awaiting_opening_stock(
    db: Session, ctx: AuthContext
) -> list[BranchStockSetup]:
    """Visible branches with no stock movement of any kind against them.

    Derived from the absence of movements rather than stored as a flag on the
    branch.  A flag would have to be cleared by whatever first touched the
    stock — a receipt, a transfer, a sale — and any path that forgot would
    leave the business nagged forever.  The ledger already knows, and the
    moment a single quantity is recorded the question has been answered.

    A business with no stocked products yet is not asked: there is nothing to
    count, and the catalogue comes first.
    """
    if not ctx.has(Permission.STOCK_VIEW):
        return []
    visible = ctx.visible_branch_ids(db)
    if not visible:
        return []

    product_count = db.execute(
        select(func.count())
        .select_from(ProductVariant)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(
            Product.tenant_id == ctx.tenant_id,
            Product.track_stock.is_(True),
            Product.is_active.is_(True),
            ProductVariant.is_active.is_(True),
        )
    ).scalar_one()
    if not product_count:
        return []

    touched = {
        row[0]
        for row in db.execute(
            select(StockMovement.branch_id)
            .where(
                StockMovement.tenant_id == ctx.tenant_id,
                StockMovement.branch_id.in_(visible),
            )
            .distinct()
        )
    }
    branches = db.execute(
        tenant_query(Branch, ctx.tenant_id)
        .where(Branch.id.in_(visible), Branch.is_active.is_(True))
        .order_by(Branch.is_default.desc(), Branch.name)
    ).scalars()
    return [
        BranchStockSetup(
            branch_id=branch.id,
            branch_name=branch.name,
            location_id=(
                branch.default_location.id if branch.default_location is not None else None
            ),
            product_count=product_count,
        )
        for branch in branches
        if branch.id not in touched
    ]


@dataclass(slots=True)
class OpeningSheetRow:
    product_id: uuid.UUID
    variant_id: uuid.UUID
    name: str
    sku: str | None
    unit: str
    #: What this location is recorded as holding now.  Shown so that a second
    #: pass through the guide corrects the figures rather than doubling them.
    quantity: Decimal


@dataclass(slots=True)
class OpeningSheet:
    branch_id: uuid.UUID
    branch_name: str
    location_id: uuid.UUID
    location_name: str
    rows: list[OpeningSheetRow]
    #: Products matching the filter, of which ``rows`` is one page.
    total_rows: int
    #: Products already carrying a quantity here, against the catalogue total,
    #: so the guide can say how much of the walk is left.
    recorded: int
    product_count: int


def opening_sheet(
    db: Session,
    ctx: AuthContext,
    *,
    branch_id: uuid.UUID,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> OpeningSheet:
    """Every product a branch could stock, with what it is recorded as holding.

    One location — the branch's default — because the guide asks for counted
    quantities and posts the difference, and a difference only makes sense
    against the shelf it is measured from.  A branch with a second location
    records that one through a count or a transfer, not through this.
    """
    ctx.require(Permission.STOCK_VIEW)
    ctx.require_branch(branch_id)
    branch = get_tenant_object(db, Branch, branch_id, ctx.tenant_id, label="Branch")
    location = branch.default_location
    if location is None:
        raise ValidationError(f"{branch.name} has no stock location to record against")

    catalogue = [
        Product.tenant_id == ctx.tenant_id,
        Product.track_stock.is_(True),
        Product.is_active.is_(True),
        ProductVariant.is_active.is_(True),
    ]
    matching = (
        select(
            ProductVariant.id,
            ProductVariant.product_id,
            ProductVariant.name.label("variant_name"),
            ProductVariant.sku,
            Product.name,
            Product.unit_of_measure,
        )
        .join(Product, Product.id == ProductVariant.product_id)
        .where(*catalogue)
    )
    if q and q.strip():
        matching = matching.where(func.lower(Product.name).like(f"%{q.strip().lower()}%"))

    total_rows = db.execute(
        select(func.count()).select_from(matching.subquery())
    ).scalar_one()
    page = db.execute(
        matching.order_by(Product.name, ProductVariant.sort_order, ProductVariant.id)
        .limit(limit)
        .offset(offset)
    ).all()

    held: dict[uuid.UUID, Decimal] = {}
    if page:
        for row in db.execute(
            select(StockBalance.variant_id, StockBalance.quantity).where(
                StockBalance.tenant_id == ctx.tenant_id,
                StockBalance.location_id == location.id,
                StockBalance.variant_id.in_([r.id for r in page]),
            )
        ):
            held[row.variant_id] = Decimal(row.quantity or 0)

    product_count = db.execute(
        select(func.count())
        .select_from(ProductVariant)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(*catalogue)
    ).scalar_one()
    recorded = db.execute(
        select(func.count())
        .select_from(StockBalance)
        .join(Product, Product.id == StockBalance.product_id)
        .join(ProductVariant, ProductVariant.id == StockBalance.variant_id)
        .where(
            *catalogue,
            StockBalance.tenant_id == ctx.tenant_id,
            StockBalance.location_id == location.id,
            StockBalance.quantity != 0,
        )
    ).scalar_one()

    return OpeningSheet(
        branch_id=branch.id,
        branch_name=branch.name,
        location_id=location.id,
        location_name=location.name,
        rows=[
            OpeningSheetRow(
                product_id=row.product_id,
                variant_id=row.id,
                name=f"{row.name} — {row.variant_name}" if row.variant_name else row.name,
                sku=row.sku,
                unit=row.unit_of_measure,
                quantity=held.get(row.id, ZERO),
            )
            for row in page
        ],
        total_rows=total_rows,
        recorded=recorded,
        product_count=product_count,
    )


def record_opening_stock(
    db: Session,
    ctx: AuthContext,
    *,
    branch_id: uuid.UUID,
    counted: list[tuple[uuid.UUID, Decimal]],
    note: str | None = None,
    idempotency_key: str | None = None,
) -> list[StockMovement]:
    """Set what a branch holds from counted quantities (PRD 8.3, 9).

    The guide collects what is on the shelf, not what changed, because that is
    the only question somebody walking a new branch can answer.  The difference
    against what is already recorded is what gets posted, so a quantity that is
    already right posts nothing and a second pass corrects rather than doubles.

    Every line lands in the ledger with a reason, an actor and a note, like any
    other adjustment — opening stock is never a silently written balance.
    """
    ctx.require(Permission.STOCK_ADJUST)
    ctx.require_branch(branch_id)
    branch = get_tenant_object(db, Branch, branch_id, ctx.tenant_id, label="Branch")
    location = branch.default_location
    if location is None:
        raise ValidationError(f"{branch.name} has no stock location to record against")
    if not counted:
        raise ValidationError("Enter a quantity for at least one product")

    reason_note = (note or "").strip() or f"Opening stock for {branch.name}"
    posted: list[StockMovement] = []
    for variant_id, quantity in counted:
        quantity = Decimal(quantity)
        if quantity < 0:
            raise ValidationError("A counted quantity cannot be negative")
        difference = quantity - get_balance(db, ctx.tenant_id, variant_id, location.id)
        if difference == 0:
            continue
        posted.append(
            adjust_stock(
                db,
                ctx,
                variant_id=variant_id,
                location_id=location.id,
                quantity=difference,
                # Stock appearing at a branch for the first time is its opening
                # balance; a correction downwards cannot be, because opening is
                # one of the reasons that may only ever add (STOCK_IN_REASONS).
                reason=(
                    MovementReason.OPENING if difference > 0 else MovementReason.ADJUSTMENT
                ),
                note=reason_note,
                idempotency_key=(
                    f"opening:{idempotency_key}:{variant_id}" if idempotency_key else None
                ),
            )
        )
    db.flush()
    return posted


# --------------------------------------------------------------------------- #
# The owner's view across branches
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class BranchColumn:
    """One branch in the overview, with everything it holds."""

    branch_id: uuid.UUID
    name: str
    is_default: bool
    total: Decimal


@dataclass(slots=True)
class OverviewRow:
    product_id: uuid.UUID
    variant_id: uuid.UUID
    name: str
    sku: str | None
    unit: str
    min_stock: Decimal | None
    reorder_level: Decimal | None
    #: Quantity at each branch in the overview, including the zeroes.
    quantities: dict[uuid.UUID, Decimal]
    total: Decimal
    status: str


@dataclass(slots=True)
class StockOverview:
    branches: list[BranchColumn]
    rows: list[OverviewRow]
    grand_total: Decimal
    #: Products matching the filter, of which ``rows`` is one page.  The branch
    #: and grand totals cover all of them, not just the page.
    total_rows: int


def _overview_scope(tenant_id: uuid.UUID, q: str | None) -> list:
    """What counts as a stocked product for the overview."""
    conditions = [Product.tenant_id == tenant_id, Product.track_stock.is_(True)]
    if q and q.strip():
        conditions.append(func.lower(Product.name).like(f"%{q.strip().lower()}%"))
    return conditions


def stock_overview(
    db: Session,
    ctx: AuthContext,
    *,
    branch_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> StockOverview:
    """Every stocked product against every branch the caller may see (PRD 9, 15).

    Driven from the catalogue rather than from the balances, because a branch
    that has never recorded a movement has no balance rows at all — and "none
    of it has reached the new branch yet" is exactly what somebody opens this
    to find out.  A branch therefore always gets a column, and a product
    always gets a cell in it, even when the honest answer is zero.
    """
    ctx.require(Permission.STOCK_VIEW)
    visible = ctx.visible_branch_ids(db)
    if branch_id is not None:
        ctx.require_branch(branch_id)
        visible = [branch_id] if branch_id in visible else []

    columns = {
        row.id: BranchColumn(
            branch_id=row.id, name=row.name, is_default=row.is_default, total=ZERO
        )
        for row in db.execute(
            select(Branch.id, Branch.name, Branch.is_default)
            .where(Branch.tenant_id == ctx.tenant_id, Branch.id.in_(visible))
            .order_by(Branch.is_default.desc(), Branch.name)
        )
    }

    scope = _overview_scope(ctx.tenant_id, q)
    stocked_somewhere = (
        select(StockBalance.variant_id)
        .where(
            StockBalance.tenant_id == ctx.tenant_id,
            StockBalance.branch_id.in_(visible),
            StockBalance.quantity != 0,
        )
        .scalar_subquery()
    )
    matching = (
        select(
            ProductVariant.id,
            ProductVariant.product_id,
            ProductVariant.name.label("variant_name"),
            ProductVariant.sku,
            ProductVariant.min_stock,
            ProductVariant.reorder_level,
            Product.name,
            Product.unit_of_measure,
        )
        .join(Product, Product.id == ProductVariant.product_id)
        .where(
            *scope,
            # Stock sitting on a shelf belongs in a stock overview even if the
            # product has since been deactivated; one that is deactivated and
            # empty is just clutter.
            or_(
                and_(Product.is_active.is_(True), ProductVariant.is_active.is_(True)),
                ProductVariant.id.in_(stocked_somewhere),
            ),
        )
    )
    total_rows = db.execute(
        select(func.count()).select_from(matching.subquery())
    ).scalar_one()
    page = db.execute(
        matching.order_by(Product.name, ProductVariant.sort_order, ProductVariant.id)
        .limit(limit)
        .offset(offset)
    ).all()

    cells: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = {}
    if page and visible:
        for cell in db.execute(
            select(
                StockBalance.variant_id,
                StockBalance.branch_id,
                func.sum(StockBalance.quantity).label("quantity"),
            )
            .where(
                StockBalance.tenant_id == ctx.tenant_id,
                StockBalance.variant_id.in_([row.id for row in page]),
                StockBalance.branch_id.in_(visible),
            )
            .group_by(StockBalance.variant_id, StockBalance.branch_id)
        ):
            cells[(cell.variant_id, cell.branch_id)] = Decimal(cell.quantity or 0)

    rows: list[OverviewRow] = []
    for row in page:
        quantities = {
            column.branch_id: cells.get((row.id, column.branch_id), ZERO)
            for column in columns.values()
        }
        total = sum(quantities.values(), ZERO)
        min_stock = Decimal(row.min_stock) if row.min_stock is not None else None
        reorder = Decimal(row.reorder_level) if row.reorder_level is not None else None
        rows.append(
            OverviewRow(
                product_id=row.product_id,
                variant_id=row.id,
                name=f"{row.name} — {row.variant_name}" if row.variant_name else row.name,
                sku=row.sku,
                unit=row.unit_of_measure,
                min_stock=min_stock,
                reorder_level=reorder,
                quantities=quantities,
                total=total,
                # Against the whole business: an item is only really short when
                # no branch has any to send.
                status=classify_stock_level(total, min_stock, reorder),
            )
        )

    # The column and grand totals cover every matching product, not the page,
    # so paging through the list never changes what the business holds.
    if visible:
        for branch_total in db.execute(
            select(
                StockBalance.branch_id,
                func.sum(StockBalance.quantity).label("quantity"),
            )
            .join(Product, Product.id == StockBalance.product_id)
            .where(
                *scope,
                StockBalance.tenant_id == ctx.tenant_id,
                StockBalance.branch_id.in_(visible),
            )
            .group_by(StockBalance.branch_id)
        ):
            column = columns.get(branch_total.branch_id)
            if column is not None:
                column.total = Decimal(branch_total.quantity or 0)

    return StockOverview(
        branches=list(columns.values()),
        rows=rows,
        grand_total=sum((column.total for column in columns.values()), ZERO),
        total_rows=total_rows,
    )


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
