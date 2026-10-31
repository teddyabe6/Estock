"""The owner's view across branches, opening stock, and inter-branch requests.

These three hang together: a branch is created empty, somebody has to say what
is actually on its shelves, and once it is trading it has to be able to ask
another branch for more (PRD 9).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.errors import (
    ConflictError,
    InsufficientStock,
    NotFoundError,
    PermissionDenied,
    ValidationError,
)
from app.core.permissions import Permission, RoleName
from app.core.tenancy import build_auth_context
from app.models.inventory import MovementReason, StockMovement, TransferStatus
from app.models.system import Notification, NotificationKind
from app.services.inventory import (
    accept_transfer,
    approve_transfer,
    available_quantity,
    branches_awaiting_opening_stock,
    cancel_transfer,
    create_transfer,
    get_balance,
    opening_sheet,
    reconcile_balances,
    record_opening_stock,
    reject_transfer,
    request_transfer,
    stock_overview,
    visible_transfers,
)


def test_overview_gives_every_branch_a_column_and_the_business_a_total(business):
    """A branch with nothing recorded still appears, holding zero."""
    empty_branch, _ = business.add_branch("Kality")
    product = business.add_product("Cement", opening_stock="40")

    overview = stock_overview(business.db, business.ctx)

    assert [column.name for column in overview.branches] == ["Main Branch", "Kality"]
    row = next(r for r in overview.rows if r.name == "Cement")
    assert row.quantities[business.branch.id] == Decimal("40.000")
    assert row.quantities[empty_branch.id] == Decimal("0.000")
    assert row.total == Decimal("40.000")
    assert overview.grand_total == Decimal("40.000")
    assert row.variant_id == product.default_variant.id


def test_overview_totals_each_branch_separately(business):
    _, warehouse = business.add_branch("Warehouse")
    business.add_product("Sugar", opening_stock="10")
    business.add_product("Salt", opening_stock="5")
    from app.services.inventory import adjust_stock

    oil = business.add_product("Oil", opening_stock=None)
    adjust_stock(
        business.db,
        business.ctx,
        variant_id=oil.default_variant.id,
        location_id=warehouse.id,
        quantity=Decimal("12"),
        reason=MovementReason.OPENING,
        note="Counted on arrival",
    )

    overview = stock_overview(business.db, business.ctx)
    totals = {column.name: column.total for column in overview.branches}

    assert totals == {"Main Branch": Decimal("15.000"), "Warehouse": Decimal("12.000")}
    assert overview.grand_total == Decimal("27.000")


def test_overview_filtered_to_one_branch_shows_only_that_branch(business):
    _, warehouse = business.add_branch("Warehouse")
    business.add_product("Sugar", opening_stock="10")

    overview = stock_overview(business.db, business.ctx, branch_id=warehouse.branch_id)

    assert [column.name for column in overview.branches] == ["Warehouse"]
    row = overview.rows[0]
    assert row.quantities == {warehouse.branch_id: Decimal("0.000")}
    assert row.total == Decimal("0.000")
    assert overview.grand_total == Decimal("0.000")


def test_overview_shows_a_manager_only_their_own_branches(business):
    """Cross-branch visibility follows the assignment, not the feature (PRD 15)."""
    other, _ = business.add_branch("Kality")
    business.add_product("Sugar", opening_stock="10")
    _, manager_ctx = business.add_user(RoleName.MANAGER, branches=[business.branch])

    overview = stock_overview(business.db, manager_ctx)

    assert [column.branch_id for column in overview.branches] == [business.branch.id]
    assert other.id not in overview.rows[0].quantities

    with pytest.raises(PermissionDenied):
        stock_overview(business.db, manager_ctx, branch_id=other.id)


def test_overview_pages_the_products_but_not_the_totals(business):
    for index in range(5):
        business.add_product(f"Item {index}", opening_stock="2")

    first = stock_overview(business.db, business.ctx, limit=2, offset=0)

    assert len(first.rows) == 2
    assert first.total_rows == 5
    # Paging through a long catalogue must not change what the business holds.
    assert first.grand_total == Decimal("10.000")
    assert stock_overview(business.db, business.ctx, limit=2, offset=4).grand_total == (
        Decimal("10.000")
    )


def test_overview_search_narrows_rows_and_totals_together(business):
    business.add_product("Sugar", opening_stock="10")
    business.add_product("Cement", opening_stock="3")

    overview = stock_overview(business.db, business.ctx, q="sug")

    assert [row.name for row in overview.rows] == ["Sugar"]
    assert overview.total_rows == 1
    assert overview.grand_total == Decimal("10.000")


def test_overview_leaves_out_services_and_empty_discontinued_lines(business):
    business.add_product("Delivery", track_stock=False, opening_stock=None)
    retired = business.add_product("Old model", opening_stock=None)
    retired.is_active = False
    stocked_but_retired = business.add_product("Last of the old stock", opening_stock="4")
    stocked_but_retired.is_active = False
    business.db.flush()

    names = [row.name for row in stock_overview(business.db, business.ctx).rows]

    assert "Delivery" not in names
    assert "Old model" not in names
    # Stock on a shelf is stock, whatever the catalogue says about the product.
    assert "Last of the old stock" in names


# --------------------------------------------------------------------------- #
# Opening stock for a new branch
# --------------------------------------------------------------------------- #


def test_only_a_branch_with_nothing_recorded_is_flagged(business):
    """The main branch already has movements, so it is not asking to be counted."""
    business.add_product("Sugar", opening_stock="10")
    business.add_branch("Kality")

    waiting = branches_awaiting_opening_stock(business.db, business.ctx)

    assert [b.branch_name for b in waiting] == ["Kality"]
    assert waiting[0].product_count == 1


def test_recording_opening_stock_clears_the_prompt(business):
    product = business.add_product("Sugar", opening_stock="10")
    branch, location = business.add_branch("Kality")

    record_opening_stock(
        business.db,
        business.ctx,
        branch_id=branch.id,
        counted=[(product.default_variant.id, Decimal("7"))],
    )

    assert branches_awaiting_opening_stock(business.db, business.ctx) == []
    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, location.id
    ) == Decimal("7.000")


def test_opening_stock_is_a_movement_with_a_reason_and_an_actor(business):
    product = business.add_product("Sugar", opening_stock=None)
    branch, location = business.add_branch("Kality")

    movements = record_opening_stock(
        business.db,
        business.ctx,
        branch_id=branch.id,
        counted=[(product.default_variant.id, Decimal("12"))],
    )

    assert len(movements) == 1
    assert movements[0].reason == MovementReason.OPENING
    assert movements[0].quantity == Decimal("12.000")
    assert movements[0].location_id == location.id
    assert movements[0].created_by_id == business.owner.id
    assert "Kality" in (movements[0].note or "")


def test_a_second_pass_corrects_rather_than_doubles(business):
    product = business.add_product("Sugar", opening_stock=None)
    branch, location = business.add_branch("Kality")
    variant = product.default_variant

    record_opening_stock(
        business.db, business.ctx, branch_id=branch.id, counted=[(variant.id, Decimal("10"))]
    )
    corrected = record_opening_stock(
        business.db, business.ctx, branch_id=branch.id, counted=[(variant.id, Decimal("8"))]
    )

    assert get_balance(business.db, business.tenant.id, variant.id, location.id) == (
        Decimal("8.000")
    )
    # Counting down is an adjustment: opening stock may only ever add.
    assert corrected[0].reason == MovementReason.ADJUSTMENT
    assert corrected[0].quantity == Decimal("-2.000")
    assert reconcile_balances(business.db, business.tenant.id) == []


def test_a_quantity_that_is_already_right_posts_nothing(business):
    product = business.add_product("Sugar", opening_stock=None)
    branch, _ = business.add_branch("Kality")
    variant = product.default_variant

    record_opening_stock(
        business.db, business.ctx, branch_id=branch.id, counted=[(variant.id, Decimal("5"))]
    )

    assert (
        record_opening_stock(
            business.db, business.ctx, branch_id=branch.id, counted=[(variant.id, Decimal("5"))]
        )
        == []
    )


def test_a_retried_submit_lands_once(business):
    """A slow connection must not double a whole sheet of counted quantities."""
    product = business.add_product("Sugar", opening_stock=None)
    branch, location = business.add_branch("Kality")
    variant = product.default_variant

    for _ in range(2):
        record_opening_stock(
            business.db,
            business.ctx,
            branch_id=branch.id,
            counted=[(variant.id, Decimal("30"))],
            idempotency_key="sheet-1",
        )

    assert get_balance(business.db, business.tenant.id, variant.id, location.id) == (
        Decimal("30.000")
    )


def test_a_negative_counted_quantity_is_refused(business):
    product = business.add_product("Sugar", opening_stock=None)
    branch, _ = business.add_branch("Kality")

    with pytest.raises(ValidationError):
        record_opening_stock(
            business.db,
            business.ctx,
            branch_id=branch.id,
            counted=[(product.default_variant.id, Decimal("-1"))],
        )


def test_the_sheet_lists_every_product_with_what_the_branch_holds(business):
    business.add_product("Sugar", opening_stock="10")
    business.add_product("Cement", opening_stock="4")
    branch, _ = business.add_branch("Kality")

    sheet = opening_sheet(business.db, business.ctx, branch_id=branch.id)

    assert sheet.branch_name == "Kality"
    assert sheet.product_count == 2
    assert sheet.recorded == 0
    assert {row.name: row.quantity for row in sheet.rows} == {
        "Cement": Decimal("0.000"),
        "Sugar": Decimal("0.000"),
    }
    # The main branch's own sheet shows what it already has.
    main = opening_sheet(business.db, business.ctx, branch_id=business.branch.id)
    assert {row.name: row.quantity for row in main.rows} == {
        "Cement": Decimal("4.000"),
        "Sugar": Decimal("10.000"),
    }
    assert main.recorded == 2


def test_a_salesperson_cannot_record_opening_stock(business):
    product = business.add_product("Sugar", opening_stock=None)
    branch, _ = business.add_branch("Kality")
    _, seller = business.add_user(RoleName.SALESPERSON, all_branches=True)

    with pytest.raises(PermissionDenied):
        record_opening_stock(
            business.db,
            seller,
            branch_id=branch.id,
            counted=[(product.default_variant.id, Decimal("1"))],
        )


def test_a_branch_a_user_cannot_see_is_neither_listed_nor_countable(business):
    product = business.add_product("Sugar", opening_stock=None)
    other, _ = business.add_branch("Kality")
    _, manager = business.add_user(RoleName.MANAGER, branches=[business.branch])

    assert [b.branch_id for b in branches_awaiting_opening_stock(business.db, manager)] == [
        business.branch.id
    ]
    with pytest.raises(PermissionDenied):
        record_opening_stock(
            business.db,
            manager,
            branch_id=other.id,
            counted=[(product.default_variant.id, Decimal("1"))],
        )


def test_a_business_with_no_products_is_not_asked_to_count_them(business):
    business.add_branch("Kality")

    assert branches_awaiting_opening_stock(business.db, business.ctx) == []


# --------------------------------------------------------------------------- #
# Asking another branch for stock
# --------------------------------------------------------------------------- #


def _two_branches(business):
    """A business whose main branch has stock and whose second branch has none."""
    product = business.add_product("Cement", opening_stock="100")
    branch, location = business.add_branch("Kality")
    return product, branch, location


def test_a_request_moves_nothing_until_it_is_accepted(business):
    product, branch, location = _two_branches(business)
    variant = product.default_variant

    transfer = request_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(variant.id, Decimal("30"))],
        note="Sold out before lunch",
    )
    assert transfer.status == TransferStatus.REQUESTED
    assert available_quantity(business.db, business.tenant.id, variant.id) == Decimal("100.000")

    approve_transfer(business.db, business.ctx, transfer.id, note="Take it from the back")
    assert transfer.status == TransferStatus.APPROVED
    # Approval is permission, not movement.
    assert get_balance(business.db, business.tenant.id, variant.id, location.id) == (
        Decimal("0.000")
    )

    accept_transfer(business.db, business.ctx, transfer.id)
    assert transfer.status == TransferStatus.RECEIVED
    assert get_balance(business.db, business.tenant.id, variant.id, business.location.id) == (
        Decimal("70.000")
    )
    assert get_balance(business.db, business.tenant.id, variant.id, location.id) == (
        Decimal("30.000")
    )
    # Nothing was created or lost on the way.
    assert available_quantity(business.db, business.tenant.id, variant.id) == Decimal("100.000")
    assert reconcile_balances(business.db, business.tenant.id) == []


def test_acceptance_posts_both_legs_of_the_move(business):
    product, _, location = _two_branches(business)
    variant = product.default_variant
    transfer = request_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(variant.id, Decimal("12"))],
    )
    approve_transfer(business.db, business.ctx, transfer.id)
    accept_transfer(business.db, business.ctx, transfer.id)

    movements = (
        business.db.query(StockMovement)
        .filter(StockMovement.source_id == transfer.id)
        .all()
    )
    by_reason = {m.reason: m for m in movements}
    assert by_reason[MovementReason.TRANSFER_OUT].quantity == Decimal("-12.000")
    assert by_reason[MovementReason.TRANSFER_OUT].location_id == business.location.id
    assert by_reason[MovementReason.TRANSFER_IN].quantity == Decimal("12.000")
    assert by_reason[MovementReason.TRANSFER_IN].location_id == location.id
    assert transfer.lines[0].quantity_received == Decimal("12.000")
    assert transfer.accepted_at is not None
    assert transfer.accepted_by_id == business.owner.id


def test_a_rejection_is_final_and_says_why(business):
    product, _, location = _two_branches(business)
    transfer = request_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(product.default_variant.id, Decimal("30"))],
    )

    reject_transfer(business.db, business.ctx, transfer.id, note="Needed here for a big order")

    assert transfer.status == TransferStatus.REJECTED
    assert transfer.decision_note == "Needed here for a big order"
    assert transfer.decided_by_id == business.owner.id
    with pytest.raises(ConflictError):
        accept_transfer(business.db, business.ctx, transfer.id)
    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, location.id
    ) == Decimal("0.000")


def test_a_rejection_must_give_a_reason(business):
    product, _, location = _two_branches(business)
    transfer = request_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(product.default_variant.id, Decimal("1"))],
    )

    with pytest.raises(ValidationError):
        reject_transfer(business.db, business.ctx, transfer.id, note="  ")
    assert transfer.status == TransferStatus.REQUESTED


def test_a_manager_may_ask_but_not_decide(business):
    """Spending another branch's stock is the owner's call by default (PRD 5.1)."""
    product, branch, location = _two_branches(business)
    _, manager = business.add_user(RoleName.MANAGER, branches=[branch])

    transfer = request_transfer(
        business.db,
        manager,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(product.default_variant.id, Decimal("5"))],
    )

    assert transfer.status == TransferStatus.REQUESTED
    # The asking branch needs no authority over the branch it is asking.
    assert transfer.requested_by_id is not None
    with pytest.raises(PermissionDenied):
        approve_transfer(business.db, manager, transfer.id)
    with pytest.raises(PermissionDenied):
        reject_transfer(business.db, manager, transfer.id, note="no")


def test_a_manager_granted_the_permission_may_decide_their_own_branch(business):
    product, branch, location = _two_branches(business)
    _, manager = business.add_user(RoleName.MANAGER, branches=[business.branch])
    business.grant(manager.membership, Permission.STOCK_TRANSFER_APPROVE)
    manager = build_auth_context(manager.user, business.tenant, manager.membership)
    requester, requester_ctx = business.add_user(RoleName.MANAGER, branches=[branch])
    transfer = request_transfer(
        business.db,
        requester_ctx,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(product.default_variant.id, Decimal("5"))],
    )

    approve_transfer(business.db, manager, transfer.id)

    assert transfer.status == TransferStatus.APPROVED
    assert requester is not None


def test_deciding_needs_authority_over_the_branch_being_asked(business):
    """Holding the permission is not the same as running the shop it spends."""
    product, branch, location = _two_branches(business)
    _, outsider = business.add_user(RoleName.MANAGER, branches=[branch])
    business.grant(outsider.membership, Permission.STOCK_TRANSFER_APPROVE)
    outsider = build_auth_context(outsider.user, business.tenant, outsider.membership)
    transfer = request_transfer(
        business.db,
        outsider,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(product.default_variant.id, Decimal("5"))],
    )

    with pytest.raises(PermissionDenied):
        approve_transfer(business.db, outsider, transfer.id)


def test_only_the_branch_that_asked_may_accept(business):
    product, _, location = _two_branches(business)
    transfer = request_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(product.default_variant.id, Decimal("5"))],
    )
    approve_transfer(business.db, business.ctx, transfer.id)
    _, elsewhere = business.add_user(RoleName.MANAGER, branches=[business.branch])

    with pytest.raises(PermissionDenied):
        accept_transfer(business.db, elsewhere, transfer.id)
    assert transfer.status == TransferStatus.APPROVED


def test_a_request_cannot_be_accepted_before_it_is_approved(business):
    product, _, location = _two_branches(business)
    transfer = request_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(product.default_variant.id, Decimal("5"))],
    )

    with pytest.raises(ConflictError):
        accept_transfer(business.db, business.ctx, transfer.id)


def test_a_request_cannot_be_decided_twice(business):
    product, _, location = _two_branches(business)
    transfer = request_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(product.default_variant.id, Decimal("5"))],
    )
    approve_transfer(business.db, business.ctx, transfer.id)

    with pytest.raises(ConflictError):
        approve_transfer(business.db, business.ctx, transfer.id)
    with pytest.raises(ConflictError):
        reject_transfer(business.db, business.ctx, transfer.id, note="changed my mind")


def test_an_approved_request_can_be_turned_down_by_whoever_asked(business):
    """"Must accept" has to have an answer other than yes."""
    product, _, location = _two_branches(business)
    variant = product.default_variant
    transfer = request_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(variant.id, Decimal("5"))],
    )
    approve_transfer(business.db, business.ctx, transfer.id)

    cancel_transfer(business.db, business.ctx, transfer.id, note="Restocked from the supplier")

    assert transfer.status == TransferStatus.CANCELLED
    assert transfer.decision_note == "Restocked from the supplier"
    assert get_balance(business.db, business.tenant.id, variant.id, location.id) == (
        Decimal("0.000")
    )
    with pytest.raises(ConflictError):
        accept_transfer(business.db, business.ctx, transfer.id)


def test_a_completed_transfer_cannot_be_cancelled(business):
    product, _, location = _two_branches(business)
    transfer = request_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(product.default_variant.id, Decimal("5"))],
    )
    approve_transfer(business.db, business.ctx, transfer.id)
    accept_transfer(business.db, business.ctx, transfer.id)

    with pytest.raises(ConflictError):
        cancel_transfer(business.db, business.ctx, transfer.id)


def test_stock_sold_between_approval_and_acceptance_blocks_the_move(business):
    """The approval stands; the goods simply are not there to take."""
    product, _, location = _two_branches(business)
    variant = product.default_variant
    transfer = request_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(variant.id, Decimal("90"))],
    )
    approve_transfer(business.db, business.ctx, transfer.id)
    business.sell(product, quantity="40")

    with pytest.raises(InsufficientStock):
        accept_transfer(business.db, business.ctx, transfer.id)
    assert transfer.status == TransferStatus.APPROVED


def test_a_short_line_stops_the_whole_transfer_before_anything_moves(business):
    """A transfer is one decision: all of it happens, or none of it does."""
    plenty = business.add_product("Cement", opening_stock="100")
    scarce = business.add_product("Steel bar", opening_stock="2")
    _, location = business.add_branch("Kality")
    transfer = request_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[
            (plenty.default_variant.id, Decimal("10")),
            (scarce.default_variant.id, Decimal("5")),
        ],
    )
    approve_transfer(business.db, business.ctx, transfer.id)

    with pytest.raises(InsufficientStock) as refusal:
        accept_transfer(business.db, business.ctx, transfer.id)

    assert "Steel bar" in str(refusal.value)
    assert "Main Branch" in str(refusal.value)
    # The line that could have moved did not move either.
    assert get_balance(
        business.db, business.tenant.id, plenty.default_variant.id, location.id
    ) == Decimal("0.000")
    assert get_balance(
        business.db, business.tenant.id, plenty.default_variant.id, business.location.id
    ) == Decimal("100.000")
    assert transfer.status == TransferStatus.APPROVED
    assert reconcile_balances(business.db, business.tenant.id) == []


def test_a_request_to_your_own_branch_is_refused(business):
    product = business.add_product("Cement", opening_stock="10")
    from app.models.organisation import LocationKind, StockLocation

    back_room = StockLocation(
        tenant_id=business.tenant.id,
        branch_id=business.branch.id,
        name="Back room",
        kind=LocationKind.WAREHOUSE,
        is_default=False,
    )
    business.db.add(back_room)
    business.db.flush()

    with pytest.raises(ValidationError):
        request_transfer(
            business.db,
            business.ctx,
            from_location_id=business.location.id,
            to_location_id=back_room.id,
            lines=[(product.default_variant.id, Decimal("1"))],
        )


def test_the_record_holds_requests_approvals_rejections_and_transfers(business):
    product, branch, location = _two_branches(business)
    variant = product.default_variant

    def ask(quantity):
        return request_transfer(
            business.db,
            business.ctx,
            from_location_id=business.location.id,
            to_location_id=location.id,
            lines=[(variant.id, Decimal(quantity))],
        )

    waiting = ask("1")
    refused = ask("2")
    reject_transfer(business.db, business.ctx, refused.id, note="No")
    done = ask("3")
    approve_transfer(business.db, business.ctx, done.id)
    accept_transfer(business.db, business.ctx, done.id)
    pushed = create_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(variant.id, Decimal("4"))],
    )

    everything = visible_transfers(business.db, business.ctx)
    by_id = {t.id: str(t.status) for t in everything}

    assert by_id[waiting.id] == "requested"
    assert by_id[refused.id] == "rejected"
    assert by_id[done.id] == "received"
    assert by_id[pushed.id] == "draft"
    # And the list narrows to what is waiting on somebody.
    assert [t.id for t in visible_transfers(
        business.db, business.ctx, statuses=[TransferStatus.REQUESTED]
    )] == [waiting.id]


def test_a_branch_only_sees_transfers_it_has_a_part_in(business):
    product, branch, location = _two_branches(business)
    third, third_location = business.add_branch("Megenagna")
    mine = request_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(product.default_variant.id, Decimal("1"))],
    )
    elsewhere = create_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=third_location.id,
        lines=[(product.default_variant.id, Decimal("1"))],
    )
    _, manager = business.add_user(RoleName.MANAGER, branches=[branch])

    seen = {t.id for t in visible_transfers(business.db, manager)}

    assert mine.id in seen
    assert elsewhere.id not in seen
    assert third is not None
    # Whoever may decide requests sees them wherever they are asked.
    assert {t.id for t in visible_transfers(business.db, business.ctx)} >= {
        mine.id,
        elsewhere.id,
    }


def test_the_owner_is_told_a_branch_is_asking_and_the_asker_hears_back(business):
    product, branch, location = _two_branches(business)
    _, manager = business.add_user(RoleName.MANAGER, branches=[branch])

    transfer = request_transfer(
        business.db,
        manager,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(product.default_variant.id, Decimal("5"))],
    )
    asked = (
        business.db.query(Notification)
        .filter(Notification.kind == NotificationKind.STOCK_REQUEST)
        .all()
    )
    assert [n.user_id for n in asked] == [business.owner.id]
    assert "Kality" in asked[0].title
    assert "Main Branch" in asked[0].title

    approve_transfer(business.db, business.ctx, transfer.id, note="Take it")
    answered = (
        business.db.query(Notification)
        .filter(Notification.kind == NotificationKind.STOCK_REQUEST_DECIDED)
        .all()
    )
    assert [n.user_id for n in answered] == [manager.user_id]
    assert transfer.reference in answered[0].title


# --------------------------------------------------------------------------- #
# Through the API, the way the web app uses it
# --------------------------------------------------------------------------- #


def test_overview_endpoint_returns_a_column_per_branch(client, business):
    business.add_product("Sugar", opening_stock="10")
    kality, _ = business.add_branch("Kality")

    body = client.get("/api/v1/stock/overview", headers=business.headers()).json()

    assert [b["name"] for b in body["branches"]] == ["Main Branch", "Kality"]
    assert body["rows"][0]["quantities"][str(business.branch.id)] == "10.000"
    assert body["rows"][0]["quantities"][str(kality.id)] == "0.000"
    assert body["grand_total"] == "10.000"
    assert body["total"] == 1


def test_setup_and_opening_endpoints_walk_a_new_branch(client, business):
    product = business.add_product("Sugar", opening_stock="10")
    branch, _ = business.add_branch("Kality")
    headers = business.headers()

    waiting = client.get("/api/v1/stock/setup", headers=headers).json()
    assert [b["branch_name"] for b in waiting] == ["Kality"]

    sheet = client.get(
        f"/api/v1/stock/opening?branch_id={branch.id}", headers=headers
    ).json()
    assert sheet["location_name"] == "Kality"
    assert sheet["rows"][0]["quantity"] == "0.000"
    assert sheet["recorded"] == 0

    recorded = client.post(
        "/api/v1/stock/opening",
        headers=headers,
        json={
            "branch_id": str(branch.id),
            "lines": [{"variant_id": str(product.default_variant.id), "quantity": "25"}],
            "idempotency_key": "sheet-1",
        },
    )
    assert recorded.status_code == 201
    assert recorded.json()["recorded"] == 1
    assert client.get("/api/v1/stock/setup", headers=headers).json() == []

    again = client.get(f"/api/v1/stock/opening?branch_id={branch.id}", headers=headers).json()
    assert again["rows"][0]["quantity"] == "25.000"
    assert again["recorded"] == 1


def test_the_dashboard_tells_whoever_signs_in_about_an_uncounted_branch(client, business):
    business.add_product("Sugar", opening_stock="10")
    business.add_branch("Kality")

    body = client.get("/api/v1/dashboard", headers=business.headers()).json()

    assert [b["branch_name"] for b in body["stock_setup"]] == ["Kality"]
    assert body["stock_setup"][0]["product_count"] == 1


def test_the_request_workflow_end_to_end_over_http(client, business):
    product = business.add_product("Cement", opening_stock="100")
    branch, location = business.add_branch("Kality")
    manager, manager_ctx = business.add_user(RoleName.MANAGER, branches=[branch])
    staff = business.headers(manager)
    owner = business.headers()

    # The branch that has run out can name the branch it wants to ask, without
    # being able to see what that branch holds.
    targets = client.get("/api/v1/stock/branches", headers=staff).json()
    by_name = {b["branch_name"]: b for b in targets}
    assert by_name["Main Branch"]["is_mine"] is False
    assert by_name["Kality"]["is_mine"] is True
    assert "quantity" not in by_name["Main Branch"]

    created = client.post(
        "/api/v1/stock/requests",
        headers=staff,
        json={
            "from_location_id": by_name["Main Branch"]["location_id"],
            "to_location_id": by_name["Kality"]["location_id"],
            "lines": [{"variant_id": str(product.default_variant.id), "quantity": "30"}],
            "note": "Sold out before lunch",
        },
    )
    assert created.status_code == 201
    request_id = created.json()["id"]
    assert created.json()["status"] == "requested"
    assert created.json()["from_branch_name"] == "Main Branch"
    assert created.json()["lines"][0]["name"] == "Cement"

    # A manager may ask but not decide.
    refused = client.post(
        f"/api/v1/stock/transfers/{request_id}/approve", headers=staff, json={}
    )
    assert refused.status_code == 403

    approved = client.post(
        f"/api/v1/stock/transfers/{request_id}/approve",
        headers=owner,
        json={"note": "Take it from the back"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["decided_by_name"] == business.owner.full_name

    accepted = client.post(f"/api/v1/stock/transfers/{request_id}/accept", headers=staff)
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "received"

    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, location.id
    ) == Decimal("30.000")
    assert manager_ctx is not None


def test_a_rejection_over_http_needs_a_reason(client, business):
    product = business.add_product("Cement", opening_stock="10")
    _, location = business.add_branch("Kality")
    headers = business.headers()
    created = client.post(
        "/api/v1/stock/requests",
        headers=headers,
        json={
            "from_location_id": str(business.location.id),
            "to_location_id": str(location.id),
            "lines": [{"variant_id": str(product.default_variant.id), "quantity": "2"}],
        },
    ).json()

    blank = client.post(
        f"/api/v1/stock/transfers/{created['id']}/reject", headers=headers, json={}
    )
    assert blank.status_code == 422
    assert "why" in blank.json()["message"].lower()

    given = client.post(
        f"/api/v1/stock/transfers/{created['id']}/reject",
        headers=headers,
        json={"note": "Needed here"},
    )
    assert given.json()["status"] == "rejected"
    assert given.json()["decision_note"] == "Needed here"


def test_the_transfer_list_can_be_narrowed_to_what_is_waiting(client, business):
    product = business.add_product("Cement", opening_stock="10")
    _, location = business.add_branch("Kality")
    headers = business.headers()
    for quantity_asked in ("1", "2"):
        client.post(
            "/api/v1/stock/requests",
            headers=headers,
            json={
                "from_location_id": str(business.location.id),
                "to_location_id": str(location.id),
                "lines": [
                    {"variant_id": str(product.default_variant.id), "quantity": quantity_asked}
                ],
            },
        )
    decided = client.get(
        "/api/v1/stock/transfers?status=requested", headers=headers
    ).json()
    assert len(decided) == 2
    client.post(
        f"/api/v1/stock/transfers/{decided[0]['id']}/reject",
        headers=headers,
        json={"note": "No"},
    )

    assert len(client.get("/api/v1/stock/transfers?status=requested", headers=headers).json()) == 1
    assert len(client.get("/api/v1/stock/transfers", headers=headers).json()) == 2


def test_another_business_sees_none_of_this(business, other_business):
    """Every new read is tenant-scoped like the rest (PRD 4)."""
    product = business.add_product("Cement", opening_stock="100")
    _, location = business.add_branch("Kality")
    mine = request_transfer(
        business.db,
        business.ctx,
        from_location_id=business.location.id,
        to_location_id=location.id,
        lines=[(product.default_variant.id, Decimal("5"))],
    )
    other_business.add_product("Nails", opening_stock="3")

    theirs = stock_overview(business.db, other_business.ctx)
    assert [row.name for row in theirs.rows] == ["Nails"]
    assert [column.name for column in theirs.branches] == ["Main Branch"]
    assert theirs.branches[0].branch_id != business.branch.id
    assert visible_transfers(business.db, other_business.ctx) == []

    # And none of it can be reached by id either.
    for call in (
        lambda: approve_transfer(business.db, other_business.ctx, mine.id),
        lambda: accept_transfer(business.db, other_business.ctx, mine.id),
        lambda: cancel_transfer(business.db, other_business.ctx, mine.id),
        lambda: opening_sheet(business.db, other_business.ctx, branch_id=business.branch.id),
    ):
        with pytest.raises(NotFoundError):
            call()
