"""new shops join the marketplace

The marketplace is worth more to everyone the more shops are in it, so a shop
created from now on joins unless it says otherwise.

A database default decides new rows only, which is the point: every shop that
already made this choice keeps it, whichever way it went.  Nothing here
rewrites a row, and the downgrade puts the old default back without touching
one either.

Through ``batch_alter_table`` because SQLite cannot ALTER a column at all:
there the table is rebuilt with the new default and its rows copied across.
The demo runs on SQLite, so a migration that only works on PostgreSQL is a
migration that stops anyone trying the thing.

Revision ID: 7898a6cca381
Revises: 9fdbde187d57
Create Date: 2026-10-25 10:34:11.272036
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Custom column types (GUID, UTCDateTime) live here.
import app.core.db

revision: str = '7898a6cca381'
down_revision: str | None = '9fdbde187d57'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _set_default(value: sa.sql.elements.ColumnElement) -> None:
    # sa.true()/sa.false() rather than sa.text("true"): each dialect writes its
    # own literal, so SQLite gets DEFAULT (1) and PostgreSQL DEFAULT true, and
    # both still match the model when alembic compares them.
    with op.batch_alter_table("online_stores") as batch:
        batch.alter_column(
            "list_on_marketplace",
            existing_type=sa.BOOLEAN(),
            server_default=value,
            existing_nullable=False,
        )


def upgrade() -> None:
    _set_default(sa.true())


def downgrade() -> None:
    _set_default(sa.false())
