"""Users, tenant membership, roles and branch assignment."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import GUID, Base, UTCDateTime
from app.core.permissions import Permission, RoleName
from app.models.base import (
    CodeText,
    MediumText,
    ShortText,
    TenantScoped,
    Timestamped,
    UUIDPrimaryKey,
    enum_column,
)


class MembershipStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    DISABLED = "disabled"


class User(UUIDPrimaryKey, Timestamped, Base):
    """A person who signs in.  Identity is global; authority comes from membership."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(MediumText, nullable=False, unique=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    full_name: Mapped[str] = mapped_column(ShortText, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    locale: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    memberships: Mapped[list[TenantMembership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Role(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """A named permission bundle.  Seeded per tenant from the defaults (PRD 5.1)."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),)

    name: Mapped[str] = mapped_column(CodeText, nullable=False)
    label: Mapped[str] = mapped_column(ShortText, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="role", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def permission_set(self) -> set[Permission]:
        return {rp.permission for rp in self.permissions}

    @property
    def is_owner_role(self) -> bool:
        return self.name == RoleName.OWNER


class RolePermission(UUIDPrimaryKey, Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission", name="uq_role_permissions_role_permission"),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission: Mapped[Permission] = mapped_column(enum_column(Permission), nullable=False)

    role: Mapped[Role] = relationship(back_populates="permissions")


class TenantMembership(UUIDPrimaryKey, Timestamped, TenantScoped, Base):
    """Links a user to a business with a role (PRD 5.1)."""

    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[MembershipStatus] = mapped_column(
        enum_column(MembershipStatus), default=MembershipStatus.ACTIVE, nullable=False
    )
    #: Access to every branch, including branches created later.
    has_all_branches: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    invited_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    invitation_token: Mapped[str | None] = mapped_column(String(64), index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship(back_populates="memberships", lazy="joined")
    role: Mapped[Role] = relationship(lazy="joined")
    branch_assignments: Mapped[list[BranchAssignment]] = relationship(
        back_populates="membership", cascade="all, delete-orphan", lazy="selectin"
    )
    permission_grants: Mapped[list[UserPermissionGrant]] = relationship(
        back_populates="membership", cascade="all, delete-orphan", lazy="selectin"
    )

    def effective_permissions(self) -> set[Permission]:
        """Role bundle plus explicit grants, minus explicit revocations."""
        permissions = set(self.role.permission_set) if self.role else set()
        for grant in self.permission_grants:
            if grant.granted:
                permissions.add(grant.permission)
            else:
                permissions.discard(grant.permission)
        return permissions

    def branch_ids(self) -> set[uuid.UUID]:
        return {assignment.branch_id for assignment in self.branch_assignments}


class BranchAssignment(UUIDPrimaryKey, Base):
    """Which branches a membership may operate in (PRD 4)."""

    __tablename__ = "branch_assignments"
    __table_args__ = (
        UniqueConstraint(
            "membership_id", "branch_id", name="uq_branch_assignments_membership_branch"
        ),
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenant_memberships.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True
    )

    membership: Mapped[TenantMembership] = relationship(back_populates="branch_assignments")


class UserPermissionGrant(UUIDPrimaryKey, Base):
    """Per-user override on top of the role bundle (grant or revoke)."""

    __tablename__ = "user_permission_grants"
    __table_args__ = (
        UniqueConstraint(
            "membership_id", "permission", name="uq_user_permission_grants_membership_permission"
        ),
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenant_memberships.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission: Mapped[Permission] = mapped_column(enum_column(Permission), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    membership: Mapped[TenantMembership] = relationship(back_populates="permission_grants")
