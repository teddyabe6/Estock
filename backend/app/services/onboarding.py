"""Registration and first-run setup (PRD 6).

Registering creates the tenant, its role bundles, the owner membership, a
default branch with a stock location, a storefront record and a trial
subscription — so the first product or sale needs no further configuration.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, record_audit
from app.core.clock import local_today
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
DEFAULT_TIMEZONE = "Africa/Addis_Ababa"
SLUG_RE = re.compile(r"[^a-z0-9]+")

logger = logging.getLogger(__name__)


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
        timezone=DEFAULT_TIMEZONE,
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
    today = local_today(tenant.timezone)
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

    # Links are routes in the web app; keep them in step with web/src/app.
    return [
        SetupStep(
            "business_profile",
            "Complete your business details",
            bool(ctx.tenant.phone and ctx.tenant.address),
            "/settings#business",
        ),
        SetupStep("first_product", "Add or import your products", product_count > 0, "/products?add=1"),
        SetupStep("pricing_rule", "Set a default pricing rule", _has_pricing_rule(db, ctx), "/settings#pricing"),
        SetupStep("first_sale", "Record your first sale", sale_count > 0, "/sales/new"),
        SetupStep("invite_staff", "Invite your team", staff_count > 1, "/settings#team"),
        SetupStep("add_branch", "Add another branch", branch_count > 1, "/settings#branches"),
        SetupStep(
            "publish_online",
            "Publish a product to your online shop",
            bool(store and store.is_published and published_count > 0),
            "/shop",
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


def load_auth_context(
    db: Session, user: User, tenant_id: uuid.UUID, *, support: bool = False
) -> AuthContext:
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
    return build_auth_context(user, tenant, membership, support=support)


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

    from app.services.notifications import send_email

    send_email(
        to=email,
        subject=f"You have been invited to {ctx.tenant.name} on Estock",
        body=(
            f"Hello {full_name.strip()},\n\n{ctx.user.full_name} has invited you to work in "
            f"{ctx.tenant.name} as {role.label}. Open this link to accept:\n\n"
            f"{invitation_link(membership)}\n"
        ),
    )
    return membership


def invitation_link(membership: TenantMembership) -> str | None:
    """The accept link for a pending invitation, or None once it has been used.

    Shown to the inviter as well as emailed, because a shop without an email
    provider configured still needs a way to hand the link over (PRD 6).
    """
    if membership.status != MembershipStatus.INVITED or not membership.invitation_token:
        return None
    return f"{settings.public_base_url}/accept-invitation?token={membership.invitation_token}"


def accept_invitation(
    db: Session, *, token: str, password: str | None = None, full_name: str | None = None
) -> TenantMembership:
    """Activate an invited membership.

    A person invited to a second business already has a password; the
    invitation must not be a way to replace it, so an existing password is
    kept and the one supplied here is ignored.  Only an account that has never
    signed in takes its password from the invitation.
    """
    membership = db.execute(
        select(TenantMembership).where(TenantMembership.invitation_token == token)
    ).scalar_one_or_none()
    if membership is None or membership.status != MembershipStatus.INVITED:
        raise ValidationError("This invitation is no longer valid")

    user = membership.user
    if user.password_hash is None:
        if not password:
            raise ValidationError("Choose a password to finish setting up your account")
        user.password_hash = hash_password(password)
        if full_name:
            user.full_name = full_name.strip()
        user.email_verified_at = user.email_verified_at or utcnow()
    membership.status = MembershipStatus.ACTIVE
    membership.accepted_at = utcnow()
    membership.invitation_token = None
    db.flush()
    return membership


# --------------------------------------------------------------------------- #
# Account recovery (PRD 20)
# --------------------------------------------------------------------------- #


def request_password_reset(db: Session, *, email: str) -> User | None:
    """Issue a single-use reset token and hand it to the email transport.

    Returns the user when one exists; the API answers the same way either way
    so the endpoint never confirms whether an address is registered.
    """
    from app.services.notifications import send_email

    email = email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not user.is_active:
        return None

    user.password_reset_token = generate_share_token(32)
    user.password_reset_expires_at = utcnow() + timedelta(
        minutes=settings.password_reset_ttl_minutes
    )
    db.flush()

    link = f"{settings.public_base_url}/reset-password?token={user.password_reset_token}"
    send_email(
        to=user.email,
        subject="Reset your Estock password",
        body=(
            f"Hello {user.full_name},\n\nUse this link to choose a new password. It works "
            f"once and expires in {settings.password_reset_ttl_minutes} minutes.\n\n{link}\n\n"
            "If you did not ask for this, you can ignore it; your password is unchanged."
        ),
    )
    return user


def reset_password(db: Session, *, token: str, password: str) -> User:
    user = db.execute(
        select(User).where(User.password_reset_token == token)
    ).scalar_one_or_none()
    if (
        user is None
        or user.password_reset_expires_at is None
        or user.password_reset_expires_at < utcnow()
    ):
        raise ValidationError("This reset link is no longer valid. Request a new one.")

    user.password_hash = hash_password(password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    user.email_verified_at = user.email_verified_at or utcnow()
    db.flush()
    logger.info("password_reset user_id=%s", user.id)
    return user
