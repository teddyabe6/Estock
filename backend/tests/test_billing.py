"""Subscription invoices and payments (PRD 17).

The platform knew which plan a shop was on and when its period ended. It had
no record of what the shop had been charged or had paid, so the one question
the business actually runs on — "who owes me money?" — had no answer.

The rules these tests pin:

* Nothing about the money is stored twice. What an invoice is paid, owes and
  whether it is overdue are summed from its payment rows, so they cannot
  disagree with them.
* A correction keeps the original. A payment is reversed, an invoice voided;
  neither is deleted.
* Paying in full renews the service and can lift read-only — but never a
  suspension, or the platform's one real sanction would be purchasable.
* A paid period that runs out lapses the shop to read-only, with the same
  promise trial expiry makes: nothing is deleted.
* The billing run is safe to repeat and never guesses a price.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.platform import (
    Subscription,
    SubscriptionInvoiceStatus,
    SubscriptionStatus,
    TenantStatus,
)
from app.models.sales import PaymentMethod
from app.models.system import Notification, NotificationKind
from app.services import billing

TODAY = date(2026, 6, 15)


def _subscription(business) -> Subscription:
    from sqlalchemy import select

    return business.db.execute(
        select(Subscription).where(Subscription.tenant_id == business.tenant.id)
    ).scalar_one()


def _priced(business, price="800.00", **kwargs):
    """A shop on a plan that costs something."""
    return business.put_on_plan(monthly_price=price, name="Standard", **kwargs)


def _paid_until(business, when: date | None):
    """Set — or clear — the period this shop has already been served for.

    Registration gives a new shop a period running to the end of its trial,
    which is right (a trial is service) but means a test reasoning from
    ``TODAY`` has to say where the shop stands first.
    """
    subscription = _subscription(business)
    subscription.current_period_ends_on = when
    business.db.flush()
    return subscription


def _invoice(business, **kwargs):
    return billing.raise_invoice(business.db, business.tenant.id, today=TODAY, **kwargs)


def _pay(business, invoice, amount, **kwargs):
    return billing.record_payment(
        business.db,
        invoice.id,
        amount=Decimal(str(amount)),
        method=kwargs.pop("method", PaymentMethod.TELEBIRR),
        today=TODAY,
        paid_on=kwargs.pop("paid_on", TODAY),
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Raising an invoice
# --------------------------------------------------------------------------- #


def test_an_invoice_takes_its_price_and_period_from_the_plan(db, business):
    _priced(business, price="800.00")
    _paid_until(business, None)
    invoice = _invoice(business)

    assert Decimal(invoice.amount) == Decimal("800.00")
    assert invoice.plan_name == "Standard"
    assert invoice.period_start == TODAY
    assert invoice.period_end == TODAY + timedelta(days=29)
    assert invoice.number.startswith("SUB-2026-")
    assert billing.derive_status(invoice, today=TODAY) == SubscriptionInvoiceStatus.OPEN


def test_a_new_shops_first_invoice_starts_when_its_trial_ends(db, business):
    """A trial is service already given, so billing starts after it, not during.

    Registration sets the subscription's period to the end of the trial, and
    the first invoice follows on from that — a shop is never charged for days
    it was given free.
    """
    _priced(business)
    subscription = _subscription(business)
    trial_ends = subscription.current_period_ends_on
    assert trial_ends is not None, "registration gives a new shop a trial period"

    invoice = _invoice(business)
    assert invoice.period_start == trial_ends + timedelta(days=1)


def test_an_invoice_snapshots_the_plan_so_a_price_change_cannot_rewrite_it(db, business):
    """A sale snapshots its prices; a bill has to do the same."""
    plan = _priced(business, price="800.00")
    invoice = _invoice(business)

    plan.name = "Standard (renamed)"
    plan.monthly_price = Decimal("1200.00")
    db.flush()
    db.refresh(invoice)

    assert Decimal(invoice.amount) == Decimal("800.00")
    assert invoice.plan_name == "Standard"


def test_a_shop_on_no_plan_is_not_billed_a_guessed_price(db, business):
    with pytest.raises(ValidationError) as raised:
        _invoice(business)
    assert "no plan" in str(raised.value).lower()


def test_a_shop_on_no_plan_can_still_be_billed_an_agreed_amount(db, business):
    """A platform owner negotiates; what is agreed is what is recorded."""
    _paid_until(business, None)
    invoice = _invoice(business, amount=Decimal("500.00"))
    assert Decimal(invoice.amount) == Decimal("500.00")
    assert invoice.plan_code is None


def test_the_next_period_follows_on_from_the_one_already_paid_for(db, business):
    """Periods meet end-to-end: no overlap, and no free gap."""
    _priced(business)
    _paid_until(business, TODAY + timedelta(days=10))

    invoice = _invoice(business)
    assert invoice.period_start == TODAY + timedelta(days=11)


def test_a_period_cannot_end_before_it_starts(db, business):
    _priced(business)
    with pytest.raises(ValidationError):
        _invoice(business, period_start=TODAY, period_end=TODAY - timedelta(days=1))


def test_billing_the_same_period_twice_is_refused(db, business):
    _priced(business)
    _paid_until(business, None)
    first = _invoice(business)
    with pytest.raises(ConflictError) as raised:
        _invoice(
            business, period_start=first.period_start, period_end=first.period_end
        )
    assert first.number in str(raised.value)


def test_a_voided_invoice_leaves_its_period_free_to_bill_again(db, business):
    """Voiding is how a mistake is undone, so the period must be re-billable."""
    _priced(business)
    _paid_until(business, None)
    first = _invoice(business)
    billing.void_invoice(db, first.id, reason="Billed the wrong plan")

    again = _invoice(
        business, period_start=first.period_start, period_end=first.period_end
    )
    assert again.id != first.id


def test_a_draft_is_not_yet_owed(db, business):
    _priced(business)
    invoice = _invoice(business, issue=False)
    assert invoice.issued_at is None
    assert billing.derive_status(invoice, today=TODAY) == SubscriptionInvoiceStatus.DRAFT

    with pytest.raises(ConflictError) as raised:
        _pay(business, invoice, "800.00")
    assert "draft" in str(raised.value).lower()

    billing.issue_invoice(db, invoice.id)
    assert billing.derive_status(invoice, today=TODAY) == SubscriptionInvoiceStatus.OPEN


# --------------------------------------------------------------------------- #
# Derived money: nothing is stored twice
# --------------------------------------------------------------------------- #


def test_what_is_paid_and_owed_is_summed_from_the_payments(db, business):
    _priced(business, price="900.00")
    invoice = _invoice(business)

    _pay(business, invoice, "300.00")
    assert billing.amount_paid(invoice) == Decimal("300.00")
    assert billing.balance_due(invoice) == Decimal("600.00")
    assert billing.derive_status(invoice, today=TODAY) == SubscriptionInvoiceStatus.PART_PAID

    _pay(business, invoice, "600.00")
    assert billing.amount_paid(invoice) == Decimal("900.00")
    assert billing.balance_due(invoice) == Decimal("0.00")
    assert billing.derive_status(invoice, today=TODAY) == SubscriptionInvoiceStatus.PAID


def test_an_invoice_with_no_due_date_never_becomes_overdue(db, business):
    """Elapsed time alone never makes a balance overdue (PRD 11.3)."""
    _priced(business)
    invoice = _invoice(business, due_on=None, terms_days=0)
    invoice.due_on = None
    db.flush()

    far_future = TODAY + timedelta(days=4000)
    assert billing.derive_status(invoice, today=far_future) == SubscriptionInvoiceStatus.OPEN


def test_an_invoice_falls_overdue_the_day_after_it_is_due(db, business):
    _priced(business)
    invoice = _invoice(business, due_on=TODAY + timedelta(days=7))

    assert billing.derive_status(invoice, today=invoice.due_on) == SubscriptionInvoiceStatus.OPEN
    assert (
        billing.derive_status(invoice, today=invoice.due_on + timedelta(days=1))
        == SubscriptionInvoiceStatus.OVERDUE
    )


def test_a_part_paid_invoice_past_its_due_date_reads_overdue(db, business):
    """Owing something late matters more than having paid something."""
    _priced(business, price="900.00")
    invoice = _invoice(business, due_on=TODAY)
    _pay(business, invoice, "100.00")

    assert (
        billing.derive_status(invoice, today=TODAY + timedelta(days=1))
        == SubscriptionInvoiceStatus.OVERDUE
    )


def test_overpayment_reads_as_paid_with_a_negative_balance(db, business):
    """The honest figure, rather than a status invented for the case."""
    _priced(business, price="800.00")
    invoice = _invoice(business)
    result = _pay(business, invoice, "1000.00")

    assert billing.derive_status(invoice, today=TODAY) == SubscriptionInvoiceStatus.PAID
    assert billing.balance_due(invoice) == Decimal("-200.00")
    assert result.warnings and "more than" in result.warnings[0]


def test_a_void_invoice_owes_nothing(db, business):
    _priced(business)
    invoice = _invoice(business)
    assert billing.balance_due(invoice) > 0

    billing.void_invoice(db, invoice.id, reason="Raised against the wrong shop")
    assert billing.balance_due(invoice) == Decimal("0.00")
    assert billing.derive_status(invoice, today=TODAY) == SubscriptionInvoiceStatus.VOID


# --------------------------------------------------------------------------- #
# Corrections keep the original
# --------------------------------------------------------------------------- #


def test_a_reversed_payment_stops_counting_but_stays_on_the_record(db, business):
    _priced(business, price="800.00")
    invoice = _invoice(business)
    result = _pay(business, invoice, "800.00", reference="TB-99887766")
    assert billing.derive_status(invoice, today=TODAY) == SubscriptionInvoiceStatus.PAID

    billing.reverse_payment(db, result.payment.id, reason="Matched the wrong shop")
    db.refresh(invoice)

    assert billing.amount_paid(invoice) == Decimal("0.00")
    assert billing.balance_due(invoice) == Decimal("800.00")
    assert len(invoice.payments) == 1, "the row is kept, not deleted"
    assert invoice.payments[0].is_reversed is True
    assert invoice.payments[0].reference == "TB-99887766"
    assert invoice.payments[0].reversal_reason == "Matched the wrong shop"


def test_reversing_twice_changes_nothing_further(db, business):
    _priced(business)
    invoice = _invoice(business)
    result = _pay(business, invoice, "800.00")
    billing.reverse_payment(db, result.payment.id, reason="First")
    first_at = result.payment.reversed_at

    billing.reverse_payment(db, result.payment.id, reason="Second")
    assert result.payment.reversed_at == first_at
    assert result.payment.reversal_reason == "First"


def test_an_invoice_with_payments_cannot_be_voided(db, business):
    """Voiding it would make the payment belong to nothing."""
    _priced(business)
    invoice = _invoice(business)
    _pay(business, invoice, "100.00")

    with pytest.raises(ConflictError) as raised:
        billing.void_invoice(db, invoice.id, reason="Changed my mind")
    assert "reverse them first" in str(raised.value).lower()


def test_voiding_works_once_the_payments_are_reversed(db, business):
    _priced(business)
    invoice = _invoice(business)
    result = _pay(business, invoice, "100.00")
    billing.reverse_payment(db, result.payment.id, reason="Recorded in error")

    voided = billing.void_invoice(db, invoice.id, reason="Shop never signed up")
    assert voided.voided_at is not None


def test_the_same_payment_submitted_twice_is_recorded_once(db, business):
    """A double tap on a slow connection must not double the money."""
    _priced(business, price="800.00")
    invoice = _invoice(business)

    first = _pay(business, invoice, "800.00", idempotency_key="deposit-5521")
    second = _pay(business, invoice, "800.00", idempotency_key="deposit-5521")

    assert first.payment.id == second.payment.id
    assert billing.amount_paid(invoice) == Decimal("800.00")
    assert len([p for p in invoice.payments if not p.is_reversed]) == 1


# --------------------------------------------------------------------------- #
# What a payment refuses
# --------------------------------------------------------------------------- #


def test_a_credit_note_is_not_a_way_of_paying_the_platform(db, business):
    """It settles a balance inside a shop's books; no money reaches the platform."""
    _priced(business)
    invoice = _invoice(business)

    with pytest.raises(ValidationError) as raised:
        _pay(business, invoice, "800.00", method=PaymentMethod.CREDIT_NOTE)
    assert "credit note" in str(raised.value).lower()
    assert "telebirr" in str(raised.value.details["allowed"])


@pytest.mark.parametrize("amount", ["0.00", "-50.00"])
def test_a_payment_must_be_for_more_than_nothing(db, business, amount):
    _priced(business)
    invoice = _invoice(business)
    with pytest.raises(ValidationError):
        _pay(business, invoice, amount)


def test_a_payment_cannot_be_dated_in_the_future(db, business):
    _priced(business)
    invoice = _invoice(business)
    with pytest.raises(ValidationError) as raised:
        _pay(business, invoice, "800.00", paid_on=TODAY + timedelta(days=1))
    assert "future" in str(raised.value).lower()


def test_paying_a_voided_invoice_is_refused(db, business):
    _priced(business)
    invoice = _invoice(business)
    billing.void_invoice(db, invoice.id, reason="Duplicate")
    with pytest.raises(ConflictError):
        _pay(business, invoice, "800.00")


def test_an_unknown_invoice_is_not_found(db, business):
    import uuid as _uuid

    with pytest.raises(NotFoundError):
        billing.record_payment(
            db,
            _uuid.uuid4(),
            amount=Decimal("100.00"),
            method=PaymentMethod.CASH,
        )


# --------------------------------------------------------------------------- #
# Billing decides access — in one direction only
# --------------------------------------------------------------------------- #


def test_paying_in_full_renews_the_service_and_lifts_read_only(db, business):
    _priced(business)
    business.tenant.status = TenantStatus.RESTRICTED
    subscription = _subscription(business)
    subscription.status = SubscriptionStatus.EXPIRED
    db.flush()

    invoice = _invoice(business)
    result = _pay(business, invoice, "800.00")

    assert result.renewed is True
    assert business.tenant.status == TenantStatus.ACTIVE
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription.current_period_ends_on == invoice.period_end


def test_part_payment_does_not_renew(db, business):
    _priced(business, price="800.00")
    business.tenant.status = TenantStatus.RESTRICTED
    db.flush()

    invoice = _invoice(business)
    result = _pay(business, invoice, "400.00")

    assert result.renewed is False
    assert business.tenant.status == TenantStatus.RESTRICTED


def test_paying_never_lifts_a_suspension(db, business):
    """A platform whose sanctions can be bought off has no sanctions.

    Suspension is a decision about conduct. The money is still recorded and
    the period still extends — the shop paid, and that is a fact — but
    getting back in takes a deliberate, audited change of status.
    """
    _priced(business)
    business.tenant.status = TenantStatus.SUSPENDED
    db.flush()

    invoice = _invoice(business)
    result = _pay(business, invoice, "800.00")

    assert business.tenant.status == TenantStatus.SUSPENDED
    assert result.tenant_status is None
    assert billing.derive_status(invoice, today=TODAY) == SubscriptionInvoiceStatus.PAID
    assert _subscription(business).current_period_ends_on == invoice.period_end


def test_renewal_never_shortens_a_period_already_paid_for(db, business):
    """Paying an old invoice late must not claw back service already bought."""
    _priced(business)
    subscription = _subscription(business)
    subscription.current_period_ends_on = TODAY + timedelta(days=200)
    db.flush()

    invoice = _invoice(
        business,
        period_start=TODAY - timedelta(days=60),
        period_end=TODAY - timedelta(days=31),
    )
    _pay(business, invoice, "800.00")

    assert subscription.current_period_ends_on == TODAY + timedelta(days=200)


def test_reversing_a_payment_does_not_take_access_away(db, business):
    """The lapse run decides that on the period's terms, not on a correction."""
    _priced(business)
    invoice = _invoice(business)
    result = _pay(business, invoice, "800.00")
    assert business.tenant.status == TenantStatus.ACTIVE

    billing.reverse_payment(db, result.payment.id, reason="Bank reversed it")

    assert business.tenant.status == TenantStatus.ACTIVE
    assert billing.balance_due(invoice) == Decimal("800.00")


# --------------------------------------------------------------------------- #
# Lapsing: the same promise trial expiry makes
# --------------------------------------------------------------------------- #


def test_a_paid_period_that_runs_out_makes_the_shop_read_only(db, business):
    _priced(business)
    subscription = _subscription(business)
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_ends_on = TODAY - timedelta(days=1)
    business.tenant.status = TenantStatus.ACTIVE
    db.flush()

    lapsed = billing.expire_lapsed_subscriptions(db, today=TODAY)

    assert business.tenant.id in lapsed
    assert business.tenant.status == TenantStatus.RESTRICTED
    assert subscription.status == SubscriptionStatus.EXPIRED


def test_lapsing_deletes_nothing(db, business):
    """The promise that matters: read-only, every figure still there."""
    _priced(business)
    product = business.add_product("Berbere", selling_price="450")
    sale = business.sell(product, quantity=2).sale

    subscription = _subscription(business)
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_ends_on = TODAY - timedelta(days=1)
    business.tenant.status = TenantStatus.ACTIVE
    db.flush()

    billing.expire_lapsed_subscriptions(db, today=TODAY)
    db.refresh(sale)

    assert business.tenant.is_read_only is True
    assert sale.id is not None
    assert Decimal(sale.total_amount) > 0
    assert db.get(type(product), product.id) is not None


def test_a_period_still_running_does_not_lapse(db, business):
    _priced(business)
    subscription = _subscription(business)
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_ends_on = TODAY
    business.tenant.status = TenantStatus.ACTIVE
    db.flush()

    assert billing.expire_lapsed_subscriptions(db, today=TODAY) == []
    assert business.tenant.status == TenantStatus.ACTIVE


def test_a_lapse_notice_is_its_own_kind_not_the_trial_one(db, business):
    """The daily de-duplication keys on kind, so sharing one would hide the other."""
    _priced(business)
    subscription = _subscription(business)
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_ends_on = TODAY - timedelta(days=1)
    business.tenant.status = TenantStatus.ACTIVE
    db.flush()

    billing.expire_lapsed_subscriptions(db, today=TODAY)

    kinds = {n.kind for n in db.query(Notification).all()}
    assert NotificationKind.SUBSCRIPTION_EXPIRY in kinds
    assert NotificationKind.TRIAL_EXPIRY not in kinds


# --------------------------------------------------------------------------- #
# The billing run
# --------------------------------------------------------------------------- #


def test_the_run_raises_an_invoice_for_a_period_about_to_end(db, business):
    _priced(business)
    subscription = _subscription(business)
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_ends_on = TODAY + timedelta(days=3)
    business.tenant.status = TenantStatus.ACTIVE
    db.flush()

    run = billing.run_billing_cycle(db, today=TODAY)

    assert len(run.raised) == 1
    rows, _ = billing.invoices_for_tenant(db, business.tenant.id)
    assert rows[0].invoice.period_start == TODAY + timedelta(days=4)


def test_the_run_leaves_a_period_with_plenty_left_alone(db, business):
    _priced(business)
    subscription = _subscription(business)
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_ends_on = TODAY + timedelta(days=90)
    business.tenant.status = TenantStatus.ACTIVE
    db.flush()

    assert billing.run_billing_cycle(db, today=TODAY).raised == []


def test_running_the_cycle_twice_bills_once(db, business):
    """It has to be safe to run twice: a cron job is not a transaction."""
    _priced(business)
    subscription = _subscription(business)
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_ends_on = TODAY + timedelta(days=3)
    business.tenant.status = TenantStatus.ACTIVE
    db.flush()

    first = billing.run_billing_cycle(db, today=TODAY)
    second = billing.run_billing_cycle(db, today=TODAY)

    assert len(first.raised) == 1
    assert second.raised == []
    assert second.skipped_already_billed == 1


def test_the_run_skips_a_shop_on_no_plan_rather_than_guessing(db, business):
    business.tenant.status = TenantStatus.ACTIVE
    subscription = _subscription(business)
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_ends_on = TODAY + timedelta(days=1)
    db.flush()

    run = billing.run_billing_cycle(db, today=TODAY)
    assert run.raised == []
    assert run.skipped_no_plan == 1


def test_the_run_bills_a_trial_as_it_runs_out(db, business):
    """A trial ending is exactly when a shop needs to be asked for money."""
    _priced(business)
    subscription = _subscription(business)
    subscription.status = SubscriptionStatus.TRIALING
    subscription.trial_ends_on = TODAY + timedelta(days=2)
    business.tenant.status = TenantStatus.TRIAL
    db.flush()

    run = billing.run_billing_cycle(db, today=TODAY)
    assert len(run.raised) == 1


def test_the_run_ignores_a_suspended_shop(db, business):
    _priced(business)
    subscription = _subscription(business)
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_ends_on = TODAY + timedelta(days=1)
    business.tenant.status = TenantStatus.SUSPENDED
    db.flush()

    assert billing.run_billing_cycle(db, today=TODAY).raised == []


# --------------------------------------------------------------------------- #
# The platform owner's own numbers
# --------------------------------------------------------------------------- #


def test_the_summary_totals_billed_collected_and_owed(db, business):
    _priced(business, price="800.00")
    paid = _invoice(business, period_start=TODAY, period_end=TODAY + timedelta(days=29))
    _pay(business, paid, "800.00")
    part = _invoice(
        business,
        period_start=TODAY + timedelta(days=30),
        period_end=TODAY + timedelta(days=59),
    )
    _pay(business, part, "300.00")

    summary = billing.billing_summary(db, today=TODAY)

    assert summary.billed == Decimal("1600.00")
    assert summary.collected == Decimal("1100.00")
    assert summary.outstanding == Decimal("500.00")
    assert summary.paying_shops == 1
    assert summary.shops_in_arrears == 1


def test_the_summary_counts_what_is_overdue_separately(db, business):
    _priced(business, price="800.00")
    _invoice(
        business,
        period_start=TODAY - timedelta(days=60),
        period_end=TODAY - timedelta(days=31),
        due_on=TODAY - timedelta(days=40),
    )

    summary = billing.billing_summary(db, today=TODAY)
    assert summary.overdue == Decimal("800.00")
    assert summary.overdue_count == 1


def test_a_void_invoice_is_in_no_total(db, business):
    """A cancelled charge was never owed; counting it overstates both sides."""
    _priced(business, price="800.00")
    invoice = _invoice(business)
    billing.void_invoice(db, invoice.id, reason="Raised twice")

    summary = billing.billing_summary(db, today=TODAY)
    assert summary.billed == Decimal("0.00")
    assert summary.outstanding == Decimal("0.00")


def test_a_draft_is_in_no_total_either(db, business):
    """Nothing is owed until the invoice is issued."""
    _priced(business, price="800.00")
    _invoice(business, issue=False)

    summary = billing.billing_summary(db, today=TODAY)
    assert summary.billed == Decimal("0.00")


def test_invoices_can_be_listed_by_their_derived_status(db, business):
    _priced(business, price="800.00")
    paid = _invoice(business, period_start=TODAY, period_end=TODAY + timedelta(days=29))
    _pay(business, paid, "800.00")
    _invoice(
        business,
        period_start=TODAY + timedelta(days=30),
        period_end=TODAY + timedelta(days=59),
    )

    only_paid, total = billing.list_invoices(
        db, status=SubscriptionInvoiceStatus.PAID, today=TODAY
    )
    assert total == 1
    assert only_paid[0].invoice.id == paid.id

    only_open, open_total = billing.list_invoices(
        db, status=SubscriptionInvoiceStatus.OPEN, today=TODAY
    )
    assert open_total == 1
    assert only_open[0].invoice.id != paid.id


# --------------------------------------------------------------------------- #
# Numbering, and one shop's books kept apart from another's
# --------------------------------------------------------------------------- #


def test_each_shop_gets_its_own_invoice_sequence(db, business, other_business):
    """An invoice is numbered like the shop's own documents, per shop."""
    _priced(business)
    _priced(other_business)

    first = _invoice(business)
    other = billing.raise_invoice(db, other_business.tenant.id, today=TODAY)

    assert first.number == "SUB-2026-000001"
    assert other.number == "SUB-2026-000001"
    assert first.tenant_id != other.tenant_id


def test_one_shop_cannot_see_another_shops_invoices(db, business, other_business):
    _priced(business)
    _priced(other_business)
    _invoice(business)
    billing.raise_invoice(db, other_business.tenant.id, today=TODAY)

    mine, total = billing.invoices_for_tenant(db, business.tenant.id)
    assert total == 1
    assert all(row.invoice.tenant_id == business.tenant.id for row in mine)


# --------------------------------------------------------------------------- #
# Through the API, and the boundary around it
# --------------------------------------------------------------------------- #


@pytest.fixture()
def admin_headers(client, db):
    """A signed-in platform administrator."""
    from app.core.security import hash_password
    from app.models.platform import PlatformAdmin

    db.add(
        PlatformAdmin(
            email="billing@estock.et",
            full_name="Billing",
            password_hash=hash_password("admin-pw-123"),
        )
    )
    db.flush()
    login = client.post(
        "/api/v1/platform/login",
        json={"email": "billing@estock.et", "password": "admin-pw-123"},
    )
    assert login.status_code == 200, login.json()
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_the_whole_cycle_through_the_api(client, db, business, admin_headers):
    """Raise, part-pay, settle, and watch the shop come back from read-only."""
    _priced(business, price="800.00")
    _paid_until(business, None)
    business.tenant.status = TenantStatus.RESTRICTED
    db.flush()

    raised = client.post(
        "/api/v1/platform/invoices",
        json={"tenant_id": str(business.tenant.id)},
        headers=admin_headers,
    )
    assert raised.status_code == 201, raised.json()
    invoice = raised.json()
    assert invoice["status"] == "open"
    assert invoice["amount"] == "800.00"
    assert invoice["balance_due"] == "800.00"

    part = client.post(
        f"/api/v1/platform/invoices/{invoice['id']}/payments",
        json={"amount": "300.00", "method": "telebirr", "reference": "TB-1234"},
        headers=admin_headers,
    )
    assert part.status_code == 201, part.json()
    assert part.json()["invoice"]["status"] == "part_paid"
    assert part.json()["invoice"]["balance_due"] == "500.00"
    assert part.json()["renewed"] is False

    rest = client.post(
        f"/api/v1/platform/invoices/{invoice['id']}/payments",
        json={"amount": "500.00", "method": "cbe_birr", "reference": "CBE-5678"},
        headers=admin_headers,
    )
    assert rest.status_code == 201, rest.json()
    assert rest.json()["invoice"]["status"] == "paid"
    assert rest.json()["renewed"] is True
    assert rest.json()["tenant_status"] == "active"

    db.refresh(business.tenant)
    assert business.tenant.status == TenantStatus.ACTIVE


def test_the_summary_endpoint_reports_the_platforms_own_numbers(
    client, db, business, admin_headers
):
    _priced(business, price="800.00")
    _paid_until(business, None)
    invoice = _invoice(business)
    _pay(business, invoice, "800.00")

    summary = client.get("/api/v1/platform/billing/summary", headers=admin_headers)
    assert summary.status_code == 200
    assert summary.json()["collected"] == "800.00"
    assert summary.json()["outstanding"] == "0.00"
    assert summary.json()["paying_shops"] == 1


def test_one_shops_billing_history_is_listed_with_its_name(
    client, db, business, admin_headers
):
    _priced(business, price="800.00")
    _paid_until(business, None)
    _invoice(business)

    page = client.get(
        f"/api/v1/platform/tenants/{business.tenant.id}/billing", headers=admin_headers
    )
    assert page.status_code == 200
    body = page.json()
    assert body["tenant_name"] == business.tenant.name
    assert body["balance_due"] == "800.00"
    assert body["unpaid_count"] == 1
    assert len(body["invoices"]) == 1


def test_a_business_sees_what_it_owes_but_cannot_change_it(client, db, business):
    """The invoice is the platform's document; a shop editing its bill is nonsense."""
    _priced(business, price="800.00")
    _paid_until(business, None)
    invoice = _invoice(business)

    mine = client.get("/api/v1/subscription", headers=business.headers())
    assert mine.status_code == 200
    billing_block = mine.json()["billing"]
    assert billing_block["balance_due"] == "800.00"
    assert billing_block["unpaid_count"] == 1
    assert billing_block["invoices"][0]["number"] == invoice.number

    # Every invoice route is the platform's; none is reachable with a shop's
    # own token.
    invoice_routes = {
        route.path
        for route in client.app.routes
        if "/invoices" in getattr(route, "path", "")
    }
    assert invoice_routes
    assert all(path.startswith("/api/v1/platform/") for path in invoice_routes)


def test_a_business_token_cannot_reach_the_platform_billing_routes(client, business):
    """Billing is the platform's, behind a separate identity boundary (PRD 5.2)."""
    headers = business.headers()
    for path in ("/api/v1/platform/invoices", "/api/v1/platform/billing/summary"):
        response = client.get(path, headers=headers)
        assert response.status_code in (401, 403), f"{path}: {response.status_code}"

    run = client.post("/api/v1/platform/billing/run", headers=headers)
    assert run.status_code in (401, 403), run.status_code


def test_a_business_cannot_read_another_shops_billing(client, business, other_business):
    response = client.get(
        f"/api/v1/platform/tenants/{other_business.tenant.id}/billing",
        headers=business.headers(),
    )
    assert response.status_code in (401, 403)


def test_the_api_refuses_a_credit_note_with_the_methods_it_does_take(
    client, db, business, admin_headers
):
    _priced(business)
    _paid_until(business, None)
    invoice = _invoice(business)

    response = client.post(
        f"/api/v1/platform/invoices/{invoice.id}/payments",
        json={"amount": "800.00", "method": "credit_note"},
        headers=admin_headers,
    )
    assert response.status_code == 422, response.json()
    assert "telebirr" in str(response.json()["details"]["allowed"])


def test_recording_a_payment_is_audited_against_the_shop(
    client, db, business, admin_headers
):
    """The shop's own audit log shows what the platform recorded about it."""
    from app.models.platform import AuditEvent

    _priced(business, price="800.00")
    _paid_until(business, None)
    invoice = _invoice(business)
    client.post(
        f"/api/v1/platform/invoices/{invoice.id}/payments",
        json={"amount": "800.00", "method": "telebirr", "reference": "TB-4242"},
        headers=admin_headers,
    ).raise_for_status()

    actions = {
        event.action
        for event in db.query(AuditEvent)
        .filter(AuditEvent.tenant_id == business.tenant.id)
        .all()
    }
    assert "subscription.payment_recorded" in actions
    assert "subscription.renewed" in actions

    recorded = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == "subscription.payment_recorded")
        .one()
    )
    assert recorded.actor_label == "billing@estock.et"
    assert "TB-4242" in (recorded.payload_json or "")


def test_a_shop_is_put_on_a_plan_through_the_api(client, db, business, admin_headers):
    """Without this there is no price, so nothing could ever be billed.

    Plans and invoices both existed; the step between them did not.
    """
    from app.models.platform import SubscriptionPlan

    plan = SubscriptionPlan(
        code="growth-test", name="Growth", monthly_price=Decimal("1500.00"), max_branches=5
    )
    db.add(plan)
    db.flush()

    moved = client.patch(
        f"/api/v1/platform/tenants/{business.tenant.id}/plan",
        json={"plan_id": str(plan.id), "reason": "Signed up for Growth"},
        headers=admin_headers,
    )
    assert moved.status_code == 200, moved.json()
    assert moved.json()["plan"]["monthly_price"] == "1500.00"
    assert {limit["name"] for limit in moved.json()["limits"]} == {
        "branches",
        "users",
        "products",
    }

    # And now it has a price to be billed.
    _paid_until(business, None)
    invoice = _invoice(business)
    assert Decimal(invoice.amount) == Decimal("1500.00")


def test_changing_plan_takes_no_data_away(client, db, business, admin_headers):
    """The same promise trial expiry and plan limits already make."""
    from app.models.platform import SubscriptionPlan

    for i in range(3):
        business.add_product(f"Thing {i}", opening_stock=None)
    tiny = SubscriptionPlan(code="tiny-test", name="Tiny", max_products=1)
    db.add(tiny)
    db.flush()

    client.patch(
        f"/api/v1/platform/tenants/{business.tenant.id}/plan",
        json={"plan_id": str(tiny.id)},
        headers=admin_headers,
    ).raise_for_status()

    from app.models.catalogue import Product

    kept = db.query(Product).filter(Product.tenant_id == business.tenant.id).count()
    assert kept == 3, "a smaller plan must not delete what the shop already has"


def test_the_daily_jobs_bill_and_lapse(client, db, business, admin_headers):
    """Both runs are wired into the job the platform owner can trigger."""
    _priced(business)
    subscription = _subscription(business)
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_ends_on = date.today() + timedelta(days=2)
    business.tenant.status = TenantStatus.ACTIVE
    db.flush()

    response = client.post("/api/v1/platform/jobs/run-daily", headers=admin_headers)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert "invoices_raised" in body
    assert "subscriptions_lapsed" in body
    assert body["invoices_raised"] == 1


def test_billing_runs_before_lapsing_so_a_shop_is_asked_while_it_still_has_service(
    client, db, business, admin_headers
):
    """Ordering matters: lapse first and the invoice is raised after cut-off."""
    _priced(business)
    subscription = _subscription(business)
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_ends_on = date.today() - timedelta(days=1)
    business.tenant.status = TenantStatus.ACTIVE
    db.flush()

    body = client.post(
        "/api/v1/platform/jobs/run-daily", headers=admin_headers
    ).json()

    # Billed for the period ahead, and only then set read-only for the one
    # that has run out — so there is an invoice waiting to be paid.
    assert body["invoices_raised"] == 1
    assert body["subscriptions_lapsed"] == 1
    db.refresh(business.tenant)
    assert business.tenant.status == TenantStatus.RESTRICTED

    rows, _ = billing.invoices_for_tenant(db, business.tenant.id)
    assert rows, "the shop has something to pay to come back"
    assert billing.balance_due(rows[0].invoice, paid=rows[0].paid) > 0


def test_the_summary_stays_one_query_however_many_invoices(db, business, counted):
    """It is read on every visit to the platform screen and grows forever.

    Deriving the totals from the invoice objects would pull every payment ever
    recorded into memory to add up a handful of figures. One query returns one
    row per invoice with its payments already summed, so the count does not
    move as the platform fills up.
    """
    _priced(business, price="800.00")
    _paid_until(business, None)
    start = TODAY
    for month in range(6):
        invoice = _invoice(
            business,
            period_start=start + timedelta(days=30 * month),
            period_end=start + timedelta(days=30 * month + 29),
        )
        _pay(business, invoice, "400.00")
        _pay(business, invoice, "400.00")
    db.flush()

    counter = counted()
    summary = billing.billing_summary(db, today=TODAY)
    queries = counter.total

    assert summary.billed == Decimal("4800.00")
    assert summary.collected == Decimal("4800.00")
    assert queries == 1, f"expected one aggregate query, got {queries}"


def test_walking_the_objects_would_have_cost_more_than_one_query(
    db, business, counted
):
    """Guards the test above from passing vacuously.

    Loading the invoices and walking ``.payments`` — what the summary used to
    do — takes more than one query, so ``== 1`` really is pinning the
    aggregate rather than restating what any implementation would score.
    """
    from sqlalchemy import select

    from app.models.platform import SubscriptionInvoice

    _priced(business, price="800.00")
    _paid_until(business, None)
    for month in range(6):
        invoice = _invoice(
            business,
            period_start=TODAY + timedelta(days=30 * month),
            period_end=TODAY + timedelta(days=30 * month + 29),
        )
        _pay(business, invoice, "800.00")
    db.flush()
    db.expire_all()

    counter = counted()
    invoices = db.execute(select(SubscriptionInvoice)).scalars().all()
    walked = sum((billing.amount_paid(i) for i in invoices), Decimal("0.00"))

    assert walked == Decimal("4800.00")
    assert counter.total > 1, "the object-walking shape should cost more than one"


def test_filtering_by_status_does_not_walk_every_payment_row(db, business, counted):
    """The status rules stay in Python; the money still comes from SQL.

    Status is derived, so filtering by it cannot be a WHERE clause without
    writing the rules out a second time — which is how a derived status starts
    disagreeing with itself. What the filter must not do is load every payment
    row of every invoice to find out what each one is paid.
    """
    _priced(business, price="800.00")
    _paid_until(business, None)
    for month in range(6):
        invoice = _invoice(
            business,
            period_start=TODAY + timedelta(days=30 * month),
            period_end=TODAY + timedelta(days=30 * month + 29),
        )
        _pay(business, invoice, "800.00")
    db.flush()
    db.expire_all()

    counter = counted()
    paid_rows, total = billing.list_invoices(
        db, status=SubscriptionInvoiceStatus.PAID, today=TODAY
    )
    queries = counter.total

    assert total == 6
    assert len(paid_rows) == 6
    assert all(row.paid == Decimal("800.00") for row in paid_rows)
    assert queries == 1, f"expected one query for the page, got {queries}"


def test_a_shops_own_screen_shows_the_payments_behind_each_invoice(
    client, db, business, admin_headers
):
    """"Paid" is not enough; a shop wants to see what it paid and how.

    The list path prices invoices from one aggregate and does not load their
    payment rows, so a screen that shows them has to ask. This test exists
    because that distinction broke the detail view once already.
    """
    _priced(business, price="800.00")
    _paid_until(business, None)
    invoice = _invoice(business)
    _pay(business, invoice, "800.00", method=PaymentMethod.TELEBIRR, reference="TB-7001")

    page = client.get(
        f"/api/v1/platform/tenants/{business.tenant.id}/billing", headers=admin_headers
    )
    assert page.status_code == 200, page.json()
    shown = page.json()["invoices"][0]
    assert shown["payments"], "the platform's own detail view lists the payments"
    assert shown["payments"][0]["reference"] == "TB-7001"
    assert shown["payments"][0]["method"] == "telebirr"

    mine = client.get("/api/v1/subscription", headers=business.headers())
    assert mine.json()["billing"]["invoices"][0]["payments"][0]["reference"] == "TB-7001"


def test_a_listed_invoice_refuses_to_pretend_it_has_no_payments(db, business):
    """Reaching for payments a list did not load is an error, not an empty list.

    The alternative — a lazy load suppressed to nothing — would have an
    invoice quietly report that it was never paid, which is the worst answer
    available.
    """
    from sqlalchemy.exc import InvalidRequestError

    _priced(business, price="800.00")
    _paid_until(business, None)
    invoice = _invoice(business)
    _pay(business, invoice, "800.00")
    db.flush()
    db.expire_all()

    rows, _ = billing.list_invoices(db)
    assert rows
    # The money is there, from the aggregate.
    assert rows[0].paid == Decimal("800.00")
    # The rows behind it were not asked for, so touching them says so.
    with pytest.raises(InvalidRequestError):
        _ = rows[0].invoice.payments

    # And asking loads them.
    with_rows, _ = billing.invoices_for_tenant(
        db, business.tenant.id, with_payments=True
    )
    assert len(with_rows[0].invoice.payments) == 1
