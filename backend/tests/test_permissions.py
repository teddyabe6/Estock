"""Role and branch access boundaries (PRD 5.1, 21)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.errors import PermissionDenied
from app.core.permissions import Permission, RoleName, permissions_for_role
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
