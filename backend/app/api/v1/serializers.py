"""Model → response conversions that respect what the caller may see."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permissions import Permission
from app.core.tenancy import AuthContext
from app.models.catalogue import Product, ProductVariant
from app.models.commerce import Quotation
from app.models.credit import CreditTransaction
from app.models.inventory import StockBalance
from app.models.sales import Sale
from app.schemas.catalogue import ProductOut, VariantOut
from app.schemas.operations import (
    CreditTransactionOut,
    PaymentOut,
    QuotationOut,
    SaleLineOut,
    SaleOut,
)
from app.services.inventory import classify_stock_level


def variant_out(
    ctx: AuthContext, variant: ProductVariant, quantity: Decimal | None = None
) -> VariantOut:
    show_cost = ctx.has(Permission.COST_VIEW)
    return VariantOut(
        id=variant.id,
        name=variant.name,
        sku=variant.sku,
        barcode=variant.barcode,
        is_default=variant.is_default,
        selling_price=variant.selling_price,
        tax_rate=variant.tax_rate,
        min_stock=variant.min_stock,
        reorder_level=variant.reorder_level,
        quantity_on_hand=quantity,
        purchase_price=variant.purchase_price if show_cost else None,
        transport_cost=variant.transport_cost if show_cost else None,
        other_costs=variant.other_costs if show_cost else None,
        landed_cost=variant.landed_cost if show_cost else None,
        average_cost=variant.average_cost if show_cost else None,
    )


def stock_totals(
    db: Session, ctx: AuthContext, product_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    """On-hand per variant, limited to the branches this user may see."""
    if not product_ids:
        return {}
    branch_ids = ctx.visible_branch_ids(db)
    if not branch_ids:
        return {}
    rows = db.execute(
        select(StockBalance.variant_id, func.sum(StockBalance.quantity))
        .where(
            StockBalance.tenant_id == ctx.tenant_id,
            StockBalance.product_id.in_(product_ids),
            StockBalance.branch_id.in_(branch_ids),
        )
        .group_by(StockBalance.variant_id)
    )
    return {row[0]: Decimal(row[1] or 0) for row in rows}


def product_out(
    ctx: AuthContext, product: Product, stock: dict[uuid.UUID, Decimal] | None = None
) -> ProductOut:
    stock = stock or {}
    variants = [
        variant_out(ctx, variant, stock.get(variant.id)) for variant in product.variants
    ]
    total = sum((stock.get(v.id, Decimal("0")) for v in product.variants), Decimal("0"))
    default = product.default_variant
    status = (
        classify_stock_level(total, default.min_stock, default.reorder_level)
        if product.track_stock
        else None
    )
    return ProductOut(
        id=product.id,
        name=product.name,
        sku=product.sku,
        description=product.description,
        brand=product.brand,
        unit_of_measure=product.unit_of_measure,
        category_id=product.category_id,
        category_name=product.category.name if product.category else None,
        is_active=product.is_active,
        is_published=product.is_published,
        track_stock=product.track_stock,
        variants=variants,
        quantity_on_hand=total if product.track_stock else None,
        stock_status=status,
    )


def sale_out(ctx: AuthContext, sale: Sale) -> SaleOut:
    show_cost = ctx.has(Permission.COST_VIEW)
    return SaleOut(
        id=sale.id,
        number=sale.number,
        branch_id=sale.branch_id,
        customer_id=sale.customer_id,
        salesperson_id=sale.salesperson_id,
        status=str(sale.status),
        sold_at=sale.sold_at,
        subtotal=sale.subtotal,
        discount_total=sale.discount_total,
        tax_total=sale.tax_total,
        total_amount=sale.total_amount,
        currency=sale.currency,
        amount_paid=sale.amount_paid,
        balance_due=sale.balance_due,
        note=sale.note,
        lines=[
            SaleLineOut(
                id=line.id,
                product_id=line.product_id,
                variant_id=line.variant_id,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_amount=line.discount_amount,
                tax_rate=line.tax_rate,
                tax_amount=line.tax_amount,
                line_total=line.line_total,
                unit_cost=line.unit_cost if show_cost else None,
            )
            for line in sale.lines
        ],
        payments=[PaymentOut.model_validate(p) for p in sale.payments],
        cost_total=sale.cost_total if show_cost else None,
        gross_profit=sale.gross_profit if show_cost else None,
    )


def credit_out(
    transaction: CreditTransaction,
    *,
    counterparty_name: str | None = None,
    today=None,
) -> CreditTransactionOut:
    from datetime import date as date_cls

    from app.services.credit import is_overdue

    today = today or date_cls.today()
    overdue = is_overdue(transaction, today=today)
    return CreditTransactionOut(
        id=transaction.id,
        reference=transaction.reference,
        kind=transaction.kind,
        status=str(transaction.status),
        branch_id=transaction.branch_id,
        customer_id=transaction.customer_id,
        supplier_id=transaction.supplier_id,
        sale_id=transaction.sale_id,
        purchase_id=transaction.purchase_id,
        original_amount=transaction.original_amount,
        amount_paid=transaction.amount_paid,
        balance=transaction.balance,
        currency=transaction.currency,
        issued_on=transaction.issued_on,
        due_date=transaction.due_date,
        agreement_note=transaction.agreement_note,
        counterparty_name=counterparty_name,
        is_overdue=overdue,
        days_overdue=(
            (today - transaction.due_date).days
            if overdue and transaction.due_date
            else None
        ),
    )


def quotation_out(quotation: Quotation, *, include_share: bool = True) -> QuotationOut:
    from app.services.commerce import quotation_status_for, share_links

    payload = QuotationOut.model_validate(quotation)
    payload.status = str(quotation_status_for(quotation))
    if include_share:
        payload.share = share_links(quotation)
    return payload
