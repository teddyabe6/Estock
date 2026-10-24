"""The central marketplace: every opted-in shop's catalogue, in one place.

No token.  These endpoints read across shops on purpose — the only place in
the system that does — through the narrow projection in
``app/services/marketplace.py``.  Nothing here can reach a cost, a customer, a
credit balance or a stock quantity.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status

from app.core.config import settings
from app.core.deps import DbSession, client_ip, limit_public_requests
from app.schemas.operations import MarketplaceRequestIn
from app.services import marketplace
from app.services.commerce import (
    MarketplaceBasketItem,
    get_marketplace_request,
    marketplace_request_state,
    submit_marketplace_request,
    withdraw_marketplace_request,
)

router = APIRouter(prefix="/market", tags=["marketplace"])


@router.get("/shops")
def list_shops(db: DbSession) -> dict:
    """Every shop on the marketplace, for browsing by vendor."""
    return {"shops": [shop.as_dict() for shop in marketplace.shops(db)]}


@router.get("/shops/{slug}")
def get_shop(slug: str, db: DbSession) -> dict:
    return marketplace.get_shop(db, slug).as_dict()


@router.get("/categories")
def list_categories(db: DbSession) -> dict:
    """Categories with at least one listed product, across every shop."""
    return {"categories": marketplace.categories(db)}


@router.get("/products")
def list_products(
    db: DbSession,
    q: str | None = None,
    category: str | None = None,
    shop: str | None = Query(default=None, description="A shop's slug"),
    limit: int = Query(30, ge=1, le=60),
    offset: int = Query(0, ge=0),
) -> dict:
    """Browse or search the whole marketplace."""
    products, total = marketplace.marketplace_products(
        db, query=q, category=category, shop_slug=shop, limit=limit, offset=offset
    )
    return {
        "items": [product.as_dict() for product in products],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/products/{product_id}")
def get_product(product_id: uuid.UUID, db: DbSession) -> dict:
    """One listed product, by a link that can be shared."""
    return marketplace.get_marketplace_product(db, product_id).as_dict()


@router.post(
    "/requests",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_public_requests)],
)
def submit_request(
    payload: MarketplaceRequestIn, db: DbSession, request: Request
) -> dict:
    """One basket spanning shops becomes one request each shop answers.

    The buyer gets their tracking link straight away.  Nothing is reserved and
    no stock moves; each shop reviews its own part and sends a price.
    """
    result = submit_marketplace_request(
        db,
        items=[
            MarketplaceBasketItem(item.variant_id, item.quantity) for item in payload.items
        ],
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        contact_email=payload.contact_email,
        company=payload.company,
        delivery_location=payload.delivery_location,
        message=payload.message,
        source_ip=client_ip(request),
    )
    return {
        "reference": result.request.reference,
        "token": result.request.share_token,
        "url": marketplace_request_url(result.request.share_token),
        "shop_count": len(result.quotations),
        "message": (
            f"Sent to {len(result.quotations)} shop(s). "
            "Keep this link to see their prices as they answer."
        ),
    }


@router.get("/requests/{token}")
def track_request(token: str, db: DbSession) -> dict:
    """The buyer's tracking page: one row per shop, and who has answered."""
    return marketplace_request_state(db, get_marketplace_request(db, token))


@router.post("/requests/{token}/withdraw", dependencies=[Depends(limit_public_requests)])
def withdraw_request(token: str, db: DbSession) -> dict:
    """The buyer changes their mind.

    Shops that have not answered yet have their proforma cancelled.  A
    proforma a shop has already priced and sent is left alone — the buyer
    declines that one on the shop's own proforma page.
    """
    request = withdraw_marketplace_request(db, token)
    return marketplace_request_state(db, request)


def marketplace_request_url(token: str) -> str:
    return f"{settings.public_base_url}/market/requests/{token}"
