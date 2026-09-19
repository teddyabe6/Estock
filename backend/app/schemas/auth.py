"""Registration, sign-in and identity schemas."""

from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import Schema

#: Ethiopian numbers, local (09..., 07...) or international (+251...) (PRD 16).
ET_PHONE_RE = re.compile(r"^(?:\+251|251|0)?(9|7)\d{8}$")


def normalise_et_phone(value: str | None) -> str | None:
    """Store Ethiopian numbers in one canonical ``+251...`` form."""
    if not value:
        return None
    cleaned = re.sub(r"[\s\-()]", "", value.strip())
    if not ET_PHONE_RE.match(cleaned):
        # Keep non-Ethiopian numbers as entered rather than rejecting them.
        return cleaned or None
    digits = cleaned.lstrip("+")
    if digits.startswith("251"):
        digits = digits[3:]
    digits = digits.lstrip("0")
    return f"+251{digits}"


class RegisterRequest(BaseModel):
    business_name: str = Field(min_length=2, max_length=120)
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    phone: str | None = None
    branch_name: str | None = Field(None, max_length=120)
    locale: str = "en"

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        return normalise_et_phone(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    tenant_id: uuid.UUID | None = None
    user: UserOut


class UserOut(Schema):
    id: uuid.UUID
    email: str
    full_name: str
    phone: str | None = None
    locale: str = "en"


class BranchOut(Schema):
    id: uuid.UUID
    name: str
    code: str | None = None
    phone: str | None = None
    address: str | None = None
    is_default: bool = False
    is_active: bool = True


class MembershipOut(Schema):
    id: uuid.UUID
    user: UserOut
    role_name: str
    status: str
    has_all_branches: bool
    branch_ids: list[uuid.UUID] = []


class SessionOut(BaseModel):
    """Everything a client needs after sign-in to render the right UI."""

    user: UserOut
    tenant_id: uuid.UUID
    tenant_name: str
    currency: str
    locale: str
    role: str
    permissions: list[str]
    all_branches: bool
    branches: list[BranchOut]
    subscription: dict


class InviteRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    role_name: str
    branch_ids: list[uuid.UUID] = []
    all_branches: bool = False


class AcceptInviteRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=72)
    full_name: str | None = None


TokenResponse.model_rebuild()
