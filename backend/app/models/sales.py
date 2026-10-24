"""Sales, sale lines and the single payment ledger (PRD 10, 11.6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
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
    #: Value taken off what a customer owed, rather than money moving.  Returns
    #: against an unpaid credit sale settle the receivable this way, so the
    #: single payment ledger still holds every movement of value while cash
    #: reports can tell it apart from money through the till.
    CREDIT_NOTE = "credit_note"
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
    #: Money paid to a supplier, or refunded to a customer.
    OUT = "out"


class RefundMethod(StrEnum):
    """Where the value of a return goes.

    A customer who still owes money on the sale is not handed cash; the return
    comes off what they owe first.  ``MIXED`` is the common case on a part-paid
    credit sale: some against the balance, the rest back in their hand.
    """

    #: Money handed back, by the sale's original method unless told otherwise.
    CASH = "cash"
    #: Taken off an outstanding receivable for this sale.
    CREDIT = "credit"
    #: Some of each.
    MIXED = "mixed"
    #: Nothing moved.  The goods came back but there was no balance to credit
    #: and nothing had been paid to refund — a sale whose debt was written off,
    #: for instance.  The customer is not owed money the business never took.
    NONE = "none"


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
    returns: Mapped[list[SaleReturn]] = relationship(
        back_populates="sale", lazy="selectin", order_by="SaleReturn.returned_at"
    )

    @property
    def amount_paid(self) -> Decimal:
        """Money received less money refunded, so a refund does not read as paid."""
        total = Decimal("0.00")
        for payment in self.payments:
            if payment.is_reversed:
                continue
            amount = Decimal(payment.amount)
            total += amount if payment.direction == PaymentDirection.IN else -amount
        return total

    @property
    def returned_total(self) -> Decimal:
        """What has been taken back, at the prices this sale charged."""
        return sum(
            (Decimal(r.total_amount) for r in self.returns), Decimal("0.00")
        )

    @property
    def effective_total(self) -> Decimal:
        """What the customer is liable for after returns."""
        return Decimal(self.total_amount) - self.returned_total

    @property
    def balance_due(self) -> Decimal:
        """Still owed: what is kept, less what has been settled or refunded."""
        return self.effective_total - self.amount_paid

    @property
    def returned_cost(self) -> Decimal:
        """Sale-time cost of the returned units."""
        return sum((Decimal(r.cost_total) for r in self.returns), Decimal("0.00"))

    @property
    def gross_profit(self) -> Decimal:
        """Profit on this sale as it stands, with returns taken back out.

        Reports aggregate returns separately rather than reading this, so the
        figures stay explainable; this is the per-sale answer.
        """
        return (
            self.effective_total
            - (Decimal(self.tax_total) - self.returned_tax)
            - (Decimal(self.cost_total) - self.returned_cost)
        )

    @property
    def returned_tax(self) -> Decimal:
        return sum((Decimal(r.tax_total) for r in self.returns), Decimal("0.00"))


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


class SaleReturn(UUIDPrimaryKey, Timestamped, TenantScoped, Auditable, Base):
    """Goods coming back, and the value going back with them (PRD 1, 10).

    A return is its own document, not an edit of the sale.  The sale's lines,
    prices and cost snapshots are what was agreed and stay exactly as they
    were; what came back, when, who took it and what it was worth lives here.
    A sale may have several returns, and the quantity returned across all of
    them can never pass the quantity sold.

    The amounts are what the customer is owed for the goods, carried from the
    sale's own prices — never recomputed from the catalogue, which may have
    moved since.  ``cost_total`` is the sale-time cost of the returned units,
    so profit reporting can take back exactly what it recognised.
    """

    __tablename__ = "sale_returns"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_sale_returns_tenant_number"),
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_sale_returns_tenant_idempotency"
        ),
        Index("ix_sale_returns_tenant_returned_at", "tenant_id", "returned_at"),
        Index("ix_sale_returns_sale", "sale_id"),
    )

    number: Mapped[str] = mapped_column(CodeText, nullable=False)
    sale_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("sales.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("stock_locations.id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("customers.id", ondelete="SET NULL"), index=True
    )
    returned_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    reason: Mapped[str] = mapped_column(MediumText, nullable=False)

    subtotal: Mapped[Decimal] = mapped_column(Money, nullable=False)
    discount_total: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    tax_total: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    #: What the returned goods are worth to the customer, tax included.
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    #: Sale-time cost of the returned units, for profit reporting (PRD 15).
    cost_total: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="ETB", nullable=False)

    refund_method: Mapped[RefundMethod] = mapped_column(
        enum_column(RefundMethod), default=RefundMethod.NONE, nullable=False
    )
    #: Money actually handed back, as a Payment row with direction OUT.
    refunded_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    #: Value taken off what the customer still owed on this sale.
    credited_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)

    note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(160), doc="Caller key, so an offline or retried return posts once"
    )

    lines: Mapped[list[SaleReturnLine]] = relationship(
        back_populates="sale_return", cascade="all, delete-orphan", lazy="selectin"
    )
    sale: Mapped[Sale] = relationship(back_populates="returns")

    @property
    def net_amount(self) -> Decimal:
        """Value excluding tax — the figure that comes off net sales."""
        return Decimal(self.total_amount) - Decimal(self.tax_total)


class SaleReturnLine(UUIDPrimaryKey, Base):
    """One sale line coming back, in whole or in part.

    Prices, discount share, tax share and unit cost are carried from the sale
    line rather than recomputed, so a return is always worth what the customer
    actually paid for those units.
    """

    __tablename__ = "sale_return_lines"
    __table_args__ = (
        Index("ix_sale_return_lines_return", "sale_return_id"),
        Index("ix_sale_return_lines_sale_line", "sale_line_id"),
    )

    sale_return_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("sale_returns.id", ondelete="CASCADE"), nullable=False
    )
    sale_line_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("sale_lines.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    description: Mapped[str] = mapped_column(MediumText, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    #: The returned quantity's share of the line's discount.
    discount_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Percent, default=0, nullable=False)
    #: The returned quantity's share of the line's tax.
    tax_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    #: Carried from the sale line, never from the catalogue (PRD 10).
    unit_cost: Mapped[Decimal | None] = mapped_column(Money)
    #: False when the goods are not fit to sell again.  They still come back on
    #: the ledger and are then written off, so the damage is a movement with a
    #: reason rather than a silent absence.
    restock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sale_return: Mapped[SaleReturn] = relationship(back_populates="lines")

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
