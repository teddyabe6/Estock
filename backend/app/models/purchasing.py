"""Purchases and goods receipt (PRD 11.2, A3)."""

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
    TenantScoped,
    Timestamped,
    UUIDPrimaryKey,
    enum_column,
)


class PurchaseStatus(StrEnum):
    RECEIVED = "received"
    CANCELLED = "cancelled"


class Purchase(UUIDPrimaryKey, Timestamped, TenantScoped, Auditable, Base):
    """A stock receipt with its costs.  Receiving posts stock exactly once and,
    where the amount paid is short, creates a single payable (PRD 11.2)."""

    __tablename__ = "purchases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_purchases_tenant_number"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_purchases_tenant_idempotency"),
        Index("ix_purchases_tenant_received", "tenant_id", "received_at"),
    )

    number: Mapped[str] = mapped_column(CodeText, nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("suppliers.id", ondelete="SET NULL"), index=True
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("stock_locations.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[PurchaseStatus] = mapped_column(
        enum_column(PurchaseStatus), default=PurchaseStatus.RECEIVED, nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    goods_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    #: Shared costs entered once and allocated across the lines (PRD 8.2).
    transport_cost: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    other_costs: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="ETB", nullable=False)
    #: ``by_value`` or ``by_quantity`` — recorded so a landed cost can be explained.
    cost_allocation_method: Mapped[str] = mapped_column(
        String(24), default="by_value", nullable=False
    )

    supplier_invoice_ref: Mapped[str | None] = mapped_column(MediumText)
    note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(160), doc="Caller key, or a composite key derived from the source document"
    )

    lines: Mapped[list[PurchaseLine]] = relationship(
        back_populates="purchase", cascade="all, delete-orphan", lazy="selectin"
    )
    #: Money paid out against this receipt — the same ledger rows the payable reads.
    payments: Mapped[list[Payment]] = relationship(  # noqa: F821
        lazy="selectin", foreign_keys="Payment.purchase_id"
    )

    @property
    def amount_paid(self) -> Decimal:
        return sum(
            (Decimal(p.amount) for p in self.payments if not p.is_reversed), Decimal("0.00")
        )

    @property
    def balance_due(self) -> Decimal:
        return Decimal(self.total_amount) - self.amount_paid


class PurchaseLine(UUIDPrimaryKey, Base):
    __tablename__ = "purchase_lines"
    __table_args__ = (Index("ix_purchase_lines_purchase", "purchase_id"),)

    purchase_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("purchases.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    description: Mapped[str] = mapped_column(MediumText, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False)
    #: Share of the purchase's transport and other costs assigned to this line.
    allocated_cost: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Money, nullable=False)

    purchase: Mapped[Purchase] = relationship(back_populates="lines")

    @property
    def landed_unit_cost(self) -> Decimal:
        """Unit cost including this line's share of shared costs (PRD 8.2)."""
        quantity = Decimal(self.quantity)
        if quantity == 0:
            return Decimal(self.unit_cost)
        return Decimal(self.unit_cost) + (Decimal(self.allocated_cost) / quantity)
