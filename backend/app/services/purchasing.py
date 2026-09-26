"""Stock receipt with landed cost and supplier credit (PRD 8.2, 11.2, A3).

Receiving posts stock exactly once and, where the amount paid falls short,
opens one payable.  Later payments never re-post stock or re-count the cost.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.audit import AuditAction, record_audit
from app.core.clock import local_date
from app.core.db import utcnow
from app.core.errors import ValidationError
from app.core.permissions import Permission
from app.core.tenancy import (
    AuthContext,
    get_tenant_object,
    resolve_branch,
    resolve_location,
    tenant_query,
)
from app.models.catalogue import ProductVariant
from app.models.contacts import Supplier
from app.models.credit import CreditKind, CreditTransaction
from app.models.inventory import MovementReason
from app.models.purchasing import Purchase, PurchaseLine, PurchaseStatus
from app.models.sales import Payment, PaymentDirection, PaymentMethod
from app.services import credit as credit_service
from app.services.inventory import (
    StockPosting,
    get_balance,
    post_movement,
    update_average_cost,
)
from app.services.numbering import next_number
from app.services.pricing import allocate_shared_cost, quantize_money

ZERO = Decimal("0.00")

ALLOCATION_METHODS = {"by_value", "by_quantity"}


@dataclass(slots=True)
class PurchaseLineInput:
    variant_id: uuid.UUID
    quantity: Decimal
    unit_cost: Decimal


@dataclass(slots=True)
class PurchaseInput:
    lines: list[PurchaseLineInput]
    supplier_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    transport_cost: Decimal = ZERO
    other_costs: Decimal = ZERO
    #: ``by_value`` (default) or ``by_quantity`` (PRD open decision 25).
    cost_allocation_method: str = "by_value"
    amount_paid: Decimal = ZERO
    payment_method: PaymentMethod = PaymentMethod.CASH
    supplier_invoice_ref: str | None = None
    note: str | None = None
    received_at: datetime | None = None
    due_date: date | None = None
    due_date_preset: str | None = None
    credit_note: str | None = None
    idempotency_key: str | None = None
    #: Update each variant's selling price from the new landed cost.
    reprice_from_cost: bool = False


@dataclass(slots=True)
class PurchaseResult:
    purchase: Purchase
    credit_transaction: CreditTransaction | None
    repriced: list[uuid.UUID] = field(default_factory=list)


def receive_purchase(db: Session, ctx: AuthContext, data: PurchaseInput) -> PurchaseResult:
    ctx.require(Permission.PURCHASE_CREATE, Permission.STOCK_RECEIVE)
    if not data.lines:
        raise ValidationError("A purchase needs at least one product")
    if data.cost_allocation_method not in ALLOCATION_METHODS:
        raise ValidationError(
            f"Unknown cost allocation method '{data.cost_allocation_method}'",
            details={"allowed": sorted(ALLOCATION_METHODS)},
        )

    if data.idempotency_key:
        existing = db.execute(
            tenant_query(Purchase, ctx.tenant_id).where(
                Purchase.idempotency_key == data.idempotency_key
            )
        ).scalar_one_or_none()
        if existing is not None:
            credit = db.execute(
                tenant_query(CreditTransaction, ctx.tenant_id).where(
                    CreditTransaction.purchase_id == existing.id
                )
            ).scalar_one_or_none()
            return PurchaseResult(purchase=existing, credit_transaction=credit)

    branch = resolve_branch(db, ctx, data.branch_id)
    location = resolve_location(db, ctx, branch, data.location_id)
    supplier = get_tenant_object(
        db, Supplier, data.supplier_id, ctx.tenant_id, label="Supplier", required=False
    )
    received_at = data.received_at or utcnow()

    variants: list[ProductVariant] = []
    for line in data.lines:
        if Decimal(line.quantity) <= 0:
            raise ValidationError("Purchase quantities must be positive")
        if Decimal(line.unit_cost) < 0:
            raise ValidationError("Unit cost cannot be negative")
        variant = db.execute(
            tenant_query(ProductVariant, ctx.tenant_id).where(
                ProductVariant.id == line.variant_id
            )
        ).scalar_one_or_none()
        if variant is None:
            raise ValidationError("Product not found")
        variants.append(variant)

    line_values = [
        quantize_money(Decimal(line.unit_cost) * Decimal(line.quantity)) for line in data.lines
    ]
    goods_total = quantize_money(sum(line_values, ZERO))
    transport_total = quantize_money(Decimal(data.transport_cost))
    other_total = quantize_money(Decimal(data.other_costs))
    shared_cost = quantize_money(transport_total + other_total)
    weights = (
        line_values
        if data.cost_allocation_method == "by_value"
        else [Decimal(line.quantity) for line in data.lines]
    )
    allocations = allocate_shared_cost(shared_cost, weights)
    total_amount = quantize_money(goods_total + shared_cost)

    purchase = Purchase(
        tenant_id=ctx.tenant_id,
        number=next_number(db, Purchase, ctx.tenant_id, "purchase", now=received_at),
        supplier_id=supplier.id if supplier else None,
        branch_id=branch.id,
        location_id=location.id,
        status=PurchaseStatus.RECEIVED,
        received_at=received_at,
        goods_total=goods_total,
        transport_cost=quantize_money(Decimal(data.transport_cost)),
        other_costs=quantize_money(Decimal(data.other_costs)),
        total_amount=total_amount,
        currency=ctx.tenant.currency,
        cost_allocation_method=data.cost_allocation_method,
        supplier_invoice_ref=data.supplier_invoice_ref,
        note=data.note,
        idempotency_key=data.idempotency_key,
        created_by_id=ctx.user_id,
    )
    db.add(purchase)
    db.flush()

    repriced: list[uuid.UUID] = []
    for index, (line, variant, allocation) in enumerate(zip(data.lines, variants, allocations, strict=False)):
        quantity = Decimal(line.quantity)
        unit_cost = quantize_money(Decimal(line.unit_cost))
        purchase_line = PurchaseLine(
            purchase_id=purchase.id,
            product_id=variant.product_id,
            variant_id=variant.id,
            description=variant.display_name,
            quantity=quantity,
            unit_cost=unit_cost,
            allocated_cost=allocation,
            line_total=quantize_money(unit_cost * quantity + allocation),
        )
        db.add(purchase_line)
        landed_unit_cost = quantize_money(purchase_line.landed_unit_cost)

        if variant.product.track_stock:
            on_hand_before = get_balance(db, ctx.tenant_id, variant.id, location.id)
            post_movement(
                db,
                ctx,
                StockPosting(
                    variant_id=variant.id,
                    location_id=location.id,
                    quantity=quantity,
                    reason=MovementReason.PURCHASE,
                    unit_cost=landed_unit_cost,
                    source_type="purchase",
                    source_id=purchase.id,
                    idempotency_key=f"purchase:{purchase.id}:{index}",
                    note=f"Purchase {purchase.number}",
                ),
                occurred_at=received_at,
            )
            update_average_cost(variant, quantity, landed_unit_cost, on_hand_before)
        else:
            variant.average_cost = landed_unit_cost

        # Keep the purchasing inputs current so the product page explains the
        # latest landed cost: the line's share of transport and of other costs,
        # each per unit.
        variant.purchase_price = unit_cost
        transport_share = (
            quantize_money(allocation * transport_total / shared_cost) if shared_cost else ZERO
        )
        variant.transport_cost = quantize_money(transport_share / quantity)
        variant.other_costs = quantize_money((allocation - transport_share) / quantity)

        if data.reprice_from_cost:
            from app.services.pricing import suggest_price_for_variant

            suggested, rule = suggest_price_for_variant(db, ctx.tenant_id, variant)
            if suggested is not None and rule is not None:
                variant.selling_price = suggested
                repriced.append(variant.id)

    amount_paid = quantize_money(Decimal(data.amount_paid))
    if amount_paid < 0:
        raise ValidationError("Amount paid cannot be negative")
    if amount_paid > total_amount:
        raise ValidationError(
            f"Amount paid ({amount_paid}) is more than the purchase total ({total_amount})",
            code="overpayment",
        )

    credit_transaction: CreditTransaction | None = None
    balance = quantize_money(total_amount - amount_paid)
    received_on = local_date(received_at, ctx.tenant.timezone)
    if balance > ZERO:
        ctx.require(Permission.CREDIT_CREATE)
        due_date = credit_service.resolve_due_date(
            data.due_date_preset, data.due_date, today=received_on
        )
        credit_transaction = credit_service.create_credit_transaction(
            db,
            ctx,
            kind=CreditKind.PAYABLE,
            amount=total_amount,
            branch_id=branch.id,
            supplier_id=purchase.supplier_id,
            purchase_id=purchase.id,
            due_date=due_date,
            issued_on=received_on,
            agreement_note=data.credit_note,
        )

    if amount_paid > ZERO:
        db.add(
            Payment(
                tenant_id=ctx.tenant_id,
                direction=PaymentDirection.OUT,
                method=data.payment_method,
                amount=amount_paid,
                currency=purchase.currency,
                paid_at=received_at,
                branch_id=branch.id,
                purchase_id=purchase.id,
                supplier_id=purchase.supplier_id,
                credit_transaction_id=(
                    credit_transaction.id if credit_transaction else None
                ),
                reference=data.supplier_invoice_ref,
                idempotency_key=(
                    f"{data.idempotency_key}:pay" if data.idempotency_key else None
                ),
                created_by_id=ctx.user_id,
            )
        )
        db.flush()
        if credit_transaction is not None:
            credit_service.recalculate(db, credit_transaction, today=received_on)

    record_audit(
        db,
        action=AuditAction.PURCHASE_RECEIVED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="purchase",
        entity_id=purchase.id,
        summary=f"Received {purchase.number} for {total_amount} {purchase.currency}",
        payload={
            "supplier_id": str(purchase.supplier_id) if purchase.supplier_id else None,
            "paid": str(amount_paid),
            "balance": str(balance),
            "allocation": data.cost_allocation_method,
        },
    )
    db.flush()
    db.refresh(purchase)
    return PurchaseResult(
        purchase=purchase, credit_transaction=credit_transaction, repriced=repriced
    )
