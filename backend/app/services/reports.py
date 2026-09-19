"""Dashboards and reports (PRD 15).

Every figure states its date range, currency and calculation basis, and every
query is filtered to the branches the caller may see.  Profit uses the cost
snapshot taken at sale time, never today's cost.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import PermissionDenied
from app.core.permissions import Permission
from app.core.tenancy import AuthContext, tenant_query
from app.models.access import User
from app.models.catalogue import Category, Product, ProductVariant
from app.models.credit import CreditKind, CreditStatus, CreditTransaction
from app.models.inventory import StockBalance
from app.models.organisation import Branch
from app.models.sales import Payment, Sale, SaleLine, SaleStatus

ZERO = Decimal("0.00")


@dataclass(slots=True)
class DateRange:
    start: date
    end: date

    @property
    def start_dt(self) -> datetime:
        return datetime.combine(self.start, time.min, tzinfo=UTC)

    @property
    def end_dt(self) -> datetime:
        return datetime.combine(self.end, time.max, tzinfo=UTC)

    def as_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


def range_for(period: str, *, today: date | None = None) -> DateRange:
    today = today or date.today()
    if period == "today":
        return DateRange(today, today)
    if period == "yesterday":
        return DateRange(today - timedelta(days=1), today - timedelta(days=1))
    if period == "7d":
        return DateRange(today - timedelta(days=6), today)
    if period == "30d":
        return DateRange(today - timedelta(days=29), today)
    if period == "month":
        return DateRange(today.replace(day=1), today)
    if period == "year":
        return DateRange(today.replace(month=1, day=1), today)
    return DateRange(today - timedelta(days=29), today)


def _sales_scope(
    ctx: AuthContext, db: Session, period: DateRange, branch_ids: list[uuid.UUID] | None
) -> Select:
    allowed = ctx.visible_branch_ids(db)
    if branch_ids:
        for branch_id in branch_ids:
            ctx.require_branch(branch_id)
        allowed = [b for b in allowed if b in set(branch_ids)]
    return (
        tenant_query(Sale, ctx.tenant_id)
        .where(
            Sale.status == SaleStatus.COMPLETED,
            Sale.sold_at >= period.start_dt,
            Sale.sold_at <= period.end_dt,
            Sale.branch_id.in_(allowed),
        )
    )


@dataclass(slots=True)
class SalesSummary:
    period: DateRange
    currency: str
    sale_count: int
    items_sold: Decimal
    gross_sales: Decimal
    discounts: Decimal
    tax: Decimal
    net_sales: Decimal
    cost_of_goods: Decimal | None
    gross_profit: Decimal | None
    #: What "profit" means here, stated on every report (PRD 15).
    profit_basis: str = "net sales excluding tax, minus sale-time cost snapshots"

    def as_dict(self, *, include_cost: bool) -> dict:
        payload = {
            "period": self.period.as_dict(),
            "currency": self.currency,
            "sale_count": self.sale_count,
            "items_sold": str(self.items_sold),
            "gross_sales": str(self.gross_sales),
            "discounts": str(self.discounts),
            "tax": str(self.tax),
            "net_sales": str(self.net_sales),
        }
        if include_cost:
            payload["cost_of_goods"] = str(self.cost_of_goods or ZERO)
            payload["gross_profit"] = str(self.gross_profit or ZERO)
            payload["profit_basis"] = self.profit_basis
        return payload


def sales_summary(
    db: Session,
    ctx: AuthContext,
    period: DateRange,
    branch_ids: list[uuid.UUID] | None = None,
) -> SalesSummary:
    ctx.require(Permission.SALE_VIEW)
    scope = _sales_scope(ctx, db, period, branch_ids).subquery()
    row = db.execute(
        select(
            func.count().label("sale_count"),
            func.coalesce(func.sum(scope.c.subtotal), 0).label("gross"),
            func.coalesce(func.sum(scope.c.discount_total), 0).label("discounts"),
            func.coalesce(func.sum(scope.c.tax_total), 0).label("tax"),
            func.coalesce(func.sum(scope.c.total_amount), 0).label("net"),
            func.coalesce(func.sum(scope.c.cost_total), 0).label("cost"),
        ).select_from(scope)
    ).one()

    items = db.execute(
        select(func.coalesce(func.sum(SaleLine.quantity), 0))
        .select_from(SaleLine)
        .join(scope, scope.c.id == SaleLine.sale_id)
    ).scalar_one()

    net = Decimal(row.net or 0)
    tax = Decimal(row.tax or 0)
    cost = Decimal(row.cost or 0)
    has_cost = ctx.has(Permission.COST_VIEW)
    return SalesSummary(
        period=period,
        currency=ctx.tenant.currency,
        sale_count=int(row.sale_count or 0),
        items_sold=Decimal(items or 0),
        gross_sales=Decimal(row.gross or 0),
        discounts=Decimal(row.discounts or 0),
        tax=tax,
        net_sales=net,
        cost_of_goods=cost if has_cost else None,
        gross_profit=(net - tax - cost) if has_cost else None,
    )


def sales_by_day(
    db: Session, ctx: AuthContext, period: DateRange, branch_ids: list[uuid.UUID] | None = None
) -> list[dict]:
    ctx.require(Permission.REPORT_SALES)
    scope = _sales_scope(ctx, db, period, branch_ids).subquery()
    rows = db.execute(
        select(
            func.date(scope.c.sold_at).label("day"),
            func.count().label("sale_count"),
            func.coalesce(func.sum(scope.c.total_amount), 0).label("total"),
        )
        .select_from(scope)
        .group_by(func.date(scope.c.sold_at))
        .order_by(func.date(scope.c.sold_at))
    )
    return [
        {"date": str(row.day), "sale_count": int(row.sale_count), "total": str(Decimal(row.total or 0))}
        for row in rows
    ]


def sales_by_payment_method(
    db: Session, ctx: AuthContext, period: DateRange, branch_ids: list[uuid.UUID] | None = None
) -> list[dict]:
    ctx.require(Permission.REPORT_SALES)
    scope = _sales_scope(ctx, db, period, branch_ids).subquery()
    rows = db.execute(
        select(
            Payment.method,
            func.count().label("count"),
            func.coalesce(func.sum(Payment.amount), 0).label("total"),
        )
        .select_from(Payment)
        .join(scope, scope.c.id == Payment.sale_id)
        .where(Payment.is_reversed.is_(False))
        .group_by(Payment.method)
        .order_by(func.sum(Payment.amount).desc())
    )
    return [
        {"method": str(row.method), "count": int(row.count), "total": str(Decimal(row.total or 0))}
        for row in rows
    ]


def product_performance(
    db: Session,
    ctx: AuthContext,
    period: DateRange,
    *,
    branch_ids: list[uuid.UUID] | None = None,
    limit: int = 20,
) -> list[dict]:
    """Units and revenue per product.  A data view, not a "best product" claim."""
    ctx.require(Permission.REPORT_SALES)
    scope = _sales_scope(ctx, db, period, branch_ids).subquery()
    include_cost = ctx.has(Permission.COST_VIEW)

    rows = db.execute(
        select(
            Product.id,
            Product.name,
            func.coalesce(func.sum(SaleLine.quantity), 0).label("quantity"),
            func.coalesce(func.sum(SaleLine.line_total), 0).label("revenue"),
            func.coalesce(
                func.sum(SaleLine.quantity * func.coalesce(SaleLine.unit_cost, 0)), 0
            ).label("cost"),
        )
        .select_from(SaleLine)
        .join(scope, scope.c.id == SaleLine.sale_id)
        .join(Product, Product.id == SaleLine.product_id)
        .group_by(Product.id, Product.name)
        .order_by(func.sum(SaleLine.line_total).desc())
        .limit(limit)
    )
    results = []
    for row in rows:
        entry = {
            "product_id": str(row.id),
            "name": row.name,
            "quantity_sold": str(Decimal(row.quantity or 0)),
            "revenue": str(Decimal(row.revenue or 0)),
        }
        if include_cost:
            entry["cost"] = str(Decimal(row.cost or 0))
            entry["gross_profit"] = str(Decimal(row.revenue or 0) - Decimal(row.cost or 0))
        results.append(entry)
    return results


def category_performance(
    db: Session, ctx: AuthContext, period: DateRange, branch_ids: list[uuid.UUID] | None = None
) -> list[dict]:
    ctx.require(Permission.REPORT_SALES)
    scope = _sales_scope(ctx, db, period, branch_ids).subquery()
    rows = db.execute(
        select(
            func.coalesce(Category.name, "Uncategorised").label("category"),
            func.coalesce(func.sum(SaleLine.quantity), 0).label("quantity"),
            func.coalesce(func.sum(SaleLine.line_total), 0).label("revenue"),
        )
        .select_from(SaleLine)
        .join(scope, scope.c.id == SaleLine.sale_id)
        .join(Product, Product.id == SaleLine.product_id)
        .join(Category, Category.id == Product.category_id, isouter=True)
        .group_by(Category.name)
        .order_by(func.sum(SaleLine.line_total).desc())
    )
    return [
        {
            "category": row.category,
            "quantity_sold": str(Decimal(row.quantity or 0)),
            "revenue": str(Decimal(row.revenue or 0)),
        }
        for row in rows
    ]


def salesperson_performance(
    db: Session, ctx: AuthContext, period: DateRange, branch_ids: list[uuid.UUID] | None = None
) -> list[dict]:
    ctx.require(Permission.REPORT_SALES)
    scope = _sales_scope(ctx, db, period, branch_ids).subquery()
    rows = db.execute(
        select(
            User.id,
            User.full_name,
            func.count().label("sale_count"),
            func.coalesce(func.sum(scope.c.total_amount), 0).label("total"),
        )
        .select_from(scope)
        .join(User, User.id == scope.c.salesperson_id)
        .group_by(User.id, User.full_name)
        .order_by(func.sum(scope.c.total_amount).desc())
    )
    return [
        {
            "user_id": str(row.id),
            "name": row.full_name,
            "sale_count": int(row.sale_count),
            "total_sales": str(Decimal(row.total or 0)),
            "period": period.as_dict(),
        }
        for row in rows
    ]


def branch_comparison(
    db: Session, ctx: AuthContext, period: DateRange
) -> list[dict]:
    """Per-branch figures for branches this user may see (PRD 15)."""
    ctx.require(Permission.REPORT_BRANCH_COMPARE)
    allowed = ctx.visible_branch_ids(db)
    if not allowed:
        raise PermissionDenied("You do not have access to any branch")

    scope = _sales_scope(ctx, db, period, None).subquery()
    include_cost = ctx.has(Permission.COST_VIEW)
    rows = db.execute(
        select(
            Branch.id,
            Branch.name,
            func.count(scope.c.id).label("sale_count"),
            func.coalesce(func.sum(scope.c.total_amount), 0).label("total"),
            func.coalesce(func.sum(scope.c.tax_total), 0).label("tax"),
            func.coalesce(func.sum(scope.c.cost_total), 0).label("cost"),
        )
        .select_from(Branch)
        .join(scope, scope.c.branch_id == Branch.id, isouter=True)
        .where(Branch.tenant_id == ctx.tenant_id, Branch.id.in_(allowed))
        .group_by(Branch.id, Branch.name)
        .order_by(Branch.name)
    )
    results = []
    for row in rows:
        entry = {
            "branch_id": str(row.id),
            "branch_name": row.name,
            "sale_count": int(row.sale_count or 0),
            "total_sales": str(Decimal(row.total or 0)),
            "period": period.as_dict(),
            "currency": ctx.tenant.currency,
        }
        if include_cost:
            entry["gross_profit"] = str(
                Decimal(row.total or 0) - Decimal(row.tax or 0) - Decimal(row.cost or 0)
            )
        results.append(entry)
    return results


@dataclass(slots=True)
class InventoryValuation:
    total_quantity: Decimal
    value_at_cost: Decimal | None
    potential_sales_value: Decimal | None
    product_count: int
    basis: str = "average landed cost where known, otherwise entered purchase cost"


def inventory_valuation(
    db: Session, ctx: AuthContext, branch_ids: list[uuid.UUID] | None = None
) -> InventoryValuation:
    ctx.require(Permission.REPORT_INVENTORY)
    allowed = ctx.visible_branch_ids(db)
    if branch_ids:
        for branch_id in branch_ids:
            ctx.require_branch(branch_id)
        allowed = [b for b in allowed if b in set(branch_ids)]

    rows = db.execute(
        select(
            StockBalance.quantity,
            ProductVariant.average_cost,
            ProductVariant.purchase_price,
            ProductVariant.transport_cost,
            ProductVariant.other_costs,
            ProductVariant.selling_price,
            StockBalance.product_id,
        )
        .join(ProductVariant, ProductVariant.id == StockBalance.variant_id)
        .where(StockBalance.tenant_id == ctx.tenant_id, StockBalance.branch_id.in_(allowed))
    ).all()

    total_quantity = ZERO
    value_at_cost = ZERO
    potential = ZERO
    products: set[uuid.UUID] = set()
    for row in rows:
        quantity = Decimal(row.quantity or 0)
        total_quantity += quantity
        products.add(row.product_id)
        cost = row.average_cost
        if cost is None and row.purchase_price is not None:
            cost = (
                Decimal(row.purchase_price)
                + Decimal(row.transport_cost or 0)
                + Decimal(row.other_costs or 0)
            )
        if cost is not None:
            value_at_cost += Decimal(cost) * quantity
        if row.selling_price is not None:
            potential += Decimal(row.selling_price) * quantity

    include_cost = ctx.has(Permission.COST_VIEW)
    return InventoryValuation(
        total_quantity=total_quantity,
        value_at_cost=value_at_cost if include_cost else None,
        potential_sales_value=potential,
        product_count=len(products),
    )


@dataclass(slots=True)
class CreditSummary:
    kind: CreditKind
    currency: str
    total_outstanding: Decimal
    due_today: Decimal
    due_within_7_days: Decimal
    overdue: Decimal
    no_due_date: Decimal
    transaction_count: int

    def as_dict(self) -> dict:
        return {
            "kind": str(self.kind),
            "currency": self.currency,
            "total_outstanding": str(self.total_outstanding),
            "due_today": str(self.due_today),
            "due_within_7_days": str(self.due_within_7_days),
            "overdue": str(self.overdue),
            "no_due_date": str(self.no_due_date),
            "transaction_count": self.transaction_count,
        }


def credit_summary(
    db: Session,
    ctx: AuthContext,
    kind: CreditKind,
    *,
    today: date | None = None,
    branch_ids: list[uuid.UUID] | None = None,
) -> CreditSummary:
    """Summary cards for receivables or payables (PRD 11.5)."""
    ctx.require(Permission.CREDIT_VIEW)
    today = today or date.today()
    allowed = ctx.visible_branch_ids(db)
    if branch_ids:
        for branch_id in branch_ids:
            ctx.require_branch(branch_id)
        allowed = [b for b in allowed if b in set(branch_ids)]

    rows = db.execute(
        tenant_query(CreditTransaction, ctx.tenant_id).where(
            CreditTransaction.kind == kind,
            CreditTransaction.cancelled_at.is_(None),
            CreditTransaction.status != CreditStatus.PAID,
            CreditTransaction.branch_id.in_(allowed + [None]),
        )
    ).scalars().all()

    total = due_today = due_soon = overdue = no_due = ZERO
    horizon = today + timedelta(days=7)
    count = 0
    for transaction in rows:
        balance = transaction.balance
        if balance <= ZERO:
            continue
        count += 1
        total += balance
        if transaction.due_date is None:
            no_due += balance
        elif transaction.due_date < today:
            overdue += balance
        elif transaction.due_date == today:
            due_today += balance
            due_soon += balance
        elif transaction.due_date <= horizon:
            due_soon += balance

    return CreditSummary(
        kind=kind,
        currency=ctx.tenant.currency,
        total_outstanding=total,
        due_today=due_today,
        due_within_7_days=due_soon,
        overdue=overdue,
        no_due_date=no_due,
        transaction_count=count,
    )


def credit_aging(
    db: Session, ctx: AuthContext, kind: CreditKind, *, today: date | None = None
) -> list[dict]:
    """Aging buckets by days past due (PRD 15)."""
    ctx.require(Permission.REPORT_CREDIT)
    today = today or date.today()
    buckets = {
        "not_due": ZERO,
        "no_due_date": ZERO,
        "1_30": ZERO,
        "31_60": ZERO,
        "61_90": ZERO,
        "over_90": ZERO,
    }
    allowed = ctx.visible_branch_ids(db)
    rows = db.execute(
        tenant_query(CreditTransaction, ctx.tenant_id).where(
            CreditTransaction.kind == kind,
            CreditTransaction.cancelled_at.is_(None),
            CreditTransaction.branch_id.in_(allowed + [None]),
        )
    ).scalars()
    for transaction in rows:
        balance = transaction.balance
        if balance <= ZERO:
            continue
        if transaction.due_date is None:
            buckets["no_due_date"] += balance
        elif transaction.due_date >= today:
            buckets["not_due"] += balance
        else:
            days = (today - transaction.due_date).days
            if days <= 30:
                buckets["1_30"] += balance
            elif days <= 60:
                buckets["31_60"] += balance
            elif days <= 90:
                buckets["61_90"] += balance
            else:
                buckets["over_90"] += balance
    return [
        {"bucket": name, "amount": str(amount), "as_of": today.isoformat()}
        for name, amount in buckets.items()
    ]


@dataclass(slots=True)
class Dashboard:
    today: SalesSummary
    low_stock: list[dict] = field(default_factory=list)
    receivables: dict | None = None
    payables: dict | None = None
    setup: list[dict] = field(default_factory=list)
    branch_summary: list[dict] = field(default_factory=list)


def home_dashboard(db: Session, ctx: AuthContext, *, today: date | None = None) -> dict:
    """The home screen: today's sales, alerts and what the user may see (PRD 15)."""
    today = today or date.today()
    period = DateRange(today, today)
    payload: dict = {"date": today.isoformat(), "currency": ctx.tenant.currency}

    if ctx.has(Permission.SALE_VIEW):
        summary = sales_summary(db, ctx, period)
        payload["today"] = summary.as_dict(include_cost=ctx.has(Permission.COST_VIEW))

    if ctx.has(Permission.STOCK_VIEW):
        from app.services.inventory import low_stock_items

        items = low_stock_items(db, ctx.tenant_id, ctx.visible_branch_ids(db))
        payload["low_stock_count"] = len(items)
        payload["low_stock"] = [
            {
                "product_id": str(item.product_id),
                "variant_id": str(item.variant_id),
                "name": item.name,
                "branch_id": str(item.branch_id),
                "quantity": str(item.quantity),
                "severity": item.severity,
            }
            for item in items[:10]
        ]

    if ctx.has(Permission.CREDIT_VIEW):
        payload["receivables"] = credit_summary(
            db, ctx, CreditKind.RECEIVABLE, today=today
        ).as_dict()
        if ctx.has(Permission.PURCHASE_VIEW):
            payload["payables"] = credit_summary(
                db, ctx, CreditKind.PAYABLE, today=today
            ).as_dict()

    if ctx.has(Permission.REPORT_BRANCH_COMPARE):
        payload["branches"] = branch_comparison(db, ctx, period)

    if ctx.has(Permission.BUSINESS_MANAGE):
        from app.services.onboarding import setup_progress

        steps = setup_progress(db, ctx)
        payload["setup"] = [
            {"key": s.key, "label": s.label, "done": s.done, "action_url": s.action_url}
            for s in steps
        ]
        payload["setup_complete"] = all(s.done for s in steps)

    return payload
