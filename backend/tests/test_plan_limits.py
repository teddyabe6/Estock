"""Plan ceilings on branches, staff and products (PRD 17).

`SubscriptionPlan` has carried `max_branches`, `max_users` and `max_products`
since the first migration, and a platform admin could edit them, but nothing
checked them: a business on a one-branch plan could open thirty.

The rules these tests pin:

* `None` means unlimited, and a business on no plan at all has no ceilings.
  A limit applies because a plan says so, never by default.
* A business pushed over a ceiling by a downgrade keeps everything it has.
  Only the next addition is refused — the same promise trial expiry makes.
* An invitation holds a seat, or a three-seat business could invite thirty
  people and have them all walk in.
* Deactivating frees a slot, which is how a business makes room without
  deleting history.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.core.errors import PlanLimitReached
from app.core.permissions import RoleName
from app.models.access import MembershipStatus, TenantMembership
from app.models.catalogue import Product
from app.services.catalogue import ProductInput, create_product
from app.services.imports import commit_import, start_import, validate_import
from app.services.onboarding import invite_user
from app.services.subscription import check_limit, limits

# --------------------------------------------------------------------------- #
# No plan, or no ceiling, means no limit
# --------------------------------------------------------------------------- #


def test_a_business_on_no_plan_has_no_ceilings(business):
    """A trial that has not chosen a plan is not quietly capped."""
    for _ in range(5):
        business.add_product(f"Thing {_}", opening_stock=None)
    check_limit(business.db, business.tenant.id, "products")
    check_limit(business.db, business.tenant.id, "branches")
    check_limit(business.db, business.tenant.id, "users")


def test_a_null_ceiling_means_unlimited(business):
    business.put_on_plan(max_products=None, max_branches=2)
    for i in range(4):
        business.add_product(f"Thing {i}", opening_stock=None)
    check_limit(business.db, business.tenant.id, "products", adding=1000)


def test_limits_report_usage_against_the_plan(business):
    business.put_on_plan(max_branches=3, max_users=5, max_products=None)
    business.add_product("One", opening_stock=None)

    reported = {limit.name: limit for limit in limits(business.db, business.tenant.id)}

    assert reported["branches"].allowed == 3
    assert reported["branches"].used == 1  # the branch registration created
    assert reported["branches"].remaining == 2
    assert reported["users"].allowed == 5
    assert reported["users"].used == 1  # the owner
    assert reported["products"].allowed is None
    assert reported["products"].unlimited is True
    assert reported["products"].remaining is None


# --------------------------------------------------------------------------- #
# Branches
# --------------------------------------------------------------------------- #


def test_a_branch_past_the_plan_is_refused(client, business):
    business.put_on_plan(max_branches=1)  # registration already made one

    response = client.post(
        "/api/v1/branches", json={"name": "Merkato"}, headers=business.headers()
    )

    assert response.status_code == 402
    body = response.json()
    assert body["code"] == "plan_limit_reached"
    assert body["details"]["limit"] == "branches"
    assert body["details"]["used"] == 1
    assert body["details"]["allowed"] == 1
    assert "Upgrade the plan" in body["message"]


def test_a_branch_within_the_plan_is_allowed(client, business):
    business.put_on_plan(max_branches=2)
    response = client.post(
        "/api/v1/branches", json={"name": "Merkato"}, headers=business.headers()
    )
    assert response.status_code == 201


def test_deactivating_a_branch_frees_its_slot(client, business):
    business.put_on_plan(max_branches=2)
    extra, _ = business.add_branch("Bole")
    with pytest.raises(PlanLimitReached):
        check_limit(business.db, business.tenant.id, "branches")

    extra.is_active = False
    business.db.flush()
    check_limit(business.db, business.tenant.id, "branches")


# --------------------------------------------------------------------------- #
# Staff
# --------------------------------------------------------------------------- #


def test_an_invitation_past_the_plan_is_refused(business):
    business.put_on_plan(max_users=1)  # the owner fills it

    with pytest.raises(PlanLimitReached) as refused:
        invite_user(
            business.db,
            business.ctx,
            email="new@example.com",
            full_name="New Person",
            role_name=RoleName.SALESPERSON,
        )

    assert refused.value.details["limit"] == "users"
    assert refused.value.status_code == 402


def test_an_outstanding_invitation_holds_a_seat(business):
    """Otherwise a three-seat business invites thirty people and all get in."""
    business.put_on_plan(max_users=2)
    invite_user(
        business.db,
        business.ctx,
        email="first@example.com",
        full_name="First",
        role_name=RoleName.SALESPERSON,
    )
    business.db.flush()

    # The invitation has not been accepted, so this person is not active yet.
    with pytest.raises(PlanLimitReached):
        invite_user(
            business.db,
            business.ctx,
            email="second@example.com",
            full_name="Second",
            role_name=RoleName.SALESPERSON,
        )


def test_a_disabled_member_does_not_hold_a_seat(business):
    business.put_on_plan(max_users=2)
    _user, _ctx = business.add_user(RoleName.SALESPERSON)
    with pytest.raises(PlanLimitReached):
        check_limit(business.db, business.tenant.id, "users")

    membership = (
        business.db.query(TenantMembership)
        .filter(
            TenantMembership.tenant_id == business.tenant.id,
            TenantMembership.id != business.membership.id,
        )
        .one()
    )
    membership.status = MembershipStatus.DISABLED
    business.db.flush()
    check_limit(business.db, business.tenant.id, "users")


# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #


def test_a_product_past_the_plan_is_refused(business):
    business.put_on_plan(max_products=2)
    business.add_product("One", opening_stock=None)
    business.add_product("Two", opening_stock=None)

    with pytest.raises(PlanLimitReached) as refused:
        create_product(
            business.db, business.ctx, ProductInput(name="Three", selling_price=Decimal("1"))
        )

    assert refused.value.details == {
        "limit": "products",
        "used": 2,
        "allowed": 2,
        "adding": 1,
        "plan": refused.value.details["plan"],
    }


def test_deactivating_a_product_frees_its_slot(business):
    business.put_on_plan(max_products=1)
    product = business.add_product("One", opening_stock=None)
    with pytest.raises(PlanLimitReached):
        check_limit(business.db, business.tenant.id, "products")

    product.is_active = False
    business.db.flush()
    check_limit(business.db, business.tenant.id, "products")


# --------------------------------------------------------------------------- #
# A downgrade never takes data away
# --------------------------------------------------------------------------- #


def test_a_downgrade_leaves_existing_data_alone(client, business):
    """Over the ceiling is not the same as losing anything (PRD 17)."""
    for i in range(5):
        business.add_product(f"Thing {i}", opening_stock=None)
    sellable = business.add_product("Sellable", opening_stock="10")

    business.put_on_plan(max_products=2)  # a downgrade: six products, room for two

    listed = client.get("/api/v1/products", headers=business.headers())
    assert listed.status_code == 200
    assert listed.json()["total"] == 6

    # Trading on what is already there still works.
    assert business.sell(sellable, quantity="1").sale.number

    # Only the next addition is refused.
    with pytest.raises(PlanLimitReached):
        check_limit(business.db, business.tenant.id, "products")


# --------------------------------------------------------------------------- #
# Spreadsheet import
# --------------------------------------------------------------------------- #


def _spreadsheet(rows: list[list]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _import_job(business, tmp_path, monkeypatch, product_names: list[str]):
    monkeypatch.setattr("app.services.storage.settings.storage_local_root", str(tmp_path))
    content = _spreadsheet(
        [["Product Name", "Selling Price"], *[[name, 100] for name in product_names]]
    )
    job, _headers, mapping = start_import(
        business.db,
        business.ctx,
        filename="stock.xlsx",
        content_type=XLSX,
        content=content,
    )
    return job, mapping


def test_an_import_past_the_plan_is_refused_whole(business, tmp_path, monkeypatch):
    """Not part-way through.

    ``create_product`` checks one product at a time, so without a batch check
    a long file would write rows until the ceiling and then raise, reporting a
    single product rather than the import.  Nothing may be written at all.
    """
    business.put_on_plan(max_products=2)
    job, mapping = _import_job(business, tmp_path, monkeypatch, ["A", "B", "C", "D", "E"])
    validate_import(business.db, business.ctx, job.id, mapping)

    with pytest.raises(PlanLimitReached) as refused:
        commit_import(business.db, business.ctx, job.id)

    assert refused.value.details["adding"] == 5
    assert refused.value.details["allowed"] == 2
    assert "5 more products" in refused.value.message

    # The check runs before the loop, so nothing was written to roll back —
    # which is the property that matters.  In a request, get_db would roll the
    # transaction back anyway.
    assert (
        business.db.query(Product).filter_by(tenant_id=business.tenant.id).count() == 0
    ), "a refused import must leave nothing behind"


def test_the_preview_warns_before_the_import_is_applied(business, tmp_path, monkeypatch):
    """The wizard can say so at the preview step rather than at apply."""
    business.put_on_plan(max_products=2)
    job, mapping = _import_job(business, tmp_path, monkeypatch, ["A", "B", "C"])

    preview = validate_import(business.db, business.ctx, job.id, mapping)

    assert preview.valid_rows == 3
    assert preview.plan_limit is not None
    assert preview.plan_limit["limit"] == "products"
    assert preview.plan_limit["adding"] == 3
    assert preview.plan_limit["allowed"] == 2


def test_an_import_within_the_plan_has_no_warning(business, tmp_path, monkeypatch):
    business.put_on_plan(max_products=5)
    job, mapping = _import_job(business, tmp_path, monkeypatch, ["A", "B"])

    preview = validate_import(business.db, business.ctx, job.id, mapping)
    assert preview.plan_limit is None

    commit_import(business.db, business.ctx, job.id)
    business.db.flush()
    assert business.db.query(Product).filter_by(tenant_id=business.tenant.id).count() == 2
