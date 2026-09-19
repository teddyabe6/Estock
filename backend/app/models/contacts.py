"""Customers and suppliers — deliberately lightweight for MVP (PRD 12)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import GUID, Base, Money
from app.models.base import (
    MediumText,
    ShortText,
    TenantScoped,
    Timestamped,
    UUIDPrimaryKey,
)


class Customer(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    __tablename__ = "customers"
    __table_args__ = (
        Index("ix_customers_tenant_name", "tenant_id", "name"),
        Index("ix_customers_tenant_phone", "tenant_id", "phone"),
    )

    name: Mapped[str] = mapped_column(ShortText, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    telegram_username: Mapped[str | None] = mapped_column(ShortText)
    email: Mapped[str | None] = mapped_column(MediumText)
    address: Mapped[str | None] = mapped_column(MediumText)
    company: Mapped[str | None] = mapped_column(ShortText)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    #: Optional limit with configurable behaviour (PRD 11.7).
    credit_limit: Mapped[Decimal | None] = mapped_column(Money)
    #: One of warn | require_approval | block; null means fall back to warn.
    credit_limit_behaviour: Mapped[str | None] = mapped_column(String(24))

    default_branch_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("branches.id", ondelete="SET NULL")
    )


class Supplier(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    __tablename__ = "suppliers"
    __table_args__ = (Index("ix_suppliers_tenant_name", "tenant_id", "name"),)

    name: Mapped[str] = mapped_column(ShortText, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(MediumText)
    telegram_username: Mapped[str | None] = mapped_column(ShortText)
    address: Mapped[str | None] = mapped_column(MediumText)
    contact_person: Mapped[str | None] = mapped_column(ShortText)
    tin: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
