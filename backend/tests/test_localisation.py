"""ETB, Ethiopian phone formats, Amharic text and date handling (PRD 16, 21)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.schemas.auth import normalise_et_phone
from app.services.pricing import quantize_money


@pytest.mark.parametrize(
    ("entered", "stored"),
    [
        ("0911234567", "+251911234567"),
        ("+251911234567", "+251911234567"),
        ("251911234567", "+251911234567"),
        ("0911 23 45 67", "+251911234567"),
        ("091-123-4567", "+251911234567"),
        ("0711234567", "+251711234567"),
    ],
)
def test_ethiopian_numbers_are_stored_in_one_form(entered, stored):
    assert normalise_et_phone(entered) == stored


def test_a_foreign_number_is_kept_as_entered():
    """Not every contact is Ethiopian; do not mangle their number."""
    assert normalise_et_phone("+44 20 7946 0000") == "+442079460000"


def test_no_phone_number_stays_empty():
    assert normalise_et_phone(None) is None
    assert normalise_et_phone("") is None


def test_a_new_business_uses_etb(business):
    assert business.tenant.currency == "ETB"
    assert business.tenant.timezone == "Africa/Addis_Ababa"


def test_money_is_held_to_two_decimals(business):
    product = business.add_product("Odd price", selling_price="33.333", opening_stock="10")
    result = business.sell(product, quantity="3")
    # 33.33 x 3 = 99.99, not 99.999
    assert result.sale.total_amount == Decimal("99.99")
    assert quantize_money(Decimal("0.005")) == Decimal("0.01")


def test_quantities_keep_three_decimals_for_weighed_goods(business):
    product = business.add_product(
        "Coffee beans", selling_price="400", opening_stock="10.500", unit_of_measure="kg"
    )
    from app.services.inventory import get_balance

    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, business.location.id
    ) == Decimal("10.500")


def test_amharic_text_round_trips(business):
    """Product names, customers and notes must store Amharic unchanged (PRD 16)."""
    product = business.add_product("ቡና", selling_price="120", opening_stock="5")
    customer = business.add_customer("አበበ በቀለ", address="አዲስ አበባ, ቦሌ")
    business.db.flush()
    business.db.refresh(product)
    business.db.refresh(customer)

    assert product.name == "ቡና"
    assert customer.name == "አበበ በቀለ"
    assert customer.address == "አዲስ አበባ, ቦሌ"


def test_amharic_survives_the_api(client, business):
    created = client.post(
        "/api/v1/products",
        json={"name": "በርበሬ", "selling_price": "450.00", "opening_stock": "20"},
        headers=business.headers(),
    )
    assert created.status_code == 201
    assert created.json()["name"] == "በርበሬ"

    listed = client.get("/api/v1/products?q=በርበሬ", headers=business.headers()).json()
    assert listed["total"] == 1


def test_timestamps_are_stored_in_utc(business):
    product = business.add_product("Timed", opening_stock="5")
    sale = business.sell(product).sale
    assert sale.sold_at.tzinfo is not None
    assert sale.sold_at.utcoffset() == timedelta(0)


def test_a_sale_dated_in_another_timezone_lands_on_the_right_day(business):
    """Addis Ababa is UTC+3; a late-evening sale must not slip to the next day."""
    from app.services.reports import DateRange, sales_summary

    product = business.add_product("Evening sale", selling_price="100", opening_stock="10")
    # 22:30 in Addis Ababa on the 15th is 19:30 UTC on the 15th.
    sold_at = datetime(2026, 3, 15, 19, 30, tzinfo=UTC)
    business.sell(product, sold_at=sold_at)

    on_the_day = sales_summary(
        business.db, business.ctx, DateRange(date(2026, 3, 15), date(2026, 3, 15))
    )
    next_day = sales_summary(
        business.db, business.ctx, DateRange(date(2026, 3, 16), date(2026, 3, 16))
    )
    assert on_the_day.sale_count == 1
    assert next_day.sale_count == 0


def test_date_ranges_cover_the_whole_end_day(business):
    from app.services.reports import DateRange, sales_summary

    product = business.add_product("Late", selling_price="100", opening_stock="10")
    business.sell(product, sold_at=datetime(2026, 3, 15, 23, 59, tzinfo=UTC))

    summary = sales_summary(
        business.db, business.ctx, DateRange(date(2026, 3, 10), date(2026, 3, 15))
    )
    assert summary.sale_count == 1


def test_report_periods_resolve_as_expected():
    from app.services.reports import range_for

    today = date(2026, 3, 15)
    assert range_for("today", today=today) == type(range_for("today", today=today))(today, today)
    assert range_for("7d", today=today).start == date(2026, 3, 9)
    assert range_for("month", today=today).start == date(2026, 3, 1)
    assert range_for("year", today=today).start == date(2026, 1, 1)


def test_due_dates_are_plain_calendar_dates(business, today):
    """Due dates are days, not instants, so a timezone cannot shift them."""
    from app.models.credit import CreditKind
    from app.services.credit import create_credit_transaction

    customer = business.add_customer("Date test")
    transaction = create_credit_transaction(
        business.db,
        business.ctx,
        kind=CreditKind.RECEIVABLE,
        amount=Decimal("100"),
        branch_id=business.branch.id,
        customer_id=customer.id,
        due_date=today + timedelta(days=30),
    )
    assert isinstance(transaction.due_date, date)
    assert not isinstance(transaction.due_date, datetime)


def test_local_payment_methods_are_available():
    """Telebirr and CBE Birr are configurable local methods (PRD 10, 16)."""
    from app.models.sales import PaymentMethod

    methods = {str(m) for m in PaymentMethod}
    assert {"telebirr", "cbe_birr", "cash", "bank_transfer"} <= methods


def test_a_sale_can_be_paid_with_telebirr(business):
    from app.models.sales import PaymentMethod
    from app.services.sales import PaymentInput, SaleInput, SaleLineInput, create_sale

    product = business.add_product("Mobile paid", selling_price="250", opening_stock="10")
    result = create_sale(
        business.db,
        business.ctx,
        SaleInput(
            lines=[SaleLineInput(variant_id=product.default_variant.id, quantity=Decimal("1"))],
            payments=[
                PaymentInput(
                    method=PaymentMethod.TELEBIRR,
                    amount=Decimal("250"),
                    reference="TB-0099887",
                )
            ],
        ),
    )
    assert result.sale.payments[0].reference == "TB-0099887"
