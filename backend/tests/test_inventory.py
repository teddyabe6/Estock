"""Stock ledger, balances, transfers, counts and reconciliation (PRD 9, 21)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.errors import ConflictError, InsufficientStock, ValidationError
from app.models.inventory import MovementReason, StockMovement, TransferStatus
from app.services.inventory import (
    StockPosting,
    adjust_stock,
    available_quantity,
    classify_stock_level,
    create_transfer,
    dispatch_transfer,
    get_balance,
    low_stock_items,
    post_count,
    post_movement,
    receive_transfer,
    reconcile_balances,
    record_count_line,
    start_count,
    update_average_cost,
)


def test_opening_stock_creates_an_auditable_movement(business):
    """Opening stock is a real movement, never a silent balance (PRD 8.3)."""
    product = business.add_product("Sugar", opening_stock="25")
    variant = product.default_variant

    movements = (
        business.db.query(StockMovement)
        .filter(StockMovement.variant_id == variant.id)
        .all()
    )
    assert len(movements) == 1
    assert movements[0].reason == MovementReason.OPENING
    assert movements[0].quantity == Decimal("25.000")
    assert movements[0].created_by_id == business.owner.id
    assert get_balance(business.db, business.tenant.id, variant.id, business.location.id) == Decimal("25.000")


def test_balance_after_is_recorded_on_every_movement(business):
    product = business.add_product("Rice", opening_stock="10")
    variant = product.default_variant

    post_movement(
        business.db,
        business.ctx,
        StockPosting(
            variant_id=variant.id,
            location_id=business.location.id,
            quantity=Decimal("-3"),
            reason=MovementReason.SALE,
        ),
    )
    movements = (
        business.db.query(StockMovement)
        .filter(StockMovement.variant_id == variant.id)
        .order_by(StockMovement.balance_after)
        .all()
    )
    assert [m.balance_after for m in movements] == [Decimal("7.000"), Decimal("10.000")]


def test_negative_stock_is_refused_by_default(business):
    """Prevent negative stock unless the business has explicitly allowed it (PRD 9)."""
    product = business.add_product("Oil", opening_stock="2")
    with pytest.raises(InsufficientStock) as exc:
        post_movement(
            business.db,
            business.ctx,
            StockPosting(
                variant_id=product.default_variant.id,
                location_id=business.location.id,
                quantity=Decimal("-5"),
                reason=MovementReason.SALE,
            ),
        )
    assert "2" in str(exc.value)


def test_negative_stock_is_allowed_and_audited_when_enabled(business):
    from app.models.platform import AuditEvent

    business.tenant.allow_negative_stock = True
    business.db.flush()
    product = business.add_product("Oil", opening_stock="2")

    post_movement(
        business.db,
        business.ctx,
        StockPosting(
            variant_id=product.default_variant.id,
            location_id=business.location.id,
            quantity=Decimal("-5"),
            reason=MovementReason.SALE,
        ),
    )
    balance = get_balance(
        business.db, business.tenant.id, product.default_variant.id, business.location.id
    )
    assert balance == Decimal("-3.000")
    audits = (
        business.db.query(AuditEvent)
        .filter(AuditEvent.action == "stock.negative_allowed")
        .all()
    )
    assert len(audits) == 1


def test_movement_reason_must_match_the_direction(business):
    product = business.add_product("Flour", opening_stock="5")
    with pytest.raises(ValidationError, match="must reduce stock"):
        post_movement(
            business.db,
            business.ctx,
            StockPosting(
                variant_id=product.default_variant.id,
                location_id=business.location.id,
                quantity=Decimal("3"),
                reason=MovementReason.SALE,
            ),
        )


def test_zero_quantity_movements_are_rejected(business):
    product = business.add_product("Salt", opening_stock="5")
    with pytest.raises(ValidationError, match="cannot be zero"):
        post_movement(
            business.db,
            business.ctx,
            StockPosting(
                variant_id=product.default_variant.id,
                location_id=business.location.id,
                quantity=Decimal("0"),
                reason=MovementReason.ADJUSTMENT,
            ),
        )


def test_idempotency_key_prevents_a_duplicate_posting(business):
    """A retried request must not post the same stock effect twice (PRD 20)."""
    product = business.add_product("Tea", opening_stock="10")
    posting = StockPosting(
        variant_id=product.default_variant.id,
        location_id=business.location.id,
        quantity=Decimal("-2"),
        reason=MovementReason.SALE,
        idempotency_key="retry-me",
    )
    first = post_movement(business.db, business.ctx, posting)
    second = post_movement(business.db, business.ctx, posting)

    assert first.id == second.id
    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, business.location.id
    ) == Decimal("8.000")


def test_adjustment_requires_a_reason_note(business):
    product = business.add_product("Coffee", opening_stock="10")
    with pytest.raises(ValidationError, match="reason note is required"):
        adjust_stock(
            business.db,
            business.ctx,
            variant_id=product.default_variant.id,
            location_id=business.location.id,
            quantity=Decimal("-1"),
            reason=MovementReason.DAMAGE,
            note="",
        )


def test_damage_cannot_increase_stock(business):
    product = business.add_product("Coffee", opening_stock="10")
    with pytest.raises(ValidationError, match="must reduce stock"):
        adjust_stock(
            business.db,
            business.ctx,
            variant_id=product.default_variant.id,
            location_id=business.location.id,
            quantity=Decimal("5"),
            reason=MovementReason.DAMAGE,
            note="Water damage",
        )


def test_adjustment_is_audited(business):
    from app.models.platform import AuditEvent

    product = business.add_product("Coffee", opening_stock="10")
    adjust_stock(
        business.db,
        business.ctx,
        variant_id=product.default_variant.id,
        location_id=business.location.id,
        quantity=Decimal("-2"),
        reason=MovementReason.DAMAGE,
        note="Spilled in transit",
    )
    audit = (
        business.db.query(AuditEvent)
        .filter(AuditEvent.action == "stock.adjusted")
        .one()
    )
    assert "Spilled in transit" in (audit.payload_json or "")


# --------------------------------------------------------------------------- #
# Transfers
# --------------------------------------------------------------------------- #


def test_transfer_moves_stock_between_branches(business):
    warehouse_branch, warehouse = business.add_branch("Warehouse")
    product = business.add_product("Notebooks", opening_stock="50")
    variant = product.default_variant

    transfer = create_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=warehouse.id,
        lines=[(variant.id, Decimal("20"))],
    )
    assert transfer.status == TransferStatus.DRAFT
    # Nothing moves until dispatch.
    assert get_balance(business.db, business.tenant.id, variant.id, business.location.id) == Decimal("50.000")

    dispatch_transfer(business.db, business.ctx, transfer.id)
    assert get_balance(business.db, business.tenant.id, variant.id, business.location.id) == Decimal("30.000")
    assert get_balance(business.db, business.tenant.id, variant.id, warehouse.id) == Decimal("0.000")

    receive_transfer(business.db, business.ctx, transfer.id)
    assert get_balance(business.db, business.tenant.id, variant.id, warehouse.id) == Decimal("20.000")
    assert available_quantity(business.db, business.tenant.id, variant.id) == Decimal("50.000")


def test_transfer_records_a_receipt_discrepancy(business):
    _, warehouse = business.add_branch("Warehouse")
    product = business.add_product("Pens", opening_stock="100")
    variant = product.default_variant

    transfer = create_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=warehouse.id,
        lines=[(variant.id, Decimal("30"))],
    )
    dispatch_transfer(business.db, business.ctx, transfer.id)
    line = transfer.lines[0]
    receive_transfer(business.db, business.ctx, transfer.id, {line.id: Decimal("28")})

    assert line.quantity_received == Decimal("28.000")
    assert line.discrepancy == Decimal("-2.000")
    # The two missing units are not silently invented at the destination.
    assert get_balance(business.db, business.tenant.id, variant.id, warehouse.id) == Decimal("28.000")


def test_receiving_more_than_dispatched_is_refused(business):
    _, warehouse = business.add_branch("Warehouse")
    product = business.add_product("Pens", opening_stock="100")
    transfer = create_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=warehouse.id,
        lines=[(product.default_variant.id, Decimal("10"))],
    )
    dispatch_transfer(business.db, business.ctx, transfer.id)
    with pytest.raises(ValidationError, match="cannot exceed"):
        receive_transfer(
            business.db, business.ctx, transfer.id, {transfer.lines[0].id: Decimal("12")}
        )


def test_transfer_cannot_be_dispatched_twice(business):
    _, warehouse = business.add_branch("Warehouse")
    product = business.add_product("Pens", opening_stock="100")
    transfer = create_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=warehouse.id,
        lines=[(product.default_variant.id, Decimal("10"))],
    )
    dispatch_transfer(business.db, business.ctx, transfer.id)
    with pytest.raises(ConflictError):
        dispatch_transfer(business.db, business.ctx, transfer.id)


def test_transfer_to_the_same_location_is_refused(business):
    product = business.add_product("Pens", opening_stock="10")
    with pytest.raises(ValidationError, match="two different locations"):
        create_transfer(
            business.db,
            business.ctx,
            from_location_id=business.location.id,
            to_location_id=business.location.id,
            lines=[(product.default_variant.id, Decimal("1"))],
        )


# --------------------------------------------------------------------------- #
# Counts
# --------------------------------------------------------------------------- #


def test_stock_count_posts_the_variance_as_an_adjustment(business):
    """Count, review variance, post — with who, when and why (PRD A5)."""
    product = business.add_product("Bottles", opening_stock="40")
    variant = product.default_variant

    count = start_count(business.db, business.ctx, location_id=business.location.id)
    line = record_count_line(
        business.db,
        business.ctx,
        count.id,
        variant_id=variant.id,
        counted_quantity=Decimal("37"),
        reason="Breakage found during count",
    )
    assert line.expected_quantity == Decimal("40.000")
    assert line.variance == Decimal("-3.000")
    # Nothing has moved yet: the variance is reviewed before it is posted.
    assert get_balance(business.db, business.tenant.id, variant.id, business.location.id) == Decimal("40.000")

    post_count(business.db, business.ctx, count.id)
    assert get_balance(business.db, business.tenant.id, variant.id, business.location.id) == Decimal("37.000")
    assert count.posted_by_id == business.owner.id


def test_a_count_with_no_variance_posts_nothing(business):
    product = business.add_product("Bottles", opening_stock="40")
    count = start_count(business.db, business.ctx, location_id=business.location.id)
    record_count_line(
        business.db,
        business.ctx,
        count.id,
        variant_id=product.default_variant.id,
        counted_quantity=Decimal("40"),
    )
    before = business.db.query(StockMovement).count()
    post_count(business.db, business.ctx, count.id)
    assert business.db.query(StockMovement).count() == before


def test_a_posted_count_cannot_be_posted_again(business):
    product = business.add_product("Bottles", opening_stock="40")
    count = start_count(business.db, business.ctx, location_id=business.location.id)
    record_count_line(
        business.db,
        business.ctx,
        count.id,
        variant_id=product.default_variant.id,
        counted_quantity=Decimal("38"),
    )
    post_count(business.db, business.ctx, count.id)
    with pytest.raises(ConflictError):
        post_count(business.db, business.ctx, count.id)


# --------------------------------------------------------------------------- #
# Costing, alerts and reconciliation
# --------------------------------------------------------------------------- #


def test_weighted_average_cost_after_a_receipt(business):
    product = business.add_product("Sugar", purchase_price="10", opening_stock="10")
    variant = product.default_variant
    assert variant.average_cost == Decimal("10.00")

    update_average_cost(variant, Decimal("10"), Decimal("20"), Decimal("10"))
    assert variant.average_cost == Decimal("15.00")


def test_average_cost_takes_over_when_nothing_is_on_hand(business):
    product = business.add_product("Sugar", purchase_price="10", opening_stock=None)
    variant = product.default_variant
    update_average_cost(variant, Decimal("5"), Decimal("30"), Decimal("0"))
    assert variant.average_cost == Decimal("30")


@pytest.mark.parametrize(
    ("quantity", "min_stock", "reorder", "expected"),
    [
        ("0", "5", "10", "out_of_stock"),
        ("-2", "5", "10", "out_of_stock"),
        ("4", "5", "10", "critical"),
        ("5", "5", "10", "critical"),
        ("8", "5", "10", "warning"),
        ("20", "5", "10", "ok"),
        ("20", None, None, "ok"),
    ],
)
def test_stock_level_classification(quantity, min_stock, reorder, expected):
    assert (
        classify_stock_level(
            Decimal(quantity),
            Decimal(min_stock) if min_stock else None,
            Decimal(reorder) if reorder else None,
        )
        == expected
    )


def test_low_stock_lists_urgent_items_first(business):
    business.add_product("Plenty", opening_stock="100", min_stock="5", reorder_level="10")
    business.add_product("Running low", opening_stock="7", min_stock="5", reorder_level="10")
    business.add_product("Critical", opening_stock="3", min_stock="5", reorder_level="10")
    gone = business.add_product("Gone", opening_stock="1", min_stock="5", reorder_level="10")
    adjust_stock(
        business.db,
        business.ctx,
        variant_id=gone.default_variant.id,
        location_id=business.location.id,
        quantity=Decimal("-1"),
        reason=MovementReason.LOSS,
        note="Stolen",
    )

    items = low_stock_items(business.db, business.tenant.id)
    assert [item.severity for item in items] == ["out_of_stock", "critical", "warning"]
    assert items[0].name == "Gone"


def test_cached_balances_reconcile_with_the_ledger(business):
    """The cached balance is never allowed to drift from the movements (PRD 19)."""
    product = business.add_product("Reconcile me", opening_stock="10")
    business.sell(product, quantity="3")
    adjust_stock(
        business.db,
        business.ctx,
        variant_id=product.default_variant.id,
        location_id=business.location.id,
        quantity=Decimal("-1"),
        reason=MovementReason.DAMAGE,
        note="Dropped",
    )
    assert reconcile_balances(business.db, business.tenant.id) == []


def test_reconciliation_reports_a_tampered_balance(business):
    from app.models.inventory import StockBalance

    product = business.add_product("Tampered", opening_stock="10")
    balance = (
        business.db.query(StockBalance)
        .filter(StockBalance.variant_id == product.default_variant.id)
        .one()
    )
    balance.quantity = Decimal("999")
    business.db.flush()

    discrepancies = reconcile_balances(business.db, business.tenant.id)
    assert len(discrepancies) == 1
    assert discrepancies[0]["ledger_total"] == "10.000"
    assert discrepancies[0]["cached_balance"] == "999"


def test_a_transfer_shortfall_is_posted_as_a_loss_movement(business):
    """Units that left the source and never arrived are a traceable loss (PRD 9)."""
    _, warehouse = business.add_branch("Warehouse")
    product = business.add_product("Pens", opening_stock="100")
    variant = product.default_variant

    transfer = create_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=warehouse.id,
        lines=[(variant.id, Decimal("30"))],
    )
    dispatch_transfer(business.db, business.ctx, transfer.id)
    receive_transfer(business.db, business.ctx, transfer.id, {transfer.lines[0].id: Decimal("28")})

    movements = (
        business.db.query(StockMovement)
        .filter(StockMovement.source_id == transfer.id, StockMovement.location_id == warehouse.id)
        .all()
    )
    by_reason = {m.reason: m for m in movements}
    assert by_reason[MovementReason.TRANSFER_IN].quantity == Decimal("30.000")
    assert by_reason[MovementReason.LOSS].quantity == Decimal("-2.000")
    assert "not received" in (by_reason[MovementReason.LOSS].note or "")
    assert by_reason[MovementReason.LOSS].created_by_id == business.owner.id
    # Source and destination together account for every unit.
    assert available_quantity(business.db, business.tenant.id, variant.id) == Decimal("98.000")
    assert reconcile_balances(business.db, business.tenant.id) == []


def test_receiving_a_transfer_twice_does_not_double_the_loss(business):
    _, warehouse = business.add_branch("Warehouse")
    product = business.add_product("Pens", opening_stock="100")
    transfer = create_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=warehouse.id,
        lines=[(product.default_variant.id, Decimal("10"))],
    )
    dispatch_transfer(business.db, business.ctx, transfer.id)
    receive_transfer(business.db, business.ctx, transfer.id, {transfer.lines[0].id: Decimal("9")})
    with pytest.raises(ConflictError):
        receive_transfer(business.db, business.ctx, transfer.id)
    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, warehouse.id
    ) == Decimal("9.000")
