"""Role and branch access boundaries (PRD 5.1, 21)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.core.errors import PermissionDenied
from app.core.permissions import Permission, RoleName, permissions_for_role
from app.core.tenancy import COST_BEARING_FIELDS
from app.services.catalogue import ProductInput, create_product
from app.services.inventory import adjust_stock
from app.services.reports import DateRange, branch_comparison, sales_summary
from app.services.sales import SaleInput, SaleLineInput, create_sale, void_sale


def test_owner_holds_every_permission():
    assert permissions_for_role(RoleName.OWNER) == frozenset(Permission)


def test_salesperson_cannot_see_cost_or_business_reports():
    """Sales and customer workflows only, unless granted explicitly (PRD 5.1)."""
    permissions = permissions_for_role(RoleName.SALESPERSON)
    assert Permission.SALE_CREATE in permissions
    assert Permission.CUSTOMER_MANAGE in permissions
    assert Permission.COST_VIEW not in permissions
    assert Permission.REPORT_PROFIT not in permissions
    assert Permission.REPORT_BRANCH_COMPARE not in permissions
    assert Permission.PRODUCT_MANAGE not in permissions


def test_stock_user_cannot_see_cost_or_sell():
    permissions = permissions_for_role(RoleName.STOCK_USER)
    assert Permission.STOCK_RECEIVE in permissions
    assert Permission.STOCK_COUNT in permissions
    assert Permission.COST_VIEW not in permissions
    assert Permission.SALE_CREATE not in permissions
    assert Permission.CREDIT_VIEW not in permissions


def test_manager_can_operate_but_not_manage_the_business():
    permissions = permissions_for_role(RoleName.MANAGER)
    assert Permission.SALE_VOID in permissions
    assert Permission.REPORT_PROFIT in permissions
    assert Permission.BUSINESS_MANAGE not in permissions
    assert Permission.USER_MANAGE not in permissions


def test_a_salesperson_cannot_create_products(business):
    _, ctx = business.add_user(RoleName.SALESPERSON)
    with pytest.raises(PermissionDenied):
        create_product(business.db, ctx, ProductInput(name="Sneaky product"))


def test_a_salesperson_cannot_void_a_sale(business):
    product = business.add_product("Thing", opening_stock="10")
    sale = business.sell(product).sale
    _, ctx = business.add_user(RoleName.SALESPERSON)
    with pytest.raises(PermissionDenied):
        void_sale(business.db, ctx, sale.id, reason="Not allowed")


def test_a_stock_user_cannot_record_a_sale(business):
    product = business.add_product("Thing", selling_price="10", opening_stock="10")
    _, ctx = business.add_user(RoleName.STOCK_USER)
    with pytest.raises(PermissionDenied):
        create_sale(
            business.db,
            ctx,
            SaleInput(
                lines=[
                    SaleLineInput(
                        variant_id=product.default_variant.id, quantity=Decimal("1")
                    )
                ]
            ),
        )


def test_a_salesperson_cannot_adjust_stock(business):
    product = business.add_product("Thing", opening_stock="10")
    _, ctx = business.add_user(RoleName.SALESPERSON)
    with pytest.raises(PermissionDenied):
        adjust_stock(
            business.db,
            ctx,
            variant_id=product.default_variant.id,
            location_id=business.location.id,
            quantity=Decimal("-1"),
            reason="damage",
            note="Broken",
        )


def test_a_stock_user_may_receive_and_count(business):
    from app.services.inventory import record_count_line, start_count

    product = business.add_product("Thing", opening_stock="10")
    _, ctx = business.add_user(RoleName.STOCK_USER)
    count = start_count(business.db, ctx, location_id=business.location.id)
    line = record_count_line(
        business.db,
        ctx,
        count.id,
        variant_id=product.default_variant.id,
        counted_quantity=Decimal("9"),
    )
    assert line.variance == Decimal("-1.000")


def test_profit_figures_are_withheld_without_cost_view(business):
    product = business.add_product(
        "Thing", selling_price="100", purchase_price="60", opening_stock="10"
    )
    business.sell(product, quantity="2")

    _, salesperson = business.add_user(RoleName.SALESPERSON)
    today = date.today()
    period = DateRange(today, today)

    for_owner = sales_summary(business.db, business.ctx, period)
    for_salesperson = sales_summary(business.db, salesperson, period)

    assert for_owner.gross_profit == Decimal("80.00")
    assert for_salesperson.gross_profit is None
    assert for_salesperson.cost_of_goods is None
    assert for_salesperson.net_sales == for_owner.net_sales


def test_branch_access_is_enforced(business):
    """A user assigned to one branch cannot act in another (PRD 4)."""
    second_branch, second_location = business.add_branch("Piassa")
    product = business.add_product("Thing", selling_price="10", opening_stock="10")

    _, ctx = business.add_user(RoleName.MANAGER, branches=[business.branch])
    assert ctx.can_access_branch(business.branch.id) is True
    assert ctx.can_access_branch(second_branch.id) is False

    with pytest.raises(PermissionDenied, match="access to this branch"):
        create_sale(
            business.db,
            ctx,
            SaleInput(
                lines=[
                    SaleLineInput(
                        variant_id=product.default_variant.id, quantity=Decimal("1")
                    )
                ],
                branch_id=second_branch.id,
            ),
        )


def test_all_branches_membership_sees_new_branches(business):
    _, ctx = business.add_user(RoleName.MANAGER, all_branches=True)
    new_branch, _ = business.add_branch("Opened later")
    assert ctx.can_access_branch(new_branch.id) is True
    assert new_branch.id in ctx.visible_branch_ids(business.db)


def test_branch_comparison_shows_only_permitted_branches(business):
    second_branch, _ = business.add_branch("Piassa")
    _, ctx = business.add_user(RoleName.MANAGER, branches=[business.branch])

    rows = branch_comparison(business.db, ctx, DateRange(date.today(), date.today()))
    assert {row["branch_name"] for row in rows} == {business.branch.name}


def test_an_explicit_grant_adds_one_permission(business):
    """Per-user grants sit on top of the role bundle."""
    from app.core.tenancy import build_auth_context
    from app.models.access import UserPermissionGrant

    user, ctx = business.add_user(RoleName.SALESPERSON)
    assert Permission.COST_VIEW not in ctx.permissions

    business.db.add(
        UserPermissionGrant(
            membership_id=ctx.membership.id, permission=Permission.COST_VIEW, granted=True
        )
    )
    business.db.flush()
    business.db.refresh(ctx.membership)

    updated = build_auth_context(user, business.tenant, ctx.membership)
    assert Permission.COST_VIEW in updated.permissions


def test_an_explicit_revocation_removes_one_permission(business):
    from app.core.tenancy import build_auth_context
    from app.models.access import UserPermissionGrant

    user, ctx = business.add_user(RoleName.MANAGER)
    assert Permission.SALE_VOID in ctx.permissions

    business.db.add(
        UserPermissionGrant(
            membership_id=ctx.membership.id, permission=Permission.SALE_VOID, granted=False
        )
    )
    business.db.flush()
    business.db.refresh(ctx.membership)

    updated = build_auth_context(user, business.tenant, ctx.membership)
    assert Permission.SALE_VOID not in updated.permissions


def test_require_reports_which_permissions_are_missing(business):
    _, ctx = business.add_user(RoleName.SALESPERSON)
    with pytest.raises(PermissionDenied) as exc:
        ctx.require(Permission.COST_VIEW, Permission.SALE_CREATE)
    assert exc.value.details["missing_permissions"] == ["cost:view"]


# --------------------------------------------------------------------------- #
# Over HTTP
# --------------------------------------------------------------------------- #


def test_api_hides_cost_fields_from_a_salesperson(client, business):
    business.add_product(
        "Thing", selling_price="100", purchase_price="60", opening_stock="5"
    )
    user, _ = business.add_user(RoleName.SALESPERSON)

    owner_view = client.get("/api/v1/products", headers=business.headers()).json()
    sales_view = client.get("/api/v1/products", headers=business.headers(user)).json()

    assert owner_view["items"][0]["variants"][0]["landed_cost"] == "60.00"
    assert sales_view["items"][0]["variants"][0]["landed_cost"] is None
    assert sales_view["items"][0]["variants"][0]["selling_price"] == "100.00"


#: Routes a cost-blind user can reach that return priced records.  Each is
#: swept for every name in ``COST_BEARING_FIELDS``, so a new endpoint that
#: forgets to withhold cost fails here rather than in production.
COST_BEARING_ROUTES = (
    "/api/v1/products",
    "/api/v1/stock/levels",
    "/api/v1/sales",
    "/api/v1/dashboard",
)


def _cost_values(payload, found=None):
    """Every value in a response that sits under a cost-bearing field name."""
    found = [] if found is None else found
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in COST_BEARING_FIELDS:
                found.append((key, value))
            else:
                _cost_values(value, found)
    elif isinstance(payload, list):
        for item in payload:
            _cost_values(item, found)
    return found


def test_no_route_leaks_a_cost_field_to_a_user_without_cost_view(client, business):
    """The invariant, swept rather than trusted to each endpoint (PRD 8.2).

    The owner's view of the same routes must carry real cost figures, or this
    test would pass by looking at nothing.
    """
    product = business.add_product(
        "Swept", selling_price="100", purchase_price="60", opening_stock="5"
    )
    business.sell(product, quantity="2")
    user, _ = business.add_user(RoleName.SALESPERSON)

    seen_for_owner = 0
    for route in COST_BEARING_ROUTES:
        as_owner = client.get(route, headers=business.headers())
        assert as_owner.status_code == 200, (route, as_owner.json())
        owner_costs = _cost_values(as_owner.json())
        seen_for_owner += sum(1 for _, value in owner_costs if value is not None)

        as_salesperson = client.get(route, headers=business.headers(user))
        assert as_salesperson.status_code == 200, (route, as_salesperson.json())
        leaked = [
            (name, value)
            for name, value in _cost_values(as_salesperson.json())
            if value is not None
        ]
        assert leaked == [], f"{route} leaked {leaked}"

    assert seen_for_owner > 0, "the sweep found no cost fields at all; it proves nothing"


def test_purchase_costs_are_not_reachable_by_granting_purchase_view(client, business):
    """A cost-blind user granted purchase:view must still not see unit costs.

    Every default role that holds purchase:view also holds cost:view, so the
    purchasing routes could rely on that coincidence instead of checking cost
    visibility themselves.  One per-user grant breaks the coincidence, and a
    purchase carries the unit and landed cost of everything received.
    """
    product = business.add_product("Thing", purchase_price="60", opening_stock="0")
    supplier = business.add_supplier()
    client.post(
        "/api/v1/purchases",
        json={
            "supplier_id": str(supplier.id),
            "lines": [
                {
                    "variant_id": str(product.default_variant.id),
                    "quantity": "10",
                    "unit_cost": "60.00",
                }
            ],
        },
        headers=business.headers(),
    ).raise_for_status()

    user, _ = business.add_user(RoleName.SALESPERSON)
    membership = _membership_of(business, user)
    business.grant(membership, Permission.PURCHASE_VIEW)

    listed = client.get("/api/v1/purchases", headers=business.headers(user))
    assert listed.status_code == 403, listed.json()
    assert "cost:view" in listed.json()["details"]["missing_permissions"]


def test_cost_view_alone_does_not_open_purchasing(client, business):
    """The two permissions are both required, not interchangeable."""
    user, _ = business.add_user(RoleName.SALESPERSON)
    membership = _membership_of(business, user)
    business.grant(membership, Permission.COST_VIEW)

    response = client.get("/api/v1/purchases", headers=business.headers(user))
    assert response.status_code == 403
    assert "purchase:view" in response.json()["details"]["missing_permissions"]


def _membership_of(business, user):
    from app.models.access import TenantMembership

    return (
        business.db.query(TenantMembership)
        .filter(
            TenantMembership.tenant_id == business.tenant.id,
            TenantMembership.user_id == user.id,
        )
        .one()
    )


def test_api_refuses_a_forbidden_action_with_403(client, business):
    user, _ = business.add_user(RoleName.SALESPERSON)
    response = client.post(
        "/api/v1/products", json={"name": "Nope"}, headers=business.headers(user)
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_api_session_reports_the_callers_permissions(client, business):
    user, _ = business.add_user(RoleName.STOCK_USER)
    payload = client.get("/api/v1/auth/session", headers=business.headers(user)).json()
    assert payload["role"] == "stock_user"
    assert "stock:receive" in payload["permissions"]
    assert "cost:view" not in payload["permissions"]


# --------------------------------------------------------------------------- #
# Platform support access (PRD 5.2)
# --------------------------------------------------------------------------- #


def _support_headers(business) -> dict:
    from app.core.security import create_access_token

    token = create_access_token(
        subject=business.owner.id,
        tenant_id=business.tenant.id,
        expires_minutes=30,
        extra_claims={"support": True, "granted_by": "test"},
    )
    return {"Authorization": f"Bearer {token}"}


def test_support_access_can_look_but_not_touch(client, business):
    """A support token is read-only, whatever role it borrows."""
    business.add_product("Visible", selling_price="10", opening_stock="5")
    headers = _support_headers(business)

    session = client.get("/api/v1/auth/session", headers=headers).json()
    assert session["is_support"] is True
    assert "product:view" in session["permissions"]
    assert "sale:create" not in session["permissions"]
    assert "product:manage" not in session["permissions"]

    assert client.get("/api/v1/products", headers=headers).status_code == 200
    assert client.get("/api/v1/dashboard", headers=headers).status_code == 200

    refused = client.post("/api/v1/products", json={"name": "Nope"}, headers=headers)
    assert refused.status_code == 403
    sale = client.post(
        "/api/v1/sales",
        json={"lines": [{"variant_id": str(uuid.uuid4()), "quantity": "1"}]},
        headers=headers,
    )
    assert sale.status_code == 403
    assert "read-only" in sale.json()["message"]


def test_support_access_is_pinned_to_one_business(client, business, other_business):
    """The tenant header cannot widen a support grant to another business."""
    business.add_product("Ours")
    other_business.add_product("Theirs")
    headers = {**_support_headers(business), "X-Tenant-Id": str(other_business.tenant.id)}
    names = {item["name"] for item in client.get("/api/v1/products", headers=headers).json()["items"]}
    assert names == {"Ours"}


def test_platform_admin_support_grant_is_audited_and_read_only(client, business, db):
    from app.core.security import hash_password
    from app.models.platform import AuditEvent, PlatformAdmin

    db.add(
        PlatformAdmin(
            email="support@estock.et", full_name="Support", password_hash=hash_password("admin-pw-123")
        )
    )
    db.flush()
    login = client.post(
        "/api/v1/platform/login", json={"email": "support@estock.et", "password": "admin-pw-123"}
    )
    assert login.status_code == 200
    admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    grant = client.post(
        "/api/v1/platform/support-access",
        json={"tenant_id": str(business.tenant.id), "reason": "Customer reported wrong stock figures"},
        headers=admin_headers,
    )
    assert grant.status_code == 200
    assert "read-only" in grant.json()["notice"]
    support_headers = {"Authorization": f"Bearer {grant.json()['access_token']}"}

    session = client.get("/api/v1/auth/session", headers=support_headers).json()
    assert session["is_support"] is True
    assert session["role"] == "owner"
    assert client.post("/api/v1/branches", json={"name": "X"}, headers=support_headers).status_code == 403

    audit = db.query(AuditEvent).filter(AuditEvent.action == "platform.support_access").one()
    assert audit.tenant_id == business.tenant.id
    assert "wrong stock" in (audit.payload_json or "")


def test_listing_a_product_publicly_needs_shop_manage_whichever_route(client, business):
    """The publication flags have a dedicated endpoint asking for shop:manage.

    They are also writable through the generic product update, which asks for
    product:manage.  If that route did not ask for shop:manage as well, the
    dedicated one's gate would be decoration: a user could put a product on
    the storefront, or on the platform-wide marketplace, by PATCHing the
    field instead of posting to the toggle.
    """
    product = business.add_product("Thing")
    user, _ = business.add_user(RoleName.SALESPERSON)
    membership = _membership_of(business, user)
    business.grant(membership, Permission.PRODUCT_MANAGE)

    for field in ("is_published", "on_marketplace"):
        patched = client.patch(
            f"/api/v1/products/{product.id}",
            json={field: True},
            headers=business.headers(user),
        )
        assert patched.status_code == 403, f"{field}: {patched.json()}"
        assert "shop:manage" in patched.json()["details"]["missing_permissions"]

    # The same caller may still edit a product's ordinary fields.
    renamed = client.patch(
        f"/api/v1/products/{product.id}",
        json={"name": "Thing, renamed"},
        headers=business.headers(user),
    )
    assert renamed.status_code == 200, renamed.json()
    assert renamed.json()["name"] == "Thing, renamed"
