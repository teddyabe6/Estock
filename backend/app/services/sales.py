"""Sale completion: lines, payments, stock and credit in one transaction (PRD 10).

The whole sale is one consistent operation — if any part fails, nothing is
posted.  Prices, discounts, tax and cost are snapshotted onto the sale lines so
later catalogue edits never rewrite history.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, record_audit
from app.core.clock import local_date
from app.core.db import utcnow
from app.core.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from app.core.permissions import Permission
from app.core.tenancy import (
    AuthContext,
    get_tenant_object,
    resolve_branch,
    resolve_location,
    tenant_query,
)
from app.models.catalogue import ProductVariant
from app.models.contacts import Customer
from app.models.credit import CreditKind, CreditTransaction
from app.models.inventory import MovementReason
from app.models.sales import (
    Payment,
    PaymentDirection,
    PaymentMethod,
    RefundMethod,
    Sale,
    SaleLine,
    SaleReturn,
    SaleReturnLine,
    SaleStatus,
)
from app.services import credit as credit_service
from app.services.inventory import MovementRefs, StockPosting, post_movement
from app.services.numbering import next_number
from app.services.pricing import quantize_money

ZERO = Decimal("0.00")


@dataclass(slots=True)
class SaleLineInput:
    variant_id: uuid.UUID
    quantity: Decimal
    #: Override the catalogue price; subject to the discount rules below.
    unit_price: Decimal | None = None
    discount_amount: Decimal | None = None
    discount_percent: Decimal | None = None
    tax_rate: Decimal | None = None
    note: str | None = None


@dataclass(slots=True)
class PaymentInput:
    method: PaymentMethod
    amount: Decimal
    reference: str | None = None
    note: str | None = None


@dataclass(slots=True)
class SaleInput:
    lines: list[SaleLineInput]
    payments: list[PaymentInput] = field(default_factory=list)
    branch_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    note: str | None = None
    sold_at: datetime | None = None
    idempotency_key: str | None = None
    # Credit terms, used only when the sale is not fully paid.
    due_date: date | None = None
    due_date_preset: str | None = None
    credit_note: str | None = None
    #: Set by an authorised user to proceed past a credit-limit warning.
    override_credit_limit: bool = False


@dataclass(slots=True)
class SaleResult:
    sale: Sale
    credit_transaction: CreditTransaction | None
    warnings: list[str] = field(default_factory=list)


def _line_amounts(
    variant: ProductVariant, line: SaleLineInput, default_tax_rate: Decimal | None
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Return (unit_price, discount, taxable base, tax_rate, tax_amount)."""
    quantity = Decimal(line.quantity)
    if quantity <= 0:
        raise ValidationError("Sale quantities must be positive")

    unit_price = (
        Decimal(line.unit_price)
        if line.unit_price is not None
        else Decimal(variant.selling_price or 0)
    )
    if unit_price < 0:
        raise ValidationError("Unit price cannot be negative")

    gross = quantize_money(unit_price * quantity)

    if line.discount_amount is not None and line.discount_percent is not None:
        raise ValidationError("Give a discount amount or a percentage, not both")
    if line.discount_percent is not None:
        percent = Decimal(line.discount_percent)
        if percent < 0 or percent > 1:
            raise ValidationError("Discount percentage must be between 0 and 100%")
        discount = quantize_money(gross * percent)
    else:
        discount = quantize_money(Decimal(line.discount_amount or 0))
    if discount < 0:
        raise ValidationError("Discount cannot be negative")
    if discount > gross:
        raise ValidationError("Discount cannot exceed the line total")

    net = quantize_money(gross - discount)
    tax_rate = (
        Decimal(line.tax_rate)
        if line.tax_rate is not None
        else Decimal(variant.tax_rate if variant.tax_rate is not None else (default_tax_rate or 0))
    )
    if tax_rate < 0:
        raise ValidationError("Tax rate cannot be negative")
    tax_amount = quantize_money(net * tax_rate)
    return unit_price, discount, net, tax_rate, tax_amount


def _check_discount_allowance(
    ctx: AuthContext, variant: ProductVariant, gross: Decimal, discount: Decimal
) -> None:
    """Enforce the per-product discount cap unless the user may approve (PRD 10)."""
    if discount <= 0 or gross <= 0:
        return
    cap = variant.max_discount_percent
    if cap is None:
        return
    applied = discount / gross
    if applied > Decimal(cap) and not ctx.has(Permission.DISCOUNT_APPROVE):
        raise PermissionDenied(
            f"Discount of {applied:.0%} exceeds the {Decimal(cap):.0%} limit for "
            f"{variant.display_name}; ask a manager to approve it",
            details={"variant_id": str(variant.id), "max_discount_percent": str(cap)},
        )


def create_sale(db: Session, ctx: AuthContext, data: SaleInput) -> SaleResult:
    """Post a sale: lines, stock, payments and any receivable, atomically."""
    ctx.require(Permission.SALE_CREATE)
    if ctx.tenant.is_read_only:
        from app.core.errors import SubscriptionInactive

        raise SubscriptionInactive(
            "This account is read-only. Renew the subscription to record new sales."
        )
    if not data.lines:
        raise ValidationError("A sale needs at least one product")

    if data.idempotency_key:
        existing = db.execute(
            tenant_query(Sale, ctx.tenant_id).where(
                Sale.idempotency_key == data.idempotency_key
            )
        ).scalar_one_or_none()
        if existing is not None:
            credit = db.execute(
                tenant_query(CreditTransaction, ctx.tenant_id).where(
                    CreditTransaction.sale_id == existing.id
                )
            ).scalar_one_or_none()
            return SaleResult(sale=existing, credit_transaction=credit)

    branch = resolve_branch(db, ctx, data.branch_id)
    location = resolve_location(db, ctx, branch, data.location_id)
    customer = get_tenant_object(
        db, Customer, data.customer_id, ctx.tenant_id, label="Customer", required=False
    )

    sold_at = data.sold_at or utcnow()
    warnings: list[str] = []

    sale = Sale(
        tenant_id=ctx.tenant_id,
        number=next_number(db, Sale, ctx.tenant_id, "sale", now=sold_at),
        branch_id=branch.id,
        location_id=location.id,
        customer_id=customer.id if customer else None,
        salesperson_id=ctx.user_id,
        status=SaleStatus.COMPLETED,
        sold_at=sold_at,
        subtotal=ZERO,
        discount_total=ZERO,
        tax_total=ZERO,
        total_amount=ZERO,
        cost_total=ZERO,
        currency=ctx.tenant.currency,
        note=data.note,
        idempotency_key=data.idempotency_key,
        created_by_id=ctx.user_id,
    )
    db.add(sale)
    db.flush()

    subtotal = discount_total = tax_total = cost_total = ZERO
    default_tax_rate = (
        Decimal(ctx.tenant.default_tax_rate) if ctx.tenant.default_tax_rate is not None else None
    )

    # Every line's variant and the one location, resolved in two queries for
    # the whole sale rather than per line — and shared with post_movement,
    # which needs the same objects.
    refs = MovementRefs(
        db,
        ctx.tenant_id,
        variant_ids=[line.variant_id for line in data.lines],
        location_ids=[location.id],
    )

    for index, line_input in enumerate(data.lines):
        variant = refs.get_variant(line_input.variant_id)
        if variant is None:
            raise NotFoundError("Product not found")
        if not variant.is_active or not variant.product.is_active:
            raise ValidationError(f"{variant.display_name} is no longer available")

        quantity = Decimal(line_input.quantity)
        unit_price, discount, net, tax_rate, tax_amount = _line_amounts(
            variant, line_input, default_tax_rate
        )
        _check_discount_allowance(ctx, variant, quantize_money(unit_price * quantity), discount)

        unit_cost = variant.cost_for_valuation
        line_total = quantize_money(net + tax_amount)

        db.add(
            SaleLine(
                sale_id=sale.id,
                product_id=variant.product_id,
                variant_id=variant.id,
                description=variant.display_name,
                quantity=quantity,
                unit_price=unit_price,
                discount_amount=discount,
                tax_rate=tax_rate,
                tax_amount=tax_amount,
                line_total=line_total,
                unit_cost=unit_cost,
                discount_approved_by_id=(
                    ctx.user_id if discount > 0 and ctx.has(Permission.DISCOUNT_APPROVE) else None
                ),
            )
        )

        subtotal = quantize_money(subtotal + quantize_money(unit_price * quantity))
        discount_total = quantize_money(discount_total + discount)
        tax_total = quantize_money(tax_total + tax_amount)
        if unit_cost is not None:
            cost_total = quantize_money(cost_total + (Decimal(unit_cost) * quantity))

        if variant.product.track_stock:
            post_movement(
                db,
                ctx,
                StockPosting(
                    variant_id=variant.id,
                    location_id=location.id,
                    quantity=-quantity,
                    reason=MovementReason.SALE,
                    unit_cost=unit_cost,
                    source_type="sale",
                    source_id=sale.id,
                    idempotency_key=f"sale:{sale.id}:{index}",
                    note=f"Sale {sale.number}",
                ),
                refs=refs,
                occurred_at=sold_at,
            )

    total_amount = quantize_money(subtotal - discount_total + tax_total)
    sale.subtotal = subtotal
    sale.discount_total = discount_total
    sale.tax_total = tax_total
    sale.total_amount = total_amount
    sale.cost_total = cost_total
    db.flush()

    paid = ZERO
    for index, payment_input in enumerate(data.payments):
        amount = quantize_money(Decimal(payment_input.amount))
        if amount <= 0:
            raise ValidationError("Payment amounts must be positive")
        paid = quantize_money(paid + amount)
        db.add(
            Payment(
                tenant_id=ctx.tenant_id,
                direction=PaymentDirection.IN,
                method=payment_input.method,
                amount=amount,
                currency=sale.currency,
                paid_at=sold_at,
                branch_id=branch.id,
                sale_id=sale.id,
                customer_id=sale.customer_id,
                reference=payment_input.reference,
                note=payment_input.note,
                idempotency_key=(
                    f"{data.idempotency_key}:pay:{index}" if data.idempotency_key else None
                ),
                created_by_id=ctx.user_id,
            )
        )

    if paid > total_amount:
        raise ValidationError(
            f"Payments of {paid} exceed the sale total of {total_amount}",
            code="overpayment",
        )

    credit_transaction: CreditTransaction | None = None
    balance = quantize_money(total_amount - paid)

    if balance > ZERO:
        ctx.require(Permission.CREDIT_CREATE)
        if ctx.tenant.require_customer_for_credit and customer is None:
            raise ValidationError(
                "Select a customer before recording a credit sale",
                code="customer_required_for_credit",
            )

        limit_check = credit_service.check_credit_limit(db, ctx, sale.customer_id, balance)
        if limit_check.message:
            # "block" means block: only the approval behaviour can be overridden,
            # and only by a user holding the override permission (PRD 11.7).
            approved = (
                limit_check.requires_approval
                and data.override_credit_limit
                and ctx.has(Permission.CREDIT_LIMIT_OVERRIDE)
            )
            if not limit_check.allowed and not approved:
                raise ConflictError(limit_check.message, code="credit_limit_exceeded")
            warnings.append(limit_check.message)
            if approved:
                record_audit(
                    db,
                    action=AuditAction.CREDIT_LIMIT_OVERRIDDEN,
                    tenant_id=ctx.tenant_id,
                    actor_user_id=ctx.user_id,
                    entity_type="customer",
                    entity_id=sale.customer_id,
                    summary=limit_check.message,
                )

        sold_on = local_date(sold_at, ctx.tenant.timezone)
        due_date = credit_service.resolve_due_date(
            data.due_date_preset, data.due_date, today=sold_on
        )
        credit_transaction = credit_service.create_credit_transaction(
            db,
            ctx,
            kind=CreditKind.RECEIVABLE,
            amount=total_amount,
            branch_id=branch.id,
            customer_id=sale.customer_id,
            sale_id=sale.id,
            due_date=due_date,
            issued_on=sold_on,
            agreement_note=data.credit_note,
        )
        # Money taken at the till settles part of the receivable straight away;
        # the payment rows are the only place the amount is recorded.
        db.flush()
        for payment in sale.payments:
            payment.credit_transaction_id = credit_transaction.id
        db.flush()
        credit_service.recalculate(db, credit_transaction, today=sold_on)

    record_audit(
        db,
        action=AuditAction.SALE_COMPLETED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="sale",
        entity_id=sale.id,
        summary=f"Sale {sale.number} for {total_amount} {sale.currency}",
        payload={
            "branch_id": str(branch.id),
            "line_count": len(data.lines),
            "paid": str(paid),
            "balance": str(balance),
        },
    )
    db.flush()
    db.refresh(sale)
    return SaleResult(sale=sale, credit_transaction=credit_transaction, warnings=warnings)


def void_sale(db: Session, ctx: AuthContext, sale_id: uuid.UUID, *, reason: str) -> Sale:
    """Reverse a sale with compensating movements; nothing is deleted (PRD 1)."""
    ctx.require(Permission.SALE_VOID)
    sale = get_tenant_object(db, Sale, sale_id, ctx.tenant_id, label="Sale")
    ctx.require_branch(sale.branch_id)
    if sale.status == SaleStatus.VOIDED:
        raise ConflictError("This sale is already voided")
    if sale.returns:
        # Voiding reverses the whole sale's stock and money.  Doing that on top
        # of a return would put the returned units back twice and refund them
        # twice, so the returns have to be dealt with first.
        raise ConflictError(
            f"Sale {sale.number} has {len(sale.returns)} return(s) against it. "
            "Voiding it now would reverse the returned goods a second time.",
            code="sale_has_returns",
            details={"returns": [r.number for r in sale.returns]},
        )
    if not reason:
        raise ValidationError("A reason is required to void a sale")

    refs = MovementRefs(
        db,
        ctx.tenant_id,
        variant_ids=[line.variant_id for line in sale.lines],
        location_ids=[sale.location_id],
    )
    for index, line in enumerate(sale.lines):
        post_movement(
            db,
            ctx,
            StockPosting(
                variant_id=line.variant_id,
                location_id=sale.location_id,
                quantity=Decimal(line.quantity),
                reason=MovementReason.SALE_VOID,
                unit_cost=line.unit_cost,
                source_type="sale_void",
                source_id=sale.id,
                idempotency_key=f"sale-void:{sale.id}:{index}",
                note=f"Void of sale {sale.number}: {reason}",
            ),
            refs=refs,
        )

    credit_transaction = db.execute(
        tenant_query(CreditTransaction, ctx.tenant_id).where(
            CreditTransaction.sale_id == sale.id
        )
    ).scalar_one_or_none()
    if credit_transaction is not None and credit_transaction.cancelled_at is None:
        credit_service.cancel_transaction(
            db, ctx, credit_transaction.id, reason=f"Sale {sale.number} voided: {reason}"
        )

    sale.status = SaleStatus.VOIDED
    sale.voided_at = utcnow()
    sale.voided_by_id = ctx.user_id
    sale.void_reason = reason

    record_audit(
        db,
        action=AuditAction.SALE_VOIDED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="sale",
        entity_id=sale.id,
        summary=f"Voided sale {sale.number}",
        payload={"reason": reason, "total": str(sale.total_amount)},
    )
    db.flush()
    return sale


# --------------------------------------------------------------------------- #
# Returns and refunds (PRD 1, 10)
# --------------------------------------------------------------------------- #
#
# A return is its own document, never an edit of the sale.  The sale keeps the
# prices, discounts, tax and cost snapshots it was agreed at; a SaleReturn
# records what came back, when, who took it and what it was worth.
#
# Three things have to agree, so each is derived rather than supplied:
#
# * **Stock.**  Returned goods come back on the ledger as SALE_RETURN.  Goods
#   not fit to sell again come back and are then written off as LOSS, so the
#   damage is a movement with a reason and an actor rather than a silent
#   absence.  This follows the choice already made for transfer shortfalls.
# * **Value.**  Carried from the sale's own line, pro-rata for a part return,
#   with the last return of a line taking the remainder exactly so the parts
#   always sum back to the whole.  Never recomputed from the catalogue, which
#   may have moved since the sale.
# * **Money.**  A customer who still owes on the sale is not handed cash: the
#   return comes off what they owe first, and only the rest is paid back.  A
#   refund can never exceed what was actually taken for the sale.


@dataclass(slots=True)
class ReturnLineInput:
    sale_line_id: uuid.UUID
    quantity: Decimal
    #: False when the goods cannot be sold again.
    restock: bool = True


@dataclass(slots=True)
class SaleReturnInput:
    lines: list[ReturnLineInput]
    reason: str
    #: How money goes back when any is owed to the customer.  Defaults to the
    #: method they paid with, falling back to cash.
    refund_method: PaymentMethod | None = None
    returned_at: datetime | None = None
    note: str | None = None
    idempotency_key: str | None = None


@dataclass(slots=True)
class ReturnedSoFar:
    quantity: Decimal = ZERO
    discount: Decimal = ZERO
    tax: Decimal = ZERO


def returned_so_far(
    db: Session, tenant_id: uuid.UUID, sale_id: uuid.UUID
) -> dict[uuid.UUID, ReturnedSoFar]:
    """What each line of this sale has already given back."""
    rows = db.execute(
        select(
            SaleReturnLine.sale_line_id,
            func.coalesce(func.sum(SaleReturnLine.quantity), 0),
            func.coalesce(func.sum(SaleReturnLine.discount_amount), 0),
            func.coalesce(func.sum(SaleReturnLine.tax_amount), 0),
        )
        .join(SaleReturn, SaleReturn.id == SaleReturnLine.sale_return_id)
        .where(SaleReturn.tenant_id == tenant_id, SaleReturn.sale_id == sale_id)
        .group_by(SaleReturnLine.sale_line_id)
    )
    return {
        row[0]: ReturnedSoFar(
            quantity=Decimal(row[1] or 0),
            discount=Decimal(row[2] or 0),
            tax=Decimal(row[3] or 0),
        )
        for row in rows
    }


def returnable(db: Session, ctx: AuthContext, sale_id: uuid.UUID) -> list[dict]:
    """Each line of a sale with how much of it can still come back."""
    ctx.require(Permission.SALE_VIEW)
    sale = get_tenant_object(db, Sale, sale_id, ctx.tenant_id, label="Sale")
    ctx.require_branch(sale.branch_id)
    already = returned_so_far(db, ctx.tenant_id, sale.id)
    return [
        {
            "sale_line_id": str(line.id),
            "variant_id": str(line.variant_id),
            "description": line.description,
            "quantity_sold": str(Decimal(line.quantity)),
            "quantity_returned": str(already.get(line.id, ReturnedSoFar()).quantity),
            "quantity_returnable": str(
                Decimal(line.quantity) - already.get(line.id, ReturnedSoFar()).quantity
            ),
            "unit_price": str(Decimal(line.unit_price)),
        }
        for line in sale.lines
    ]


def _line_value(
    line: SaleLine, quantity: Decimal, already: ReturnedSoFar
) -> tuple[Decimal, Decimal, Decimal]:
    """The returned quantity's share of this line's discount, tax and total.

    Pro-rata, except for the return that takes the rest of a line: that one
    gets exactly what is left, so returning a line in two goes gives back the
    same total as returning it in one and no cent is lost to rounding.
    """
    sold = Decimal(line.quantity)
    remaining = sold - already.quantity
    if quantity == remaining:
        discount = quantize_money(Decimal(line.discount_amount) - already.discount)
        tax = quantize_money(Decimal(line.tax_amount) - already.tax)
    else:
        share = quantity / sold
        discount = quantize_money(Decimal(line.discount_amount) * share)
        tax = quantize_money(Decimal(line.tax_amount) * share)
    net = quantize_money(Decimal(line.unit_price) * quantity) - discount
    return discount, tax, quantize_money(net + tax)


def create_sale_return(
    db: Session, ctx: AuthContext, sale_id: uuid.UUID, data: SaleReturnInput
) -> SaleReturn:
    """Take goods back from a sale and give the value back (PRD 1, 10)."""
    ctx.require(Permission.SALE_REFUND)
    if ctx.tenant.is_read_only:
        from app.core.errors import SubscriptionInactive

        raise SubscriptionInactive(
            "This account is read-only. Renew the subscription to record returns."
        )
    if not data.lines:
        raise ValidationError("A return needs at least one line")
    if not (data.reason or "").strip():
        raise ValidationError("A reason is required to take goods back")
    if data.refund_method == PaymentMethod.CREDIT_NOTE:
        # credit_note is how the service records value taken off a balance.
        # Letting a caller pick it for the cash leg would label real money
        # leaving the till as if nothing had moved.
        raise ValidationError(
            "'credit_note' is not a way to hand money back. Value owed against an "
            "outstanding balance is credited automatically.",
            details={
                "allowed": [m.value for m in PaymentMethod if m != PaymentMethod.CREDIT_NOTE]
            },
        )

    if data.idempotency_key:
        existing = db.execute(
            tenant_query(SaleReturn, ctx.tenant_id).where(
                SaleReturn.idempotency_key == data.idempotency_key
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    sale = get_tenant_object(db, Sale, sale_id, ctx.tenant_id, label="Sale")
    ctx.require_branch(sale.branch_id)
    if sale.status == SaleStatus.VOIDED:
        raise ConflictError(
            "This sale was voided, so there is nothing to return against. "
            "A void already reversed its stock and its money."
        )

    by_id = {line.id: line for line in sale.lines}
    already = returned_so_far(db, ctx.tenant_id, sale.id)
    returned_at = data.returned_at or utcnow()

    wanted: dict[uuid.UUID, Decimal] = {}
    restock_of: dict[uuid.UUID, bool] = {}
    for line_input in data.lines:
        line = by_id.get(line_input.sale_line_id)
        if line is None:
            raise NotFoundError("That line is not part of this sale")
        quantity = Decimal(line_input.quantity)
        if quantity <= 0:
            raise ValidationError("Return quantities must be positive")
        wanted[line.id] = wanted.get(line.id, ZERO) + quantity
        # Two entries for one line with different handling would be ambiguous;
        # the stricter answer wins, so damage is never quietly restocked.
        restock_of[line.id] = restock_of.get(line.id, True) and line_input.restock

    for line_id, quantity in wanted.items():
        line = by_id[line_id]
        remaining = Decimal(line.quantity) - already.get(line_id, ReturnedSoFar()).quantity
        if quantity > remaining:
            raise ValidationError(
                f"Only {remaining} of {line.description} can still be returned; "
                f"{quantity} was asked for.",
                code="return_exceeds_sold",
                details={
                    "sale_line_id": str(line_id),
                    "returnable": str(remaining),
                    "requested": str(quantity),
                },
            )

    sale_return = SaleReturn(
        tenant_id=ctx.tenant_id,
        number=next_number(db, SaleReturn, ctx.tenant_id, "sale_return", now=returned_at),
        sale_id=sale.id,
        branch_id=sale.branch_id,
        location_id=sale.location_id,
        customer_id=sale.customer_id,
        returned_at=returned_at,
        reason=data.reason.strip(),
        subtotal=ZERO,
        discount_total=ZERO,
        tax_total=ZERO,
        total_amount=ZERO,
        cost_total=ZERO,
        currency=sale.currency,
        note=data.note,
        idempotency_key=data.idempotency_key,
        created_by_id=ctx.user_id,
    )
    # Appended through the relationship, not db.add: the sale's ``returns`` are
    # eagerly loaded, so a row attached by foreign key alone would leave the
    # collection stale and ``returned_total`` reading zero.
    sale.returns.append(sale_return)
    db.flush()

    refs = MovementRefs(
        db,
        ctx.tenant_id,
        variant_ids=[by_id[line_id].variant_id for line_id in wanted],
        location_ids=[sale.location_id],
    )

    subtotal = discount_total = tax_total = total = cost_total = ZERO
    for index, (line_id, quantity) in enumerate(wanted.items()):
        line = by_id[line_id]
        discount, tax, line_total = _line_value(
            line, quantity, already.get(line_id, ReturnedSoFar())
        )
        restock = restock_of[line_id]

        sale_return.lines.append(
            SaleReturnLine(
                sale_return_id=sale_return.id,
                sale_line_id=line.id,
                product_id=line.product_id,
                variant_id=line.variant_id,
                description=line.description,
                quantity=quantity,
                unit_price=line.unit_price,
                discount_amount=discount,
                tax_rate=line.tax_rate,
                tax_amount=tax,
                line_total=line_total,
                unit_cost=line.unit_cost,
                restock=restock,
            )
        )

        subtotal = quantize_money(subtotal + quantize_money(Decimal(line.unit_price) * quantity))
        discount_total = quantize_money(discount_total + discount)
        tax_total = quantize_money(tax_total + tax)
        total = quantize_money(total + line_total)
        if line.unit_cost is not None:
            cost_total = quantize_money(cost_total + Decimal(line.unit_cost) * quantity)

        if refs.variant(line.variant_id).product.track_stock:
            post_movement(
                db,
                ctx,
                StockPosting(
                    variant_id=line.variant_id,
                    location_id=sale.location_id,
                    quantity=quantity,
                    reason=MovementReason.SALE_RETURN,
                    unit_cost=line.unit_cost,
                    source_type="sale_return",
                    source_id=sale_return.id,
                    idempotency_key=f"return:{sale_return.id}:{index}",
                    note=f"Return {sale_return.number} of sale {sale.number}",
                ),
                occurred_at=returned_at,
                refs=refs,
            )
            if not restock:
                # The goods came back and are not sellable.  Writing them off
                # here keeps the loss on the ledger with a reason and an actor,
                # the same way a transfer shortfall is handled.
                post_movement(
                    db,
                    ctx,
                    StockPosting(
                        variant_id=line.variant_id,
                        location_id=sale.location_id,
                        quantity=-quantity,
                        reason=MovementReason.LOSS,
                        unit_cost=line.unit_cost,
                        source_type="sale_return",
                        source_id=sale_return.id,
                        idempotency_key=f"return-loss:{sale_return.id}:{index}",
                        note=(
                            f"Return {sale_return.number}: not fit to sell again "
                            f"({sale_return.reason})"
                        ),
                    ),
                    occurred_at=returned_at,
                    # Writing off what just arrived cannot be refused for stock.
                    allow_negative=True,
                    refs=refs,
                )

    sale_return.subtotal = subtotal
    sale_return.discount_total = discount_total
    sale_return.tax_total = tax_total
    sale_return.total_amount = total
    sale_return.cost_total = cost_total
    db.flush()

    _settle(db, ctx, sale, sale_return, data)

    record_audit(
        db,
        action=AuditAction.SALE_RETURNED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="sale_return",
        entity_id=sale_return.id,
        summary=(
            f"Return {sale_return.number} of sale {sale.number} for "
            f"{sale_return.total_amount} {sale_return.currency}: {sale_return.reason}"
        ),
        payload={
            "sale_id": str(sale.id),
            "line_count": len(sale_return.lines),
            "refunded": str(sale_return.refunded_amount),
            "credited": str(sale_return.credited_amount),
            "restocked": [str(line.quantity) for line in sale_return.lines if line.restock],
        },
    )
    db.flush()
    return sale_return


def _settle(
    db: Session, ctx: AuthContext, sale: Sale, sale_return: SaleReturn, data: SaleReturnInput
) -> None:
    """Put the value back: against what is owed first, then in the customer's hand.

    Handing cash to someone who still owes money on the same sale would be
    paying them twice, so an outstanding balance absorbs the return first.
    What is left can only be paid back up to what was actually taken for this
    sale — the business cannot refund money it never received.
    """
    value = Decimal(sale_return.total_amount)
    if value <= ZERO:
        sale_return.refund_method = RefundMethod.NONE
        return

    credit_transaction = db.execute(
        tenant_query(CreditTransaction, ctx.tenant_id).where(
            CreditTransaction.sale_id == sale.id,
            CreditTransaction.cancelled_at.is_(None),
        )
    ).scalar_one_or_none()

    outstanding = Decimal(credit_transaction.balance) if credit_transaction else ZERO
    credited = min(value, max(outstanding, ZERO))
    refundable = quantize_money(value - credited)

    # Never more than was taken for this sale.
    taken = ZERO
    for payment in sale.payments:
        if payment.is_reversed:
            continue
        amount = Decimal(payment.amount)
        taken += amount if payment.direction == PaymentDirection.IN else -amount
    refunded = min(refundable, max(taken, ZERO))

    if credited > ZERO and credit_transaction is not None:
        credit_transaction.payments.append(
            Payment(
                tenant_id=ctx.tenant_id,
                direction=PaymentDirection.IN,
                # Not money through the till: value taken off what was owed.
                method=PaymentMethod.CREDIT_NOTE,
                amount=quantize_money(credited),
                currency=sale_return.currency,
                paid_at=sale_return.returned_at,
                branch_id=sale_return.branch_id,
                # Deliberately not linked to the sale: the sale's own balance
                # already falls by the returned value, and counting it twice
                # would make the sale look overpaid.
                credit_transaction_id=credit_transaction.id,
                customer_id=sale_return.customer_id,
                reference=sale_return.number,
                note=f"Return {sale_return.number}: {sale_return.reason}",
                idempotency_key=(
                    f"return-credit:{sale_return.id}" if sale_return.id else None
                ),
                created_by_id=ctx.user_id,
            )
        )
        db.flush()
        credit_service.recalculate(
            db, credit_transaction, today=local_date(sale_return.returned_at, ctx.tenant.timezone)
        )

    if refunded > ZERO:
        sale.payments.append(
            Payment(
                tenant_id=ctx.tenant_id,
                direction=PaymentDirection.OUT,
                method=data.refund_method or _original_method(sale),
                amount=quantize_money(refunded),
                currency=sale_return.currency,
                paid_at=sale_return.returned_at,
                branch_id=sale_return.branch_id,
                sale_id=sale.id,
                customer_id=sale_return.customer_id,
                reference=sale_return.number,
                note=f"Refund for return {sale_return.number}",
                idempotency_key=f"return-refund:{sale_return.id}",
                created_by_id=ctx.user_id,
            )
        )

    sale_return.credited_amount = quantize_money(credited)
    sale_return.refunded_amount = quantize_money(refunded)
    if credited > ZERO and refunded > ZERO:
        sale_return.refund_method = RefundMethod.MIXED
    elif credited > ZERO:
        sale_return.refund_method = RefundMethod.CREDIT
    elif refunded > ZERO:
        sale_return.refund_method = RefundMethod.CASH
    else:
        sale_return.refund_method = RefundMethod.NONE
    db.flush()


def _original_method(sale: Sale) -> PaymentMethod:
    """Refund the way they paid, falling back to cash."""
    for payment in sale.payments:
        if (
            not payment.is_reversed
            and payment.direction == PaymentDirection.IN
            and payment.method != PaymentMethod.CREDIT_NOTE
        ):
            return payment.method
    return PaymentMethod.CASH
