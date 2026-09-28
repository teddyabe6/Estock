"""The marketplace: browsing across shops, a cart checked out as orders, and a
cart sent to several shops as proforma requests (PRD 13, 14).

Each shop sees and is told about its own part only.  Placing an order or a
request never reserves stock; only completion or conversion does.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.errors import ConflictError, ValidationError
from app.models.commerce import OnlineStore, Order, OrderStatus, Quotation, QuotationStatus
from app.services import messaging
from app.services.checkout import (
    CheckoutContact,
    CheckoutItem,
    cancel_order,
    complete_order,
    confirm_order,
    mark_order_ready,
    place_orders,
    request_proformas,
)
from app.services.inventory import get_balance
from app.services.notifications import EmailSender, set_email_sender


class RecordingEmail(EmailSender):
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, *, to, subject, body):
        self.sent.append({"to": to, "subject": subject, "body": body})
        return True


class RecordingTelegram(messaging.TelegramSender):
    def __init__(self, updates=None):
        self.sent: list[dict] = []
        self.pending = list(updates or [])
        self.confirmed_offset = None

    def send(self, *, chat_id, text):
        self.sent.append({"chat_id": chat_id, "text": text})
        return True

    def updates(self, *, offset=None):
        if offset is not None:
            self.confirmed_offset = offset
            return []
        return list(self.pending)


@pytest.fixture
def mail():
    sender = RecordingEmail()
    set_email_sender(sender)
    yield sender
    set_email_sender(EmailSender())


@pytest.fixture
def telegram():
    sender = RecordingTelegram()
    messaging.set_telegram_sender(sender)
    yield sender
    messaging.set_telegram_sender(None)


def open_shop(biz, *, email="shop@example.et", **fields) -> OnlineStore:
    store = biz.db.query(OnlineStore).filter_by(tenant_id=biz.tenant.id).one()
    store.is_published = True
    store.contact_email = email
    for key, value in fields.items():
        setattr(store, key, value)
    biz.db.flush()
    return store


def contact(**overrides) -> CheckoutContact:
    base = {"name": "Meseret Tadesse", "phone": "0912 00 04 44", "delivery_location": "Bole"}
    base.update(overrides)
    return CheckoutContact(**base)


@pytest.fixture
def two_shops(business, other_business):
    """Two open shops, each with a published product, plus a hidden one."""
    grain = open_shop(business, email="grain@example.et")
    hardware = open_shop(other_business, email="hardware@example.et", telegram_chat_id="4242")
    teff = business.add_product(
        "Teff 50kg", selling_price="4200", opening_stock="20", is_published=True, category_name="Grains"
    )
    coffee = business.add_product(
        "Coffee 1kg", selling_price="850", opening_stock="5", is_published=True, category_name="Drinks"
    )
    cement = other_business.add_product(
        "Cement 50kg", selling_price="900", opening_stock="100", is_published=True, category_name="Building"
    )
    other_business.add_product("Private item", selling_price="1", opening_stock="5")
    return {"grain": grain, "hardware": hardware, "teff": teff, "coffee": coffee, "cement": cement}


# --------------------------------------------------------------------------- #
# Browsing across shops
# --------------------------------------------------------------------------- #


def test_the_marketplace_lists_every_open_shop_and_filters(client, two_shops):
    market = client.get("/api/v1/public/market").json()
    assert [s["slug"] for s in market["shops"]] == ["addis-retail", "bahir-dar-traders"]
    assert market["categories"] == ["Building", "Drinks", "Grains"]
    grain = next(s for s in market["shops"] if s["slug"] == "addis-retail")
    assert grain["product_count"] == 2 and grain["categories"] == ["Drinks", "Grains"]

    everything = client.get("/api/v1/public/market/products").json()
    assert everything["total"] == 3
    assert {item["shop"]["slug"] for item in everything["items"]} == {"addis-retail", "bahir-dar-traders"}

    by_shop = client.get("/api/v1/public/market/products?shop=bahir-dar-traders").json()
    assert [i["name"] for i in by_shop["items"]] == ["Cement 50kg"]

    by_category = client.get("/api/v1/public/market/products?category=drinks").json()
    assert [i["name"] for i in by_category["items"]] == ["Coffee 1kg"]

    by_price = client.get("/api/v1/public/market/products?min_price=800&max_price=1000").json()
    assert sorted(i["name"] for i in by_price["items"]) == ["Cement 50kg", "Coffee 1kg"]

    cheapest_first = client.get("/api/v1/public/market/products?sort=price_asc").json()
    assert [i["price"] for i in cheapest_first["items"]] == ["850.00", "900.00", "4200.00"]

    by_word = client.get("/api/v1/public/market/products?q=cem").json()
    assert by_word["total"] == 1

    assert client.get("/api/v1/public/market/products?sort=sideways").status_code == 422


def test_a_closed_or_suspended_shop_is_not_on_the_marketplace(client, two_shops, other_business):
    from app.models.platform import TenantStatus

    two_shops["hardware"].is_published = False
    other_business.db.flush()
    assert [s["slug"] for s in client.get("/api/v1/public/market").json()["shops"]] == ["addis-retail"]

    two_shops["hardware"].is_published = True
    other_business.tenant.status = TenantStatus.SUSPENDED
    other_business.db.flush()
    assert [s["slug"] for s in client.get("/api/v1/public/market").json()["shops"]] == ["addis-retail"]
    assert client.get("/api/v1/public/market/products").json()["total"] == 2


# --------------------------------------------------------------------------- #
# Orders across shops
# --------------------------------------------------------------------------- #


def test_a_cart_across_two_shops_becomes_one_order_per_shop(client, two_shops, business, other_business, mail, telegram):
    teff, coffee, cement = two_shops["teff"], two_shops["coffee"], two_shops["cement"]
    response = client.post(
        "/api/v1/public/checkout/orders",
        json={
            "items": [
                {"shop": "addis-retail", "variant_id": str(teff.default_variant.id), "quantity": "2"},
                {"shop": "addis-retail", "variant_id": str(coffee.default_variant.id), "quantity": "1"},
                {"shop": "bahir-dar-traders", "variant_id": str(cement.default_variant.id), "quantity": "10"},
            ],
            "contact_name": "Meseret Tadesse",
            "contact_phone": "0912 00 04 44",
            "contact_email": "meseret@example.et",
            "delivery_location": "Bole",
            "delivery_method": "delivery",
            "payment_method": "telebirr",
            "message": "Saturday please",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "order"
    assert body["url"].endswith(f"/track/{body['token']}")
    parts = {p["shop"]["slug"]: p for p in body["parts"]}
    assert parts["addis-retail"]["total_amount"] == "9250.00"
    assert parts["bahir-dar-traders"]["total_amount"] == "9000.00"
    assert all(p["number"].startswith("ORD-") for p in body["parts"])

    # Nothing reserved.
    assert get_balance(business.db, business.tenant.id, teff.default_variant.id, business.location.id) == Decimal("20.000")

    # Each shop sees only its own order.
    mine = client.get("/api/v1/shop/orders", headers=business.headers()).json()
    theirs = client.get("/api/v1/shop/orders", headers=other_business.headers()).json()
    assert [o["number"] for o in mine["items"]] == [parts["addis-retail"]["number"]]
    assert [o["number"] for o in theirs["items"]] == [parts["bahir-dar-traders"]["number"]]
    order = mine["items"][0]
    assert order["payment_method"] == "telebirr"
    assert order["delivery_method"] == "delivery"
    assert order["customer_message"] == "Saturday please"
    assert order["tracking_url"] == body["url"]
    assert {line["description"] for line in order["lines"]} == {"Teff 50kg", "Coffee 1kg"}
    other_id = theirs["items"][0]["id"]
    assert client.get(f"/api/v1/shop/orders/{other_id}", headers=business.headers()).status_code == 404

    # Each shop is emailed its own part, and only the linked shop gets Telegram.
    by_to = {m["to"]: m for m in mail.sent}
    assert "Teff 50kg" in by_to["grain@example.et"]["body"]
    assert "Cement" not in by_to["grain@example.et"]["body"]
    assert "Cement 50kg" in by_to["hardware@example.et"]["body"]
    assert "Teff" not in by_to["hardware@example.et"]["body"]
    assert "telebirr" in by_to["grain@example.et"]["body"]
    assert len(telegram.sent) == 1
    assert telegram.sent[0]["chat_id"] == "4242"
    assert "Cement 50kg" in telegram.sent[0]["text"] and "Teff" not in telegram.sent[0]["text"]

    # Staff of each shop get an in-app notification for their own order.
    from app.models.system import Notification

    for biz in (business, other_business):
        notes = biz.db.query(Notification).filter_by(tenant_id=biz.tenant.id).all()
        assert [n.kind.value for n in notes] == ["new_order"]

    # The tracking page shows both parts.
    tracked = client.get(f"/api/v1/public/checkout/{body['token']}").json()
    assert tracked["kind"] == "order"
    assert {p["shop"]["slug"] for p in tracked["parts"]} == {"addis-retail", "bahir-dar-traders"}
    assert all(p["can_cancel"] for p in tracked["parts"])


def test_an_order_moves_through_confirm_ready_and_completion(two_shops, business, mail):
    teff = two_shops["teff"]
    result = place_orders(
        business.db,
        items=[CheckoutItem("addis-retail", teff.default_variant.id, Decimal("2"))],
        contact=contact(email="meseret@example.et"),
    )
    order = result.orders[0]
    assert order.status == OrderStatus.PLACED
    assert order.total_amount == Decimal("8400.00")

    confirm_order(business.db, business.ctx, order.id, delivery_charge=Decimal("300"), seller_note="Before noon")
    assert order.status == OrderStatus.CONFIRMED
    assert order.total_amount == Decimal("8700.00")
    assert mail.sent[-1]["to"] == "meseret@example.et"
    assert "confirmed" in mail.sent[-1]["subject"]
    assert result.tracking_url in mail.sent[-1]["body"]

    with pytest.raises(ConflictError):
        confirm_order(business.db, business.ctx, order.id)

    mark_order_ready(business.db, business.ctx, order.id)
    assert order.status == OrderStatus.READY

    balance = lambda: get_balance(  # noqa: E731
        business.db, business.tenant.id, teff.default_variant.id, business.location.id
    )
    assert balance() == Decimal("20.000")
    completed, sale_result = complete_order(business.db, business.ctx, order.id)
    assert completed.status == OrderStatus.COMPLETED
    assert completed.converted_sale_id == sale_result.sale.id
    assert sale_result.sale.total_amount == Decimal("8400.00")
    assert sale_result.sale.customer_id == order.customer_id
    assert any("delivery charge" in w for w in sale_result.warnings)
    assert balance() == Decimal("18.000")

    with pytest.raises(ConflictError, match="void the sale"):
        cancel_order(business.db, business.ctx, order.id)


def test_a_customer_can_withdraw_only_before_the_shop_confirms(client, two_shops, business):
    teff = two_shops["teff"]
    body = client.post(
        "/api/v1/public/checkout/orders",
        json={
            "items": [{"shop": "addis-retail", "variant_id": str(teff.default_variant.id), "quantity": "1"}],
            "contact_name": "Meseret Tadesse",
            "contact_phone": "0912000444",
        },
    ).json()
    token = body["token"]
    part = client.get(f"/api/v1/public/checkout/{token}").json()["parts"][0]

    cancelled = client.post(f"/api/v1/public/orders/{part['token']}/cancel", json={"reason": "Found it cheaper"})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    from app.models.system import Notification

    kinds = [n.kind.value for n in business.db.query(Notification).filter_by(tenant_id=business.tenant.id)]
    assert "order_update" in kinds

    # A confirmed order can no longer be withdrawn by the customer.
    order = place_orders(
        business.db,
        items=[CheckoutItem("addis-retail", teff.default_variant.id, Decimal("1"))],
        contact=contact(),
    ).orders[0]
    confirm_order(business.db, business.ctx, order.id)
    refused = client.post(f"/api/v1/public/orders/{order.share_token}/cancel", json={})
    assert refused.status_code == 409
    assert "already confirmed" in refused.json()["message"]


def test_a_shop_that_takes_requests_only_cannot_be_ordered_from(client, two_shops, other_business):
    two_shops["hardware"].accepts_orders = False
    other_business.db.flush()
    cement = two_shops["cement"]
    items = [{"shop": "bahir-dar-traders", "variant_id": str(cement.default_variant.id), "quantity": "1"}]
    refused = client.post(
        "/api/v1/public/checkout/orders",
        json={"items": items, "contact_name": "Meseret", "contact_phone": "0912000444"},
    )
    assert refused.status_code == 422
    assert "proforma requests only" in refused.json()["message"]
    assert refused.json()["details"]["proforma_only_shops"] == ["bahir-dar-traders"]

    allowed = client.post(
        "/api/v1/public/checkout/proforma-requests",
        json={"items": items, "contact_name": "Meseret", "contact_phone": "0912000444"},
    )
    assert allowed.status_code == 201


def test_unknown_shops_and_unpublished_items_are_refused(client, two_shops, other_business):
    private = other_business.db.query(Order).count()  # noqa: F841  (touch the session)
    from app.models.catalogue import Product

    hidden = other_business.db.query(Product).filter_by(name="Private item").one()
    refused = client.post(
        "/api/v1/public/checkout/orders",
        json={
            "items": [{"shop": "bahir-dar-traders", "variant_id": str(hidden.default_variant.id), "quantity": "1"}],
            "contact_name": "Meseret",
            "contact_phone": "0912000444",
        },
    )
    assert refused.status_code == 422
    assert refused.json()["details"]["unavailable"] == [str(hidden.default_variant.id)]

    refused = client.post(
        "/api/v1/public/checkout/orders",
        json={
            "items": [{"shop": "nowhere", "variant_id": str(two_shops["teff"].default_variant.id), "quantity": "1"}],
            "contact_name": "Meseret",
            "contact_phone": "0912000444",
        },
    )
    assert refused.status_code == 422
    assert refused.json()["details"]["unavailable_shops"] == ["nowhere"]


def test_checkouts_are_rate_limited_per_address(client, two_shops, monkeypatch):
    from app.core import deps

    monkeypatch.setattr(deps.public_limiter, "limit", 1)
    teff = two_shops["teff"]
    payload = {
        "items": [{"shop": "addis-retail", "variant_id": str(teff.default_variant.id), "quantity": "1"}],
        "contact_name": "Meseret",
        "contact_phone": "0912000444",
    }
    assert client.post("/api/v1/public/checkout/orders", json=payload).status_code == 201
    assert client.post("/api/v1/public/checkout/orders", json=payload).status_code == 429


# --------------------------------------------------------------------------- #
# Proforma requests across shops
# --------------------------------------------------------------------------- #


def test_a_cart_sent_to_several_shops_becomes_one_request_each(client, two_shops, business, other_business, mail, telegram):
    teff, cement = two_shops["teff"], two_shops["cement"]
    response = client.post(
        "/api/v1/public/checkout/proforma-requests",
        json={
            "items": [
                {"shop": "addis-retail", "variant_id": str(teff.default_variant.id), "quantity": "100"},
                {"shop": "bahir-dar-traders", "variant_id": str(cement.default_variant.id), "quantity": "200"},
            ],
            "contact_name": "Selam Construction",
            "contact_phone": "0913000333",
            "contact_email": "selam@example.et",
            "company": "Selam Construction PLC",
            "message": "Site delivery, Ayat",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "proforma"
    assert len(body["parts"]) == 2
    assert all(p["status"] == "requested" and p["url"] and "/q/" in p["url"] for p in body["parts"])

    grain_requests = client.get("/api/v1/shop/quotations?status=requested", headers=business.headers()).json()
    hardware_requests = client.get("/api/v1/shop/quotations?status=requested", headers=other_business.headers()).json()
    assert [q["lines"][0]["description"] for q in grain_requests["items"]] == ["Teff 50kg"]
    assert [q["lines"][0]["description"] for q in hardware_requests["items"]] == ["Cement 50kg"]
    assert grain_requests["items"][0]["customer_company"] == "Selam Construction PLC"

    by_to = {m["to"]: m for m in mail.sent}
    assert "Teff 50kg × 100" in by_to["grain@example.et"]["body"]
    assert "Cement" not in by_to["grain@example.et"]["body"]
    assert "Cement 50kg × 200" in by_to["hardware@example.et"]["body"]
    assert "Proforma request" in by_to["hardware@example.et"]["subject"]
    assert [m["chat_id"] for m in telegram.sent] == ["4242"]
    assert "Cement 50kg" in telegram.sent[0]["text"] and "Teff" not in telegram.sent[0]["text"]

    tracked = client.get(f"/api/v1/public/checkout/{body['token']}").json()
    assert tracked["kind"] == "proforma"
    assert [p["kind"] for p in tracked["parts"]] == ["proforma", "proforma"]
    assert all(p["next_step"] for p in tracked["parts"])

    # Each shop sends its own proforma; the customer's part link and tracking page both update.
    quotation = business.db.query(Quotation).filter_by(tenant_id=business.tenant.id).one()
    from app.services.commerce import send_quotation

    send_quotation(business.db, business.ctx, quotation.id)
    assert quotation.status == QuotationStatus.SENT
    tracked = client.get(f"/api/v1/public/checkout/{body['token']}").json()
    statuses = {p["shop"]["slug"]: p["status"] for p in tracked["parts"]}
    assert statuses == {"addis-retail": "sent", "bahir-dar-traders": "requested"}
    view = client.get(f"/api/v1/public/quotations/{quotation.share_token}").json()
    assert view["tracking_url"] == body["url"]


def test_a_request_without_a_batch_still_works_from_one_shop(two_shops, business, mail):
    """The single-shop path used by a shop's own page keeps working."""
    result = request_proformas(
        business.db,
        items=[CheckoutItem("addis-retail", two_shops["teff"].default_variant.id, Decimal("1"))],
        contact=contact(),
    )
    assert len(result.quotations) == 1
    assert mail.sent[-1]["to"] == "grain@example.et"


# --------------------------------------------------------------------------- #
# Telegram linking
# --------------------------------------------------------------------------- #


def test_a_shop_links_telegram_by_pressing_start(client, business, telegram, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    monkeypatch.setattr(settings, "telegram_bot_username", "EstockShopBot")
    store = open_shop(business)

    started = client.post("/api/v1/shop/telegram/link", headers=business.headers())
    assert started.status_code == 200
    body = started.json()
    assert body["telegram_configured"] is True
    assert body["telegram_linked"] is False
    assert body["telegram_start_url"].startswith("https://t.me/EstockShopBot?start=")
    code = body["telegram_start_url"].split("start=")[1]

    # The owner presses Start; the poller sees it and links the chat.
    telegram.pending = [
        {"update_id": 7, "message": {"text": "/start nonsense", "chat": {"id": 1}, "from": {}}},
        {"update_id": 8, "message": {"text": f"/start {code}", "chat": {"id": 9001}, "from": {"username": "grainshop"}}},
    ]
    linked = messaging.sync_telegram_links(business.db, sender=telegram)
    assert linked == 1
    assert telegram.confirmed_offset == 9
    business.db.refresh(store)
    assert store.telegram_chat_id == "9001"
    assert store.telegram_link_code is None
    assert store.telegram_username == "grainshop"
    assert "connected" in telegram.sent[-1]["text"]

    settings_now = client.get("/api/v1/shop/settings", headers=business.headers()).json()
    assert settings_now["telegram_linked"] is True

    dropped = client.delete("/api/v1/shop/telegram/link", headers=business.headers())
    assert dropped.json()["telegram_linked"] is False


def test_the_webhook_needs_its_secret(client, business, telegram, monkeypatch):
    from app.core.config import settings

    assert client.post("/api/v1/public/telegram/webhook", json={}).status_code == 404
    monkeypatch.setattr(settings, "telegram_webhook_secret", "s3cret")
    assert client.post("/api/v1/public/telegram/webhook", json={}).status_code == 403

    store = open_shop(business)
    code = messaging.begin_telegram_link(business.db, store)
    accepted = client.post(
        "/api/v1/public/telegram/webhook",
        json={"update_id": 1, "message": {"text": f"/start {code}", "chat": {"id": 55}, "from": {}}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["linked"] is True
    business.db.refresh(store)
    assert store.telegram_chat_id == "55"


def test_without_a_bot_token_telegram_is_only_logged(business, two_shops):
    messaging.set_telegram_sender(None)
    assert isinstance(messaging.telegram_sender(), messaging.TelegramSender)
    assert not isinstance(messaging.telegram_sender(), messaging.BotApiTelegramSender)
    # Linked chat, no transport: the checkout still succeeds.
    result = place_orders(
        business.db,
        items=[CheckoutItem("bahir-dar-traders", two_shops["cement"].default_variant.id, Decimal("1"))],
        contact=contact(),
    )
    assert result.orders[0].status == OrderStatus.PLACED


def test_a_zero_quantity_or_empty_cart_is_refused(business, two_shops):
    with pytest.raises(ValidationError, match="empty"):
        place_orders(business.db, items=[], contact=contact())
    with pytest.raises(ValidationError, match="positive"):
        place_orders(
            business.db,
            items=[CheckoutItem("addis-retail", two_shops["teff"].default_variant.id, Decimal("0"))],
            contact=contact(),
        )
