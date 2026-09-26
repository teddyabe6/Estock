"""The hourly worker must not repeat a daily notice (PRD 9, 11.4, 17)."""

from __future__ import annotations

from datetime import date, timedelta

from app.models.system import Notification, NotificationKind
from app.services.notifications import already_notified_today, run_low_stock_alerts
from app.services.subscription import warn_expiring_trials


def _count(db, kind: NotificationKind) -> int:
    return db.query(Notification).filter(Notification.kind == kind).count()


def test_low_stock_alerts_are_sent_once_a_day_however_often_the_worker_runs(business):
    business.add_product("Nearly gone", opening_stock="1", min_stock="5", reorder_level="10")

    first = run_low_stock_alerts(business.db)
    again = run_low_stock_alerts(business.db)

    assert first.alerts_created == 1
    assert again.alerts_created == 0
    assert _count(business.db, NotificationKind.LOW_STOCK) == 1


def test_trial_warnings_are_sent_once_a_day(business):
    from app.models.platform import Subscription

    subscription = (
        business.db.query(Subscription).filter_by(tenant_id=business.tenant.id).one()
    )
    subscription.trial_ends_on = date.today() + timedelta(days=3)
    business.db.flush()

    assert warn_expiring_trials(business.db) == 1
    assert warn_expiring_trials(business.db) == 0
    assert _count(business.db, NotificationKind.TRIAL_EXPIRY) == 1


def test_already_notified_today_is_per_person_and_per_notice(business):
    from app.core.permissions import RoleName
    from app.services.notifications import notify

    notify(
        business.db,
        tenant_id=business.tenant.id,
        user_id=business.owner.id,
        kind=NotificationKind.GENERAL,
        title="Hello",
    )
    business.db.flush()
    other, _ = business.add_user(RoleName.MANAGER)

    assert already_notified_today(
        business.db, tenant=business.tenant, user_id=business.owner.id, kind=NotificationKind.GENERAL
    )
    assert not already_notified_today(
        business.db, tenant=business.tenant, user_id=other.id, kind=NotificationKind.GENERAL
    )
    assert not already_notified_today(
        business.db,
        tenant=business.tenant,
        user_id=business.owner.id,
        kind=NotificationKind.GENERAL,
        title="Something else",
    )
