"""Credit receivables and payables, reminders and follow-up (PRD 11).

A ``CreditTransaction`` is the balance record for one credit sale or credit
purchase.  Its ``amount_paid`` is a cached aggregate of the ``Payment`` rows
that point at it — never an independently maintained number.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Date, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import GUID, Base, Money, UTCDateTime
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


class CreditKind(StrEnum):
    #: Owed to the business by a customer.
    RECEIVABLE = "receivable"
    #: Owed by the business to a supplier.
    PAYABLE = "payable"


class CreditStatus(StrEnum):
    OUTSTANDING = "outstanding"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class ReminderKind(StrEnum):
    DUE_SOON = "due_soon"
    DUE_TODAY = "due_today"
    OVERDUE = "overdue"


class ReminderChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    PUSH = "push"


class ReminderStatus(StrEnum):
    SCHEDULED = "scheduled"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FollowUpKind(StrEnum):
    CALLED = "called"
    MESSAGE_SENT = "message_sent"
    PROMISE_TO_PAY = "promise_to_pay"
    ARRANGEMENT = "arrangement"
    NOTE = "note"


class CreditTransaction(UUIDPrimaryKey, Timestamped, TenantScoped, Auditable, Base):
    __tablename__ = "credit_transactions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_credit_transactions_tenant_reference"),
        Index("ix_credit_transactions_tenant_kind_status", "tenant_id", "kind", "status"),
        Index("ix_credit_transactions_due_date", "tenant_id", "due_date"),
        Index("ix_credit_transactions_customer", "customer_id"),
        Index("ix_credit_transactions_supplier", "supplier_id"),
    )

    reference: Mapped[str] = mapped_column(CodeText, nullable=False)
    kind: Mapped[CreditKind] = mapped_column(enum_column(CreditKind), nullable=False)
    status: Mapped[CreditStatus] = mapped_column(
        enum_column(CreditStatus), default=CreditStatus.OUTSTANDING, nullable=False
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("branches.id", ondelete="SET NULL"), index=True
    )

    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("customers.id", ondelete="SET NULL")
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("suppliers.id", ondelete="SET NULL")
    )
    sale_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("sales.id", ondelete="CASCADE"), unique=True
    )
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("purchases.id", ondelete="CASCADE"), unique=True
    )

    #: Full transaction amount; the balance is this minus payments received.
    original_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    #: Cached sum of non-reversed payments against this transaction.
    amount_paid: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="ETB", nullable=False)

    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    #: Optional.  Without one the balance is outstanding but never overdue (PRD 11.3).
    due_date: Mapped[date | None] = mapped_column(Date)
    agreement_note: Mapped[str | None] = mapped_column(Text)

    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cancelled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    cancel_reason: Mapped[str | None] = mapped_column(MediumText)

    payments: Mapped[list[Payment]] = relationship(  # noqa: F821
        back_populates="credit_transaction",
        lazy="selectin",
        foreign_keys="Payment.credit_transaction_id",
    )
    reminders: Mapped[list[Reminder]] = relationship(
        back_populates="credit_transaction", cascade="all, delete-orphan"
    )
    activities: Mapped[list[FollowUpActivity]] = relationship(
        back_populates="credit_transaction", cascade="all, delete-orphan"
    )

    @property
    def balance(self) -> Decimal:
        """Total amount minus payments received (PRD 11.1)."""
        return Decimal(self.original_amount) - Decimal(self.amount_paid)

    @property
    def is_settled(self) -> bool:
        return self.balance <= Decimal("0.00")


class Reminder(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """An internal reminder for staff.  Never a message to the counterparty
    and never proof that one was contacted (PRD 11.4)."""

    __tablename__ = "reminders"
    __table_args__ = (
        Index("ix_reminders_tenant_scheduled", "tenant_id", "scheduled_for", "status"),
        UniqueConstraint(
            "credit_transaction_id",
            "kind",
            "channel",
            "scheduled_for",
            name="uq_reminders_transaction_kind_channel_date",
        ),
    )

    credit_transaction_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("credit_transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[ReminderKind] = mapped_column(enum_column(ReminderKind), nullable=False)
    channel: Mapped[ReminderChannel] = mapped_column(
        enum_column(ReminderChannel), default=ReminderChannel.IN_APP, nullable=False
    )
    status: Mapped[ReminderStatus] = mapped_column(
        enum_column(ReminderStatus), default=ReminderStatus.SCHEDULED, nullable=False
    )
    scheduled_for: Mapped[date] = mapped_column(Date, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failure_reason: Mapped[str | None] = mapped_column(MediumText)

    credit_transaction: Mapped[CreditTransaction] = relationship(back_populates="reminders")


class FollowUpActivity(UUIDPrimaryKey, Timestamped, TenantScoped, Auditable, Base):
    """A record that someone followed up.  Never changes a balance (PRD 11.6)."""

    __tablename__ = "follow_up_activities"

    credit_transaction_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("credit_transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[FollowUpKind] = mapped_column(enum_column(FollowUpKind), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    #: For a promise-to-pay, what the counterparty committed to.
    promised_amount: Mapped[Decimal | None] = mapped_column(Money)
    promised_date: Mapped[date | None] = mapped_column(Date)
    outcome: Mapped[str | None] = mapped_column(ShortText)

    credit_transaction: Mapped[CreditTransaction] = relationship(back_populates="activities")
