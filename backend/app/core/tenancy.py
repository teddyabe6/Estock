"""Request-scoped authorisation context and tenant-safe query helpers.

Tenant isolation is enforced here, on the server, and never by client-side
filtering (PRD 20).  Every read of an operational table goes through
:func:`tenant_query`, which cannot be called without a tenant id.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, TypeVar

from sqlalchemy import ColumnElement, Select, or_, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, PermissionDenied
from app.core.permissions import READ_ONLY_PERMISSIONS, Permission
from app.models.access import TenantMembership, User
from app.models.organisation import Branch, StockLocation
from app.models.platform import Tenant

ModelT = TypeVar("ModelT")


@dataclass(slots=True)
class AuthContext:
    """Who is acting, for which business, with what authority."""

    user: User
    tenant: Tenant
    membership: TenantMembership
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    #: Branch ids the user may operate in; empty with ``all_branches`` set means all.
    assigned_branch_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    all_branches: bool = False
    #: A platform-support session: may look at everything the user may, but
    #: never change anything (PRD 5.2).
    is_support: bool = False

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.tenant.id

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    def has(self, *permissions: Permission) -> bool:
        return all(p in self.permissions for p in permissions)

    def has_any(self, *permissions: Permission) -> bool:
        return any(p in self.permissions for p in permissions)

    def require(self, *permissions: Permission) -> None:
        missing = [p for p in permissions if p not in self.permissions]
        if missing:
            raise PermissionDenied(
                "You do not have permission to perform this action",
                details={"missing_permissions": [str(p) for p in missing]},
            )

    def can_access_branch(self, branch_id: uuid.UUID | None) -> bool:
        if branch_id is None:
            return True
        if self.all_branches:
            return True
        return branch_id in self.assigned_branch_ids

    def require_branch(self, branch_id: uuid.UUID | None) -> None:
        if not self.can_access_branch(branch_id):
            raise PermissionDenied("You do not have access to this branch")

    def visible_branch_ids(self, db: Session) -> list[uuid.UUID]:
        """Branch ids this user may see, resolved against the tenant."""
        if self.all_branches:
            rows = db.execute(
                select(Branch.id).where(Branch.tenant_id == self.tenant_id)
            ).scalars()
            return list(rows)
        return list(self.assigned_branch_ids)


def build_auth_context(
    user: User, tenant: Tenant, membership: TenantMembership, *, support: bool = False
) -> AuthContext:
    permissions = frozenset(membership.effective_permissions())
    if support:
        permissions = permissions & READ_ONLY_PERMISSIONS
    return AuthContext(
        user=user,
        tenant=tenant,
        membership=membership,
        permissions=permissions,
        assigned_branch_ids=frozenset(membership.branch_ids()),
        all_branches=membership.has_all_branches,
        is_support=support,
    )


def in_branches(column: ColumnElement, branch_ids: list[uuid.UUID]) -> ColumnElement:
    """Rows in the given branches, plus rows that belong to no branch.

    ``column.in_([..., None])`` looks like it does this but never matches a
    NULL — SQL's ``IN`` compares with ``=`` — so business-wide rows would
    silently vanish from every branch-filtered list.
    """
    return or_(column.in_(branch_ids), column.is_(None))


def tenant_query(model: type[ModelT], tenant_id: uuid.UUID) -> Select[tuple[ModelT]]:
    """``SELECT`` already filtered to one tenant.

    Prefer this over ``select(Model)`` everywhere; it makes forgetting the
    tenant filter a visible omission rather than a silent leak.
    """
    return select(model).where(model.tenant_id == tenant_id)  # type: ignore[attr-defined]


def get_tenant_object(
    db: Session,
    model: type[ModelT],
    object_id: uuid.UUID | None,
    tenant_id: uuid.UUID,
    *,
    label: str | None = None,
    required: bool = True,
) -> ModelT | None:
    """Fetch one row, refusing to cross the tenant boundary.

    A row belonging to another tenant is reported as *not found* rather than
    *forbidden*, so the API never confirms that an id exists elsewhere.
    """
    if object_id is None:
        if required:
            raise NotFoundError(f"{label or model.__name__} is required")
        return None
    obj = db.execute(
        tenant_query(model, tenant_id).where(model.id == object_id)  # type: ignore[attr-defined]
    ).scalar_one_or_none()
    if obj is None and required:
        raise NotFoundError(f"{label or model.__name__} not found")
    return obj


def resolve_branch(
    db: Session, ctx: AuthContext, branch_id: uuid.UUID | None
) -> Branch:
    """Resolve the branch to act in, defaulting to the user's only branch."""
    if branch_id is None:
        candidates = ctx.visible_branch_ids(db)
        if len(candidates) == 1:
            branch_id = candidates[0]
        else:
            default = db.execute(
                tenant_query(Branch, ctx.tenant_id).where(Branch.is_default.is_(True))
            ).scalar_one_or_none()
            if default is None:
                raise NotFoundError("Select a branch for this operation")
            branch_id = default.id
    branch = get_tenant_object(db, Branch, branch_id, ctx.tenant_id, label="Branch")
    ctx.require_branch(branch.id)
    return branch


def resolve_location(
    db: Session, ctx: AuthContext, branch: Branch, location_id: uuid.UUID | None
) -> StockLocation:
    """Resolve a stock location inside a branch, defaulting to its main location."""
    if location_id is not None:
        location = get_tenant_object(
            db, StockLocation, location_id, ctx.tenant_id, label="Stock location"
        )
        if location.branch_id != branch.id:
            raise PermissionDenied("Stock location does not belong to this branch")
        return location
    location = db.execute(
        tenant_query(StockLocation, ctx.tenant_id)
        .where(StockLocation.branch_id == branch.id)
        .order_by(StockLocation.is_default.desc(), StockLocation.created_at.asc())
    ).scalars().first()
    if location is None:
        raise NotFoundError("This branch has no stock location")
    return location


def scrub_cost_fields(ctx: AuthContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Drop cost and profit fields for users without ``cost:view`` (PRD 8.2)."""
    if ctx.has(Permission.COST_VIEW):
        return payload
    hidden = {
        "purchase_price",
        "transport_cost",
        "other_costs",
        "landed_cost",
        "average_cost",
        "cost_total",
        "unit_cost",
        "gross_profit",
        "profit",
        "margin",
        "stock_value_at_cost",
    }
    return {k: v for k, v in payload.items() if k not in hidden}
