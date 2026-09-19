"""Per-tenant sequential document numbers.

The number is derived from the count of existing documents inside a
``SELECT ... FOR UPDATE``-guarded transaction; the unique constraint on
``(tenant_id, number)`` is the real guard against collisions, and the caller
retries on conflict.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow

PREFIXES = {
    "sale": "S",
    "purchase": "P",
    "quotation": "PF",
    "transfer": "TR",
    "count": "SC",
    "credit": "CR",
    "enquiry": "ENQ",
}


def next_number(
    db: Session,
    model: type,
    tenant_id: uuid.UUID,
    kind: str,
    *,
    now: datetime | None = None,
    column: str = "number",
) -> str:
    """Return the next document number, e.g. ``S-2026-000042``."""
    now = now or utcnow()
    prefix = f"{PREFIXES.get(kind, kind.upper()[:3])}-{now.year}-"
    target = getattr(model, column)
    count = db.execute(
        select(func.count())
        .select_from(model)
        .where(model.tenant_id == tenant_id, target.like(f"{prefix}%"))
    ).scalar_one()
    return f"{prefix}{count + 1:06d}"
