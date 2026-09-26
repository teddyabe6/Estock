"""Report periods follow the business's clock, not the server's (PRD 15, 16, 21)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from app.core.clock import day_end, day_start, local_date, local_today, tzinfo_for
from app.services.reports import DateRange, home_dashboard, range_for, sales_by_day, sales_summary

ADDIS = "Africa/Addis_Ababa"


def test_addis_ababa_is_three_hours_ahead_of_utc():
    moment = datetime(2026, 3, 15, 22, 0, tzinfo=UTC)
    assert local_date(moment, ADDIS) == date(2026, 3, 16)
    assert local_date(moment, "UTC") == date(2026, 3, 15)


def test_an_unknown_timezone_falls_back_rather_than_failing():
    assert str(tzinfo_for("Mars/Olympus_Mons")) == ADDIS
    assert isinstance(local_today("nonsense"), date)


def test_day_boundaries_are_the_business_midnight():
    start = day_start(date(2026, 3, 16), ADDIS)
    end = day_end(date(2026, 3, 16), ADDIS)
    assert start.astimezone(UTC) == datetime(2026, 3, 15, 21, 0, tzinfo=UTC)
    assert end.astimezone(UTC).date() == date(2026, 3, 16)


def test_a_sale_after_midnight_in_addis_belongs_to_the_new_day(business):
    """22:00 UTC on the 15th is 01:00 on the 16th where the shop is."""
    product = business.add_product("Late sale", selling_price="100", opening_stock="10")
    business.sell(product, sold_at=datetime(2026, 3, 15, 22, 0, tzinfo=UTC))

    the_16th = DateRange(date(2026, 3, 16), date(2026, 3, 16), ADDIS)
    the_15th = DateRange(date(2026, 3, 15), date(2026, 3, 15), ADDIS)
    assert sales_summary(business.db, business.ctx, the_16th).sale_count == 1
    assert sales_summary(business.db, business.ctx, the_15th).sale_count == 0

    by_day = sales_by_day(business.db, business.ctx, DateRange(date(2026, 3, 1), date(2026, 3, 31), ADDIS))
    assert by_day == [{"date": "2026-03-16", "sale_count": 1, "total": "100.00"}]


def test_range_for_uses_the_business_today():
    today = date(2026, 3, 16)
    period = range_for("7d", today=today, tz_name=ADDIS)
    assert period.start == date(2026, 3, 10)
    assert period.end == today
    assert period.tz_name == ADDIS
    assert period.as_dict()["timezone"] == ADDIS


def test_the_dashboard_reports_its_timezone(business):
    payload = home_dashboard(business.db, business.ctx)
    assert payload["timezone"] == ADDIS
    assert payload["date"] == local_today(ADDIS).isoformat()


def test_sales_by_day_totals_agree_with_the_summary(business):
    product = business.add_product("Daily", selling_price="40", opening_stock="50")
    for hour in (6, 12, 18):
        business.sell(product, sold_at=datetime(2026, 4, 2, hour, tzinfo=UTC))
    business.sell(product, sold_at=datetime(2026, 4, 3, 9, tzinfo=UTC))

    period = DateRange(date(2026, 4, 1), date(2026, 4, 30), ADDIS)
    rows = sales_by_day(business.db, business.ctx, period)
    assert [(r["date"], r["sale_count"]) for r in rows] == [("2026-04-02", 3), ("2026-04-03", 1)]
    assert sum(Decimal(r["total"]) for r in rows) == sales_summary(
        business.db, business.ctx, period
    ).net_sales
