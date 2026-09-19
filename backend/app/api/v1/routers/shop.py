"""Online shop administration and proformas (PRD 13, 14)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.api.v1.serializers import quotation_out, sale_out
from app.core.config import settings
from app.core.db import utcnow
from app.core.deps import Ctx, DbSession, WritableCtx
from app.core.permissions import Permission
from app.core.tenancy import get_tenant_object, tenant_query
from app.models.commerce import (
    CustomerEnquiry,
    EnquiryStatus,
    OnlineStore,
    Quotation,
)
from app.schemas.common import Page
from app.schemas.operations import (
    ConvertQuotationIn,
    EnquiryOut,
    QuotationIn,
    QuotationOut,
    SaleOut,
    StoreOut,
    StoreSettingsIn,
)
from app.services.commerce import (
    QuotationInput,
    QuotationLineInput,
    convert_to_sale,
    create_quotation,
    send_quotation,
)
from app.services.sales import PaymentInput

router = APIRouter(prefix="/shop", tags=["online shop"])


def _store(db, ctx) -> OnlineStore:
    store = db.execute(tenant_query(OnlineStore, ctx.tenant_id)).scalars().first()
    if store is None:
        from app.services.onboarding import slugify, unique_slug

        store = OnlineStore(
            tenant_id=ctx.tenant_id,
            slug=unique_slug(db, OnlineStore, OnlineStore.slug, slugify(ctx.tenant.name)),
            display_name=ctx.tenant.name,
            contact_phone=ctx.tenant.phone,
            contact_email=ctx.tenant.email,
        )
        db.add(store)
        db.flush()
    return store


def _store_out(store: OnlineStore) -> StoreOut:
    payload = StoreOut.model_validate(store)
    payload.public_url = f"{settings.public_base_url}/shop/{store.slug}"
    return payload


@router.get("/settings", response_model=StoreOut)
def get_store(ctx: Ctx, db: DbSession) -> StoreOut:
    ctx.require(Permission.SHOP_VIEW)
    return _store_out(_store(db, ctx))


@router.patch("/settings", response_model=StoreOut)
def update_store(payload: StoreSettingsIn, ctx: WritableCtx, db: DbSession) -> StoreOut:
    ctx.require(Permission.SHOP_MANAGE)
    store = _store(db, ctx)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(store, key, value)
    db.flush()
    return _store_out(store)


@router.get("/enquiries", response_model=Page[EnquiryOut])
def list_enquiries(
    ctx: Ctx,
    db: DbSession,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[EnquiryOut]:
    ctx.require(Permission.ENQUIRY_VIEW)
    stmt = tenant_query(CustomerEnquiry, ctx.tenant_id)
    if status_filter:
        stmt = stmt.where(CustomerEnquiry.status == status_filter)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(CustomerEnquiry.created_at.desc()).limit(limit).offset(offset)
    ).scalars()
    return Page(
        items=[EnquiryOut.model_validate(e) for e in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/enquiries/{enquiry_id}", response_model=EnquiryOut)
def get_enquiry(enquiry_id: uuid.UUID, ctx: Ctx, db: DbSession) -> EnquiryOut:
    ctx.require(Permission.ENQUIRY_VIEW)
    enquiry = get_tenant_object(
        db, CustomerEnquiry, enquiry_id, ctx.tenant_id, label="Enquiry"
    )
    return EnquiryOut.model_validate(enquiry)


@router.patch("/enquiries/{enquiry_id}", response_model=EnquiryOut)
def update_enquiry(
    enquiry_id: uuid.UUID,
    ctx: WritableCtx,
    db: DbSession,
    status_value: EnquiryStatus = Query(alias="status"),
) -> EnquiryOut:
    ctx.require(Permission.ENQUIRY_MANAGE)
    enquiry = get_tenant_object(
        db, CustomerEnquiry, enquiry_id, ctx.tenant_id, label="Enquiry"
    )
    enquiry.status = status_value
    enquiry.handled_by_id = ctx.user_id
    enquiry.handled_at = utcnow()
    db.flush()
    return EnquiryOut.model_validate(enquiry)


# --------------------------------------------------------------------------- #
# Quotations / proformas
# --------------------------------------------------------------------------- #


@router.get("/quotations", response_model=Page[QuotationOut])
def list_quotations(
    ctx: Ctx,
    db: DbSession,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[QuotationOut]:
    ctx.require(Permission.QUOTATION_VIEW)
    stmt = tenant_query(Quotation, ctx.tenant_id)
    if status_filter:
        stmt = stmt.where(Quotation.status == status_filter)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(Quotation.created_at.desc()).limit(limit).offset(offset)
    ).scalars()
    return Page(
        items=[quotation_out(q) for q in rows], total=total, limit=limit, offset=offset
    )


@router.post("/quotations", response_model=QuotationOut, status_code=status.HTTP_201_CREATED)
def new_quotation(payload: QuotationIn, ctx: WritableCtx, db: DbSession) -> QuotationOut:
    """Create a proforma.  This is not a sale and deducts no stock (PRD 14)."""
    quotation = create_quotation(
        db,
        ctx,
        QuotationInput(
            customer_name=payload.customer_name,
            lines=[
                QuotationLineInput(
                    variant_id=line.variant_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    discount_amount=line.discount_amount,
                    tax_rate=line.tax_rate,
                )
                for line in payload.lines
            ],
            customer_id=payload.customer_id,
            customer_phone=payload.customer_phone,
            customer_email=payload.customer_email,
            customer_company=payload.customer_company,
            delivery_location=payload.delivery_location,
            delivery_charge=payload.delivery_charge,
            branch_id=payload.branch_id,
            enquiry_id=payload.enquiry_id,
            valid_until=payload.valid_until,
            validity_days=payload.validity_days,
            terms=payload.terms,
            note=payload.note,
        ),
    )
    return quotation_out(quotation)


@router.get("/quotations/{quotation_id}", response_model=QuotationOut)
def get_quotation(quotation_id: uuid.UUID, ctx: Ctx, db: DbSession) -> QuotationOut:
    ctx.require(Permission.QUOTATION_VIEW)
    quotation = get_tenant_object(
        db, Quotation, quotation_id, ctx.tenant_id, label="Proforma"
    )
    return quotation_out(quotation)


@router.post("/quotations/{quotation_id}/send", response_model=QuotationOut)
def send(quotation_id: uuid.UUID, ctx: WritableCtx, db: DbSession) -> QuotationOut:
    """Mark as sent and return the share link, Telegram and email options."""
    return quotation_out(send_quotation(db, ctx, quotation_id))


@router.post("/quotations/{quotation_id}/convert", response_model=SaleOut)
def convert(
    quotation_id: uuid.UUID, payload: ConvertQuotationIn, ctx: WritableCtx, db: DbSession
) -> SaleOut:
    """The explicit step that posts the sale and deducts stock (PRD 14)."""
    result = convert_to_sale(
        db,
        ctx,
        quotation_id,
        branch_id=payload.branch_id,
        location_id=payload.location_id,
        payments=[
            PaymentInput(method=p.method, amount=p.amount, reference=p.reference)
            for p in payload.payments
        ],
        due_date=payload.due_date,
    )
    return sale_out(ctx, result.sale)
