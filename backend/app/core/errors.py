"""Domain errors mapped to HTTP responses by the application error handlers."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for expected, user-correctable failures."""

    status_code = 400
    code = "domain_error"

    def __init__(self, message: str, *, code: str | None = None, details: object = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class PermissionDenied(DomainError):
    status_code = 403
    code = "permission_denied"


class AuthenticationError(DomainError):
    status_code = 401
    code = "not_authenticated"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class ValidationError(DomainError):
    status_code = 422
    code = "validation_error"


class InsufficientStock(DomainError):
    status_code = 409
    code = "insufficient_stock"


class SubscriptionInactive(DomainError):
    status_code = 402
    code = "subscription_inactive"


class PlanLimitReached(DomainError):
    """The plan's ceiling on branches, users or products, not a permission problem.

    402 like :class:`SubscriptionInactive`, because the answer is a commercial
    one — upgrade or free a slot — and a separate code so a client can tell the
    two apart.
    """

    status_code = 402
    code = "plan_limit_reached"
