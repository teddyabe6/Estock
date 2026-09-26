"""Business profile, branches, team and subscription (PRD 4, 5, 17)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.audit import AuditAction, record_audit
from app.core.deps import Ctx, DbSession
from app.core.errors import ValidationError
from app.core.permissions import Permission
from app.core.tenancy import get_tenant_object, tenant_query
from app.models.access import BranchAssignment, MembershipStatus, Role, TenantMembership
from app.models.organisation import Branch, LocationKind, StockLocation
from app.models.platform import AuditEvent
from app.schemas.auth import BranchOut, InviteRequest, MembershipOut, UserOut, normalise_et_phone
from app.services import subscription as subscription_service
from app.services.onboarding import invite_user, setup_progress

router = APIRouter(tags=["business"])


class BusinessOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    tin: str | None = None
    business_type: str | None = None
    currency: str
    locale: str
    timezone: str
    allow_negative_stock: bool
    require_customer_for_credit: bool
    hide_out_of_stock_online: bool
    reminder_lead_days: int
    #: Fractional: 0.15 means 15%.  Applied to products with no rate of their own.
    default_tax_rate: Decimal | None = None
    status: str


class BusinessUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    phone: str | None = Field(None, max_length=32)
    email: str | None = Field(None, max_length=255)
    address: str | None = Field(None, max_length=255)
    tin: str | None = Field(None, max_length=64)
    business_type: str | None = Field(None, max_length=120)
    locale: str | None = Field(None, pattern="^(en|am)$")
    timezone: str | None = Field(None, max_length=64)
    allow_negative_stock: bool | None = None
    require_customer_for_credit: bool | None = None
    hide_out_of_stock_online: bool | None = None
    reminder_lead_days: int | None = Field(None, ge=0, le=60)
    default_tax_rate: Decimal | None = Field(None, ge=0, le=1)


class BranchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str | None = Field(None, max_length=64)
    phone: str | None = Field(None, max_length=32)
    address: str | None = Field(None, max_length=255)
    notes: str | None = Field(None, max_length=2000)
    is_active: bool | None = None


@router.get("/business", response_model=BusinessOut)
def get_business(ctx: Ctx) -> BusinessOut:
    ctx.require(Permission.BUSINESS_VIEW)
    tenant = ctx.tenant
    return BusinessOut(
        id=tenant.id,
        name=tenant.name,
        phone=tenant.phone,
        email=tenant.email,
        address=tenant.address,
        tin=tenant.tin,
        business_type=tenant.business_type,
        currency=tenant.currency,
        locale=tenant.locale,
        timezone=tenant.timezone,
        allow_negative_stock=tenant.allow_negative_stock,
        require_customer_for_credit=tenant.require_customer_for_credit,
        hide_out_of_stock_online=tenant.hide_out_of_stock_online,
        reminder_lead_days=tenant.reminder_lead_days,
        default_tax_rate=tenant.default_tax_rate,
        status=str(tenant.status),
    )


@router.patch("/business", response_model=BusinessOut)
def update_business(payload: BusinessUpdate, ctx: Ctx, db: DbSession) -> BusinessOut:
    ctx.require(Permission.BUSINESS_MANAGE)
    changes = payload.model_dump(exclude_unset=True)
    if "phone" in changes:
        changes["phone"] = normalise_et_phone(changes["phone"])
    if "timezone" in changes:
        from app.core.clock import tzinfo_for

        if str(tzinfo_for(changes["timezone"])) != changes["timezone"]:
            raise ValidationError(f"Unknown timezone '{changes['timezone']}'")
    # Enabling negative stock is a deliberate policy change, so it is audited.
    if "allow_negative_stock" in changes:
        ctx.require(Permission.SETTINGS_MANAGE)
        record_audit(
            db,
            action=AuditAction.TENANT_STATUS_CHANGED,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            entity_type="tenant",
            entity_id=ctx.tenant_id,
            summary=f"allow_negative_stock set to {changes['allow_negative_stock']}",
        )
    for key, value in changes.items():
        setattr(ctx.tenant, key, value)
    db.flush()
    return get_business(ctx)


@router.get("/branches", response_model=list[BranchOut])
def list_branches(ctx: Ctx, db: DbSession) -> list[BranchOut]:
    ctx.require(Permission.BRANCH_VIEW)
    branches = db.execute(
        tenant_query(Branch, ctx.tenant_id).order_by(Branch.is_default.desc(), Branch.name)
    ).scalars().all()
    if not ctx.all_branches:
        branches = [b for b in branches if b.id in ctx.assigned_branch_ids]
    return [BranchOut.model_validate(b) for b in branches]


@router.post("/branches", response_model=BranchOut, status_code=status.HTTP_201_CREATED)
def create_branch(payload: BranchIn, ctx: Ctx, db: DbSession) -> BranchOut:
    ctx.require(Permission.BRANCH_MANAGE)
    branch = Branch(
        tenant_id=ctx.tenant_id,
        name=payload.name.strip(),
        code=payload.code or None,
        phone=normalise_et_phone(payload.phone),
        address=payload.address,
        notes=payload.notes,
        is_default=False,
    )
    db.add(branch)
    db.flush()
    db.add(
        StockLocation(
            tenant_id=ctx.tenant_id,
            branch_id=branch.id,
            name=branch.name,
            kind=LocationKind.SHOP,
            is_default=True,
        )
    )
    record_audit(
        db,
        action=AuditAction.BRANCH_CREATED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        entity_type="branch",
        entity_id=branch.id,
        summary=f"Created branch {branch.name}",
    )
    db.flush()
    return BranchOut.model_validate(branch)


@router.patch("/branches/{branch_id}", response_model=BranchOut)
def update_branch(
    branch_id: uuid.UUID, payload: BranchIn, ctx: Ctx, db: DbSession
) -> BranchOut:
    ctx.require(Permission.BRANCH_MANAGE)
    branch = get_tenant_object(db, Branch, branch_id, ctx.tenant_id, label="Branch")
    changes = payload.model_dump(exclude_unset=True)
    if "phone" in changes:
        changes["phone"] = normalise_et_phone(changes["phone"])
    if "code" in changes:
        changes["code"] = changes["code"] or None
    if changes.get("is_active") is False and branch.is_default:
        raise ValidationError("The main branch cannot be deactivated")
    for key, value in changes.items():
        setattr(branch, key, value)
    db.flush()
    return BranchOut.model_validate(branch)


@router.get("/locations")
def list_locations(ctx: Ctx, db: DbSession) -> list[dict]:
    ctx.require(Permission.STOCK_VIEW)
    visible = set(ctx.visible_branch_ids(db))
    rows = db.execute(
        tenant_query(StockLocation, ctx.tenant_id).order_by(StockLocation.name)
    ).scalars()
    return [
        {
            "id": str(location.id),
            "name": location.name,
            "branch_id": str(location.branch_id),
            "kind": str(location.kind),
            "is_default": location.is_default,
        }
        for location in rows
        if location.branch_id in visible
    ]


@router.get("/team", response_model=list[MembershipOut])
def list_team(ctx: Ctx, db: DbSession) -> list[MembershipOut]:
    ctx.require(Permission.USER_VIEW)
    memberships = db.execute(
        tenant_query(TenantMembership, ctx.tenant_id)
    ).scalars().all()
    return [
        MembershipOut(
            id=m.id,
            user=UserOut.model_validate(m.user),
            role_name=m.role.name,
            status=str(m.status),
            has_all_branches=m.has_all_branches,
            branch_ids=sorted(m.branch_ids()),
        )
        for m in memberships
    ]


@router.post("/team/invite", response_model=MembershipOut, status_code=status.HTTP_201_CREATED)
def invite(payload: InviteRequest, ctx: Ctx, db: DbSession) -> MembershipOut:
    membership = invite_user(
        db,
        ctx,
        email=payload.email,
        full_name=payload.full_name,
        role_name=payload.role_name,
        branch_ids=payload.branch_ids,
        all_branches=payload.all_branches,
    )
    return MembershipOut(
        id=membership.id,
        user=UserOut.model_validate(membership.user),
        role_name=membership.role.name,
        status=str(membership.status),
        has_all_branches=membership.has_all_branches,
        branch_ids=sorted(membership.branch_ids()),
    )


class MembershipUpdate(BaseModel):
    role_name: str | None = None
    branch_ids: list[uuid.UUID] | None = None
    all_branches: bool | None = None
    status: str | None = Field(None, pattern="^(active|disabled)$")


@router.patch("/team/{membership_id}", response_model=MembershipOut)
def update_membership(
    membership_id: uuid.UUID, payload: MembershipUpdate, ctx: Ctx, db: DbSession
) -> MembershipOut:
    ctx.require(Permission.USER_MANAGE)
    membership = get_tenant_object(
        db, TenantMembership, membership_id, ctx.tenant_id, label="Team member"
    )
    if membership.user_id == ctx.user_id and payload.status == "disabled":
        raise ValidationError("You cannot disable your own access")

    if payload.role_name:
        role = db.execute(
            tenant_query(Role, ctx.tenant_id).where(Role.name == payload.role_name)
        ).scalar_one_or_none()
        if role is None:
            raise ValidationError(f"Unknown role '{payload.role_name}'")
        if membership.role.is_owner_role and not role.is_owner_role:
            _assert_not_last_owner(db, ctx, membership)
        membership.role_id = role.id
        record_audit(
            db,
            action=AuditAction.USER_ROLE_CHANGED,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            entity_type="tenant_membership",
            entity_id=membership.id,
            summary=f"Role set to {payload.role_name}",
        )

    if payload.all_branches is not None:
        membership.has_all_branches = payload.all_branches
    if payload.branch_ids is not None:
        for assignment in list(membership.branch_assignments):
            db.delete(assignment)
        db.flush()
        for branch_id in payload.branch_ids:
            get_tenant_object(db, Branch, branch_id, ctx.tenant_id, label="Branch")
            db.add(BranchAssignment(membership_id=membership.id, branch_id=branch_id))
    if payload.status == "disabled":
        if membership.role.is_owner_role:
            _assert_not_last_owner(db, ctx, membership)
        membership.status = MembershipStatus.DISABLED
        record_audit(
            db,
            action=AuditAction.USER_DISABLED,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            entity_type="tenant_membership",
            entity_id=membership.id,
            summary=f"Disabled {membership.user.email}",
        )
    elif payload.status == "active":
        membership.status = MembershipStatus.ACTIVE

    db.flush()
    return MembershipOut(
        id=membership.id,
        user=UserOut.model_validate(membership.user),
        role_name=membership.role.name,
        status=str(membership.status),
        has_all_branches=membership.has_all_branches,
        branch_ids=sorted(membership.branch_ids()),
    )


def _assert_not_last_owner(db, ctx, membership) -> None:
    """A business must always keep at least one active owner."""
    owners = db.execute(
        tenant_query(TenantMembership, ctx.tenant_id).where(
            TenantMembership.status == MembershipStatus.ACTIVE
        )
    ).scalars().all()
    remaining = [
        m for m in owners if m.role.is_owner_role and m.id != membership.id
    ]
    if not remaining:
        raise ValidationError(
            "This is the only owner. Make someone else an owner first."
        )


@router.get("/roles")
def list_roles(ctx: Ctx, db: DbSession) -> list[dict]:
    ctx.require(Permission.USER_VIEW)
    roles = db.execute(tenant_query(Role, ctx.tenant_id).order_by(Role.name)).scalars()
    return [
        {
            "id": str(role.id),
            "name": role.name,
            "label": role.label,
            "description": role.description,
            "permissions": sorted(str(p) for p in role.permission_set),
        }
        for role in roles
    ]


@router.get("/setup-progress")
def get_setup_progress(ctx: Ctx, db: DbSession) -> list[dict]:
    ctx.require(Permission.BUSINESS_VIEW)
    return [
        {"key": s.key, "label": s.label, "done": s.done, "action_url": s.action_url}
        for s in setup_progress(db, ctx)
    ]


@router.get("/subscription")
def get_subscription(ctx: Ctx, db: DbSession) -> dict:
    ctx.require(Permission.BUSINESS_VIEW)
    return subscription_service.describe(db, ctx.tenant).as_dict()


@router.get("/audit-events")
def list_audit_events(
    ctx: Ctx, db: DbSession, limit: int = 50, offset: int = 0
) -> list[dict]:
    ctx.require(Permission.AUDIT_VIEW)
    rows = db.execute(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == ctx.tenant_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(min(limit, 200))
        .offset(offset)
    ).scalars()
    return [
        {
            "id": str(event.id),
            "created_at": event.created_at.isoformat(),
            "action": event.action,
            "summary": event.summary,
            "entity_type": event.entity_type,
            "entity_id": str(event.entity_id) if event.entity_id else None,
            "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        }
        for event in rows
    ]
