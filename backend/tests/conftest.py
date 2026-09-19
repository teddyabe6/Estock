"""Test fixtures.

The suite runs on SQLite so it needs no external services; the models are kept
portable for exactly this reason.  PostgreSQL is what Docker Compose and
deployment run.
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("STORAGE_LOCAL_ROOT", "./var/test-uploads")
os.environ.setdefault("DEFAULT_TRIAL_DAYS", "14")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.core.permissions import RoleName
from app.core.security import create_access_token
from app.core.tenancy import AuthContext, build_auth_context
from app.main import app as fastapi_app
from app.models.access import BranchAssignment, MembershipStatus, Role, TenantMembership, User
from app.models.organisation import Branch, StockLocation
from app.services.onboarding import register_business

#: Set TEST_DATABASE_URL to run the same suite against PostgreSQL, which also
#: exercises the ``SELECT ... FOR UPDATE`` paths SQLite skips.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite://")


@pytest.fixture(scope="session")
def engine():
    if TEST_DATABASE_URL.startswith("sqlite"):
        engine = create_engine(
            TEST_DATABASE_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_connection, _record):  # noqa: ANN001
            # SQLite ignores foreign keys unless asked; PostgreSQL always enforces them.
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    else:
        engine = create_engine(TEST_DATABASE_URL, poolclass=StaticPool)

    import app.models  # noqa: F401  (registers every mapper)

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def db(engine) -> Session:
    """A session on a transaction that is rolled back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):  # noqa: ANN001
        if trans.nested and not trans._parent.nested:
            sess.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db) -> TestClient:
    """A TestClient sharing the test's session, so API writes are rolled back."""

    def override_get_db():
        yield db

    fastapi_app.dependency_overrides[get_db] = override_get_db
    with TestClient(fastapi_app) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.clear()


class Business:
    """A registered business with helpers for building test scenarios."""

    def __init__(self, db: Session, name: str, email: str):
        self.db = db
        result = register_business(
            db,
            business_name=name,
            full_name=f"Owner of {name}",
            email=email,
            password="test-password-123",
            phone="0911223344",
        )
        db.flush()
        self.tenant = result.tenant
        self.owner = result.user
        self.membership = result.membership
        self.branch = result.branch
        self.location = result.location
        self.ctx = build_auth_context(self.owner, self.tenant, self.membership)

    # -- authority -------------------------------------------------------- #

    def token(self, user: User | None = None) -> str:
        return create_access_token(
            subject=(user or self.owner).id, tenant_id=self.tenant.id
        )

    def headers(self, user: User | None = None) -> dict:
        return {"Authorization": f"Bearer {self.token(user)}"}

    def add_user(
        self,
        role: RoleName,
        *,
        email: str | None = None,
        branches: list[Branch] | None = None,
        all_branches: bool = False,
    ) -> tuple[User, AuthContext]:
        email = email or f"{role.value}-{uuid.uuid4().hex[:6]}@example.com"
        user = User(
            email=email,
            full_name=f"{role.value.title()} User",
            password_hash=None,
            is_active=True,
        )
        self.db.add(user)
        self.db.flush()
        role_row = (
            self.db.query(Role)
            .filter(Role.tenant_id == self.tenant.id, Role.name == role.value)
            .one()
        )
        membership = TenantMembership(
            tenant_id=self.tenant.id,
            user_id=user.id,
            role_id=role_row.id,
            status=MembershipStatus.ACTIVE,
            has_all_branches=all_branches,
        )
        self.db.add(membership)
        self.db.flush()
        for branch in branches or ([] if all_branches else [self.branch]):
            self.db.add(
                BranchAssignment(membership_id=membership.id, branch_id=branch.id)
            )
        self.db.flush()
        self.db.refresh(membership)
        return user, build_auth_context(user, self.tenant, membership)

    def add_branch(self, name: str) -> tuple[Branch, StockLocation]:
        branch = Branch(tenant_id=self.tenant.id, name=name)
        self.db.add(branch)
        self.db.flush()
        location = StockLocation(
            tenant_id=self.tenant.id, branch_id=branch.id, name=name, is_default=True
        )
        self.db.add(location)
        self.db.flush()
        return branch, location

    # -- catalogue -------------------------------------------------------- #

    def add_product(
        self,
        name: str = "Test Product",
        *,
        selling_price: Decimal | str = "100.00",
        purchase_price: Decimal | str | None = "60.00",
        opening_stock: Decimal | str | None = "10",
        **kwargs,
    ):
        from app.services.catalogue import ProductInput, create_product

        product = create_product(
            self.db,
            self.ctx,
            ProductInput(
                name=name,
                selling_price=Decimal(selling_price) if selling_price is not None else None,
                purchase_price=Decimal(purchase_price) if purchase_price is not None else None,
                opening_stock=Decimal(opening_stock) if opening_stock is not None else None,
                **kwargs,
            ),
        )
        self.db.flush()
        return product

    def add_customer(self, name: str = "Test Customer", **kwargs):
        from app.models.contacts import Customer

        customer = Customer(tenant_id=self.tenant.id, name=name, **kwargs)
        self.db.add(customer)
        self.db.flush()
        return customer

    def add_supplier(self, name: str = "Test Supplier", **kwargs):
        from app.models.contacts import Supplier

        supplier = Supplier(tenant_id=self.tenant.id, name=name, **kwargs)
        self.db.add(supplier)
        self.db.flush()
        return supplier

    def sell(self, product, quantity="1", paid=None, **kwargs):
        """Record a sale of one product, paid in cash unless told otherwise."""
        from app.models.sales import PaymentMethod
        from app.services.sales import PaymentInput, SaleInput, SaleLineInput, create_sale

        variant = product.default_variant
        payments = []
        if paid is not None and Decimal(paid) > 0:
            payments.append(
                PaymentInput(method=PaymentMethod.CASH, amount=Decimal(paid))
            )
        elif paid is None:
            total = Decimal(variant.selling_price or 0) * Decimal(quantity)
            payments.append(PaymentInput(method=PaymentMethod.CASH, amount=total))

        return create_sale(
            self.db,
            self.ctx,
            SaleInput(
                lines=[SaleLineInput(variant_id=variant.id, quantity=Decimal(quantity))],
                payments=payments,
                **kwargs,
            ),
        )


@pytest.fixture
def business(db) -> Business:
    return Business(db, "Addis Retail", "owner@addisretail.et")


@pytest.fixture
def other_business(db) -> Business:
    """A second, unrelated business used to prove tenant isolation."""
    return Business(db, "Bahir Dar Traders", "owner@bahirdar.et")


@pytest.fixture
def today() -> date:
    return date.today()
