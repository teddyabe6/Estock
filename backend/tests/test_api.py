"""HTTP-level behaviour: the whole stack, including error shapes (PRD 21)."""

from __future__ import annotations


def test_health_endpoints(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/health/ready").json()["database"] == "ok"


def test_register_then_use_the_returned_token(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Hawassa Hardware",
            "full_name": "Selam Kebede",
            "email": "selam@hawassa.et",
            "password": "strong-password-1",
            "phone": "0911998877",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"]

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    session = client.get("/api/v1/auth/session", headers=headers).json()
    assert session["tenant_name"] == "Hawassa Hardware"
    assert session["currency"] == "ETB"
    assert session["role"] == "owner"
    assert len(session["branches"]) == 1
    assert session["branches"][0]["name"] == "Main Branch"
    assert session["subscription"]["read_only"] is False


def test_login_with_a_wrong_password_is_indistinguishable(client, business):
    unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@nowhere-at-all.et", "password": "whatever"},
    )
    wrong = client.post(
        "/api/v1/auth/login",
        json={"email": business.owner.email, "password": "wrong-password"},
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["message"] == wrong.json()["message"]


def test_register_rejects_a_weak_password(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Too Easy",
            "full_name": "Someone",
            "email": "someone@newshop.et",
            "password": "short",
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_create_a_product_and_record_a_sale_over_http(client, business):
    created = client.post(
        "/api/v1/products",
        json={
            "name": "Macchiato",
            "selling_price": "45.00",
            "purchase_price": "20.00",
            "opening_stock": "100",
            "category_name": "Drinks",
        },
        headers=business.headers(),
    )
    assert created.status_code == 201
    product = created.json()
    variant_id = product["variants"][0]["id"]
    assert product["quantity_on_hand"] == "100.000"

    sale = client.post(
        "/api/v1/sales",
        json={
            "lines": [{"variant_id": variant_id, "quantity": "2"}],
            "payments": [{"method": "cash", "amount": "90.00"}],
        },
        headers=business.headers(),
    )
    assert sale.status_code == 201
    body = sale.json()["sale"]
    assert body["total_amount"] == "90.00"
    assert body["balance_due"] == "0.00"
    assert sale.json()["credit_transaction_id"] is None

    refreshed = client.get(
        f"/api/v1/products/{product['id']}", headers=business.headers()
    ).json()
    assert refreshed["quantity_on_hand"] == "98.000"


def test_a_credit_sale_over_http_creates_a_receivable(client, business):
    customer = client.post(
        "/api/v1/customers",
        json={"name": "Yonas Alemu", "phone": "0911223355"},
        headers=business.headers(),
    ).json()
    product = client.post(
        "/api/v1/products",
        json={"name": "Cement bag", "selling_price": "1200.00", "opening_stock": "50"},
        headers=business.headers(),
    ).json()

    sale = client.post(
        "/api/v1/sales",
        json={
            "lines": [{"variant_id": product["variants"][0]["id"], "quantity": "5"}],
            "payments": [{"method": "cash", "amount": "2000.00"}],
            "customer_id": customer["id"],
            "due_date_preset": "30_days",
        },
        headers=business.headers(),
    )
    assert sale.status_code == 201
    transaction_id = sale.json()["credit_transaction_id"]
    assert transaction_id

    transaction = client.get(
        f"/api/v1/credit/transactions/{transaction_id}", headers=business.headers()
    ).json()
    assert transaction["original_amount"] == "6000.00"
    assert transaction["balance"] == "4000.00"
    assert transaction["status"] == "partially_paid"
    assert transaction["is_overdue"] is False
    assert transaction["counterparty_name"] == "Yonas Alemu"

    summary = client.get(
        "/api/v1/credit/summary?kind=receivable", headers=business.headers()
    ).json()
    assert summary["total_outstanding"] == "4000.00"
    assert summary["due_within_7_days"] == "0.00"


def test_recording_a_credit_payment_over_http(client, business):
    customer = business.add_customer("Meron")
    product = business.add_product("Sand truck", selling_price="9000", opening_stock="5")
    result = business.sell(product, paid="0", customer_id=customer.id)

    response = client.post(
        f"/api/v1/credit/transactions/{result.credit_transaction.id}/payments",
        json={"amount": "4000.00", "method": "telebirr", "reference": "TB-9931"},
        headers=business.headers(),
    )
    assert response.status_code == 201
    assert response.json()["balance"] == "5000.00"
    assert response.json()["status"] == "partially_paid"


def test_overpayment_over_http_returns_a_clear_error(client, business):
    customer = business.add_customer("Meron")
    product = business.add_product("Sand truck", selling_price="1000", opening_stock="5")
    result = business.sell(product, paid="0", customer_id=customer.id)

    response = client.post(
        f"/api/v1/credit/transactions/{result.credit_transaction.id}/payments",
        json={"amount": "5000.00", "method": "cash"},
        headers=business.headers(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "overpayment"
    assert response.json()["details"]["balance"] == "1000.00"


def test_insufficient_stock_over_http(client, business):
    product = business.add_product("Rare", selling_price="10", opening_stock="1")
    response = client.post(
        "/api/v1/sales",
        json={
            "lines": [{"variant_id": str(product.default_variant.id), "quantity": "5"}],
            "payments": [{"method": "cash", "amount": "50.00"}],
        },
        headers=business.headers(),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "insufficient_stock"
    assert response.json()["details"]["available"] == "1.000"


def test_barcode_lookup(client, business):
    business.add_product("Scanned", barcode="6001234567890", selling_price="35", opening_stock="9")
    found = client.get(
        "/api/v1/products/lookup/barcode/6001234567890", headers=business.headers()
    )
    assert found.status_code == 200
    assert found.json()["barcode"] == "6001234567890"

    missing = client.get(
        "/api/v1/products/lookup/barcode/0000000000000", headers=business.headers()
    )
    assert missing.status_code == 404


def test_dashboard_reports_todays_figures(client, business):
    product = business.add_product(
        "Dashboard item", selling_price="100", purchase_price="70", opening_stock="20"
    )
    business.sell(product, quantity="3")

    payload = client.get("/api/v1/dashboard", headers=business.headers()).json()
    assert payload["today"]["sale_count"] == 1
    assert payload["today"]["net_sales"] == "300.00"
    assert payload["today"]["gross_profit"] == "90.00"
    assert payload["currency"] == "ETB"
    assert "setup" in payload


def test_stock_reconciliation_endpoint_reports_agreement(client, business):
    product = business.add_product("Reconciled", selling_price="10", opening_stock="10")
    business.sell(product, quantity="2")
    payload = client.get("/api/v1/stock/reconciliation", headers=business.headers()).json()
    assert payload["in_balance"] is True
    assert payload["discrepancies"] == []


def test_receipt_endpoint_returns_printable_data(client, business):
    product = business.add_product("Receipt item", selling_price="60", opening_stock="10")
    sale = business.sell(product, quantity="2").sale

    payload = client.get(
        f"/api/v1/sales/{sale.id}/receipt", headers=business.headers()
    ).json()
    assert payload["business"]["name"] == business.tenant.name
    assert payload["sale"]["total_amount"] == "120.00"
    assert payload["lines"][0]["description"] == "Receipt item"
    assert payload["payments"][0]["method"] == "cash"


def test_pricing_suggestion_states_the_calculation(client, business):
    client.put(
        "/api/v1/pricing-rules",
        json={"scope": "business", "basis": "margin", "rate": "0.25"},
        headers=business.headers(),
    )
    payload = client.get(
        "/api/v1/pricing/suggest?cost=100", headers=business.headers()
    ).json()
    assert payload["suggested_price"] == "133.33"
    assert payload["basis"] == "margin"
    assert "gross margin" in payload["explanation"]


def test_public_storefront_and_enquiry(client, business):
    from app.models.commerce import OnlineStore

    business.add_product(
        "Public item", selling_price="150", opening_stock="10", is_published=True
    )
    store = business.db.query(OnlineStore).filter_by(tenant_id=business.tenant.id).one()
    store.is_published = True
    business.db.flush()

    shop = client.get(f"/api/v1/public/shops/{store.slug}")
    assert shop.status_code == 200
    assert shop.json()["currency"] == "ETB"

    products = client.get(f"/api/v1/public/shops/{store.slug}/products").json()
    assert products["total"] == 1
    assert products["items"][0]["name"] == "Public item"
    assert products["items"][0]["price"] == "150.00"

    enquiry = client.post(
        f"/api/v1/public/shops/{store.slug}/enquiries",
        json={
            "contact_name": "Bereket",
            "contact_phone": "0922334455",
            "message": "Is this available in bulk?",
            "wants_proforma": True,
        },
    )
    assert enquiry.status_code == 201
    assert enquiry.json()["status"] == "new"


def test_the_public_storefront_needs_no_token(client, business):
    """A customer browsing the shop is never asked to sign in (PRD 13)."""
    from app.models.commerce import OnlineStore

    store = business.db.query(OnlineStore).filter_by(tenant_id=business.tenant.id).one()
    store.is_published = True
    business.db.flush()
    assert client.get(f"/api/v1/public/shops/{store.slug}/products").status_code == 200


def test_proforma_share_link_is_viewable_without_a_token(client, business):
    product = business.add_product("Quoted", selling_price="700", opening_stock="10")
    created = client.post(
        "/api/v1/shop/quotations",
        json={
            "customer_name": "Sara Haile",
            "customer_phone": "0911445566",
            "lines": [
                {"variant_id": str(product.default_variant.id), "quantity": "3"}
            ],
        },
        headers=business.headers(),
    )
    assert created.status_code == 201
    quotation = created.json()
    assert quotation["total_amount"] == "2100.00"

    sent = client.post(
        f"/api/v1/shop/quotations/{quotation['id']}/send", headers=business.headers()
    ).json()
    token = sent["share"]["url"].rsplit("/", 1)[-1]

    public = client.get(f"/api/v1/public/quotations/{token}")
    assert public.status_code == 200
    assert public.json()["number"] == quotation["number"]
    assert "not a receipt" in public.json()["disclaimer"]


def test_an_invalid_share_token_is_not_found(client):
    assert client.get("/api/v1/public/quotations/made-up-token").status_code == 404


def test_import_template_downloads_as_a_spreadsheet(client, business):
    response = client.get("/api/v1/imports/template", headers=business.headers())
    assert response.status_code == 200
    assert "spreadsheetml" in response.headers["content-type"]
    assert response.content[:2] == b"PK"  # xlsx is a zip


def test_notifications_list_is_per_user(client, business):
    from app.models.system import Notification, NotificationKind

    business.db.add(
        Notification(
            tenant_id=business.tenant.id,
            user_id=business.owner.id,
            kind=NotificationKind.GENERAL,
            title="Something happened",
        )
    )
    business.db.flush()

    payload = client.get("/api/v1/notifications", headers=business.headers()).json()
    assert payload["unread"] == 1
    assert payload["items"][0]["title"] == "Something happened"

    notification_id = payload["items"][0]["id"]
    client.post(f"/api/v1/notifications/{notification_id}/read", headers=business.headers())
    assert client.get("/api/v1/notifications", headers=business.headers()).json()["unread"] == 0


def test_branch_creation_makes_a_stock_location(client, business):
    response = client.post(
        "/api/v1/branches", json={"name": "Bole Branch"}, headers=business.headers()
    )
    assert response.status_code == 201
    branch_id = response.json()["id"]

    locations = client.get("/api/v1/locations", headers=business.headers()).json()
    assert any(loc["branch_id"] == branch_id for loc in locations)


def test_team_invitation_and_acceptance(client, business):
    invite = client.post(
        "/api/v1/team/invite",
        json={
            "email": "cashier@addisretail.et",
            "full_name": "Kebede Worku",
            "role_name": "salesperson",
            "branch_ids": [str(business.branch.id)],
        },
        headers=business.headers(),
    )
    assert invite.status_code == 201
    assert invite.json()["status"] == "invited"

    from app.models.access import TenantMembership

    membership = (
        business.db.query(TenantMembership)
        .filter(TenantMembership.id == invite.json()["id"])
        .one()
    )
    accepted = client.post(
        "/api/v1/auth/accept-invitation",
        json={"token": membership.invitation_token, "password": "cashier-password-1"},
    )
    assert accepted.status_code == 200

    session = client.get(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {accepted.json()['access_token']}"},
    ).json()
    assert session["role"] == "salesperson"
    assert session["all_branches"] is False


def test_the_last_owner_cannot_be_demoted(client, business):
    response = client.patch(
        f"/api/v1/team/{business.membership.id}",
        json={"role_name": "salesperson"},
        headers=business.headers(),
    )
    assert response.status_code == 422
    assert "only owner" in response.json()["message"]


def test_openapi_document_is_served(client):
    schema = client.get("/api/v1/openapi.json")
    assert schema.status_code == 200
    assert schema.json()["info"]["title"] == "Estock API"
    assert "/api/v1/sales" in schema.json()["paths"]


# --------------------------------------------------------------------------- #
# Account security and recovery (PRD 20)
# --------------------------------------------------------------------------- #


def test_repeated_failed_sign_ins_are_rate_limited(client, business, monkeypatch):
    from app.core.deps import login_limiter

    monkeypatch.setattr(login_limiter, "limit", 3)
    body = {"email": business.owner.email, "password": "wrong-password"}
    for _ in range(3):
        assert client.post("/api/v1/auth/login", json=body).status_code == 401
    blocked = client.post("/api/v1/auth/login", json=body)
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "rate_limited"

    # The limit is per account: another account on the same address still signs in.
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "someone-else@example.com", "password": "whatever"},
        ).status_code
        == 401
    )


def test_password_reset_round_trip(client, business):
    from app.models.access import User

    requested = client.post(
        "/api/v1/auth/password-reset/request", json={"email": business.owner.email}
    )
    assert requested.status_code == 200
    # The same reply for an unknown address, so the endpoint confirms nothing.
    unknown = client.post(
        "/api/v1/auth/password-reset/request", json={"email": "nobody@nowhere.et"}
    )
    assert unknown.json()["message"] == requested.json()["message"]

    user = business.db.query(User).filter_by(id=business.owner.id).one()
    token = user.password_reset_token
    assert token and user.password_reset_expires_at is not None

    confirmed = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "password": "brand-new-password-1"},
    )
    assert confirmed.status_code == 200

    login = client.post(
        "/api/v1/auth/login",
        json={"email": business.owner.email, "password": "brand-new-password-1"},
    )
    assert login.status_code == 200

    # Single use.
    reused = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "password": "another-password-2"},
    )
    assert reused.status_code == 422


def test_an_expired_reset_token_is_refused(client, business):
    from datetime import timedelta

    from app.core.db import utcnow

    business.owner.password_reset_token = "expired-token-abcdef"
    business.owner.password_reset_expires_at = utcnow() - timedelta(minutes=1)
    business.db.flush()
    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "expired-token-abcdef", "password": "another-password-2"},
    )
    assert response.status_code == 422
    assert "no longer valid" in response.json()["message"]


def test_accepting_an_invitation_never_replaces_an_existing_password(client, business, other_business):
    """A person invited to a second business keeps the password they already have."""
    from app.core.security import verify_password

    invite = client.post(
        "/api/v1/team/invite",
        json={
            "email": other_business.owner.email,
            "full_name": "Owner of Bahir Dar",
            "role_name": "manager",
            "all_branches": True,
        },
        headers=business.headers(),
    )
    assert invite.status_code == 201

    from app.models.access import TenantMembership

    membership = (
        business.db.query(TenantMembership).filter(TenantMembership.id == invite.json()["id"]).one()
    )
    accepted = client.post(
        "/api/v1/auth/accept-invitation",
        json={"token": membership.invitation_token, "password": "attacker-chosen-pw-1"},
    )
    assert accepted.status_code == 200

    business.db.refresh(other_business.owner)
    assert verify_password("test-password-123", other_business.owner.password_hash)
    assert not verify_password("attacker-chosen-pw-1", other_business.owner.password_hash)
    # …and is now a member of both businesses.
    mine = client.get(
        "/api/v1/auth/memberships",
        headers={"Authorization": f"Bearer {accepted.json()['access_token']}"},
    ).json()
    assert {m["tenant_id"] for m in mine} == {str(business.tenant.id), str(other_business.tenant.id)}


def test_a_new_invitee_must_choose_a_password(client, business):
    from app.models.access import TenantMembership

    invite = client.post(
        "/api/v1/team/invite",
        json={"email": "newperson@example.com", "full_name": "New Person", "role_name": "salesperson"},
        headers=business.headers(),
    ).json()
    membership = business.db.query(TenantMembership).filter(TenantMembership.id == invite["id"]).one()
    response = client.post(
        "/api/v1/auth/accept-invitation", json={"token": membership.invitation_token}
    )
    assert response.status_code == 422
    assert "Choose a password" in response.json()["message"]


# --------------------------------------------------------------------------- #
# Exports, receipts and the odd response shape
# --------------------------------------------------------------------------- #


def test_stock_export_neutralises_spreadsheet_formulas(client, business):
    """A product named like a formula must not execute when the CSV is opened (PRD 20)."""
    business.add_product("=HYPERLINK(\"http://evil\")", selling_price="1", opening_stock="3")
    response = client.get("/api/v1/stock/levels/export", headers=business.headers())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    text = response.content.decode("utf-8-sig")
    assert "'=HYPERLINK" in text
    assert "\n=HYPERLINK" not in text


def test_sales_export_lists_each_day(client, business):
    product = business.add_product("Exported", selling_price="25", opening_stock="10")
    business.sell(product, quantity="2")
    response = client.get("/api/v1/reports/sales/export?period=today", headers=business.headers())
    assert response.status_code == 200
    lines = response.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0].startswith("Date,Sales,Total")
    assert len(lines) == 2
    assert "50.00" in lines[1]


def test_credit_export_needs_the_credit_report_permission(client, business):
    from app.core.permissions import RoleName

    user, _ = business.add_user(RoleName.SALESPERSON)
    assert (
        client.get("/api/v1/credit/transactions/export", headers=business.headers(user)).status_code
        == 403
    )
    assert client.get("/api/v1/credit/transactions/export", headers=business.headers()).status_code == 200


def test_a_purchase_reports_what_was_paid_and_what_is_owed(client, business):
    supplier = business.add_supplier("Grain Co")
    product = business.add_product("Teff", opening_stock=None, purchase_price=None)
    response = client.post(
        "/api/v1/purchases",
        json={
            "lines": [{"variant_id": str(product.default_variant.id), "quantity": "10", "unit_cost": "100"}],
            "supplier_id": str(supplier.id),
            "transport_cost": "50",
            "other_costs": "30",
            "amount_paid": "400",
            "due_date_preset": "15_days",
        },
        headers=business.headers(),
    )
    assert response.status_code == 201
    purchase = response.json()["purchase"]
    assert purchase["total_amount"] == "1080.00"
    assert purchase["amount_paid"] == "400.00"
    assert purchase["balance_due"] == "680.00"
    assert response.json()["credit_transaction_id"]

    listed = client.get("/api/v1/purchases", headers=business.headers()).json()
    assert listed["items"][0]["balance_due"] == "680.00"

    # The receipt's transport and other costs are shown per unit on the product.
    detail = client.get(f"/api/v1/products/{product.id}", headers=business.headers()).json()
    variant = detail["variants"][0]
    assert variant["purchase_price"] == "100.00"
    assert variant["transport_cost"] == "5.00"
    assert variant["other_costs"] == "3.00"
    assert variant["average_cost"] == "108.00"


def test_barcode_lookup_names_the_product(client, business):
    """The sales screen shows the product, not 'Scanned item'."""
    business.add_product("Sunflower oil 5L", barcode="6001234500001", selling_price="950", opening_stock="4")
    found = client.get(
        "/api/v1/products/lookup/barcode/6001234500001", headers=business.headers()
    ).json()
    assert found["product_name"] == "Sunflower oil 5L"
    assert found["display_name"] == "Sunflower oil 5L"
    assert found["quantity_on_hand"] == "4.000"


def test_editing_a_simple_product_keeps_its_variant_codes_in_step(client, business):
    product = business.add_product("Codes", sku="OLD-1", barcode="111", opening_stock=None)
    business.add_product("Other", sku="TAKEN", opening_stock=None)

    clash = client.patch(
        f"/api/v1/products/{product.id}", json={"sku": "TAKEN"}, headers=business.headers()
    )
    assert clash.status_code == 409

    updated = client.patch(
        f"/api/v1/products/{product.id}",
        json={"sku": "NEW-1", "barcode": "222"},
        headers=business.headers(),
    ).json()
    assert updated["sku"] == "NEW-1"
    assert updated["variants"][0]["sku"] == "NEW-1"
    assert updated["variants"][0]["barcode"] == "222"
    assert client.get("/api/v1/products/lookup/barcode/222", headers=business.headers()).status_code == 200
    assert client.get("/api/v1/products/lookup/barcode/111", headers=business.headers()).status_code == 404


def test_converting_a_proforma_with_a_delivery_charge_says_so(client, business):
    product = business.add_product("Quoted", selling_price="100", opening_stock="10")
    quotation = client.post(
        "/api/v1/shop/quotations",
        json={
            "customer_name": "Delivery Customer",
            "customer_phone": "0911000000",
            "delivery_charge": "250",
            "lines": [{"variant_id": str(product.default_variant.id), "quantity": "2"}],
        },
        headers=business.headers(),
    ).json()
    converted = client.post(
        f"/api/v1/shop/quotations/{quotation['id']}/convert",
        json={"payments": [{"method": "cash", "amount": "200"}]},
        headers=business.headers(),
    )
    assert converted.status_code == 200
    assert converted.json()["sale"]["total_amount"] == "200.00"
    assert any("delivery charge" in w for w in converted.json()["warnings"])


def test_business_settings_accept_a_default_tax_rate(client, business):
    response = client.patch(
        "/api/v1/business",
        json={"default_tax_rate": "0.15", "phone": "0911 22 33 44"},
        headers=business.headers(),
    )
    assert response.status_code == 200
    assert response.json()["default_tax_rate"] == "0.15"
    assert response.json()["phone"] == "+251911223344"

    bad_zone = client.patch(
        "/api/v1/business", json={"timezone": "Mars/Olympus"}, headers=business.headers()
    )
    assert bad_zone.status_code == 422


def test_public_enquiries_are_rate_limited(client, business, monkeypatch):
    from app.core.deps import public_limiter
    from app.models.commerce import OnlineStore

    store = business.db.query(OnlineStore).filter_by(tenant_id=business.tenant.id).one()
    store.is_published = True
    business.db.flush()
    monkeypatch.setattr(public_limiter, "limit", 2)

    body = {"contact_name": "Spammer", "contact_phone": "0911111111"}
    for _ in range(2):
        assert client.post(f"/api/v1/public/shops/{store.slug}/enquiries", json=body).status_code == 201
    assert client.post(f"/api/v1/public/shops/{store.slug}/enquiries", json=body).status_code == 429
