"""End-to-end workflows from the PRD's acceptance gate (PRD 24, A1–A5)."""

from __future__ import annotations

import io
from datetime import date, timedelta
from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.core.errors import ConflictError, ValidationError
from app.models.commerce import QuotationStatus
from app.models.credit import CreditKind, CreditStatus
from app.models.platform import TenantStatus
from app.models.sales import PaymentMethod
from app.services.commerce import (
    QuotationInput,
    QuotationLineInput,
    convert_to_sale,
    create_quotation,
    get_public_store,
    list_public_products,
    respond_to_quotation,
    send_quotation,
    submit_enquiry,
)
from app.services.imports import commit_import, start_import, validate_import
from app.services.inventory import get_balance
from app.services.purchasing import PurchaseInput, PurchaseLineInput, receive_purchase

# --------------------------------------------------------------------------- #
# A1 / onboarding
# --------------------------------------------------------------------------- #


def test_registration_creates_a_ready_to_use_business(db):
    """Register → tenant, roles, owner, branch, location, store, trial (PRD 6)."""
    from app.models.commerce import OnlineStore
    from app.models.platform import Subscription
    from app.services.onboarding import register_business

    result = register_business(
        db,
        business_name="Merkato Electronics",
        full_name="Tigist Bekele",
        email="tigist@merkato.et",
        password="a-good-password",
        phone="0911234567",
    )
    db.flush()

    assert result.tenant.status == TenantStatus.TRIAL
    assert result.tenant.currency == "ETB"
    assert result.branch.name == "Main Branch"
    assert result.branch.is_default is True
    assert result.location.branch_id == result.branch.id
    assert result.membership.role.name == "owner"
    assert result.membership.has_all_branches is True

    subscription = db.query(Subscription).filter_by(tenant_id=result.tenant.id).one()
    assert subscription.trial_ends_on == date.today() + timedelta(days=14)

    store = db.query(OnlineStore).filter_by(tenant_id=result.tenant.id).one()
    assert store.is_published is False  # publishing is a deliberate choice


def test_a_product_needs_only_a_name(business):
    """Progressive disclosure: everything else is optional (PRD 8.1, A1)."""
    product = business.add_product(
        "Mystery item", selling_price=None, purchase_price=None, opening_stock=None
    )
    assert product.name == "Mystery item"
    assert product.default_variant.selling_price is None
    assert product.default_variant.is_default is True
    assert len(product.variants) == 1


def test_registration_refuses_a_duplicate_email(db, business):
    from app.services.onboarding import register_business

    with pytest.raises(ConflictError, match="already exists"):
        register_business(
            db,
            business_name="Copycat",
            full_name="Someone",
            email=business.owner.email,
            password="another-password",
        )


def test_setup_progress_tracks_what_is_left(business):
    from app.services.onboarding import setup_progress

    steps = {s.key: s.done for s in setup_progress(business.db, business.ctx)}
    assert steps["first_product"] is False
    assert steps["first_sale"] is False

    product = business.add_product("First thing", opening_stock="5")
    business.sell(product)
    steps = {s.key: s.done for s in setup_progress(business.db, business.ctx)}
    assert steps["first_product"] is True
    assert steps["first_sale"] is True


# --------------------------------------------------------------------------- #
# Excel import (PRD 8.3)
# --------------------------------------------------------------------------- #


def _spreadsheet(rows: list[list]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_import_maps_headers_validates_then_writes(business, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.storage.settings.storage_local_root", str(tmp_path)
    )
    content = _spreadsheet(
        [
            ["Product Name", "SKU", "Selling Price", "Quantity", "Category"],
            ["Teff flour 25kg", "TEFF-25", 2800, 12, "Grains"],
            ["Berbere 1kg", "BERB-1", 450, 30, "Spices"],
        ]
    )

    job, headers, mapping = start_import(
        business.db,
        business.ctx,
        filename="stock.xlsx",
        content_type=XLSX,
        content=content,
    )
    assert headers[0] == "Product Name"
    assert mapping["Product Name"] == "name"
    assert mapping["Quantity"] == "opening_stock"

    preview = validate_import(business.db, business.ctx, job.id, mapping)
    assert preview.total_rows == 2
    assert preview.valid_rows == 2
    assert preview.error_rows == 0

    commit_import(business.db, business.ctx, job.id)
    business.db.flush()

    from app.models.catalogue import Product

    products = business.db.query(Product).filter_by(tenant_id=business.tenant.id).all()
    assert {p.name for p in products} == {"Teff flour 25kg", "Berbere 1kg"}

    teff = next(p for p in products if p.name.startswith("Teff"))
    assert teff.default_variant.selling_price == Decimal("2800.00")
    assert teff.category.name == "Grains"
    # Imported opening stock is a real, auditable movement (PRD 8.3).
    assert get_balance(
        business.db, business.tenant.id, teff.default_variant.id, business.location.id
    ) == Decimal("12.000")


def test_import_reports_problem_rows_before_writing_anything(business, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.storage.settings.storage_local_root", str(tmp_path)
    )
    content = _spreadsheet(
        [
            ["Product Name", "SKU", "Selling Price"],
            ["Good one", "OK-1", 100],
            ["", "MISSING-NAME", 50],
            ["Bad price", "BAD-1", "not a number"],
            ["Duplicate sku", "OK-1", 75],
        ]
    )
    job, _, mapping = start_import(
        business.db,
        business.ctx,
        filename="messy.xlsx",
        content_type=XLSX,
        content=content,
    )
    preview = validate_import(business.db, business.ctx, job.id, mapping)

    assert preview.total_rows == 4
    assert preview.valid_rows == 1
    assert preview.error_rows == 3
    codes = {issue.code for issue in preview.issues}
    assert "missing_name" in codes
    assert "not_a_number" in codes
    assert "duplicate_sku_in_file" in codes

    from app.models.catalogue import Product

    # Nothing was written during validation.
    assert business.db.query(Product).filter_by(tenant_id=business.tenant.id).count() == 0

    commit_import(business.db, business.ctx, job.id, skip_rows_with_errors=True)
    business.db.flush()
    products = business.db.query(Product).filter_by(tenant_id=business.tenant.id).all()
    assert [p.name for p in products] == ["Good one"]
    assert job.skipped_rows == 3


def test_import_refuses_to_proceed_when_errors_must_be_fixed(business, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.storage.settings.storage_local_root", str(tmp_path)
    )
    content = _spreadsheet([["Product Name", "Selling Price"], ["", 10]])
    job, _, mapping = start_import(
        business.db, business.ctx, filename="bad.xlsx", content_type=XLSX, content=content
    )
    validate_import(business.db, business.ctx, job.id, mapping)
    with pytest.raises(ValidationError, match="need attention"):
        commit_import(business.db, business.ctx, job.id, skip_rows_with_errors=False)


def test_import_flags_a_sku_that_already_exists(business, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.storage.settings.storage_local_root", str(tmp_path)
    )
    business.add_product("Already here", sku="EXIST-1", opening_stock=None)
    content = _spreadsheet([["Product Name", "SKU"], ["New name", "EXIST-1"]])
    job, _, mapping = start_import(
        business.db, business.ctx, filename="dup.xlsx", content_type=XLSX, content=content
    )
    preview = validate_import(business.db, business.ctx, job.id, mapping)
    assert {issue.code for issue in preview.issues} == {"duplicate_sku"}


def test_a_non_spreadsheet_upload_is_rejected(business):
    with pytest.raises(ValidationError, match="not accepted"):
        start_import(
            business.db,
            business.ctx,
            filename="virus.exe",
            content_type="application/x-msdownload",
            content=b"MZ\x90\x00",
        )


def test_csv_files_import_too(business, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.storage.settings.storage_local_root", str(tmp_path)
    )
    content = b"Product Name,Price,Qty\nShiro powder,320,8\n"
    job, headers, mapping = start_import(
        business.db,
        business.ctx,
        filename="products.csv",
        content_type="text/csv",
        content=content,
    )
    assert headers == ["Product Name", "Price", "Qty"]
    preview = validate_import(business.db, business.ctx, job.id, mapping)
    assert preview.valid_rows == 1


def test_export_cells_are_protected_from_formula_injection():
    """A product name starting with '=' must not execute in a spreadsheet (PRD 20)."""
    from app.services.storage import escape_for_spreadsheet

    assert escape_for_spreadsheet("=cmd|'/c calc'!A1").startswith("'=")
    assert escape_for_spreadsheet("+1+1") == "'+1+1"
    assert escape_for_spreadsheet("Normal name") == "Normal name"
    assert escape_for_spreadsheet(None) is None


# --------------------------------------------------------------------------- #
# A3: receive stock with supplier credit
# --------------------------------------------------------------------------- #


def test_receiving_stock_posts_once_and_opens_one_payable(business):
    supplier = business.add_supplier("Wholesale Traders")
    product = business.add_product("Cooking oil", opening_stock=None, purchase_price=None)
    variant = product.default_variant

    result = receive_purchase(
        business.db,
        business.ctx,
        PurchaseInput(
            lines=[
                PurchaseLineInput(
                    variant_id=variant.id, quantity=Decimal("100"), unit_cost=Decimal("80")
                )
            ],
            supplier_id=supplier.id,
            transport_cost=Decimal("500"),
            amount_paid=Decimal("3000"),
            due_date_preset="30_days",
        ),
    )

    assert result.purchase.goods_total == Decimal("8000.00")
    assert result.purchase.total_amount == Decimal("8500.00")
    assert get_balance(
        business.db, business.tenant.id, variant.id, business.location.id
    ) == Decimal("100.000")

    payable = result.credit_transaction
    assert payable is not None
    assert payable.kind == CreditKind.PAYABLE
    assert payable.original_amount == Decimal("8500.00")
    assert payable.amount_paid == Decimal("3000.00")
    assert payable.balance == Decimal("5500.00")

    # The landed cost includes the transport allocation: 80 + (500 / 100).
    assert variant.average_cost == Decimal("85.00")


def test_paying_a_payable_does_not_move_stock_again(business):
    """Payments must never duplicate inventory or purchase cost (PRD 11.8)."""
    from app.models.inventory import StockMovement
    from app.services.credit import record_payment

    supplier = business.add_supplier("Wholesale Traders")
    product = business.add_product("Cooking oil", opening_stock=None, purchase_price=None)
    result = receive_purchase(
        business.db,
        business.ctx,
        PurchaseInput(
            lines=[
                PurchaseLineInput(
                    variant_id=product.default_variant.id,
                    quantity=Decimal("50"),
                    unit_cost=Decimal("100"),
                )
            ],
            supplier_id=supplier.id,
            amount_paid=Decimal("0"),
        ),
    )
    movements_before = business.db.query(StockMovement).count()

    record_payment(
        business.db,
        business.ctx,
        result.credit_transaction.id,
        amount=Decimal("5000"),
        method=PaymentMethod.BANK_TRANSFER,
    )
    business.db.refresh(result.credit_transaction)

    assert business.db.query(StockMovement).count() == movements_before
    assert result.credit_transaction.status == CreditStatus.PAID


def test_shared_cost_allocation_by_quantity(business):
    cheap = business.add_product("Cheap", opening_stock=None, purchase_price=None)
    dear = business.add_product("Dear", opening_stock=None, purchase_price=None)

    result = receive_purchase(
        business.db,
        business.ctx,
        PurchaseInput(
            lines=[
                PurchaseLineInput(
                    variant_id=cheap.default_variant.id,
                    quantity=Decimal("10"),
                    unit_cost=Decimal("10"),
                ),
                PurchaseLineInput(
                    variant_id=dear.default_variant.id,
                    quantity=Decimal("10"),
                    unit_cost=Decimal("1000"),
                ),
            ],
            transport_cost=Decimal("200"),
            cost_allocation_method="by_quantity",
            amount_paid=Decimal("10300"),
        ),
    )
    allocations = [line.allocated_cost for line in result.purchase.lines]
    assert allocations == [Decimal("100.00"), Decimal("100.00")]


def test_receiving_can_reprice_from_the_new_cost(business):
    from app.models.catalogue import PricingBasis, PricingRule, PricingScope

    business.db.add(
        PricingRule(
            tenant_id=business.tenant.id,
            scope=PricingScope.BUSINESS,
            basis=PricingBasis.MARKUP,
            rate=Decimal("0.5"),
        )
    )
    business.db.flush()
    product = business.add_product(
        "Repriced", opening_stock=None, purchase_price=None, selling_price="100"
    )
    receive_purchase(
        business.db,
        business.ctx,
        PurchaseInput(
            lines=[
                PurchaseLineInput(
                    variant_id=product.default_variant.id,
                    quantity=Decimal("10"),
                    unit_cost=Decimal("200"),
                )
            ],
            amount_paid=Decimal("2000"),
            reprice_from_cost=True,
        ),
    )
    assert product.default_variant.selling_price == Decimal("300.00")


def test_a_purchase_retry_does_not_receive_stock_twice(business):
    product = business.add_product("Retry stock", opening_stock=None, purchase_price=None)
    payload = PurchaseInput(
        lines=[
            PurchaseLineInput(
                variant_id=product.default_variant.id,
                quantity=Decimal("25"),
                unit_cost=Decimal("40"),
            )
        ],
        amount_paid=Decimal("1000"),
        idempotency_key="grn-77",
    )
    first = receive_purchase(business.db, business.ctx, payload)
    second = receive_purchase(business.db, business.ctx, payload)

    assert first.purchase.id == second.purchase.id
    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, business.location.id
    ) == Decimal("25.000")


# --------------------------------------------------------------------------- #
# A4: publish online, enquiry and proforma
# --------------------------------------------------------------------------- #


@pytest.fixture
def published_store(business):
    from app.models.commerce import OnlineStore

    store = (
        business.db.query(OnlineStore).filter_by(tenant_id=business.tenant.id).one()
    )
    store.is_published = True
    business.db.flush()
    return store


def test_the_storefront_uses_the_same_catalogue_and_stock(business, published_store):
    business.add_product("Published", selling_price="250", opening_stock="5", is_published=True)
    business.add_product("Not published", selling_price="99", opening_stock="5")

    store, tenant = get_public_store(business.db, published_store.slug)
    products, total = list_public_products(business.db, store, tenant)

    assert total == 1
    assert products[0].name == "Published"
    assert products[0].price == Decimal("250.00")
    assert products[0].in_stock is True


def test_out_of_stock_products_can_be_hidden_online(business, published_store):
    business.add_product(
        "Sold out", selling_price="250", opening_stock=None, is_published=True
    )
    store, tenant = get_public_store(business.db, published_store.slug)

    _, shown = list_public_products(business.db, store, tenant)
    assert shown == 1  # shown as out of stock by default

    tenant.hide_out_of_stock_online = True
    business.db.flush()
    _, hidden = list_public_products(business.db, store, tenant)
    assert hidden == 0


def test_an_enquiry_reserves_no_stock(business, published_store):
    """A request never touches inventory (PRD 13, A4)."""
    product = business.add_product(
        "Wanted", selling_price="1000", opening_stock="10", is_published=True
    )
    store, _ = get_public_store(business.db, published_store.slug)

    enquiry = submit_enquiry(
        business.db,
        store,
        contact_name="Dawit",
        contact_phone="0912345678",
        message="Do you deliver to Adama?",
        wants_proforma=True,
    )
    assert enquiry.reference.startswith("ENQ-")
    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, business.location.id
    ) == Decimal("10.000")


def test_an_enquiry_notifies_authorised_staff(business, published_store):
    from app.models.system import Notification, NotificationKind

    store, _ = get_public_store(business.db, published_store.slug)
    submit_enquiry(
        business.db, store, contact_name="Dawit", contact_phone="0912345678"
    )
    notifications = (
        business.db.query(Notification)
        .filter(Notification.kind == NotificationKind.NEW_ENQUIRY)
        .all()
    )
    assert [n.user_id for n in notifications] == [business.owner.id]


def test_an_unpublished_store_is_not_reachable(business):
    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        get_public_store(business.db, business.tenant.slug)


def test_a_proforma_is_not_a_sale_until_it_is_converted(business):
    """Generating and sharing a proforma posts no sale and deducts no stock (PRD 14)."""
    from app.models.sales import Sale

    product = business.add_product("Quoted", selling_price="1200", opening_stock="20")
    quotation = create_quotation(
        business.db,
        business.ctx,
        QuotationInput(
            customer_name="Hana Girma",
            customer_phone="0911112222",
            lines=[
                QuotationLineInput(
                    variant_id=product.default_variant.id, quantity=Decimal("5")
                )
            ],
            delivery_charge=Decimal("300"),
        ),
    )
    assert quotation.number.startswith("PF-")
    assert quotation.total_amount == Decimal("6300.00")
    assert quotation.status == QuotationStatus.DRAFT
    assert business.db.query(Sale).filter_by(tenant_id=business.tenant.id).count() == 0
    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, business.location.id
    ) == Decimal("20.000")

    send_quotation(business.db, business.ctx, quotation.id)
    assert quotation.share_token is not None
    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, business.location.id
    ) == Decimal("20.000")

    # Acceptance records intent, still no sale.
    respond_to_quotation(business.db, quotation.share_token, accept=True)
    assert quotation.status == QuotationStatus.ACCEPTED
    assert business.db.query(Sale).filter_by(tenant_id=business.tenant.id).count() == 0

    # Only the explicit conversion posts the sale and moves stock.
    result = convert_to_sale(business.db, business.ctx, quotation.id)
    assert quotation.status == QuotationStatus.CONVERTED
    assert result.sale.total_amount == Decimal("6000.00")
    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, business.location.id
    ) == Decimal("15.000")


def test_a_proforma_share_link_offers_telegram_and_email(business):
    product = business.add_product("Quoted", selling_price="500", opening_stock="10")
    quotation = create_quotation(
        business.db,
        business.ctx,
        QuotationInput(
            customer_name="Hana Girma",
            customer_email="hana@example.et",
            lines=[
                QuotationLineInput(
                    variant_id=product.default_variant.id, quantity=Decimal("1")
                )
            ],
        ),
    )
    send_quotation(business.db, business.ctx, quotation.id)

    from app.services.commerce import share_links

    links = share_links(quotation)
    assert quotation.share_token in links["url"]
    assert links["telegram"].startswith("https://t.me/share/url?")
    assert "hana@example.et" in links["mailto"]


def test_an_expired_proforma_cannot_be_accepted(business):
    product = business.add_product("Quoted", selling_price="500", opening_stock="10")
    quotation = create_quotation(
        business.db,
        business.ctx,
        QuotationInput(
            customer_name="Late Customer",
            lines=[
                QuotationLineInput(
                    variant_id=product.default_variant.id, quantity=Decimal("1")
                )
            ],
        ),
    )
    send_quotation(business.db, business.ctx, quotation.id)
    quotation.valid_until = date.today() - timedelta(days=1)
    business.db.flush()

    with pytest.raises(ConflictError, match="expired"):
        respond_to_quotation(business.db, quotation.share_token, accept=True)


def test_a_proforma_cannot_be_converted_twice(business):
    product = business.add_product("Quoted", selling_price="500", opening_stock="10")
    quotation = create_quotation(
        business.db,
        business.ctx,
        QuotationInput(
            customer_name="Repeat",
            customer_phone="0911000000",
            lines=[
                QuotationLineInput(
                    variant_id=product.default_variant.id, quantity=Decimal("1")
                )
            ],
        ),
    )
    convert_to_sale(business.db, business.ctx, quotation.id)
    with pytest.raises(ConflictError, match="already been converted"):
        convert_to_sale(business.db, business.ctx, quotation.id)


def test_a_free_text_proforma_line_cannot_be_sold(business):
    quotation = create_quotation(
        business.db,
        business.ctx,
        QuotationInput(
            customer_name="Custom job",
            lines=[
                QuotationLineInput(
                    description="Installation labour",
                    quantity=Decimal("1"),
                    unit_price=Decimal("2000"),
                )
            ],
        ),
    )
    with pytest.raises(ValidationError, match="not linked to a product"):
        convert_to_sale(business.db, business.ctx, quotation.id)


# --------------------------------------------------------------------------- #
# Trial expiry (PRD 17)
# --------------------------------------------------------------------------- #


def test_an_expired_trial_restricts_access_without_deleting_data(business):
    from app.models.platform import Subscription, SubscriptionStatus
    from app.services.subscription import expire_lapsed_trials

    product = business.add_product("Before expiry", selling_price="100", opening_stock="10")
    sale = business.sell(product).sale

    subscription = (
        business.db.query(Subscription).filter_by(tenant_id=business.tenant.id).one()
    )
    subscription.trial_ends_on = date.today() - timedelta(days=1)
    business.db.flush()

    expired = expire_lapsed_trials(business.db)
    assert business.tenant.id in expired
    assert business.tenant.status == TenantStatus.RESTRICTED
    assert subscription.status == SubscriptionStatus.EXPIRED

    # Nothing was deleted or altered.
    business.db.refresh(sale)
    assert sale.total_amount == Decimal("100.00")
    assert get_balance(
        business.db, business.tenant.id, product.default_variant.id, business.location.id
    ) == Decimal("9.000")


def test_owners_are_warned_before_a_trial_ends(business):
    from app.models.platform import Subscription
    from app.models.system import Notification, NotificationKind
    from app.services.subscription import warn_expiring_trials

    subscription = (
        business.db.query(Subscription).filter_by(tenant_id=business.tenant.id).one()
    )
    subscription.trial_ends_on = date.today() + timedelta(days=3)
    business.db.flush()

    assert warn_expiring_trials(business.db) == 1
    notifications = (
        business.db.query(Notification)
        .filter(Notification.kind == NotificationKind.TRIAL_EXPIRY)
        .all()
    )
    assert len(notifications) == 1
    assert "3 day" in notifications[0].title
