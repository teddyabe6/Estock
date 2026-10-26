"""The central marketplace, and requests that span shops (PRD 13, 14).

Two things are new here, and one of them crosses the line the rest of the
system is built on.

**Reading across shops.** Everywhere else a read goes through
``tenant_query``, which cannot be called without a tenant id. The marketplace
has to show a buyer products from shops that know nothing of each other, so
the crossing is made once, in ``app/services/marketplace.py``, through a
projection that cannot reach a cost, a customer, a credit balance or a stock
quantity. These tests are what hold that projection narrow.

**Fanning a basket out.** One buyer's cross-shop basket becomes one request of
theirs and one proforma per shop. Each shop reviews its own part and never
learns who else was asked.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.errors import NotFoundError, ValidationError
from app.core.tenancy import COST_BEARING_FIELDS
from app.models.commerce import (
    MarketplaceRequest,
    MarketplaceRequestStatus,
    OnlineStore,
    QuotationStatus,
)
from app.models.platform import TenantStatus
from app.services import marketplace
from app.services.catalogue import (
    list_published_on_marketplace,
    set_published,
    update_product,
)
from app.services.commerce import (
    MarketplaceBasketItem,
    get_marketplace_request,
    marketplace_request_state,
    send_quotation,
    submit_marketplace_request,
    withdraw_marketplace_request,
)


def _join_marketplace(business, *, slug: str, name: str, published: bool = True):
    """Give a business a storefront row and put it on the marketplace."""
    store = (
        business.db.query(OnlineStore)
        .filter(OnlineStore.tenant_id == business.tenant.id)
        .one_or_none()
    )
    if store is None:
        store = OnlineStore(tenant_id=business.tenant.id, slug=slug, display_name=name)
        business.db.add(store)
    store.slug = slug
    store.display_name = name
    store.is_published = published
    store.list_on_marketplace = True
    business.db.flush()
    return store


def _list(business, product):
    product.on_marketplace = True
    product.is_published = True
    business.db.flush()
    return product


@pytest.fixture
def two_shops(business, other_business):
    """Two unrelated businesses, both on the marketplace, with one product each."""
    _join_marketplace(business, slug="addis-retail", name="Addis Retail")
    _join_marketplace(other_business, slug="bahir-dar", name="Bahir Dar Traders")
    first = _list(business, business.add_product("Teff 25kg", selling_price="2800",
                                                 purchase_price="2000", opening_stock="20"))
    second = _list(other_business, other_business.add_product("Berbere 1kg", selling_price="450",
                                                              purchase_price="300",
                                                              opening_stock="40"))
    return first, second


# --------------------------------------------------------------------------- #
# One catalogue, many shops
# --------------------------------------------------------------------------- #


def test_the_marketplace_shows_products_from_every_shop(db, two_shops):
    first, second = two_shops
    products, total = marketplace.marketplace_products(db)

    assert total == 2
    names = {p.name for p in products}
    assert names == {"Teff 25kg", "Berbere 1kg"}
    shops = {p.shop.name for p in products}
    assert shops == {"Addis Retail", "Bahir Dar Traders"}


def test_a_product_is_listed_only_when_its_shop_opted_in(db, business, other_business):
    _join_marketplace(business, slug="in", name="In")
    _list(business, business.add_product("Listed", selling_price="10"))

    # The second shop marked a product for the marketplace but opted out of
    # the marketplace itself.  Said out loud rather than left to the default,
    # which now puts a new shop in.
    other_store = (
        db.query(OnlineStore)
        .filter(OnlineStore.tenant_id == other_business.tenant.id)
        .one()
    )
    other_store.list_on_marketplace = False
    other = other_business.add_product("Not listed", selling_price="10")
    other.on_marketplace = True
    db.flush()

    products, total = marketplace.marketplace_products(db)
    assert total == 1
    assert products[0].name == "Listed"


def test_a_product_is_listed_only_when_the_shop_marked_it(db, business):
    _join_marketplace(business, slug="in", name="In")
    business.add_product("Kept back", selling_price="10")  # on_marketplace defaults false

    _products, total = marketplace.marketplace_products(db)
    assert total == 0


def test_joining_the_marketplace_is_separate_from_publishing_your_own_page(db, business):
    """A shop may do either, both or neither."""
    store = _join_marketplace(business, slug="quiet", name="Quiet Shop", published=False)
    _list(business, business.add_product("Teff", selling_price="10"))

    products, total = marketplace.marketplace_products(db)
    assert total == 1
    assert products[0].shop.has_own_page is False
    assert store.is_published is False


def test_a_suspended_shop_disappears_from_the_marketplace(db, business, two_shops):
    business.tenant.status = TenantStatus.SUSPENDED
    db.flush()

    products, total = marketplace.marketplace_products(db)
    assert total == 1
    assert products[0].shop.name == "Bahir Dar Traders"


def test_a_shop_that_cannot_answer_is_not_listed(db, business, two_shops):
    """A lapsed trial is read-only, so it could not reply to a request.

    Listing a shop that cannot quote would send buyers to a dead end.
    """
    business.tenant.status = TenantStatus.RESTRICTED
    db.flush()

    _products, total = marketplace.marketplace_products(db)
    assert total == 1


def test_search_and_filters_work_across_shops(db, two_shops):
    by_name, _ = marketplace.marketplace_products(db, query="berbere")
    assert [p.name for p in by_name] == ["Berbere 1kg"]

    by_shop, _ = marketplace.marketplace_products(db, shop_slug="addis-retail")
    assert [p.name for p in by_shop] == ["Teff 25kg"]

    nothing, total = marketplace.marketplace_products(db, query="bicycle")
    assert nothing == [] and total == 0


def test_the_shop_directory_lists_only_shops_on_the_marketplace(db, two_shops):
    names = [shop.name for shop in marketplace.shops(db)]
    assert names == ["Addis Retail", "Bahir Dar Traders"]


def test_a_shop_not_on_the_marketplace_is_not_found_by_slug(db, business):
    store = _join_marketplace(business, slug="leaving", name="Leaving")
    store.list_on_marketplace = False
    db.flush()

    with pytest.raises(NotFoundError):
        marketplace.get_shop(db, "leaving")


def test_a_product_with_several_variants_counts_once(db, business):
    """The catalogue eager-loads variants, which is a collection join.

    If that join reached the count, a shirt in three sizes would report as
    three products.  It does not — SQLAlchemy leaves loader options out of the
    count subquery — but that is not obvious, so it is pinned here.
    """
    from app.services.catalogue import VariantInput, add_variant

    _join_marketplace(business, slug="clothes", name="Clothes")
    shirt = _list(business, business.add_product("Shirt", selling_price="500"))
    add_variant(business.db, business.ctx, shirt.id, VariantInput(name="Medium"))
    add_variant(business.db, business.ctx, shirt.id, VariantInput(name="Large"))
    db.flush()
    db.refresh(shirt)
    assert len(shirt.variants) == 3

    products, total = marketplace.marketplace_products(db)
    assert total == 1
    assert len(products) == 1
    assert len(products[0].variants) == 3


# --------------------------------------------------------------------------- #
# What the projection refuses to carry
# --------------------------------------------------------------------------- #


def test_the_marketplace_never_exposes_cost_or_profit(client, two_shops):
    """No token, no permissions — so no cost field may appear at all."""
    listing = client.get("/api/v1/market/products")
    assert listing.status_code == 200

    def leaks(payload, found=None):
        found = [] if found is None else found
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in COST_BEARING_FIELDS and value is not None:
                    found.append((key, value))
                leaks(value, found)
        elif isinstance(payload, list):
            for item in payload:
                leaks(item, found)
        return found

    assert leaks(listing.json()) == []


def test_the_marketplace_reports_availability_but_not_quantity(db, two_shops):
    """A rival must not be able to watch a shop's stock by polling."""
    products, _ = marketplace.marketplace_products(db)
    teff = next(p for p in products if p.name == "Teff 25kg")

    assert teff.in_stock is True
    payload = teff.as_dict()
    assert "quantity" not in payload
    assert "quantity_on_hand" not in payload
    assert set(payload["variants"][0]) == {"id", "name", "is_default", "price", "in_stock"}


def test_a_shop_that_hides_prices_shows_none_on_the_marketplace(db, business, two_shops):
    store = business.db.query(OnlineStore).filter_by(tenant_id=business.tenant.id).one()
    store.show_prices = False
    db.flush()

    products, _ = marketplace.marketplace_products(db)
    teff = next(p for p in products if p.name == "Teff 25kg")
    assert teff.price is None
    assert all(v.price is None for v in teff.variants)


# --------------------------------------------------------------------------- #
# One basket, several shops
# --------------------------------------------------------------------------- #


def _submit(db, items, **kwargs):
    return submit_marketplace_request(
        db,
        items=items,
        contact_name=kwargs.pop("contact_name", "Abebe Bekele"),
        contact_phone=kwargs.pop("contact_phone", "0911223344"),
        **kwargs,
    )


def test_one_basket_becomes_one_proforma_per_shop(db, two_shops):
    first, second = two_shops

    result = _submit(
        db,
        [
            MarketplaceBasketItem(first.default_variant.id, Decimal("2")),
            MarketplaceBasketItem(second.default_variant.id, Decimal("5")),
        ],
        delivery_location="Bole, Addis Ababa",
        message="Need these by Friday.",
    )
    db.flush()

    assert result.request.reference.startswith("MR-")
    assert len(result.quotations) == 2
    # Each shop's own sequential proforma number, in its own books.
    assert {q.number[:3] for q in result.quotations} == {"PF-"}
    assert {q.tenant_id for q in result.quotations} == {
        first.tenant_id,
        second.tenant_id,
    }
    # Priced from each shop's own catalogue, not retyped by the buyer.
    teff = next(q for q in result.quotations if q.tenant_id == first.tenant_id)
    assert teff.total_amount == Decimal("5600.00")
    assert all(q.status == QuotationStatus.REQUESTED for q in result.quotations)


def test_each_shop_sees_only_its_own_part(db, two_shops):
    first, second = two_shops
    result = _submit(
        db,
        [
            MarketplaceBasketItem(first.default_variant.id, Decimal("1")),
            MarketplaceBasketItem(second.default_variant.id, Decimal("1")),
        ],
    )
    db.flush()

    for quotation in result.quotations:
        assert len(quotation.lines) == 1
        assert quotation.lines[0].variant_id in {
            first.default_variant.id,
            second.default_variant.id,
        }
        # Nothing joins from a quotation to its siblings.
        assert not hasattr(quotation, "siblings")


def test_a_shop_cannot_reach_another_shops_part_of_the_request(client, db, two_shops):
    """The parent id is on the quotation; it must not open a door to the rest."""
    first, second = two_shops
    result = _submit(
        db,
        [
            MarketplaceBasketItem(first.default_variant.id, Decimal("1")),
            MarketplaceBasketItem(second.default_variant.id, Decimal("1")),
        ],
    )
    db.flush()

    mine = next(q for q in result.quotations if q.tenant_id == first.tenant_id)
    theirs = next(q for q in result.quotations if q.tenant_id == second.tenant_id)
    assert mine.marketplace_request_id == theirs.marketplace_request_id

    # The first shop's own API cannot read the second shop's proforma, even
    # knowing its id and sharing a parent request.
    headers = {"Authorization": f"Bearer {_token_for(db, first.tenant_id)}"}
    response = client.get(f"/api/v1/shop/quotations/{theirs.id}", headers=headers)
    assert response.status_code == 404


def _token_for(db, tenant_id):
    from app.core.security import create_access_token
    from app.models.access import TenantMembership

    membership = (
        db.query(TenantMembership).filter(TenantMembership.tenant_id == tenant_id).first()
    )
    return create_access_token(subject=membership.user_id, tenant_id=tenant_id)


def test_the_buyer_gets_one_link_that_tracks_every_shop(db, two_shops):
    first, second = two_shops
    result = _submit(
        db,
        [
            MarketplaceBasketItem(first.default_variant.id, Decimal("1")),
            MarketplaceBasketItem(second.default_variant.id, Decimal("1")),
        ],
    )
    db.flush()

    state = marketplace_request_state(db, result.request)
    assert state["shop_count"] == 2
    assert state["answered_count"] == 0
    assert state["status"] == str(MarketplaceRequestStatus.OPEN)
    assert [row["shop"] for row in state["shops"]] == ["Addis Retail", "Bahir Dar Traders"]
    # Nothing is priced to the buyer until a shop sends it.
    assert all(row["total_amount"] is None for row in state["shops"])


def test_the_tracking_page_fills_in_as_shops_answer(db, business, two_shops):
    first, second = two_shops
    result = _submit(
        db,
        [
            MarketplaceBasketItem(first.default_variant.id, Decimal("2")),
            MarketplaceBasketItem(second.default_variant.id, Decimal("1")),
        ],
    )
    db.flush()

    mine = next(q for q in result.quotations if q.tenant_id == business.tenant.id)
    send_quotation(db, business.ctx, mine.id)
    db.flush()

    state = marketplace_request_state(db, result.request)
    assert state["answered_count"] == 1
    assert state["status"] == str(MarketplaceRequestStatus.OPEN)  # one still to answer
    answered = next(row for row in state["shops"] if row["shop"] == "Addis Retail")
    assert answered["answered"] is True
    assert answered["total_amount"] == "5600.00"
    assert answered["token"] == mine.share_token


def test_a_request_is_answered_once_no_shop_is_still_sitting_on_it(db, business, other_business, two_shops):
    first, second = two_shops
    result = _submit(
        db,
        [
            MarketplaceBasketItem(first.default_variant.id, Decimal("1")),
            MarketplaceBasketItem(second.default_variant.id, Decimal("1")),
        ],
    )
    db.flush()

    for ctx, tenant in ((business.ctx, business.tenant), (other_business.ctx, other_business.tenant)):
        quotation = next(q for q in result.quotations if q.tenant_id == tenant.id)
        send_quotation(db, ctx, quotation.id)
    db.flush()

    state = marketplace_request_state(db, result.request)
    assert state["status"] == str(MarketplaceRequestStatus.ANSWERED)
    assert state["answered_count"] == 2


def test_an_unlisted_item_refuses_the_whole_request(db, business, two_shops):
    """The basket is in the buyer's browser, so they lose nothing by retrying.

    A request silently missing an item would be worse than one refused with a
    reason.
    """
    first, second = two_shops
    first.on_marketplace = False
    db.flush()

    with pytest.raises(ValidationError) as refused:
        _submit(
            db,
            [
                MarketplaceBasketItem(first.default_variant.id, Decimal("1")),
                MarketplaceBasketItem(second.default_variant.id, Decimal("1")),
            ],
        )
    assert str(first.default_variant.id) in refused.value.details["unavailable"]
    assert db.query(MarketplaceRequest).count() == 0


def test_a_request_reserves_no_stock(db, two_shops):
    """Asking for a price moves nothing, exactly as for a single-shop request."""
    from app.services.inventory import get_balance

    first, _second = two_shops
    location_id = _location(db, first.tenant_id)
    args = (db, first.tenant_id, first.default_variant.id, location_id)

    before = get_balance(*args)
    _submit(db, [MarketplaceBasketItem(first.default_variant.id, Decimal("5"))])
    db.flush()

    assert get_balance(*args) == before


def _location(db, tenant_id):
    from app.models.organisation import StockLocation

    return db.query(StockLocation).filter(StockLocation.tenant_id == tenant_id).first().id


def test_a_buyer_can_withdraw_before_anyone_has_quoted(db, business, two_shops):
    first, second = two_shops
    result = _submit(
        db,
        [
            MarketplaceBasketItem(first.default_variant.id, Decimal("1")),
            MarketplaceBasketItem(second.default_variant.id, Decimal("1")),
        ],
    )
    db.flush()

    withdraw_marketplace_request(db, result.request.share_token)
    db.flush()

    state = marketplace_request_state(db, result.request)
    assert state["status"] == str(MarketplaceRequestStatus.WITHDRAWN)
    assert all(q.status == QuotationStatus.CANCELLED for q in result.quotations)


def test_withdrawing_leaves_a_quotation_a_shop_already_sent(db, business, two_shops):
    """Silently cancelling work a shop has done would be rude.

    The buyer declines a sent proforma on that shop's own page instead.
    """
    first, second = two_shops
    result = _submit(
        db,
        [
            MarketplaceBasketItem(first.default_variant.id, Decimal("1")),
            MarketplaceBasketItem(second.default_variant.id, Decimal("1")),
        ],
    )
    db.flush()
    mine = next(q for q in result.quotations if q.tenant_id == business.tenant.id)
    send_quotation(db, business.ctx, mine.id)
    db.flush()

    withdraw_marketplace_request(db, result.request.share_token)
    db.flush()

    assert mine.status == QuotationStatus.SENT
    theirs = next(q for q in result.quotations if q.tenant_id != business.tenant.id)
    assert theirs.status == QuotationStatus.CANCELLED


def test_a_withdrawal_is_recorded_in_each_shops_own_audit_log(db, business, two_shops):
    first, second = two_shops
    result = _submit(
        db,
        [
            MarketplaceBasketItem(first.default_variant.id, Decimal("1")),
            MarketplaceBasketItem(second.default_variant.id, Decimal("1")),
        ],
    )
    db.flush()
    withdraw_marketplace_request(db, result.request.share_token)
    db.flush()

    from app.models.platform import AuditEvent

    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.tenant_id == business.tenant.id, AuditEvent.action == "quotation.cancelled")
        .all()
    )
    assert len(events) == 1
    assert "Abebe Bekele" in events[0].actor_label
    assert result.request.reference in events[0].summary


def test_two_requests_never_share_a_reference(db, two_shops):
    """The reference is random, so it is checked before it is used.

    Not atomic — the unique constraint on the column is the real backstop —
    but it keeps a collision off the common path.
    """
    first, _second = two_shops
    refs = set()
    for _ in range(12):
        result = _submit(db, [MarketplaceBasketItem(first.default_variant.id, Decimal("1"))])
        db.flush()
        refs.add(result.request.reference)

    assert len(refs) == 12
    assert all(len(ref.split("-")[-1]) == 8 for ref in refs), refs


def test_a_reference_avoids_characters_people_confuse(db, two_shops):
    """A buyer reads this out over the phone."""
    first, _second = two_shops
    result = _submit(db, [MarketplaceBasketItem(first.default_variant.id, Decimal("1"))])
    body = result.request.reference.split("-")[-1]
    assert not set(body) & set("01OIL")


def test_a_tracking_link_that_does_not_exist_is_not_found(db):
    with pytest.raises(NotFoundError):
        get_marketplace_request(db, "not-a-real-token")


def test_the_same_item_twice_is_one_line_of_the_larger_quantity(db, two_shops):
    first, _second = two_shops
    result = _submit(
        db, [MarketplaceBasketItem(first.default_variant.id, Decimal("1"))] * 3
    )
    db.flush()

    assert len(result.quotations) == 1
    assert len(result.quotations[0].lines) == 1
    assert result.quotations[0].lines[0].quantity == Decimal("3.000")


def test_too_many_items_in_one_basket_is_refused(db, business, two_shops):
    """A basket cannot price a whole catalogue."""
    from app.services.commerce import MAX_REQUEST_TOTAL_LINES

    _join_marketplace(business, slug="addis-retail", name="Addis Retail")
    items = []
    for i in range(MAX_REQUEST_TOTAL_LINES + 1):
        product = _list(business, business.add_product(f"Item {i}", selling_price="10"))
        items.append(MarketplaceBasketItem(product.default_variant.id, Decimal("1")))

    with pytest.raises(ValidationError) as refused:
        _submit(db, items)
    assert str(MAX_REQUEST_TOTAL_LINES) in str(refused.value)
    assert db.query(MarketplaceRequest).count() == 0


def test_too_many_shops_in_one_basket_is_refused(db):
    """Canvassing the whole platform with one click is not a feature."""
    from conftest import Business

    from app.services.commerce import MAX_REQUEST_SHOPS

    items = []
    for i in range(MAX_REQUEST_SHOPS + 1):
        shop = Business(db, f"Shop {i}", f"owner{i}@shop.et")
        _join_marketplace(shop, slug=f"shop-{i}", name=f"Shop {i}")
        product = _list(shop, shop.add_product("Teff", selling_price="10"))
        items.append(MarketplaceBasketItem(product.default_variant.id, Decimal("1")))

    with pytest.raises(ValidationError) as refused:
        _submit(db, items)
    assert str(MAX_REQUEST_SHOPS) in str(refused.value)
    assert db.query(MarketplaceRequest).count() == 0


# --------------------------------------------------------------------------- #
# Joining the marketplace, and what comes with you
# --------------------------------------------------------------------------- #
#
# Two flags decide whether a product is on the marketplace — the shop's and
# the product's — and holding them wholly apart set a trap: a seller ticks
# the shop's switch, looks at the marketplace, and finds nothing of theirs.
# These are the rules that close it without collapsing the two decisions into
# one, because a shop may still want its own page only, or the marketplace
# only, or both.


def _store_of(business) -> OnlineStore:
    return (
        business.db.query(OnlineStore)
        .filter(OnlineStore.tenant_id == business.tenant.id)
        .one()
    )


def test_a_new_shop_joins_the_marketplace(business):
    """The default a seller should not have to go looking for."""
    store = _store_of(business)
    assert store.list_on_marketplace is True
    # Its own page is a separate decision and stays offline until they make it.
    assert store.is_published is False


def test_a_shop_that_stayed_out_is_left_out(business):
    """A default decides new rows.  It must never rewrite an old answer."""
    store = _store_of(business)
    store.list_on_marketplace = False
    business.db.flush()
    business.db.expire(store)
    assert _store_of(business).list_on_marketplace is False


def test_a_product_created_published_is_listed_too(business):
    """The rule has to hold on every path into publication, not just the
    toggle: a product form can publish on the way in."""
    product = business.add_product("Teff 25kg", is_published=True)

    assert product.on_marketplace is True


def test_editing_a_product_into_publication_lists_it(business):
    product = business.add_product("Teff 25kg")

    update_product(business.db, business.ctx, product.id, {"is_published": True})

    assert product.on_marketplace is True


def test_publishing_a_product_lists_it_where_the_shop_has_joined(business):
    product = business.add_product("Teff 25kg")
    assert product.on_marketplace is False, "nothing is listed until it is published"

    set_published(business.db, business.ctx, product.id, True)

    assert product.is_published is True
    assert product.on_marketplace is True


def test_publishing_lists_nothing_where_the_shop_stayed_out(business):
    store = _store_of(business)
    store.list_on_marketplace = False
    business.db.flush()
    product = business.add_product("Teff 25kg")

    set_published(business.db, business.ctx, product.id, True)

    assert product.on_marketplace is False, "the shop's own choice decides this"


def test_hiding_a_product_does_not_take_it_off_the_marketplace(business):
    """A shop selling only through the marketplace publishes no page at all."""
    product = business.add_product("Teff 25kg")
    set_published(business.db, business.ctx, product.id, True)

    set_published(business.db, business.ctx, product.id, False)

    assert product.is_published is False
    assert product.on_marketplace is True, "unlisting is its own deliberate act"


def test_joining_brings_the_published_catalogue_with_it(business):
    store = _store_of(business)
    store.list_on_marketplace = False
    business.db.flush()

    on_sale = business.add_product("Teff 25kg")
    set_published(business.db, business.ctx, on_sale.id, True)
    held_back = business.add_product("Damaged sacks")

    store.list_on_marketplace = True
    moved = list_published_on_marketplace(business.db, business.ctx)

    assert moved == 1
    assert on_sale.on_marketplace is True
    assert held_back.on_marketplace is False, (
        "joining a marketplace is not a decision to publish what was kept back"
    )


def test_the_switch_itself_brings_them(client, business):
    """The service rule is only worth having if the switch actually runs it."""
    store = _store_of(business)
    store.list_on_marketplace = False
    business.db.flush()
    product = business.add_product("Teff 25kg")
    set_published(business.db, business.ctx, product.id, True)
    assert product.on_marketplace is False

    response = client.patch(
        "/api/v1/shop/settings",
        json={"list_on_marketplace": True},
        headers=business.headers(),
    )

    assert response.status_code == 200, response.json()
    business.db.expire(product)
    assert product.on_marketplace is True


def test_a_shop_with_nothing_listed_stays_out_of_the_directory(business):
    """Every shop joins by default, so the directory has to earn its names."""
    store = _store_of(business)
    store.slug = "empty-shop"
    business.db.flush()
    assert [shop.slug for shop in marketplace.shops(business.db)] == []

    product = business.add_product("Teff 25kg")
    set_published(business.db, business.ctx, product.id, True)

    assert [shop.slug for shop in marketplace.shops(business.db)] == ["empty-shop"]


# --------------------------------------------------------------------------- #
# Telling the shops
# --------------------------------------------------------------------------- #


def _notices(business, kind: str = "proforma_request"):
    from app.models.system import Notification

    return (
        business.db.query(Notification)
        .filter(
            Notification.tenant_id == business.tenant.id,
            Notification.kind == kind,
        )
        .all()
    )


def test_each_shop_in_a_request_is_told_about_its_own_part(
    db, two_shops, business, other_business
):
    """The fan-out is only worth having if the shops find out about it."""
    first, second = two_shops

    submit_marketplace_request(
        db,
        items=[
            MarketplaceBasketItem(first.variants[0].id, Decimal("2")),
            MarketplaceBasketItem(second.variants[0].id, Decimal("1")),
        ],
        contact_name="Abebe Kebede",
        contact_phone="0911223344",
    )

    for shop in (business, other_business):
        notices = _notices(shop)
        assert len(notices) == 1, "one notice per shop, about its own part"
        assert notices[0].link.startswith("/shop?tab=proformas&open=")


def test_a_marketplace_notice_says_the_shop_is_in_a_race(db, two_shops, business):
    """A notice that reads like a direct request tells a shop to take its
    time, which is exactly wrong when others are pricing the same basket."""
    first, _second = two_shops

    submit_marketplace_request(
        db,
        items=[MarketplaceBasketItem(first.variants[0].id, Decimal("2"))],
        contact_name="Abebe Kebede",
        contact_phone="0911223344",
    )

    notice = _notices(business)[0]
    assert "Marketplace request" in notice.title
    assert "other shops were asked" in (notice.body or "")
    # And still nothing about who they are or what they said.
    assert "Bahir Dar" not in f"{notice.title} {notice.body}"


def test_a_shop_asked_directly_is_not_told_it_is_competing(client, business):
    """The same notice, through the shop's own page, says no such thing."""
    _join_marketplace(business, slug="direct", name="Direct Shop")
    product = _list(business, business.add_product("Teff 25kg", selling_price="2800"))

    response = client.post(
        "/api/v1/public/shops/direct/proforma-requests",
        json={
            "items": [{"variant_id": str(product.variants[0].id), "quantity": "1"}],
            "contact_name": "Abebe Kebede",
            "contact_phone": "0911223344",
        },
    )

    assert response.status_code == 201, response.json()
    notice = _notices(business)[0]
    assert notice.title.startswith("Proforma request")
    assert "other shops" not in (notice.body or "")


def test_a_shop_already_listed_can_bring_its_catalogue_in_later(client, business):
    """The state the switch's own catch-up cannot reach.

    A shop that joined the marketplace before it had a catalogue — or before
    publishing carried a listing with it — never sees the switch go off-to-on
    again, so the products it published in between sit outside.
    """
    store = _store_of(business)
    store.list_on_marketplace = True
    business.db.flush()
    stranded = business.add_product("Teff 25kg")
    stranded.is_published = True  # published without going through set_published
    held_back = business.add_product("Damaged sacks")
    business.db.flush()

    response = client.post(
        "/api/v1/shop/marketplace/list-published", headers=business.headers()
    )

    assert response.status_code == 200, response.json()
    assert response.json() == {"listed": 1}
    business.db.expire(stranded)
    business.db.expire(held_back)
    assert stranded.on_marketplace is True
    assert held_back.on_marketplace is False


def test_a_shop_that_is_not_on_the_marketplace_is_told_so(client, business):
    store = _store_of(business)
    store.list_on_marketplace = False
    business.db.flush()
    product = business.add_product("Teff 25kg")
    product.is_published = True
    business.db.flush()

    response = client.post(
        "/api/v1/shop/marketplace/list-published", headers=business.headers()
    )

    assert response.status_code == 409, response.json()
    assert "not on the marketplace" in response.json()["message"]
    business.db.expire(product)
    assert product.on_marketplace is False


# --------------------------------------------------------------------------- #
# Narrowing the marketplace, and comparing across it
# --------------------------------------------------------------------------- #


def _stock(business, name, price, *, category=None):
    product = business.add_product(
        name, selling_price=price, purchase_price="100", opening_stock="10",
        **({"category_name": category} if category else {}),
    )
    return _list(business, product)


@pytest.fixture
def two_catalogues(business, other_business):
    """Two shops that both sell cement, at different prices."""
    _join_marketplace(business, slug="merkato", name="Merkato Wholesale")
    _join_marketplace(other_business, slug="bole", name="Bole Building")
    _stock(business, "Cement bag 50kg", "1200", category="Building")
    _stock(business, "Sugar 50kg", "4750", category="Grains")
    _stock(other_business, "Cement bag 50kg", "1150", category="Building")
    _stock(other_business, "Roofing sheet", "640", category="Building")
    return business, other_business


def test_the_catalogue_puts_the_same_product_from_two_shops_together(db, two_catalogues):
    """The default order is by name, because comparing is the point."""
    products, _total = marketplace.marketplace_products(db)

    assert [p.name for p in products] == [
        "Cement bag 50kg",
        "Cement bag 50kg",
        "Roofing sheet",
        "Sugar 50kg",
    ]


def test_a_price_window_keeps_only_what_is_inside_it(db, two_catalogues):
    products, total = marketplace.marketplace_products(
        db, min_price=Decimal("700"), max_price=Decimal("1180")
    )

    assert total == 1
    assert [(p.name, str(p.price)) for p in products] == [("Cement bag 50kg", "1150.00")]


def test_sorting_puts_the_cheapest_first_or_last(db, two_catalogues):
    cheap, _ = marketplace.marketplace_products(db, sort="price_low")
    dear, _ = marketplace.marketplace_products(db, sort="price_high")

    assert [str(p.price) for p in cheap] == ["640.00", "1150.00", "1200.00", "4750.00"]
    assert [str(p.price) for p in dear] == ["4750.00", "1200.00", "1150.00", "640.00"]


def test_the_price_range_covers_the_whole_marketplace(db, two_catalogues):
    low, high = marketplace.price_range(db)

    assert (str(low), str(high)) == ("640.00", "4750.00")


def test_a_shop_that_hides_prices_has_nothing_to_filter_on(db, two_catalogues):
    """A price a buyer cannot see cannot be compared, so it is not a price."""
    business, _other = two_catalogues
    store = business.db.query(OnlineStore).filter_by(tenant_id=business.tenant.id).one()
    store.show_prices = False
    db.flush()

    products, _ = marketplace.marketplace_products(db, max_price=Decimal("100000"))

    assert {p.shop.slug for p in products} == {"bole"}, "the hidden ones cannot qualify"


def test_a_product_page_shows_the_same_item_at_another_shop(db, two_catalogues):
    business, other = two_catalogues
    mine = next(
        p for p in marketplace.marketplace_products(db)[0]
        if p.name == "Cement bag 50kg" and p.shop.slug == "merkato"
    )

    related = marketplace.related_elsewhere(db, mine.id)

    assert related, "a marketplace that cannot compare is a list"
    assert related[0].name == "Cement bag 50kg"
    assert related[0].shop.slug == "bole"
    assert all(p.shop.slug != "merkato" for p in related), "never the shop you are on"


def test_a_size_is_not_an_identity(db, two_catalogues):
    """Sugar 50kg is not a kind of cement, however the names read."""
    business, _other = two_catalogues
    sugar = next(
        p for p in marketplace.marketplace_products(db)[0] if p.name == "Sugar 50kg"
    )

    related = marketplace.related_elsewhere(db, sugar.id)

    assert all("Cement" not in p.name for p in related), [p.name for p in related]


def test_related_falls_back_to_the_category(db, two_catalogues):
    """Nobody else sells a roofing sheet, so show what else they do sell."""
    _business, other = two_catalogues
    sheet = next(
        p for p in marketplace.marketplace_products(db)[0] if p.name == "Roofing sheet"
    )

    related = marketplace.related_elsewhere(db, sheet.id)

    assert [p.name for p in related] == ["Cement bag 50kg"]
    assert related[0].shop.slug == "merkato"
