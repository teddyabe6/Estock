"""Platform-wide switches the owner controls (PRD 5.2).

``FeatureFlag`` has existed since the first migration, and the admin API could
write rows to it, but nothing anywhere read one — so every switch was a note to
self.  This module is where a flag becomes a decision the system acts on.

A flag is read as: the row for this tenant if there is one, else the global row
(``tenant_id IS NULL``), else the default stated here.  That ordering is what
makes "closed to new shops, except this one" expressible.

Flags are deliberately few.  A switch nothing reads is worse than no switch,
because it looks like control and is not, so each one listed here is enforced
somewhere and named in :data:`FLAGS`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.models.platform import FeatureFlag


@dataclass(frozen=True, slots=True)
class Flag:
    """One switch: its key, what it does, and what it is when nobody has set it."""

    key: str
    default: bool
    #: Shown on the platform screen, so the owner knows what they are turning.
    description: str
    #: False for a switch that only makes sense platform-wide.
    per_tenant: bool = True


#: Every flag the system actually reads.  Adding a key here without enforcing
#: it somewhere is the mistake this registry exists to prevent.
FLAGS: tuple[Flag, ...] = (
    Flag(
        key="registration_open",
        default=True,
        description=(
            "Whether new businesses may sign themselves up. Turn it off to "
            "take the platform invitation-only; existing shops are unaffected."
        ),
        per_tenant=False,
    ),
    Flag(
        key="marketplace_open",
        default=True,
        description=(
            "Whether the central marketplace accepts new requests from buyers. "
            "Turn it off to pause the marketplace without unlisting anything."
        ),
    ),
)

_BY_KEY = {flag.key: flag for flag in FLAGS}


def known(key: str) -> Flag:
    """The flag by that name, or a refusal naming the ones that exist."""
    flag = _BY_KEY.get(key)
    if flag is None:
        raise ValidationError(
            f"'{key}' is not a switch this system reads.",
            details={"known": sorted(_BY_KEY)},
        )
    return flag


def is_enabled(db: Session, key: str, *, tenant_id: uuid.UUID | None = None) -> bool:
    """Whether a switch is on: this shop's setting, else the platform's, else the default.

    The per-tenant row wins so that "closed, except for this one" can be said
    at all.  A flag with no row anywhere is its documented default, never
    simply off — a missing row must not quietly disable something.
    """
    flag = known(key)
    rows = db.execute(
        select(FeatureFlag).where(
            FeatureFlag.key == key,
            FeatureFlag.tenant_id.in_([tenant_id, None])
            if tenant_id is not None
            else FeatureFlag.tenant_id.is_(None),
        )
    ).scalars().all()

    if tenant_id is not None:
        for row in rows:
            if row.tenant_id == tenant_id:
                return row.enabled
    for row in rows:
        if row.tenant_id is None:
            return row.enabled
    return flag.default


def describe(db: Session) -> list[dict]:
    """Every switch with its platform-wide setting, for the admin screen."""
    rows = {
        row.key: row
        for row in db.execute(
            select(FeatureFlag).where(FeatureFlag.tenant_id.is_(None))
        ).scalars()
    }
    return [
        {
            "key": flag.key,
            "description": flag.description,
            "default": flag.default,
            "enabled": rows[flag.key].enabled if flag.key in rows else flag.default,
            "set_explicitly": flag.key in rows,
            "per_tenant": flag.per_tenant,
        }
        for flag in FLAGS
    ]
