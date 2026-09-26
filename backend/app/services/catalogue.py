"""Product creation and maintenance (PRD 8).

Only a name is required.  A product always gets a default variant so stock,
sales and pricing have one shape to work with, and opening stock is posted as a
real movement rather than a silent balance (PRD 8.3, 9).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.permissions import Permission
from app.core.tenancy import (
    AuthContext,
    get_tenant_object,
    resolve_branch,
    resolve_location,
    tenant_query,
)
from app.models.catalogue import Category, Product, ProductVariant
from app.models.inventory import MovementReason, StockBalance
from app.services.inventory import StockPosting, post_movement
from app.services.pricing import quantize_money

ZERO = Decimal("0.00")

#: Money columns hold two decimals; round on input so the value held in memory
#: is the value that was stored.
MONEY_FIELDS = ("purchase_price", "transport_cost", "other_costs", "selling_price")


def _money(value: Decimal | None) -> Decimal | None:
    return None if value is None else quantize_money(Decimal(value))


@dataclass(slots=True)
class VariantInput:
    name: str | None = None
    attributes: dict[str, str] | None = None
    sku: str | None = None
    barcode: str | None = None
    purchase_price: Decimal | None = None
    transport_cost: Decimal | None = None
    other_costs: Decimal | None = None
    selling_price: Decimal | None = None
    tax_rate: Decimal | None = None
    max_discount_percent: Decimal | None = None
    min_stock: Decimal | None = None
    reorder_level: Decimal | None = None
    opening_stock: Decimal | None = None


@dataclass(slots=True)
class ProductInput:
    name: str
    sku: str | None = None
    description: str | None = None
    brand: str | None = None
    unit_of_measure: str = "pcs"
    category_id: uuid.UUID | None = None
    category_name: str | None = None
    preferred_supplier_id: uuid.UUID | None = None
    track_stock: bool = True
    is_published: bool = False
    online_description: str | None = None
    variants: list[VariantInput] = field(default_factory=list)
    # Convenience fields for the "add a product quickly" flow (PRD A1).
    purchase_price: Decimal | None = None
    transport_cost: Decimal | None = None
    other_costs: Decimal | None = None
    selling_price: Decimal | None = None
    barcode: str | None = None
    opening_stock: Decimal | None = None
    min_stock: Decimal | None = None
    reorder_level: Decimal | None = None
    branch_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None


def get_or_create_category(
    db: Session, ctx: AuthContext, name: str | None
) -> Category | None:
    if not name or not name.strip():
        return None
    name = name.strip()
    category = db.execute(
        tenant_query(Category, ctx.tenant_id).where(func.lower(Category.name) == name.lower())
    ).scalar_one_or_none()
    if category is None:
        category = Category(tenant_id=ctx.tenant_id, name=name)
        db.add(category)
        db.flush()
    return category


def _assert_unique_code(
    db: Session, tenant_id: uuid.UUID, *, sku: str | None, barcode: str | None,
    exclude_variant_id: uuid.UUID | None = None,
) -> None:
    """Codes are unique inside a business; two businesses may reuse the same one."""
    if sku:
        clash = db.execute(
            tenant_query(ProductVariant, tenant_id).where(ProductVariant.sku == sku)
        ).scalars().first()
        if clash and clash.id != exclude_variant_id:
            raise ConflictError(f"SKU '{sku}' is already used by another product")
    if barcode:
        clash = db.execute(
            tenant_query(ProductVariant, tenant_id).where(ProductVariant.barcode == barcode)
        ).scalars().first()
        if clash and clash.id != exclude_variant_id:
            raise ConflictError(f"Barcode '{barcode}' is already used by another product")


def create_product(db: Session, ctx: AuthContext, data: ProductInput) -> Product:
    ctx.require(Permission.PRODUCT_MANAGE)
    if not data.name or not data.name.strip():
        raise ValidationError("Product name is required")

    category = None
    if data.category_id is not None:
        category = get_tenant_object(
            db, Category, data.category_id, ctx.tenant_id, label="Category"
        )
    elif data.category_name:
        category = get_or_create_category(db, ctx, data.category_name)

    if data.sku:
        existing = db.execute(
            tenant_query(Product, ctx.tenant_id).where(Product.sku == data.sku)
        ).scalars().first()
        if existing is not None:
            raise ConflictError(f"SKU '{data.sku}' is already used by another product")

    product = Product(
        tenant_id=ctx.tenant_id,
        name=data.name.strip(),
        sku=data.sku,
        description=data.description,
        brand=data.brand,
        unit_of_measure=data.unit_of_measure or "pcs",
        category_id=category.id if category else None,
        preferred_supplier_id=data.preferred_supplier_id,
        track_stock=data.track_stock,
        is_published=data.is_published,
        online_description=data.online_description,
    )
    db.add(product)
    db.flush()

    variant_inputs = data.variants or [
        VariantInput(
            sku=data.sku,
            barcode=data.barcode,
            purchase_price=data.purchase_price,
            transport_cost=data.transport_cost,
            other_costs=data.other_costs,
            selling_price=data.selling_price,
            min_stock=data.min_stock,
            reorder_level=data.reorder_level,
            opening_stock=data.opening_stock,
        )
    ]

    for index, variant_input in enumerate(variant_inputs):
        _assert_unique_code(
            db, ctx.tenant_id, sku=variant_input.sku, barcode=variant_input.barcode
        )
        variant = ProductVariant(
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            name=variant_input.name,
            attributes_json=(
                json.dumps(variant_input.attributes) if variant_input.attributes else None
            ),
            sku=variant_input.sku,
            barcode=variant_input.barcode,
            is_default=index == 0,
            purchase_price=_money(variant_input.purchase_price),
            transport_cost=_money(variant_input.transport_cost),
            other_costs=_money(variant_input.other_costs),
            selling_price=_money(variant_input.selling_price),
            tax_rate=variant_input.tax_rate,
            max_discount_percent=variant_input.max_discount_percent,
            min_stock=variant_input.min_stock,
            reorder_level=variant_input.reorder_level,
            sort_order=index,
        )
        landed = variant.landed_cost
        if landed is not None:
            variant.average_cost = landed
        db.add(variant)
        db.flush()

        opening = variant_input.opening_stock
        if opening is not None and Decimal(opening) != 0 and product.track_stock:
            post_opening_stock(
                db, ctx, variant, Decimal(opening), data.branch_id, data.location_id
            )

    db.flush()
    db.refresh(product)
    return product


def post_opening_stock(
    db: Session,
    ctx: AuthContext,
    variant: ProductVariant,
    quantity: Decimal,
    branch_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
) -> None:
    """Opening stock is an auditable movement, never a silent balance (PRD 8.3)."""
    branch = resolve_branch(db, ctx, branch_id)
    location = resolve_location(db, ctx, branch, location_id)
    post_movement(
        db,
        ctx,
        StockPosting(
            variant_id=variant.id,
            location_id=location.id,
            quantity=Decimal(quantity),
            reason=MovementReason.OPENING,
            unit_cost=variant.cost_for_valuation,
            note="Opening stock",
            source_type="opening",
            source_id=variant.id,
            idempotency_key=f"opening:{variant.id}:{location.id}",
        ),
    )


def add_variant(
    db: Session, ctx: AuthContext, product_id: uuid.UUID, data: VariantInput
) -> ProductVariant:
    """Add a variant to an existing product, with its own codes, prices and stock."""
    ctx.require(Permission.PRODUCT_MANAGE)
    product = get_tenant_object(db, Product, product_id, ctx.tenant_id, label="Product")
    _assert_unique_code(db, ctx.tenant_id, sku=data.sku, barcode=data.barcode)
    variant = ProductVariant(
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        name=data.name,
        attributes_json=json.dumps(data.attributes) if data.attributes else None,
        sku=data.sku,
        barcode=data.barcode,
        is_default=False,
        purchase_price=_money(data.purchase_price),
        transport_cost=_money(data.transport_cost),
        other_costs=_money(data.other_costs),
        selling_price=_money(data.selling_price),
        tax_rate=data.tax_rate,
        max_discount_percent=data.max_discount_percent,
        min_stock=data.min_stock,
        reorder_level=data.reorder_level,
        sort_order=len(product.variants),
    )
    landed = variant.landed_cost
    if landed is not None:
        variant.average_cost = landed
    db.add(variant)
    db.flush()
    if data.opening_stock is not None and Decimal(data.opening_stock) != 0 and product.track_stock:
        post_opening_stock(db, ctx, variant, Decimal(data.opening_stock))
    db.refresh(product)
    return variant


def update_product(
    db: Session, ctx: AuthContext, product_id: uuid.UUID, changes: dict
) -> Product:
    ctx.require(Permission.PRODUCT_MANAGE)
    product = get_tenant_object(db, Product, product_id, ctx.tenant_id, label="Product")
    changes = dict(changes)

    if "category_name" in changes:
        category = get_or_create_category(db, ctx, changes.pop("category_name"))
        product.category_id = category.id if category else None

    # A simple product's code and barcode live on its one variant as well, so
    # the sales screen and the product list keep agreeing with each other.
    default = product.default_variant if not product.has_real_variants else None
    sku = changes.get("sku", product.sku) or None
    barcode = changes.pop("barcode", None)
    if "sku" in changes and sku:
        clash = db.execute(
            tenant_query(Product, ctx.tenant_id).where(
                Product.sku == sku, Product.id != product.id
            )
        ).scalars().first()
        if clash is not None:
            raise ConflictError(f"SKU '{sku}' is already used by another product")
    if default is not None and ("sku" in changes or barcode is not None):
        _assert_unique_code(
            db,
            ctx.tenant_id,
            sku=sku if "sku" in changes else None,
            barcode=barcode or None,
            exclude_variant_id=default.id,
        )
        if "sku" in changes:
            default.sku = sku
        if barcode is not None:
            default.barcode = barcode or None

    for field_name, value in changes.items():
        if field_name in {"id", "tenant_id", "created_at"}:
            continue
        if field_name == "sku":
            value = sku
        if hasattr(product, field_name):
            setattr(product, field_name, value)
    db.flush()
    return product


def update_variant(
    db: Session, ctx: AuthContext, variant_id: uuid.UUID, changes: dict
) -> ProductVariant:
    ctx.require(Permission.PRODUCT_MANAGE)
    variant = get_tenant_object(
        db, ProductVariant, variant_id, ctx.tenant_id, label="Product variant"
    )
    cost_fields = {"purchase_price", "transport_cost", "other_costs", "average_cost"}
    if cost_fields & set(changes):
        ctx.require(Permission.COST_VIEW)

    _assert_unique_code(
        db,
        ctx.tenant_id,
        sku=changes.get("sku"),
        barcode=changes.get("barcode"),
        exclude_variant_id=variant.id,
    )
    for field_name, value in changes.items():
        if field_name in {"id", "tenant_id", "product_id", "created_at"}:
            continue
        if field_name in MONEY_FIELDS:
            value = _money(value)
        if hasattr(variant, field_name):
            setattr(variant, field_name, value)

    if cost_fields & set(changes):
        landed = variant.landed_cost
        if landed is not None:
            variant.average_cost = landed
    db.flush()
    return variant


def search_products(
    db: Session,
    ctx: AuthContext,
    *,
    query: str | None = None,
    category_id: uuid.UUID | None = None,
    published_only: bool = False,
    include_inactive: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Product], int]:
    ctx.require(Permission.PRODUCT_VIEW)
    stmt = tenant_query(Product, ctx.tenant_id)
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    if published_only:
        stmt = stmt.where(Product.is_published.is_(True))
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
    if query:
        pattern = f"%{query.strip().lower()}%"
        variant_match = select(ProductVariant.product_id).where(
            ProductVariant.tenant_id == ctx.tenant_id,
            or_(
                func.lower(ProductVariant.sku).like(pattern),
                func.lower(ProductVariant.barcode).like(pattern),
            ),
        )
        stmt = stmt.where(
            or_(
                func.lower(Product.name).like(pattern),
                func.lower(Product.sku).like(pattern),
                func.lower(Product.brand).like(pattern),
                Product.id.in_(variant_match),
            )
        )

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    rows = db.execute(
        stmt.order_by(Product.name).limit(limit).offset(offset)
    ).scalars().all()
    return list(rows), total


def find_by_barcode(db: Session, ctx: AuthContext, barcode: str) -> ProductVariant:
    """Barcode lookup for the sales screen (PRD 10)."""
    ctx.require(Permission.PRODUCT_VIEW)
    variant = db.execute(
        tenant_query(ProductVariant, ctx.tenant_id).where(
            ProductVariant.barcode == barcode.strip(), ProductVariant.is_active.is_(True)
        )
    ).scalar_one_or_none()
    if variant is None:
        raise NotFoundError(f"No product found for barcode {barcode}")
    return variant


def set_published(
    db: Session, ctx: AuthContext, product_id: uuid.UUID, published: bool
) -> Product:
    """The online availability toggle (PRD 13)."""
    ctx.require(Permission.SHOP_MANAGE)
    product = get_tenant_object(db, Product, product_id, ctx.tenant_id, label="Product")
    product.is_published = published
    db.flush()
    return product


def stock_by_branch(
    db: Session, ctx: AuthContext, product_id: uuid.UUID
) -> list[dict]:
    """On-hand quantity for a product, per branch the user may see (PRD 9)."""
    ctx.require(Permission.STOCK_VIEW)
    visible = ctx.visible_branch_ids(db)
    rows = db.execute(
        select(
            StockBalance.branch_id,
            StockBalance.variant_id,
            func.sum(StockBalance.quantity).label("quantity"),
        )
        .where(
            StockBalance.tenant_id == ctx.tenant_id,
            StockBalance.product_id == product_id,
            StockBalance.branch_id.in_(visible),
        )
        .group_by(StockBalance.branch_id, StockBalance.variant_id)
    )
    return [
        {
            "branch_id": row.branch_id,
            "variant_id": row.variant_id,
            "quantity": Decimal(row.quantity or 0),
        }
        for row in rows
    ]
