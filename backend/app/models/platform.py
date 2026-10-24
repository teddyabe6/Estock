"""Platform-level models: tenants, subscriptions, billing, flags and audit.

``PaymentMethod`` is imported from the sales models: it is a vocabulary of
payment instruments — cash, telebirr, CBE Birr, a bank transfer — rather
than anything about a shop's own sales, and defining it once keeps the two
from drifting as Ethiopian payment rails change.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import GUID, Base, Money, Percent, UTCDateTime
from app.models.base import (
    CodeText,
    MediumText,
    ShortText,
    Timestamped,
    UUIDPrimaryKey,
    enum_column,
)
from app.models.sales import PaymentMethod


class TenantStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    #: Trial or subscription lapsed: read-only access, data retained (PRD 17).
    RESTRICTED = "restricted"
    SUSPENDED = "suspended"


class SubscriptionStatus(StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class Tenant(UUIDPrimaryKey, Timestamped, Base):
    """One independent business account.  The isolation boundary (PRD 4)."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(ShortText, nullable=False)
    slug: Mapped[str] = mapped_column(CodeText, nullable=False, unique=True)
    status: Mapped[TenantStatus] = mapped_column(
        enum_column(TenantStatus), default=TenantStatus.TRIAL, nullable=False
    )

    # Business profile
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(MediumText)
    address: Mapped[str | None] = mapped_column(MediumText)
    tin: Mapped[str | None] = mapped_column(CodeText, doc="Taxpayer identification number")
    business_type: Mapped[str | None] = mapped_column(ShortText)
    logo_asset_id: Mapped[uuid.UUID | None] = mapped_column(GUID)

    # Localisation / operating settings
    currency: Mapped[str] = mapped_column(String(3), default="ETB", nullable=False)
    locale: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Addis_Ababa", nullable=False)

    #: Explicit business setting; negative stock is refused unless enabled (PRD 9).
    allow_negative_stock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Whether a credit sale must name a customer (PRD open decision 25).
    require_customer_for_credit: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    #: Hide out-of-stock products in the storefront, or show them as unavailable (PRD 13).
    hide_out_of_stock_online: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    reminder_lead_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    #: Fractional rate applied to products with no rate of their own; 0.15 is 15%.
    default_tax_rate: Mapped[Decimal | None] = mapped_column(Percent, nullable=True)

    onboarding_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    subscription: Mapped[Subscription | None] = relationship(
        back_populates="tenant", uselist=False, cascade="all, delete-orphan"
    )
    branches: Mapped[list[Branch]] = relationship(  # noqa: F821
        back_populates="tenant", cascade="all, delete-orphan"
    )

    @property
    def is_read_only(self) -> bool:
        return self.status in (TenantStatus.RESTRICTED, TenantStatus.SUSPENDED)


class SubscriptionPlan(UUIDPrimaryKey, Timestamped, Base):
    """Platform-managed plan definition."""

    __tablename__ = "subscription_plans"

    code: Mapped[str] = mapped_column(CodeText, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(ShortText, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    monthly_price: Mapped[float] = mapped_column(Money, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="ETB", nullable=False)
    max_branches: Mapped[int | None] = mapped_column(Integer)
    max_users: Mapped[int | None] = mapped_column(Integer)
    max_products: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Subscription(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "subscriptions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("subscription_plans.id", ondelete="SET NULL")
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        enum_column(SubscriptionStatus), default=SubscriptionStatus.TRIALING, nullable=False
    )
    trial_started_on: Mapped[date | None] = mapped_column(Date)
    trial_ends_on: Mapped[date | None] = mapped_column(Date)
    current_period_ends_on: Mapped[date | None] = mapped_column(Date)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    notes: Mapped[str | None] = mapped_column(Text)

    tenant: Mapped[Tenant] = relationship(back_populates="subscription")
    plan: Mapped[SubscriptionPlan | None] = relationship()


class FeatureFlag(UUIDPrimaryKey, Timestamped, Base):
    """Per-tenant (or global when ``tenant_id`` is null) feature toggle."""

    __tablename__ = "feature_flags"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_feature_flags_tenant_key"),)

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    key: Mapped[str] = mapped_column(CodeText, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class PlatformAdmin(UUIDPrimaryKey, Timestamped, Base):
    """Separate identity boundary from tenant users (PRD 5.2)."""

    __tablename__ = "platform_admins"

    email: Mapped[str] = mapped_column(MediumText, nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(ShortText, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AuditEvent(UUIDPrimaryKey, Base):
    """Append-only record of privileged and financially material actions (PRD 20)."""

    __tablename__ = "audit_events"

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    actor_platform_admin_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    actor_label: Mapped[str | None] = mapped_column(ShortText)
    action: Mapped[str] = mapped_column(CodeText, nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(CodeText)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID)
    summary: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(64))


# --------------------------------------------------------------------------- #
# Billing: what a shop was charged, and what it paid
# --------------------------------------------------------------------------- #
#
# A subscription on its own says which plan a shop is on and when its period
# ends.  It cannot answer "has this shop paid?", which is the question the
# platform owner actually runs the business on.  These two tables answer it.
#
# They sit beside Subscription rather than in a tenant-scoped module because
# the money is between the platform and the shop, not inside the shop's books.
# A shop's own sales ledger has nothing to do with what it owes for the
# software.  So, like Subscription, they carry ``tenant_id`` as a plain
# foreign key and are not ``TenantScoped``: the platform reads them across
# shops as a matter of course, and a shop reads its own through one endpoint
# that filters explicitly.


class SubscriptionInvoiceStatus(StrEnum):
    """Where an invoice stands.

    Derived from its payments, its dates and whether it was voided — never
    stored.  A stored column would have to be rewritten on every payment and
    again every midnight as an invoice fell overdue, and would be wrong in
    between.  The same reasoning as credit status.
    """

    #: Raised but not yet sent to the shop.  Still editable.
    DRAFT = "draft"
    #: Issued, nothing paid yet.
    OPEN = "open"
    PART_PAID = "part_paid"
    PAID = "paid"
    #: Issued, still owing, and the due date has passed.
    OVERDUE = "overdue"
    #: Cancelled by the platform.  Kept, never deleted.
    VOID = "void"


class SubscriptionInvoice(UUIDPrimaryKey, Timestamped, Base):
    """One period's charge to one shop (PRD 17).

    The plan's name and price are copied onto the invoice when it is raised.
    Renaming a plan or changing its price must not rewrite what a shop was
    already billed, exactly as a sale snapshots its prices.
    """

    __tablename__ = "subscription_invoices"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "number", name="uq_subscription_invoices_tenant_number"
        ),
        # One *live* invoice per shop per period, so the billing run is safe
        # to repeat.  Partial, because voiding is how an invoice raised in
        # error is undone and the period has to be billable again afterwards —
        # a plain unique constraint would make a mistake permanent.
        Index(
            "uq_subscription_invoices_live_period",
            "tenant_id",
            "period_start",
            "period_end",
            unique=True,
            postgresql_where=text("voided_at IS NULL"),
            sqlite_where=text("voided_at IS NULL"),
        ),
        Index("ix_subscription_invoices_tenant", "tenant_id"),
        Index("ix_subscription_invoices_due", "due_on"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    #: Sequential per shop, from the same locked-row numbering as its own
    #: documents: ``SUB-2026-000001``.
    number: Mapped[str] = mapped_column(CodeText, nullable=False)

    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("subscription_plans.id", ondelete="SET NULL")
    )
    #: Snapshotted, so a renamed or deleted plan does not rewrite history.
    plan_code: Mapped[str | None] = mapped_column(CodeText)
    plan_name: Mapped[str | None] = mapped_column(ShortText)

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="ETB", nullable=False)
    #: Optional, and an invoice with no due date is never overdue — the same
    #: rule customer credit follows (PRD 11.3).
    due_on: Mapped[date | None] = mapped_column(Date)

    #: Null while the invoice is a draft.  Issuing it is the deliberate step
    #: that makes it something the shop owes.
    issued_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    voided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    void_reason: Mapped[str | None] = mapped_column(MediumText)
    note: Mapped[str | None] = mapped_column(Text)
    raised_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(GUID)

    payments: Mapped[list[SubscriptionPayment]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", lazy="selectin"
    )
    tenant: Mapped[Tenant] = relationship()


class SubscriptionPayment(UUIDPrimaryKey, Timestamped, Base):
    """Money a shop paid the platform against one invoice.

    Append-only in spirit: a mistake is reversed, never deleted, so the record
    of what was recorded and corrected survives (PRD 11.6, 20).
    """

    __tablename__ = "subscription_payments"
    __table_args__ = (
        UniqueConstraint(
            "invoice_id", "idempotency_key", name="uq_subscription_payments_idempotency"
        ),
        Index("ix_subscription_payments_tenant_paid", "tenant_id", "paid_on"),
        Index("ix_subscription_payments_invoice", "invoice_id"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("subscription_invoices.id", ondelete="CASCADE"), nullable=False
    )
    #: Repeated from the invoice so the platform can total a shop's payments
    #: without joining, and so a report survives an invoice being reassigned.
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    method: Mapped[PaymentMethod] = mapped_column(
        enum_column(PaymentMethod), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="ETB", nullable=False)
    #: A date, not a timestamp: a telebirr transfer or a bank deposit has a
    #: value date, and that is the day the platform was paid.
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    #: The telebirr transaction number, the bank slip, the deposit reference —
    #: what the platform owner checks the money against.
    reference: Mapped[str | None] = mapped_column(ShortText)
    note: Mapped[str | None] = mapped_column(Text)
    recorded_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(GUID)
    idempotency_key: Mapped[str | None] = mapped_column(String(160))

    is_reversed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reversed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reversed_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(GUID)
    reversal_reason: Mapped[str | None] = mapped_column(MediumText)

    invoice: Mapped[SubscriptionInvoice] = relationship(back_populates="payments")
