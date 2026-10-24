"""Password hashing and JWT issuing/verification."""

from __future__ import annotations

import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.core.errors import AuthenticationError

#: bcrypt truncates at 72 bytes; reject longer input rather than silently ignore it.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError("Password must be at most 72 bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    *,
    subject: uuid.UUID,
    tenant_id: uuid.UUID | None,
    is_platform_admin: bool = False,
    expires_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    ttl = expires_minutes or settings.access_token_ttl_minutes
    payload: dict[str, Any] = {
        "sub": str(subject),
        "tid": str(tenant_id) if tenant_id else None,
        "pa": is_platform_admin,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl)).timestamp()),
        "jti": secrets.token_urlsafe(12),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Session expired, please sign in again") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid authentication token") from exc


def generate_share_token(nbytes: int = 24) -> str:
    """Unguessable token for secure share links (proformas, receipts)."""
    return secrets.token_urlsafe(nbytes)


#: No 0/O, 1/I/L — a buyer reads these out over the phone.
_REFERENCE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def generate_public_reference(prefix: str, *, year: int, length: int = 8) -> str:
    """A short, quotable reference for a record that belongs to no one tenant.

    Tenant documents get sequential numbers from a locked per-business row
    (``app/services/numbering.py``).  A marketplace request spans businesses,
    so there is no such row to lock without serialising every shop on the
    platform behind one sequence — and a sequential public reference would
    tell anyone who asked for two how many requests the platform handles.

    Random it is, from an alphabet without characters people confuse.  Eight
    characters of 31 is 8.5e11 combinations, so a collision becomes likely
    somewhere around a million requests rather than thirty thousand — and the
    caller retries on one anyway, with a unique constraint behind that.
    """
    body = "".join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(length))
    return f"{prefix}-{year}-{body}"


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
