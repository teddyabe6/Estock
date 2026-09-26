"""Per-tenant document numbering (sales, purchases, proformas, …).

One row per business, document kind and period holds the last number issued.
It is read under ``SELECT … FOR UPDATE`` so two sales posted at the same
moment cannot be handed the same number (PRD 20, 21).
"""

from __future__ import annotations

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import CodeText, TenantScoped, Timestamped, UUIDPrimaryKey


class DocumentSequence(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    __tablename__ = "document_sequences"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "kind", "period", name="uq_document_sequences_tenant_kind_period"
        ),
    )

    #: ``sale``, ``purchase``, ``quotation``, ``transfer``, ``count``, ``credit``, ``enquiry``.
    kind: Mapped[str] = mapped_column(CodeText, nullable=False)
    #: Numbers restart per period — the calendar year, e.g. ``2026``.
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    last_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
