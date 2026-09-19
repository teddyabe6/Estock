"""Customers and suppliers (PRD 12)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Query, status
from sqlalchemy import func, or_, select

from app.core.deps import Ctx, DbSession, WritableCtx
from app.core.permissions import Permission
from app.core.tenancy import get_tenant_object, tenant_query
from app.models.contacts import Customer, Supplier
from app.models.credit import CreditKind, CreditTransaction
from app.models.sales import Sale, SaleStatus
from app.schemas.auth import normalise_et_phone
from app.schemas.common import Page
from app.schemas.operations import (
    CustomerIn,
    CustomerOut,
    SupplierIn,
    SupplierOut,
)

router = APIRouter(tags=["contacts"])


def _outstanding(db, tenant_id, *, customer_id=None, supplier_id=None) -> Decimal:
    stmt = select(
        func.coalesce(
            func.sum(CreditTransaction.original_amount - CreditTransaction.amount_paid), 0
        )
    ).where(
        CreditTransaction.tenant_id == tenant_id,
        CreditTransaction.cancelled_at.is_(None),
    )
    if customer_id is not None:
        stmt = stmt.where(
            CreditTransaction.customer_id == customer_id,
            CreditTransaction.kind == CreditKind.RECEIVABLE,
        )
    else:
        stmt = stmt.where(
            CreditTransaction.supplier_id == supplier_id,
            CreditTransaction.kind == CreditKind.PAYABLE,
        )
    return Decimal(db.execute(stmt).scalar_one() or 0)


@router.get("/customers", response_model=Page[CustomerOut])
def list_customers(
    ctx: Ctx,
    db: DbSession,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[CustomerOut]:
    ctx.require(Permission.CUSTOMER_VIEW)
    stmt = tenant_query(Customer, ctx.tenant_id).where(Customer.is_active.is_(True))
    if q:
        pattern = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Customer.name).like(pattern),
                func.lower(Customer.phone).like(pattern),
                func.lower(Customer.company).like(pattern),
            )
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Customer.name).limit(limit).offset(offset)).scalars().all()

    show_credit = ctx.has(Permission.CREDIT_VIEW)
    items = []
    for customer in rows:
        payload = CustomerOut.model_validate(customer)
        if show_credit:
            payload.outstanding_balance = _outstanding(
                db, ctx.tenant_id, customer_id=customer.id
            )
        else:
            payload.credit_limit = None
        items.append(payload)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/customers", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def add_customer(payload: CustomerIn, ctx: WritableCtx, db: DbSession) -> CustomerOut:
    ctx.require(Permission.CUSTOMER_MANAGE)
    data = payload.model_dump()
    data["phone"] = normalise_et_phone(data.get("phone"))
    if data.get("credit_limit") is not None:
        ctx.require(Permission.CREDIT_LIMIT_OVERRIDE)
    customer = Customer(tenant_id=ctx.tenant_id, **data)
    db.add(customer)
    db.flush()
    return CustomerOut.model_validate(customer)


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: uuid.UUID, ctx: Ctx, db: DbSession) -> CustomerOut:
    ctx.require(Permission.CUSTOMER_VIEW)
    customer = get_tenant_object(db, Customer, customer_id, ctx.tenant_id, label="Customer")
    payload = CustomerOut.model_validate(customer)
    if ctx.has(Permission.CREDIT_VIEW):
        payload.outstanding_balance = _outstanding(
            db, ctx.tenant_id, customer_id=customer.id
        )
    else:
        payload.credit_limit = None
    return payload


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
def edit_customer(
    customer_id: uuid.UUID, payload: CustomerIn, ctx: WritableCtx, db: DbSession
) -> CustomerOut:
    ctx.require(Permission.CUSTOMER_MANAGE)
    customer = get_tenant_object(db, Customer, customer_id, ctx.tenant_id, label="Customer")
    changes = payload.model_dump(exclude_unset=True)
    if "credit_limit" in changes or "credit_limit_behaviour" in changes:
        ctx.require(Permission.CREDIT_LIMIT_OVERRIDE)
    if "phone" in changes:
        changes["phone"] = normalise_et_phone(changes["phone"])
    for key, value in changes.items():
        setattr(customer, key, value)
    db.flush()
    return CustomerOut.model_validate(customer)


@router.get("/customers/{customer_id}/history")
def customer_history(customer_id: uuid.UUID, ctx: Ctx, db: DbSession) -> dict:
    """Purchases, credit balances and follow-up for one customer (PRD 12)."""
    ctx.require(Permission.CUSTOMER_VIEW)
    customer = get_tenant_object(db, Customer, customer_id, ctx.tenant_id, label="Customer")
    allowed = ctx.visible_branch_ids(db)

    sales = db.execute(
        tenant_query(Sale, ctx.tenant_id)
        .where(
            Sale.customer_id == customer.id,
            Sale.status == SaleStatus.COMPLETED,
            Sale.branch_id.in_(allowed),
        )
        .order_by(Sale.sold_at.desc())
        .limit(50)
    ).scalars().all() if ctx.has(Permission.SALE_VIEW) else []

    credits = []
    if ctx.has(Permission.CREDIT_VIEW):
        from app.api.v1.serializers import credit_out

        rows = db.execute(
            tenant_query(CreditTransaction, ctx.tenant_id)
            .where(
                CreditTransaction.customer_id == customer.id,
                CreditTransaction.kind == CreditKind.RECEIVABLE,
            )
            .order_by(CreditTransaction.issued_on.desc())
        ).scalars()
        credits = [credit_out(t, counterparty_name=customer.name).model_dump(mode="json") for t in rows]

    return {
        "customer": CustomerOut.model_validate(customer).model_dump(mode="json"),
        "outstanding_balance": (
            str(_outstanding(db, ctx.tenant_id, customer_id=customer.id))
            if ctx.has(Permission.CREDIT_VIEW)
            else None
        ),
        "sales": [
            {
                "id": str(sale.id),
                "number": sale.number,
                "sold_at": sale.sold_at.isoformat(),
                "total_amount": str(sale.total_amount),
                "balance_due": str(sale.balance_due),
            }
            for sale in sales
        ],
        "credit_transactions": credits,
    }


@router.get("/suppliers", response_model=Page[SupplierOut])
def list_suppliers(
    ctx: Ctx,
    db: DbSession,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[SupplierOut]:
    ctx.require(Permission.SUPPLIER_VIEW)
    stmt = tenant_query(Supplier, ctx.tenant_id).where(Supplier.is_active.is_(True))
    if q:
        pattern = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Supplier.name).like(pattern),
                func.lower(Supplier.phone).like(pattern),
            )
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Supplier.name).limit(limit).offset(offset)).scalars().all()

    items = []
    for supplier in rows:
        payload = SupplierOut.model_validate(supplier)
        if ctx.has(Permission.CREDIT_VIEW, Permission.PURCHASE_VIEW):
            payload.outstanding_balance = _outstanding(
                db, ctx.tenant_id, supplier_id=supplier.id
            )
        items.append(payload)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/suppliers", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
def add_supplier(payload: SupplierIn, ctx: WritableCtx, db: DbSession) -> SupplierOut:
    ctx.require(Permission.SUPPLIER_MANAGE)
    data = payload.model_dump()
    data["phone"] = normalise_et_phone(data.get("phone"))
    supplier = Supplier(tenant_id=ctx.tenant_id, **data)
    db.add(supplier)
    db.flush()
    return SupplierOut.model_validate(supplier)


@router.get("/suppliers/{supplier_id}", response_model=SupplierOut)
def get_supplier(supplier_id: uuid.UUID, ctx: Ctx, db: DbSession) -> SupplierOut:
    ctx.require(Permission.SUPPLIER_VIEW)
    supplier = get_tenant_object(db, Supplier, supplier_id, ctx.tenant_id, label="Supplier")
    payload = SupplierOut.model_validate(supplier)
    if ctx.has(Permission.CREDIT_VIEW, Permission.PURCHASE_VIEW):
        payload.outstanding_balance = _outstanding(
            db, ctx.tenant_id, supplier_id=supplier.id
        )
    return payload


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def edit_supplier(
    supplier_id: uuid.UUID, payload: SupplierIn, ctx: WritableCtx, db: DbSession
) -> SupplierOut:
    ctx.require(Permission.SUPPLIER_MANAGE)
    supplier = get_tenant_object(db, Supplier, supplier_id, ctx.tenant_id, label="Supplier")
    changes = payload.model_dump(exclude_unset=True)
    if "phone" in changes:
        changes["phone"] = normalise_et_phone(changes["phone"])
    for key, value in changes.items():
        setattr(supplier, key, value)
    db.flush()
    return SupplierOut.model_validate(supplier)
