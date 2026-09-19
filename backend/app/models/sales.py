"""Sales, sale lines and the single payment ledger (PRD 10, 11.6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import GUID, Base, Money, Percent, Quantity, UTCDateTime
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


class SaleStatus(StrEnum):
    COMPLETED = "completed"
    #: Reversed with compensating stock movements; history is preserved (PRD 1).
    VOIDED = "voided"


class PaymentMethod(StrEnum):
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    TELEBIRR = "telebirr"
    CBE_BIRR = "cbe_birr"
    MOBILE_MONEY = "mobile_money"
    CARD = "card"
    CHEQUE = "cheque"
    OTHER = "other"


class PaymentDirection(StrEnum):
    #: Money received from a customer.
    IN = "in"
    #: Money paid to a supplier.
    OUT = "out"


class Sale(UUIDPrimaryKey, Timestamped, TenantScoped, Auditable, Base):
    """A completed sale.  Prices, discounts, tax and cost are snapshotted so
    later catalogue edits never rewrite history (PRD 8.2, 10)."""

    __tablename__ = "sales"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_sales_tenant_number"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_sales_tenant_idempotency"),
        Index("ix_sales_tenant_sold_at", "tenant_id", "sold_at"),
        Index("ix_sales_tenant_branch", "tenant_id", "branch_id"),
    )

    number: Mapped[str] = mapped_column(CodeText, nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("stock_locations.id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("customers.id", ondelete="SET NULL"), index=True
    )
    salesperson_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[SaleStatus] = mapped_column(
        enum_column(SaleStatus), default=SaleStatus.COMPLETED, nullable=False
    )
    sold_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    subtotal: Mapped[Decimal] = mapped_column(Money, nullable=False)
    discount_total: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    tax_total: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    #: Sum of sale-time unit costs — the basis for profit reporting (PRD 15).
    cost_total: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="ETB", nullable=False)

    note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(160), doc="Caller key, or a composite key derived from the source document"
    )

    voided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    voided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    void_reason: Mapped[str | None] = mapped_column(MediumText)

    lines: Mapped[list[SaleLine]] = relationship(
        back_populates="sale", cascade="all, delete-orphan", lazy="selectin"
    )
    payments: Mapped[list[Payment]] = relationship(
        back_populates="sale", lazy="selectin", foreign_keys="Payment.sale_id"
    )

    @property
    def amount_paid(self) -> Decimal:
        return sum(
            (Decimal(p.amount) for p in self.payments if not p.is_reversed),
            Decimal("0.00"),
        )

    @property
    def balance_due(self) -> Decimal:
        return Decimal(self.total_amount) - self.amount_paid

    @property
    def gross_profit(self) -> Decimal:
        return Decimal(self.total_amount) - Decimal(self.tax_total) - Decimal(self.cost_total)


class SaleLine(UUIDPrimaryKey, Base):
    __tablename__ = "sale_lines"
    __table_args__ = (Index("ix_sale_lines_sale", "sale_id"),)

    sale_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("sales.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    #: Name as it was at sale time, so receipts reprint faithfully.
    description: Mapped[str] = mapped_column(MediumText, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Percent, default=0, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    #: Cost snapshot at sale time (PRD 10).
    unit_cost: Mapped[Decimal | None] = mapped_column(Money)
    discount_approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )

    sale: Mapped[Sale] = relationship(back_populates="lines")

    @property
    def cost_total(self) -> Decimal:
        return Decimal(self.unit_cost or 0) * Decimal(self.quantity)


class Payment(UUIDPrimaryKey, Timestamped, TenantScoped, Auditable, Base):
    """One money ledger for sales, purchases and credit settlement.

    A payment may reference the sale or purchase it was taken against and the
    credit transaction it settles; balances are always derived from these rows
    so no two tables track the same money independently (PRD 19).
    """

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_payments_tenant_idempotency"),
        Index("ix_payments_tenant_paid_at", "tenant_id", "paid_at"),
        Index("ix_payments_credit_transaction", "credit_transaction_id"),
    )

    direction: Mapped[PaymentDirection] = mapped_column(
        enum_column(PaymentDirection), nullable=False
    )
    method: Mapped[PaymentMethod] = mapped_column(enum_column(PaymentMethod), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="ETB", nullable=False)
    paid_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("branches.id", ondelete="SET NULL"), index=True
    )

    sale_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("sales.id", ondelete="CASCADE"), index=True
    )
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("purchases.id", ondelete="CASCADE"), index=True
    )
    credit_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("credit_transactions.id", ondelete="CASCADE")
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("customers.id", ondelete="SET NULL")
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("suppliers.id", ondelete="SET NULL")
    )

    reference: Mapped[str | None] = mapped_column(ShortText)
    note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(160), doc="Caller key, or a composite key derived from the source document"
    )

    #: Corrections keep the original row and mark it reversed (PRD 11.6).
    is_reversed: Mapped[bool] = mapped_column(default=False, nullable=False)
    reversed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reversed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    reversal_reason: Mapped[str | None] = mapped_column(MediumText)

    sale: Mapped[Sale | None] = relationship(back_populates="payments", foreign_keys=[sale_id])
    credit_transaction: Mapped[CreditTransaction | None] = relationship(  # noqa: F821
        back_populates="payments", foreign_keys=[credit_transaction_id]
    )
