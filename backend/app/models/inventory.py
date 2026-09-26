"""Stock ledger, balances, transfers and counts (PRD 9).

``StockMovement`` is the append-only source of truth.  ``StockBalance`` is a
cached per-(variant, location) total maintained inside the same transaction as
the movement that changes it; ``app.services.inventory.reconcile_balances``
recomputes it from the ledger and is exercised by the test-suite.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import GUID, Base, Money, Quantity, UTCDateTime
from app.models.base import (
    Auditable,
    CodeText,
    MediumText,
    ShortText,
    TenantScoped,
    Timestamped,
    UUIDPrimaryKey,
    enum_column,
)


class MovementReason(StrEnum):
    """Why stock moved.  Sign is carried by the quantity, not the reason."""

    OPENING = "opening"
    PURCHASE = "purchase"
    SALE = "sale"
    SALE_RETURN = "sale_return"
    PURCHASE_RETURN = "purchase_return"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    ADJUSTMENT = "adjustment"
    COUNT_ADJUSTMENT = "count_adjustment"
    DAMAGE = "damage"
    LOSS = "loss"
    SALE_VOID = "sale_void"


#: Reasons that may only ever add stock, and those that may only remove it.
STOCK_IN_REASONS = frozenset(
    {
        MovementReason.OPENING,
        MovementReason.PURCHASE,
        MovementReason.SALE_RETURN,
        MovementReason.TRANSFER_IN,
        MovementReason.SALE_VOID,
    }
)
STOCK_OUT_REASONS = frozenset(
    {
        MovementReason.SALE,
        MovementReason.PURCHASE_RETURN,
        MovementReason.TRANSFER_OUT,
        MovementReason.DAMAGE,
        MovementReason.LOSS,
    }
)


class TransferStatus(StrEnum):
    DRAFT = "draft"
    DISPATCHED = "dispatched"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class StockCountStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    POSTED = "posted"
    CANCELLED = "cancelled"


class StockMovement(UUIDPrimaryKey, TenantScoped, Auditable, Base):
    """Immutable ledger entry.  Never updated or deleted."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_stock_movements_variant_location", "variant_id", "location_id"),
        Index("ix_stock_movements_tenant_occurred", "tenant_id", "occurred_at"),
        Index("ix_stock_movements_source", "source_type", "source_id"),
        # Guards against a retried request posting the same effect twice (PRD 20).
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_stock_movements_tenant_idempotency"
        ),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("stock_locations.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: Signed: positive adds stock, negative removes it.
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    #: Balance at this location after the movement, for fast history display.
    balance_after: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    reason: Mapped[MovementReason] = mapped_column(enum_column(MovementReason), nullable=False)
    #: Unit cost attributed to this movement, used for valuation and profit.
    unit_cost: Mapped[Decimal | None] = mapped_column(Money)
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    #: What caused the movement, e.g. ``sale``/``purchase``/``transfer``/``count``.
    source_type: Mapped[str | None] = mapped_column(CodeText)
    source_id: Mapped[uuid.UUID | None] = mapped_column(GUID)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(160), doc="Caller key, or a composite key derived from the source document"
    )


class StockBalance(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """Cached on-hand quantity per variant and location."""

    __tablename__ = "stock_balances"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "variant_id", "location_id", name="uq_stock_balances_variant_location"
        ),
        Index("ix_stock_balances_tenant_branch", "tenant_id", "branch_id"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("stock_locations.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, default=0, nullable=False)


class StockTransfer(UUIDPrimaryKey, Timestamped, TenantScoped, Auditable, Base):
    """Movement of stock between locations, with linked out and in entries."""

    __tablename__ = "stock_transfers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_stock_transfers_tenant_reference"),
    )

    reference: Mapped[str] = mapped_column(CodeText, nullable=False)
    from_location_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("stock_locations.id", ondelete="RESTRICT"), nullable=False
    )
    to_location_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("stock_locations.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[TransferStatus] = mapped_column(
        enum_column(TransferStatus), default=TransferStatus.DRAFT, nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    dispatched_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    received_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list[StockTransferLine]] = relationship(
        back_populates="transfer", cascade="all, delete-orphan", lazy="selectin"
    )


class StockTransferLine(UUIDPrimaryKey, Base):
    __tablename__ = "stock_transfer_lines"

    transfer_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("stock_transfers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_sent: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    #: Set at receipt; a shortfall against ``quantity_sent`` is posted as an
    #: explicit loss movement at the destination (PRD 9).
    quantity_received: Mapped[Decimal | None] = mapped_column(Quantity)
    note: Mapped[str | None] = mapped_column(MediumText)

    transfer: Mapped[StockTransfer] = relationship(back_populates="lines")

    @property
    def discrepancy(self) -> Decimal | None:
        if self.quantity_received is None:
            return None
        return Decimal(self.quantity_received) - Decimal(self.quantity_sent)


class StockCount(UUIDPrimaryKey, Timestamped, TenantScoped, Auditable, Base):
    """A physical count session against one location (PRD 9, A5)."""

    __tablename__ = "stock_counts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_stock_counts_tenant_reference"),
    )

    reference: Mapped[str] = mapped_column(CodeText, nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("stock_locations.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[StockCountStatus] = mapped_column(
        enum_column(StockCountStatus), default=StockCountStatus.IN_PROGRESS, nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    posted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )

    lines: Mapped[list[StockCountLine]] = relationship(
        back_populates="count", cascade="all, delete-orphan", lazy="selectin"
    )


class StockCountLine(UUIDPrimaryKey, Base):
    __tablename__ = "stock_count_lines"
    __table_args__ = (
        UniqueConstraint("count_id", "variant_id", name="uq_stock_count_lines_count_variant"),
    )

    count_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("stock_counts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    #: Snapshot of the system quantity when the line was added.
    expected_quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    counted_quantity: Mapped[Decimal | None] = mapped_column(Quantity)
    reason: Mapped[str | None] = mapped_column(ShortText)
    note: Mapped[str | None] = mapped_column(MediumText)
    counted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    counted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    count: Mapped[StockCount] = relationship(back_populates="lines")

    @property
    def variance(self) -> Decimal | None:
        if self.counted_quantity is None:
            return None
        return Decimal(self.counted_quantity) - Decimal(self.expected_quantity)
