"""document sequences, password reset, tax rate precision

Revision ID: 8c2f1d4e9a01
Revises: 41b344b218fa
Create Date: 2026-09-26 15:10:00

Non-destructive:

* ``document_sequences`` is a new table; the first document numbered after
  this migration seeds the row from the numbers that already exist, so
  numbering continues where the count-based scheme left off.
* ``users`` gains two nullable columns for account recovery.
* ``tenants.default_tax_rate`` was stored with two decimals (a *money*
  column); a rate wants four.  Existing values are preserved by the widening.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.core.db

revision: str = "8c2f1d4e9a01"
down_revision: str | None = "41b344b218fa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_sequences",
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.Column("tenant_id", app.core.db.GUID(), nullable=False),
        sa.Column("id", app.core.db.GUID(), nullable=False),
        sa.Column("created_at", app.core.db.UTCDateTime(), nullable=False),
        sa.Column("updated_at", app.core.db.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_document_sequences_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_sequences")),
        sa.UniqueConstraint(
            "tenant_id", "kind", "period", name="uq_document_sequences_tenant_kind_period"
        ),
    )
    op.create_index(
        op.f("ix_document_sequences_tenant_id"), "document_sequences", ["tenant_id"], unique=False
    )

    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("password_reset_token", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("password_reset_expires_at", app.core.db.UTCDateTime(), nullable=True)
        )
        batch_op.create_index(
            op.f("ix_users_password_reset_token"), ["password_reset_token"], unique=False
        )

    with op.batch_alter_table("tenants") as batch_op:
        batch_op.alter_column(
            "default_tax_rate",
            existing_type=sa.Numeric(precision=14, scale=2),
            type_=sa.Numeric(precision=7, scale=4),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.alter_column(
            "default_tax_rate",
            existing_type=sa.Numeric(precision=7, scale=4),
            type_=sa.Numeric(precision=14, scale=2),
            existing_nullable=True,
        )
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index(op.f("ix_users_password_reset_token"))
        batch_op.drop_column("password_reset_expires_at")
        batch_op.drop_column("password_reset_token")
    op.drop_index(op.f("ix_document_sequences_tenant_id"), table_name="document_sequences")
    op.drop_table("document_sequences")
