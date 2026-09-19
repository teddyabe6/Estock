"""Shared model mixins and column helpers."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.core.db import GUID, UTCDateTime, new_uuid, utcnow


def enum_column(enum_cls: type[PyEnum], **kwargs: Any) -> SAEnum:
    """Portable enum column: VARCHAR + CHECK constraint on every backend."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=48,
        validate_strings=True,
        values_callable=lambda e: [item.value for item in e],
        **kwargs,
    )


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=new_uuid
    )


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class TenantScoped:
    """Every operational record carries its tenant (PRD section 4).

    Queries must go through :func:`app.core.tenancy.tenant_query` so the filter
    can never be forgotten.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(
            GUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        )


class BranchScoped:
    """Branch-level records also identify their branch (PRD section 4)."""

    @declared_attr
    def branch_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(
            GUID, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
        )


class Auditable:
    """Who created the record, for audit trails on financial/stock operations."""

    @declared_attr
    def created_by_id(cls) -> Mapped[uuid.UUID | None]:  # noqa: N805
        return mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def tenant_unique(table: str, *columns: str, name: str | None = None) -> Index:
    """Unique index scoped to the tenant, so two businesses may reuse a code."""
    index_name = name or f"uq_{table}_tenant_{'_'.join(columns)}"
    return Index(index_name, "tenant_id", *columns, unique=True)


ShortText = String(120)
MediumText = String(255)
CodeText = String(64)
