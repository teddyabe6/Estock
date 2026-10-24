"""Returns and refunds (PRD 1, 10).

A sale could only ever be voided in full.  A customer bringing back two of
five bags needed a return, and the decisions register listed refunds as still
to be designed.

The design these tests pin:

* A return is its own document.  The sale keeps the prices, discounts, tax and
  cost snapshots it was agreed at; nothing rewrites it.
* Value is carried from the sale's own line, never recomputed from the
  catalogue — which may have moved since.
* Returning a line in two goes gives back exactly what returning it in one
  would: the last return of a line takes the remainder, so no cent is lost to
  rounding.
* Goods come back on the stock ledger.  Goods not fit to sell again come back
  and are then written off, so the damage is a movement with a reason rather
  than a silent absence.
* A customer who still owes on the sale is not handed cash: the return comes
  off what they owe first.  A refund can never exceed what was actually taken.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest

from app.core.errors import ConflictError, PermissionDenied, ValidationError
from app.core.permissions import Permission, RoleName
from app.models.credit import CreditStatus, CreditTransaction
from app.models.inventory import MovementReason, StockMovement
from app.models.sales import PaymentDirection, PaymentMethod, RefundMethod
from app.services.credit import cancel_transaction, record_payment
from app.services.inventory import get_balance
from app.services.sales import (
    PaymentInput,
    ReturnLineInput,
    SaleInput,
    SaleLineInput,
    SaleReturnInput,
    create_sale,
    create_sale_return,
    returnable,
    void_sale,
)


def _sell(business, product, quantity="5", unit_price=None, paid=None, **kwargs):
    """A sale of one product, paid in full in cash unless told otherwise."""
    variant = product.default_variant
    total = Decimal(unit_price or variant.selling_price) * Decimal(quantity)
    payments = []
    if paid is None:
        payments = [PaymentInput(method=PaymentMethod.CASH, amount=total)]
    elif Decimal(paid) > 0:
        payments = [PaymentInput(method=PaymentMethod.CASH, amount=Decimal(paid))]
    return create_sale(
        business.db,
        business.ctx,
        SaleInput(
            lines=[SaleLineInput(variant_id=variant.id, quantity=Decimal(quantity))],
            payments=payments,
            **kwargs,
        ),
    )


def _return(business, sale, line_index=0, quantity="1", reason="Customer changed their mind", **kwargs):
    return create_sale_return(
        business.db,
        business.ctx,
        sale.id,
        SaleReturnInput(
            lines=[
                ReturnLineInput(
                    sale_line_id=sale.lines[line_index].id, quantity=Decimal(quantity), **kwargs
                )
            ],
            reason=reason,
        ),
    )


def _movements(business, variant_id, reason):
    return (
        business.db.query(StockMovement)
        .filter(
            StockMovement.tenant_id == business.tenant.id,
            StockMovement.variant_id == variant_id,
            StockMovement.reason == reason,
        )
        .all()
    )


# --------------------------------------------------------------------------- #
# Goods and value
# --------------------------------------------------------------------------- #


def test_a_partial_return_puts_back_only_what_came_back(business):
    product = business.add_product("Teff 25kg", selling_price="100", purchase_price="60",
                                   opening_stock="10")
    variant = product.default_variant
    sale = _sell(business, product, quantity="5").sale
    assert get_balance(business.db, business.tenant.id, variant.id, business.location.id) == Decimal("5.000")

    returned = _return(business, sale, quantity="2")
    business.db.flush()

    assert returned.number.startswith("SR-")
    assert returned.total_amount == Decimal("200.00")
    assert get_balance(
        business.db, business.tenant.id, variant.id, business.location.id
    ) == Decimal("7.000")
    assert len(_movements(business, variant.id, MovementReason.SALE_RETURN)) == 1


def test_the_sale_itself_is_not_rewritten(business):
    """History stays true; the return is a separate document (PRD 1)."""
    product = business.add_product("Teff", selling_price="100", purchase_price="60",
                                   opening_stock="10")
    sale = _sell(business, product, quantity="5").sale
    original_total = sale.total_amount
    original_quantity = sale.lines[0].quantity

    _return(business, sale, quantity="2")
    business.db.flush()

    assert sale.total_amount == original_total
    assert sale.lines[0].quantity == original_quantity
    assert sale.status == "completed"
    # What the customer is now liable for is derived, not stored on the sale.
    assert sale.returned_total == Decimal("200.00")
    assert sale.effective_total == Decimal("300.00")


def test_value_comes_from_the_sale_not_the_current_price(business):
    """The catalogue may have moved since; the customer paid the old price."""
    product = business.add_product("Teff", selling_price="100", purchase_price="60",
                                   opening_stock="10")
    sale = _sell(business, product, quantity="2").sale

    product.default_variant.selling_price = Decimal("250.00")
    business.db.flush()

    returned = _return(business, sale, quantity="2")
    assert returned.total_amount == Decimal("200.00")
    assert returned.lines[0].unit_price == Decimal("100.00")


def test_returning_more_than_was_sold_is_refused(business):
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    sale = _sell(business, product, quantity="3").sale

    with pytest.raises(ValidationError) as refused:
        _return(business, sale, quantity="4")

    assert refused.value.code == "return_exceeds_sold"
    assert refused.value.details["returnable"] == "3.000"


def test_returns_accumulate_against_the_quantity_sold(business):
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    sale = _sell(business, product, quantity="3").sale

    _return(business, sale, quantity="2")
    business.db.flush()
    with pytest.raises(ValidationError):
        _return(business, sale, quantity="2")

    _return(business, sale, quantity="1")  # the last one is allowed
    business.db.flush()
    assert sale.returned_total == Decimal("300.00")


def test_returnable_reports_what_is_left(business):
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    sale = _sell(business, product, quantity="5").sale
    _return(business, sale, quantity="2")
    business.db.flush()

    lines = returnable(business.db, business.ctx, sale.id)
    assert lines[0]["quantity_sold"] == "5.000"
    assert lines[0]["quantity_returned"] == "2.000"
    assert lines[0]["quantity_returnable"] == "3.000"


# --------------------------------------------------------------------------- #
# Rounding
# --------------------------------------------------------------------------- #


def test_returning_a_line_in_two_goes_gives_back_the_same_total(business):
    """The last return of a line takes the remainder, so no cent is lost.

    Three units with a discount that does not divide by three is the case
    where pro-rata alone would lose a cent.
    """
    product = business.add_product("Teff", selling_price="100", purchase_price="60",
                                   opening_stock="10")
    sale = create_sale(
        business.db,
        business.ctx,
        SaleInput(
            lines=[
                SaleLineInput(
                    variant_id=product.default_variant.id,
                    quantity=Decimal("3"),
                    discount_amount=Decimal("10.00"),  # 3.333... a unit
                )
            ],
            payments=[PaymentInput(method=PaymentMethod.CASH, amount=Decimal("290.00"))],
        ),
    ).sale
    line_total = sale.lines[0].line_total

    first = _return(business, sale, quantity="1")
    business.db.flush()
    second = _return(business, sale, quantity="2")
    business.db.flush()

    assert first.total_amount + second.total_amount == line_total
    assert (
        first.discount_total + second.discount_total == sale.lines[0].discount_amount
    )


# --------------------------------------------------------------------------- #
# Damaged goods
# --------------------------------------------------------------------------- #


def test_goods_not_fit_to_sell_come_back_and_are_written_off(business):
    """Visible as a loss on the ledger, not a silent absence.

    This follows the choice already made for transfer shortfalls: a
    discrepancy gets a movement with a reason, an actor and a timestamp.
    """
    product = business.add_product("Teff", selling_price="100", purchase_price="60",
                                   opening_stock="10")
    variant = product.default_variant
    sale = _sell(business, product, quantity="5").sale
    before = get_balance(business.db, business.tenant.id, variant.id, business.location.id)

    returned = _return(business, sale, quantity="2", restock=False, reason="Torn sacks")
    business.db.flush()

    # Stock is unchanged: it came back, then went out as a loss.
    assert get_balance(
        business.db, business.tenant.id, variant.id, business.location.id
    ) == before
    assert len(_movements(business, variant.id, MovementReason.SALE_RETURN)) == 1
    losses = _movements(business, variant.id, MovementReason.LOSS)
    assert len(losses) == 1
    assert losses[0].quantity == Decimal("-2.000")
    assert "Torn sacks" in losses[0].note
    # The customer is still owed for them.
    assert returned.total_amount == Decimal("200.00")
    assert returned.lines[0].restock is False


# --------------------------------------------------------------------------- #
# Money
# --------------------------------------------------------------------------- #


def test_a_paid_sale_refunds_cash(business):
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    sale = _sell(business, product, quantity="5").sale
    assert sale.amount_paid == Decimal("500.00")

    returned = _return(business, sale, quantity="2")
    business.db.flush()

    assert returned.refund_method == RefundMethod.CASH
    assert returned.refunded_amount == Decimal("200.00")
    assert returned.credited_amount == Decimal("0.00")
    # Money out, not money in.
    refunds = [p for p in sale.payments if p.direction == PaymentDirection.OUT]
    assert len(refunds) == 1
    assert refunds[0].amount == Decimal("200.00")
    # The sale is square: kept 300, took 500, gave 200 back.
    assert sale.amount_paid == Decimal("300.00")
    assert sale.effective_total == Decimal("300.00")
    assert sale.balance_due == Decimal("0.00")


def test_an_unpaid_credit_sale_is_credited_not_refunded(business):
    """Handing cash to someone who still owes you would be paying them twice."""
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    customer = business.add_customer("Abebe")
    sale = _sell(business, product, quantity="5", paid=0, customer_id=customer.id).sale
    receivable = business.db.query(CreditTransaction).filter_by(sale_id=sale.id).one()
    assert receivable.balance == Decimal("500.00")

    returned = _return(business, sale, quantity="2")
    business.db.flush()

    assert returned.refund_method == RefundMethod.CREDIT
    assert returned.credited_amount == Decimal("200.00")
    assert returned.refunded_amount == Decimal("0.00")
    assert receivable.balance == Decimal("300.00")
    # No money left the till.
    assert not [p for p in sale.payments if p.direction == PaymentDirection.OUT]


def test_a_part_paid_credit_sale_clears_the_balance_first(business):
    """200 owed and 300 paid: a full return cancels the debt, then refunds 300."""
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    customer = business.add_customer("Abebe")
    sale = _sell(business, product, quantity="5", paid="300", customer_id=customer.id).sale
    receivable = business.db.query(CreditTransaction).filter_by(sale_id=sale.id).one()
    assert receivable.balance == Decimal("200.00")

    returned = _return(business, sale, quantity="5")
    business.db.flush()

    assert returned.refund_method == RefundMethod.MIXED
    assert returned.credited_amount == Decimal("200.00")
    assert returned.refunded_amount == Decimal("300.00")
    assert receivable.balance == Decimal("0.00")
    assert receivable.status == CreditStatus.PAID
    assert sale.balance_due == Decimal("0.00")


def test_a_refund_never_exceeds_what_was_taken(business):
    """The business cannot pay back money it never received."""
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    customer = business.add_customer("Abebe")
    sale = _sell(business, product, quantity="5", paid=0, customer_id=customer.id).sale

    returned = _return(business, sale, quantity="5")
    business.db.flush()

    assert returned.credited_amount == Decimal("500.00")
    assert returned.refunded_amount == Decimal("0.00")


def test_a_refund_follows_the_method_the_customer_paid_with(business):
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    sale = create_sale(
        business.db,
        business.ctx,
        SaleInput(
            lines=[SaleLineInput(variant_id=product.default_variant.id, quantity=Decimal("2"))],
            payments=[PaymentInput(method=PaymentMethod.TELEBIRR, amount=Decimal("200.00"))],
        ),
    ).sale

    _return(business, sale, quantity="2")
    business.db.flush()

    refund = next(p for p in sale.payments if p.direction == PaymentDirection.OUT)
    assert refund.method == PaymentMethod.TELEBIRR


def test_a_credit_note_is_not_counted_as_money_through_the_till(business):
    """It settles a receivable; it is not cash, and reports must tell them apart."""
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    customer = business.add_customer("Abebe")
    sale = _sell(business, product, quantity="5", paid=0, customer_id=customer.id).sale
    receivable = business.db.query(CreditTransaction).filter_by(sale_id=sale.id).one()

    _return(business, sale, quantity="2")
    business.db.flush()

    notes = [p for p in receivable.payments if p.method == PaymentMethod.CREDIT_NOTE]
    assert len(notes) == 1
    # Deliberately not linked to the sale: the sale's balance already falls by
    # the returned value, and counting it twice would look like overpayment.
    assert notes[0].sale_id is None
    assert sale.amount_paid == Decimal("0.00")


def test_a_later_payment_on_a_reduced_balance_still_works(business):
    """The receivable must behave normally after a return touched it."""
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    customer = business.add_customer("Abebe")
    sale = _sell(business, product, quantity="5", paid=0, customer_id=customer.id).sale
    receivable = business.db.query(CreditTransaction).filter_by(sale_id=sale.id).one()

    _return(business, sale, quantity="2")
    business.db.flush()
    assert receivable.balance == Decimal("300.00")

    record_payment(
        business.db,
        business.ctx,
        receivable.id,
        amount=Decimal("300.00"),
        method=PaymentMethod.CASH,
    )
    business.db.flush()
    assert receivable.balance == Decimal("0.00")
    assert receivable.status == CreditStatus.PAID


def test_overpaying_a_balance_a_return_reduced_is_still_refused(business):
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    customer = business.add_customer("Abebe")
    sale = _sell(business, product, quantity="5", paid=0, customer_id=customer.id).sale
    receivable = business.db.query(CreditTransaction).filter_by(sale_id=sale.id).one()
    _return(business, sale, quantity="2")
    business.db.flush()

    with pytest.raises(ValidationError):
        record_payment(
            business.db,
            business.ctx,
            receivable.id,
            amount=Decimal("301.00"),
            method=PaymentMethod.CASH,
        )


def test_a_written_off_debt_gives_the_goods_back_but_not_money(business):
    """The shop never took the money, so it does not owe any back.

    Reached by cancelling the receivable — writing the debt off — and then
    taking the goods back.  The return is still recorded, with nothing moved.
    """
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    customer = business.add_customer("Abebe")
    sale = _sell(business, product, quantity="5", paid=0, customer_id=customer.id).sale
    receivable = business.db.query(CreditTransaction).filter_by(sale_id=sale.id).one()
    cancel_transaction(business.db, business.ctx, receivable.id, reason="Written off")
    business.db.flush()

    returned = _return(business, sale, quantity="2")
    business.db.flush()

    assert returned.total_amount == Decimal("200.00")
    assert returned.credited_amount == Decimal("0.00")
    assert returned.refunded_amount == Decimal("0.00")
    assert returned.refund_method == RefundMethod.NONE
    # The goods still came back.
    assert len(_movements(business, product.default_variant.id, MovementReason.SALE_RETURN)) == 1


def test_a_credit_note_cannot_be_chosen_as_the_way_to_hand_money_back(business):
    """It is how value against a balance is recorded, not a way to pay out."""
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    sale = _sell(business, product, quantity="5").sale

    with pytest.raises(ValidationError) as refused:
        create_sale_return(
            business.db,
            business.ctx,
            sale.id,
            SaleReturnInput(
                lines=[ReturnLineInput(sale_line_id=sale.lines[0].id, quantity=Decimal("1"))],
                reason="Customer changed their mind",
                refund_method=PaymentMethod.CREDIT_NOTE,
            ),
        )
    assert "credit_note" in str(refused.value)


def test_refunds_across_several_returns_never_exceed_what_was_taken(business):
    """The cap is cumulative, not per return."""
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    sale = _sell(business, product, quantity="5").sale

    totals = Decimal("0.00")
    for _ in range(5):
        returned = _return(business, sale, quantity="1")
        business.db.flush()
        totals += returned.refunded_amount

    assert totals == Decimal("500.00")
    assert sale.amount_paid == Decimal("0.00")
    assert sale.effective_total == Decimal("0.00")
    assert sale.balance_due == Decimal("0.00")


# --------------------------------------------------------------------------- #
# Cost and profit
# --------------------------------------------------------------------------- #


def test_a_return_takes_back_the_cost_it_recognised(business):
    product = business.add_product("Teff", selling_price="100", purchase_price="60",
                                   opening_stock="10")
    sale = _sell(business, product, quantity="5").sale
    assert sale.cost_total == Decimal("300.00")
    assert sale.gross_profit == Decimal("200.00")

    returned = _return(business, sale, quantity="2")
    business.db.flush()

    assert returned.cost_total == Decimal("120.00")
    # Three units left: 300 revenue, 180 cost.
    assert sale.gross_profit == Decimal("120.00")


# --------------------------------------------------------------------------- #
# Guards
# --------------------------------------------------------------------------- #


def test_a_voided_sale_cannot_be_returned_against(business):
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    sale = _sell(business, product, quantity="5").sale
    void_sale(business.db, business.ctx, sale.id, reason="Rang it up twice")
    business.db.flush()

    with pytest.raises(ConflictError) as refused:
        _return(business, sale, quantity="2")
    assert "voided" in str(refused.value).lower()


def test_a_sale_with_returns_cannot_be_voided(business):
    """Voiding would reverse the returned goods and money a second time."""
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    sale = _sell(business, product, quantity="5").sale
    _return(business, sale, quantity="2")
    business.db.flush()

    with pytest.raises(ConflictError) as refused:
        void_sale(business.db, business.ctx, sale.id, reason="Changed my mind")
    assert refused.value.code == "sale_has_returns"


def test_a_reason_is_required(business):
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    sale = _sell(business, product, quantity="5").sale

    with pytest.raises(ValidationError):
        create_sale_return(
            business.db,
            business.ctx,
            sale.id,
            SaleReturnInput(
                lines=[ReturnLineInput(sale_line_id=sale.lines[0].id, quantity=Decimal("1"))],
                reason="  ",
            ),
        )


def test_a_line_from_another_sale_is_refused(business):
    product = business.add_product("Teff", selling_price="100", opening_stock="20")
    first = _sell(business, product, quantity="2").sale
    second = _sell(business, product, quantity="2").sale

    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        create_sale_return(
            business.db,
            business.ctx,
            first.id,
            SaleReturnInput(
                lines=[ReturnLineInput(sale_line_id=second.lines[0].id, quantity=Decimal("1"))],
                reason="Wrong sale",
            ),
        )


def test_taking_a_return_needs_the_refund_permission(business):
    """A salesperson does not get it by default: each shop decides."""
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    sale = _sell(business, product, quantity="5").sale
    _user, cashier_ctx = business.add_user(RoleName.SALESPERSON)

    assert Permission.SALE_REFUND not in cashier_ctx.permissions
    with pytest.raises(PermissionDenied):
        create_sale_return(
            business.db,
            cashier_ctx,
            sale.id,
            SaleReturnInput(
                lines=[ReturnLineInput(sale_line_id=sale.lines[0].id, quantity=Decimal("1"))],
                reason="Customer changed their mind",
            ),
        )


def test_a_manager_may_take_returns(business):
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    sale = _sell(business, product, quantity="5").sale
    _user, manager_ctx = business.add_user(RoleName.MANAGER)

    assert Permission.SALE_REFUND in manager_ctx.permissions
    returned = create_sale_return(
        business.db,
        manager_ctx,
        sale.id,
        SaleReturnInput(
            lines=[ReturnLineInput(sale_line_id=sale.lines[0].id, quantity=Decimal("1"))],
            reason="Customer changed their mind",
        ),
    )
    assert returned.total_amount == Decimal("100.00")


def test_replaying_a_return_with_the_same_key_posts_it_once(business):
    """What makes an offline or retried return safe."""
    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    variant = product.default_variant
    sale = _sell(business, product, quantity="5").sale

    payload = SaleReturnInput(
        lines=[ReturnLineInput(sale_line_id=sale.lines[0].id, quantity=Decimal("2"))],
        reason="Customer changed their mind",
        idempotency_key="till-7-return-1",
    )
    first = create_sale_return(business.db, business.ctx, sale.id, payload)
    business.db.flush()
    second = create_sale_return(business.db, business.ctx, sale.id, payload)
    business.db.flush()

    assert first.id == second.id
    assert len(_movements(business, variant.id, MovementReason.SALE_RETURN)) == 1
    assert get_balance(
        business.db, business.tenant.id, variant.id, business.location.id
    ) == Decimal("7.000")


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #


def test_reports_do_not_count_revenue_that_came_back(business):
    """Without this, every report overstates sales the moment a return exists."""
    from app.core.clock import local_today
    from app.services.reports import DateRange, sales_summary

    product = business.add_product("Teff", selling_price="100", purchase_price="60",
                                   opening_stock="10")
    sale = _sell(business, product, quantity="5").sale
    today = local_today(business.tenant.timezone)
    period = DateRange(today, today, business.tenant.timezone)

    before = sales_summary(business.db, business.ctx, period)
    assert before.net_sales == Decimal("500.00")
    assert before.returns_value == Decimal("0.00")
    assert before.net_after_returns == Decimal("500.00")
    assert before.gross_profit == Decimal("200.00")

    _return(business, sale, quantity="2")
    business.db.flush()

    after = sales_summary(business.db, business.ctx, period)
    # What was sold is unchanged; what came back is its own figure.
    assert after.net_sales == Decimal("500.00")
    assert after.return_count == 1
    assert after.items_returned == Decimal("2.000")
    assert after.returns_value == Decimal("200.00")
    assert after.net_after_returns == Decimal("300.00")
    # Both revenue and the cost of those units come out, or profit is wrong twice.
    assert after.returns_cost == Decimal("120.00")
    assert after.gross_profit == Decimal("120.00")


def test_the_summary_shows_returns_rather_than_hiding_them(business):
    """A reader can see the difference between sold and kept."""
    from app.core.clock import local_today
    from app.services.reports import DateRange, sales_summary

    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    sale = _sell(business, product, quantity="5").sale
    _return(business, sale, quantity="1")
    business.db.flush()

    today = local_today(business.tenant.timezone)
    payload = sales_summary(
        business.db, business.ctx, DateRange(today, today, business.tenant.timezone)
    ).as_dict(include_cost=True)

    assert payload["net_sales"] == "500.00"
    assert payload["returns_value"] == "100.00"
    assert payload["net_after_returns"] == "400.00"
    assert "after returns" in payload["profit_basis"]


def test_product_performance_separates_what_came_back(business):
    from app.core.clock import local_today
    from app.services.reports import DateRange, product_performance

    product = business.add_product("Teff", selling_price="100", purchase_price="60",
                                   opening_stock="10")
    sale = _sell(business, product, quantity="5").sale
    _return(business, sale, quantity="2")
    business.db.flush()

    today = local_today(business.tenant.timezone)
    rows = product_performance(
        business.db, business.ctx, DateRange(today, today, business.tenant.timezone)
    )
    row = next(r for r in rows if r["name"] == "Teff")
    assert row["quantity_sold"] == "5.000"
    assert row["quantity_returned"] == "2.000"
    assert row["revenue"] == "500.00"
    assert row["returns_value"] == "200.00"
    assert row["net_revenue"] == "300.00"
    # Money is reported with two decimals.  quantity is Numeric(14,3) and
    # unit_cost Numeric(14,2), so their product carries five on PostgreSQL;
    # these assertions are what caught that, and SQLite alone would not have.
    assert row["cost"] == "300.00"
    assert row["returns_cost"] == "120.00"
    assert row["gross_profit"] == "120.00"


def test_a_refund_is_not_counted_as_money_taken(business):
    """A till that took 500 and gave 200 back took 500 and refunded 200."""
    from app.core.clock import local_today
    from app.services.reports import DateRange, sales_by_payment_method

    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    sale = _sell(business, product, quantity="5").sale
    _return(business, sale, quantity="2")
    business.db.flush()

    today = local_today(business.tenant.timezone)
    rows = sales_by_payment_method(
        business.db, business.ctx, DateRange(today, today, business.tenant.timezone)
    )
    cash = next(r for r in rows if r["method"] == "cash")
    assert cash["received"] == "500.00"
    assert cash["refunded"] == "200.00"
    assert cash["total"] == "300.00"


def test_a_return_belongs_to_the_day_it_came_back(business):
    """Not to the day of the sale: that is when the money moved."""
    from app.core.clock import local_today
    from app.services.reports import DateRange, sales_summary

    product = business.add_product("Teff", selling_price="100", opening_stock="10")
    today = local_today(business.tenant.timezone)
    yesterday = today - timedelta(days=1)

    sale = create_sale(
        business.db,
        business.ctx,
        SaleInput(
            lines=[SaleLineInput(variant_id=product.default_variant.id, quantity=Decimal("5"))],
            payments=[PaymentInput(method=PaymentMethod.CASH, amount=Decimal("500.00"))],
            sold_at=datetime.combine(yesterday, time(10, 0), tzinfo=UTC),
        ),
    ).sale
    _return(business, sale, quantity="2")  # today
    business.db.flush()

    yesterdays = sales_summary(
        business.db, business.ctx, DateRange(yesterday, yesterday, business.tenant.timezone)
    )
    todays = sales_summary(
        business.db, business.ctx, DateRange(today, today, business.tenant.timezone)
    )

    assert yesterdays.net_sales == Decimal("500.00")
    assert yesterdays.returns_value == Decimal("0.00")
    assert todays.net_sales == Decimal("0.00")
    assert todays.returns_value == Decimal("200.00")
