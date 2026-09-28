"""Unauthenticated storefront and proforma share links (PRD 13, 14).

Nothing here reads across tenants: every lookup starts from a published store
slug, an unguessable share token, or the unguessable id of a public file.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.deps import DbSession, client_ip, limit_public_requests
from app.core.errors import NotFoundError
from app.models.commerce import QuotationStatus
from app.models.platform import Tenant
from app.models.system import FileAsset
from app.schemas.operations import EnquiryIn, EnquiryOut, ProformaRequestIn
from app.services.commerce import (
    BasketItem,
    get_public_product,
    get_public_store,
    get_quotation_by_token,
    list_public_products,
    public_categories,
    quotation_status_for,
    request_quotation,
    respond_to_quotation,
    share_links,
    store_for_tenant,
    submit_enquiry,
)
from app.services.storage import get_storage

router = APIRouter(prefix="/public", tags=["public storefront"])


@router.get("/shops/{slug}")
def shop(slug: str, db: DbSession) -> dict:
    store, tenant = get_public_store(db, slug)
    return {
        "slug": store.slug,
        "display_name": store.display_name,
        "tagline": store.tagline,
        "about": store.about,
        "contact_phone": store.contact_phone,
        "contact_email": store.contact_email,
        "telegram_username": store.telegram_username,
        "address": store.address,
        "currency": tenant.currency,
        "show_prices": store.show_prices,
        "checkout_note": store.checkout_note,
        "categories": public_categories(db, store),
    }


@router.get("/shops/{slug}/products")
def shop_products(
    slug: str,
    db: DbSession,
    q: str | None = None,
    category: str | None = None,
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    """Published products with live availability from the shared stock source."""
    store, tenant = get_public_store(db, slug)
    products, total = list_public_products(
        db, store, tenant, query=q, category=category, limit=limit, offset=offset
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "currency": tenant.currency,
        "items": [product.as_dict() for product in products],
    }


@router.get("/shops/{slug}/products/{product_id}")
def shop_product(slug: str, product_id: uuid.UUID, db: DbSession) -> dict:
    """One product, for its own page and shareable link (PRD 13)."""
    store, tenant = get_public_store(db, slug)
    payload = get_public_product(db, store, tenant, product_id).as_dict()
    payload["currency"] = tenant.currency
    return payload


@router.post(
    "/shops/{slug}/enquiries",
    response_model=EnquiryOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_public_requests)],
)
def enquire(slug: str, payload: EnquiryIn, db: DbSession, request: Request) -> EnquiryOut:
    """Ask a question.  No stock is reserved (PRD 13)."""
    store, _ = get_public_store(db, slug)
    enquiry = submit_enquiry(
        db,
        store,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        contact_email=payload.contact_email,
        company=payload.company,
        delivery_location=payload.delivery_location,
        message=payload.message,
        items=[item.model_dump(mode="json") for item in payload.items],
        wants_proforma=payload.wants_proforma,
        source_ip=client_ip(request),
    )
    return EnquiryOut.model_validate(enquiry)


@router.post(
    "/shops/{slug}/proforma-requests",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_public_requests)],
)
def request_proforma(slug: str, payload: ProformaRequestIn, db: DbSession) -> dict:
    """Turn a visitor's basket into a numbered proforma request (PRD 13, 14).

    The seller reviews and sends it; nothing is reserved or deducted.
    """
    store, tenant = get_public_store(db, slug)
    quotation = request_quotation(
        db,
        store,
        tenant,
        items=[BasketItem(item.variant_id, item.quantity) for item in payload.items],
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        contact_email=payload.contact_email,
        company=payload.company,
        delivery_location=payload.delivery_location,
        message=payload.message,
    )
    return {
        "number": quotation.number,
        "status": str(quotation.status),
        "token": quotation.share_token,
        "url": share_links(quotation)["url"],
        "item_count": len(quotation.lines),
        "total_amount": str(quotation.total_amount) if store.show_prices else None,
        "currency": quotation.currency,
        "message": (
            f"Thank you. {store.display_name} will confirm prices and delivery, and your "
            f"proforma {quotation.number} will appear at your link."
        ),
    }


_NEXT_STEP = {
    QuotationStatus.REQUESTED: (
        "The seller is reviewing your request and will send the priced proforma here."
    ),
    QuotationStatus.DRAFT: "Accept below to confirm your order.",
    QuotationStatus.SENT: (
        "Accept below to confirm your order. Nothing is reserved until the seller confirms."
    ),
    QuotationStatus.ACCEPTED: (
        "You accepted this proforma. The seller will contact you about delivery and payment."
    ),
    QuotationStatus.DECLINED: "You declined this proforma.",
    QuotationStatus.EXPIRED: "This proforma has expired. Ask the seller for a new one.",
    QuotationStatus.CONVERTED: "This order has been completed by the seller.",
}


@router.get("/quotations/{token}")
def view_quotation(token: str, db: DbSession) -> dict:
    """A customer's view of a shared proforma, and their order tracking page."""
    quotation = get_quotation_by_token(db, token)
    tenant = db.get(Tenant, quotation.tenant_id)
    store = store_for_tenant(db, quotation.tenant_id)
    status_now = quotation_status_for(quotation)
    # A request the seller has not priced yet shows amounts only where the shop
    # shows prices to visitors anyway.
    amounts_visible = status_now != QuotationStatus.REQUESTED or bool(
        store and store.show_prices
    )

    def money(value) -> str | None:
        return str(value) if amounts_visible else None

    return {
        "number": quotation.number,
        "status": str(status_now),
        "next_step": _NEXT_STEP.get(status_now, ""),
        "can_respond": status_now in (QuotationStatus.SENT, QuotationStatus.DRAFT),
        "amounts_visible": amounts_visible,
        "issued_on": quotation.issued_on.isoformat(),
        "valid_until": quotation.valid_until.isoformat() if quotation.valid_until else None,
        "seller": {
            "name": tenant.name if tenant else None,
            "phone": tenant.phone if tenant else None,
            "address": tenant.address if tenant else None,
            "tin": tenant.tin if tenant else None,
        },
        "shop": (
            {
                "slug": store.slug,
                "display_name": store.display_name,
                "contact_phone": store.contact_phone,
                "contact_email": store.contact_email,
                "telegram_username": store.telegram_username,
            }
            if store
            else None
        ),
        "customer": {
            "name": quotation.customer_name,
            "phone": quotation.customer_phone,
            "company": quotation.customer_company,
            "delivery_location": quotation.delivery_location,
        },
        "customer_message": quotation.customer_message,
        "currency": quotation.currency,
        "subtotal": money(quotation.subtotal),
        "discount_total": money(quotation.discount_total),
        "tax_total": money(quotation.tax_total),
        "delivery_charge": money(quotation.delivery_charge),
        "total_amount": money(quotation.total_amount),
        "terms": quotation.terms,
        "note": quotation.note,
        "lines": [
            {
                "description": line.description,
                "quantity": str(line.quantity),
                "unit_price": money(line.unit_price),
                "discount_amount": money(line.discount_amount),
                "tax_amount": money(line.tax_amount),
                "line_total": money(line.line_total),
            }
            for line in quotation.lines
        ],
        "disclaimer": (
            "This is a proforma invoice. It is not a receipt and no payment has "
            "been recorded against it."
        ),
    }


@router.post("/quotations/{token}/respond", dependencies=[Depends(limit_public_requests)])
def respond(token: str, db: DbSession, accept: bool = True) -> dict:
    """Accept or decline.  Acceptance records intent; it posts no sale (PRD 14)."""
    quotation = respond_to_quotation(db, token, accept=accept)
    return {
        "number": quotation.number,
        "status": str(quotation.status),
        "message": (
            "Thank you. The seller has been notified and will confirm your order."
            if accept
            else "Thank you for letting the seller know."
        ),
    }


@router.get("/files/{asset_id}")
def public_file(asset_id: uuid.UUID, db: DbSession) -> Response:
    """A public asset such as a product photo.  Only assets flagged public are served."""
    asset = db.get(FileAsset, asset_id)
    if asset is None or not asset.is_public:
        raise NotFoundError("File not found")
    storage = get_storage()
    direct = storage.url_for(asset.storage_key)
    if direct:
        return RedirectResponse(direct, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return Response(
        content=storage.load(asset.storage_key),
        media_type=asset.content_type,
        headers={
            # Every upload gets a new id, so a file never changes behind its URL.
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Disposition": f'inline; filename="{asset.filename}"',
        },
    )
