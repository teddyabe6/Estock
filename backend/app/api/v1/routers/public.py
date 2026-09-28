"""Unauthenticated storefront, marketplace, checkout and share links (PRD 13, 14).

Nothing here reads across tenants except the marketplace listing, which shows
only what every shop has already published.  Every other lookup starts from a
published shop slug, an unguessable token, or the unguessable id of a file
flagged public.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.deps import DbSession, client_ip, limit_public_requests
from app.core.errors import NotFoundError, PermissionDenied
from app.models.commerce import Order, OrderStatus, Quotation, QuotationStatus
from app.models.platform import Tenant
from app.models.system import FileAsset
from app.schemas.operations import (
    CancelOrderIn,
    EnquiryIn,
    EnquiryOut,
    OrderCheckoutIn,
    ProformaCheckoutIn,
    ProformaRequestIn,
)
from app.services.checkout import (
    CheckoutContact,
    CheckoutItem,
    cancel_order_by_customer,
    get_batch,
    order_next_step,
    place_orders,
    request_proformas,
    tracking_url,
)
from app.services.commerce import (
    BasketItem,
    get_public_product,
    get_public_store,
    get_quotation_by_token,
    list_market_products,
    list_market_shops,
    list_public_products,
    market_categories,
    public_categories,
    quotation_next_step,
    quotation_status_for,
    request_quotation,
    respond_to_quotation,
    share_links,
    store_for_tenant,
    submit_enquiry,
)
from app.services.messaging import process_telegram_update, store_and_tenant
from app.services.storage import get_storage

router = APIRouter(prefix="/public", tags=["public storefront"])


# --------------------------------------------------------------------------- #
# The marketplace: every open shop
# --------------------------------------------------------------------------- #


@router.get("/market")
def market(db: DbSession) -> dict:
    """The shops that are open and the categories across them."""
    return {
        "shops": list_market_shops(db),
        "categories": market_categories(db),
        "currency": settings.default_currency,
    }


@router.get("/market/products")
def market_products(
    db: DbSession,
    q: str | None = None,
    category: str | None = None,
    shop: str | None = None,
    min_price: Decimal | None = Query(None, ge=0),
    max_price: Decimal | None = Query(None, ge=0),
    in_stock: bool = False,
    sort: str = "name",
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    """Published products across shops, filterable by shop, category and price."""
    items, total = list_market_products(
        db,
        query=q,
        category=category,
        shop=shop,
        min_price=min_price,
        max_price=max_price,
        in_stock_only=in_stock,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "currency": settings.default_currency,
        "items": items,
    }


# --------------------------------------------------------------------------- #
# One shop
# --------------------------------------------------------------------------- #


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
        "accepts_orders": store.accepts_orders,
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
    shop_info = {
        "slug": store.slug,
        "display_name": store.display_name,
        "accepts_orders": store.accepts_orders,
        "show_prices": store.show_prices,
    }
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "currency": tenant.currency,
        "items": [{**product.as_dict(), "shop": shop_info} for product in products],
    }


@router.get("/shops/{slug}/products/{product_id}")
def shop_product(slug: str, product_id: uuid.UUID, db: DbSession) -> dict:
    """One product, for its own page and shareable link (PRD 13)."""
    store, tenant = get_public_store(db, slug)
    payload = get_public_product(db, store, tenant, product_id).as_dict()
    payload["currency"] = tenant.currency
    payload["shop"] = {
        "slug": store.slug,
        "display_name": store.display_name,
        "accepts_orders": store.accepts_orders,
        "show_prices": store.show_prices,
    }
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
    """A basket from one shop, requested as a proforma (PRD 13, 14)."""
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


# --------------------------------------------------------------------------- #
# Checkout across shops
# --------------------------------------------------------------------------- #


def _contact(payload) -> CheckoutContact:
    return CheckoutContact(
        name=payload.contact_name,
        phone=payload.contact_phone,
        email=payload.contact_email,
        company=payload.company,
        delivery_location=payload.delivery_location,
        message=payload.message,
    )


def _items(payload) -> list[CheckoutItem]:
    return [
        CheckoutItem(shop=item.shop, variant_id=item.variant_id, quantity=item.quantity)
        for item in payload.items
    ]


@router.post(
    "/checkout/orders",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_public_requests)],
)
def checkout_orders(payload: OrderCheckoutIn, db: DbSession, request: Request) -> dict:
    """Place one order per shop.  No payment is taken and no stock is reserved."""
    result = place_orders(
        db,
        items=_items(payload),
        contact=_contact(payload),
        delivery_method=payload.delivery_method,
        payment_method=payload.payment_method.value,
        source_ip=client_ip(request),
    )
    return {
        "token": result.batch.token,
        "url": result.tracking_url,
        "kind": "order",
        "parts": [
            {
                "kind": "order",
                "shop": _shop_of(db, order.tenant_id),
                "number": order.number,
                "status": str(order.status),
                "total_amount": str(order.total_amount),
                "currency": order.currency,
            }
            for order in result.orders
        ],
        "message": (
            f"Thank you. {len(result.orders)} shop(s) have your order and will confirm it. "
            "Keep your tracking link."
        ),
    }


@router.post(
    "/checkout/proforma-requests",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_public_requests)],
)
def checkout_proformas(payload: ProformaCheckoutIn, db: DbSession, request: Request) -> dict:
    """Send each chosen shop a proforma request for its own items."""
    result = request_proformas(
        db, items=_items(payload), contact=_contact(payload), source_ip=client_ip(request)
    )
    return {
        "token": result.batch.token,
        "url": result.tracking_url,
        "kind": "proforma",
        "parts": [
            {
                "kind": "proforma",
                "shop": _shop_of(db, quotation.tenant_id),
                "number": quotation.number,
                "status": str(quotation.status),
                "url": share_links(quotation)["url"],
                "currency": quotation.currency,
            }
            for quotation in result.quotations
        ],
        "message": (
            f"Thank you. {len(result.quotations)} shop(s) have your request; each will send "
            "its own proforma. Keep your tracking link."
        ),
    }


def _shop_of(db: DbSession, tenant_id: uuid.UUID) -> dict | None:
    found = store_and_tenant(db, tenant_id)
    if found is None:
        return None
    store, _tenant = found
    return {
        "slug": store.slug,
        "display_name": store.display_name,
        "contact_phone": store.contact_phone,
        "contact_email": store.contact_email,
        "telegram_username": store.telegram_username,
    }


def _order_part(db: DbSession, order: Order) -> dict:
    return {
        "kind": "order",
        "shop": _shop_of(db, order.tenant_id),
        "number": order.number,
        "status": str(order.status),
        "next_step": order_next_step(order),
        "can_cancel": order.status == OrderStatus.PLACED,
        "token": order.share_token,
        "payment_method": order.payment_method,
        "delivery_method": str(order.delivery_method),
        "delivery_location": order.delivery_location,
        "seller_note": order.seller_note,
        "currency": order.currency,
        "subtotal": str(order.subtotal),
        "tax_total": str(order.tax_total),
        "delivery_charge": str(order.delivery_charge),
        "total_amount": str(order.total_amount),
        "lines": [
            {
                "description": line.description,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "line_total": str(line.line_total),
            }
            for line in order.lines
        ],
    }


def _proforma_part(db: DbSession, quotation: Quotation) -> dict:
    status_now = quotation_status_for(quotation)
    found = store_and_tenant(db, quotation.tenant_id)
    visible = status_now != QuotationStatus.REQUESTED or bool(found and found[0].show_prices)
    return {
        "kind": "proforma",
        "shop": _shop_of(db, quotation.tenant_id),
        "number": quotation.number,
        "status": str(status_now),
        "next_step": quotation_next_step(status_now),
        "url": share_links(quotation)["url"],
        "currency": quotation.currency,
        "amounts_visible": visible,
        "total_amount": str(quotation.total_amount) if visible else None,
        "lines": [
            {
                "description": line.description,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price) if visible else None,
                "line_total": str(line.line_total) if visible else None,
            }
            for line in quotation.lines
        ],
    }


@router.get("/checkout/{token}")
def track_checkout(token: str, db: DbSession) -> dict:
    """The customer's tracking page: every shop's part of one checkout."""
    batch, orders, quotations = get_batch(db, token)
    return {
        "token": batch.token,
        "kind": str(batch.kind),
        "created_at": batch.created_at.isoformat(),
        "customer": {
            "name": batch.customer_name,
            "phone": batch.customer_phone,
            "company": batch.company,
            "delivery_location": batch.delivery_location,
            "message": batch.message,
        },
        "parts": [_order_part(db, order) for order in orders]
        + [_proforma_part(db, quotation) for quotation in quotations],
    }


@router.post("/orders/{token}/cancel", dependencies=[Depends(limit_public_requests)])
def cancel_order(token: str, payload: CancelOrderIn, db: DbSession) -> dict:
    """A buyer withdraws an order the shop has not confirmed yet."""
    order = cancel_order_by_customer(db, token, reason=payload.reason)
    return {
        "number": order.number,
        "status": str(order.status),
        "message": "Your order was cancelled and the shop has been told.",
    }


# --------------------------------------------------------------------------- #
# Proforma share links
# --------------------------------------------------------------------------- #


@router.get("/quotations/{token}")
def view_quotation(token: str, db: DbSession) -> dict:
    """A customer's view of a shared proforma, and their tracking page for it."""
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

    tracking = None
    if quotation.batch_id is not None:
        from app.models.commerce import CheckoutBatch

        batch = db.get(CheckoutBatch, quotation.batch_id)
        tracking = tracking_url(batch.token) if batch else None

    return {
        "number": quotation.number,
        "status": str(status_now),
        "next_step": quotation_next_step(status_now),
        "can_respond": status_now in (QuotationStatus.SENT, QuotationStatus.DRAFT),
        "amounts_visible": amounts_visible,
        "tracking_url": tracking,
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


# --------------------------------------------------------------------------- #
# Files and integrations
# --------------------------------------------------------------------------- #


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


@router.post("/telegram/webhook")
def telegram_webhook(
    update: dict,
    db: DbSession,
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> dict:
    """Telegram delivers bot updates here when a webhook is configured."""
    if not settings.telegram_webhook_secret:
        raise NotFoundError("Not found")
    if secret != settings.telegram_webhook_secret:
        raise PermissionDenied("Bad webhook secret")
    store = process_telegram_update(db, update)
    return {"ok": True, "linked": store is not None}
