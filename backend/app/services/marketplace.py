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

import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import Select, and_, case, exists, func, or_, select
from sqlalchemy.orm import Session, aliased, joinedload

from app.core.errors import NotFoundError
from app.models.catalogue import Category, Product, ProductVariant
from app.models.commerce import OnlineStore
from app.models.inventory import StockBalance
from app.models.platform import Tenant, TenantStatus
from app.services import platform_settings
from app.services.storage import public_file_url

#: Shops in these states cannot post anything, so they cannot answer a
#: request.  Listing them would send buyers to a dead end.
UNAVAILABLE_STATUSES = (TenantStatus.SUSPENDED, TenantStatus.RESTRICTED)

MAX_PAGE = 60

#: The orders a buyer may ask for, named as the shop view names them.
SORT_ORDERS = ("name", "price_low", "price_high")

#: How many of another shop's products to put under one, and how much of a
#: name has to match.  Four tokens is enough for "Cement bag 50kg" and keeps
#: the OR from growing into a scan of the whole catalogue.
MAX_RELATED = 8
MAX_NAME_TOKENS = 4
MIN_TOKEN = 3


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


def taking_part(db: Session, tenant_column):
    """Shops the platform owner has not paused, as a SQL condition.

    Two separate decisions decide whether a shop appears here, and keeping
    them apart matters.  ``OnlineStore.list_on_marketplace`` is the *shop's*
    choice to be listed.  ``marketplace_listed`` is the *platform owner's*
    switch over that shop — a way to stop sending buyers to a shop that is
    not answering, without quietly rewriting the shop's own decision, which
    would be there waiting the moment the pause was lifted.
    """
    return platform_settings.participation_filter(db, "marketplace_listed", tenant_column)


def _listed_shops(db: Session) -> Select:
    """Shops on the marketplace that are in a state to answer a request.

    A shop with nothing listed is left out.  Every new shop joins by default,
    so without this the directory fills with names that lead to an empty
    page — and "17 shops" that are mostly empty says less than "3" that are
    not.  The shop reappears the moment it lists something.
    """
    return (
        select(OnlineStore, Tenant)
        .join(Tenant, Tenant.id == OnlineStore.tenant_id)
        .where(
            OnlineStore.list_on_marketplace.is_(True),
            Tenant.status.notin_(UNAVAILABLE_STATUSES),
            taking_part(db, OnlineStore.tenant_id),
            exists().where(
                Product.tenant_id == OnlineStore.tenant_id,
                Product.on_marketplace.is_(True),
                Product.is_active.is_(True),
            ),
        )
    )


def _listed_products(db: Session) -> Select:
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
            taking_part(db, Product.tenant_id),
        )
    )


def shops(db: Session) -> list[MarketplaceShop]:
    """The shop directory, for browsing by vendor."""
    rows = db.execute(_listed_shops(db).order_by(OnlineStore.display_name)).all()
    return [_shop(store) for store, _tenant in rows]


def get_shop(db: Session, slug: str) -> MarketplaceShop:
    """One shop's marketplace listing."""
    row = db.execute(_listed_shops(db).where(OnlineStore.slug == slug)).first()
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
            taking_part(db, Product.tenant_id),
        )
        .distinct()
        .order_by(Category.name)
    )
    return [row[0] for row in rows]


def _with_shown_price(stmt: Select):
    """Attach the price a buyer is shown, as SQL.

    The same rule :func:`_project` applies when it builds a card — the default
    variant's price, and nothing at all where the shop hides prices — said
    once more in SQL so that a filter and a sort can use it without first
    loading every listed product on the platform into memory.
    """
    variant = aliased(ProductVariant)
    stmt = stmt.outerjoin(
        variant,
        and_(
            variant.product_id == Product.id,
            variant.is_default.is_(True),
            variant.is_active.is_(True),
        ),
    )
    shown = case((OnlineStore.show_prices.is_(True), variant.selling_price), else_=None)
    return stmt, shown


def price_range(db: Session) -> tuple[Decimal | None, Decimal | None]:
    """The cheapest and dearest price on the marketplace.

    Over the whole listed catalogue rather than the filtered page, so the
    bounds a buyer is offered do not move about as they narrow things down.
    ``(None, None)`` where nothing carries a price, which is the signal not to
    offer a price filter at all rather than offer an empty one.
    """
    stmt, shown = _with_shown_price(_listed_products(db))
    inner = stmt.with_only_columns(shown.label("price")).order_by(None).subquery()
    low, high = db.execute(
        select(func.min(inner.c.price), func.max(inner.c.price))
    ).one()
    if low is None or high is None:
        return None, None
    return Decimal(low), Decimal(high)


def marketplace_products(
    db: Session,
    *,
    query: str | None = None,
    category: str | None = None,
    shop_slug: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    sort: str | None = None,
    limit: int = 30,
    offset: int = 0,
) -> tuple[list[MarketplaceProduct], int]:
    """Browse or search the whole marketplace.  Returns a page and the total."""
    limit = max(1, min(limit, MAX_PAGE))
    stmt = _listed_products(db).options(
        joinedload(Product.variants), joinedload(Product.category)
    )
    stmt, shown = _with_shown_price(stmt)

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
    # A bound excludes anything with no price to compare: a product whose
    # price is "ask us" cannot be said to be under 500 birr.
    if min_price is not None:
        stmt = stmt.where(shown >= min_price)
    if max_price is not None:
        stmt = stmt.where(shown <= max_price)

    total = db.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ).scalar_one()

    # By name first, not by shop: the point of a marketplace is that the same
    # thing from two shops lands side by side.  A product with no price shown
    # sorts last either way rather than being treated as free.
    if sort == "price_low":
        order = (shown.is_(None), shown.asc(), Product.name)
    elif sort == "price_high":
        order = (shown.is_(None), shown.desc(), Product.name)
    else:
        order = (Product.name, OnlineStore.display_name)

    rows = (
        db.execute(stmt.order_by(*order).limit(limit).offset(offset))
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
        _listed_products(db)
        .where(Product.id == product_id)
        .options(joinedload(Product.variants), joinedload(Product.category))
    ).unique().first()
    if row is None:
        raise NotFoundError("Product not found")
    product, store = row
    return _project(product, store, _in_stock(db, [product]))


#: A size rather than a thing: 50kg, 12mm, 1kg, 500ml.  Matching on one puts
#: sugar under cement, and the size is on the card anyway.
_SIZE = re.compile(r"^\d+[a-z]{0,3}$")


def _name_tokens(name: str) -> list[str]:
    """The words of a product name worth matching another shop's against."""
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[^0-9A-Za-z\u1200-\u137f]+", name.lower()):
        if len(raw) < MIN_TOKEN or raw in seen or _SIZE.match(raw):
            continue
        seen.add(raw)
        tokens.append(raw)
        if len(tokens) == MAX_NAME_TOKENS:
            break
    return tokens


def related_elsewhere(
    db: Session, product_id: uuid.UUID, *, limit: int = MAX_RELATED
) -> list[MarketplaceProduct]:
    """The same sort of thing, at other shops.

    This is what makes a marketplace worth opening a product page in: the item
    you are looking at, from somebody else, with their price beside it.
    Matched on the words of the name first and the category second, because
    "Cement bag 50kg" somewhere else is a far better answer than something
    else from Building.  Cheapest first *within* each of those, so the
    comparison a buyer came to make is at the top and never buried under an
    unrelated bargain.

    Never this shop's own products.  A buyer comparing prices is not helped by
    more of what they are already looking at, and the shop they are on already
    has a page of its own.
    """
    origin = get_marketplace_product(db, product_id)
    base, shown = _with_shown_price(_listed_products(db))
    base = base.where(Product.tenant_id != origin.shop.id).options(
        joinedload(Product.variants), joinedload(Product.category)
    )

    found: list[tuple[Product, OnlineStore]] = []
    seen: set[uuid.UUID] = set()

    def take(stmt: Select) -> None:
        rows = (
            db.execute(stmt.order_by(shown.is_(None), shown.asc(), Product.name).limit(limit))
            .unique()
            .all()
        )
        for product, store in rows:
            if product.id in seen or len(found) >= limit:
                continue
            seen.add(product.id)
            found.append((product, store))

    tokens = _name_tokens(origin.name)
    if tokens:
        take(base.where(or_(*(func.lower(Product.name).like(f"%{token}%") for token in tokens))))
    if origin.category and len(found) < limit:
        take(
            base.join(Category, Category.id == Product.category_id).where(
                func.lower(Category.name) == origin.category.lower()
            )
        )

    availability = _in_stock(db, [product for product, _ in found])
    return [_project(product, store, availability) for product, store in found]


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
