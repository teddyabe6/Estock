"""Online shop administration and proformas (PRD 13, 14)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel
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
    PaymentSlip,
    Quotation,
    QuotationStatus,
)
from app.models.system import FileAsset
from app.schemas.common import Page
from app.schemas.operations import (
    CancelQuotationIn,
    ConvertQuotationIn,
    EnquiryOut,
    QuotationIn,
    QuotationOut,
    QuotationUpdateIn,
    SaleResponse,
    StoreOut,
    StoreSettingsIn,
)
from app.services.catalogue import list_published_on_marketplace
from app.services.commerce import (
    QuotationInput,
    QuotationLineInput,
    cancel_quotation,
    convert_to_sale,
    create_quotation,
    payment_slip_as_dict,
    review_payment_slip,
    send_quotation,
    update_quotation,
)
from app.services.sales import PaymentInput
from app.services.storage import get_storage

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
    if store.list_on_marketplace:
        payload.marketplace_url = f"{settings.public_base_url}/market?shop={store.slug}"
    return payload


@router.get("/settings", response_model=StoreOut)
def get_store(ctx: Ctx, db: DbSession) -> StoreOut:
    ctx.require(Permission.SHOP_VIEW)
    return _store_out(_store(db, ctx))


@router.patch("/settings", response_model=StoreOut)
def update_store(payload: StoreSettingsIn, ctx: WritableCtx, db: DbSession) -> StoreOut:
    ctx.require(Permission.SHOP_MANAGE)
    store = _store(db, ctx)
    changes = payload.model_dump(exclude_unset=True)
    # Joining the marketplace with a catalogue already published, and finding
    # nothing of yours listed, is the trap two separate flags set. Switching
    # the shop on brings what it already publishes with it; leaving does not
    # take anything off, because the shop's own switch already hides it all
    # and the products' own choice is waiting if it comes back.
    joining = bool(changes.get("list_on_marketplace")) and not store.list_on_marketplace
    for key, value in changes.items():
        setattr(store, key, value)
    if joining:
        list_published_on_marketplace(db, ctx)
    db.flush()
    return _store_out(store)


@router.get("/summary")
def shop_summary(ctx: Ctx, db: DbSession) -> dict:
    """What is waiting for the seller: basket requests and unanswered enquiries."""
    ctx.require(Permission.SHOP_VIEW)

    def count(stmt) -> int:
        return db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    return {
        "proforma_requests": count(
            tenant_query(Quotation, ctx.tenant_id).where(
                Quotation.status == QuotationStatus.REQUESTED
            )
        ),
        "new_enquiries": count(
            tenant_query(CustomerEnquiry, ctx.tenant_id).where(
                CustomerEnquiry.status == EnquiryStatus.NEW
            )
        ),
    }


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
        items=[_enquiry_out(e) for e in rows],
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
    return _enquiry_out(enquiry)


def _enquiry_out(enquiry: CustomerEnquiry) -> EnquiryOut:
    import json

    payload = EnquiryOut.model_validate(enquiry)
    payload.items = json.loads(enquiry.requested_items_json or "[]")
    return payload


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
    return _enquiry_out(enquiry)


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


@router.patch("/quotations/{quotation_id}", response_model=QuotationOut)
def edit_quotation(
    quotation_id: uuid.UUID, payload: QuotationUpdateIn, ctx: WritableCtx, db: DbSession
) -> QuotationOut:
    """Review a request or draft: change lines, prices, delivery and terms."""
    changes = payload.model_dump(exclude_unset=True)
    changes.pop("lines", None)
    quotation = update_quotation(
        db,
        ctx,
        quotation_id,
        lines=(
            [
                QuotationLineInput(
                    variant_id=line.variant_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    discount_amount=line.discount_amount,
                    tax_rate=line.tax_rate,
                )
                for line in payload.lines
            ]
            if payload.lines is not None
            else None
        ),
        delivery_charge=changes.pop("delivery_charge", None),
        valid_until=changes.pop("valid_until", None),
        validity_days=changes.pop("validity_days", None),
        fields=changes,
    )
    return quotation_out(quotation)


@router.post("/quotations/{quotation_id}/cancel", response_model=QuotationOut)
def cancel(
    quotation_id: uuid.UUID, payload: CancelQuotationIn, ctx: WritableCtx, db: DbSession
) -> QuotationOut:
    """Withdraw a proforma; its share link stops working."""
    return quotation_out(cancel_quotation(db, ctx, quotation_id, reason=payload.reason))


@router.post("/quotations/{quotation_id}/send", response_model=QuotationOut)
def send(quotation_id: uuid.UUID, ctx: WritableCtx, db: DbSession) -> QuotationOut:
    """Mark as sent and return the share link, Telegram and email options."""
    return quotation_out(send_quotation(db, ctx, quotation_id))


@router.post("/quotations/{quotation_id}/convert", response_model=SaleResponse)
def convert(
    quotation_id: uuid.UUID, payload: ConvertQuotationIn, ctx: WritableCtx, db: DbSession
) -> SaleResponse:
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
    return SaleResponse(
        sale=sale_out(ctx, result.sale),
        credit_transaction_id=(
            result.credit_transaction.id if result.credit_transaction else None
        ),
        warnings=result.warnings,
    )


# --------------------------------------------------------------------------- #
# Proof of payment a buyer has sent
# --------------------------------------------------------------------------- #


@router.get("/quotations/{quotation_id}/payment-slips")
def list_payment_slips(quotation_id: uuid.UUID, ctx: Ctx, db: DbSession) -> dict:
    """What a buyer has sent to say they have paid this proforma."""
    ctx.require(Permission.QUOTATION_VIEW)
    quotation = get_tenant_object(
        db, Quotation, quotation_id, ctx.tenant_id, label="Proforma"
    )
    return {
        "items": [
            payment_slip_as_dict(slip, include_file=True)
            for slip in sorted(quotation.payment_slips, key=lambda s: s.created_at or utcnow())
        ]
    }


@router.get("/payment-slips/{slip_id}/file")
def payment_slip_file(slip_id: uuid.UUID, ctx: Ctx, db: DbSession) -> Response:
    """The slip itself.

    Served through the shop's own session rather than a public link: it is a
    stranger's banking document, and the only people with a reason to see it
    are the ones who can act on it.
    """
    ctx.require(Permission.QUOTATION_VIEW)
    slip = get_tenant_object(db, PaymentSlip, slip_id, ctx.tenant_id, label="Payment slip")
    asset = get_tenant_object(
        db, FileAsset, slip.file_asset_id, ctx.tenant_id, label="File"
    )
    storage = get_storage()
    return Response(
        content=storage.load(asset.storage_key),
        media_type=asset.content_type,
        headers={"Content-Disposition": f'inline; filename="{asset.filename}"'},
    )


class ReviewSlipIn(BaseModel):
    accept: bool
    note: str | None = None


@router.post("/payment-slips/{slip_id}/review")
def review_slip(
    slip_id: uuid.UUID, payload: ReviewSlipIn, ctx: WritableCtx, db: DbSession
) -> dict:
    """Record that you found the money, or that you did not.

    This does not post anything to your books. Take the payment against the
    sale in the usual way, so there stays one path by which money enters.
    """
    slip = review_payment_slip(
        db, ctx, slip_id, accept=payload.accept, note=payload.note
    )
    return payment_slip_as_dict(slip, include_file=True)
