"""Branches and stock locations."""

from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import GUID, Base
from app.models.base import (
    CodeText,
    MediumText,
    ShortText,
    TenantScoped,
    Timestamped,
    UUIDPrimaryKey,
    enum_column,
)


class LocationKind(StrEnum):
    SHOP = "shop"
    WAREHOUSE = "warehouse"


class Branch(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """A location belonging to a tenant — never a tenant of its own (PRD 4)."""

    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_branches_tenant_code"),)

    name: Mapped[str] = mapped_column(ShortText, nullable=False)
    code: Mapped[str | None] = mapped_column(CodeText)
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(MediumText)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: The branch created automatically at registration (PRD 4, 6).
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    tenant: Mapped[Tenant] = relationship(back_populates="branches")  # noqa: F821
    locations: Mapped[list[StockLocation]] = relationship(
        back_populates="branch", cascade="all, delete-orphan"
    )

    @property
    def default_location(self) -> StockLocation | None:
        for location in self.locations:
            if location.is_default:
                return location
        return self.locations[0] if self.locations else None


class StockLocation(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """Where stock physically sits.  Each branch gets one by default."""

    __tablename__ = "stock_locations"

    branch_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(ShortText, nullable=False)
    kind: Mapped[LocationKind] = mapped_column(
        enum_column(LocationKind), default=LocationKind.SHOP, nullable=False
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    branch: Mapped[Branch] = relationship(back_populates="locations")
