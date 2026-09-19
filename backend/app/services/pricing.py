"""Landed cost, markup/margin and the pricing-rule hierarchy (PRD 8.2).

The interface may call it "target profit", but every calculation here states
which of markup or gross margin it means, and the suggested price is always
shown before anything is saved.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.models.catalogue import (
    PricingBasis,
    PricingRule,
    PricingScope,
    Product,
    ProductVariant,
)

MONEY_QUANT = Decimal("0.01")
ONE = Decimal("1")


def quantize_money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def landed_cost(
    purchase_price: Decimal | None,
    transport_cost: Decimal | None = None,
    other_costs: Decimal | None = None,
) -> Decimal | None:
    """Purchase cost plus the additional costs attributed to one unit."""
    if purchase_price is None:
        return None
    total = Decimal(purchase_price) + Decimal(transport_cost or 0) + Decimal(other_costs or 0)
    return quantize_money(total)


def allocate_shared_cost(
    shared_cost: Decimal,
    line_weights: list[Decimal],
) -> list[Decimal]:
    """Split a shared cost across lines in proportion to their weights.

    ``line_weights`` is line value for ``by_value`` allocation, or line quantity
    for ``by_quantity``.  Rounding differences land on the largest line so the
    parts always sum back to ``shared_cost`` exactly (PRD 8.2).
    """
    shared_cost = Decimal(shared_cost)
    if shared_cost == 0 or not line_weights:
        return [Decimal("0.00") for _ in line_weights]

    total_weight = sum((Decimal(w) for w in line_weights), Decimal("0"))
    if total_weight <= 0:
        # Nothing to weight by: split evenly.
        even = quantize_money(shared_cost / Decimal(len(line_weights)))
        parts = [even for _ in line_weights]
    else:
        parts = [
            quantize_money(shared_cost * Decimal(w) / total_weight) for w in line_weights
        ]

    drift = quantize_money(shared_cost - sum(parts, Decimal("0.00")))
    if drift != 0:
        largest = max(range(len(parts)), key=lambda i: parts[i])
        parts[largest] = quantize_money(parts[largest] + drift)
    return parts


def price_from_markup(cost: Decimal, rate: Decimal) -> Decimal:
    """``price = cost x (1 + rate)``.  A 25% markup on 100 gives 125."""
    if rate < 0:
        raise ValidationError("Markup cannot be negative")
    return quantize_money(Decimal(cost) * (ONE + Decimal(rate)))


def price_from_margin(cost: Decimal, rate: Decimal) -> Decimal:
    """``price = cost / (1 - rate)``.  A 25% gross margin on 100 gives 133.33."""
    rate = Decimal(rate)
    if rate < 0:
        raise ValidationError("Margin cannot be negative")
    if rate >= ONE:
        raise ValidationError("Gross margin must be below 100%")
    return quantize_money(Decimal(cost) / (ONE - rate))


def suggested_price(
    cost: Decimal,
    basis: PricingBasis,
    rate: Decimal,
    rounding_increment: Decimal | None = None,
) -> Decimal:
    price = (
        price_from_markup(cost, rate)
        if basis == PricingBasis.MARKUP
        else price_from_margin(cost, rate)
    )
    return round_to_increment(price, rounding_increment)


def round_to_increment(value: Decimal, increment: Decimal | None) -> Decimal:
    """Round up to a shop-friendly increment, e.g. the nearest 0.25 or 1 Birr."""
    if not increment or Decimal(increment) <= 0:
        return quantize_money(value)
    increment = Decimal(increment)
    steps = (Decimal(value) / increment).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return quantize_money(steps * increment)


def margin_percent(price: Decimal, cost: Decimal) -> Decimal | None:
    """Gross margin as a fraction of the selling price."""
    price = Decimal(price)
    if price == 0:
        return None
    return ((price - Decimal(cost)) / price).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def markup_percent(price: Decimal, cost: Decimal) -> Decimal | None:
    """Markup as a fraction of cost."""
    cost = Decimal(cost)
    if cost == 0:
        return None
    return ((Decimal(price) - cost) / cost).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@dataclass(slots=True)
class ResolvedPricingRule:
    basis: PricingBasis
    rate: Decimal
    rounding_increment: Decimal | None
    scope: PricingScope
    rule_id: uuid.UUID | None


def resolve_pricing_rule(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    product: Product | None = None,
    category_id: uuid.UUID | None = None,
) -> ResolvedPricingRule | None:
    """Most specific active rule wins: product → category → business (PRD 8.2)."""
    rules = db.execute(
        select(PricingRule).where(
            PricingRule.tenant_id == tenant_id,
            PricingRule.is_active.is_(True),
        )
    ).scalars().all()
    if not rules:
        return None

    product_id = product.id if product else None
    if category_id is None and product is not None:
        category_id = product.category_id

    by_scope: dict[PricingScope, PricingRule] = {}
    for rule in rules:
        if rule.scope == PricingScope.PRODUCT and rule.product_id == product_id and product_id:
            by_scope[PricingScope.PRODUCT] = rule
        elif rule.scope == PricingScope.CATEGORY and rule.category_id == category_id and category_id:
            by_scope[PricingScope.CATEGORY] = rule
        elif rule.scope == PricingScope.BUSINESS:
            by_scope[PricingScope.BUSINESS] = rule

    for scope in (PricingScope.PRODUCT, PricingScope.CATEGORY, PricingScope.BUSINESS):
        rule = by_scope.get(scope)
        if rule is not None:
            return ResolvedPricingRule(
                basis=rule.basis,
                rate=Decimal(rule.rate),
                rounding_increment=(
                    Decimal(rule.rounding_increment) if rule.rounding_increment else None
                ),
                scope=scope,
                rule_id=rule.id,
            )
    return None


def suggest_price_for_variant(
    db: Session, tenant_id: uuid.UUID, variant: ProductVariant
) -> tuple[Decimal | None, ResolvedPricingRule | None]:
    """Suggested selling price for a variant, or ``None`` when cost is unknown."""
    cost = variant.cost_for_valuation
    if cost is None:
        return None, None
    rule = resolve_pricing_rule(db, tenant_id, product=variant.product)
    if rule is None:
        return None, None
    return suggested_price(cost, rule.basis, rule.rate, rule.rounding_increment), rule
