"""Business-local dates.

Timestamps are stored in UTC; a business lives in its own timezone (Addis
Ababa is UTC+3).  "Today", "due today", report day boundaries and sales-by-day
grouping must all follow the business's clock, or a sale at 01:00 in Addis
lands on yesterday's report and a balance due today reads as due tomorrow
until 03:00 (PRD 15, 16, 21).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Africa/Addis_Ababa"


def tzinfo_for(name: str | None) -> ZoneInfo:
    """The zone for a business, falling back to the default rather than failing."""
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def local_now(tz_name: str | None) -> datetime:
    return datetime.now(tzinfo_for(tz_name))


def local_today(tz_name: str | None) -> date:
    """The calendar date where the business is, not where the server is."""
    return local_now(tz_name).date()


def local_date(moment: datetime, tz_name: str | None) -> date:
    """The business-local calendar date of a stored (UTC) timestamp."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(tzinfo_for(tz_name)).date()


def day_start(day: date, tz_name: str | None) -> datetime:
    """Midnight at the start of ``day`` in the business's zone, as an aware instant."""
    return datetime.combine(day, time.min, tzinfo=tzinfo_for(tz_name))


def day_end(day: date, tz_name: str | None) -> datetime:
    """The last instant of ``day`` in the business's zone."""
    return datetime.combine(day, time.max, tzinfo=tzinfo_for(tz_name))
