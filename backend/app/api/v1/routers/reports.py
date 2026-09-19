"""Dashboards and reports (PRD 15)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Query

from app.core.deps import Ctx, DbSession
from app.core.permissions import Permission
from app.models.credit import CreditKind
from app.services import reports as service

router = APIRouter(tags=["reports"])

PERIODS = "today|yesterday|7d|30d|month|year|custom"


def _range(period: str, date_from: date | None, date_to: date | None) -> service.DateRange:
    if period == "custom":
        if date_from is None or date_to is None:
            from app.core.errors import ValidationError

            raise ValidationError("A custom period needs both a start and an end date")
        if date_to < date_from:
            from app.core.errors import ValidationError

            raise ValidationError("The end date is before the start date")
        return service.DateRange(date_from, date_to)
    return service.range_for(period)


@router.get("/dashboard")
def dashboard(ctx: Ctx, db: DbSession) -> dict:
    """Home screen: today's figures, alerts and balances the user may see."""
    return service.home_dashboard(db, ctx)


@router.get("/reports/sales")
def sales_report(
    ctx: Ctx,
    db: DbSession,
    period: str = Query("30d", pattern=f"^({PERIODS})$"),
    date_from: date | None = None,
    date_to: date | None = None,
    branch_id: uuid.UUID | None = None,
) -> dict:
    period_range = _range(period, date_from, date_to)
    branches = [branch_id] if branch_id else None
    summary = service.sales_summary(db, ctx, period_range, branches)
    return {
        "summary": summary.as_dict(include_cost=ctx.has(Permission.COST_VIEW)),
        "by_day": service.sales_by_day(db, ctx, period_range, branches),
        "by_payment_method": service.sales_by_payment_method(db, ctx, period_range, branches),
        "basis": "Completed sales only; voided sales are excluded.",
    }


@router.get("/reports/products")
def product_report(
    ctx: Ctx,
    db: DbSession,
    period: str = Query("30d", pattern=f"^({PERIODS})$"),
    date_from: date | None = None,
    date_to: date | None = None,
    branch_id: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    period_range = _range(period, date_from, date_to)
    branches = [branch_id] if branch_id else None
    return {
        "period": period_range.as_dict(),
        "currency": ctx.tenant.currency,
        "products": service.product_performance(
            db, ctx, period_range, branch_ids=branches, limit=limit
        ),
        "categories": service.category_performance(db, ctx, period_range, branches),
        "note": "Ranked by revenue for the stated period. This is a data view, not a rating.",
    }


@router.get("/reports/salespeople")
def salesperson_report(
    ctx: Ctx,
    db: DbSession,
    period: str = Query("30d", pattern=f"^({PERIODS})$"),
    date_from: date | None = None,
    date_to: date | None = None,
    branch_id: uuid.UUID | None = None,
) -> dict:
    period_range = _range(period, date_from, date_to)
    branches = [branch_id] if branch_id else None
    return {
        "period": period_range.as_dict(),
        "currency": ctx.tenant.currency,
        "salespeople": service.salesperson_performance(db, ctx, period_range, branches),
        "note": (
            "Total sales recorded by each user in the stated period. "
            "It does not rank people."
        ),
    }


@router.get("/reports/branches")
def branch_report(
    ctx: Ctx,
    db: DbSession,
    period: str = Query("30d", pattern=f"^({PERIODS})$"),
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    period_range = _range(period, date_from, date_to)
    return {
        "period": period_range.as_dict(),
        "currency": ctx.tenant.currency,
        "branches": service.branch_comparison(db, ctx, period_range),
        "note": "Only branches you have access to are shown.",
    }


@router.get("/reports/inventory")
def inventory_report(
    ctx: Ctx, db: DbSession, branch_id: uuid.UUID | None = None
) -> dict:
    branches = [branch_id] if branch_id else None
    valuation = service.inventory_valuation(db, ctx, branches)
    from app.services.inventory import low_stock_items

    items = low_stock_items(db, ctx.tenant_id, ctx.visible_branch_ids(db))
    return {
        "as_of": date.today().isoformat(),
        "currency": ctx.tenant.currency,
        "total_quantity": str(valuation.total_quantity),
        "product_count": valuation.product_count,
        "value_at_cost": (
            str(valuation.value_at_cost) if valuation.value_at_cost is not None else None
        ),
        "potential_sales_value": (
            str(valuation.potential_sales_value)
            if valuation.potential_sales_value is not None
            else None
        ),
        "valuation_basis": valuation.basis,
        "low_stock_count": len(items),
    }


@router.get("/reports/credit")
def credit_report(
    ctx: Ctx, db: DbSession, kind: CreditKind = CreditKind.RECEIVABLE
) -> dict:
    if kind == CreditKind.PAYABLE:
        ctx.require(Permission.PURCHASE_VIEW)
    return {
        "as_of": date.today().isoformat(),
        "summary": service.credit_summary(db, ctx, kind).as_dict(),
        "aging": service.credit_aging(db, ctx, kind),
        "basis": (
            "Balance is the transaction amount minus payments received. "
            "A balance with no due date is outstanding but never overdue."
        ),
    }
