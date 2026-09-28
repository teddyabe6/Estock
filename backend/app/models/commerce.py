"""Online catalogue, enquiries and proformas (PRD 13, 14).

An enquiry or proforma never reserves or reduces stock; only an explicit
conversion to a sale does (PRD 13, 14).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, Text, UniqueConstraint
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


class EnquiryStatus(StrEnum):
    NEW = "new"
    IN_REVIEW = "in_review"
    QUOTED = "quoted"
    CLOSED = "closed"


class QuotationStatus(StrEnum):
    #: Requested by a customer from the storefront basket; awaiting the seller's
    #: review before it is sent (PRD 13, 14).
    REQUESTED = "requested"
    DRAFT = "draft"
    SENT = "sent"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    #: Turned into a sale through the explicit conversion step.
    CONVERTED = "converted"
    CANCELLED = "cancelled"


class CheckoutKind(StrEnum):
    ORDER = "order"
    PROFORMA = "proforma"


class OrderStatus(StrEnum):
    #: Placed by the customer; the shop has not confirmed it yet.
    PLACED = "placed"
    #: The shop confirmed prices and delivery.
    CONFIRMED = "confirmed"
    #: Ready for pickup, or out for delivery.
    READY = "ready"
    #: Turned into a sale through the explicit conversion step.
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DeliveryMethod(StrEnum):
    DELIVERY = "delivery"
    PICKUP = "pickup"


class OnlineStore(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """Storefront settings.  One per tenant for MVP."""

    __tablename__ = "online_stores"
    __table_args__ = (UniqueConstraint("slug", name="uq_online_stores_slug"),)

    slug: Mapped[str] = mapped_column(CodeText, nullable=False)
    display_name: Mapped[str] = mapped_column(ShortText, nullable=False)
    tagline: Mapped[str | None] = mapped_column(MediumText)
    about: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    contact_email: Mapped[str | None] = mapped_column(MediumText)
    telegram_username: Mapped[str | None] = mapped_column(ShortText)
    address: Mapped[str | None] = mapped_column(MediumText)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Whether visitors see prices without contacting the seller.
    show_prices: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: Terms copied onto every proforma requested from the storefront.
    default_terms: Mapped[str | None] = mapped_column(Text)
    #: Shown to the customer at checkout: delivery areas, how you confirm, etc.
    checkout_note: Mapped[str | None] = mapped_column(Text)
    #: Whether visitors can place an order (as opposed to only requesting a proforma).
    accepts_orders: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: Set once the owner has opened the bot and pressed Start (PRD 14: Telegram).
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    #: One-time code the owner sends to the bot to link this shop.
    telegram_link_code: Mapped[str | None] = mapped_column(String(64), index=True)


class CheckoutBatch(UUIDPrimaryKey, Timestamped, Base):
    """One visit to the marketplace checkout, possibly spanning several shops.

    Deliberately not tenant-scoped: each part (an order or a proforma request)
    belongs to one shop, and a shop only ever sees its own part.  The batch
    exists so the customer has one link that tracks all of them.
    """

    __tablename__ = "checkout_batches"
    __table_args__ = (UniqueConstraint("token", name="uq_checkout_batches_token"),)

    token: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[CheckoutKind] = mapped_column(enum_column(CheckoutKind), nullable=False)
    customer_name: Mapped[str] = mapped_column(ShortText, nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    customer_email: Mapped[str | None] = mapped_column(MediumText)
    company: Mapped[str | None] = mapped_column(ShortText)
    delivery_location: Mapped[str | None] = mapped_column(MediumText)
    message: Mapped[str | None] = mapped_column(Text)
    source_ip: Mapped[str | None] = mapped_column(String(64))


class Order(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """An online order for one shop (PRD 13, 19).

    Placing it reserves nothing.  Payment is recorded as the buyer's chosen
    method, not processed: the order becomes a sale, and stock moves, only
    through the explicit completion step.
    """

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_orders_tenant_number"),
        UniqueConstraint("share_token", name="uq_orders_share_token"),
        Index("ix_orders_tenant_status", "tenant_id", "status"),
    )

    number: Mapped[str] = mapped_column(CodeText, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        enum_column(OrderStatus), default=OrderStatus.PLACED, nullable=False
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("checkout_batches.id", ondelete="SET NULL")
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("customers.id", ondelete="SET NULL")
    )
    customer_name: Mapped[str] = mapped_column(ShortText, nullable=False)
    customer_phone: Mapped[str | None] = mapped_column(String(32))
    customer_email: Mapped[str | None] = mapped_column(MediumText)
    customer_company: Mapped[str | None] = mapped_column(ShortText)
    delivery_location: Mapped[str | None] = mapped_column(MediumText)
    delivery_method: Mapped[DeliveryMethod] = mapped_column(
        enum_column(DeliveryMethod), default=DeliveryMethod.DELIVERY, nullable=False
    )
    #: How the buyer intends to pay; recorded for the shop, never processed here.
    payment_method: Mapped[str] = mapped_column(String(24), default="cash", nullable=False)
    customer_message: Mapped[str | None] = mapped_column(Text)
    seller_note: Mapped[str | None] = mapped_column(Text)

    subtotal: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    tax_total: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    delivery_charge: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="ETB", nullable=False)

    share_token: Mapped[str | None] = mapped_column(String(64), index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ready_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cancel_reason: Mapped[str | None] = mapped_column(MediumText)
    converted_sale_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("sales.id", ondelete="SET NULL")
    )
    handled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )

    lines: Mapped[list[OrderLine]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin",
        order_by="OrderLine.sort_order",
    )


class OrderLine(UUIDPrimaryKey, Base):
    __tablename__ = "order_lines"
    __table_args__ = (Index("ix_order_lines_order", "order_id"),)

    order_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("products.id", ondelete="SET NULL")
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("product_variants.id", ondelete="SET NULL")
    )
    description: Mapped[str] = mapped_column(MediumText, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Percent, default=0, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)

    order: Mapped[Order] = relationship(back_populates="lines")


class CustomerEnquiry(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """A request submitted from the storefront (PRD 13)."""

    __tablename__ = "customer_enquiries"
    __table_args__ = (Index("ix_customer_enquiries_tenant_status", "tenant_id", "status"),)

    reference: Mapped[str] = mapped_column(CodeText, nullable=False)
    status: Mapped[EnquiryStatus] = mapped_column(
        enum_column(EnquiryStatus), default=EnquiryStatus.NEW, nullable=False
    )
    #: Set when a staff member links the enquiry to a known customer record.
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("customers.id", ondelete="SET NULL")
    )

    contact_name: Mapped[str] = mapped_column(ShortText, nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(MediumText)
    company: Mapped[str | None] = mapped_column(ShortText)
    delivery_location: Mapped[str | None] = mapped_column(MediumText)
    message: Mapped[str | None] = mapped_column(Text)
    #: Requested items as submitted, before a staff member prices them.
    requested_items_json: Mapped[str | None] = mapped_column(Text)
    wants_proforma: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    handled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    handled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    source_ip: Mapped[str | None] = mapped_column(String(64))


class Quotation(UUIDPrimaryKey, Timestamped, TenantScoped, Auditable, Base):
    """A numbered quotation/proforma.  Not a sale, a payment or a stock
    deduction until converted (PRD 14)."""

    __tablename__ = "quotations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_quotations_tenant_number"),
        UniqueConstraint("share_token", name="uq_quotations_share_token"),
        Index("ix_quotations_tenant_status", "tenant_id", "status"),
    )

    number: Mapped[str] = mapped_column(CodeText, nullable=False)
    status: Mapped[QuotationStatus] = mapped_column(
        enum_column(QuotationStatus), default=QuotationStatus.DRAFT, nullable=False
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("branches.id", ondelete="SET NULL")
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("customers.id", ondelete="SET NULL")
    )
    enquiry_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("customer_enquiries.id", ondelete="SET NULL")
    )
    #: Set when the request came through the marketplace checkout.
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("checkout_batches.id", ondelete="SET NULL")
    )

    # Denormalised recipient details: a quotation may precede a customer record.
    customer_name: Mapped[str] = mapped_column(ShortText, nullable=False)
    customer_phone: Mapped[str | None] = mapped_column(String(32))
    customer_email: Mapped[str | None] = mapped_column(MediumText)
    customer_company: Mapped[str | None] = mapped_column(ShortText)
    delivery_location: Mapped[str | None] = mapped_column(MediumText)

    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)

    subtotal: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    discount_total: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    tax_total: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    delivery_charge: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="ETB", nullable=False)

    terms: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    #: What the customer wrote when requesting it from the storefront.
    customer_message: Mapped[str | None] = mapped_column(Text)

    #: Unguessable token backing the public share link (PRD 14).
    share_token: Mapped[str | None] = mapped_column(String(64), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    declined_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    converted_sale_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("sales.id", ondelete="SET NULL")
    )

    lines: Mapped[list[QuotationLine]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan", lazy="selectin"
    )


class QuotationLine(UUIDPrimaryKey, Base):
    __tablename__ = "quotation_lines"
    __table_args__ = (Index("ix_quotation_lines_quotation", "quotation_id"),)

    quotation_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("products.id", ondelete="SET NULL")
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("product_variants.id", ondelete="SET NULL")
    )
    description: Mapped[str] = mapped_column(MediumText, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Percent, default=0, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)

    quotation: Mapped[Quotation] = relationship(back_populates="lines")
