"""Unit tests for landed cost, markup/margin and the pricing hierarchy (PRD 21)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.errors import ValidationError
from app.models.catalogue import PricingBasis, PricingScope
from app.services.pricing import (
    allocate_shared_cost,
    landed_cost,
    margin_percent,
    markup_percent,
    price_from_margin,
    price_from_markup,
    resolve_pricing_rule,
    round_to_increment,
    suggested_price,
)


def test_landed_cost_adds_transport_and_other_costs():
    assert landed_cost(Decimal("100"), Decimal("15"), Decimal("5")) == Decimal("120.00")


def test_landed_cost_is_none_without_a_purchase_price():
    assert landed_cost(None, Decimal("15")) is None


def test_landed_cost_tolerates_missing_extras():
    assert landed_cost(Decimal("100")) == Decimal("100.00")


def test_markup_and_margin_are_different_calculations():
    """The same 25% means two different prices; the system must not confuse them."""
    cost = Decimal("100")
    assert price_from_markup(cost, Decimal("0.25")) == Decimal("125.00")
    assert price_from_margin(cost, Decimal("0.25")) == Decimal("133.33")


def test_margin_of_100_percent_is_rejected():
    with pytest.raises(ValidationError, match="below 100%"):
        price_from_margin(Decimal("100"), Decimal("1"))


def test_negative_rates_are_rejected():
    with pytest.raises(ValidationError):
        price_from_markup(Decimal("100"), Decimal("-0.1"))
    with pytest.raises(ValidationError):
        price_from_margin(Decimal("100"), Decimal("-0.1"))


def test_margin_and_markup_percent_round_trip():
    price = price_from_markup(Decimal("80"), Decimal("0.25"))
    assert markup_percent(price, Decimal("80")) == Decimal("0.2500")
    assert margin_percent(Decimal("100"), Decimal("75")) == Decimal("0.2500")


def test_percentages_are_undefined_at_zero():
    assert markup_percent(Decimal("100"), Decimal("0")) is None
    assert margin_percent(Decimal("0"), Decimal("0")) is None


@pytest.mark.parametrize(
    ("value", "increment", "expected"),
    [
        ("123.40", "1", "123.00"),
        ("123.60", "1", "124.00"),
        ("123.30", "0.25", "123.25"),
        ("123.00", None, "123.00"),
        ("123.456", "0", "123.46"),
    ],
)
def test_round_to_increment(value, increment, expected):
    result = round_to_increment(
        Decimal(value), Decimal(increment) if increment is not None else None
    )
    assert result == Decimal(expected)


def test_suggested_price_applies_rounding():
    price = suggested_price(
        Decimal("60"), PricingBasis.MARKUP, Decimal("0.3"), Decimal("1")
    )
    assert price == Decimal("78.00")


def test_allocate_shared_cost_by_value_sums_exactly():
    parts = allocate_shared_cost(Decimal("100.00"), [Decimal("300"), Decimal("700")])
    assert parts == [Decimal("30.00"), Decimal("70.00")]
    assert sum(parts) == Decimal("100.00")


def test_allocate_shared_cost_absorbs_rounding_drift():
    """Three-way splits of an odd amount must still add back to the total."""
    parts = allocate_shared_cost(Decimal("100.00"), [Decimal("1"), Decimal("1"), Decimal("1")])
    assert sum(parts) == Decimal("100.00")


def test_allocate_shared_cost_splits_evenly_when_weights_are_zero():
    parts = allocate_shared_cost(Decimal("90.00"), [Decimal("0"), Decimal("0")])
    assert parts == [Decimal("45.00"), Decimal("45.00")]


def test_allocate_nothing_when_there_is_no_shared_cost():
    assert allocate_shared_cost(Decimal("0"), [Decimal("5")]) == [Decimal("0.00")]


def test_pricing_rule_hierarchy_prefers_the_most_specific(business):
    """Resolution order is product → category → business (PRD 8.2)."""
    from app.models.catalogue import PricingRule

    db, ctx = business.db, business.ctx
    product = business.add_product("Shoes", category_name="Footwear")
    category_id = product.category_id

    db.add(
        PricingRule(
            tenant_id=ctx.tenant_id,
            scope=PricingScope.BUSINESS,
            basis=PricingBasis.MARKUP,
            rate=Decimal("0.10"),
        )
    )
    db.flush()
    assert resolve_pricing_rule(db, ctx.tenant_id, product=product).scope == PricingScope.BUSINESS

    db.add(
        PricingRule(
            tenant_id=ctx.tenant_id,
            scope=PricingScope.CATEGORY,
            category_id=category_id,
            basis=PricingBasis.MARKUP,
            rate=Decimal("0.20"),
        )
    )
    db.flush()
    resolved = resolve_pricing_rule(db, ctx.tenant_id, product=product)
    assert resolved.scope == PricingScope.CATEGORY
    assert resolved.rate == Decimal("0.2000")

    db.add(
        PricingRule(
            tenant_id=ctx.tenant_id,
            scope=PricingScope.PRODUCT,
            product_id=product.id,
            basis=PricingBasis.MARGIN,
            rate=Decimal("0.30"),
        )
    )
    db.flush()
    resolved = resolve_pricing_rule(db, ctx.tenant_id, product=product)
    assert resolved.scope == PricingScope.PRODUCT
    assert resolved.basis == PricingBasis.MARGIN


def test_no_rule_resolves_to_none(business):
    product = business.add_product("Unpriced")
    assert resolve_pricing_rule(business.db, business.ctx.tenant_id, product=product) is None
