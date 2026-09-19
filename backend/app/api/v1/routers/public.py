"""Unauthenticated storefront and proforma share links (PRD 13, 14).

Nothing here reads across tenants: every lookup starts from a published store
slug or an unguessable share token.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, status

from app.core.deps import DbSession, client_ip
from app.schemas.operations import EnquiryIn, EnquiryOut
from app.services.commerce import (
    get_public_store,
    get_quotation_by_token,
    list_public_products,
    quotation_status_for,
    respond_to_quotation,
    submit_enquiry,
)

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
    }


@router.get("/shops/{slug}/products")
def shop_products(
    slug: str,
    db: DbSession,
    q: str | None = None,
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    """Published products with live availability from the shared stock source."""
    store, tenant = get_public_store(db, slug)
    products, total = list_public_products(
        db, store, tenant, query=q, limit=limit, offset=offset
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "currency": tenant.currency,
        "items": [
            {
                "id": str(product.id),
                "name": product.name,
                "description": product.description,
                "brand": product.brand,
                "category": product.category,
                "unit_of_measure": product.unit_of_measure,
                "price": str(product.price) if product.price is not None else None,
                "in_stock": product.in_stock,
                "variants": product.variants,
            }
            for product in products
        ],
    }


@router.post("/shops/{slug}/enquiries", response_model=EnquiryOut, status_code=status.HTTP_201_CREATED)
def enquire(slug: str, payload: EnquiryIn, db: DbSession, request: Request) -> EnquiryOut:
    """Submit an enquiry or proforma request.  No stock is reserved (PRD 13)."""
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


@router.get("/quotations/{token}")
def view_quotation(token: str, db: DbSession) -> dict:
    """A customer's view of a shared proforma."""
    quotation = get_quotation_by_token(db, token)
    from app.models.platform import Tenant

    tenant = db.get(Tenant, quotation.tenant_id)
    return {
        "number": quotation.number,
        "status": str(quotation_status_for(quotation)),
        "issued_on": quotation.issued_on.isoformat(),
        "valid_until": quotation.valid_until.isoformat() if quotation.valid_until else None,
        "seller": {
            "name": tenant.name if tenant else None,
            "phone": tenant.phone if tenant else None,
            "address": tenant.address if tenant else None,
            "tin": tenant.tin if tenant else None,
        },
        "customer": {
            "name": quotation.customer_name,
            "phone": quotation.customer_phone,
            "company": quotation.customer_company,
            "delivery_location": quotation.delivery_location,
        },
        "currency": quotation.currency,
        "subtotal": str(quotation.subtotal),
        "discount_total": str(quotation.discount_total),
        "tax_total": str(quotation.tax_total),
        "delivery_charge": str(quotation.delivery_charge),
        "total_amount": str(quotation.total_amount),
        "terms": quotation.terms,
        "note": quotation.note,
        "lines": [
            {
                "description": line.description,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "discount_amount": str(line.discount_amount),
                "tax_amount": str(line.tax_amount),
                "line_total": str(line.line_total),
            }
            for line in quotation.lines
        ],
        "disclaimer": (
            "This is a proforma invoice. It is not a receipt and no payment has "
            "been recorded against it."
        ),
    }


@router.post("/quotations/{token}/respond")
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
