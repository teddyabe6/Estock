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


# --------------------------------------------------------------------------- #
# Chasing a shop that has left a request sitting
# --------------------------------------------------------------------------- #
#
# The request raised its own notice when it arrived.  This is the second
# prompt, and it has to be bounded at both ends: too eager and it fires before
# a shop has had a chance to look; never giving up and a shop learns to ignore
# the lot.


def _waiting_request(business, *, days_ago: float, from_marketplace: bool = False):
    """A proforma request this shop has not answered, aged on purpose."""
    from datetime import UTC, datetime, timedelta

    from app.models.commerce import MarketplaceRequest, OnlineStore
    from app.services.commerce import BasketItem, generate_share_token, request_quotation

    store = (
        business.db.query(OnlineStore).filter_by(tenant_id=business.tenant.id).one()
    )
    store.is_published = True
    product = business.add_product(
        f"Teff {days_ago}", selling_price="2800", opening_stock="20"
    )
    product.is_published = True
    business.db.flush()

    quotation = request_quotation(
        business.db,
        store,
        business.tenant,
        items=[BasketItem(product.variants[0].id, 1)],
        contact_name="Abebe Kebede",
        contact_phone="0911223344",
        from_marketplace=from_marketplace,
    )
    if from_marketplace:
        parent = MarketplaceRequest(
            reference=f"MR-TEST-{days_ago}",
            share_token=generate_share_token(),
            contact_name="Abebe Kebede",
            contact_phone="0911223344",
        )
        business.db.add(parent)
        business.db.flush()
        quotation.marketplace_request_id = parent.id
    quotation.created_at = datetime.now(UTC) - timedelta(days=days_ago)
    business.db.flush()
    return quotation


def test_a_request_left_overnight_is_chased(business):
    from app.services.notifications import run_unanswered_request_nudges

    quotation = _waiting_request(business, days_ago=2)

    result = run_unanswered_request_nudges(business.db)

    assert result.requests_waiting == 1
    assert result.nudges_created == 1
    notice = (
        business.db.query(Notification)
        .filter(Notification.kind == NotificationKind.PROFORMA_WAITING)
        .one()
    )
    assert "waiting for your price" in notice.title
    assert quotation.number in notice.body
    assert notice.link == "/shop?tab=proformas"


def test_a_request_from_this_morning_is_left_alone(business):
    from app.services.notifications import run_unanswered_request_nudges

    _waiting_request(business, days_ago=0.2)

    result = run_unanswered_request_nudges(business.db)

    assert result.requests_waiting == 0
    assert _count(business.db, NotificationKind.PROFORMA_WAITING) == 0


def test_a_request_nobody_answered_for_a_week_is_given_up_on(business):
    from app.services.notifications import run_unanswered_request_nudges

    _waiting_request(business, days_ago=9)

    result = run_unanswered_request_nudges(business.db)

    assert result.requests_waiting == 0, "a shop that ignores these stops reading them"


def test_a_priced_and_sent_proforma_is_not_chased(business):
    from app.services.commerce import send_quotation
    from app.services.notifications import run_unanswered_request_nudges

    quotation = _waiting_request(business, days_ago=3)
    send_quotation(business.db, business.ctx, quotation.id)

    result = run_unanswered_request_nudges(business.db)

    assert result.requests_waiting == 0, "the ball is the buyer's now"


def test_the_nudge_says_how_many_are_races(business):
    from app.services.notifications import run_unanswered_request_nudges

    _waiting_request(business, days_ago=2)
    _waiting_request(business, days_ago=3, from_marketplace=True)

    run_unanswered_request_nudges(business.db)

    notice = (
        business.db.query(Notification)
        .filter(Notification.kind == NotificationKind.PROFORMA_WAITING)
        .one()
    )
    assert notice.title.startswith("2 proforma request")
    assert "1 came through the marketplace" in notice.body
    assert "other shops were asked" in notice.body


def test_the_nudge_is_once_a_day_however_often_the_worker_runs(business):
    from app.services.notifications import run_unanswered_request_nudges

    _waiting_request(business, days_ago=2)

    first = run_unanswered_request_nudges(business.db)
    again = run_unanswered_request_nudges(business.db)

    assert (first.nudges_created, again.nudges_created) == (1, 0)
    assert _count(business.db, NotificationKind.PROFORMA_WAITING) == 1


def test_a_nudge_does_not_swallow_the_day_s_new_requests(business):
    """Separate kinds, so the daily de-duplication cannot confuse the two."""
    from app.services.notifications import run_unanswered_request_nudges

    _waiting_request(business, days_ago=2)
    run_unanswered_request_nudges(business.db)
    _waiting_request(business, days_ago=0)  # arrives now, notifies on arrival

    assert _count(business.db, NotificationKind.PROFORMA_WAITING) == 1
    assert _count(business.db, NotificationKind.PROFORMA_REQUEST) == 2
