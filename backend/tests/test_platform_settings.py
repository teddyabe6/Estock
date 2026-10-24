"""Platform-wide switches the owner controls (PRD 5.2).

`FeatureFlag` has existed since the first migration and the admin API could
write rows to it, but nothing anywhere read one — so "control their
registration" was a table, not a feature. These tests pin the switches that
now decide something:

* A switch with no row anywhere is its documented default, never simply off.
  A missing row must not quietly disable the platform.
* A per-tenant row beats the platform-wide one, so "closed, except for this
  shop" can be said at all.
* A key nothing reads is refused with the list of real ones, rather than
  stored as a setting that does nothing.
* Closing registration never touches a shop that already exists.
"""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.models.platform import FeatureFlag
from app.services import platform_settings


@pytest.fixture()
def admin_headers(client, db):
    from app.core.security import hash_password
    from app.models.platform import PlatformAdmin

    db.add(
        PlatformAdmin(
            email="switches@estock.et",
            full_name="Operator",
            password_hash=hash_password("admin-pw-123"),
        )
    )
    db.flush()
    login = client.post(
        "/api/v1/platform/login",
        json={"email": "switches@estock.et", "password": "admin-pw-123"},
    )
    assert login.status_code == 200, login.json()
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _register(client, email="new@shop.et"):
    return client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "New Shop",
            "full_name": "New Owner",
            "email": email,
            "password": "a-good-password-1",
        },
    )


# --------------------------------------------------------------------------- #
# Reading a switch
# --------------------------------------------------------------------------- #


def test_a_switch_with_no_row_is_its_documented_default(db):
    """A missing row must not read as off, or an empty table disables everything."""
    assert platform_settings.is_enabled(db, "registration_open") is True
    assert platform_settings.is_enabled(db, "marketplace_open") is True
    assert platform_settings.is_enabled(db, "marketplace_listed") is True


def test_a_platform_row_overrides_the_default(db):
    db.add(FeatureFlag(key="registration_open", tenant_id=None, enabled=False))
    db.flush()
    assert platform_settings.is_enabled(db, "registration_open") is False


def test_a_shops_own_row_beats_the_platform_setting(db, business):
    """"Paused for everyone, except this shop" has to be expressible."""
    db.add(FeatureFlag(key="marketplace_listed", tenant_id=None, enabled=False))
    db.add(
        FeatureFlag(key="marketplace_listed", tenant_id=business.tenant.id, enabled=True)
    )
    db.flush()

    assert platform_settings.is_enabled(db, "marketplace_listed") is False
    assert (
        platform_settings.is_enabled(
            db, "marketplace_listed", tenant_id=business.tenant.id
        )
        is True
    )


def test_an_unknown_key_is_refused_with_the_real_ones(db):
    with pytest.raises(ValidationError) as raised:
        platform_settings.is_enabled(db, "registrations_open")
    assert "registration_open" in str(raised.value.details["known"])


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def test_registration_is_open_unless_it_is_closed(client, db):
    assert _register(client).status_code == 201


def test_closing_registration_turns_new_sign_ups_away(client, db, admin_headers):
    turned = client.put(
        "/api/v1/platform/settings",
        json={"key": "registration_open", "enabled": False, "reason": "Going invite-only"},
        headers=admin_headers,
    )
    assert turned.status_code == 200, turned.json()
    assert turned.json()["enabled"] is False

    refused = _register(client)
    assert refused.status_code == 403, refused.json()
    assert refused.json()["code"] == "registration_closed"


def test_closing_registration_leaves_existing_shops_alone(
    client, db, business, admin_headers
):
    """The switch is about new sign-ups, not about anybody already trading."""
    client.put(
        "/api/v1/platform/settings",
        json={"key": "registration_open", "enabled": False},
        headers=admin_headers,
    ).raise_for_status()

    product = business.add_product("Berbere", selling_price="450")
    sold = client.post(
        "/api/v1/sales",
        json={
            "lines": [{"variant_id": str(product.default_variant.id), "quantity": "1"}],
            "payments": [{"method": "cash", "amount": "450.00"}],
        },
        headers=business.headers(),
    )
    assert sold.status_code == 201, sold.json()

    session = client.get("/api/v1/auth/session", headers=business.headers())
    assert session.status_code == 200


def test_reopening_registration_lets_sign_ups_through_again(client, db, admin_headers):
    for enabled in (False, True):
        client.put(
            "/api/v1/platform/settings",
            json={"key": "registration_open", "enabled": enabled},
            headers=admin_headers,
        ).raise_for_status()
    assert _register(client).status_code == 201


# --------------------------------------------------------------------------- #
# The marketplace switch
# --------------------------------------------------------------------------- #


def test_pausing_the_marketplace_stops_requests_but_not_browsing(
    client, db, business, admin_headers
):
    """Unlisting every product to pause for a week would be a blunt instrument."""
    from sqlalchemy import select

    from app.models.commerce import OnlineStore

    store = db.execute(
        select(OnlineStore).where(OnlineStore.tenant_id == business.tenant.id)
    ).scalar_one_or_none()
    if store is None:
        from app.services.onboarding import slugify, unique_slug

        store = OnlineStore(
            tenant_id=business.tenant.id,
            slug=unique_slug(db, OnlineStore, OnlineStore.slug, slugify(business.tenant.name)),
            display_name=business.tenant.name,
        )
        db.add(store)
    store.list_on_marketplace = True
    product = business.add_product("Shiro", selling_price="320")
    product.on_marketplace = True
    db.flush()

    client.put(
        "/api/v1/platform/settings",
        json={"key": "marketplace_open", "enabled": False},
        headers=admin_headers,
    ).raise_for_status()

    # Still browsable.
    browsing = client.get("/api/v1/market/products")
    assert browsing.status_code == 200
    assert browsing.json()["total"] >= 1

    # But not requestable.
    asked = client.post(
        "/api/v1/market/requests",
        json={
            "items": [{"variant_id": str(product.default_variant.id), "quantity": "2"}],
            "contact_name": "Buyer",
            "contact_phone": "0911000000",
        },
    )
    assert asked.status_code == 422, asked.json()
    assert "not taking new requests" in asked.json()["message"]


# --------------------------------------------------------------------------- #
# The admin endpoint
# --------------------------------------------------------------------------- #


def test_the_settings_screen_lists_only_switches_something_reads(
    client, admin_headers
):
    listed = client.get("/api/v1/platform/settings", headers=admin_headers)
    assert listed.status_code == 200
    keys = {row["key"] for row in listed.json()["settings"]}
    assert keys == {"registration_open", "marketplace_open", "marketplace_listed"}
    for row in listed.json()["settings"]:
        assert row["description"], "a switch has to say what it does"
        assert row["set_explicitly"] is False


def test_the_api_refuses_a_key_nothing_reads(client, admin_headers):
    """The old endpoint stored any key, so a typo looked like a setting."""
    response = client.put(
        "/api/v1/platform/settings",
        json={"key": "enable_dark_mode", "enabled": True},
        headers=admin_headers,
    )
    assert response.status_code == 422, response.json()
    assert "registration_open" in str(response.json()["details"]["known"])


def test_a_platform_wide_switch_cannot_be_set_for_one_shop(
    client, business, admin_headers
):
    """Registration is not per-shop: a shop that exists has already registered."""
    response = client.put(
        "/api/v1/platform/settings",
        json={
            "key": "registration_open",
            "enabled": False,
            "tenant_id": str(business.tenant.id),
        },
        headers=admin_headers,
    )
    assert response.status_code == 422, response.json()
    assert "platform-wide" in response.json()["message"]


def test_turning_a_switch_is_audited(client, db, admin_headers):
    from app.models.platform import AuditEvent

    client.put(
        "/api/v1/platform/settings",
        json={"key": "registration_open", "enabled": False, "reason": "Capacity"},
        headers=admin_headers,
    ).raise_for_status()

    event = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == "platform.setting_changed")
        .one()
    )
    assert event.actor_label == "switches@estock.et"
    assert "Capacity" in (event.payload_json or "")
    # The effective previous value, not the column's. A switch nobody had set
    # was at its default, and "None → False" would read as "it was unset".
    assert event.summary == "registration_open: on → off"


def test_a_shop_token_cannot_turn_a_platform_switch(client, business):
    response = client.put(
        "/api/v1/platform/settings",
        json={"key": "registration_open", "enabled": False},
        headers=business.headers(),
    )
    assert response.status_code in (401, 403)


# --------------------------------------------------------------------------- #
# Pausing one shop's marketplace
# --------------------------------------------------------------------------- #


@pytest.fixture()
def listed_shops(db, business, other_business):
    """Two shops, both listed on the marketplace with one product each."""
    from sqlalchemy import select

    from app.models.commerce import OnlineStore
    from app.services.onboarding import slugify, unique_slug

    made = []
    for shop, name in ((business, "Berbere"), (other_business, "Shiro")):
        store = db.execute(
            select(OnlineStore).where(OnlineStore.tenant_id == shop.tenant.id)
        ).scalar_one_or_none()
        if store is None:
            store = OnlineStore(
                tenant_id=shop.tenant.id,
                slug=unique_slug(
                    db, OnlineStore, OnlineStore.slug, slugify(shop.tenant.name)
                ),
                display_name=shop.tenant.name,
            )
            db.add(store)
        store.list_on_marketplace = True
        product = shop.add_product(name, selling_price="450")
        product.on_marketplace = True
        made.append((shop, product))
    db.flush()
    return made


def _pause(client, headers, tenant_id, enabled=False):
    response = client.put(
        "/api/v1/platform/settings",
        json={
            "key": "marketplace_listed",
            "enabled": enabled,
            "tenant_id": str(tenant_id),
            "reason": "Not answering requests",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.json()
    return response


def test_pausing_one_shop_takes_its_products_off_the_marketplace(
    client, db, listed_shops, admin_headers
):
    (paused, _), (other, _) = listed_shops
    before = client.get("/api/v1/market/products").json()
    assert before["total"] == 2

    _pause(client, admin_headers, paused.tenant.id)

    after = client.get("/api/v1/market/products").json()
    assert after["total"] == 1, "the paused shop's product is gone"
    assert after["items"][0]["shop"]["name"] == other.tenant.name


def test_pausing_one_shop_leaves_every_other_shop_alone(
    client, db, listed_shops, admin_headers
):
    (paused, _), (other, _) = listed_shops
    _pause(client, admin_headers, paused.tenant.id)

    shops = client.get("/api/v1/market/shops").json()["shops"]
    names = {shop["name"] for shop in shops}
    assert other.tenant.name in names
    assert paused.tenant.name not in names


def test_a_paused_shop_cannot_receive_a_request(client, db, listed_shops, admin_headers):
    """A basket filled before the pause must not reach it either."""
    (paused, product), _ = listed_shops
    _pause(client, admin_headers, paused.tenant.id)

    asked = client.post(
        "/api/v1/market/requests",
        json={
            "items": [{"variant_id": str(product.default_variant.id), "quantity": "1"}],
            "contact_name": "Buyer",
            "contact_phone": "0911000000",
        },
    )
    assert asked.status_code == 422, asked.json()
    assert "no longer available" in asked.json()["message"]


def test_pausing_does_not_touch_the_shops_own_decision_to_be_listed(
    client, db, listed_shops, admin_headers
):
    """The shop's opt-in is its own, and is waiting when the pause is lifted."""
    from sqlalchemy import select

    from app.models.commerce import OnlineStore

    (paused, _), _ = listed_shops
    _pause(client, admin_headers, paused.tenant.id)

    store = db.execute(
        select(OnlineStore).where(OnlineStore.tenant_id == paused.tenant.id)
    ).scalar_one()
    assert store.list_on_marketplace is True, "the operator did not rewrite it"

    _pause(client, admin_headers, paused.tenant.id, enabled=True)
    assert client.get("/api/v1/market/products").json()["total"] == 2


def test_a_shops_switches_are_readable_on_its_own(client, db, business, admin_headers):
    page = client.get(
        f"/api/v1/platform/tenants/{business.tenant.id}/settings", headers=admin_headers
    )
    assert page.status_code == 200, page.json()
    rows = {row["key"]: row for row in page.json()["settings"]}
    # Only the switches that mean something for one shop.
    assert set(rows) == {"marketplace_listed"}
    assert rows["marketplace_listed"]["enabled"] is True
    assert rows["marketplace_listed"]["set_for_shop"] is False

    _pause(client, admin_headers, business.tenant.id)
    after = client.get(
        f"/api/v1/platform/tenants/{business.tenant.id}/settings", headers=admin_headers
    ).json()["settings"][0]
    assert after["enabled"] is False
    assert after["set_for_shop"] is True


def test_pausing_the_platform_still_lets_one_shop_be_turned_back_on(
    client, db, listed_shops, admin_headers
):
    """"Paused for everyone, except this one" has to work in the query too."""
    (kept, _), _ = listed_shops
    client.put(
        "/api/v1/platform/settings",
        json={"key": "marketplace_listed", "enabled": False},
        headers=admin_headers,
    ).raise_for_status()
    assert client.get("/api/v1/market/products").json()["total"] == 0

    _pause(client, admin_headers, kept.tenant.id, enabled=True)
    listed = client.get("/api/v1/market/products").json()
    assert listed["total"] == 1
    assert listed["items"][0]["shop"]["name"] == kept.tenant.name
