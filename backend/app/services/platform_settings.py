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

from sqlalchemy import false, select, true
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
            "Turn it off to pause the marketplace without unlisting anything: "
            "people can still browse, they just cannot ask for prices."
        ),
        per_tenant=False,
    ),
    Flag(
        key="marketplace_listed",
        default=True,
        description=(
            "Whether shops take part in the central marketplace. Off for one "
            "shop stops sending buyers to that one; off platform-wide unlists "
            "every shop that has no setting of its own. Either way a shop's "
            "products stop appearing and it stops receiving requests, and its "
            "own decision to be listed is left untouched."
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


def participation_filter(db: Session, key: str, tenant_column):
    """A SQL condition matching rows whose shop has this switch on.

    The point is to resolve the switch for every shop in one query and hand
    back something a catalogue query can use directly, rather than asking per
    row.  It resolves the same way :func:`is_enabled` does for one shop — the
    shop's own row wins, else the platform row, else the default — in both
    directions:

    * platform on  → every shop but the ones explicitly turned off;
    * platform off → only the shops explicitly turned back on, which is what
      makes "paused for everyone, except this one" work.

    Returns ``true()`` or ``false()`` when the answer is the same for all of
    them, so the common case costs nothing in the query.
    """
    flag = known(key)
    rows = db.execute(select(FeatureFlag).where(FeatureFlag.key == key)).scalars().all()
    platform_on = next(
        (row.enabled for row in rows if row.tenant_id is None), flag.default
    )
    per_shop = {row.tenant_id: row.enabled for row in rows if row.tenant_id is not None}

    if platform_on:
        off = [tenant_id for tenant_id, on in per_shop.items() if not on]
        return true() if not off else tenant_column.notin_(off)
    on = [tenant_id for tenant_id, enabled in per_shop.items() if enabled]
    return false() if not on else tenant_column.in_(on)


def enabled_platform_wide(db: Session, key: str) -> bool:
    """The platform-wide setting on its own, ignoring any per-shop rows."""
    flag = known(key)
    row = db.execute(
        select(FeatureFlag).where(
            FeatureFlag.key == key, FeatureFlag.tenant_id.is_(None)
        )
    ).scalar_one_or_none()
    return flag.default if row is None else row.enabled


def describe_for_tenant(db: Session, tenant_id: uuid.UUID) -> list[dict]:
    """One shop's switches: where each stands for it, and why.

    Only the switches that can be set per shop. A platform-wide one is not
    this shop's business and is not offered against it.
    """
    rows = {
        row.key: row
        for row in db.execute(
            select(FeatureFlag).where(FeatureFlag.tenant_id == tenant_id)
        ).scalars()
    }
    return [
        {
            "key": flag.key,
            "description": flag.description,
            "enabled": is_enabled(db, flag.key, tenant_id=tenant_id),
            "set_for_shop": flag.key in rows,
            "platform_default": enabled_platform_wide(db, flag.key),
        }
        for flag in FLAGS
        if flag.per_tenant
    ]


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
