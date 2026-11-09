"""Finding one thing in a long stock list (PRD 9, 15).

A shop with a few hundred products across a few branches has a stock list of
a few thousand rows.  Scrolling it is not an answer, so the list has to be
narrowed, ordered and read a page at a time — and the ordering has to be the
grouping too, because a group that only holds together inside one page is
not a group.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.models.inventory import MovementReason
from app.services.inventory import adjust_stock, stock_overview


def names(body) -> list[str]:
    return [row["name"] for row in body["items"]]


# --------------------------------------------------------------------------- #
# Narrowing the list
# --------------------------------------------------------------------------- #


def test_levels_can_be_narrowed_to_one_category(client, business):
    business.add_product("Teff flour", category_name="Grains", opening_stock="40")
    business.add_product("Sugar", category_name="Grains", opening_stock="10")
    business.add_product("Cement", category_name="Building", opening_stock="60")
    grains = next(
        row["category_id"]
        for row in client.get("/api/v1/stock/levels", headers=business.headers()).json()[
            "items"
        ]
        if row["category_name"] == "Grains"
    )

    body = client.get(
        f"/api/v1/stock/levels?category_id={grains}", headers=business.headers()
    ).json()

    assert sorted(names(body)) == ["Sugar", "Teff flour"]
    # The count follows the filter, or the pager lies about what is left.
    assert body["total"] == 2


def test_levels_carry_the_category_so_a_heading_can_be_drawn(client, business):
    business.add_product("Teff flour", category_name="Grains", opening_stock="40")

    row = client.get("/api/v1/stock/levels", headers=business.headers()).json()["items"][0]

    assert row["category_name"] == "Grains"
    assert row["category_id"] is not None


def test_levels_can_be_narrowed_to_what_needs_attention(client, business):
    business.add_product("Plenty", opening_stock="500", min_stock="1", reorder_level="2")
    business.add_product("Thin", opening_stock="3", min_stock="1", reorder_level="10")
    gone = business.add_product("Gone", opening_stock="6", min_stock="1", reorder_level="10")
    adjust_stock(
        business.db,
        business.ctx,
        variant_id=gone.default_variant.id,
        location_id=business.location.id,
        quantity=Decimal("-6"),
        reason=MovementReason.DAMAGE,
        note="Flooded",
    )

    low = client.get("/api/v1/stock/levels?status=low", headers=business.headers()).json()
    out = client.get(
        "/api/v1/stock/levels?status=out_of_stock", headers=business.headers()
    ).json()

    assert sorted(names(low)) == ["Gone", "Thin"]
    assert names(out) == ["Gone"]
    assert low["total"] == 2


def test_a_narrowed_list_pages_over_what_is_left_not_over_everything(client, business):
    for n in range(6):
        business.add_product(f"Grain {n}", category_name="Grains", opening_stock="5")
    business.add_product("Cement", category_name="Building", opening_stock="5")
    grains = next(
        row["category_id"]
        for row in client.get("/api/v1/stock/levels", headers=business.headers()).json()[
            "items"
        ]
        if row["category_name"] == "Grains"
    )

    page = client.get(
        f"/api/v1/stock/levels?category_id={grains}&limit=4&offset=4",
        headers=business.headers(),
    ).json()

    assert page["total"] == 6
    assert len(page["items"]) == 2
    assert all(row["category_name"] == "Grains" for row in page["items"])


# --------------------------------------------------------------------------- #
# Ordering, which is also grouping
# --------------------------------------------------------------------------- #


def test_sorting_by_quantity_puts_the_emptiest_shelf_first(client, business):
    business.add_product("Middle", opening_stock="50")
    business.add_product("Most", opening_stock="900")
    business.add_product("Least", opening_stock="1")

    up = client.get("/api/v1/stock/levels?sort=quantity", headers=business.headers()).json()
    down = client.get(
        "/api/v1/stock/levels?sort=quantity&direction=desc", headers=business.headers()
    ).json()

    assert names(up) == ["Least", "Middle", "Most"]
    assert names(down) == ["Most", "Middle", "Least"]


def test_sorting_by_status_is_by_urgency_not_by_the_alphabet(client, business):
    business.add_product("Fine", opening_stock="500", min_stock="1", reorder_level="2")
    business.add_product("Warning", opening_stock="8", min_stock="1", reorder_level="10")
    business.add_product("Critical", opening_stock="1", min_stock="1", reorder_level="10")
    empty = business.add_product("Empty", opening_stock="4", min_stock="1", reorder_level="10")
    adjust_stock(
        business.db,
        business.ctx,
        variant_id=empty.default_variant.id,
        location_id=business.location.id,
        quantity=Decimal("-4"),
        reason=MovementReason.DAMAGE,
        note="Flooded",
    )

    body = client.get("/api/v1/stock/levels?sort=status", headers=business.headers()).json()

    assert [row["status"] for row in body["items"]] == [
        "out_of_stock",
        "critical",
        "warning",
        "ok",
    ]


def test_grouping_by_branch_keeps_a_branch_together_across_a_page_boundary(
    client, business
):
    kality, kality_place = business.add_branch("Kality")
    for name in ("Apple", "Banana", "Cherry"):
        product = business.add_product(name, opening_stock="5")
        adjust_stock(
            business.db,
            business.ctx,
            variant_id=product.default_variant.id,
            location_id=kality_place.id,
            quantity=Decimal("4"),
            reason=MovementReason.OPENING,
            note="Counted on arrival",
        )

    first = client.get(
        "/api/v1/stock/levels?sort=branch&limit=3", headers=business.headers()
    ).json()
    second = client.get(
        "/api/v1/stock/levels?sort=branch&limit=3&offset=3", headers=business.headers()
    ).json()

    assert [row["branch_name"] for row in first["items"]] == ["Kality"] * 3
    assert [row["branch_name"] for row in second["items"]] == ["Main Branch"] * 3
    # Alphabetical within the heading, so the rows under it never shuffle.
    assert names(first) == ["Apple", "Banana", "Cherry"]
    assert first["total"] == 6


def test_reversing_the_order_does_not_reverse_the_rows_inside_a_group(client, business):
    business.add_product("Apple", category_name="Fruit", opening_stock="5")
    business.add_product("Banana", category_name="Fruit", opening_stock="5")
    business.add_product("Cement", category_name="Building", opening_stock="5")

    body = client.get(
        "/api/v1/stock/levels?sort=category&direction=desc", headers=business.headers()
    ).json()

    # Fruit before Building, but Apple still before Banana.
    assert names(body) == ["Apple", "Banana", "Cement"]
    assert [row["category_name"] for row in body["items"]] == [
        "Fruit",
        "Fruit",
        "Building",
    ]


def test_a_product_with_no_category_sorts_last_not_first(client, business):
    business.add_product("Zebra", category_name="Animals", opening_stock="5")
    business.add_product("Apple", opening_stock="5")

    body = client.get(
        "/api/v1/stock/levels?sort=category", headers=business.headers()
    ).json()

    assert names(body) == ["Zebra", "Apple"]


# --------------------------------------------------------------------------- #
# The overview across branches
# --------------------------------------------------------------------------- #


def test_the_overview_can_be_narrowed_to_a_category(business):
    business.add_product("Teff flour", category_name="Grains", opening_stock="40")
    cement = business.add_product("Cement", category_name="Building", opening_stock="60")

    result = stock_overview(business.db, business.ctx, category_id=cement.category_id)

    assert [row.name for row in result.rows] == ["Cement"]
    assert result.total_rows == 1


def test_the_overview_can_lead_with_what_there_is_most_of(business):
    business.add_product("Few", opening_stock="2")
    business.add_product("Many", opening_stock="800")
    business.add_product("Some", opening_stock="50")

    result = stock_overview(business.db, business.ctx, sort="total", direction="desc")

    assert [row.name for row in result.rows] == ["Many", "Some", "Few"]


def test_the_overview_row_names_its_category(business):
    business.add_product("Teff flour", category_name="Grains", opening_stock="40")

    result = stock_overview(business.db, business.ctx)

    assert result.rows[0].category_name == "Grains"


# --------------------------------------------------------------------------- #
# The ledger
# --------------------------------------------------------------------------- #


def test_the_ledger_names_what_it_is_about(client, business):
    """Identifiers are not a ledger anybody can read."""
    business.add_product("Teff flour", opening_stock="40")

    row = client.get("/api/v1/stock/movements", headers=business.headers()).json()["items"][0]

    assert row["product_name"] == "Teff flour"
    assert row["branch_name"] == "Main Branch"
    assert row["by_name"] == business.owner.full_name


def test_the_ledger_can_be_narrowed_to_one_reason(client, business):
    product = business.add_product("Teff flour", opening_stock="40")
    adjust_stock(
        business.db,
        business.ctx,
        variant_id=product.default_variant.id,
        location_id=business.location.id,
        quantity=Decimal("-2"),
        reason=MovementReason.DAMAGE,
        note="Torn sack",
    )

    body = client.get(
        "/api/v1/stock/movements?reason=damage", headers=business.headers()
    ).json()

    assert body["total"] == 1
    assert body["items"][0]["note"] == "Torn sack"


def test_the_ledger_can_be_narrowed_to_a_stretch_of_days(client, business):
    business.add_product("Teff flour", opening_stock="40")
    today = date.today()

    inside = client.get(
        f"/api/v1/stock/movements?since={today}&until={today}", headers=business.headers()
    ).json()
    before = client.get(
        f"/api/v1/stock/movements?until={today - timedelta(days=1)}",
        headers=business.headers(),
    ).json()

    assert inside["total"] == 1
    assert before["total"] == 0


def test_the_ledger_pages_and_says_how_much_there_is(client, business):
    product = business.add_product("Teff flour", opening_stock="40")
    for n in range(4):
        adjust_stock(
            business.db,
            business.ctx,
            variant_id=product.default_variant.id,
            location_id=business.location.id,
            quantity=Decimal("1"),
            reason=MovementReason.ADJUSTMENT,
            note=f"Count {n}",
        )

    page = client.get(
        "/api/v1/stock/movements?limit=2&offset=2", headers=business.headers()
    ).json()

    assert page["total"] == 5
    assert len(page["items"]) == 2


def test_another_business_cannot_read_this_ones_ledger_or_levels(
    client, business, other_business
):
    business.add_product("Teff flour", category_name="Grains", opening_stock="40")

    levels = client.get(
        "/api/v1/stock/levels?sort=category", headers=other_business.headers()
    ).json()
    ledger = client.get("/api/v1/stock/movements", headers=other_business.headers()).json()

    assert levels["items"] == []
    assert ledger["items"] == []
