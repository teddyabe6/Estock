"""marketplace orders, checkout batches and telegram links

New tables for orders placed from the marketplace and for the checkout batch
that groups one visit's orders or requests across shops.  Existing shops keep
accepting orders (``accepts_orders`` defaults to true) and nothing existing
changes shape.

Revision ID: b30b5e6b5e2e
Revises: b7e4f2a91c03
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Custom column types (GUID, UTCDateTime) live here.
import app.core.db

revision: str = "b30b5e6b5e2e"
down_revision: str | None = "b7e4f2a91c03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "checkout_batches",
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("order", "proforma", name="checkoutkind", native_enum=False, length=48),
            nullable=False,
        ),
        sa.Column("customer_name", sa.String(length=120), nullable=False),
        sa.Column("customer_phone", sa.String(length=32), nullable=False),
        sa.Column("customer_email", sa.String(length=255), nullable=True),
        sa.Column("company", sa.String(length=120), nullable=True),
        sa.Column("delivery_location", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("id", app.core.db.GUID(), nullable=False),
        sa.Column("created_at", app.core.db.UTCDateTime(), nullable=False),
        sa.Column("updated_at", app.core.db.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checkout_batches")),
        sa.UniqueConstraint("token", name="uq_checkout_batches_token"),
    )
    op.create_table(
        "orders",
        sa.Column("number", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "placed",
                "confirmed",
                "ready",
                "completed",
                "cancelled",
                name="orderstatus",
                native_enum=False,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("batch_id", app.core.db.GUID(), nullable=True),
        sa.Column("customer_id", app.core.db.GUID(), nullable=True),
        sa.Column("customer_name", sa.String(length=120), nullable=False),
        sa.Column("customer_phone", sa.String(length=32), nullable=True),
        sa.Column("customer_email", sa.String(length=255), nullable=True),
        sa.Column("customer_company", sa.String(length=120), nullable=True),
        sa.Column("delivery_location", sa.String(length=255), nullable=True),
        sa.Column(
            "delivery_method",
            sa.Enum("delivery", "pickup", name="deliverymethod", native_enum=False, length=48),
            nullable=False,
        ),
        sa.Column("payment_method", sa.String(length=24), nullable=False),
        sa.Column("customer_message", sa.Text(), nullable=True),
        sa.Column("seller_note", sa.Text(), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("tax_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("delivery_charge", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("share_token", sa.String(length=64), nullable=True),
        sa.Column("confirmed_at", app.core.db.UTCDateTime(), nullable=True),
        sa.Column("ready_at", app.core.db.UTCDateTime(), nullable=True),
        sa.Column("completed_at", app.core.db.UTCDateTime(), nullable=True),
        sa.Column("cancelled_at", app.core.db.UTCDateTime(), nullable=True),
        sa.Column("cancel_reason", sa.String(length=255), nullable=True),
        sa.Column("converted_sale_id", app.core.db.GUID(), nullable=True),
        sa.Column("handled_by_id", app.core.db.GUID(), nullable=True),
        sa.Column("id", app.core.db.GUID(), nullable=False),
        sa.Column("created_at", app.core.db.UTCDateTime(), nullable=False),
        sa.Column("updated_at", app.core.db.UTCDateTime(), nullable=False),
        sa.Column("tenant_id", app.core.db.GUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["checkout_batches.id"],
            name=op.f("fk_orders_batch_id_checkout_batches"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["converted_sale_id"],
            ["sales.id"],
            name=op.f("fk_orders_converted_sale_id_sales"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_orders_customer_id_customers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["handled_by_id"],
            ["users.id"],
            name=op.f("fk_orders_handled_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_orders_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("share_token", name="uq_orders_share_token"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_orders_tenant_number"),
    )
    op.create_index(op.f("ix_orders_share_token"), "orders", ["share_token"], unique=False)
    op.create_index(op.f("ix_orders_tenant_id"), "orders", ["tenant_id"], unique=False)
    op.create_index("ix_orders_tenant_status", "orders", ["tenant_id", "status"], unique=False)
    op.create_table(
        "order_lines",
        sa.Column("order_id", app.core.db.GUID(), nullable=False),
        sa.Column("product_id", app.core.db.GUID(), nullable=True),
        sa.Column("variant_id", app.core.db.GUID(), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("tax_rate", sa.Numeric(precision=7, scale=4), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", app.core.db.GUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_order_lines_order_id_orders"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_order_lines_product_id_products"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name=op.f("fk_order_lines_variant_id_product_variants"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_lines")),
    )
    op.create_index("ix_order_lines_order", "order_lines", ["order_id"], unique=False)

    # Batch mode so SQLite can add the columns and the foreign key too.
    with op.batch_alter_table("online_stores") as batch_op:
        batch_op.add_column(
            sa.Column(
                "accepts_orders", sa.Boolean(), nullable=False, server_default=sa.true()
            )
        )
        batch_op.add_column(sa.Column("telegram_chat_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("telegram_link_code", sa.String(length=64), nullable=True))
        batch_op.create_index(
            op.f("ix_online_stores_telegram_link_code"), ["telegram_link_code"], unique=False
        )
    with op.batch_alter_table("online_stores") as batch_op:
        # The default only served existing rows; the application sets the value.
        batch_op.alter_column("accepts_orders", server_default=None)
    with op.batch_alter_table("quotations") as batch_op:
        batch_op.add_column(sa.Column("batch_id", app.core.db.GUID(), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_quotations_batch_id_checkout_batches"),
            "checkout_batches",
            ["batch_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("quotations") as batch_op:
        batch_op.drop_constraint(op.f("fk_quotations_batch_id_checkout_batches"), type_="foreignkey")
        batch_op.drop_column("batch_id")
    with op.batch_alter_table("online_stores") as batch_op:
        batch_op.drop_index(op.f("ix_online_stores_telegram_link_code"))
        batch_op.drop_column("telegram_link_code")
        batch_op.drop_column("telegram_chat_id")
        batch_op.drop_column("accepts_orders")
    op.drop_index("ix_order_lines_order", table_name="order_lines")
    op.drop_table("order_lines")
    op.drop_index("ix_orders_tenant_status", table_name="orders")
    op.drop_index(op.f("ix_orders_tenant_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_share_token"), table_name="orders")
    op.drop_table("orders")
    op.drop_table("checkout_batches")
