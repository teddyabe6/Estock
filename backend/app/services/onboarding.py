"""Registration and first-run setup (PRD 6).

Registering creates the tenant, its role bundles, the owner membership, a
default branch with a stock location, a storefront record and a trial
subscription — so the first product or sale needs no further configuration.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, record_audit
from app.core.config import settings
from app.core.db import utcnow
from app.core.errors import ConflictError, ValidationError
from app.core.permissions import (
    DEFAULT_ROLE_PERMISSIONS,
    ROLE_DESCRIPTIONS,
    Permission,
    RoleName,
)
from app.core.security import generate_share_token, hash_password
from app.core.tenancy import AuthContext, build_auth_context, tenant_query
from app.models.access import (
    BranchAssignment,
    MembershipStatus,
    Role,
    RolePermission,
    TenantMembership,
    User,
)
from app.models.catalogue import Product
from app.models.commerce import OnlineStore
from app.models.organisation import Branch, LocationKind, StockLocation
from app.models.platform import (
    Subscription,
    SubscriptionStatus,
    Tenant,
    TenantStatus,
)

DEFAULT_BRANCH_NAME = "Main Branch"
SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    slug = SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "shop"


def unique_slug(db: Session, model: type, column, base: str) -> str:
    slug = base
    suffix = 1
    while db.execute(select(model).where(column == slug)).first() is not None:
        suffix += 1
        slug = f"{base}-{suffix}"
        if suffix > 50:
            slug = f"{base}-{generate_share_token(4)}"
            break
    return slug


@dataclass(slots=True)
class RegistrationResult:
    tenant: Tenant
    user: User
    membership: TenantMembership
    branch: Branch
    location: StockLocation


def seed_roles(db: Session, tenant_id: uuid.UUID) -> dict[RoleName, Role]:
    """Create the four default role bundles for a new business (PRD 5.1)."""
    roles: dict[RoleName, Role] = {}
    for role_name, permissions in DEFAULT_ROLE_PERMISSIONS.items():
        role = Role(
            tenant_id=tenant_id,
            name=role_name.value,
            label=role_name.value.replace("_", " ").title(),
            description=ROLE_DESCRIPTIONS[role_name],
            is_system=True,
        )
        db.add(role)
        db.flush()
        for permission in sorted(permissions, key=str):
            db.add(RolePermission(role_id=role.id, permission=permission))
        roles[role_name] = role
    db.flush()
    return roles


def register_business(
    db: Session,
    *,
    business_name: str,
    full_name: str,
    email: str,
    password: str,
    phone: str | None = None,
    branch_name: str | None = None,
    locale: str = "en",
    trial_days: int | None = None,
) -> RegistrationResult:
    email = email.strip().lower()
    if not business_name.strip():
        raise ValidationError("Business name is required")
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise ConflictError("An account with this email already exists")

    tenant = Tenant(
        name=business_name.strip(),
        slug=unique_slug(db, Tenant, Tenant.slug, slugify(business_name)),
        status=TenantStatus.TRIAL,
        phone=phone,
        email=email,
        currency=settings.default_currency,
        locale=locale,
        timezone="Africa/Addis_Ababa",
    )
    db.add(tenant)
    db.flush()

    roles = seed_roles(db, tenant.id)

    user = User(
        email=email,
        full_name=full_name.strip(),
        phone=phone,
        password_hash=hash_password(password),
        locale=locale,
        is_active=True,
    )
    db.add(user)
    db.flush()

    membership = TenantMembership(
        tenant_id=tenant.id,
        user_id=user.id,
        role_id=roles[RoleName.OWNER].id,
        status=MembershipStatus.ACTIVE,
        has_all_branches=True,
        accepted_at=utcnow(),
    )
    db.add(membership)

    branch = Branch(
        tenant_id=tenant.id,
        name=(branch_name or DEFAULT_BRANCH_NAME).strip(),
        is_default=True,
        is_active=True,
        phone=phone,
    )
    db.add(branch)
    db.flush()

    location = StockLocation(
        tenant_id=tenant.id,
        branch_id=branch.id,
        name=branch.name,
        kind=LocationKind.SHOP,
        is_default=True,
    )
    db.add(location)

    db.add(
        OnlineStore(
            tenant_id=tenant.id,
            slug=unique_slug(db, OnlineStore, OnlineStore.slug, tenant.slug),
            display_name=tenant.name,
            contact_phone=phone,
            contact_email=email,
            is_published=False,
        )
    )

    days = trial_days if trial_days is not None else settings.default_trial_days
    today = date.today()
    db.add(
        Subscription(
            tenant_id=tenant.id,
            status=SubscriptionStatus.TRIALING,
            trial_started_on=today,
            trial_ends_on=today + timedelta(days=days),
            current_period_ends_on=today + timedelta(days=days),
        )
    )

    record_audit(
        db,
        action=AuditAction.TENANT_REGISTERED,
        tenant_id=tenant.id,
        actor_user_id=user.id,
        actor_label=user.email,
        entity_type="tenant",
        entity_id=tenant.id,
        summary=f"Registered {tenant.name} with a {days}-day trial",
    )
    db.flush()
    return RegistrationResult(
        tenant=tenant, user=user, membership=membership, branch=branch, location=location
    )


@dataclass(slots=True)
class SetupStep:
    key: str
    label: str
    done: bool
    action_url: str | None = None


def setup_progress(db: Session, ctx: AuthContext) -> list[SetupStep]:
    """The home-screen checklist of next recommended actions (PRD 6)."""
    product_count = db.execute(
        select(func.count()).select_from(Product).where(Product.tenant_id == ctx.tenant_id)
    ).scalar_one()
    branch_count = db.execute(
        select(func.count()).select_from(Branch).where(Branch.tenant_id == ctx.tenant_id)
    ).scalar_one()
    staff_count = db.execute(
        select(func.count())
        .select_from(TenantMembership)
        .where(TenantMembership.tenant_id == ctx.tenant_id)
    ).scalar_one()
    from app.models.sales import Sale

    sale_count = db.execute(
        select(func.count()).select_from(Sale).where(Sale.tenant_id == ctx.tenant_id)
    ).scalar_one()
    store = db.execute(tenant_query(OnlineStore, ctx.tenant_id)).scalars().first()
    published_count = db.execute(
        select(func.count())
        .select_from(Product)
        .where(Product.tenant_id == ctx.tenant_id, Product.is_published.is_(True))
    ).scalar_one()

    return [
        SetupStep("business_profile", "Complete your business details", bool(ctx.tenant.phone), "/settings/business"),
        SetupStep("first_product", "Add or import your products", product_count > 0, "/products/new"),
        SetupStep("pricing_rule", "Set a default pricing rule", _has_pricing_rule(db, ctx), "/settings/pricing"),
        SetupStep("first_sale", "Record your first sale", sale_count > 0, "/sales/new"),
        SetupStep("invite_staff", "Invite your team", staff_count > 1, "/settings/team"),
        SetupStep("add_branch", "Add another branch", branch_count > 1, "/settings/branches"),
        SetupStep(
            "publish_online",
            "Publish a product to your online shop",
            bool(store and store.is_published and published_count > 0),
            "/shop/settings",
        ),
    ]


def _has_pricing_rule(db: Session, ctx: AuthContext) -> bool:
    from app.models.catalogue import PricingRule

    return (
        db.execute(
            select(func.count())
            .select_from(PricingRule)
            .where(PricingRule.tenant_id == ctx.tenant_id, PricingRule.is_active.is_(True))
        ).scalar_one()
        > 0
    )


def load_auth_context(db: Session, user: User, tenant_id: uuid.UUID) -> AuthContext:
    """Build the request's authorisation context, or refuse if not a member."""
    from app.core.errors import PermissionDenied

    membership = db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user.id,
            TenantMembership.status == MembershipStatus.ACTIVE,
        )
    ).scalar_one_or_none()
    if membership is None:
        raise PermissionDenied("You do not have access to this business")
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise PermissionDenied("You do not have access to this business")
    return build_auth_context(user, tenant, membership)


def invite_user(
    db: Session,
    ctx: AuthContext,
    *,
    email: str,
    full_name: str,
    role_name: str,
    branch_ids: list[uuid.UUID] | None = None,
    all_branches: bool = False,
) -> TenantMembership:
    """Invite a staff member to this business (PRD 6)."""
    ctx.require(Permission.USER_MANAGE)
    email = email.strip().lower()
    role = db.execute(
        tenant_query(Role, ctx.tenant_id).where(Role.name == role_name)
    ).scalar_one_or_none()
    if role is None:
        raise ValidationError(f"Unknown role '{role_name}'")

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(email=email, full_name=full_name.strip(), is_active=True)
        db.add(user)
        db.flush()

    existing = db.execute(
        tenant_query(TenantMembership, ctx.tenant_id).where(
            TenantMembership.user_id == user.id
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("This person is already part of the business")

    membership = TenantMembership(
        tenant_id=ctx.tenant_id,
        user_id=user.id,
        role_id=role.id,
        status=MembershipStatus.INVITED,
        has_all_branches=all_branches,
        invited_at=utcnow(),
        invitation_token=generate_share_token(),
    )
    db.add(membership)
    db.flush()

    for branch_id in branch_ids or []:
        branch = db.execute(
            tenant_query(Branch, ctx.tenant_id).where(Branch.id == branch_id)
        ).scalar_one_or_none()
        if branch is None:
            raise ValidationError("Branch not found")
        db.add(BranchAssignment(membership_id=membership.id, branch_id=branch.id))

    record_audit(
        db,
        action=AuditAction.USER_INVITED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="tenant_membership",
        entity_id=membership.id,
        summary=f"Invited {email} as {role_name}",
    )
    db.flush()
    return membership


def accept_invitation(db: Session, *, token: str, password: str, full_name: str | None = None) -> TenantMembership:
    membership = db.execute(
        select(TenantMembership).where(TenantMembership.invitation_token == token)
    ).scalar_one_or_none()
    if membership is None or membership.status != MembershipStatus.INVITED:
        raise ValidationError("This invitation is no longer valid")

    user = membership.user
    user.password_hash = hash_password(password)
    if full_name:
        user.full_name = full_name.strip()
    user.email_verified_at = utcnow()
    membership.status = MembershipStatus.ACTIVE
    membership.accepted_at = utcnow()
    membership.invitation_token = None
    db.flush()
    return membership
