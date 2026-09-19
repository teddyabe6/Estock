"""FastAPI dependencies: authentication, tenant context and permission guards."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AuthenticationError, PermissionDenied, SubscriptionInactive
from app.core.permissions import Permission
from app.core.security import decode_access_token
from app.core.tenancy import AuthContext
from app.models.access import User
from app.models.platform import PlatformAdmin

DbSession = Annotated[Session, Depends(get_db)]


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("Sign in to continue")
    return authorization.split(" ", 1)[1].strip()


def get_current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    payload = decode_access_token(_bearer_token(authorization))
    if payload.get("pa"):
        raise AuthenticationError("Use the platform admin API with this token")
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthenticationError("This account is no longer active")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_auth_context(
    db: DbSession,
    user: CurrentUser,
    authorization: Annotated[str | None, Header()] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> AuthContext:
    """Resolve the business this request acts on, and the caller's authority.

    The tenant comes from the signed token; the ``X-Tenant-Id`` header may only
    select among businesses the user is actually a member of.
    """
    from app.services.onboarding import load_auth_context

    payload = decode_access_token(_bearer_token(authorization))
    tenant_id = payload.get("tid")
    if x_tenant_id:
        tenant_id = x_tenant_id
    if not tenant_id:
        raise PermissionDenied("No business selected")
    try:
        tenant_uuid = uuid.UUID(str(tenant_id))
    except ValueError as exc:
        raise PermissionDenied("No business selected") from exc
    return load_auth_context(db, user, tenant_uuid)


Ctx = Annotated[AuthContext, Depends(get_auth_context)]


def require_permissions(*permissions: Permission):
    """Route guard: ``dependencies=[Depends(require_permissions(...))]``."""

    def guard(ctx: Ctx) -> AuthContext:
        ctx.require(*permissions)
        return ctx

    return guard


def require_writable(ctx: Ctx) -> AuthContext:
    """Block posting operations for a restricted or suspended account (PRD 17)."""
    if ctx.tenant.is_read_only:
        raise SubscriptionInactive(
            "This account is read-only. Your data is safe — subscribe to continue "
            "recording new transactions."
        )
    return ctx


WritableCtx = Annotated[AuthContext, Depends(require_writable)]


def get_platform_admin(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> PlatformAdmin:
    """Separate identity boundary from tenant users (PRD 5.2)."""
    payload = decode_access_token(_bearer_token(authorization))
    if not payload.get("pa"):
        raise PermissionDenied("Platform administrator access is required")
    admin = db.get(PlatformAdmin, uuid.UUID(payload["sub"]))
    if admin is None or not admin.is_active:
        raise AuthenticationError("This administrator account is no longer active")
    return admin


PlatformAdminUser = Annotated[PlatformAdmin, Depends(get_platform_admin)]


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
