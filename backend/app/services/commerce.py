"""Storefront, enquiries and proformas (PRD 13, 14).

Publishing uses the same catalogue and stock as physical sales.  An enquiry or
a proforma never reserves or reduces stock; only an explicit conversion to a
sale does.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, record_audit
from app.core.config import settings
from app.core.db import utcnow
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.permissions import Permission
from app.core.security import generate_share_token
from app.core.tenancy import AuthContext, get_tenant_object, tenant_query
from app.models.catalogue import Product, ProductVariant
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
from app.services.numbering import next_number
from app.services.pricing import quantize_money

ZERO = Decimal("0.00")
DEFAULT_VALIDITY_DAYS = 14


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
    variants: list[dict] = field(default_factory=list)


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


def list_public_products(
    db: Session,
    store: OnlineStore,
    tenant: Tenant,
    *,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PublicProduct], int]:
    """Published products, with availability from the one shared stock source."""
    stmt = tenant_query(Product, store.tenant_id).where(
        Product.is_published.is_(True), Product.is_active.is_(True)
    )
    if query:
        pattern = f"%{query.strip().lower()}%"
        stmt = stmt.where(func.lower(Product.name).like(pattern))

    products = list(db.execute(stmt.order_by(Product.name)).scalars())
    stock = _stock_map(db, store.tenant_id, [product.id for product in products])

    results: list[PublicProduct] = []
    for product in products:
        in_stock = stock.get(product.id, ZERO) > 0
        if tenant.hide_out_of_stock_online and not in_stock and product.track_stock:
            continue
        default = product.default_variant
        results.append(
            PublicProduct(
                id=product.id,
                name=product.name,
                description=product.online_description or product.description,
                brand=product.brand,
                category=product.category.name if product.category else None,
                unit_of_measure=product.unit_of_measure,
                price=(
                    Decimal(default.selling_price)
                    if store.show_prices and default.selling_price is not None
                    else None
                ),
                in_stock=in_stock or not product.track_stock,
                variants=[
                    {
                        "id": str(variant.id),
                        "name": variant.name,
                        "price": (
                            str(variant.selling_price)
                            if store.show_prices and variant.selling_price is not None
                            else None
                        ),
                    }
                    for variant in product.variants
                    if variant.is_active
                ],
            )
        )

    total = len(results)
    return results[offset : offset + limit], total


def _stock_map(
    db: Session, tenant_id: uuid.UUID, product_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    if not product_ids:
        return {}
    rows = db.execute(
        select(StockBalance.product_id, func.sum(StockBalance.quantity))
        .where(StockBalance.tenant_id == tenant_id, StockBalance.product_id.in_(product_ids))
        .group_by(StockBalance.product_id)
    )
    return {row[0]: Decimal(row[1] or 0) for row in rows}


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
    _notify_enquiry(db, enquiry)
    return enquiry


def _notify_enquiry(db: Session, enquiry: CustomerEnquiry) -> None:
    from app.models.access import MembershipStatus, TenantMembership
    from app.models.system import Notification, NotificationKind

    memberships = db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == enquiry.tenant_id,
            TenantMembership.status == MembershipStatus.ACTIVE,
        )
    ).scalars()
    for membership in memberships:
        if Permission.ENQUIRY_VIEW not in membership.effective_permissions():
            continue
        db.add(
            Notification(
                tenant_id=enquiry.tenant_id,
                user_id=membership.user_id,
                kind=NotificationKind.NEW_ENQUIRY,
                title=f"New enquiry from {enquiry.contact_name}",
                body=enquiry.message,
                link=f"/shop/enquiries/{enquiry.id}",
                entity_type="customer_enquiry",
                entity_id=enquiry.id,
            )
        )
    db.flush()


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


def create_quotation(db: Session, ctx: AuthContext, data: QuotationInput) -> Quotation:
    """Build a numbered proforma.  Not a sale and not a stock deduction (PRD 14)."""
    ctx.require(Permission.QUOTATION_MANAGE)
    if not data.lines:
        raise ValidationError("A proforma needs at least one line")
    if not data.customer_name.strip():
        raise ValidationError("Who is this proforma for?")

    today = date.today()
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

    subtotal = discount_total = tax_total = ZERO
    for index, line in enumerate(data.lines):
        quantity = Decimal(line.quantity)
        if quantity <= 0:
            raise ValidationError("Quantities must be positive")

        variant = None
        if line.variant_id is not None:
            variant = get_tenant_object(
                db, ProductVariant, line.variant_id, ctx.tenant_id, label="Product"
            )
        description = line.description or (variant.display_name if variant else None)
        if not description:
            raise ValidationError("Each line needs a product or a description")

        unit_price = Decimal(
            line.unit_price
            if line.unit_price is not None
            else (variant.selling_price if variant and variant.selling_price else 0)
        )
        gross = quantize_money(unit_price * quantity)
        discount = quantize_money(Decimal(line.discount_amount or 0))
        if discount > gross:
            raise ValidationError("Discount cannot exceed the line total")
        net = quantize_money(gross - discount)
        tax_rate = Decimal(
            line.tax_rate
            if line.tax_rate is not None
            else (variant.tax_rate if variant and variant.tax_rate else 0)
        )
        tax_amount = quantize_money(net * tax_rate)

        db.add(
            QuotationLine(
                quotation_id=quotation.id,
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
        subtotal = quantize_money(subtotal + gross)
        discount_total = quantize_money(discount_total + discount)
        tax_total = quantize_money(tax_total + tax_amount)

    quotation.subtotal = subtotal
    quotation.discount_total = discount_total
    quotation.tax_total = tax_total
    quotation.total_amount = quantize_money(
        subtotal - discount_total + tax_total + quotation.delivery_charge
    )
    db.flush()
    db.refresh(quotation)
    return quotation


def send_quotation(db: Session, ctx: AuthContext, quotation_id: uuid.UUID) -> Quotation:
    """Mark as sent and mint the secure share link (PRD 14)."""
    ctx.require(Permission.QUOTATION_MANAGE)
    quotation = get_tenant_object(
        db, Quotation, quotation_id, ctx.tenant_id, label="Proforma"
    )
    if quotation.status in (QuotationStatus.CONVERTED, QuotationStatus.CANCELLED):
        raise ConflictError(f"This proforma is {quotation.status}")

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
