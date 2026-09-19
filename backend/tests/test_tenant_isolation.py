"""Proof that one business cannot read or change another's data (PRD 20, 21).

Isolation is enforced on the server.  A row belonging to another business is
reported as *not found*, so the API never even confirms that an id exists
elsewhere.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.errors import NotFoundError, PermissionDenied
from app.core.tenancy import get_tenant_object, tenant_query
from app.models.catalogue import Product
from app.models.inventory import StockBalance
from app.models.sales import PaymentMethod
from app.services.catalogue import update_product
from app.services.credit import record_payment
from app.services.inventory import adjust_stock
from app.services.sales import SaleInput, SaleLineInput, create_sale, void_sale


def test_product_lists_never_cross_the_tenant_boundary(business, other_business):
    business.add_product("Ours A")
    business.add_product("Ours B")
    other_business.add_product("Theirs")

    ours = business.db.execute(tenant_query(Product, business.tenant.id)).scalars().all()
    theirs = (
        business.db.execute(tenant_query(Product, other_business.tenant.id)).scalars().all()
    )
    assert {p.name for p in ours} == {"Ours A", "Ours B"}
    assert {p.name for p in theirs} == {"Theirs"}


def test_fetching_another_tenants_row_reports_not_found(business, other_business):
    theirs = other_business.add_product("Theirs")
    with pytest.raises(NotFoundError):
        get_tenant_object(business.db, Product, theirs.id, business.tenant.id, label="Product")


def test_editing_another_tenants_product_is_refused(business, other_business):
    theirs = other_business.add_product("Theirs")
    with pytest.raises(NotFoundError):
        update_product(business.db, business.ctx, theirs.id, {"name": "Stolen"})
    assert theirs.name == "Theirs"


def test_selling_another_tenants_product_is_refused(business, other_business):
    theirs = other_business.add_product("Theirs", opening_stock="100")
    with pytest.raises(NotFoundError):
        create_sale(
            business.db,
            business.ctx,
            SaleInput(
                lines=[
                    SaleLineInput(
                        variant_id=theirs.default_variant.id, quantity=Decimal("1")
                    )
                ]
            ),
        )


def test_adjusting_another_tenants_stock_is_refused(business, other_business):
    theirs = other_business.add_product("Theirs", opening_stock="100")
    with pytest.raises(NotFoundError):
        adjust_stock(
            business.db,
            business.ctx,
            variant_id=theirs.default_variant.id,
            location_id=other_business.location.id,
            quantity=Decimal("-10"),
            reason="adjustment",
            note="Not mine to touch",
        )


def test_voiding_another_tenants_sale_is_refused(business, other_business):
    product = other_business.add_product("Theirs", opening_stock="10")
    their_sale = other_business.sell(product).sale
    with pytest.raises(NotFoundError):
        void_sale(business.db, business.ctx, their_sale.id, reason="Not mine")


def test_paying_another_tenants_receivable_is_refused(business, other_business):
    customer = other_business.add_customer("Their customer")
    product = other_business.add_product("Theirs", selling_price="500", opening_stock="10")
    result = other_business.sell(product, paid="0", customer_id=customer.id)

    with pytest.raises(NotFoundError):
        record_payment(
            business.db,
            business.ctx,
            result.credit_transaction.id,
            amount=Decimal("100"),
            method=PaymentMethod.CASH,
        )


def test_stock_balances_are_separate_per_tenant(business, other_business):
    business.add_product("Same name", opening_stock="10")
    other_business.add_product("Same name", opening_stock="999")

    ours = (
        business.db.query(StockBalance)
        .filter(StockBalance.tenant_id == business.tenant.id)
        .all()
    )
    assert len(ours) == 1
    assert ours[0].quantity == Decimal("10.000")


def test_two_businesses_may_reuse_the_same_sku(business, other_business):
    """Codes are unique inside a business, not across the platform."""
    business.add_product("Ours", sku="SKU-1")
    other_business.add_product("Theirs", sku="SKU-1")
    business.db.flush()

    ours = business.db.execute(
        tenant_query(Product, business.tenant.id).where(Product.sku == "SKU-1")
    ).scalars().all()
    assert len(ours) == 1
    assert ours[0].name == "Ours"


def test_document_numbers_restart_per_business(business, other_business):
    ours = business.add_product("Ours", opening_stock="10")
    theirs = other_business.add_product("Theirs", opening_stock="10")

    our_sale = business.sell(ours).sale
    their_sale = other_business.sell(theirs).sale
    assert our_sale.number == their_sale.number


def test_credit_summaries_do_not_leak_across_tenants(business, other_business):
    from app.models.credit import CreditKind
    from app.services.reports import credit_summary

    their_customer = other_business.add_customer("Theirs")
    their_product = other_business.add_product("Theirs", selling_price="5000", opening_stock="5")
    other_business.sell(their_product, paid="0", customer_id=their_customer.id)

    ours = credit_summary(business.db, business.ctx, CreditKind.RECEIVABLE)
    assert ours.total_outstanding == Decimal("0.00")
    assert ours.transaction_count == 0


def test_dashboard_shows_only_the_callers_business(business, other_business):
    from app.services.reports import home_dashboard

    their_product = other_business.add_product("Theirs", selling_price="900", opening_stock="10")
    other_business.sell(their_product, quantity="3")

    payload = home_dashboard(business.db, business.ctx)
    assert payload["today"]["sale_count"] == 0
    assert payload["today"]["net_sales"] == "0"


def test_a_user_of_one_business_cannot_load_another(business, other_business):
    from app.services.onboarding import load_auth_context

    with pytest.raises(PermissionDenied):
        load_auth_context(business.db, business.owner, other_business.tenant.id)


# --------------------------------------------------------------------------- #
# The same guarantees over HTTP
# --------------------------------------------------------------------------- #


def test_api_product_list_is_scoped_to_the_token(client, business, other_business):
    business.add_product("Ours")
    other_business.add_product("Theirs")

    response = client.get("/api/v1/products", headers=business.headers())
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["items"]}
    assert names == {"Ours"}


def test_api_returns_404_for_another_tenants_product(client, business, other_business):
    theirs = other_business.add_product("Theirs")
    response = client.get(f"/api/v1/products/{theirs.id}", headers=business.headers())
    assert response.status_code == 404


def test_api_rejects_a_forged_tenant_header(client, business, other_business):
    """``X-Tenant-Id`` may only select a business the user belongs to."""
    other_business.add_product("Theirs")
    response = client.get(
        "/api/v1/products",
        headers={**business.headers(), "X-Tenant-Id": str(other_business.tenant.id)},
    )
    assert response.status_code == 403


def test_api_requires_authentication(client, business):
    business.add_product("Ours")
    assert client.get("/api/v1/products").status_code == 401
    assert (
        client.get("/api/v1/products", headers={"Authorization": "Bearer nonsense"}).status_code
        == 401
    )
