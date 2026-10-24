"""The central marketplace: every shop's listed products, in one catalogue.

**This module contains the only cross-tenant read in the codebase.**

Everywhere else, a read goes through ``tenant_query(Model, tenant_id)``, which
cannot be called without a tenant id, so forgetting the filter is a visible
omission rather than a silent leak (``app/core/tenancy.py``).  A marketplace
has to cross that line on purpose: its whole job is to show a buyer products
from shops that know nothing of each other.

So the crossing is made once, here, in :func:`marketplace_products`, and it is
narrow by construction:

* It reads ``products``, ``product_variants``, ``categories``,
  ``online_stores`` and ``stock_balances`` and nothing else.  No customer, no
  credit, no sale, no purchase, no cost and no audit row is reachable from a
  marketplace request.
* It returns :class:`MarketplaceProduct`, a projection built field by field.
  Nothing hands back a model instance a caller could walk relationships from.
* Stock is reduced to a boolean.  A competitor should not be able to watch a
  rival's quantities by polling the marketplace, and a buyer only needs to
  know whether to ask.
* It lists only shops that opted in **and** can actually answer: a suspended
  shop, or one whose trial has lapsed into read-only, cannot respond to a
  request, so soliciting one would waste the buyer's time.

Anything that needs more than this projection belongs behind a shop's own
authenticated API, not here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.errors import NotFoundError
from app.models.catalogue import Category, Product, ProductVariant
from app.models.commerce import OnlineStore
from app.models.inventory import StockBalance
from app.models.platform import Tenant, TenantStatus
from app.services.storage import public_file_url

#: Shops in these states cannot post anything, so they cannot answer a
#: request.  Listing them would send buyers to a dead end.
UNAVAILABLE_STATUSES = (TenantStatus.SUSPENDED, TenantStatus.RESTRICTED)

MAX_PAGE = 60


@dataclass(slots=True)
class MarketplaceShop:
    """A shop as a buyer sees it: a name and a way to be contacted."""

    id: uuid.UUID
    slug: str
    name: str
    tagline: str | None
    address: str | None
    phone: str | None
    #: True when the shop also runs its own page, so we can link to it.
    has_own_page: bool

    def as_dict(self) -> dict:
        return {
            "id": str(self.id),
            "slug": self.slug,
            "name": self.name,
            "tagline": self.tagline,
            "address": self.address,
            "phone": self.phone,
            "has_own_page": self.has_own_page,
        }


@dataclass(slots=True)
class MarketplaceVariant:
    id: uuid.UUID
    name: str | None
    is_default: bool
    price: Decimal | None
    in_stock: bool

    def as_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "is_default": self.is_default,
            "price": str(self.price) if self.price is not None else None,
            "in_stock": self.in_stock,
        }


@dataclass(slots=True)
class MarketplaceProduct:
    """What a marketplace request may know about a product.  Nothing more."""

    id: uuid.UUID
    name: str
    description: str | None
    brand: str | None
    category: str | None
    unit_of_measure: str
    price: Decimal | None
    in_stock: bool
    image_url: str | None
    shop: MarketplaceShop
    variants: list[MarketplaceVariant] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "brand": self.brand,
            "category": self.category,
            "unit_of_measure": self.unit_of_measure,
            "price": str(self.price) if self.price is not None else None,
            "in_stock": self.in_stock,
            "image_url": self.image_url,
            "shop": self.shop.as_dict(),
            "variants": [v.as_dict() for v in self.variants],
        }


def _listed_shops() -> Select:
    """Shops on the marketplace that are in a state to answer a request."""
    return (
        select(OnlineStore, Tenant)
        .join(Tenant, Tenant.id == OnlineStore.tenant_id)
        .where(
            OnlineStore.list_on_marketplace.is_(True),
            Tenant.status.notin_(UNAVAILABLE_STATUSES),
        )
    )


def _listed_products() -> Select:
    """The cross-tenant catalogue.  The one place this boundary is crossed.

    Joined to ``online_stores`` rather than filtered by tenant id, because the
    shop's own opt-in is what makes a product visible here — there is no
    single tenant to scope to, which is exactly why this lives in one function
    with a name that says so.
    """
    return (
        select(Product, OnlineStore)
        .join(OnlineStore, OnlineStore.tenant_id == Product.tenant_id)
        .join(Tenant, Tenant.id == Product.tenant_id)
        .where(
            Product.on_marketplace.is_(True),
            Product.is_active.is_(True),
            OnlineStore.list_on_marketplace.is_(True),
            Tenant.status.notin_(UNAVAILABLE_STATUSES),
        )
    )


def shops(db: Session) -> list[MarketplaceShop]:
    """The shop directory, for browsing by vendor."""
    rows = db.execute(_listed_shops().order_by(OnlineStore.display_name)).all()
    return [_shop(store) for store, _tenant in rows]


def get_shop(db: Session, slug: str) -> MarketplaceShop:
    """One shop's marketplace listing."""
    row = db.execute(_listed_shops().where(OnlineStore.slug == slug)).first()
    if row is None:
        raise NotFoundError("Shop not found")
    return _shop(row[0])


def categories(db: Session) -> list[str]:
    """Category names with at least one listed product, across every shop."""
    rows = db.execute(
        select(Category.name)
        .join(Product, Product.category_id == Category.id)
        .join(OnlineStore, OnlineStore.tenant_id == Product.tenant_id)
        .join(Tenant, Tenant.id == Product.tenant_id)
        .where(
            Product.on_marketplace.is_(True),
            Product.is_active.is_(True),
            OnlineStore.list_on_marketplace.is_(True),
            Tenant.status.notin_(UNAVAILABLE_STATUSES),
        )
        .distinct()
        .order_by(Category.name)
    )
    return [row[0] for row in rows]


def marketplace_products(
    db: Session,
    *,
    query: str | None = None,
    category: str | None = None,
    shop_slug: str | None = None,
    limit: int = 30,
    offset: int = 0,
) -> tuple[list[MarketplaceProduct], int]:
    """Browse or search the whole marketplace.  Returns a page and the total."""
    limit = max(1, min(limit, MAX_PAGE))
    stmt = _listed_products().options(
        joinedload(Product.variants), joinedload(Product.category)
    )

    if query:
        term = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                Product.name.ilike(term),
                Product.brand.ilike(term),
                Product.description.ilike(term),
            )
        )
    if category:
        stmt = stmt.join(Category, Category.id == Product.category_id).where(
            Category.name == category
        )
    if shop_slug:
        stmt = stmt.where(OnlineStore.slug == shop_slug)

    total = db.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ).scalar_one()

    rows = (
        db.execute(
            stmt.order_by(OnlineStore.display_name, Product.name).limit(limit).offset(offset)
        )
        .unique()
        .all()
    )
    products = [product for product, _store in rows]
    availability = _in_stock(db, products)
    return (
        [_project(product, store, availability) for product, store in rows],
        int(total or 0),
    )


def get_marketplace_product(
    db: Session, product_id: uuid.UUID
) -> MarketplaceProduct:
    """One listed product, by its own shareable id."""
    row = db.execute(
        _listed_products()
        .where(Product.id == product_id)
        .options(joinedload(Product.variants), joinedload(Product.category))
    ).unique().first()
    if row is None:
        raise NotFoundError("Product not found")
    product, store = row
    return _project(product, store, _in_stock(db, [product]))


# --------------------------------------------------------------------------- #
# Projection
# --------------------------------------------------------------------------- #


def _shop(store: OnlineStore) -> MarketplaceShop:
    return MarketplaceShop(
        id=store.tenant_id,
        slug=store.slug,
        name=store.display_name,
        tagline=store.tagline,
        address=store.address,
        phone=store.contact_phone,
        has_own_page=bool(store.is_published),
    )


def _in_stock(db: Session, products: list[Product]) -> set[uuid.UUID]:
    """Variant ids with something on hand, as a set of booleans and no more.

    Quantities are deliberately not returned.  A rival could otherwise watch a
    shop's stock levels by polling the marketplace, and a buyer deciding
    whether to ask only needs to know that there is some.
    """
    if not products:
        return set()
    variant_ids = [variant.id for product in products for variant in product.variants]
    if not variant_ids:
        return set()
    rows = db.execute(
        select(StockBalance.variant_id)
        .where(StockBalance.variant_id.in_(variant_ids))
        .group_by(StockBalance.variant_id)
        .having(func.sum(StockBalance.quantity) > 0)
    ).scalars()
    return set(rows)


def _project(
    product: Product, store: OnlineStore, available: set[uuid.UUID]
) -> MarketplaceProduct:
    shop = _shop(store)
    show_prices = bool(store.show_prices)

    def price_of(variant: ProductVariant) -> Decimal | None:
        if not show_prices or variant.selling_price is None:
            return None
        return Decimal(variant.selling_price)

    variants = [
        MarketplaceVariant(
            id=variant.id,
            name=variant.name,
            is_default=variant.is_default,
            price=price_of(variant),
            # An untracked product is always askable; a tracked one needs stock.
            in_stock=(not product.track_stock) or variant.id in available,
        )
        for variant in product.variants
        if variant.is_active
    ]
    default = next((v for v in variants if v.is_default), variants[0] if variants else None)
    return MarketplaceProduct(
        id=product.id,
        name=product.name,
        description=product.online_description or product.description,
        brand=product.brand,
        category=product.category.name if product.category else None,
        unit_of_measure=product.unit_of_measure,
        price=default.price if default else None,
        in_stock=any(v.in_stock for v in variants),
        image_url=public_file_url(product.image_asset_id) if product.image_asset_id else None,
        shop=shop,
        variants=variants,
    )
