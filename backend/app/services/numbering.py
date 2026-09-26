"""Per-tenant sequential document numbers, e.g. ``S-2026-000042``.

Each business, document kind and year has one :class:`DocumentSequence` row.
The row is locked (``SELECT … FOR UPDATE`` on PostgreSQL; SQLite serialises
writers anyway) for the rest of the transaction, so two sales posted at the
same moment queue behind each other instead of both computing the same number
and one of them failing on the unique constraint.

The unique constraint on ``(tenant_id, number)`` stays as the backstop.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import supports_row_locks, utcnow
from app.models.sequences import DocumentSequence

PREFIXES = {
    "sale": "S",
    "purchase": "P",
    "quotation": "PF",
    "transfer": "TR",
    "count": "SC",
    "credit": "CR",
    "enquiry": "ENQ",
}

_SUFFIX = re.compile(r"(\d+)$")


def prefix_for(kind: str, now: datetime | None = None) -> str:
    now = now or utcnow()
    return f"{PREFIXES.get(kind, kind.upper()[:3])}-{now.year}-"


def next_number(
    db: Session,
    model: type,
    tenant_id: uuid.UUID,
    kind: str,
    *,
    now: datetime | None = None,
    column: str = "number",
) -> str:
    """Return the next document number for this business, kind and year."""
    now = now or utcnow()
    prefix = prefix_for(kind, now)
    period = str(now.year)

    stmt = select(DocumentSequence).where(
        DocumentSequence.tenant_id == tenant_id,
        DocumentSequence.kind == kind,
        DocumentSequence.period == period,
    )
    if supports_row_locks(db):
        stmt = stmt.with_for_update()

    sequence = db.execute(stmt).scalar_one_or_none()
    if sequence is None:
        sequence = _start_sequence(db, model, tenant_id, kind, period, prefix, column, stmt)

    sequence.last_number += 1
    db.flush()
    return f"{prefix}{sequence.last_number:06d}"


def _start_sequence(db, model, tenant_id, kind, period, prefix, column, locked_stmt):
    """Create the sequence row, continuing from documents that already exist.

    A database upgraded from count-based numbering keeps counting where it
    left off rather than restarting at 000001 and colliding.  If two requests
    race to create the very first row, the unique constraint lets one win and
    the other re-reads the winner's row under the lock.
    """
    target = getattr(model, column)
    existing = db.execute(
        select(target).where(model.tenant_id == tenant_id, target.like(f"{prefix}%"))
    ).scalars()
    highest = 0
    for value in existing:
        match = _SUFFIX.search(value or "")
        if match:
            highest = max(highest, int(match.group(1)))

    sequence = DocumentSequence(
        tenant_id=tenant_id, kind=kind, period=period, last_number=highest
    )
    try:
        with db.begin_nested():
            db.add(sequence)
            db.flush()
    except IntegrityError:
        sequence = db.execute(locked_stmt).scalar_one()
    return sequence


def document_count(db: Session, model: type, tenant_id: uuid.UUID) -> int:
    return db.execute(
        select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
    ).scalar_one()
