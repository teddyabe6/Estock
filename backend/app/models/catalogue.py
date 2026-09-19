"""Products, categories, variants and pricing rules.

Every product owns at least one variant.  Simple products get an implicit
default variant so the stock, sales and pricing code has exactly one shape to
handle, while the API still lets a user create a product from a name alone
(PRD 8.1).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import GUID, Base, Money, Percent, Quantity
from app.models.base import (
    CodeText,
    ShortText,
    TenantScoped,
    Timestamped,
    UUIDPrimaryKey,
    enum_column,
)


class PricingBasis(StrEnum):
    """What a target-profit percentage means.

    The UI may say "target profit", but the system always stores which of the
    two calculations applies (PRD 8.2).
    """

    #: price = cost * (1 + pct)
    MARKUP = "markup"
    #: price = cost / (1 - pct)
    MARGIN = "margin"


class PricingScope(StrEnum):
    BUSINESS = "business"
    CATEGORY = "category"
    PRODUCT = "product"


class Category(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_categories_tenant_name"),)

    name: Mapped[str] = mapped_column(ShortText, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("categories.id", ondelete="SET NULL")
    )
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    products: Mapped[list[Product]] = relationship(back_populates="category")


class Product(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """Catalogue item.  Only ``name`` is required (PRD 8.1)."""

    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_tenant_name", "tenant_id", "name"),
        Index("uq_products_tenant_sku", "tenant_id", "sku", unique=True),
    )

    name: Mapped[str] = mapped_column(ShortText, nullable=False)
    sku: Mapped[str | None] = mapped_column(CodeText)
    description: Mapped[str | None] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(ShortText)
    unit_of_measure: Mapped[str] = mapped_column(String(24), default="pcs", nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    preferred_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("suppliers.id", ondelete="SET NULL")
    )
    image_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("file_assets.id", ondelete="SET NULL")
    )

    # Online publication (PRD 13) — a simple availability toggle.
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    online_description: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: Services and non-stocked items skip inventory checks.
    track_stock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    category: Mapped[Category | None] = relationship(back_populates="products")
    variants: Mapped[list[ProductVariant]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def default_variant(self) -> ProductVariant:
        for variant in self.variants:
            if variant.is_default:
                return variant
        return self.variants[0]

    @property
    def has_real_variants(self) -> bool:
        return len(self.variants) > 1


class ProductVariant(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """A sellable, stockable unit.  Costs and prices live here."""

    __tablename__ = "product_variants"
    __table_args__ = (
        Index("uq_product_variants_tenant_barcode", "tenant_id", "barcode", unique=True),
        Index("uq_product_variants_tenant_sku", "tenant_id", "sku", unique=True),
        Index("ix_product_variants_product", "product_id"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(
        ShortText, doc="Variant label such as 'Red / Large'; null on the default variant"
    )
    attributes_json: Mapped[str | None] = mapped_column(
        Text, doc='Variant attributes, e.g. {"colour": "red", "size": "L"}'
    )
    sku: Mapped[str | None] = mapped_column(CodeText)
    barcode: Mapped[str | None] = mapped_column(CodeText)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Purchase/cost inputs.  Landed cost is derived from these (PRD 8.2).
    purchase_price: Mapped[Decimal | None] = mapped_column(Money)
    transport_cost: Mapped[Decimal | None] = mapped_column(Money)
    other_costs: Mapped[Decimal | None] = mapped_column(Money)
    #: Weighted average landed cost, maintained by receiving (PRD 8.2, 9).
    average_cost: Mapped[Decimal | None] = mapped_column(Money)

    # Sales fields
    selling_price: Mapped[Decimal | None] = mapped_column(Money)
    tax_rate: Mapped[Decimal | None] = mapped_column(Percent)
    max_discount_percent: Mapped[Decimal | None] = mapped_column(Percent)

    # Stock control thresholds (PRD 9)
    min_stock: Mapped[Decimal | None] = mapped_column(Quantity)
    reorder_level: Mapped[Decimal | None] = mapped_column(Quantity)

    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    product: Mapped[Product] = relationship(back_populates="variants")

    @property
    def landed_cost(self) -> Decimal | None:
        """Purchase price plus directly attributed additional costs (PRD 8.2)."""
        if self.purchase_price is None:
            return None
        return (
            Decimal(self.purchase_price)
            + Decimal(self.transport_cost or 0)
            + Decimal(self.other_costs or 0)
        )

    @property
    def cost_for_valuation(self) -> Decimal | None:
        """Average cost where receiving has established one, else landed cost."""
        if self.average_cost is not None:
            return Decimal(self.average_cost)
        return self.landed_cost

    @property
    def display_name(self) -> str:
        base = self.product.name if self.product else ""
        return f"{base} — {self.name}" if self.name else base


class PricingRule(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """Target-profit rule applied at business, category or product level.

    Resolution order is business default → category rule → product override
    (PRD 8.2).
    """

    __tablename__ = "pricing_rules"
    __table_args__ = (
        Index("ix_pricing_rules_tenant_scope", "tenant_id", "scope"),
        UniqueConstraint(
            "tenant_id", "scope", "category_id", "product_id", name="uq_pricing_rules_scope_target"
        ),
    )

    scope: Mapped[PricingScope] = mapped_column(enum_column(PricingScope), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("categories.id", ondelete="CASCADE")
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("products.id", ondelete="CASCADE")
    )
    basis: Mapped[PricingBasis] = mapped_column(
        enum_column(PricingBasis), default=PricingBasis.MARKUP, nullable=False
    )
    #: Fractional rate: 0.25 means 25%.
    rate: Mapped[Decimal] = mapped_column(Percent, nullable=False)
    #: Round suggested prices to this increment, e.g. 0.25 or 1.00.
    rounding_increment: Mapped[Decimal | None] = mapped_column(Money)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
