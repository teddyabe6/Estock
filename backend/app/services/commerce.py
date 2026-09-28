"""Storefront, enquiries and proformas (PRD 13, 14).

Publishing uses the same catalogue and stock as physical sales.  An enquiry or
a proforma never reserves or reduces stock; only an explicit conversion to a
sale does.

A visitor can fill a basket on the storefront and request a proforma from it.
That creates a numbered proforma in the ``requested`` state, priced from the
catalogue, which the seller reviews and sends.  Nothing about it touches stock
until the explicit conversion step.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, record_audit
from app.core.clock import local_today
from app.core.config import settings
from app.core.db import utcnow
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.permissions import Permission
from app.core.phone import normalise_et_phone
from app.core.security import generate_share_token
from app.core.tenancy import AuthContext, get_tenant_object, tenant_query
from app.models.catalogue import Category, Product, ProductVariant
from app.models.commerce import (
    CustomerEnquiry,
    EnquiryStatus,
    OnlineStore,
    Quotation,
    QuotationLine,
    QuotationStatus,
)
from app.models.contacts import Customer
from app.models.inventory import StockBalance
from app.models.platform import Tenant, TenantStatus
from app.services.messaging import notify_store
from app.services.numbering import next_number
from app.services.pricing import quantize_money
from app.services.storage import public_file_url

ZERO = Decimal("0.00")
DEFAULT_VALIDITY_DAYS = 14
#: One basket request cannot price a whole catalogue.
MAX_REQUEST_LINES = 50
#: Statuses in which the seller may still change lines, prices and terms.
EDITABLE_STATUSES = (QuotationStatus.REQUESTED, QuotationStatus.DRAFT, QuotationStatus.SENT)


# --------------------------------------------------------------------------- #
# Public storefront
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class PublicProduct:
    id: uuid.UUID
    name: str
    description: str | None
    brand: str | None
    category: str | None
    unit_of_measure: str
    price: Decimal | None
    in_stock: bool
    image_url: str | None = None
    variants: list[dict] = field(default_factory=list)

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
            "variants": self.variants,
        }


def get_public_store(db: Session, slug: str) -> tuple[OnlineStore, Tenant]:
    store = db.execute(
        select(OnlineStore).where(OnlineStore.slug == slug, OnlineStore.is_published.is_(True))
    ).scalar_one_or_none()
    if store is None:
        raise NotFoundError("Shop not found")
    tenant = db.get(Tenant, store.tenant_id)
    if tenant is None or tenant.status == TenantStatus.SUSPENDED:
        raise NotFoundError("Shop not found")
    return store, tenant


def store_for_tenant(db: Session, tenant_id: uuid.UUID) -> OnlineStore | None:
    """The tenant's storefront if it is published, for linking back to it."""
    return db.execute(
        select(OnlineStore).where(
            OnlineStore.tenant_id == tenant_id, OnlineStore.is_published.is_(True)
        )
    ).scalar_one_or_none()


def _published_products(tenant_id: uuid.UUID):
    return tenant_query(Product, tenant_id).where(
        Product.is_published.is_(True), Product.is_active.is_(True)
    )


def public_categories(db: Session, store: OnlineStore) -> list[str]:
    """Category names that have at least one published product, for filtering."""
    rows = db.execute(
        select(Category.name)
        .join(Product, Product.category_id == Category.id)
        .where(
            Product.tenant_id == store.tenant_id,
            Product.is_published.is_(True),
            Product.is_active.is_(True),
        )
        .distinct()
        .order_by(Category.name)
    )
    return [row[0] for row in rows]


def list_public_products(
    db: Session,
    store: OnlineStore,
    tenant: Tenant,
    *,
    query: str | None = None,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PublicProduct], int]:
    """Published products, with availability from the one shared stock source."""
    stmt = _published_products(store.tenant_id)
    if query:
        pattern = f"%{query.strip().lower()}%"
        stmt = stmt.where(
            or_(func.lower(Product.name).like(pattern), func.lower(Product.brand).like(pattern))
        )
    if category:
        stmt = stmt.join(Category, Product.category_id == Category.id).where(
            func.lower(Category.name) == category.strip().lower()
        )

    products = list(db.execute(stmt.order_by(Product.name)).scalars())
    stock = _stock_by_variant(db, [store.tenant_id], products)

    results: list[PublicProduct] = []
    for product in products:
        item = _public_product(product, store, stock)
        if tenant.hide_out_of_stock_online and not item.in_stock and product.track_stock:
            continue
        results.append(item)

    total = len(results)
    return results[offset : offset + limit], total


def get_public_product(
    db: Session, store: OnlineStore, tenant: Tenant, product_id: uuid.UUID
) -> PublicProduct:
    """One product for its own page and shareable link (PRD 13)."""
    product = db.execute(
        _published_products(store.tenant_id).where(Product.id == product_id)
    ).scalar_one_or_none()
    if product is None:
        raise NotFoundError("This product is not available")
    item = _public_product(product, store, _stock_by_variant(db, [store.tenant_id], [product]))
    if tenant.hide_out_of_stock_online and not item.in_stock and product.track_stock:
        raise NotFoundError("This product is not available at the moment")
    return item


def _public_product(
    product: Product, store: OnlineStore, stock: dict[uuid.UUID, Decimal]
) -> PublicProduct:
    variants = [variant for variant in product.variants if variant.is_active]
    on_hand = sum((stock.get(variant.id, ZERO) for variant in variants), ZERO)
    in_stock = on_hand > 0 or not product.track_stock
    default = product.default_variant

    def price_of(variant: ProductVariant) -> Decimal | None:
        if store.show_prices and variant.selling_price is not None:
            return Decimal(variant.selling_price)
        return None

    return PublicProduct(
        id=product.id,
        name=product.name,
        description=product.online_description or product.description,
        brand=product.brand,
        category=product.category.name if product.category else None,
        unit_of_measure=product.unit_of_measure,
        price=price_of(default),
        in_stock=in_stock,
        image_url=public_file_url(product.image_asset_id) if product.image_asset_id else None,
        variants=[
            {
                "id": str(variant.id),
                "name": variant.name,
                "is_default": variant.is_default,
                "price": (
                    str(price_of(variant)) if price_of(variant) is not None else None
                ),
                "in_stock": stock.get(variant.id, ZERO) > 0 or not product.track_stock,
            }
            for variant in variants
        ],
    )


def _stock_by_variant(
    db: Session, tenant_ids: list[uuid.UUID], products: list[Product]
) -> dict[uuid.UUID, Decimal]:
    variant_ids = [variant.id for product in products for variant in product.variants]
    if not variant_ids:
        return {}
    rows = db.execute(
        select(StockBalance.variant_id, func.sum(StockBalance.quantity))
        .where(StockBalance.tenant_id.in_(tenant_ids), StockBalance.variant_id.in_(variant_ids))
        .group_by(StockBalance.variant_id)
    )
    return {row[0]: Decimal(row[1] or 0) for row in rows}


# --------------------------------------------------------------------------- #
# The marketplace: every open shop at once
# --------------------------------------------------------------------------- #

MARKET_SORTS = ("name", "price_asc", "price_desc", "newest")


def market_stores(db: Session) -> list[tuple[OnlineStore, Tenant]]:
    """Published shops whose business is not suspended."""
    rows = db.execute(
        select(OnlineStore, Tenant)
        .join(Tenant, Tenant.id == OnlineStore.tenant_id)
        .where(OnlineStore.is_published.is_(True), Tenant.status != TenantStatus.SUSPENDED)
        .order_by(OnlineStore.display_name)
    )
    return [(row[0], row[1]) for row in rows]


def _shop_summary(store: OnlineStore) -> dict:
    return {
        "slug": store.slug,
        "display_name": store.display_name,
        "accepts_orders": store.accepts_orders,
        "show_prices": store.show_prices,
    }


def list_market_shops(db: Session) -> list[dict]:
    shops = []
    for store, _tenant in market_stores(db):
        count = db.execute(
            select(func.count()).select_from(_published_products(store.tenant_id).subquery())
        ).scalar_one()
        shops.append(
            {
                **_shop_summary(store),
                "tagline": store.tagline,
                "address": store.address,
                "telegram_username": store.telegram_username,
                "product_count": count,
                "categories": public_categories(db, store),
            }
        )
    return shops


def market_categories(db: Session) -> list[str]:
    tenant_ids = [tenant.id for _store, tenant in market_stores(db)]
    if not tenant_ids:
        return []
    rows = db.execute(
        select(Category.name)
        .join(Product, Product.category_id == Category.id)
        .where(
            Product.tenant_id.in_(tenant_ids),
            Product.is_published.is_(True),
            Product.is_active.is_(True),
        )
        .distinct()
        .order_by(Category.name)
    )
    return [row[0] for row in rows]


def list_market_products(
    db: Session,
    *,
    query: str | None = None,
    category: str | None = None,
    shop: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    in_stock_only: bool = False,
    sort: str = "name",
    limit: int = 24,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Published products across every open shop, with the shop on each item."""
    if sort not in MARKET_SORTS:
        raise ValidationError(f"sort must be one of {', '.join(MARKET_SORTS)}")
    stores = market_stores(db)
    if shop:
        stores = [(s, t) for s, t in stores if s.slug == shop.strip().lower()]
    by_tenant = {tenant.id: (store, tenant) for store, tenant in stores}
    if not by_tenant:
        return [], 0

    stmt = select(Product).where(
        Product.tenant_id.in_(list(by_tenant)),
        Product.is_published.is_(True),
        Product.is_active.is_(True),
    )
    if query:
        pattern = f"%{query.strip().lower()}%"
        stmt = stmt.where(
            or_(func.lower(Product.name).like(pattern), func.lower(Product.brand).like(pattern))
        )
    if category:
        stmt = stmt.join(Category, Product.category_id == Category.id).where(
            func.lower(Category.name) == category.strip().lower()
        )
    order = Product.created_at.desc() if sort == "newest" else Product.name
    products = list(db.execute(stmt.order_by(order)).scalars())
    stock = _stock_by_variant(db, list(by_tenant), products)

    items: list[dict] = []
    for product in products:
        store, tenant = by_tenant[product.tenant_id]
        item = _public_product(product, store, stock)
        if tenant.hide_out_of_stock_online and not item.in_stock and product.track_stock:
            continue
        if in_stock_only and not item.in_stock:
            continue
        if min_price is not None and (item.price is None or item.price < min_price):
            continue
        if max_price is not None and (item.price is None or item.price > max_price):
            continue
        payload = item.as_dict()
        payload["shop"] = _shop_summary(store)
        items.append(payload)

    if sort in ("price_asc", "price_desc"):
        priced = [i for i in items if i["price"] is not None]
        unpriced = [i for i in items if i["price"] is None]
        priced.sort(key=lambda i: Decimal(i["price"]), reverse=sort == "price_desc")
        items = priced + unpriced

    total = len(items)
    return items[offset : offset + limit], total


def submit_enquiry(
    db: Session,
    store: OnlineStore,
    *,
    contact_name: str,
    contact_phone: str,
    contact_email: str | None = None,
    company: str | None = None,
    delivery_location: str | None = None,
    message: str | None = None,
    items: list[dict] | None = None,
    wants_proforma: bool = False,
    source_ip: str | None = None,
) -> CustomerEnquiry:
    """Accept a storefront enquiry.  No stock is touched (PRD 13, A4)."""
    if not contact_name.strip():
        raise ValidationError("Please give your name")
    if not contact_phone.strip():
        raise ValidationError("Please give a phone number we can reach you on")

    enquiry = CustomerEnquiry(
        tenant_id=store.tenant_id,
        reference=next_number(
            db, CustomerEnquiry, store.tenant_id, "enquiry", column="reference"
        ),
        status=EnquiryStatus.NEW,
        contact_name=contact_name.strip(),
        contact_phone=contact_phone.strip(),
        contact_email=(contact_email or "").strip() or None,
        company=company,
        delivery_location=delivery_location,
        message=message,
        requested_items_json=json.dumps(items) if items else None,
        wants_proforma=wants_proforma,
        source_ip=source_ip,
    )
    db.add(enquiry)
    db.flush()
    notify_staff(
        db,
        tenant_id=enquiry.tenant_id,
        permission=Permission.ENQUIRY_VIEW,
        kind="new_enquiry",
        title=f"New enquiry from {enquiry.contact_name}",
        body=enquiry.message,
        link=f"/shop?tab=enquiries&open={enquiry.id}",
        entity_type="customer_enquiry",
        entity_id=enquiry.id,
    )
    return enquiry


def notify_staff(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    permission: Permission,
    kind: str,
    title: str,
    body: str | None,
    link: str,
    entity_type: str,
    entity_id: uuid.UUID,
) -> int:
    """One in-app notification per active member who may act on it."""
    from app.models.access import MembershipStatus, TenantMembership
    from app.models.system import Notification, NotificationKind

    memberships = db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.status == MembershipStatus.ACTIVE,
        )
    ).scalars()
    count = 0
    for membership in memberships:
        if permission not in membership.effective_permissions():
            continue
        db.add(
            Notification(
                tenant_id=tenant_id,
                user_id=membership.user_id,
                kind=NotificationKind(kind),
                title=title,
                body=body,
                link=link,
                entity_type=entity_type,
                entity_id=entity_id,
            )
        )
        count += 1
    db.flush()
    return count


# --------------------------------------------------------------------------- #
# Quotations / proformas
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class QuotationLineInput:
    description: str | None = None
    variant_id: uuid.UUID | None = None
    quantity: Decimal = Decimal("1")
    unit_price: Decimal | None = None
    discount_amount: Decimal | None = None
    tax_rate: Decimal | None = None


@dataclass(slots=True)
class QuotationInput:
    customer_name: str
    lines: list[QuotationLineInput]
    customer_id: uuid.UUID | None = None
    customer_phone: str | None = None
    customer_email: str | None = None
    customer_company: str | None = None
    delivery_location: str | None = None
    delivery_charge: Decimal = ZERO
    branch_id: uuid.UUID | None = None
    enquiry_id: uuid.UUID | None = None
    valid_until: date | None = None
    validity_days: int | None = None
    terms: str | None = None
    note: str | None = None


@dataclass(slots=True)
class BasketItem:
    variant_id: uuid.UUID
    quantity: Decimal


def create_quotation(db: Session, ctx: AuthContext, data: QuotationInput) -> Quotation:
    """Build a numbered proforma.  Not a sale and not a stock deduction (PRD 14)."""
    ctx.require(Permission.QUOTATION_MANAGE)
    if not data.lines:
        raise ValidationError("A proforma needs at least one line")
    if not data.customer_name.strip():
        raise ValidationError("Who is this proforma for?")

    today = local_today(ctx.tenant.timezone)
    valid_until = data.valid_until or (
        today + timedelta(days=data.validity_days or DEFAULT_VALIDITY_DAYS)
    )
    if valid_until < today:
        raise ValidationError("The validity date is in the past")

    quotation = Quotation(
        tenant_id=ctx.tenant_id,
        number=next_number(db, Quotation, ctx.tenant_id, "quotation"),
        status=QuotationStatus.DRAFT,
        branch_id=data.branch_id,
        customer_id=data.customer_id,
        enquiry_id=data.enquiry_id,
        customer_name=data.customer_name.strip(),
        customer_phone=data.customer_phone,
        customer_email=data.customer_email,
        customer_company=data.customer_company,
        delivery_location=data.delivery_location,
        issued_on=today,
        valid_until=valid_until,
        delivery_charge=quantize_money(Decimal(data.delivery_charge or 0)),
        currency=ctx.tenant.currency,
        terms=data.terms,
        note=data.note,
        created_by_id=ctx.user_id,
    )
    db.add(quotation)
    db.flush()
    _apply_lines(db, ctx.tenant_id, quotation, data.lines)
    return quotation


def request_quotation(
    db: Session,
    store: OnlineStore,
    tenant: Tenant,
    *,
    items: list[BasketItem],
    contact_name: str,
    contact_phone: str,
    contact_email: str | None = None,
    company: str | None = None,
    delivery_location: str | None = None,
    message: str | None = None,
    batch_id: uuid.UUID | None = None,
) -> Quotation:
    """A visitor's basket becomes a numbered proforma request (PRD 13, 14).

    Lines are priced from the catalogue so the seller reviews rather than
    retypes, the customer is matched to an existing record by phone, staff who
    handle proformas are notified in the app, and the shop is told by email
    and Telegram.  No stock is reserved.
    """
    if not items:
        raise ValidationError("Your basket is empty")
    if len(items) > MAX_REQUEST_LINES:
        raise ValidationError(f"A request can hold at most {MAX_REQUEST_LINES} different items")
    if not contact_name.strip():
        raise ValidationError("Please give your name")
    if not contact_phone.strip():
        raise ValidationError("Please give a phone number the seller can reach you on")

    wanted: dict[uuid.UUID, Decimal] = {}
    for item in items:
        quantity = Decimal(item.quantity)
        if quantity <= 0:
            raise ValidationError("Quantities must be positive")
        wanted[item.variant_id] = wanted.get(item.variant_id, ZERO) + quantity

    variants = db.execute(
        select(ProductVariant)
        .join(Product, ProductVariant.product_id == Product.id)
        .where(
            ProductVariant.tenant_id == store.tenant_id,
            ProductVariant.id.in_(list(wanted)),
            ProductVariant.is_active.is_(True),
            Product.is_published.is_(True),
            Product.is_active.is_(True),
        )
    ).scalars()
    by_id = {variant.id: variant for variant in variants}
    unavailable = [str(variant_id) for variant_id in wanted if variant_id not in by_id]
    if unavailable:
        raise ValidationError(
            "Some items in your basket are no longer available. Remove them and try again.",
            details={"unavailable": unavailable},
        )

    customer = find_or_create_customer(
        db,
        store.tenant_id,
        name=contact_name,
        phone=contact_phone,
        email=contact_email,
        company=company,
        address=delivery_location,
    )
    quotation = Quotation(
        tenant_id=store.tenant_id,
        number=next_number(db, Quotation, store.tenant_id, "quotation"),
        status=QuotationStatus.REQUESTED,
        batch_id=batch_id,
        customer_id=customer.id,
        customer_name=contact_name.strip(),
        customer_phone=customer.phone,
        customer_email=(contact_email or "").strip() or None,
        customer_company=(company or "").strip() or None,
        delivery_location=(delivery_location or "").strip() or None,
        issued_on=local_today(tenant.timezone),
        valid_until=None,  # set when the seller sends it
        currency=tenant.currency,
        terms=store.default_terms,
        customer_message=(message or "").strip() or None,
        # The customer gets their tracking link straight away.
        share_token=generate_share_token(),
    )
    db.add(quotation)
    db.flush()
    _apply_lines(
        db,
        store.tenant_id,
        quotation,
        [
            QuotationLineInput(
                variant_id=variant_id,
                quantity=quantity,
                unit_price=Decimal(by_id[variant_id].selling_price or 0),
            )
            for variant_id, quantity in wanted.items()
        ],
    )
    notify_staff(
        db,
        tenant_id=store.tenant_id,
        permission=Permission.QUOTATION_VIEW,
        kind="proforma_request",
        title=f"Proforma request {quotation.number} from {quotation.customer_name}",
        body=(
            f"{len(quotation.lines)} item(s) · {quotation.total_amount} {quotation.currency}"
            + (f" · {quotation.customer_message}" if quotation.customer_message else "")
        ),
        link=f"/shop?tab=proformas&open={quotation.id}",
        entity_type="quotation",
        entity_id=quotation.id,
    )
    notify_store(
        db,
        store,
        tenant,
        subject=f"Proforma request {quotation.number} from {quotation.customer_name}",
        lines=describe_request(quotation),
        link=f"{settings.public_base_url}/shop?tab=proformas&open={quotation.id}",
    )
    return quotation


def describe_request(quotation: Quotation) -> list[str]:
    """The shop's own part of a request, one line per item, for email or Telegram."""
    lines = [
        f"• {line.description} × {Decimal(line.quantity).normalize():f} "
        f"@ {line.unit_price} = {line.line_total} {quotation.currency}"
        for line in quotation.lines
    ]
    lines.append(f"Total at catalogue prices: {quotation.total_amount} {quotation.currency}")
    lines.append(f"From: {quotation.customer_name} · {quotation.customer_phone or ''}".rstrip(" ·"))
    if quotation.customer_company:
        lines.append(f"Company: {quotation.customer_company}")
    if quotation.delivery_location:
        lines.append(f"Deliver to: {quotation.delivery_location}")
    if quotation.customer_message:
        lines.append(f"Note: {quotation.customer_message}")
    return lines


def quotation_next_step(status: QuotationStatus) -> str:
    return _NEXT_STEP.get(status, "")


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


def find_or_create_customer(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    name: str,
    phone: str,
    email: str | None,
    company: str | None,
    address: str | None,
) -> Customer:
    """Match on the phone number, the one identifier a walk-in customer has."""
    normalised = normalise_et_phone(phone) or phone.strip()
    customer = db.execute(
        tenant_query(Customer, tenant_id)
        .where(Customer.phone.in_([normalised, phone.strip()]))
        .order_by(Customer.created_at)
    ).scalars().first()
    if customer is None:
        customer = Customer(
            tenant_id=tenant_id,
            name=name.strip(),
            phone=normalised,
            email=(email or "").strip() or None,
            company=(company or "").strip() or None,
            address=(address or "").strip() or None,
        )
        db.add(customer)
    else:
        customer.email = customer.email or (email or "").strip() or None
        customer.company = customer.company or (company or "").strip() or None
        customer.address = customer.address or (address or "").strip() or None
    db.flush()
    return customer


def _apply_lines(
    db: Session, tenant_id: uuid.UUID, quotation: Quotation, lines: list[QuotationLineInput]
) -> None:
    """Replace the lines and recompute every total from them."""
    if not lines:
        raise ValidationError("A proforma needs at least one line")
    quotation.lines.clear()
    db.flush()

    for index, line in enumerate(lines):
        quantity = Decimal(line.quantity)
        if quantity <= 0:
            raise ValidationError("Quantities must be positive")

        variant = None
        if line.variant_id is not None:
            variant = get_tenant_object(
                db, ProductVariant, line.variant_id, tenant_id, label="Product"
            )
        description = line.description or (variant.display_name if variant else None)
        if not description:
            raise ValidationError("Each line needs a product or a description")

        unit_price = quantize_money(
            Decimal(
                line.unit_price
                if line.unit_price is not None
                else (variant.selling_price if variant and variant.selling_price else 0)
            )
        )
        if unit_price < 0:
            raise ValidationError("Prices cannot be negative")
        gross = quantize_money(unit_price * quantity)
        discount = quantize_money(Decimal(line.discount_amount or 0))
        if discount < 0:
            raise ValidationError("Discounts cannot be negative")
        if discount > gross:
            raise ValidationError("Discount cannot exceed the line total")
        net = quantize_money(gross - discount)
        tax_rate = Decimal(
            line.tax_rate
            if line.tax_rate is not None
            else (variant.tax_rate if variant and variant.tax_rate else 0)
        )
        tax_amount = quantize_money(net * tax_rate)

        quotation.lines.append(
            QuotationLine(
                product_id=variant.product_id if variant else None,
                variant_id=variant.id if variant else None,
                description=description,
                quantity=quantity,
                unit_price=unit_price,
                discount_amount=discount,
                tax_rate=tax_rate,
                tax_amount=tax_amount,
                line_total=quantize_money(net + tax_amount),
                sort_order=index,
            )
        )
    _recalculate(quotation)
    db.flush()


def _recalculate(quotation: Quotation) -> None:
    subtotal = discount_total = tax_total = ZERO
    for line in quotation.lines:
        subtotal = quantize_money(
            subtotal + quantize_money(Decimal(line.unit_price) * Decimal(line.quantity))
        )
        discount_total = quantize_money(discount_total + Decimal(line.discount_amount))
        tax_total = quantize_money(tax_total + Decimal(line.tax_amount))
    quotation.subtotal = subtotal
    quotation.discount_total = discount_total
    quotation.tax_total = tax_total
    quotation.total_amount = quantize_money(
        subtotal - discount_total + tax_total + Decimal(quotation.delivery_charge or 0)
    )


def update_quotation(
    db: Session,
    ctx: AuthContext,
    quotation_id: uuid.UUID,
    *,
    lines: list[QuotationLineInput] | None = None,
    delivery_charge: Decimal | None = None,
    valid_until: date | None = None,
    validity_days: int | None = None,
    fields: dict | None = None,
) -> Quotation:
    """The seller's review step: adjust lines, prices, delivery and terms.

    Allowed while the proforma is requested, a draft, or sent but not yet
    answered.  Once the customer has accepted it, or it has become a sale,
    the numbers it carries are what was agreed and stay as they are.
    """
    ctx.require(Permission.QUOTATION_MANAGE)
    quotation = get_tenant_object(db, Quotation, quotation_id, ctx.tenant_id, label="Proforma")
    if quotation.status not in EDITABLE_STATUSES:
        raise ConflictError(f"A proforma that is {quotation.status} can no longer be changed")

    for key, value in (fields or {}).items():
        if key not in {
            "customer_name",
            "customer_phone",
            "customer_email",
            "customer_company",
            "delivery_location",
            "terms",
            "note",
            "branch_id",
        }:
            raise ValidationError(f"'{key}' cannot be changed here")
        if key == "customer_name" and not (value or "").strip():
            raise ValidationError("Who is this proforma for?")
        setattr(quotation, key, value)

    today = local_today(ctx.tenant.timezone)
    if valid_until is not None:
        if valid_until < today:
            raise ValidationError("The validity date is in the past")
        quotation.valid_until = valid_until
    elif validity_days is not None:
        quotation.valid_until = today + timedelta(days=validity_days)

    if delivery_charge is not None:
        if Decimal(delivery_charge) < 0:
            raise ValidationError("The delivery charge cannot be negative")
        quotation.delivery_charge = quantize_money(Decimal(delivery_charge))

    if lines is not None:
        _apply_lines(db, ctx.tenant_id, quotation, lines)
    else:
        _recalculate(quotation)

    record_audit(
        db,
        action=AuditAction.QUOTATION_UPDATED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="quotation",
        entity_id=quotation.id,
        summary=f"Updated proforma {quotation.number}",
    )
    db.flush()
    return quotation


def send_quotation(db: Session, ctx: AuthContext, quotation_id: uuid.UUID) -> Quotation:
    """Mark as sent and mint the secure share link (PRD 14).

    For a storefront request this is the seller's confirmation: the customer's
    existing link starts showing the priced proforma, and they can accept it.
    """
    ctx.require(Permission.QUOTATION_MANAGE)
    quotation = get_tenant_object(
        db, Quotation, quotation_id, ctx.tenant_id, label="Proforma"
    )
    if quotation.status in (QuotationStatus.CONVERTED, QuotationStatus.CANCELLED):
        raise ConflictError(f"This proforma is {quotation.status}")
    unpriced = [
        line.description
        for line in quotation.lines
        if line.variant_id is not None and Decimal(line.unit_price) == 0
    ]
    if unpriced:
        raise ValidationError(
            f"Give every item a price before sending: {', '.join(unpriced[:3])}"
            + (" and more" if len(unpriced) > 3 else "")
        )

    was_requested = quotation.status == QuotationStatus.REQUESTED
    today = local_today(ctx.tenant.timezone)
    if quotation.valid_until is None or quotation.valid_until < today:
        quotation.valid_until = today + timedelta(days=DEFAULT_VALIDITY_DAYS)
    if not quotation.share_token:
        quotation.share_token = generate_share_token()
    quotation.status = QuotationStatus.SENT
    quotation.sent_at = utcnow()

    record_audit(
        db,
        action=AuditAction.QUOTATION_SENT,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="quotation",
        entity_id=quotation.id,
        summary=f"Sent proforma {quotation.number}",
    )
    db.flush()

    if was_requested and quotation.customer_email:
        from app.services.notifications import send_email

        send_email(
            to=quotation.customer_email,
            subject=f"Your proforma {quotation.number} from {ctx.tenant.name}",
            body=(
                f"Hello {quotation.customer_name},\n\n{ctx.tenant.name} has sent your "
                f"proforma {quotation.number} for {quotation.total_amount} "
                f"{quotation.currency}. Open it here:\n\n{share_links(quotation)['url']}\n"
            ),
        )
    return quotation


def cancel_quotation(
    db: Session, ctx: AuthContext, quotation_id: uuid.UUID, *, reason: str | None = None
) -> Quotation:
    """Withdraw a proforma.  Its share link stops working; nothing else changes."""
    ctx.require(Permission.QUOTATION_MANAGE)
    quotation = get_tenant_object(db, Quotation, quotation_id, ctx.tenant_id, label="Proforma")
    if quotation.status == QuotationStatus.CONVERTED:
        raise ConflictError("This proforma became a sale; void the sale instead")
    if quotation.status == QuotationStatus.CANCELLED:
        raise ConflictError("This proforma is already cancelled")
    quotation.status = QuotationStatus.CANCELLED
    record_audit(
        db,
        action=AuditAction.QUOTATION_CANCELLED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="quotation",
        entity_id=quotation.id,
        summary=f"Cancelled proforma {quotation.number}"
        + (f": {reason.strip()}" if reason and reason.strip() else ""),
    )
    db.flush()
    return quotation


def share_links(quotation: Quotation) -> dict[str, str | None]:
    """Web link plus a ready-to-use Telegram/email share (PRD 14)."""
    if not quotation.share_token:
        return {"url": None, "telegram": None, "mailto": None}
    from urllib.parse import quote

    url = f"{settings.public_base_url}/q/{quotation.share_token}"
    text = f"Proforma {quotation.number} — {quotation.total_amount} {quotation.currency}"
    return {
        "url": url,
        "telegram": f"https://t.me/share/url?url={quote(url)}&text={quote(text)}",
        "mailto": (
            f"mailto:{quotation.customer_email or ''}"
            f"?subject={quote(text)}&body={quote(url)}"
        ),
    }


def get_quotation_by_token(db: Session, token: str) -> Quotation:
    quotation = db.execute(
        select(Quotation).where(Quotation.share_token == token)
    ).scalar_one_or_none()
    if quotation is None or quotation.status == QuotationStatus.CANCELLED:
        raise NotFoundError("This proforma link is no longer valid")
    return quotation


def quotation_status_for(quotation: Quotation, *, today: date | None = None) -> QuotationStatus:
    """Expire a sent proforma once its validity date has passed."""
    today = today or date.today()
    if (
        quotation.status == QuotationStatus.SENT
        and quotation.valid_until is not None
        and quotation.valid_until < today
    ):
        return QuotationStatus.EXPIRED
    return quotation.status


def respond_to_quotation(db: Session, token: str, *, accept: bool) -> Quotation:
    """Customer acceptance.  Records intent only — no sale, no stock (PRD 14)."""
    quotation = get_quotation_by_token(db, token)
    if quotation.status == QuotationStatus.REQUESTED:
        raise ConflictError("The seller has not sent this proforma yet")
    if quotation_status_for(quotation) == QuotationStatus.EXPIRED:
        raise ConflictError("This proforma has expired. Ask the seller for a new one.")
    if quotation.status not in (QuotationStatus.SENT, QuotationStatus.DRAFT):
        raise ConflictError(f"This proforma is already {quotation.status}")

    if accept:
        quotation.status = QuotationStatus.ACCEPTED
        quotation.accepted_at = utcnow()
    else:
        quotation.status = QuotationStatus.DECLINED
        quotation.declined_at = utcnow()
    db.flush()
    notify_staff(
        db,
        tenant_id=quotation.tenant_id,
        permission=Permission.QUOTATION_VIEW,
        kind="proforma_response",
        title=(
            f"{quotation.customer_name} accepted proforma {quotation.number}"
            if accept
            else f"{quotation.customer_name} declined proforma {quotation.number}"
        ),
        body=(
            f"{quotation.total_amount} {quotation.currency}. Convert it to a sale when the "
            "goods go out."
            if accept
            else None
        ),
        link=f"/shop?tab=proformas&open={quotation.id}",
        entity_type="quotation",
        entity_id=quotation.id,
    )
    return quotation


def convert_to_sale(
    db: Session,
    ctx: AuthContext,
    quotation_id: uuid.UUID,
    *,
    branch_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    payments: list | None = None,
    due_date: date | None = None,
):
    """The explicit step that turns a proforma into a sale (PRD 14)."""
    from app.services.sales import SaleInput, SaleLineInput, create_sale

    ctx.require(Permission.QUOTATION_MANAGE, Permission.SALE_CREATE)
    quotation = get_tenant_object(
        db, Quotation, quotation_id, ctx.tenant_id, label="Proforma"
    )
    if quotation.status == QuotationStatus.CONVERTED:
        raise ConflictError("This proforma has already been converted to a sale")
    if quotation.status == QuotationStatus.CANCELLED:
        raise ConflictError("This proforma has been cancelled")

    lines = []
    for line in quotation.lines:
        if line.variant_id is None:
            raise ValidationError(
                f"'{line.description}' is not linked to a product, so it cannot be sold. "
                "Edit the proforma and choose a product for each line."
            )
        lines.append(
            SaleLineInput(
                variant_id=line.variant_id,
                quantity=Decimal(line.quantity),
                unit_price=Decimal(line.unit_price),
                discount_amount=Decimal(line.discount_amount),
                tax_rate=Decimal(line.tax_rate),
            )
        )

    customer_id = quotation.customer_id
    if customer_id is None and quotation.customer_phone:
        customer = Customer(
            tenant_id=ctx.tenant_id,
            name=quotation.customer_name,
            phone=quotation.customer_phone,
            email=quotation.customer_email,
            company=quotation.customer_company,
            address=quotation.delivery_location,
        )
        db.add(customer)
        db.flush()
        customer_id = customer.id
        quotation.customer_id = customer_id

    result = create_sale(
        db,
        ctx,
        SaleInput(
            lines=lines,
            payments=payments or [],
            branch_id=branch_id or quotation.branch_id,
            location_id=location_id,
            customer_id=customer_id,
            note=f"From proforma {quotation.number}",
            due_date=due_date,
            idempotency_key=f"quotation:{quotation.id}",
        ),
    )
    if Decimal(quotation.delivery_charge or 0) > 0:
        # A sale has no delivery line; say so rather than let the charge vanish.
        result.warnings.append(
            f"The proforma's delivery charge of {quotation.delivery_charge} "
            f"{quotation.currency} is not part of the sale total; record it separately."
        )

    quotation.status = QuotationStatus.CONVERTED
    quotation.converted_sale_id = result.sale.id
    record_audit(
        db,
        action=AuditAction.QUOTATION_CONVERTED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="quotation",
        entity_id=quotation.id,
        summary=f"Converted {quotation.number} to sale {result.sale.number}",
    )
    db.flush()
    return result
