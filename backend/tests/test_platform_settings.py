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


def test_a_platform_row_overrides_the_default(db):
    db.add(FeatureFlag(key="registration_open", tenant_id=None, enabled=False))
    db.flush()
    assert platform_settings.is_enabled(db, "registration_open") is False


def test_a_shops_own_row_beats_the_platform_setting(db, business):
    """"Paused for everyone, except this shop" has to be expressible."""
    db.add(FeatureFlag(key="marketplace_open", tenant_id=None, enabled=False))
    db.add(FeatureFlag(key="marketplace_open", tenant_id=business.tenant.id, enabled=True))
    db.flush()

    assert platform_settings.is_enabled(db, "marketplace_open") is False
    assert (
        platform_settings.is_enabled(
            db, "marketplace_open", tenant_id=business.tenant.id
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
    assert keys == {"registration_open", "marketplace_open"}
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
