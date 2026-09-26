"""Retries, duplicate submissions and concurrent posting (PRD 20, 21)."""

from __future__ import annotations

import os
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db import utcnow
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


# --------------------------------------------------------------------------- #
# Document numbering (PRD 20, 21)
# --------------------------------------------------------------------------- #


def test_document_numbers_come_from_a_locked_sequence(business):
    """Numbers are handed out by a per-business sequence row, not by counting."""
    from app.models.sequences import DocumentSequence

    product = business.add_product("Numbered", selling_price="10", opening_stock="50")
    business.sell(product)
    business.sell(product)

    sequence = (
        business.db.query(DocumentSequence)
        .filter_by(tenant_id=business.tenant.id, kind="sale")
        .one()
    )
    assert sequence.last_number == 2


def test_numbering_continues_from_documents_that_already_exist(business):
    """An upgraded database keeps counting from its highest existing number."""
    from app.services.numbering import next_number, prefix_for

    prefix = prefix_for("sale")
    existing = Sale(
        tenant_id=business.tenant.id,
        number=f"{prefix}000041",
        branch_id=business.branch.id,
        location_id=business.location.id,
        status="completed",
        sold_at=utcnow(),
        subtotal=Decimal("10"),
        total_amount=Decimal("10"),
    )
    business.db.add(existing)
    business.db.flush()

    assert next_number(business.db, Sale, business.tenant.id, "sale") == f"{prefix}000042"


def test_a_voided_sale_keeps_its_number(business):
    """Voiding never frees a number for reuse; history stays traceable."""
    from app.services.sales import void_sale

    product = business.add_product("Numbered", selling_price="10", opening_stock="50")
    first = business.sell(product).sale
    void_sale(business.db, business.ctx, first.id, reason="Mistake")
    second = business.sell(product).sale
    assert first.number != second.number
    assert second.number.endswith("000002")


@pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL", "sqlite://").startswith("sqlite"),
    reason="row locking needs PostgreSQL",
)
def test_concurrent_numbering_serialises_on_postgresql(engine):
    """Two transactions asking for a number at once get consecutive numbers.

    Session B blocks on A's row lock and only proceeds once A commits, so it
    reads A's increment instead of computing the same number.
    """
    import threading

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from app.services.numbering import next_number
    from app.services.onboarding import register_business

    url = os.environ["TEST_DATABASE_URL"]
    setup = create_engine(url)
    with Session(setup) as session:
        tenant_id = register_business(
            session,
            business_name="Race Traders",
            full_name="Owner",
            email=f"race-{uuid.uuid4().hex[:6]}@example.com",
            password="test-password-123",
        ).tenant.id
        session.commit()

    results: dict[str, str] = {}
    b_started = threading.Event()
    a_done = threading.Event()

    def worker_a():
        with Session(setup) as session:
            results["a"] = next_number(session, Sale, tenant_id, "sale")
            b_started.wait(timeout=5)
            # Hold the lock long enough for B to be waiting on it.
            threading.Event().wait(0.3)
            session.commit()
            a_done.set()

    def worker_b():
        with Session(setup) as session:
            b_started.set()
            results["b"] = next_number(session, Sale, tenant_id, "sale")
            results["b_after_a"] = str(a_done.is_set())
            session.commit()

    try:
        threads = [threading.Thread(target=worker_a), threading.Thread(target=worker_b)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        year = date.today().year
        assert {results["a"], results["b"]} == {f"S-{year}-000001", f"S-{year}-000002"}
        assert results["b_after_a"] == "True", "B must wait for A's lock"
    finally:
        with setup.connect() as connection:
            connection.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": tenant_id})
            connection.commit()
        setup.dispose()
