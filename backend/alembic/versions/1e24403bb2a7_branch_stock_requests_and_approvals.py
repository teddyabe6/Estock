"""branch stock requests and approvals

Revision ID: 1e24403bb2a7
Revises: 7898a6cca381
Create Date: 2026-10-31 05:21:29.330499

Additive, and reversible:

* ``stock_transfers`` gains the milestones of a *pull* transfer — when it was
  asked for, decided and accepted, and by whom — so a request and the transfer
  it becomes stay one row with one reference.  Every column is nullable, which
  is what every transfer recorded before now truthfully is: it was pushed out
  as a draft, never requested.
* ``requested``, ``approved`` and ``rejected`` are new ``TransferStatus``
  values on a ``native_enum=False`` column, which is a plain ``VARCHAR`` with
  no check constraint, so they need no DDL at all.
* ``stock:transfer_approve`` is a new permission.  ``role_permissions`` rows
  are written once per business when it registers, from the bundle in force at
  the time, so a new permission is invisible to every business that already
  exists — including its owner, who would then be unable to answer a request
  nobody else may answer either.  The backfill gives existing owners what an
  owner registering today gets, and only where the row is missing.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Custom column types (GUID, UTCDateTime) live here.
import app.core.db

revision: str = '1e24403bb2a7'
down_revision: str | None = '7898a6cca381'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite cannot add a foreign key to a table that already exists, so the
    # columns and their constraints go on together inside a batch, which
    # rebuilds the table there and is a plain ALTER on PostgreSQL.
    # scripts/demo.sh migrates SQLite, so both paths have to work.
    with op.batch_alter_table('stock_transfers') as batch_op:
        batch_op.add_column(sa.Column('requested_at', app.core.db.UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column('requested_by_id', app.core.db.GUID(), nullable=True))
        batch_op.add_column(sa.Column('decided_at', app.core.db.UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column('decided_by_id', app.core.db.GUID(), nullable=True))
        batch_op.add_column(sa.Column('decision_note', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('accepted_at', app.core.db.UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column('accepted_by_id', app.core.db.GUID(), nullable=True))
        batch_op.create_foreign_key(
            op.f('fk_stock_transfers_requested_by_id_users'),
            'users',
            ['requested_by_id'],
            ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_foreign_key(
            op.f('fk_stock_transfers_decided_by_id_users'),
            'users',
            ['decided_by_id'],
            ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_foreign_key(
            op.f('fk_stock_transfers_accepted_by_id_users'),
            'users',
            ['accepted_by_id'],
            ['id'],
            ondelete='SET NULL',
        )

    _grant_approval_permission()


#: Only the owner, matching DEFAULT_ROLE_PERMISSIONS.  Deciding a request
#: spends one branch's stock on another's behalf, which is not a manager's
#: call by default; a business that wants it theirs grants it per user.
_APPROVAL_ROLES = ("owner",)
_APPROVAL_PERMISSION = "stock:transfer_approve"


def _roles_table() -> sa.TableClause:
    return sa.table(
        "roles",
        sa.column("id", app.core.db.GUID()),
        sa.column("name", sa.String()),
    )


def _role_permissions_table() -> sa.TableClause:
    return sa.table(
        "role_permissions",
        sa.column("id", app.core.db.GUID()),
        sa.column("role_id", app.core.db.GUID()),
        sa.column("permission", sa.String()),
    )


def _grant_approval_permission() -> None:
    """Give existing businesses the permission a new one would be created with."""
    roles = _roles_table()
    role_permissions = _role_permissions_table()

    connection = op.get_bind()
    existing = {
        row[0]
        for row in connection.execute(
            sa.select(role_permissions.c.role_id).where(
                role_permissions.c.permission == _APPROVAL_PERMISSION
            )
        )
    }
    targets = connection.execute(
        sa.select(roles.c.id).where(roles.c.name.in_(_APPROVAL_ROLES))
    ).scalars()

    rows = [
        {"id": uuid.uuid4(), "role_id": role_id, "permission": _APPROVAL_PERMISSION}
        for role_id in targets
        if role_id not in existing
    ]
    if rows:
        op.bulk_insert(role_permissions, rows)


def _revoke_approval_permission() -> None:
    role_permissions = _role_permissions_table()
    op.execute(
        role_permissions.delete().where(
            role_permissions.c.permission == _APPROVAL_PERMISSION
        )
    )


def downgrade() -> None:
    # Dropping the columns discards who asked for and allowed each transfer,
    # and leaves any request still in flight looking like a stale draft, which
    # is why this is a downgrade and not a routine operation.
    _revoke_approval_permission()
    op.execute(
        sa.text(
            "UPDATE stock_transfers SET status = 'cancelled' "
            "WHERE status IN ('requested', 'approved', 'rejected')"
        )
    )
    with op.batch_alter_table('stock_transfers') as batch_op:
        batch_op.drop_constraint(
            op.f('fk_stock_transfers_accepted_by_id_users'), type_='foreignkey'
        )
        batch_op.drop_constraint(
            op.f('fk_stock_transfers_decided_by_id_users'), type_='foreignkey'
        )
        batch_op.drop_constraint(
            op.f('fk_stock_transfers_requested_by_id_users'), type_='foreignkey'
        )
        batch_op.drop_column('accepted_by_id')
        batch_op.drop_column('accepted_at')
        batch_op.drop_column('decision_note')
        batch_op.drop_column('decided_by_id')
        batch_op.drop_column('decided_at')
        batch_op.drop_column('requested_by_id')
        batch_op.drop_column('requested_at')
