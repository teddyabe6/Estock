"""Query counts for operations that post one movement per line.

A sale, purchase, transfer or count posts one stock movement per line, and
every posting needs the line's variant and the operation's location.  Looking
those up inside the loop made the query count grow several times faster than
the number of lines — invisible in a test that only checks the result, and
paid for on every multi-line sale at the till.

These tests pin the shape rather than an absolute number: adding lines may
add the writes a line genuinely needs, but it must not add another lookup of
the catalogue or the location.  An absolute budget would break on any
unrelated query change and teach people to raise the number.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import event

from app.models.sales import PaymentMethod
from app.services.inventory import create_transfer, dispatch_transfer, post_count
from app.services.purchasing import PurchaseInput, PurchaseLineInput, receive_purchase
from app.services.sales import PaymentInput, SaleInput, SaleLineInput, create_sale


class Counted:
    """SQL issued while the block runs, grouped by the table read or written."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def matching(self, fragment: str) -> int:
        return sum(1 for s in self.statements if fragment in s)

    @property
    def total(self) -> int:
        return len(self.statements)


@pytest.fixture
def counted(engine):
    counter = Counted()
    recording = {"on": False}

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if recording["on"]:
            counter.statements.append(" ".join(statement.split()))

    def start():
        counter.statements.clear()
        recording["on"] = True
        return counter

    yield start
    recording["on"] = False
    event.remove(engine, "before_cursor_execute", _record)


def _products(business, count: int):
    return [
        business.add_product(
            f"Item {i}", selling_price="100", purchase_price="60", opening_stock="500"
        )
        for i in range(count)
    ]


def _sell(business, products):
    return create_sale(
        business.db,
        business.ctx,
        SaleInput(
            lines=[
                SaleLineInput(variant_id=p.default_variant.id, quantity=Decimal("1"))
                for p in products
            ],
            payments=[
                PaymentInput(method=PaymentMethod.CASH, amount=Decimal(100 * len(products)))
            ],
        ),
    )


def test_a_sale_looks_up_its_catalogue_once_however_many_lines(business, counted):
    """Ten lines must not mean ten trips to product_variants."""
    one = _products(business, 1)
    many = _products(business, 10)

    counter = counted()
    _sell(business, one)
    business.db.flush()
    single_line_lookups = counter.matching("FROM product_variants")

    counter = counted()
    _sell(business, many)
    business.db.flush()
    ten_line_lookups = counter.matching("FROM product_variants")

    assert single_line_lookups <= 1
    assert ten_line_lookups <= single_line_lookups, (
        f"a ten-line sale read product_variants {ten_line_lookups} times, "
        f"a one-line sale {single_line_lookups}"
    )


def test_a_sale_does_not_reread_its_location_per_line(business, counted):
    products = _products(business, 10)
    counter = counted()
    _sell(business, products)
    business.db.flush()
    assert counter.matching("FROM stock_locations") <= 2, counter.matching("FROM stock_locations")


def test_a_sale_does_not_lazy_load_each_products_row(business, counted):
    """``track_stock`` and ``is_active`` live on the product, so every line
    touches it; the batched variant query joins it rather than lazy-loading
    one row per line.

    The session is expired first on purpose.  A real request starts with a
    cold session, and leaving the catalogue warm from the fixture would make
    this pass whether or not the join is there.  The variant ids are read
    *before* expiring, because reading them afterwards would refresh each
    object one at a time and the test would be measuring its own setup.
    """
    products = _products(business, 10)
    variant_ids = [product.default_variant.id for product in products]
    business.db.flush()
    business.db.expire_all()

    counter = counted()
    create_sale(
        business.db,
        business.ctx,
        SaleInput(
            lines=[
                SaleLineInput(variant_id=variant_id, quantity=Decimal("1"))
                for variant_id in variant_ids
            ],
            payments=[
                PaymentInput(method=PaymentMethod.CASH, amount=Decimal(100 * len(variant_ids)))
            ],
        ),
    )
    business.db.flush()
    assert counter.matching("FROM products") == 0, (
        f"the sale lazy-loaded products {counter.matching('FROM products')} times"
    )


def test_receiving_a_purchase_looks_up_its_catalogue_once(business, counted):
    products = _products(business, 10)
    supplier = business.add_supplier()

    counter = counted()
    receive_purchase(
        business.db,
        business.ctx,
        PurchaseInput(
            lines=[
                PurchaseLineInput(
                    variant_id=p.default_variant.id,
                    quantity=Decimal("1"),
                    unit_cost=Decimal("60"),
                )
                for p in products
            ],
            supplier_id=supplier.id,
            transport_cost=Decimal("100"),
        ),
    )
    business.db.flush()
    assert counter.matching("FROM product_variants") <= 1
    # The movement reports the balance it saw, so there is no second read of it
    # just to work out the weighted average cost.
    assert counter.matching("SELECT stock_balances.quantity") == 0


def test_drafting_a_transfer_is_flat_in_the_number_of_lines(business, counted):
    few = _products(business, 1)
    lots = _products(business, 20)
    destination, _ = business.add_branch("Warehouse")
    to_location = (
        business.db.query(type(business.location))
        .filter_by(branch_id=destination.id)
        .one()
    )

    counter = counted()
    create_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=to_location.id,
        lines=[(p.default_variant.id, Decimal("1")) for p in few],
    )
    business.db.flush()
    one_line = counter.total

    counter = counted()
    create_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=to_location.id,
        lines=[(p.default_variant.id, Decimal("1")) for p in lots],
    )
    business.db.flush()
    twenty_lines = counter.total

    # Not equality: the first transfer of the year also creates the numbering
    # row, so it costs a little more.  What matters is that twenty lines cost
    # no more than one.
    assert twenty_lines <= one_line, (
        f"drafting a 20-line transfer took {twenty_lines} queries against "
        f"{one_line} for a single line; it should not grow with the lines"
    )


def test_dispatching_a_transfer_looks_up_its_catalogue_once(business, counted):
    products = _products(business, 10)
    destination, _ = business.add_branch("Warehouse")
    to_location = (
        business.db.query(type(business.location))
        .filter_by(branch_id=destination.id)
        .one()
    )
    transfer = create_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=to_location.id,
        lines=[(p.default_variant.id, Decimal("1")) for p in products],
    )
    business.db.flush()

    counter = counted()
    dispatch_transfer(business.db, business.ctx, transfer.id)
    business.db.flush()
    assert counter.matching("FROM product_variants") <= 1
    assert counter.matching("FROM stock_locations") <= 1


def test_posting_a_count_looks_up_its_catalogue_once(business, counted):
    from app.services.inventory import record_count_line, start_count

    products = _products(business, 10)
    count = start_count(business.db, business.ctx, location_id=business.location.id)
    business.db.flush()
    for product in products:
        record_count_line(
            business.db,
            business.ctx,
            count.id,
            variant_id=product.default_variant.id,
            counted_quantity=Decimal("499"),
        )
    business.db.flush()

    counter = counted()
    post_count(business.db, business.ctx, count.id)
    business.db.flush()
    assert counter.matching("FROM product_variants") <= 1
    assert counter.matching("FROM stock_locations") <= 1
