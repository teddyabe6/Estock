"""Registration, sign-in and the current session."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.core.config import settings
from app.core.db import utcnow
from app.core.deps import Ctx, CurrentUser, DbSession, client_ip, login_limiter
from app.core.errors import AuthenticationError
from app.core.security import create_access_token, verify_password
from app.core.tenancy import tenant_query
from app.models.access import MembershipStatus, TenantMembership, User
from app.models.organisation import Branch
from app.schemas.auth import (
    AcceptInviteRequest,
    BranchOut,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    SessionOut,
    TokenResponse,
    UserOut,
)
from app.schemas.common import Message
from app.services import subscription as subscription_service
from app.services.onboarding import (
    accept_invitation,
    register_business,
    request_password_reset,
    reset_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbSession, request: Request) -> TokenResponse:
    """Create the business, its first branch and the owner account (PRD 6)."""
    result = register_business(
        db,
        business_name=payload.business_name,
        full_name=payload.full_name,
        email=payload.email,
        password=payload.password,
        phone=payload.phone,
        branch_name=payload.branch_name,
        locale=payload.locale,
    )
    db.flush()
    token = create_access_token(subject=result.user.id, tenant_id=result.tenant.id)
    return TokenResponse(
        access_token=token,
        expires_in_minutes=settings.access_token_ttl_minutes,
        tenant_id=result.tenant.id,
        user=UserOut.model_validate(result.user),
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession, request: Request) -> TokenResponse:
    # Per address and per account, so a guessing run is stopped early (PRD 20).
    login_limiter.check(client_ip(request), payload.email.strip().lower())
    user = db.execute(
        select(User).where(User.email == payload.email.strip().lower())
    ).scalar_one_or_none()
    # Same message either way, so the endpoint never confirms an email exists.
    if user is None or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise AuthenticationError("Email or password is incorrect")
    if not user.is_active:
        raise AuthenticationError("This account has been disabled")

    membership = db.execute(
        select(TenantMembership).where(
            TenantMembership.user_id == user.id,
            TenantMembership.status == MembershipStatus.ACTIVE,
        )
    ).scalars().first()
    user.last_login_at = utcnow()

    token = create_access_token(
        subject=user.id, tenant_id=membership.tenant_id if membership else None
    )
    return TokenResponse(
        access_token=token,
        expires_in_minutes=settings.access_token_ttl_minutes,
        tenant_id=membership.tenant_id if membership else None,
        user=UserOut.model_validate(user),
    )


@router.post("/accept-invitation", response_model=TokenResponse)
def accept_invite(payload: AcceptInviteRequest, db: DbSession) -> TokenResponse:
    membership = accept_invitation(
        db, token=payload.token, password=payload.password, full_name=payload.full_name
    )
    token = create_access_token(
        subject=membership.user_id, tenant_id=membership.tenant_id
    )
    return TokenResponse(
        access_token=token,
        expires_in_minutes=settings.access_token_ttl_minutes,
        tenant_id=membership.tenant_id,
        user=UserOut.model_validate(membership.user),
    )


@router.post("/password-reset/request", response_model=Message)
def password_reset_request(
    payload: PasswordResetRequest, db: DbSession, request: Request
) -> Message:
    """Start account recovery.  The reply never says whether the address exists."""
    login_limiter.check(client_ip(request), "reset", payload.email.strip().lower())
    request_password_reset(db, email=payload.email)
    return Message(
        message="If that address has an account, a reset link is on its way.",
        detail=f"The link works once and expires in {settings.password_reset_ttl_minutes} minutes.",
    )


@router.post("/password-reset/confirm", response_model=Message)
def password_reset_confirm(payload: PasswordResetConfirm, db: DbSession, request: Request) -> Message:
    login_limiter.check(client_ip(request), "reset-confirm")
    reset_password(db, token=payload.token, password=payload.password)
    return Message(message="Your password has been changed. Sign in with the new one.")


@router.get("/session", response_model=SessionOut)
def current_session(ctx: Ctx, db: DbSession) -> SessionOut:
    """Everything the client needs to render only what this user may see."""
    branches = db.execute(
        tenant_query(Branch, ctx.tenant_id).order_by(Branch.is_default.desc(), Branch.name)
    ).scalars().all()
    if not ctx.all_branches:
        branches = [b for b in branches if b.id in ctx.assigned_branch_ids]

    return SessionOut(
        user=UserOut.model_validate(ctx.user),
        tenant_id=ctx.tenant_id,
        tenant_name=ctx.tenant.name,
        currency=ctx.tenant.currency,
        locale=ctx.tenant.locale,
        role=ctx.membership.role.name,
        permissions=sorted(str(p) for p in ctx.permissions),
        all_branches=ctx.all_branches,
        branches=[BranchOut.model_validate(b) for b in branches],
        subscription=subscription_service.describe(db, ctx.tenant).as_dict(),
        timezone=ctx.tenant.timezone,
        is_support=ctx.is_support,
    )


@router.get("/memberships")
def my_businesses(user: CurrentUser, db: DbSession) -> list[dict]:
    """Businesses this user belongs to, for an account-switcher."""
    memberships = db.execute(
        select(TenantMembership).where(
            TenantMembership.user_id == user.id,
            TenantMembership.status == MembershipStatus.ACTIVE,
        )
    ).scalars()
    return [
        {
            "tenant_id": str(m.tenant_id),
            "role": m.role.name,
            "all_branches": m.has_all_branches,
        }
        for m in memberships
    ]
