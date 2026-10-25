"""Online catalogue, enquiries and proformas (PRD 13, 14).

An enquiry or proforma never reserves or reduces stock; only an explicit
conversion to a sale does (PRD 13, 14).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, Text, UniqueConstraint, false
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


class OnlineStore(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """Storefront settings.  One per tenant for MVP."""

    __tablename__ = "online_stores"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_online_stores_slug"),
        # "One per tenant" was a docstring; the marketplace made it load-bearing.
        # Its catalogue joins products to stores on tenant_id, so a second row
        # would quietly list every product twice rather than failing loudly.
        UniqueConstraint("tenant_id", name="uq_online_stores_tenant"),
    )

    slug: Mapped[str] = mapped_column(CodeText, nullable=False)
    display_name: Mapped[str] = mapped_column(ShortText, nullable=False)
    tagline: Mapped[str | None] = mapped_column(MediumText)
    about: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    contact_email: Mapped[str | None] = mapped_column(MediumText)
    telegram_username: Mapped[str | None] = mapped_column(ShortText)
    address: Mapped[str | None] = mapped_column(MediumText)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Whether this shop's products appear on the central marketplace.  A shop
    #: can be on the marketplace without publishing its own page, or publish
    #: its own page without joining the marketplace; this row is its public
    #: identity either way.
    #: ``server_default`` as well as ``default``: this column was added to a
    #: populated table, and the marketplace migration explains why the database
    #: default has to stay.
    list_on_marketplace: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False, index=True
    )
    #: Whether visitors see prices without contacting the seller.
    show_prices: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: Terms copied onto every proforma requested from the storefront.
    default_terms: Mapped[str | None] = mapped_column(Text)
    #: Shown to the customer at checkout: delivery areas, how you confirm, etc.
    checkout_note: Mapped[str | None] = mapped_column(Text)


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


class MarketplaceRequestStatus(StrEnum):
    """Where a buyer's cross-shop request has got to, overall.

    Derived from the shops' quotations, never stored — a column would read
    "open" forever once the first shop answered.  See
    ``_derive_request_status``.
    """

    #: Sent to the shops; at least one has not answered.
    OPEN = "open"
    #: Every shop has quoted, declined or had its quotation cancelled.
    ANSWERED = "answered"
    #: The buyer accepted at least one shop's quotation.
    ACCEPTED = "accepted"
    #: The buyer withdrew the whole request.
    WITHDRAWN = "withdrawn"


class MarketplaceRequest(UUIDPrimaryKey, Timestamped, Base):
    """One buyer's request for prices, spanning several shops (PRD 13, 14).

    This is the only operational table that is **not** tenant-scoped, because
    it belongs to the buyer rather than to any one shop.  It holds nothing a
    shop owns: just who asked, how to reach them, and the link they track it
    with.  Everything priced lives in the per-shop :class:`Quotation` rows that
    point back here, each of which is tenant-scoped as usual.

    A shop loading its own quotation can see that the request came from the
    marketplace — useful context, since it means the buyer is probably asking
    others — but never which other shops were asked or what they quoted.  That
    is the buyer's business, and nothing joins from a quotation to its
    siblings.
    """

    __tablename__ = "marketplace_requests"
    __table_args__ = (
        UniqueConstraint("reference", name="uq_marketplace_requests_reference"),
        UniqueConstraint("share_token", name="uq_marketplace_requests_share_token"),
        Index("ix_marketplace_requests_created", "created_at"),
    )

    #: Quotable by phone, and random rather than sequential — see
    #: ``generate_public_reference`` for why.
    reference: Mapped[str] = mapped_column(CodeText, nullable=False)
    #: The buyer's tracking link.  Their only way back in; there is no sign-in.
    share_token: Mapped[str] = mapped_column(String(64), nullable=False)

    contact_name: Mapped[str] = mapped_column(ShortText, nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(MediumText)
    company: Mapped[str | None] = mapped_column(ShortText)
    delivery_location: Mapped[str | None] = mapped_column(MediumText)
    message: Mapped[str | None] = mapped_column(Text)
    #: Where the request came from, for the platform's own reporting.
    source_ip: Mapped[str | None] = mapped_column(String(64))
    #: The one fact about the request's own progress that is stored.  Its
    #: status is derived from this and from the quotations
    #: (``_derive_request_status``), so there is no stored copy to fall out of
    #: step when a shop answers.
    withdrawn_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    quotations: Mapped[list[Quotation]] = relationship(
        back_populates="marketplace_request", lazy="selectin"
    )

    @property
    def shop_count(self) -> int:
        return len(self.quotations)


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
    #: Set when this quotation is one shop's part of a cross-shop request.
    #: The shop may know it came from the marketplace; it may not reach the
    #: other shops' quotations through here.
    marketplace_request_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("marketplace_requests.id", ondelete="SET NULL"), index=True
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

    marketplace_request: Mapped[MarketplaceRequest | None] = relationship(
        back_populates="quotations"
    )
    lines: Mapped[list[QuotationLine]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan", lazy="selectin"
    )
    #: Proof of payment the buyer sent. A claim, not a posting — see PaymentSlip.
    payment_slips: Mapped[list[PaymentSlip]] = relationship(
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


class PaymentSlipStatus(StrEnum):
    """What the seller has made of a slip a buyer sent.

    Derived from nothing — this one is a judgement the seller makes, so it is
    stored.  A slip is a *claim* that money was sent, not the money itself,
    which is why accepting it is a deliberate act and why it never touches the
    books on its own.
    """

    #: Sent by the buyer, not yet looked at.
    SUBMITTED = "submitted"
    #: The seller found the money.
    ACCEPTED = "accepted"
    #: The seller could not find it, or it was for something else.
    REJECTED = "rejected"


class PaymentSlip(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """Proof of payment a buyer sends the seller (PRD 13).

    There is no payment gateway here on purpose.  An Ethiopian buyer transfers
    by telebirr, CBE Birr or a bank deposit and then sends the screenshot or
    the slip; this is that screenshot, attached to the proforma it pays for so
    the seller sees the claim and the document it belongs to together.

    It records nothing in the shop's own books.  Posting the money is the
    seller's existing payment flow against the sale, and keeping the two apart
    means a buyer cannot write to a shop's ledger by uploading a picture.
    """

    __tablename__ = "payment_slips"
    __table_args__ = (
        Index("ix_payment_slips_quotation", "quotation_id"),
        Index("ix_payment_slips_tenant_status", "tenant_id", "status"),
    )

    quotation_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False
    )
    #: The uploaded image or PDF.  Bytes live behind the storage interface.
    file_asset_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("file_assets.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[PaymentSlipStatus] = mapped_column(
        enum_column(PaymentSlipStatus),
        default=PaymentSlipStatus.SUBMITTED,
        nullable=False,
    )
    #: What the buyer says they sent.  Their word until the seller checks it,
    #: which is why it is separate from anything in the payment ledger.
    amount_claimed: Mapped[Decimal | None] = mapped_column(Money)
    method: Mapped[str | None] = mapped_column(ShortText)
    #: The telebirr transaction number or bank reference, as the buyer typed it.
    reference: Mapped[str | None] = mapped_column(ShortText)
    paid_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)

    #: Who sent it.  A buyer has no account, so this is what they typed.
    sender_name: Mapped[str | None] = mapped_column(ShortText)
    sender_phone: Mapped[str | None] = mapped_column(String(32))
    source_ip: Mapped[str | None] = mapped_column(String(64))

    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    review_note: Mapped[str | None] = mapped_column(Text)

    quotation: Mapped[Quotation] = relationship(back_populates="payment_slips")
