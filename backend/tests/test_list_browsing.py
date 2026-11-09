"""Finding one sale, or one balance, among thousands (PRD 10, 11.5).

A shop taking fifty sales a day has fifteen thousand a year, and a credit
book that only grows.  Both lists have to be narrowed, ordered and read a
page at a time — and the ordering has to be the grouping too, because a
group that only holds together inside one page is not a group.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.models.credit import CreditKind
from app.models.inventory import MovementReason
from app.services.credit import create_credit_transaction


def numbers(body) -> list[str]:
    return [row["number"] for row in body["items"]]


def references(body) -> list[str]:
    return [row["reference"] for row in body["items"]]


# --------------------------------------------------------------------------- #
# Sales
# --------------------------------------------------------------------------- #


def test_a_sale_is_found_by_its_number_or_by_who_bought(client, business):
    selam = business.add_customer("Selam Construction")
    cement = business.add_product("Cement", opening_stock="100")
    first = business.sell(cement, customer_id=selam.id).sale
    second = business.sell(cement).sale

    by_name = client.get(
        "/api/v1/sales?q=selam", headers=business.headers()
    ).json()
    by_number = client.get(
        f"/api/v1/sales?q={second.number}", headers=business.headers()
    ).json()

    assert numbers(by_name) == [first.number]
    assert by_name["total"] == 1
    assert numbers(by_number) == [second.number]


def test_a_sale_says_whose_it_was(client, business):
    """You can search by customer; the rows have to say which one you found.

    A list of numbers and times identifies a sale only to somebody who
    already knows which one they are looking for.
    """
    selam = business.add_customer("Selam Construction")
    cement = business.add_product("Cement", opening_stock="100")
    business.sell(cement, customer_id=selam.id)
    business.sell(cement)

    listed = client.get("/api/v1/sales", headers=business.headers()).json()
    names = {row["customer_name"] for row in listed["items"]}

    assert names == {"Selam Construction", None}

    # And on one sale read by itself, not only in the list.
    one = next(r for r in listed["items"] if r["customer_name"])
    alone = client.get(
        f"/api/v1/sales/{one['id']}", headers=business.headers()
    ).json()
    assert alone["customer_name"] == "Selam Construction"


def test_a_voided_sale_is_kept_out_of_the_way_but_not_out_of_reach(
    client, business, db
):
    cement = business.add_product("Cement", opening_stock="100")
    kept = business.sell(cement).sale
    gone = business.sell(cement).sale
    from app.services.sales import void_sale

    void_sale(db, business.ctx, sale_id=gone.id, reason="Rung up twice")
    db.flush()

    default = client.get("/api/v1/sales", headers=business.headers()).json()
    voided = client.get(
        "/api/v1/sales?status=voided", headers=business.headers()
    ).json()
    both = client.get("/api/v1/sales?status=all", headers=business.headers()).json()

    assert numbers(default) == [kept.number]
    assert numbers(voided) == [gone.number]
    assert both["total"] == 2
    # The older spelling still widens the list, for a client that has not
    # been changed yet.
    older = client.get(
        "/api/v1/sales?include_voided=true", headers=business.headers()
    ).json()
    assert older["total"] == 2


def test_sales_can_lead_with_the_biggest(client, business):
    cement = business.add_product("Cement", selling_price="100", opening_stock="500")
    small = business.sell(cement, quantity="1").sale
    big = business.sell(cement, quantity="40").sale
    middling = business.sell(cement, quantity="10").sale

    down = client.get(
        "/api/v1/sales?sort=total&direction=desc", headers=business.headers()
    ).json()
    up = client.get(
        "/api/v1/sales?sort=total&direction=asc", headers=business.headers()
    ).json()

    assert numbers(down) == [big.number, middling.number, small.number]
    assert numbers(up) == [small.number, middling.number, big.number]


def test_grouping_sales_by_branch_keeps_a_branch_together(client, business, db):
    kality, kality_place = business.add_branch("Kality")
    cement = business.add_product("Cement", opening_stock="400")
    from app.services.inventory import adjust_stock

    adjust_stock(
        db,
        business.ctx,
        variant_id=cement.default_variant.id,
        location_id=kality_place.id,
        quantity=Decimal("20"),
        reason=MovementReason.OPENING,
        note="Counted on arrival",
    )
    here_one = business.sell(cement).sale
    here_two = business.sell(cement).sale
    there = business.sell(cement, branch_id=kality.id, location_id=kality_place.id).sale

    body = client.get("/api/v1/sales?sort=branch", headers=business.headers()).json()
    branches = [row["branch_id"] for row in body["items"]]

    assert branches == [str(kality.id), str(business.branch.id), str(business.branch.id)]
    assert set(numbers(body)) == {here_one.number, here_two.number, there.number}


def test_a_narrowed_sales_list_pages_over_what_is_left(client, business):
    selam = business.add_customer("Selam Construction")
    cement = business.add_product("Cement", opening_stock="500")
    for _ in range(5):
        business.sell(cement, customer_id=selam.id)
    for _ in range(3):
        business.sell(cement)

    page = client.get(
        "/api/v1/sales?q=selam&limit=2&offset=4", headers=business.headers()
    ).json()

    assert page["total"] == 5
    assert len(page["items"]) == 1


def test_sales_can_be_narrowed_to_a_stretch_of_days(client, business):
    cement = business.add_product("Cement", opening_stock="100")
    business.sell(cement)
    today = date.today()

    inside = client.get(
        f"/api/v1/sales?date_from={today}&date_to={today}", headers=business.headers()
    ).json()
    before = client.get(
        f"/api/v1/sales?date_to={today - timedelta(days=1)}",
        headers=business.headers(),
    ).json()

    assert inside["total"] == 1
    assert before["total"] == 0


# --------------------------------------------------------------------------- #
# Credit
# --------------------------------------------------------------------------- #


def _owing(business, name: str, amount: str, due: date | None) -> str:
    """One receivable, owed by a customer of that name."""
    customer = business.add_customer(name)
    transaction = create_credit_transaction(
        business.db,
        business.ctx,
        kind=CreditKind.RECEIVABLE,
        amount=Decimal(amount),
        customer_id=customer.id,
        branch_id=business.branch.id,
        due_date=due,
    )
    business.db.flush()
    return transaction.reference


def test_a_balance_is_found_by_the_name_that_owes_it(client, business):
    today = date.today()
    _owing(business, "Selam Construction", "900", today)
    hidden = _owing(business, "Dawit Trading", "400", today)

    body = client.get(
        "/api/v1/credit/transactions?view=all&q=selam", headers=business.headers()
    ).json()

    assert body["total"] == 1
    assert hidden not in references(body)
    assert body["items"][0]["counterparty_name"] == "Selam Construction"


def test_balances_lead_with_what_is_due_soonest(client, business):
    today = date.today()
    late = _owing(business, "Late", "100", today + timedelta(days=30))
    soon = _owing(business, "Soon", "100", today + timedelta(days=1))
    undated = _owing(business, "Undated", "100", None)

    body = client.get(
        "/api/v1/credit/transactions?view=all&sort=due", headers=business.headers()
    ).json()

    # Soonest first, and a balance with no due date is not urgent — it sorts
    # after the ones that are, not ahead of them.
    assert references(body) == [soon, late, undated]


def test_balances_can_lead_with_the_biggest_debt(client, business):
    today = date.today()
    small = _owing(business, "Small", "50", today)
    large = _owing(business, "Large", "5000", today)
    middling = _owing(business, "Middling", "500", today)

    body = client.get(
        "/api/v1/credit/transactions?view=all&sort=outstanding",
        headers=business.headers(),
    ).json()

    assert references(body) == [large, middling, small]


def test_grouping_balances_by_name_keeps_one_customer_together(client, business):
    today = date.today()
    customer = business.add_customer("Selam Construction")
    first = create_credit_transaction(
        business.db,
        business.ctx,
        kind=CreditKind.RECEIVABLE,
        amount=Decimal("100"),
        customer_id=customer.id,
        branch_id=business.branch.id,
        due_date=today,
    )
    second = create_credit_transaction(
        business.db,
        business.ctx,
        kind=CreditKind.RECEIVABLE,
        amount=Decimal("200"),
        customer_id=customer.id,
        branch_id=business.branch.id,
        due_date=today,
    )
    business.db.flush()
    _owing(business, "Abebe Retail", "300", today)

    body = client.get(
        "/api/v1/credit/transactions?view=all&sort=name", headers=business.headers()
    ).json()
    names = [row["counterparty_name"] for row in body["items"]]

    assert names == ["Abebe Retail", "Selam Construction", "Selam Construction"]
    assert set(references(body)[1:]) == {first.reference, second.reference}


def test_a_narrowed_credit_list_pages_over_what_is_left(client, business):
    today = date.today()
    for n in range(5):
        _owing(business, f"Selam {n}", "100", today)
    _owing(business, "Somebody else", "100", today)

    page = client.get(
        "/api/v1/credit/transactions?view=all&q=selam&limit=2&offset=4",
        headers=business.headers(),
    ).json()

    assert page["total"] == 5
    assert len(page["items"]) == 1


def test_the_credit_export_follows_the_same_search_as_the_screen(client, business):
    today = date.today()
    _owing(business, "Selam Construction", "900", today)
    _owing(business, "Dawit Trading", "400", today)

    everything = client.get(
        "/api/v1/credit/transactions/export?view=all", headers=business.headers()
    )
    narrowed = client.get(
        "/api/v1/credit/transactions/export?view=all&q=selam",
        headers=business.headers(),
    )

    assert "Dawit" in everything.text
    assert "Selam" in narrowed.text
    assert "Dawit" not in narrowed.text


def test_another_business_sees_none_of_these(client, business, other_business):
    cement = business.add_product("Cement", opening_stock="100")
    business.sell(cement)
    _owing(business, "Selam Construction", "900", date.today())

    sales = client.get("/api/v1/sales?q=cement", headers=other_business.headers()).json()
    credit = client.get(
        "/api/v1/credit/transactions?view=all&q=selam",
        headers=other_business.headers(),
    ).json()

    assert sales["items"] == []
    assert credit["items"] == []


# --------------------------------------------------------------------------- #
# The catalogue
# --------------------------------------------------------------------------- #


def names(body) -> list[str]:
    return [row["name"] for row in body["items"]]


def test_products_can_be_narrowed_to_one_category(client, business):
    business.add_product("Teff flour", category_name="Grains")
    business.add_product("Sugar", category_name="Grains")
    business.add_product("Cement", category_name="Building")
    grains = next(
        row["category_id"]
        for row in client.get("/api/v1/products", headers=business.headers()).json()[
            "items"
        ]
        if row["category_name"] == "Grains"
    )

    body = client.get(
        f"/api/v1/products?category_id={grains}", headers=business.headers()
    ).json()

    assert sorted(names(body)) == ["Sugar", "Teff flour"]
    assert body["total"] == 2


def test_products_can_be_narrowed_to_what_is_on_the_shop_and_what_is_not(
    client, business, db
):
    listed = business.add_product("Listed")
    business.add_product("Unlisted")
    listed.is_published = True
    db.flush()

    on = client.get("/api/v1/products?published=true", headers=business.headers()).json()
    off = client.get(
        "/api/v1/products?published=false", headers=business.headers()
    ).json()
    both = client.get("/api/v1/products", headers=business.headers()).json()

    assert names(on) == ["Listed"]
    assert names(off) == ["Unlisted"]
    assert both["total"] == 2


def test_an_archived_product_is_out_of_the_way_but_not_out_of_reach(
    client, business, db
):
    business.add_product("Selling")
    gone = business.add_product("Discontinued")
    gone.is_active = False
    db.flush()

    default = client.get("/api/v1/products", headers=business.headers()).json()
    with_archived = client.get(
        "/api/v1/products?include_inactive=true", headers=business.headers()
    ).json()

    assert names(default) == ["Selling"]
    assert default["total"] == 1
    assert sorted(names(with_archived)) == ["Discontinued", "Selling"]


def test_products_can_lead_with_the_dearest_or_the_cheapest(client, business):
    business.add_product("Middling", selling_price="500")
    business.add_product("Dear", selling_price="5000")
    business.add_product("Cheap", selling_price="5")

    down = client.get("/api/v1/products?sort=price", headers=business.headers()).json()
    up = client.get(
        "/api/v1/products?sort=price&direction=asc", headers=business.headers()
    ).json()

    # Price reads dearest first unless asked otherwise.
    assert names(down) == ["Dear", "Middling", "Cheap"]
    assert names(up) == ["Cheap", "Middling", "Dear"]


def test_products_can_lead_with_the_emptiest_shelf(client, business):
    business.add_product("Plenty", opening_stock="900")
    business.add_product("Some", opening_stock="40")
    business.add_product("Almost none", opening_stock="1")

    up = client.get(
        "/api/v1/products?sort=stock&direction=asc", headers=business.headers()
    ).json()

    assert names(up) == ["Almost none", "Some", "Plenty"]


def test_grouping_products_by_category_keeps_a_category_together(client, business):
    business.add_product("Apple", category_name="Fruit")
    business.add_product("Banana", category_name="Fruit")
    business.add_product("Cement", category_name="Building")
    business.add_product("Uncategorised")

    body = client.get(
        "/api/v1/products?sort=category", headers=business.headers()
    ).json()

    assert [row["category_name"] for row in body["items"]] == [
        "Building",
        "Fruit",
        "Fruit",
        None,
    ]
    # Alphabetical within the heading, so the rows under it never shuffle.
    assert names(body) == ["Cement", "Apple", "Banana", "Uncategorised"]


def test_a_narrowed_catalogue_pages_over_what_is_left(client, business):
    for n in range(6):
        business.add_product(f"Grain {n}", category_name="Grains")
    business.add_product("Cement", category_name="Building")
    grains = next(
        row["category_id"]
        for row in client.get(
            "/api/v1/products?limit=50", headers=business.headers()
        ).json()["items"]
        if row["category_name"] == "Grains"
    )

    page = client.get(
        f"/api/v1/products?category_id={grains}&limit=4&offset=4",
        headers=business.headers(),
    ).json()

    assert page["total"] == 6
    assert len(page["items"]) == 2
    assert all(row["category_name"] == "Grains" for row in page["items"])


def test_another_business_sees_none_of_this_catalogue(client, business, other_business):
    business.add_product("Teff flour", category_name="Grains")

    body = client.get(
        "/api/v1/products?sort=category", headers=other_business.headers()
    ).json()

    assert body["items"] == []
