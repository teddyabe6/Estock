"""Products, categories and pricing rules (PRD 8)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Query, status

from app.api.v1.serializers import product_out, stock_totals, variant_out
from app.core.audit import AuditAction, record_audit
from app.core.deps import Ctx, DbSession
from app.core.errors import NotFoundError
from app.core.permissions import Permission
from app.core.tenancy import get_tenant_object, tenant_query
from app.models.catalogue import Category, PricingRule, Product, ProductVariant
from app.schemas.catalogue import (
    CategoryIn,
    CategoryOut,
    PriceSuggestion,
    PricingRuleIn,
    PricingRuleOut,
    ProductIn,
    ProductOut,
    ProductUpdate,
    VariantIn,
    VariantOut,
    VariantUpdate,
)
from app.schemas.common import Page
from app.services.catalogue import (
    ProductInput,
    VariantInput,
    create_product,
    find_by_barcode,
    search_products,
    set_published,
    stock_by_branch,
    update_product,
    update_variant,
)
from app.services.catalogue import (
    add_variant as add_variant_to_product,
)
from app.services.pricing import resolve_pricing_rule, suggested_price

router = APIRouter(tags=["catalogue"])


@router.get("/products", response_model=Page[ProductOut])
def list_products(
    ctx: Ctx,
    db: DbSession,
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    published_only: bool = False,
    include_inactive: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[ProductOut]:
    products, total = search_products(
        db,
        ctx,
        query=q,
        category_id=category_id,
        published_only=published_only,
        include_inactive=include_inactive,
        limit=limit,
        offset=offset,
    )
    stock = (
        stock_totals(db, ctx, [p.id for p in products])
        if ctx.has(Permission.STOCK_VIEW)
        else {}
    )
    return Page(
        items=[product_out(ctx, p, stock) for p in products],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def add_product(payload: ProductIn, ctx: Ctx, db: DbSession) -> ProductOut:
    """Add a product.  Name is the only required field (PRD A1)."""
    data = ProductInput(
        name=payload.name,
        sku=payload.sku,
        barcode=payload.barcode,
        description=payload.description,
        brand=payload.brand,
        unit_of_measure=payload.unit_of_measure,
        category_id=payload.category_id,
        category_name=payload.category_name,
        preferred_supplier_id=payload.preferred_supplier_id,
        track_stock=payload.track_stock,
        is_published=payload.is_published,
        online_description=payload.online_description,
        purchase_price=payload.purchase_price,
        transport_cost=payload.transport_cost,
        other_costs=payload.other_costs,
        selling_price=payload.selling_price,
        opening_stock=payload.opening_stock,
        min_stock=payload.min_stock,
        reorder_level=payload.reorder_level,
        branch_id=payload.branch_id,
        location_id=payload.location_id,
        variants=[
            VariantInput(
                name=v.name,
                attributes=v.attributes,
                sku=v.sku,
                barcode=v.barcode,
                purchase_price=v.purchase_price,
                transport_cost=v.transport_cost,
                other_costs=v.other_costs,
                selling_price=v.selling_price,
                tax_rate=v.tax_rate,
                max_discount_percent=v.max_discount_percent,
                min_stock=v.min_stock,
                reorder_level=v.reorder_level,
                opening_stock=v.opening_stock,
            )
            for v in payload.variants
        ],
    )
    product = create_product(db, ctx, data)
    return product_out(ctx, product, stock_totals(db, ctx, [product.id]))


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: uuid.UUID, ctx: Ctx, db: DbSession) -> ProductOut:
    ctx.require(Permission.PRODUCT_VIEW)
    product = get_tenant_object(db, Product, product_id, ctx.tenant_id, label="Product")
    return product_out(ctx, product, stock_totals(db, ctx, [product.id]))


@router.patch("/products/{product_id}", response_model=ProductOut)
def edit_product(
    product_id: uuid.UUID, payload: ProductUpdate, ctx: Ctx, db: DbSession
) -> ProductOut:
    product = update_product(
        db, ctx, product_id, payload.model_dump(exclude_unset=True)
    )
    return product_out(ctx, product, stock_totals(db, ctx, [product.id]))


@router.post("/products/{product_id}/variants", response_model=VariantOut, status_code=201)
def add_variant(
    product_id: uuid.UUID, payload: VariantIn, ctx: Ctx, db: DbSession
) -> VariantOut:
    variant = add_variant_to_product(
        db,
        ctx,
        product_id,
        VariantInput(
            name=payload.name,
            attributes=payload.attributes,
            sku=payload.sku,
            barcode=payload.barcode,
            purchase_price=payload.purchase_price,
            transport_cost=payload.transport_cost,
            other_costs=payload.other_costs,
            selling_price=payload.selling_price,
            tax_rate=payload.tax_rate,
            max_discount_percent=payload.max_discount_percent,
            min_stock=payload.min_stock,
            reorder_level=payload.reorder_level,
            opening_stock=payload.opening_stock,
        ),
    )
    stock = stock_totals(db, ctx, [variant.product_id])
    return variant_out(ctx, variant, stock.get(variant.id))


@router.patch("/variants/{variant_id}", response_model=VariantOut)
def edit_variant(
    variant_id: uuid.UUID, payload: VariantUpdate, ctx: Ctx, db: DbSession
) -> VariantOut:
    variant = update_variant(
        db, ctx, variant_id, payload.model_dump(exclude_unset=True)
    )
    return variant_out(ctx, variant)


@router.get("/products/{product_id}/stock")
def product_stock(product_id: uuid.UUID, ctx: Ctx, db: DbSession) -> list[dict]:
    get_tenant_object(db, Product, product_id, ctx.tenant_id, label="Product")
    return [
        {
            "branch_id": str(row["branch_id"]),
            "variant_id": str(row["variant_id"]),
            "quantity": str(row["quantity"]),
        }
        for row in stock_by_branch(db, ctx, product_id)
    ]


@router.post("/products/{product_id}/publish", response_model=ProductOut)
def publish_product(
    product_id: uuid.UUID, ctx: Ctx, db: DbSession, published: bool = True
) -> ProductOut:
    """The online availability toggle (PRD 13)."""
    product = set_published(db, ctx, product_id, published)
    return product_out(ctx, product, stock_totals(db, ctx, [product.id]))


@router.get("/products/lookup/barcode/{barcode}", response_model=VariantOut)
def lookup_barcode(barcode: str, ctx: Ctx, db: DbSession) -> VariantOut:
    """Barcode scan on the sales screen (PRD 10)."""
    variant = find_by_barcode(db, ctx, barcode)
    stock = stock_totals(db, ctx, [variant.product_id])
    return variant_out(ctx, variant, stock.get(variant.id))


# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(ctx: Ctx, db: DbSession) -> list[CategoryOut]:
    ctx.require(Permission.PRODUCT_VIEW)
    rows = db.execute(
        tenant_query(Category, ctx.tenant_id).order_by(Category.name)
    ).scalars()
    return [CategoryOut.model_validate(c) for c in rows]


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def add_category(payload: CategoryIn, ctx: Ctx, db: DbSession) -> CategoryOut:
    ctx.require(Permission.PRODUCT_MANAGE)
    from app.services.catalogue import get_or_create_category

    category = get_or_create_category(db, ctx, payload.name)
    if payload.parent_id is not None:
        get_tenant_object(db, Category, payload.parent_id, ctx.tenant_id, label="Category")
        category.parent_id = payload.parent_id
    if payload.description:
        category.description = payload.description
    db.flush()
    return CategoryOut.model_validate(category)


# --------------------------------------------------------------------------- #
# Pricing
# --------------------------------------------------------------------------- #


@router.get("/pricing-rules", response_model=list[PricingRuleOut])
def list_pricing_rules(ctx: Ctx, db: DbSession) -> list[PricingRuleOut]:
    ctx.require(Permission.PRICING_MANAGE)
    rows = db.execute(tenant_query(PricingRule, ctx.tenant_id)).scalars()
    return [PricingRuleOut.model_validate(rule) for rule in rows]


@router.put("/pricing-rules", response_model=PricingRuleOut)
def upsert_pricing_rule(payload: PricingRuleIn, ctx: Ctx, db: DbSession) -> PricingRuleOut:
    """Set the rule for a scope.  One rule per business/category/product (PRD 8.2)."""
    ctx.require(Permission.PRICING_MANAGE)
    if payload.category_id:
        get_tenant_object(db, Category, payload.category_id, ctx.tenant_id, label="Category")
    if payload.product_id:
        get_tenant_object(db, Product, payload.product_id, ctx.tenant_id, label="Product")

    rule = db.execute(
        tenant_query(PricingRule, ctx.tenant_id).where(
            PricingRule.scope == payload.scope,
            PricingRule.category_id == payload.category_id,
            PricingRule.product_id == payload.product_id,
        )
    ).scalar_one_or_none()

    if rule is None:
        rule = PricingRule(
            tenant_id=ctx.tenant_id,
            scope=payload.scope,
            category_id=payload.category_id,
            product_id=payload.product_id,
        )
        db.add(rule)
    rule.basis = payload.basis
    rule.rate = payload.rate
    rule.rounding_increment = payload.rounding_increment
    rule.is_active = True
    db.flush()

    record_audit(
        db,
        action=AuditAction.PRICING_RULE_CHANGED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="pricing_rule",
        entity_id=rule.id,
        summary=f"{payload.scope} rule: {payload.basis} {payload.rate}",
    )
    db.flush()
    return PricingRuleOut.model_validate(rule)


@router.get("/pricing/suggest", response_model=PriceSuggestion)
def suggest(
    ctx: Ctx,
    db: DbSession,
    cost: Decimal = Query(gt=0),
    variant_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
) -> PriceSuggestion:
    """Show the suggested price and say which calculation produced it (PRD 8.2)."""
    ctx.require(Permission.PRODUCT_VIEW, Permission.COST_VIEW)
    product = None
    if variant_id is not None:
        variant = get_tenant_object(
            db, ProductVariant, variant_id, ctx.tenant_id, label="Product"
        )
        product = variant.product
    rule = resolve_pricing_rule(db, ctx.tenant_id, product=product, category_id=category_id)
    if rule is None:
        raise NotFoundError(
            "No pricing rule is set yet. Add a default rule in settings first."
        )
    price = suggested_price(cost, rule.basis, rule.rate, rule.rounding_increment)
    basis_text = (
        f"{rule.rate:.0%} markup on cost"
        if rule.basis == "markup"
        else f"{rule.rate:.0%} gross margin on the selling price"
    )
    return PriceSuggestion(
        cost=Decimal(cost),
        basis=rule.basis,
        rate=rule.rate,
        suggested_price=price,
        applied_scope=rule.scope,
        explanation=f"{basis_text}, from the {rule.scope} rule.",
    )
