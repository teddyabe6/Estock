"""The storefront as a shop: basket → proforma request → review → send → accept.

A request never reserves or reduces stock; only the explicit conversion does
(PRD 13, 14).
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest

from app.core.errors import ConflictError, ValidationError
from app.models.commerce import QuotationStatus
from app.services.commerce import (
    BasketItem,
    cancel_quotation,
    get_public_store,
    request_quotation,
    send_quotation,
    update_quotation,
)
from app.services.inventory import get_balance


def publish(business):
    from app.models.commerce import OnlineStore

    store = business.db.query(OnlineStore).filter_by(tenant_id=business.tenant.id).one()
    store.is_published = True
    store.default_terms = "Payment on delivery."
    business.db.flush()
    return store


def basket_request(client, store, items, **contact):
    payload = {
        "items": items,
        "contact_name": "Meseret Tadesse",
        "contact_phone": "0912 00 04 44",
        **contact,
    }
    return client.post(f"/api/v1/public/shops/{store.slug}/proforma-requests", json=payload)


# --------------------------------------------------------------------------- #
# Requesting from the basket
# --------------------------------------------------------------------------- #


def test_a_basket_becomes_a_numbered_proforma_request(client, business):
    store = publish(business)
    coffee = business.add_product(
        "Coffee 1kg", selling_price="850", opening_stock="20", is_published=True
    )
    sugar = business.add_product(
        "Sugar 50kg", selling_price="4200", opening_stock="8", is_published=True
    )

    response = basket_request(
        client,
        store,
        [
            {"variant_id": str(coffee.default_variant.id), "quantity": "3"},
            {"variant_id": str(sugar.default_variant.id), "quantity": "1"},
        ],
        delivery_location="Bole",
        message="Saturday morning please",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["number"].startswith("PF-")
    assert body["status"] == "requested"
    assert body["item_count"] == 2
    assert body["total_amount"] == "6750.00"
    assert body["url"].endswith(f"/q/{body['token']}")

    # Stock is untouched: a request reserves nothing.
    assert get_balance(
        business.db, business.tenant.id, coffee.default_variant.id, business.location.id
    ) == Decimal("20.000")

    # The seller sees it, priced from the catalogue, with the customer's note.
    listed = client.get(
        "/api/v1/shop/quotations?status=requested", headers=business.headers()
    ).json()
    assert listed["total"] == 1
    quotation = listed["items"][0]
    assert quotation["source"] == "storefront"
    assert quotation["can_edit"] is True
    assert quotation["customer_message"] == "Saturday morning please"
    assert quotation["terms"] == "Payment on delivery."
    assert {line["description"]: line["unit_price"] for line in quotation["lines"]} == {
        "Coffee 1kg": "850.00",
        "Sugar 50kg": "4200.00",
    }
    assert quotation["share"]["url"] == body["url"]


def test_the_customer_is_matched_by_phone_not_duplicated(client, business):
    store = publish(business)
    product = business.add_product("Item", selling_price="100", opening_stock="5", is_published=True)
    existing = business.add_customer("Meseret T.", phone="+251912000444")

    response = basket_request(
        client, store, [{"variant_id": str(product.default_variant.id), "quantity": "1"}]
    )
    assert response.status_code == 201
    from app.models.commerce import Quotation
    from app.models.contacts import Customer

    customers = business.db.query(Customer).filter_by(tenant_id=business.tenant.id).all()
    assert len(customers) == 1
    quotation = business.db.query(Quotation).filter_by(tenant_id=business.tenant.id).one()
    assert quotation.customer_id == existing.id
    assert quotation.customer_phone == "+251912000444"


def test_a_new_customer_record_is_created_from_the_request(client, business):
    store = publish(business)
    product = business.add_product("Item", selling_price="100", opening_stock="5", is_published=True)
    basket_request(
        client,
        store,
        [{"variant_id": str(product.default_variant.id), "quantity": "2"}],
        company="Meseret Trading",
        contact_email="meseret@example.et",
    )
    from app.models.contacts import Customer

    customer = business.db.query(Customer).filter_by(tenant_id=business.tenant.id).one()
    assert customer.name == "Meseret Tadesse"
    assert customer.phone == "+251912000444"
    assert customer.company == "Meseret Trading"
    assert customer.email == "meseret@example.et"


def test_only_published_products_can_be_requested(client, business):
    store = publish(business)
    hidden = business.add_product("Hidden", selling_price="100", opening_stock="5")
    response = basket_request(
        client, store, [{"variant_id": str(hidden.default_variant.id), "quantity": "1"}]
    )
    assert response.status_code == 422
    assert "no longer available" in response.json()["message"]
    assert response.json()["details"]["unavailable"] == [str(hidden.default_variant.id)]


def test_another_shops_product_cannot_be_requested(client, business, other_business):
    store = publish(business)
    theirs = other_business.add_product(
        "Theirs", selling_price="100", opening_stock="5", is_published=True
    )
    response = basket_request(
        client, store, [{"variant_id": str(theirs.default_variant.id), "quantity": "1"}]
    )
    assert response.status_code == 422


def test_an_empty_or_absurd_basket_is_refused(client, business):
    store = publish(business)
    product = business.add_product("Item", selling_price="100", opening_stock="5", is_published=True)
    assert basket_request(client, store, []).status_code == 422
    assert (
        basket_request(
            client, store, [{"variant_id": str(product.default_variant.id), "quantity": "0"}]
        ).status_code
        == 422
    )
    assert (
        basket_request(
            client,
            store,
            [{"variant_id": str(product.default_variant.id), "quantity": "1"}],
            contact_name="M",
        ).status_code
        == 422
    )


def test_duplicate_basket_lines_are_merged(business):
    store = publish(business)
    product = business.add_product("Item", selling_price="10", opening_stock="5", is_published=True)
    store, tenant = get_public_store(business.db, store.slug)
    variant_id = product.default_variant.id
    quotation = request_quotation(
        business.db,
        store,
        tenant,
        items=[BasketItem(variant_id, Decimal("2")), BasketItem(variant_id, Decimal("3"))],
        contact_name="Meseret",
        contact_phone="0912000444",
    )
    assert len(quotation.lines) == 1
    assert quotation.lines[0].quantity == Decimal("5")
    assert quotation.total_amount == Decimal("50.00")


def test_staff_who_handle_proformas_are_notified(client, business):
    from app.models.system import Notification

    store = publish(business)
    product = business.add_product("Item", selling_price="100", opening_stock="5", is_published=True)
    basket_request(client, store, [{"variant_id": str(product.default_variant.id), "quantity": "1"}])
    notes = business.db.query(Notification).filter_by(tenant_id=business.tenant.id).all()
    assert [n.kind.value for n in notes] == ["proforma_request"]
    assert notes[0].user_id == business.owner.id
    assert "Meseret Tadesse" in notes[0].title
    assert notes[0].link.startswith("/shop?tab=proformas&open=")

    summary = client.get("/api/v1/shop/summary", headers=business.headers()).json()
    assert summary["proforma_requests"] == 1


def test_requests_are_rate_limited_per_address(client, business, monkeypatch):
    from app.core import deps

    monkeypatch.setattr(deps.public_limiter, "limit", 2)
    store = publish(business)
    product = business.add_product("Item", selling_price="100", opening_stock="5", is_published=True)
    items = [{"variant_id": str(product.default_variant.id), "quantity": "1"}]
    assert basket_request(client, store, items).status_code == 201
    assert basket_request(client, store, items).status_code == 201
    assert basket_request(client, store, items).status_code == 429


# --------------------------------------------------------------------------- #
# The customer's tracking link
# --------------------------------------------------------------------------- #


def test_the_tracking_link_shows_the_request_and_cannot_be_accepted_yet(client, business):
    store = publish(business)
    store.telegram_username = "addisretail"
    product = business.add_product("Item", selling_price="100", opening_stock="5", is_published=True)
    token = basket_request(
        client, store, [{"variant_id": str(product.default_variant.id), "quantity": "2"}]
    ).json()["token"]

    view = client.get(f"/api/v1/public/quotations/{token}")
    assert view.status_code == 200
    body = view.json()
    assert body["status"] == "requested"
    assert body["can_respond"] is False
    assert "reviewing your request" in body["next_step"]
    assert body["shop"]["slug"] == store.slug
    assert body["shop"]["telegram_username"] == "addisretail"
    assert body["amounts_visible"] is True
    assert body["total_amount"] == "200.00"

    refused = client.post(f"/api/v1/public/quotations/{token}/respond?accept=true")
    assert refused.status_code == 409
    assert "not sent" in refused.json()["message"]


def test_amounts_stay_hidden_on_a_request_when_the_shop_hides_prices(client, business):
    store = publish(business)
    store.show_prices = False
    business.db.flush()
    product = business.add_product("Item", selling_price="100", opening_stock="5", is_published=True)
    created = basket_request(
        client, store, [{"variant_id": str(product.default_variant.id), "quantity": "2"}]
    ).json()
    assert created["total_amount"] is None

    body = client.get(f"/api/v1/public/quotations/{created['token']}").json()
    assert body["amounts_visible"] is False
    assert body["total_amount"] is None
    assert body["lines"][0]["unit_price"] is None
    assert Decimal(body["lines"][0]["quantity"]) == Decimal("2")

    # Once the seller sends it, the priced proforma is what the customer sees.
    from app.models.commerce import Quotation

    quotation = business.db.query(Quotation).filter_by(tenant_id=business.tenant.id).one()
    send_quotation(business.db, business.ctx, quotation.id)
    body = client.get(f"/api/v1/public/quotations/{created['token']}").json()
    assert body["status"] == "sent"
    assert body["total_amount"] == "200.00"


# --------------------------------------------------------------------------- #
# The seller's review
# --------------------------------------------------------------------------- #


def test_the_seller_reviews_prices_and_delivery_then_sends(client, business):
    store = publish(business)
    product = business.add_product("Item", selling_price="100", opening_stock="5", is_published=True)
    created = basket_request(
        client, store, [{"variant_id": str(product.default_variant.id), "quantity": "2"}]
    ).json()
    quotation_id = client.get(
        "/api/v1/shop/quotations", headers=business.headers()
    ).json()["items"][0]["id"]

    edited = client.patch(
        f"/api/v1/shop/quotations/{quotation_id}",
        json={
            "lines": [
                {"variant_id": str(product.default_variant.id), "quantity": "2", "unit_price": "95"}
            ],
            "delivery_charge": "150",
            "validity_days": 7,
            "note": "Bulk price applied",
        },
        headers=business.headers(),
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["subtotal"] == "190.00"
    assert body["delivery_charge"] == "150.00"
    assert body["total_amount"] == "340.00"
    assert body["note"] == "Bulk price applied"
    assert body["status"] == "requested"

    sent = client.post(f"/api/v1/shop/quotations/{quotation_id}/send", headers=business.headers())
    assert sent.status_code == 200
    assert sent.json()["status"] == "sent"
    assert sent.json()["valid_until"] is not None
    # The customer's link is the same one they were given at checkout.
    assert sent.json()["share"]["url"] == created["url"]

    public = client.get(f"/api/v1/public/quotations/{created['token']}").json()
    assert public["can_respond"] is True
    assert public["total_amount"] == "340.00"

    accepted = client.post(f"/api/v1/public/quotations/{created['token']}/respond?accept=true")
    assert accepted.status_code == 200
    from app.models.system import Notification

    kinds = [
        n.kind.value
        for n in business.db.query(Notification).filter_by(tenant_id=business.tenant.id)
    ]
    assert kinds.count("proforma_response") == 1

    # Editing after acceptance is refused: the numbers are what was agreed.
    again = client.patch(
        f"/api/v1/shop/quotations/{quotation_id}",
        json={"delivery_charge": "0"},
        headers=business.headers(),
    )
    assert again.status_code == 409


def test_a_product_line_without_a_price_cannot_be_sent(business):
    store = publish(business)
    product = business.add_product(
        "Unpriced", selling_price=None, opening_stock="5", is_published=True
    )
    store, tenant = get_public_store(business.db, store.slug)
    quotation = request_quotation(
        business.db,
        store,
        tenant,
        items=[BasketItem(product.default_variant.id, Decimal("1"))],
        contact_name="Meseret",
        contact_phone="0912000444",
    )
    with pytest.raises(ValidationError, match="Give every item a price"):
        send_quotation(business.db, business.ctx, quotation.id)

    from app.services.commerce import QuotationLineInput

    update_quotation(
        business.db,
        business.ctx,
        quotation.id,
        lines=[
            QuotationLineInput(
                variant_id=product.default_variant.id,
                quantity=Decimal("1"),
                unit_price=Decimal("75"),
            )
        ],
    )
    send_quotation(business.db, business.ctx, quotation.id)
    assert quotation.status == QuotationStatus.SENT
    assert quotation.total_amount == Decimal("75.00")


def test_a_cancelled_request_disappears_from_the_customer_link(client, business):
    store = publish(business)
    product = business.add_product("Item", selling_price="100", opening_stock="5", is_published=True)
    created = basket_request(
        client, store, [{"variant_id": str(product.default_variant.id), "quantity": "1"}]
    ).json()
    quotation_id = client.get(
        "/api/v1/shop/quotations", headers=business.headers()
    ).json()["items"][0]["id"]

    cancelled = client.post(
        f"/api/v1/shop/quotations/{quotation_id}/cancel",
        json={"reason": "Out of season"},
        headers=business.headers(),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert client.get(f"/api/v1/public/quotations/{created['token']}").status_code == 404

    from app.models.platform import AuditEvent

    events = business.db.query(AuditEvent).filter_by(tenant_id=business.tenant.id).all()
    assert any("Out of season" in (e.summary or "") for e in events)


def test_a_converted_proforma_cannot_be_cancelled(business):
    from app.services.commerce import convert_to_sale

    store = publish(business)
    product = business.add_product("Item", selling_price="100", opening_stock="5", is_published=True)
    store, tenant = get_public_store(business.db, store.slug)
    quotation = request_quotation(
        business.db,
        store,
        tenant,
        items=[BasketItem(product.default_variant.id, Decimal("1"))],
        contact_name="Meseret",
        contact_phone="0912000444",
    )
    convert_to_sale(business.db, business.ctx, quotation.id)
    with pytest.raises(ConflictError, match="void the sale"):
        cancel_quotation(business.db, business.ctx, quotation.id)


def test_converting_a_request_deducts_stock_only_then(business):
    from app.services.commerce import convert_to_sale

    store = publish(business)
    product = business.add_product("Item", selling_price="100", opening_stock="5", is_published=True)
    store, tenant = get_public_store(business.db, store.slug)
    quotation = request_quotation(
        business.db,
        store,
        tenant,
        items=[BasketItem(product.default_variant.id, Decimal("2"))],
        contact_name="Meseret",
        contact_phone="0912000444",
    )
    send_quotation(business.db, business.ctx, quotation.id)
    balance = lambda: get_balance(  # noqa: E731
        business.db, business.tenant.id, product.default_variant.id, business.location.id
    )
    assert balance() == Decimal("5.000")
    result = convert_to_sale(business.db, business.ctx, quotation.id)
    assert balance() == Decimal("3.000")
    assert result.sale.customer_id == quotation.customer_id


def test_a_salesperson_without_the_permission_cannot_edit(client, business):
    from app.core.permissions import RoleName

    store = publish(business)
    product = business.add_product("Item", selling_price="100", opening_stock="5", is_published=True)
    basket_request(client, store, [{"variant_id": str(product.default_variant.id), "quantity": "1"}])
    quotation_id = client.get(
        "/api/v1/shop/quotations", headers=business.headers()
    ).json()["items"][0]["id"]
    stock_user, _ = business.add_user(RoleName.STOCK_USER)
    response = client.patch(
        f"/api/v1/shop/quotations/{quotation_id}",
        json={"delivery_charge": "10"},
        headers=business.headers(stock_user),
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# Browsing: categories, product pages, photos
# --------------------------------------------------------------------------- #


def test_the_shop_lists_its_categories_and_filters_by_them(client, business):
    store = publish(business)
    business.add_product("Coffee", selling_price="850", opening_stock="5", is_published=True, category_name="Drinks")
    business.add_product("Tea", selling_price="120", opening_stock="5", is_published=True, category_name="Drinks")
    business.add_product("Cement", selling_price="900", opening_stock="5", is_published=True, category_name="Building")
    business.add_product("Secret", selling_price="1", opening_stock="5", category_name="Hidden")

    shop = client.get(f"/api/v1/public/shops/{store.slug}").json()
    assert shop["categories"] == ["Building", "Drinks"]

    drinks = client.get(f"/api/v1/public/shops/{store.slug}/products?category=drinks").json()
    assert [item["name"] for item in drinks["items"]] == ["Coffee", "Tea"]
    assert drinks["total"] == 2


def test_a_product_has_its_own_public_page(client, business, other_business):
    store = publish(business)
    product = business.add_product(
        "Coffee", selling_price="850", opening_stock="5", is_published=True,
        online_description="Washed Yirgacheffe, medium roast",
    )
    hidden = business.add_product("Hidden", selling_price="1", opening_stock="5")

    page = client.get(f"/api/v1/public/shops/{store.slug}/products/{product.id}")
    assert page.status_code == 200
    body = page.json()
    assert body["name"] == "Coffee"
    assert body["description"] == "Washed Yirgacheffe, medium roast"
    assert body["price"] == "850.00"
    assert body["currency"] == "ETB"
    assert body["variants"][0]["in_stock"] is True

    assert client.get(f"/api/v1/public/shops/{store.slug}/products/{hidden.id}").status_code == 404
    theirs = other_business.add_product("Theirs", selling_price="1", opening_stock="5", is_published=True)
    assert client.get(f"/api/v1/public/shops/{store.slug}/products/{theirs.id}").status_code == 404


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
    b"\x00\x00IEND\xaeB`\x82"
)


def test_a_product_photo_is_uploaded_served_publicly_and_removable(client, business):
    store = publish(business)
    product = business.add_product("Coffee", selling_price="850", opening_stock="5", is_published=True)

    uploaded = client.post(
        f"/api/v1/products/{product.id}/image",
        files={"file": ("coffee.png", io.BytesIO(PNG), "image/png")},
        headers=business.headers(),
    )
    assert uploaded.status_code == 200, uploaded.text
    image_url = uploaded.json()["image_url"]
    assert image_url and "/public/files/" in image_url

    # The storefront shows it, and the file is served without a token.
    listed = client.get(f"/api/v1/public/shops/{store.slug}/products").json()
    assert listed["items"][0]["image_url"] == image_url
    path = image_url.split("/api/v1", 1)[1]
    served = client.get(f"/api/v1{path}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == PNG
    assert "immutable" in served.headers["cache-control"]

    # Replacing it discards the old file; removing it clears the product.
    replaced = client.post(
        f"/api/v1/products/{product.id}/image",
        files={"file": ("coffee2.png", io.BytesIO(PNG), "image/png")},
        headers=business.headers(),
    )
    assert replaced.json()["image_url"] != image_url
    assert client.get(f"/api/v1{path}").status_code == 404

    removed = client.delete(f"/api/v1/products/{product.id}/image", headers=business.headers())
    assert removed.status_code == 200
    assert removed.json()["image_url"] is None


def test_only_images_are_accepted_as_product_photos(client, business):
    product = business.add_product("Coffee", selling_price="850", opening_stock="5")
    response = client.post(
        f"/api/v1/products/{product.id}/image",
        files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
        headers=business.headers(),
    )
    assert response.status_code == 422
    assert "not accepted" in response.json()["message"]


def test_private_uploads_are_never_served_publicly(client, business):
    from app.models.system import FileAsset
    from app.services.storage import get_storage

    key = get_storage().save(business.tenant.id, "import.csv", b"name,price\n")
    asset = FileAsset(
        tenant_id=business.tenant.id,
        filename="import.csv",
        content_type="text/csv",
        size_bytes=11,
        storage_key=key,
        is_public=False,
    )
    business.db.add(asset)
    business.db.flush()
    assert client.get(f"/api/v1/public/files/{asset.id}").status_code == 404
