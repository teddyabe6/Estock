"""storefront proforma requests

Terms and a checkout note on the storefront, and the customer's message on a
proforma they requested from their basket.

Revision ID: b7e4f2a91c03
Revises: 8c2f1d4e9a01
Create Date: 2026-09-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b7e4f2a91c03"
down_revision: str | None = "8c2f1d4e9a01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("online_stores") as batch_op:
        batch_op.add_column(sa.Column("default_terms", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("checkout_note", sa.Text(), nullable=True))
    with op.batch_alter_table("quotations") as batch_op:
        batch_op.add_column(sa.Column("customer_message", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("quotations") as batch_op:
        batch_op.drop_column("customer_message")
    with op.batch_alter_table("online_stores") as batch_op:
        batch_op.drop_column("checkout_note")
        batch_op.drop_column("default_terms")
