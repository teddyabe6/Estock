"""Product, variant, category and pricing schemas."""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.catalogue import PricingBasis, PricingScope
from app.schemas.common import Schema


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None
    description: str | None = None


class CategoryOut(Schema):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None
    is_active: bool = True


class VariantIn(BaseModel):
    name: str | None = Field(None, max_length=120)
    attributes: dict[str, str] | None = None
    sku: str | None = Field(None, max_length=64)
    barcode: str | None = Field(None, max_length=64)
    purchase_price: Decimal | None = Field(None, ge=0)
    transport_cost: Decimal | None = Field(None, ge=0)
    other_costs: Decimal | None = Field(None, ge=0)
    selling_price: Decimal | None = Field(None, ge=0)
    tax_rate: Decimal | None = Field(None, ge=0, le=1)
    max_discount_percent: Decimal | None = Field(None, ge=0, le=1)
    min_stock: Decimal | None = Field(None, ge=0)
    reorder_level: Decimal | None = Field(None, ge=0)
    opening_stock: Decimal | None = None


class ProductIn(BaseModel):
    """Only ``name`` is required; everything else is progressive disclosure."""

    name: str = Field(min_length=1, max_length=120)
    sku: str | None = Field(None, max_length=64)
    barcode: str | None = Field(None, max_length=64)
    description: str | None = None
    brand: str | None = Field(None, max_length=120)
    unit_of_measure: str = "pcs"
    category_id: uuid.UUID | None = None
    category_name: str | None = Field(None, max_length=120)
    preferred_supplier_id: uuid.UUID | None = None
    track_stock: bool = True
    is_published: bool = False
    online_description: str | None = None

    purchase_price: Decimal | None = Field(None, ge=0)
    transport_cost: Decimal | None = Field(None, ge=0)
    other_costs: Decimal | None = Field(None, ge=0)
    selling_price: Decimal | None = Field(None, ge=0)
    opening_stock: Decimal | None = None
    min_stock: Decimal | None = Field(None, ge=0)
    reorder_level: Decimal | None = Field(None, ge=0)
    branch_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None

    variants: list[VariantIn] = []

    @model_validator(mode="after")
    def _no_conflicting_category(self):
        if self.category_id is not None and self.category_name:
            raise ValueError("Give a category id or a category name, not both")
        return self


class ProductUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    sku: str | None = None
    description: str | None = None
    brand: str | None = None
    unit_of_measure: str | None = None
    category_id: uuid.UUID | None = None
    category_name: str | None = None
    preferred_supplier_id: uuid.UUID | None = None
    is_active: bool | None = None
    is_published: bool | None = None
    online_description: str | None = None
    track_stock: bool | None = None


class VariantUpdate(BaseModel):
    name: str | None = None
    sku: str | None = None
    barcode: str | None = None
    purchase_price: Decimal | None = Field(None, ge=0)
    transport_cost: Decimal | None = Field(None, ge=0)
    other_costs: Decimal | None = Field(None, ge=0)
    selling_price: Decimal | None = Field(None, ge=0)
    tax_rate: Decimal | None = Field(None, ge=0, le=1)
    max_discount_percent: Decimal | None = Field(None, ge=0, le=1)
    min_stock: Decimal | None = Field(None, ge=0)
    reorder_level: Decimal | None = Field(None, ge=0)
    is_active: bool | None = None


class VariantOut(BaseModel):
    id: uuid.UUID
    name: str | None = None
    sku: str | None = None
    barcode: str | None = None
    is_default: bool = True
    selling_price: Decimal | None = None
    tax_rate: Decimal | None = None
    min_stock: Decimal | None = None
    reorder_level: Decimal | None = None
    quantity_on_hand: Decimal | None = None
    # Cost fields are present only for users holding cost:view (PRD 8.2).
    purchase_price: Decimal | None = None
    transport_cost: Decimal | None = None
    other_costs: Decimal | None = None
    landed_cost: Decimal | None = None
    average_cost: Decimal | None = None


class ProductOut(BaseModel):
    id: uuid.UUID
    name: str
    sku: str | None = None
    description: str | None = None
    brand: str | None = None
    unit_of_measure: str = "pcs"
    category_id: uuid.UUID | None = None
    category_name: str | None = None
    is_active: bool = True
    is_published: bool = False
    track_stock: bool = True
    variants: list[VariantOut] = []
    quantity_on_hand: Decimal | None = None
    stock_status: str | None = None


class PricingRuleIn(BaseModel):
    scope: PricingScope
    basis: PricingBasis = PricingBasis.MARKUP
    #: Fractional rate: 0.25 means 25%.
    rate: Decimal = Field(ge=0, lt=10)
    category_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    rounding_increment: Decimal | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _scope_target(self):
        if self.scope == PricingScope.CATEGORY and self.category_id is None:
            raise ValueError("A category rule needs a category")
        if self.scope == PricingScope.PRODUCT and self.product_id is None:
            raise ValueError("A product rule needs a product")
        if self.basis == PricingBasis.MARGIN and self.rate >= 1:
            raise ValueError("Gross margin must be below 100%")
        return self


class PricingRuleOut(Schema):
    id: uuid.UUID
    scope: PricingScope
    basis: PricingBasis
    rate: Decimal
    category_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    rounding_increment: Decimal | None = None
    is_active: bool = True


class PriceSuggestion(BaseModel):
    """Always shown before a price is saved (PRD 8.2)."""

    cost: Decimal
    basis: PricingBasis
    rate: Decimal
    suggested_price: Decimal
    applied_scope: PricingScope | None = None
    explanation: str
