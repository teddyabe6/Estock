"""The marketplace checkout: a cart across shops becomes one order or one
proforma request per shop (PRD 13, 14, 19).

Two flows share the same cart and split the same way:

* **Orders.** The buyer chooses how they will pay and the shop confirms,
  fulfils and finally completes the order, which posts the sale.  Nothing is
  charged online and nothing is reserved until completion.
* **Proforma requests.** The buyer asks the chosen shops to quote; each shop
  reviews and sends its own proforma.

Each shop is told about its own part only, by in-app notification, email and,
when linked, Telegram.  A shop never sees another shop's part.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, record_audit
from app.core.config import settings
from app.core.db import utcnow
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.permissions import Permission
from app.core.security import generate_share_token
from app.core.tenancy import AuthContext, get_tenant_object
from app.models.catalogue import Product, ProductVariant
from app.models.commerce import (
    CheckoutBatch,
    CheckoutKind,
    DeliveryMethod,
    OnlineStore,
    Order,
    OrderLine,
    OrderStatus,
    Quotation,
)
from app.models.platform import Tenant, TenantStatus
from app.services.commerce import (
    find_or_create_customer,
    notify_staff,
    request_quotation,
)
from app.services.messaging import notify_store
from app.services.notifications import send_email
from app.services.numbering import next_number
from app.services.pricing import quantize_money

ZERO = Decimal("0.00")
MAX_CHECKOUT_ITEMS = 100
MAX_SHOPS_PER_CHECKOUT = 10


@dataclass(slots=True)
class CheckoutItem:
    shop: str
    variant_id: uuid.UUID
    quantity: Decimal


@dataclass(slots=True)
class CheckoutContact:
    name: str
    phone: str
    email: str | None = None
    company: str | None = None
    delivery_location: str | None = None
    message: str | None = None


@dataclass(slots=True)
class ShopPart:
    store: OnlineStore
    tenant: Tenant
    #: variant → quantity, duplicates already merged
    wanted: dict[uuid.UUID, Decimal]
    variants: dict[uuid.UUID, ProductVariant]


@dataclass(slots=True)
class CheckoutResult:
    batch: CheckoutBatch
    orders: list[Order] = field(default_factory=list)
    quotations: list[Quotation] = field(default_factory=list)

    @property
    def tracking_url(self) -> str:
        return tracking_url(self.batch.token)


def tracking_url(token: str) -> str:
    return f"{settings.public_base_url}/track/{token}"


# --------------------------------------------------------------------------- #
# Splitting the cart
# --------------------------------------------------------------------------- #


def _split_by_shop(db: Session, items: list[CheckoutItem]) -> list[ShopPart]:
    if not items:
        raise ValidationError("Your cart is empty")
    if len(items) > MAX_CHECKOUT_ITEMS:
        raise ValidationError(f"A checkout can hold at most {MAX_CHECKOUT_ITEMS} items")

    wanted_by_shop: dict[str, dict[uuid.UUID, Decimal]] = {}
    for item in items:
        quantity = Decimal(item.quantity)
        if quantity <= 0:
            raise ValidationError("Quantities must be positive")
        slug = item.shop.strip().lower()
        shop_wanted = wanted_by_shop.setdefault(slug, {})
        shop_wanted[item.variant_id] = shop_wanted.get(item.variant_id, ZERO) + quantity
    if len(wanted_by_shop) > MAX_SHOPS_PER_CHECKOUT:
        raise ValidationError(f"A checkout can span at most {MAX_SHOPS_PER_CHECKOUT} shops")

    rows = db.execute(
        select(OnlineStore, Tenant)
        .join(Tenant, Tenant.id == OnlineStore.tenant_id)
        .where(
            OnlineStore.slug.in_(list(wanted_by_shop)),
            OnlineStore.is_published.is_(True),
            Tenant.status != TenantStatus.SUSPENDED,
        )
    )
    open_shops = {row[0].slug: (row[0], row[1]) for row in rows}
    closed = sorted(slug for slug in wanted_by_shop if slug not in open_shops)
    if closed:
        raise ValidationError(
            "Some shops in your cart are not open any more. Remove their items and try again.",
            details={"unavailable_shops": closed},
        )

    parts: list[ShopPart] = []
    unavailable: list[str] = []
    for slug, wanted in wanted_by_shop.items():
        store, tenant = open_shops[slug]
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
        unavailable.extend(str(v) for v in wanted if v not in by_id)
        parts.append(ShopPart(store=store, tenant=tenant, wanted=wanted, variants=by_id))
    if unavailable:
        raise ValidationError(
            "Some items in your cart are no longer available. Remove them and try again.",
            details={"unavailable": unavailable},
        )
    return parts


def _new_batch(
    db: Session, kind: CheckoutKind, contact: CheckoutContact, source_ip: str | None
) -> CheckoutBatch:
    if not contact.name.strip():
        raise ValidationError("Please give your name")
    if not contact.phone.strip():
        raise ValidationError("Please give a phone number the shops can reach you on")
    batch = CheckoutBatch(
        token=generate_share_token(),
        kind=kind,
        customer_name=contact.name.strip(),
        customer_phone=contact.phone.strip(),
        customer_email=(contact.email or "").strip() or None,
        company=(contact.company or "").strip() or None,
        delivery_location=(contact.delivery_location or "").strip() or None,
        message=(contact.message or "").strip() or None,
        source_ip=source_ip,
    )
    db.add(batch)
    db.flush()
    return batch


# --------------------------------------------------------------------------- #
# Orders
# --------------------------------------------------------------------------- #


def place_orders(
    db: Session,
    *,
    items: list[CheckoutItem],
    contact: CheckoutContact,
    delivery_method: DeliveryMethod = DeliveryMethod.DELIVERY,
    payment_method: str = "cash",
    source_ip: str | None = None,
) -> CheckoutResult:
    """Checkout: one order per shop, priced from each shop's catalogue."""
    parts = _split_by_shop(db, items)
    proforma_only = sorted(part.store.slug for part in parts if not part.store.accepts_orders)
    if proforma_only:
        names = ", ".join(
            part.store.display_name for part in parts if part.store.slug in proforma_only
        )
        raise ValidationError(
            f"{names} takes proforma requests only. Remove those items, or request a "
            "proforma for your whole cart instead.",
            details={"proforma_only_shops": proforma_only},
        )
    unpriced = [
        variant.display_name
        for part in parts
        for variant in part.variants.values()
        if not part.store.show_prices or variant.selling_price is None
    ]
    if unpriced:
        raise ValidationError(
            "These items have no online price, so they can only be requested as a proforma: "
            + ", ".join(unpriced[:3])
            + (" and more" if len(unpriced) > 3 else ""),
            details={"unpriced": unpriced},
        )

    batch = _new_batch(db, CheckoutKind.ORDER, contact, source_ip)
    result = CheckoutResult(batch=batch)
    for part in parts:
        result.orders.append(
            _create_order(
                db,
                part,
                batch=batch,
                delivery_method=delivery_method,
                payment_method=payment_method,
            )
        )
    return result


def _create_order(
    db: Session,
    part: ShopPart,
    *,
    batch: CheckoutBatch,
    delivery_method: DeliveryMethod,
    payment_method: str,
) -> Order:
    store, tenant = part.store, part.tenant
    customer = find_or_create_customer(
        db,
        tenant.id,
        name=batch.customer_name,
        phone=batch.customer_phone,
        email=batch.customer_email,
        company=batch.company,
        address=batch.delivery_location,
    )
    order = Order(
        tenant_id=tenant.id,
        number=next_number(db, Order, tenant.id, "order"),
        status=OrderStatus.PLACED,
        batch_id=batch.id,
        customer_id=customer.id,
        customer_name=batch.customer_name,
        customer_phone=customer.phone,
        customer_email=batch.customer_email,
        customer_company=batch.company,
        delivery_location=batch.delivery_location,
        delivery_method=delivery_method,
        payment_method=str(payment_method),
        customer_message=batch.message,
        currency=tenant.currency,
        share_token=generate_share_token(),
    )
    db.add(order)
    db.flush()
    for index, (variant_id, quantity) in enumerate(part.wanted.items()):
        variant = part.variants[variant_id]
        unit_price = quantize_money(Decimal(variant.selling_price or 0))
        gross = quantize_money(unit_price * quantity)
        tax_rate = Decimal(variant.tax_rate or 0)
        tax_amount = quantize_money(gross * tax_rate)
        order.lines.append(
            OrderLine(
                product_id=variant.product_id,
                variant_id=variant.id,
                description=variant.display_name,
                quantity=quantity,
                unit_price=unit_price,
                tax_rate=tax_rate,
                tax_amount=tax_amount,
                line_total=quantize_money(gross + tax_amount),
                sort_order=index,
            )
        )
    _recalculate(order)
    db.flush()

    notify_staff(
        db,
        tenant_id=tenant.id,
        permission=Permission.SHOP_MANAGE,
        kind="new_order",
        title=f"Order {order.number} from {order.customer_name}",
        body=(
            f"{len(order.lines)} item(s) · {order.total_amount} {order.currency} · "
            f"{_payment_label(order.payment_method)} · {_delivery_label(order)}"
        ),
        link=f"/shop?tab=orders&open={order.id}",
        entity_type="order",
        entity_id=order.id,
    )
    notify_store(
        db,
        store,
        tenant,
        subject=f"New order {order.number} from {order.customer_name}",
        lines=describe_order(order),
        link=f"{settings.public_base_url}/shop?tab=orders&open={order.id}",
    )
    return order


def _recalculate(order: Order) -> None:
    subtotal = tax_total = ZERO
    for line in order.lines:
        subtotal = quantize_money(
            subtotal + quantize_money(Decimal(line.unit_price) * Decimal(line.quantity))
        )
        tax_total = quantize_money(tax_total + Decimal(line.tax_amount))
    order.subtotal = subtotal
    order.tax_total = tax_total
    order.total_amount = quantize_money(
        subtotal + tax_total + Decimal(order.delivery_charge or 0)
    )


def _payment_label(method: str) -> str:
    return {
        "cash": "cash on delivery or pickup",
        "bank_transfer": "bank transfer",
        "telebirr": "telebirr",
        "cbe_birr": "CBE Birr",
        "mobile_money": "mobile money",
    }.get(method, method.replace("_", " "))


def _delivery_label(order: Order) -> str:
    if order.delivery_method == DeliveryMethod.PICKUP:
        return "pickup"
    return f"deliver to {order.delivery_location}" if order.delivery_location else "delivery"


def describe_order(order: Order) -> list[str]:
    """The shop's own part of a checkout, one line per item, for email or Telegram."""
    lines = [
        f"• {line.description} × {Decimal(line.quantity).normalize():f} "
        f"@ {line.unit_price} = {line.line_total} {order.currency}"
        for line in order.lines
    ]
    lines.append(f"Total: {order.total_amount} {order.currency}")
    lines.append(f"Payment: {_payment_label(order.payment_method)} · {_delivery_label(order)}")
    lines.append(f"From: {order.customer_name} · {order.customer_phone or ''}".rstrip(" ·"))
    if order.customer_company:
        lines.append(f"Company: {order.customer_company}")
    if order.customer_message:
        lines.append(f"Note: {order.customer_message}")
    return lines


ORDER_NEXT_STEP = {
    OrderStatus.PLACED: "The shop will confirm your order and contact you if anything needs checking.",
    OrderStatus.CONFIRMED: "Confirmed. The shop is preparing your order.",
    OrderStatus.READY: "Ready: for pickup at the shop, or on its way to you.",
    OrderStatus.COMPLETED: "Completed. Thank you for your order.",
    OrderStatus.CANCELLED: "This order was cancelled.",
}


def order_next_step(order: Order) -> str:
    text = ORDER_NEXT_STEP.get(order.status, "")
    if order.status == OrderStatus.READY and order.delivery_method == DeliveryMethod.PICKUP:
        return "Ready for pickup at the shop."
    if order.status == OrderStatus.READY:
        return "On its way to you."
    if order.status == OrderStatus.CANCELLED and order.cancel_reason:
        return f"This order was cancelled: {order.cancel_reason}"
    return text


# --------------------------------------------------------------------------- #
# The shop handles an order
# --------------------------------------------------------------------------- #


def _load(db: Session, ctx: AuthContext, order_id: uuid.UUID) -> Order:
    return get_tenant_object(db, Order, order_id, ctx.tenant_id, label="Order")


def get_order(db: Session, ctx: AuthContext, order_id: uuid.UUID) -> Order:
    ctx.require(Permission.SHOP_VIEW)
    return _load(db, ctx, order_id)


def tracking_url_for(db: Session, order: Order) -> str | None:
    if order.batch_id is None:
        return None
    batch = db.get(CheckoutBatch, order.batch_id)
    return tracking_url(batch.token) if batch else None


def _tell_customer(db: Session, order: Order, *, subject: str, body: str) -> None:
    if not order.customer_email:
        return
    link = tracking_url_for(db, order)
    send_email(
        to=order.customer_email,
        subject=subject,
        body=f"Hello {order.customer_name},\n\n{body}\n" + (f"\nTrack it: {link}\n" if link else ""),
    )


def confirm_order(
    db: Session,
    ctx: AuthContext,
    order_id: uuid.UUID,
    *,
    delivery_charge: Decimal | None = None,
    seller_note: str | None = None,
) -> Order:
    """The shop confirms prices and delivery.  Still nothing reserved."""
    ctx.require(Permission.SHOP_MANAGE)
    order = _load(db, ctx, order_id)
    if order.status != OrderStatus.PLACED:
        raise ConflictError(f"This order is already {order.status}")
    if delivery_charge is not None:
        if Decimal(delivery_charge) < 0:
            raise ValidationError("The delivery charge cannot be negative")
        order.delivery_charge = quantize_money(Decimal(delivery_charge))
    if seller_note is not None:
        order.seller_note = seller_note.strip() or None
    _recalculate(order)
    order.status = OrderStatus.CONFIRMED
    order.confirmed_at = utcnow()
    order.handled_by_id = ctx.user_id
    record_audit(
        db,
        action=AuditAction.ORDER_CONFIRMED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="order",
        entity_id=order.id,
        summary=f"Confirmed order {order.number} at {order.total_amount} {order.currency}",
    )
    db.flush()
    _tell_customer(
        db,
        order,
        subject=f"Your order {order.number} is confirmed",
        body=(
            f"{ctx.tenant.name} confirmed your order {order.number}: "
            f"{order.total_amount} {order.currency}, {_payment_label(order.payment_method)}."
            + (f"\n\n{order.seller_note}" if order.seller_note else "")
        ),
    )
    return order


def mark_order_ready(db: Session, ctx: AuthContext, order_id: uuid.UUID) -> Order:
    ctx.require(Permission.SHOP_MANAGE)
    order = _load(db, ctx, order_id)
    if order.status != OrderStatus.CONFIRMED:
        raise ConflictError(f"Confirm the order first; it is {order.status}")
    order.status = OrderStatus.READY
    order.ready_at = utcnow()
    order.handled_by_id = ctx.user_id
    db.flush()
    _tell_customer(
        db,
        order,
        subject=f"Your order {order.number} is {'ready for pickup' if order.delivery_method == DeliveryMethod.PICKUP else 'on its way'}",
        body=f"{ctx.tenant.name}: order {order.number} is {order_next_step(order).lower()}",
    )
    return order


def complete_order(
    db: Session,
    ctx: AuthContext,
    order_id: uuid.UUID,
    *,
    payments: list | None = None,
    branch_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    due_date: date | None = None,
):
    """The explicit step that posts the sale and moves stock (PRD 13)."""
    from app.services.sales import SaleInput, SaleLineInput, create_sale

    ctx.require(Permission.SHOP_MANAGE, Permission.SALE_CREATE)
    order = _load(db, ctx, order_id)
    if order.status == OrderStatus.COMPLETED:
        raise ConflictError("This order has already been completed")
    if order.status == OrderStatus.CANCELLED:
        raise ConflictError("This order was cancelled")

    result = create_sale(
        db,
        ctx,
        SaleInput(
            lines=[
                SaleLineInput(
                    variant_id=line.variant_id,
                    quantity=Decimal(line.quantity),
                    unit_price=Decimal(line.unit_price),
                    tax_rate=Decimal(line.tax_rate),
                )
                for line in order.lines
            ],
            payments=payments or [],
            branch_id=branch_id,
            location_id=location_id,
            customer_id=order.customer_id,
            note=f"From online order {order.number}",
            due_date=due_date,
            idempotency_key=f"order:{order.id}",
        ),
    )
    if Decimal(order.delivery_charge or 0) > 0:
        result.warnings.append(
            f"The order's delivery charge of {order.delivery_charge} {order.currency} is not "
            "part of the sale total; record it separately."
        )
    order.status = OrderStatus.COMPLETED
    order.completed_at = utcnow()
    order.converted_sale_id = result.sale.id
    order.handled_by_id = ctx.user_id
    record_audit(
        db,
        action=AuditAction.ORDER_COMPLETED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="order",
        entity_id=order.id,
        summary=f"Completed order {order.number} as sale {result.sale.number}",
    )
    db.flush()
    _tell_customer(
        db,
        order,
        subject=f"Your order {order.number} is complete",
        body=f"{ctx.tenant.name} has completed your order {order.number}. Thank you.",
    )
    return order, result


def cancel_order(
    db: Session, ctx: AuthContext, order_id: uuid.UUID, *, reason: str | None = None
) -> Order:
    ctx.require(Permission.SHOP_MANAGE)
    order = _load(db, ctx, order_id)
    if order.status == OrderStatus.COMPLETED:
        raise ConflictError("This order became a sale; void the sale instead")
    if order.status == OrderStatus.CANCELLED:
        raise ConflictError("This order is already cancelled")
    _cancel(order, reason)
    order.handled_by_id = ctx.user_id
    record_audit(
        db,
        action=AuditAction.ORDER_CANCELLED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="order",
        entity_id=order.id,
        summary=f"Cancelled order {order.number}" + (f": {order.cancel_reason}" if order.cancel_reason else ""),
    )
    db.flush()
    _tell_customer(
        db,
        order,
        subject=f"Your order {order.number} was cancelled",
        body=f"{ctx.tenant.name} cancelled order {order.number}."
        + (f" Reason: {order.cancel_reason}" if order.cancel_reason else ""),
    )
    return order


def _cancel(order: Order, reason: str | None) -> None:
    order.status = OrderStatus.CANCELLED
    order.cancelled_at = utcnow()
    order.cancel_reason = (reason or "").strip() or None


# --------------------------------------------------------------------------- #
# The customer's side
# --------------------------------------------------------------------------- #


def get_order_by_token(db: Session, token: str) -> Order:
    order = db.execute(select(Order).where(Order.share_token == token)).scalar_one_or_none()
    if order is None:
        raise NotFoundError("This order link is no longer valid")
    return order


def cancel_order_by_customer(db: Session, token: str, *, reason: str | None = None) -> Order:
    """A buyer may withdraw while the shop has not yet confirmed."""
    order = get_order_by_token(db, token)
    if order.status == OrderStatus.CANCELLED:
        raise ConflictError("This order is already cancelled")
    if order.status != OrderStatus.PLACED:
        raise ConflictError(
            "The shop has already confirmed this order. Contact them to change it."
        )
    _cancel(order, reason)
    db.flush()
    notify_staff(
        db,
        tenant_id=order.tenant_id,
        permission=Permission.SHOP_MANAGE,
        kind="order_update",
        title=f"{order.customer_name} cancelled order {order.number}",
        body=order.cancel_reason,
        link=f"/shop?tab=orders&open={order.id}",
        entity_type="order",
        entity_id=order.id,
    )
    return order


def get_batch(db: Session, token: str) -> tuple[CheckoutBatch, list[Order], list[Quotation]]:
    batch = db.execute(
        select(CheckoutBatch).where(CheckoutBatch.token == token)
    ).scalar_one_or_none()
    if batch is None:
        raise NotFoundError("This tracking link is no longer valid")
    orders = list(
        db.execute(
            select(Order).where(Order.batch_id == batch.id).order_by(Order.created_at)
        ).scalars()
    )
    quotations = list(
        db.execute(
            select(Quotation).where(Quotation.batch_id == batch.id).order_by(Quotation.created_at)
        ).scalars()
    )
    return batch, orders, quotations


# --------------------------------------------------------------------------- #
# Proforma requests across shops
# --------------------------------------------------------------------------- #


def request_proformas(
    db: Session,
    *,
    items: list[CheckoutItem],
    contact: CheckoutContact,
    source_ip: str | None = None,
) -> CheckoutResult:
    """One proforma request per chosen shop, each told about its own part."""
    from app.services.commerce import BasketItem

    parts = _split_by_shop(db, items)
    batch = _new_batch(db, CheckoutKind.PROFORMA, contact, source_ip)
    result = CheckoutResult(batch=batch)
    for part in parts:
        result.quotations.append(
            request_quotation(
                db,
                part.store,
                part.tenant,
                items=[
                    BasketItem(variant_id=variant_id, quantity=quantity)
                    for variant_id, quantity in part.wanted.items()
                ],
                contact_name=batch.customer_name,
                contact_phone=batch.customer_phone,
                contact_email=batch.customer_email,
                company=batch.company,
                delivery_location=batch.delivery_location,
                message=batch.message,
                batch_id=batch.id,
            )
        )
    return result
