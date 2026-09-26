"""Credit balances, due dates, overdue rules, payments and reminders (PRD 11, 21)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.errors import ConflictError, PermissionDenied, ValidationError
from app.core.permissions import Permission, RoleName
from app.models.credit import (
    CreditKind,
    CreditStatus,
    FollowUpKind,
    ReminderKind,
    ReminderStatus,
)
from app.models.sales import PaymentMethod
from app.services.credit import (
    add_follow_up,
    cancel_transaction,
    change_due_date,
    check_credit_limit,
    create_credit_transaction,
    derive_status,
    is_overdue,
    record_payment,
    resolve_due_date,
    reverse_payment,
)


@pytest.fixture
def credit_sale(business):
    """A 1,000 ETB credit sale with 300 paid at the till."""
    customer = business.add_customer("Almaz Tadesse", phone="+251911000111")
    product = business.add_product("Cement", selling_price="1000.00", opening_stock="50")
    result = business.sell(
        product, quantity="1", paid="300", customer_id=customer.id, due_date_preset="30_days"
    )
    return result


# --------------------------------------------------------------------------- #
# Balances
# --------------------------------------------------------------------------- #


def test_credit_sale_opens_a_receivable_for_the_unpaid_balance(business, credit_sale):
    transaction = credit_sale.credit_transaction
    assert transaction is not None
    assert transaction.kind == CreditKind.RECEIVABLE
    assert transaction.original_amount == Decimal("1000.00")
    assert transaction.amount_paid == Decimal("300.00")
    assert transaction.balance == Decimal("700.00")
    assert transaction.status == CreditStatus.PARTIALLY_PAID


def test_the_till_payment_is_not_counted_twice(business, credit_sale):
    """One payment ledger: the sale and the receivable read the same rows."""
    sale = credit_sale.sale
    transaction = credit_sale.credit_transaction
    assert sale.amount_paid == Decimal("300.00")
    assert transaction.amount_paid == Decimal("300.00")
    assert len(transaction.payments) == 1
    assert transaction.payments[0].sale_id == sale.id


def test_a_fully_paid_sale_opens_no_receivable(business):
    product = business.add_product("Paid up", selling_price="100.00", opening_stock="10")
    result = business.sell(product, quantity="1")
    assert result.credit_transaction is None


def test_partial_payments_reduce_the_balance(business, credit_sale):
    transaction = credit_sale.credit_transaction
    record_payment(
        business.db,
        business.ctx,
        transaction.id,
        amount=Decimal("200.00"),
        method=PaymentMethod.TELEBIRR,
    )
    business.db.refresh(transaction)
    assert transaction.amount_paid == Decimal("500.00")
    assert transaction.balance == Decimal("500.00")
    assert transaction.status == CreditStatus.PARTIALLY_PAID


def test_a_final_payment_settles_the_transaction(business, credit_sale):
    transaction = credit_sale.credit_transaction
    record_payment(
        business.db,
        business.ctx,
        transaction.id,
        amount=Decimal("700.00"),
        method=PaymentMethod.CASH,
    )
    business.db.refresh(transaction)
    assert transaction.balance == Decimal("0.00")
    assert transaction.status == CreditStatus.PAID
    assert transaction.settled_at is not None


def test_overpayment_is_refused_and_reports_the_balance(business, credit_sale):
    transaction = credit_sale.credit_transaction
    with pytest.raises(ValidationError) as exc:
        record_payment(
            business.db,
            business.ctx,
            transaction.id,
            amount=Decimal("800.00"),
            method=PaymentMethod.CASH,
        )
    assert exc.value.code == "overpayment"
    assert "700.00" in str(exc.value)


def test_overpayment_needs_the_override_permission(business, credit_sale):
    _, salesperson = business.add_user(RoleName.SALESPERSON)
    with pytest.raises(PermissionDenied):
        record_payment(
            business.db,
            salesperson,
            credit_sale.credit_transaction.id,
            amount=Decimal("800.00"),
            method=PaymentMethod.CASH,
            allow_overpayment=True,
        )


def test_a_zero_or_negative_payment_is_refused(business, credit_sale):
    with pytest.raises(ValidationError, match="must be positive"):
        record_payment(
            business.db,
            business.ctx,
            credit_sale.credit_transaction.id,
            amount=Decimal("0"),
            method=PaymentMethod.CASH,
        )


def test_a_duplicate_payment_submission_is_recorded_once(business, credit_sale):
    """Retries must not double-count money received (PRD 11.6)."""
    transaction = credit_sale.credit_transaction
    first = record_payment(
        business.db,
        business.ctx,
        transaction.id,
        amount=Decimal("100.00"),
        method=PaymentMethod.CASH,
        idempotency_key="pay-once",
    )
    second = record_payment(
        business.db,
        business.ctx,
        transaction.id,
        amount=Decimal("100.00"),
        method=PaymentMethod.CASH,
        idempotency_key="pay-once",
    )
    assert first.id == second.id
    business.db.refresh(transaction)
    assert transaction.amount_paid == Decimal("400.00")


def test_reversing_a_payment_restores_the_balance_and_keeps_the_row(business, credit_sale):
    transaction = credit_sale.credit_transaction
    payment = record_payment(
        business.db,
        business.ctx,
        transaction.id,
        amount=Decimal("700.00"),
        method=PaymentMethod.CASH,
    )
    business.db.refresh(transaction)
    assert transaction.status == CreditStatus.PAID

    reverse_payment(business.db, business.ctx, payment.id, reason="Cheque bounced")
    business.db.refresh(transaction)

    assert payment.is_reversed is True
    assert payment.reversal_reason == "Cheque bounced"
    assert transaction.balance == Decimal("700.00")
    assert transaction.status != CreditStatus.PAID


def test_a_payment_cannot_be_reversed_twice(business, credit_sale):
    payment = record_payment(
        business.db,
        business.ctx,
        credit_sale.credit_transaction.id,
        amount=Decimal("100.00"),
        method=PaymentMethod.CASH,
    )
    reverse_payment(business.db, business.ctx, payment.id, reason="Wrong customer")
    with pytest.raises(ConflictError):
        reverse_payment(business.db, business.ctx, payment.id, reason="Again")


# --------------------------------------------------------------------------- #
# Due dates and overdue classification
# --------------------------------------------------------------------------- #


def test_due_date_presets(today):
    assert resolve_due_date("today", None, today=today) == today
    assert resolve_due_date("tomorrow", None, today=today) == today + timedelta(days=1)
    assert resolve_due_date("30_days", None, today=today) == today + timedelta(days=30)
    assert resolve_due_date(None, None, today=today) is None
    assert resolve_due_date(None, date(2030, 1, 1), today=today) == date(2030, 1, 1)


def test_an_unknown_preset_is_rejected(today):
    with pytest.raises(ValidationError, match="Unknown due-date choice"):
        resolve_due_date("next_year", None, today=today)


def test_a_balance_without_a_due_date_is_never_overdue(business, today):
    """Elapsed time alone does not make a balance overdue (PRD 11.3)."""
    customer = business.add_customer("No due date")
    transaction = create_credit_transaction(
        business.db,
        business.ctx,
        kind=CreditKind.RECEIVABLE,
        amount=Decimal("500.00"),
        branch_id=business.branch.id,
        customer_id=customer.id,
        issued_on=today - timedelta(days=400),
        due_date=None,
    )
    assert is_overdue(transaction, today=today) is False
    assert derive_status(transaction, today=today) == CreditStatus.OUTSTANDING


def test_a_balance_becomes_overdue_the_day_after_its_due_date(business, today):
    customer = business.add_customer("Due yesterday")
    transaction = create_credit_transaction(
        business.db,
        business.ctx,
        kind=CreditKind.RECEIVABLE,
        amount=Decimal("500.00"),
        branch_id=business.branch.id,
        customer_id=customer.id,
        due_date=today - timedelta(days=1),
    )
    assert is_overdue(transaction, today=today) is True
    assert derive_status(transaction, today=today) == CreditStatus.OVERDUE


def test_a_balance_due_today_is_not_yet_overdue(business, today):
    customer = business.add_customer("Due today")
    transaction = create_credit_transaction(
        business.db,
        business.ctx,
        kind=CreditKind.RECEIVABLE,
        amount=Decimal("500.00"),
        branch_id=business.branch.id,
        customer_id=customer.id,
        due_date=today,
    )
    assert is_overdue(transaction, today=today) is False
    assert derive_status(transaction, today=today) == CreditStatus.OUTSTANDING


def test_a_paid_transaction_is_never_overdue(business, today):
    customer = business.add_customer("Paid late but paid")
    transaction = create_credit_transaction(
        business.db,
        business.ctx,
        kind=CreditKind.RECEIVABLE,
        amount=Decimal("500.00"),
        branch_id=business.branch.id,
        customer_id=customer.id,
        due_date=today - timedelta(days=30),
    )
    record_payment(
        business.db,
        business.ctx,
        transaction.id,
        amount=Decimal("500.00"),
        method=PaymentMethod.CASH,
    )
    business.db.refresh(transaction)
    assert is_overdue(transaction, today=today) is False
    assert transaction.status == CreditStatus.PAID


def test_status_is_never_paid_with_a_remaining_balance(business, credit_sale):
    """Derived status must never contradict the balance (PRD 11.7)."""
    transaction = credit_sale.credit_transaction
    transaction.status = CreditStatus.PAID  # a hand-set value
    assert derive_status(transaction) != CreditStatus.PAID
    assert transaction.balance > 0


def test_changing_the_due_date_reschedules_reminders_and_status(business, today):
    customer = business.add_customer("Extended terms")
    transaction = create_credit_transaction(
        business.db,
        business.ctx,
        kind=CreditKind.RECEIVABLE,
        amount=Decimal("500.00"),
        branch_id=business.branch.id,
        customer_id=customer.id,
        due_date=today - timedelta(days=5),
    )
    assert derive_status(transaction, today=today) == CreditStatus.OVERDUE
    scheduled_before = [
        r.id for r in transaction.reminders if r.status == ReminderStatus.SCHEDULED
    ]

    change_due_date(
        business.db, business.ctx, transaction.id, due_date=today + timedelta(days=14)
    )
    business.db.refresh(transaction)

    assert transaction.status == CreditStatus.OUTSTANDING
    still_scheduled = {
        r.id for r in transaction.reminders if r.status == ReminderStatus.SCHEDULED
    }
    assert not (set(scheduled_before) & still_scheduled)
    assert still_scheduled


def test_changing_a_due_date_is_audited(business, credit_sale, today):
    from app.models.platform import AuditEvent

    change_due_date(
        business.db,
        business.ctx,
        credit_sale.credit_transaction.id,
        due_date=today + timedelta(days=60),
    )
    audits = (
        business.db.query(AuditEvent)
        .filter(AuditEvent.action == "credit.due_date_changed")
        .all()
    )
    assert len(audits) == 1


def test_changing_a_due_date_needs_the_permission(business, credit_sale, today):
    _, salesperson = business.add_user(RoleName.SALESPERSON)
    assert Permission.CREDIT_DUEDATE_CHANGE not in salesperson.permissions
    with pytest.raises(PermissionDenied):
        change_due_date(
            business.db, salesperson, credit_sale.credit_transaction.id, due_date=today
        )


# --------------------------------------------------------------------------- #
# Cancellation and follow-up
# --------------------------------------------------------------------------- #


def test_cancelling_keeps_the_record_and_needs_a_reason(business, credit_sale):
    transaction = credit_sale.credit_transaction
    with pytest.raises(ValidationError, match="reason is required"):
        cancel_transaction(business.db, business.ctx, transaction.id, reason="")

    cancel_transaction(business.db, business.ctx, transaction.id, reason="Written off")
    business.db.refresh(transaction)
    assert transaction.status == CreditStatus.CANCELLED
    assert transaction.cancel_reason == "Written off"
    assert transaction.original_amount == Decimal("1000.00")


def test_no_payment_can_be_recorded_against_a_cancelled_transaction(business, credit_sale):
    transaction = credit_sale.credit_transaction
    cancel_transaction(business.db, business.ctx, transaction.id, reason="Written off")
    with pytest.raises(ConflictError, match="cancelled"):
        record_payment(
            business.db,
            business.ctx,
            transaction.id,
            amount=Decimal("100"),
            method=PaymentMethod.CASH,
        )


def test_follow_up_activity_does_not_change_the_balance(business, credit_sale, today):
    """Logging a call is never proof of payment (PRD 11.6)."""
    transaction = credit_sale.credit_transaction
    balance_before = transaction.balance

    add_follow_up(
        business.db,
        business.ctx,
        transaction.id,
        kind=FollowUpKind.PROMISE_TO_PAY,
        note="Said they will pay on Friday",
        promised_amount=Decimal("700.00"),
        promised_date=today + timedelta(days=3),
    )
    business.db.refresh(transaction)

    assert transaction.balance == balance_before
    assert transaction.status != CreditStatus.PAID
    assert len(transaction.activities) == 1


# --------------------------------------------------------------------------- #
# Reminders
# --------------------------------------------------------------------------- #


def test_reminders_are_scheduled_for_a_due_date(business, today):
    customer = business.add_customer("Reminder me")
    transaction = create_credit_transaction(
        business.db,
        business.ctx,
        kind=CreditKind.RECEIVABLE,
        amount=Decimal("500.00"),
        branch_id=business.branch.id,
        customer_id=customer.id,
        due_date=today + timedelta(days=10),
    )
    kinds = {r.kind for r in transaction.reminders}
    assert kinds == {ReminderKind.DUE_SOON, ReminderKind.DUE_TODAY, ReminderKind.OVERDUE}


def test_no_reminders_without_a_due_date(business):
    customer = business.add_customer("No date")
    transaction = create_credit_transaction(
        business.db,
        business.ctx,
        kind=CreditKind.RECEIVABLE,
        amount=Decimal("500.00"),
        branch_id=business.branch.id,
        customer_id=customer.id,
        due_date=None,
    )
    assert transaction.reminders == []


def test_settling_a_balance_cancels_its_pending_reminders(business, credit_sale):
    transaction = credit_sale.credit_transaction
    assert any(r.status == ReminderStatus.SCHEDULED for r in transaction.reminders)

    record_payment(
        business.db,
        business.ctx,
        transaction.id,
        amount=Decimal("700.00"),
        method=PaymentMethod.CASH,
    )
    business.db.refresh(transaction)
    assert all(r.status != ReminderStatus.SCHEDULED for r in transaction.reminders)


def test_reminder_delivery_notifies_authorised_staff_only(business, credit_sale, today):
    """Reminders are internal; nothing is sent to the customer (PRD 11.4)."""
    from app.models.system import Notification, NotificationKind
    from app.services.notifications import run_due_reminders

    transaction = credit_sale.credit_transaction
    for reminder in transaction.reminders:
        reminder.scheduled_for = today
    business.db.flush()

    stock_user, stock_ctx = business.add_user(RoleName.STOCK_USER)
    assert Permission.CREDIT_VIEW not in stock_ctx.permissions

    result = run_due_reminders(business.db, on=today)
    assert result.delivered > 0

    notifications = (
        business.db.query(Notification)
        .filter(Notification.kind == NotificationKind.CREDIT_REMINDER)
        .all()
    )
    recipients = {n.user_id for n in notifications}
    assert business.owner.id in recipients
    assert stock_user.id not in recipients
    assert all("no message has been sent" in (n.body or "") for n in notifications)


def test_reminders_for_a_settled_balance_are_skipped(business, credit_sale, today):
    from app.services.notifications import run_due_reminders

    transaction = credit_sale.credit_transaction
    record_payment(
        business.db,
        business.ctx,
        transaction.id,
        amount=Decimal("700.00"),
        method=PaymentMethod.CASH,
    )
    for reminder in transaction.reminders:
        reminder.status = ReminderStatus.SCHEDULED
        reminder.scheduled_for = today
    business.db.flush()

    result = run_due_reminders(business.db, on=today)
    assert result.delivered == 0
    assert result.skipped_settled > 0


# --------------------------------------------------------------------------- #
# Credit limits
# --------------------------------------------------------------------------- #


def test_credit_limit_warns_but_allows(business):
    customer = business.add_customer(
        "Warn me", credit_limit=Decimal("1000"), credit_limit_behaviour="warn"
    )
    check = check_credit_limit(business.db, business.ctx, customer.id, Decimal("1500"))
    assert check.allowed is True
    assert check.message is not None


def test_credit_limit_can_block_a_sale(business):
    customer = business.add_customer(
        "Blocked", credit_limit=Decimal("100"), credit_limit_behaviour="block"
    )
    product = business.add_product("Expensive", selling_price="5000.00", opening_stock="5")
    with pytest.raises(ConflictError, match="credit limit"):
        business.sell(product, quantity="1", paid="0", customer_id=customer.id)


def test_a_blocking_limit_cannot_be_overridden(business):
    """"Block" means block, even for a user holding the override permission."""
    customer = business.add_customer(
        "Blocked", credit_limit=Decimal("100"), credit_limit_behaviour="block"
    )
    product = business.add_product("Expensive", selling_price="5000.00", opening_stock="5")
    assert Permission.CREDIT_LIMIT_OVERRIDE in business.ctx.permissions
    with pytest.raises(ConflictError):
        business.sell(
            product,
            quantity="1",
            paid="0",
            customer_id=customer.id,
            override_credit_limit=True,
        )


def test_approval_behaviour_allows_an_authorised_override(business):
    customer = business.add_customer(
        "Needs approval",
        credit_limit=Decimal("100"),
        credit_limit_behaviour="require_approval",
    )
    product = business.add_product("Expensive", selling_price="5000.00", opening_stock="5")
    result = business.sell(
        product, quantity="1", paid="0", customer_id=customer.id, override_credit_limit=True
    )
    assert result.credit_transaction is not None
    assert result.warnings


def test_no_limit_means_no_restriction(business):
    customer = business.add_customer("No limit")
    check = check_credit_limit(business.db, business.ctx, customer.id, Decimal("99999"))
    assert check.allowed is True
    assert check.limit is None


def test_a_credit_sale_can_require_a_named_customer(business):
    product = business.add_product("On credit", selling_price="500.00", opening_stock="10")
    assert business.tenant.require_customer_for_credit is True
    with pytest.raises(ValidationError) as exc:
        business.sell(product, quantity="1", paid="0")
    assert exc.value.code == "customer_required_for_credit"


def test_anonymous_credit_is_possible_when_the_business_allows_it(business):
    business.tenant.require_customer_for_credit = False
    business.db.flush()
    product = business.add_product("On credit", selling_price="500.00", opening_stock="10")
    result = business.sell(product, quantity="1", paid="0")
    assert result.credit_transaction is not None
    assert result.credit_transaction.customer_id is None


def test_holding_the_override_permission_is_not_the_same_as_using_it(business):
    """"Require approval" means an explicit, audited approval (PRD 11.7, 20)."""
    from app.models.platform import AuditEvent

    customer = business.add_customer(
        "Needs approval",
        credit_limit=Decimal("100"),
        credit_limit_behaviour="require_approval",
    )
    product = business.add_product("Expensive", selling_price="5000.00", opening_stock="5")
    assert Permission.CREDIT_LIMIT_OVERRIDE in business.ctx.permissions

    with pytest.raises(ConflictError, match="credit limit"):
        business.sell(product, quantity="1", paid="0", customer_id=customer.id)

    business.sell(
        product, quantity="1", paid="0", customer_id=customer.id, override_credit_limit=True
    )
    overrides = (
        business.db.query(AuditEvent)
        .filter(AuditEvent.action == "credit.limit_overridden")
        .all()
    )
    assert len(overrides) == 1
    assert overrides[0].actor_user_id == business.owner.id


def test_a_salesperson_cannot_touch_supplier_payables(business):
    """Payables are purchasing data; a cashier records customer payments only."""
    from app.services.purchasing import PurchaseInput, PurchaseLineInput, receive_purchase

    product = business.add_product("Stocked", opening_stock=None, purchase_price=None)
    payable = receive_purchase(
        business.db,
        business.ctx,
        PurchaseInput(
            lines=[
                PurchaseLineInput(
                    variant_id=product.default_variant.id,
                    quantity=Decimal("10"),
                    unit_cost=Decimal("50"),
                )
            ],
            amount_paid=Decimal("0"),
        ),
    ).credit_transaction

    _, salesperson = business.add_user(RoleName.SALESPERSON)
    assert Permission.CREDIT_PAYMENT_RECORD in salesperson.permissions
    with pytest.raises(PermissionDenied):
        record_payment(
            business.db, salesperson, payable.id, amount=Decimal("100"), method=PaymentMethod.CASH
        )
    with pytest.raises(PermissionDenied):
        add_follow_up(business.db, salesperson, payable.id, kind=FollowUpKind.CALLED)


def test_a_balance_with_no_branch_still_counts_in_the_summary(business, today):
    """``IN (…, NULL)`` never matches; business-wide balances must not vanish."""
    from app.services.reports import credit_summary

    customer = business.add_customer("Head office account")
    create_credit_transaction(
        business.db,
        business.ctx,
        kind=CreditKind.RECEIVABLE,
        amount=Decimal("750.00"),
        branch_id=None,
        customer_id=customer.id,
    )
    summary = credit_summary(business.db, business.ctx, CreditKind.RECEIVABLE, today=today)
    assert summary.total_outstanding == Decimal("750.00")
    assert summary.transaction_count == 1


def test_the_due_date_of_a_cancelled_balance_cannot_be_changed(business, credit_sale, today):
    transaction = credit_sale.credit_transaction
    cancel_transaction(business.db, business.ctx, transaction.id, reason="Written off")
    with pytest.raises(ConflictError):
        change_due_date(business.db, business.ctx, transaction.id, due_date=today)
