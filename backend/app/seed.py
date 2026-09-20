"""Seed a development database with a realistic business (PRD 18).

    python -m app.seed

Creates one business with branches, staff, products, stock, sales, credit and
a published storefront, plus a platform administrator.  Safe to re-run: it
refuses rather than duplicating.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.permissions import RoleName
from app.core.security import hash_password
from app.core.tenancy import build_auth_context
from app.models.access import BranchAssignment, MembershipStatus, Role, TenantMembership, User
from app.models.catalogue import PricingBasis, PricingRule, PricingScope
from app.models.commerce import OnlineStore
from app.models.platform import PlatformAdmin, SubscriptionPlan
from app.models.sales import PaymentMethod
from app.services.catalogue import ProductInput, create_product
from app.services.commerce import (
    QuotationInput,
    QuotationLineInput,
    create_quotation,
    send_quotation,
)
from app.services.onboarding import register_business
from app.services.purchasing import PurchaseInput, PurchaseLineInput, receive_purchase
from app.services.sales import PaymentInput, SaleInput, SaleLineInput, create_sale

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("estock.seed")

DEMO_EMAIL = "owner@merkato-demo.et"
DEMO_PASSWORD = "demo-password-123"
ADMIN_EMAIL = "admin@estock.et"
ADMIN_PASSWORD = "admin-password-123"

CATALOGUE = [
    # (name, category, unit, purchase price, selling price, opening stock, min, reorder)
    ("Teff flour 25kg", "Grains", "bag", "2400", "2800", "40", "5", "10"),
    ("Berbere 1kg", "Spices", "kg", "320", "450", "60", "10", "20"),
    ("Shiro powder 1kg", "Spices", "kg", "230", "320", "35", "10", "15"),
    ("Sunflower oil 5L", "Cooking", "bottle", "780", "950", "24", "6", "12"),
    ("Sugar 50kg", "Grains", "bag", "4100", "4750", "12", "3", "6"),
    ("Coffee beans 1kg", "Drinks", "kg", "520", "720", "50", "10", "20"),
    ("Macchiato cup", "Drinks", "pcs", "12", "45", "500", "50", "100"),
    ("Cement bag 50kg", "Building", "bag", "980", "1200", "150", "20", "40"),
    ("Steel bar 12mm", "Building", "pcs", "640", "820", "80", "15", "30"),
    ("Exercise book A4", "Stationery", "pcs", "28", "45", "300", "40", "80"),
    # Amharic names and categories, so the demo shows that Ethiopic text works
    # end to end — database, API and both clients (PRD 16).
    ("ቡና (የአቢሲኒያ)", "መጠጦች", "kg", "520", "720", "25", "5", "10"),
    ("በርበሬ", "ቅመማ ቅመም", "kg", "320", "450", "40", "10", "20"),
]


def seed() -> None:
    with SessionLocal() as db:
        if db.execute(select(User).where(User.email == DEMO_EMAIL)).scalar_one_or_none():
            logger.info("Demo data already present; nothing to do.")
            return

        _seed_platform(db)
        result = register_business(
            db,
            business_name="Merkato Wholesale",
            full_name="Tigist Bekele",
            email=DEMO_EMAIL,
            password=DEMO_PASSWORD,
            phone="0911223344",
            branch_name="Merkato Main",
        )
        db.flush()
        tenant, owner = result.tenant, result.user
        ctx = build_auth_context(owner, tenant, result.membership)

        tenant.address = "Merkato, Addis Ababa"
        tenant.tin = "0012345678"
        tenant.business_type = "Wholesale and retail"

        db.add(
            PricingRule(
                tenant_id=tenant.id,
                scope=PricingScope.BUSINESS,
                basis=PricingBasis.MARKUP,
                rate=Decimal("0.25"),
                rounding_increment=Decimal("5"),
            )
        )

        second_branch = _add_branch(db, ctx, "Bole Branch")
        _add_staff(db, tenant.id, result.branch.id, second_branch.id)

        products = _add_products(db, ctx)
        supplier = _add_supplier(db, tenant.id)
        _receive_stock(db, ctx, products[0], supplier)
        customers = _add_customers(db, tenant.id)
        _record_sales(db, ctx, products, customers)
        _publish_store(db, tenant.id, products)
        _add_proforma(db, ctx, products)

        db.commit()

    logger.info("")
    logger.info("Seed complete.")
    logger.info("  Business owner : %s / %s", DEMO_EMAIL, DEMO_PASSWORD)
    logger.info("  Platform admin : %s / %s", ADMIN_EMAIL, ADMIN_PASSWORD)


def _seed_platform(db) -> None:
    if not db.execute(select(PlatformAdmin)).first():
        db.add(
            PlatformAdmin(
                email=ADMIN_EMAIL,
                full_name="Platform Administrator",
                password_hash=hash_password(ADMIN_PASSWORD),
            )
        )
    if not db.execute(select(SubscriptionPlan)).first():
        db.add_all(
            [
                SubscriptionPlan(
                    code="starter",
                    name="Starter",
                    description="One branch, up to 3 users.",
                    monthly_price=Decimal("500"),
                    max_branches=1,
                    max_users=3,
                ),
                SubscriptionPlan(
                    code="growth",
                    name="Growth",
                    description="Up to 5 branches and 15 users.",
                    monthly_price=Decimal("1500"),
                    max_branches=5,
                    max_users=15,
                ),
            ]
        )
    db.flush()


def _add_branch(db, ctx, name: str):
    from app.models.organisation import Branch, LocationKind, StockLocation

    branch = Branch(tenant_id=ctx.tenant_id, name=name, address="Bole, Addis Ababa")
    db.add(branch)
    db.flush()
    db.add(
        StockLocation(
            tenant_id=ctx.tenant_id,
            branch_id=branch.id,
            name=name,
            kind=LocationKind.SHOP,
            is_default=True,
        )
    )
    db.flush()
    return branch


def _add_staff(db, tenant_id, main_branch_id, second_branch_id) -> None:
    people = [
        ("manager@merkato-demo.et", "Dawit Haile", RoleName.MANAGER, [second_branch_id], False),
        ("cashier@merkato-demo.et", "Hana Girma", RoleName.SALESPERSON, [main_branch_id], False),
        ("store@merkato-demo.et", "Abebe Kebede", RoleName.STOCK_USER, [main_branch_id], False),
    ]
    for email, full_name, role_name, branches, all_branches in people:
        role = db.execute(
            select(Role).where(Role.tenant_id == tenant_id, Role.name == role_name.value)
        ).scalar_one()
        user = User(
            email=email,
            full_name=full_name,
            password_hash=hash_password(DEMO_PASSWORD),
            is_active=True,
        )
        db.add(user)
        db.flush()
        membership = TenantMembership(
            tenant_id=tenant_id,
            user_id=user.id,
            role_id=role.id,
            status=MembershipStatus.ACTIVE,
            has_all_branches=all_branches,
        )
        db.add(membership)
        db.flush()
        for branch_id in branches:
            db.add(BranchAssignment(membership_id=membership.id, branch_id=branch_id))
    db.flush()


def _add_products(db, ctx) -> list:
    products = []
    for name, category, unit, cost, price, stock, min_stock, reorder in CATALOGUE:
        products.append(
            create_product(
                db,
                ctx,
                ProductInput(
                    name=name,
                    category_name=category,
                    unit_of_measure=unit,
                    purchase_price=Decimal(cost),
                    selling_price=Decimal(price),
                    opening_stock=Decimal(stock),
                    min_stock=Decimal(min_stock),
                    reorder_level=Decimal(reorder),
                    is_published=category in {"Grains", "Building", "Spices"},
                ),
            )
        )
    db.flush()
    return products


def _add_supplier(db, tenant_id):
    from app.models.contacts import Supplier

    supplier = Supplier(
        tenant_id=tenant_id,
        name="Highland Grain Suppliers",
        phone="+251911777888",
        contact_person="Mulugeta Assefa",
        address="Adama",
    )
    db.add(supplier)
    db.flush()
    return supplier


def _receive_stock(db, ctx, product, supplier) -> None:
    """A part-paid receipt, so the demo has a supplier payable to look at."""
    receive_purchase(
        db,
        ctx,
        PurchaseInput(
            lines=[
                PurchaseLineInput(
                    variant_id=product.default_variant.id,
                    quantity=Decimal("20"),
                    unit_cost=Decimal("2400"),
                )
            ],
            supplier_id=supplier.id,
            transport_cost=Decimal("2000"),
            amount_paid=Decimal("20000"),
            payment_method=PaymentMethod.BANK_TRANSFER,
            due_date_preset="30_days",
            supplier_invoice_ref="INV-4471",
        ),
    )


def _add_customers(db, tenant_id) -> list:
    from app.models.contacts import Customer

    rows = [
        ("Almaz Tadesse", "+251911000111", None),
        ("Yonas Alemu", "+251912000222", Decimal("50000")),
        ("Selam Construction PLC", "+251913000333", Decimal("250000")),
    ]
    customers = []
    for name, phone, limit in rows:
        customer = Customer(
            tenant_id=tenant_id,
            name=name,
            phone=phone,
            credit_limit=limit,
            credit_limit_behaviour="warn" if limit else None,
        )
        db.add(customer)
        customers.append(customer)
    db.flush()
    return customers


def _record_sales(db, ctx, products, customers) -> None:
    from app.core.db import utcnow

    now = utcnow()

    # A few paid sales spread over the last week.
    for days_ago, (product, quantity, method) in enumerate(
        [
            (products[6], "12", PaymentMethod.CASH),
            (products[1], "3", PaymentMethod.TELEBIRR),
            (products[9], "25", PaymentMethod.CASH),
            (products[5], "2", PaymentMethod.CBE_BIRR),
        ]
    ):
        variant = product.default_variant
        total = Decimal(variant.selling_price) * Decimal(quantity)
        create_sale(
            db,
            ctx,
            SaleInput(
                lines=[SaleLineInput(variant_id=variant.id, quantity=Decimal(quantity))],
                payments=[PaymentInput(method=method, amount=total)],
                sold_at=now - timedelta(days=days_ago),
            ),
        )

    # A credit sale with a due date, and an overdue one, so the credit screens
    # and the reminder worker have something real to show.
    cement = products[7]
    create_sale(
        db,
        ctx,
        SaleInput(
            lines=[SaleLineInput(variant_id=cement.default_variant.id, quantity=Decimal("30"))],
            payments=[PaymentInput(method=PaymentMethod.CASH, amount=Decimal("10000"))],
            customer_id=customers[2].id,
            due_date=date.today() + timedelta(days=21),
            credit_note="Agreed 21-day terms with site manager.",
        ),
    )
    create_sale(
        db,
        ctx,
        SaleInput(
            lines=[SaleLineInput(variant_id=products[8].default_variant.id, quantity=Decimal("10"))],
            customer_id=customers[1].id,
            due_date=date.today() - timedelta(days=6),
            credit_note="Was due last week; follow up.",
            sold_at=now - timedelta(days=20),
        ),
    )
    db.flush()


def _publish_store(db, tenant_id, products) -> None:
    store = db.execute(
        select(OnlineStore).where(OnlineStore.tenant_id == tenant_id)
    ).scalar_one()
    store.is_published = True
    store.tagline = "Wholesale grains, spices and building materials in Merkato"
    store.about = "Serving Addis Ababa since 2009. Delivery available across the city."
    store.telegram_username = "merkatowholesale"
    db.flush()


def _add_proforma(db, ctx, products) -> None:
    quotation = create_quotation(
        db,
        ctx,
        QuotationInput(
            customer_name="Selam Construction PLC",
            customer_phone="+251913000333",
            customer_company="Selam Construction PLC",
            delivery_location="Ayat site, Addis Ababa",
            lines=[
                QuotationLineInput(
                    variant_id=products[7].default_variant.id, quantity=Decimal("200")
                ),
                QuotationLineInput(
                    variant_id=products[8].default_variant.id, quantity=Decimal("50")
                ),
            ],
            delivery_charge=Decimal("3500"),
            terms="Valid for 14 days. 50% advance required before delivery.",
        ),
    )
    send_quotation(db, ctx, quotation.id)
    db.flush()


if __name__ == "__main__":
    seed()
