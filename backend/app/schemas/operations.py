"""Schemas for stock, sales, purchasing, credit and commerce operations."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.credit import CreditKind, FollowUpKind
from app.models.inventory import MovementReason
from app.models.sales import PaymentMethod
from app.schemas.common import Schema

# --------------------------------------------------------------------------- #
# Stock
# --------------------------------------------------------------------------- #


class StockAdjustIn(BaseModel):
    variant_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal = Field(description="Signed: negative removes stock")
    reason: MovementReason
    note: str = Field(min_length=3, max_length=255, description="Required for the audit trail")

    @model_validator(mode="after")
    def _non_zero(self):
        if self.quantity == 0:
            raise ValueError("Quantity cannot be zero")
        return self


class MovementOut(Schema):
    id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID
    branch_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal
    balance_after: Decimal
    reason: MovementReason
    note: str | None = None
    occurred_at: datetime
    source_type: str | None = None
    source_id: uuid.UUID | None = None


class StockLevelOut(BaseModel):
    product_id: uuid.UUID
    variant_id: uuid.UUID
    name: str
    branch_id: uuid.UUID
    branch_name: str | None = None
    quantity: Decimal
    min_stock: Decimal | None = None
    reorder_level: Decimal | None = None
    status: str


class TransferLineIn(BaseModel):
    variant_id: uuid.UUID
    quantity: Decimal = Field(gt=0)


class TransferIn(BaseModel):
    from_location_id: uuid.UUID
    to_location_id: uuid.UUID
    lines: list[TransferLineIn] = Field(min_length=1)
    note: str | None = Field(None, max_length=2000)


class TransferReceiveIn(BaseModel):
    """Received quantities per line; omitted lines default to the amount sent."""

    received: dict[uuid.UUID, Decimal] = {}


class TransferLineOut(Schema):
    id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID
    quantity_sent: Decimal
    quantity_received: Decimal | None = None
    note: str | None = None


class TransferOut(Schema):
    id: uuid.UUID
    reference: str
    from_location_id: uuid.UUID
    to_location_id: uuid.UUID
    status: str
    dispatched_at: datetime | None = None
    received_at: datetime | None = None
    note: str | None = None
    lines: list[TransferLineOut] = []


class CountStartIn(BaseModel):
    location_id: uuid.UUID
    note: str | None = Field(None, max_length=2000)


class CountLineIn(BaseModel):
    variant_id: uuid.UUID
    counted_quantity: Decimal = Field(ge=0)
    reason: str | None = Field(None, max_length=120)
    note: str | None = Field(None, max_length=255)


class CountLineOut(Schema):
    id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID
    expected_quantity: Decimal
    counted_quantity: Decimal | None = None
    variance: Decimal | None = None
    reason: str | None = None


class CountOut(Schema):
    id: uuid.UUID
    reference: str
    location_id: uuid.UUID
    branch_id: uuid.UUID
    status: str
    note: str | None = None
    posted_at: datetime | None = None
    lines: list[CountLineOut] = []


# --------------------------------------------------------------------------- #
# Sales
# --------------------------------------------------------------------------- #


class SaleLineIn(BaseModel):
    variant_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal | None = Field(None, ge=0)
    discount_amount: Decimal | None = Field(None, ge=0)
    discount_percent: Decimal | None = Field(None, ge=0, le=1)
    tax_rate: Decimal | None = Field(None, ge=0, le=1)

    @model_validator(mode="after")
    def _one_discount(self):
        if self.discount_amount is not None and self.discount_percent is not None:
            raise ValueError("Give a discount amount or a percentage, not both")
        return self


class PaymentIn(BaseModel):
    method: PaymentMethod
    amount: Decimal = Field(gt=0)
    reference: str | None = Field(None, max_length=120)
    note: str | None = Field(None, max_length=2000)


class SaleIn(BaseModel):
    lines: list[SaleLineIn] = Field(min_length=1)
    payments: list[PaymentIn] = []
    branch_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    note: str | None = Field(None, max_length=2000)
    #: Credit terms, used only when the payments do not cover the total.
    due_date: date | None = None
    due_date_preset: str | None = Field(
        None, description="today | tomorrow | 7_days | 15_days | 30_days"
    )
    credit_note: str | None = Field(None, max_length=2000)
    override_credit_limit: bool = False
    idempotency_key: str | None = Field(None, max_length=80)


class SaleLineOut(Schema):
    id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    line_total: Decimal
    unit_cost: Decimal | None = None


class PaymentOut(Schema):
    id: uuid.UUID
    method: PaymentMethod
    amount: Decimal
    paid_at: datetime
    reference: str | None = None
    note: str | None = None
    is_reversed: bool = False
    reversal_reason: str | None = None


class SaleOut(Schema):
    id: uuid.UUID
    number: str
    branch_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    salesperson_id: uuid.UUID | None = None
    status: str
    sold_at: datetime
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total_amount: Decimal
    currency: str
    amount_paid: Decimal
    balance_due: Decimal
    note: str | None = None
    lines: list[SaleLineOut] = []
    payments: list[PaymentOut] = []
    cost_total: Decimal | None = None
    gross_profit: Decimal | None = None


class SaleResponse(BaseModel):
    sale: SaleOut
    credit_transaction_id: uuid.UUID | None = None
    warnings: list[str] = []


class VoidSaleIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


# --------------------------------------------------------------------------- #
# Purchasing
# --------------------------------------------------------------------------- #


class PurchaseLineIn(BaseModel):
    variant_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)


class PurchaseIn(BaseModel):
    lines: list[PurchaseLineIn] = Field(min_length=1)
    supplier_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    transport_cost: Decimal = Field(Decimal("0"), ge=0)
    other_costs: Decimal = Field(Decimal("0"), ge=0)
    cost_allocation_method: str = Field("by_value", pattern="^(by_value|by_quantity)$")
    amount_paid: Decimal = Field(Decimal("0"), ge=0)
    payment_method: PaymentMethod = PaymentMethod.CASH
    supplier_invoice_ref: str | None = Field(None, max_length=255)
    note: str | None = Field(None, max_length=2000)
    due_date: date | None = None
    due_date_preset: str | None = Field(None, max_length=24)
    credit_note: str | None = Field(None, max_length=2000)
    reprice_from_cost: bool = False
    idempotency_key: str | None = Field(None, max_length=80)


class PurchaseLineOut(Schema):
    id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID
    description: str
    quantity: Decimal
    unit_cost: Decimal
    allocated_cost: Decimal
    line_total: Decimal


class PurchaseOut(Schema):
    id: uuid.UUID
    number: str
    supplier_id: uuid.UUID | None = None
    branch_id: uuid.UUID
    status: str
    received_at: datetime
    goods_total: Decimal
    transport_cost: Decimal
    other_costs: Decimal
    total_amount: Decimal
    amount_paid: Decimal = Decimal("0")
    balance_due: Decimal = Decimal("0")
    currency: str
    cost_allocation_method: str
    supplier_invoice_ref: str | None = None
    note: str | None = None
    lines: list[PurchaseLineOut] = []


class PurchaseResponse(BaseModel):
    purchase: PurchaseOut
    credit_transaction_id: uuid.UUID | None = None
    repriced_variant_ids: list[uuid.UUID] = []


# --------------------------------------------------------------------------- #
# Contacts
# --------------------------------------------------------------------------- #


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(None, max_length=32)
    telegram_username: str | None = Field(None, max_length=120)
    email: EmailStr | None = None
    address: str | None = Field(None, max_length=255)
    company: str | None = Field(None, max_length=120)
    notes: str | None = Field(None, max_length=2000)
    credit_limit: Decimal | None = Field(None, ge=0)
    credit_limit_behaviour: str | None = Field(
        None, pattern="^(warn|require_approval|block)$"
    )


class CustomerOut(Schema):
    id: uuid.UUID
    name: str
    phone: str | None = None
    telegram_username: str | None = None
    email: str | None = None
    address: str | None = None
    company: str | None = None
    notes: str | None = None
    credit_limit: Decimal | None = None
    credit_limit_behaviour: str | None = None
    is_active: bool = True
    outstanding_balance: Decimal | None = None


class SupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(None, max_length=32)
    email: EmailStr | None = None
    telegram_username: str | None = Field(None, max_length=120)
    address: str | None = Field(None, max_length=255)
    contact_person: str | None = Field(None, max_length=120)
    tin: str | None = Field(None, max_length=64)
    notes: str | None = Field(None, max_length=2000)


class SupplierOut(Schema):
    id: uuid.UUID
    name: str
    phone: str | None = None
    email: str | None = None
    contact_person: str | None = None
    address: str | None = None
    tin: str | None = None
    notes: str | None = None
    is_active: bool = True
    outstanding_balance: Decimal | None = None


# --------------------------------------------------------------------------- #
# Credit
# --------------------------------------------------------------------------- #


class CreditTransactionOut(Schema):
    id: uuid.UUID
    reference: str
    kind: CreditKind
    status: str
    cancel_reason: str | None = None
    branch_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    sale_id: uuid.UUID | None = None
    purchase_id: uuid.UUID | None = None
    original_amount: Decimal
    amount_paid: Decimal
    balance: Decimal
    currency: str
    issued_on: date
    due_date: date | None = None
    agreement_note: str | None = None
    counterparty_name: str | None = None
    is_overdue: bool = False
    days_overdue: int | None = None


class CreditPaymentIn(BaseModel):
    amount: Decimal = Field(gt=0)
    method: PaymentMethod
    paid_on: date | None = None
    reference: str | None = Field(None, max_length=120)
    note: str | None = Field(None, max_length=2000)
    allow_overpayment: bool = False
    idempotency_key: str | None = Field(None, max_length=80)


class DueDateChangeIn(BaseModel):
    due_date: date | None = None
    due_date_preset: str | None = Field(None, max_length=24)
    note: str | None = Field(None, max_length=2000)


class CancelCreditIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


class FollowUpIn(BaseModel):
    kind: FollowUpKind
    note: str | None = Field(None, max_length=2000)
    promised_amount: Decimal | None = Field(None, ge=0)
    promised_date: date | None = None
    outcome: str | None = Field(None, max_length=120)


class FollowUpOut(Schema):
    id: uuid.UUID
    kind: FollowUpKind
    occurred_at: datetime
    note: str | None = None
    promised_amount: Decimal | None = None
    promised_date: date | None = None
    outcome: str | None = None


class ReversePaymentIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


# --------------------------------------------------------------------------- #
# Commerce
# --------------------------------------------------------------------------- #


class StoreSettingsIn(BaseModel):
    display_name: str | None = Field(None, max_length=120)
    tagline: str | None = None
    about: str | None = None
    contact_phone: str | None = Field(None, max_length=32)
    contact_email: EmailStr | None = None
    telegram_username: str | None = Field(None, max_length=120)
    address: str | None = Field(None, max_length=255)
    is_published: bool | None = None
    show_prices: bool | None = None


class StoreOut(Schema):
    id: uuid.UUID
    slug: str
    display_name: str
    tagline: str | None = None
    about: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    telegram_username: str | None = None
    address: str | None = None
    is_published: bool
    show_prices: bool
    public_url: str | None = None


class EnquiryItemIn(BaseModel):
    product_id: uuid.UUID | None = None
    name: str | None = None
    quantity: Decimal = Field(Decimal("1"), gt=0)


class EnquiryIn(BaseModel):
    contact_name: str = Field(min_length=2, max_length=120)
    contact_phone: str = Field(min_length=5, max_length=32)
    contact_email: EmailStr | None = None
    company: str | None = Field(None, max_length=120)
    delivery_location: str | None = Field(None, max_length=255)
    message: str | None = Field(None, max_length=2000)
    items: list[EnquiryItemIn] = []
    wants_proforma: bool = False


class EnquiryOut(Schema):
    id: uuid.UUID
    reference: str
    status: str
    contact_name: str
    contact_phone: str
    contact_email: str | None = None
    company: str | None = None
    delivery_location: str | None = None
    message: str | None = None
    wants_proforma: bool
    created_at: datetime
    #: Requested items as the customer submitted them.
    items: list[dict] = []


class QuotationLineIn(BaseModel):
    variant_id: uuid.UUID | None = None
    description: str | None = None
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal | None = Field(None, ge=0)
    discount_amount: Decimal | None = Field(None, ge=0)
    tax_rate: Decimal | None = Field(None, ge=0, le=1)

    @model_validator(mode="after")
    def _identified(self):
        if self.variant_id is None and not self.description:
            raise ValueError("Each line needs a product or a description")
        return self


class QuotationIn(BaseModel):
    customer_name: str = Field(min_length=2, max_length=120)
    lines: list[QuotationLineIn] = Field(min_length=1)
    customer_id: uuid.UUID | None = None
    customer_phone: str | None = Field(None, max_length=32)
    customer_email: EmailStr | None = None
    customer_company: str | None = Field(None, max_length=120)
    delivery_location: str | None = Field(None, max_length=255)
    delivery_charge: Decimal = Field(Decimal("0"), ge=0)
    branch_id: uuid.UUID | None = None
    enquiry_id: uuid.UUID | None = None
    valid_until: date | None = None
    validity_days: int | None = Field(None, ge=1, le=365)
    terms: str | None = Field(None, max_length=4000)
    note: str | None = Field(None, max_length=2000)


class QuotationLineOut(Schema):
    id: uuid.UUID
    product_id: uuid.UUID | None = None
    variant_id: uuid.UUID | None = None
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    line_total: Decimal


class QuotationOut(Schema):
    id: uuid.UUID
    number: str
    status: str
    customer_id: uuid.UUID | None = None
    customer_name: str
    customer_phone: str | None = None
    customer_email: str | None = None
    customer_company: str | None = None
    delivery_location: str | None = None
    issued_on: date
    valid_until: date | None = None
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    delivery_charge: Decimal
    total_amount: Decimal
    currency: str
    terms: str | None = None
    note: str | None = None
    lines: list[QuotationLineOut] = []
    share: dict | None = None
    converted_sale_id: uuid.UUID | None = None


class ConvertQuotationIn(BaseModel):
    branch_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    payments: list[PaymentIn] = []
    due_date: date | None = None
