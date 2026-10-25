"""new shops join the marketplace

The marketplace is worth more to everyone the more shops are in it, so a shop
created from now on joins unless it says otherwise.

A database default decides new rows only, which is the point: every shop that
already made this choice keeps it, whichever way it went.  Nothing here
rewrites a row, and the downgrade puts the old default back without touching
one either.

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


def upgrade() -> None:
    op.alter_column(
        "online_stores",
        "list_on_marketplace",
        existing_type=sa.BOOLEAN(),
        server_default=sa.text("true"),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "online_stores",
        "list_on_marketplace",
        existing_type=sa.BOOLEAN(),
        server_default=sa.text("false"),
        existing_nullable=False,
    )
