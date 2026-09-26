"""Platform-level models: tenants, subscriptions, feature flags and audit."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
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
