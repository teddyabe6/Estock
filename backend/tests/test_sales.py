"""Sale completion, snapshots, discounts, voids and idempotency (PRD 10, 21)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.errors import (
    ConflictError,
    InsufficientStock,
    PermissionDenied,
    SubscriptionInactive,
    ValidationError,
)
from app.core.permissions import RoleName
from app.models.credit import CreditStatus
from app.models.inventory import MovementReason, StockMovement
from app.models.platform import TenantStatus
from app.models.sales import PaymentMethod, Sale, SaleStatus
from app.services.inventory import get_balance
from app.services.sales import (
    PaymentInput,
    SaleInput,
    SaleLineInput,
    create_sale,
    void_sale,
)


def test_a_cash_sale_posts_lines_stock_and_payment_together(business):
    product = business.add_product("Bread", selling_price="25.00", opening_stock="100")
    result = business.sell(product, quantity="4")
    sale = result.sale

    assert sale.status == SaleStatus.COMPLETED
    assert sale.total_amount == Decimal("100.00")
    assert sale.amount_paid == Decimal("100.00")
    assert sale.balance_due == Decimal("0.00")
    assert len(sale.lines) == 1
    assert len(sale.payments) == 1
    assert result.credit_transaction is None

    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, business.location.id
    ) == Decimal("96.000")

    movement = (
        business.db.query(StockMovement)
        .filter(StockMovement.reason == MovementReason.SALE)
        .one()
    )
    assert movement.source_type == "sale"
    assert movement.source_id == sale.id


def test_sale_numbers_are_sequential_within_a_business(business):
    product = business.add_product("Bread", opening_stock="100")
    first = business.sell(product).sale
    second = business.sell(product).sale
    assert first.number.endswith("000001")
    assert second.number.endswith("000002")


def test_sale_snapshots_price_and_cost_so_later_edits_do_not_rewrite_history(business):
    """Editing the catalogue must never change what a past sale recorded (PRD 8.2)."""
    product = business.add_product(
        "Shirt", selling_price="200.00", purchase_price="120.00", opening_stock="10"
    )
    sale = business.sell(product, quantity="2").sale

    variant = product.default_variant
    variant.selling_price = Decimal("300.00")
    variant.purchase_price = Decimal("150.00")
    variant.average_cost = Decimal("150.00")
    business.db.flush()

    business.db.refresh(sale)
    assert sale.lines[0].unit_price == Decimal("200.00")
    assert sale.lines[0].unit_cost == Decimal("120.00")
    assert sale.total_amount == Decimal("400.00")
    assert sale.cost_total == Decimal("240.00")
    assert sale.gross_profit == Decimal("160.00")


def test_selling_more_than_available_is_refused(business):
    product = business.add_product("Scarce", opening_stock="2")
    with pytest.raises(InsufficientStock):
        business.sell(product, quantity="5")


def test_nothing_is_posted_when_a_sale_line_fails(business):
    """A sale is one consistent operation: a failure leaves no partial effect."""
    plenty = business.add_product("Plenty", selling_price="10", opening_stock="100")
    scarce = business.add_product("Scarce", selling_price="10", opening_stock="1")

    savepoint = business.db.begin_nested()
    with pytest.raises(InsufficientStock):
        create_sale(
            business.db,
            business.ctx,
            SaleInput(
                lines=[
                    SaleLineInput(variant_id=plenty.default_variant.id, quantity=Decimal("2")),
                    SaleLineInput(variant_id=scarce.default_variant.id, quantity=Decimal("5")),
                ],
            ),
        )
    # The request handler rolls the transaction back; the first line's stock
    # reduction goes with it, leaving no half-posted sale behind.
    savepoint.rollback()

    assert get_balance(
        business.db, business.tenant.id, plenty.default_variant.id, business.location.id
    ) == Decimal("100.000")
    assert get_balance(
        business.db, business.tenant.id, scarce.default_variant.id, business.location.id
    ) == Decimal("1.000")
    assert business.db.query(Sale).count() == 0


def test_line_discount_by_percentage(business):
    product = business.add_product("Jacket", selling_price="1000.00", opening_stock="5")
    result = create_sale(
        business.db,
        business.ctx,
        SaleInput(
            lines=[
                SaleLineInput(
                    variant_id=product.default_variant.id,
                    quantity=Decimal("1"),
                    discount_percent=Decimal("0.10"),
                )
            ],
            payments=[PaymentInput(method=PaymentMethod.CASH, amount=Decimal("900.00"))],
        ),
    )
    assert result.sale.discount_total == Decimal("100.00")
    assert result.sale.total_amount == Decimal("900.00")


def test_a_discount_larger_than_the_line_is_refused(business):
    product = business.add_product("Jacket", selling_price="100.00", opening_stock="5")
    with pytest.raises(ValidationError, match="cannot exceed"):
        create_sale(
            business.db,
            business.ctx,
            SaleInput(
                lines=[
                    SaleLineInput(
                        variant_id=product.default_variant.id,
                        quantity=Decimal("1"),
                        discount_amount=Decimal("200"),
                    )
                ]
            ),
        )


def test_discount_above_the_product_cap_needs_approval(business):
    """Role-based discount limits are enforced at sale time (PRD 10)."""
    product = business.add_product("Capped", selling_price="100.00", opening_stock="10")
    product.default_variant.max_discount_percent = Decimal("0.05")
    business.db.flush()

    _, salesperson_ctx = business.add_user(RoleName.SALESPERSON)
    with pytest.raises(PermissionDenied, match="ask a manager"):
        create_sale(
            business.db,
            salesperson_ctx,
            SaleInput(
                lines=[
                    SaleLineInput(
                        variant_id=product.default_variant.id,
                        quantity=Decimal("1"),
                        discount_percent=Decimal("0.20"),
                    )
                ]
            ),
        )

    # The owner holds discount:approve, so the same sale goes through.
    result = create_sale(
        business.db,
        business.ctx,
        SaleInput(
            lines=[
                SaleLineInput(
                    variant_id=product.default_variant.id,
                    quantity=Decimal("1"),
                    discount_percent=Decimal("0.20"),
                )
            ],
            payments=[PaymentInput(method=PaymentMethod.CASH, amount=Decimal("80.00"))],
        ),
    )
    assert result.sale.lines[0].discount_approved_by_id == business.owner.id


def test_tax_is_applied_after_the_discount(business):
    product = business.add_product("Taxed", selling_price="100.00", opening_stock="10")
    product.default_variant.tax_rate = Decimal("0.15")
    business.db.flush()

    result = create_sale(
        business.db,
        business.ctx,
        SaleInput(
            lines=[
                SaleLineInput(
                    variant_id=product.default_variant.id,
                    quantity=Decimal("1"),
                    discount_amount=Decimal("20"),
                )
            ],
            payments=[PaymentInput(method=PaymentMethod.CASH, amount=Decimal("92.00"))],
        ),
    )
    # (100 - 20) * 15% = 12.00
    assert result.sale.tax_total == Decimal("12.00")
    assert result.sale.total_amount == Decimal("92.00")


def test_split_payment_across_methods(business):
    product = business.add_product("Split", selling_price="500.00", opening_stock="10")
    result = create_sale(
        business.db,
        business.ctx,
        SaleInput(
            lines=[SaleLineInput(variant_id=product.default_variant.id, quantity=Decimal("1"))],
            payments=[
                PaymentInput(method=PaymentMethod.CASH, amount=Decimal("200.00")),
                PaymentInput(method=PaymentMethod.TELEBIRR, amount=Decimal("300.00")),
            ],
        ),
    )
    assert result.sale.amount_paid == Decimal("500.00")
    assert result.credit_transaction is None
    assert {str(p.method) for p in result.sale.payments} == {"cash", "telebirr"}


def test_paying_more_than_the_total_is_refused(business):
    product = business.add_product("Overpaid", selling_price="100.00", opening_stock="10")
    with pytest.raises(ValidationError, match="exceed"):
        business.sell(product, quantity="1", paid="150")


def test_an_empty_sale_is_refused(business):
    with pytest.raises(ValidationError, match="at least one product"):
        create_sale(business.db, business.ctx, SaleInput(lines=[]))


def test_idempotency_key_returns_the_same_sale_on_retry(business):
    """A retried submission must not post a second sale (PRD 20, 21)."""
    product = business.add_product("Retry", selling_price="50.00", opening_stock="20")
    payload = SaleInput(
        lines=[SaleLineInput(variant_id=product.default_variant.id, quantity=Decimal("2"))],
        payments=[PaymentInput(method=PaymentMethod.CASH, amount=Decimal("100.00"))],
        idempotency_key="checkout-abc-123",
    )
    first = create_sale(business.db, business.ctx, payload)
    second = create_sale(business.db, business.ctx, payload)

    assert first.sale.id == second.sale.id
    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, business.location.id
    ) == Decimal("18.000")


def test_voiding_a_sale_restores_stock_and_keeps_history(business):
    """Nothing is deleted; the reversal is a compensating movement (PRD 1)."""
    product = business.add_product("Returned", selling_price="80.00", opening_stock="10")
    sale = business.sell(product, quantity="3").sale

    voided = void_sale(business.db, business.ctx, sale.id, reason="Customer changed their mind")

    assert voided.status == SaleStatus.VOIDED
    assert voided.void_reason == "Customer changed their mind"
    assert voided.total_amount == Decimal("240.00")  # the record is preserved
    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, business.location.id
    ) == Decimal("10.000")

    reasons = [
        m.reason
        for m in business.db.query(StockMovement)
        .filter(StockMovement.product_id == product.id)
        .all()
    ]
    assert MovementReason.SALE in reasons
    assert MovementReason.SALE_VOID in reasons


def test_voiding_twice_is_refused(business):
    product = business.add_product("Returned", opening_stock="10")
    sale = business.sell(product).sale
    void_sale(business.db, business.ctx, sale.id, reason="Mistake")
    with pytest.raises(ConflictError, match="already voided"):
        void_sale(business.db, business.ctx, sale.id, reason="Mistake again")


def test_voiding_requires_a_reason(business):
    product = business.add_product("Returned", opening_stock="10")
    sale = business.sell(product).sale
    with pytest.raises(ValidationError, match="reason is required"):
        void_sale(business.db, business.ctx, sale.id, reason="")


def test_voiding_a_credit_sale_cancels_its_receivable(business):
    customer = business.add_customer("Abebe")
    product = business.add_product("On credit", selling_price="500.00", opening_stock="10")
    result = business.sell(product, quantity="1", paid="0", customer_id=customer.id)
    assert result.credit_transaction is not None

    void_sale(business.db, business.ctx, result.sale.id, reason="Entered by mistake")
    business.db.refresh(result.credit_transaction)
    assert result.credit_transaction.status == CreditStatus.CANCELLED


def test_a_read_only_account_cannot_record_a_sale(business):
    """A lapsed trial blocks new posting but never touches data (PRD 17)."""
    product = business.add_product("Blocked", opening_stock="10")
    business.tenant.status = TenantStatus.RESTRICTED
    business.db.flush()

    with pytest.raises(SubscriptionInactive, match="read-only"):
        business.sell(product)


def test_a_service_product_sells_without_touching_stock(business):
    product = business.add_product(
        "Delivery service", selling_price="50.00", opening_stock=None, track_stock=False
    )
    result = business.sell(product, quantity="1")
    assert result.sale.total_amount == Decimal("50.00")
    assert (
        business.db.query(StockMovement)
        .filter(StockMovement.product_id == product.id)
        .count()
        == 0
    )
