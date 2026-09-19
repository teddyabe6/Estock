"""Notifications, file assets and spreadsheet import jobs."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import GUID, Base, UTCDateTime
from app.models.base import (
    CodeText,
    MediumText,
    ShortText,
    TenantScoped,
    Timestamped,
    UUIDPrimaryKey,
    enum_column,
)


class NotificationKind(StrEnum):
    LOW_STOCK = "low_stock"
    CREDIT_REMINDER = "credit_reminder"
    NEW_ENQUIRY = "new_enquiry"
    TRIAL_EXPIRY = "trial_expiry"
    IMPORT_COMPLETE = "import_complete"
    GENERAL = "general"


class ImportJobStatus(StrEnum):
    UPLOADED = "uploaded"
    MAPPED = "mapped"
    VALIDATED = "validated"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Notification(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_tenant_user_read", "tenant_id", "user_id", "read_at"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE")
    )
    kind: Mapped[NotificationKind] = mapped_column(
        enum_column(NotificationKind), default=NotificationKind.GENERAL, nullable=False
    )
    title: Mapped[str] = mapped_column(ShortText, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    #: Deep link into the app, e.g. ``/credit/receivables/<id>``.
    link: Mapped[str | None] = mapped_column(MediumText)
    entity_type: Mapped[str | None] = mapped_column(CodeText)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class FileAsset(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """An uploaded file.  Bytes live behind the storage interface, not in the DB."""

    __tablename__ = "file_assets"

    filename: Mapped[str] = mapped_column(MediumText, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(24), default="local", nullable=False)
    storage_key: Mapped[str] = mapped_column(MediumText, nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ImportJob(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """A product import: upload → map → preview → confirm (PRD 8.3)."""

    __tablename__ = "import_jobs"

    status: Mapped[ImportJobStatus] = mapped_column(
        enum_column(ImportJobStatus), default=ImportJobStatus.UPLOADED, nullable=False
    )
    file_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("file_assets.id", ondelete="SET NULL")
    )
    original_filename: Mapped[str] = mapped_column(MediumText, nullable=False)
    #: Chosen column mapping, ``{"name": "Product Name", ...}``.
    column_mapping_json: Mapped[str | None] = mapped_column(Text)
    #: Parsed header row, offered to the user for mapping.
    detected_headers_json: Mapped[str | None] = mapped_column(Text)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("branches.id", ondelete="SET NULL")
    )

    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_products: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_products: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    row_errors: Mapped[list[ImportRowError]] = relationship(
        back_populates="job", cascade="all, delete-orphan", lazy="selectin"
    )


class ImportRowError(UUIDPrimaryKey, Base):
    """One problem found on one row, surfaced before anything is written."""

    __tablename__ = "import_row_errors"

    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("import_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    column_name: Mapped[str | None] = mapped_column(ShortText)
    code: Mapped[str] = mapped_column(CodeText, nullable=False)
    message: Mapped[str] = mapped_column(MediumText, nullable=False)
    raw_value: Mapped[str | None] = mapped_column(MediumText)

    job: Mapped[ImportJob] = relationship(back_populates="row_errors")
