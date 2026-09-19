"""Retries, duplicate submissions and concurrent posting (PRD 20, 21)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.inventory import StockMovement
from app.models.sales import PaymentMethod, Sale
from app.services.inventory import get_balance
from app.services.sales import PaymentInput, SaleInput, SaleLineInput, create_sale


def test_two_sales_with_the_same_idempotency_key_cannot_both_exist(business):
    """The unique constraint is the last line of defence behind the lookup."""
    product = business.add_product("Guarded", selling_price="10", opening_stock="50")
    sale = business.sell(product).sale

    duplicate = Sale(
        tenant_id=business.tenant.id,
        number="S-9999-000001",
        branch_id=business.branch.id,
        location_id=business.location.id,
        status=sale.status,
        sold_at=sale.sold_at,
        subtotal=Decimal("10"),
        total_amount=Decimal("10"),
        idempotency_key="dup-key",
    )
    sale.idempotency_key = "dup-key"
    business.db.add(duplicate)
    with pytest.raises(IntegrityError):
        business.db.flush()


def test_a_second_sale_number_cannot_collide(business):
    product = business.add_product("Numbered", selling_price="10", opening_stock="50")
    first = business.sell(product).sale

    clash = Sale(
        tenant_id=business.tenant.id,
        number=first.number,
        branch_id=business.branch.id,
        location_id=business.location.id,
        status=first.status,
        sold_at=first.sold_at,
        subtotal=Decimal("10"),
        total_amount=Decimal("10"),
    )
    business.db.add(clash)
    with pytest.raises(IntegrityError):
        business.db.flush()


def test_stock_movements_cannot_be_posted_twice_for_one_source(business):
    product = business.add_product("Once only", opening_stock="20")
    movement = (
        business.db.query(StockMovement)
        .filter(StockMovement.variant_id == product.default_variant.id)
        .one()
    )

    duplicate = StockMovement(
        tenant_id=business.tenant.id,
        product_id=movement.product_id,
        variant_id=movement.variant_id,
        location_id=movement.location_id,
        branch_id=movement.branch_id,
        quantity=Decimal("5"),
        balance_after=Decimal("25"),
        reason=movement.reason,
        occurred_at=movement.occurred_at,
        idempotency_key=movement.idempotency_key,
    )
    business.db.add(duplicate)
    with pytest.raises(IntegrityError):
        business.db.flush()


def test_repeated_submissions_of_one_sale_reduce_stock_once(business):
    product = business.add_product("Retried", selling_price="20", opening_stock="30")
    payload = SaleInput(
        lines=[SaleLineInput(variant_id=product.default_variant.id, quantity=Decimal("3"))],
        payments=[PaymentInput(method=PaymentMethod.CASH, amount=Decimal("60"))],
        idempotency_key="one-checkout",
    )
    sales = [create_sale(business.db, business.ctx, payload) for _ in range(5)]

    assert len({result.sale.id for result in sales}) == 1
    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, business.location.id
    ) == Decimal("27.000")
    assert business.db.query(Sale).filter_by(tenant_id=business.tenant.id).count() == 1


def test_sequential_sales_draw_stock_down_correctly(business):
    """Each sale sees the balance the previous one left behind."""
    product = business.add_product("Draining", selling_price="10", opening_stock="10")
    for _ in range(4):
        business.sell(product, quantity="2")
    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, business.location.id
    ) == Decimal("2.000")

    from app.core.errors import InsufficientStock

    with pytest.raises(InsufficientStock):
        business.sell(product, quantity="3")


def test_a_payment_retry_is_recorded_once(business):
    from app.services.credit import record_payment

    customer = business.add_customer("Retry payer")
    product = business.add_product("Credit item", selling_price="1000", opening_stock="10")
    result = business.sell(product, paid="0", customer_id=customer.id)

    key = f"pay-{uuid.uuid4().hex[:8]}"
    payments = [
        record_payment(
            business.db,
            business.ctx,
            result.credit_transaction.id,
            amount=Decimal("250"),
            method=PaymentMethod.CASH,
            idempotency_key=key,
        )
        for _ in range(3)
    ]
    business.db.refresh(result.credit_transaction)

    assert len({p.id for p in payments}) == 1
    assert result.credit_transaction.amount_paid == Decimal("250.00")
    assert result.credit_transaction.balance == Decimal("750.00")
