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
    Sale,
    SaleLine,
    SaleStatus,
)
from app.services import credit as credit_service
from app.services.inventory import StockPosting, post_movement
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

    for index, line_input in enumerate(data.lines):
        variant = db.execute(
            tenant_query(ProductVariant, ctx.tenant_id).where(
                ProductVariant.id == line_input.variant_id
            )
        ).scalar_one_or_none()
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
    if not reason:
        raise ValidationError("A reason is required to void a sale")

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
