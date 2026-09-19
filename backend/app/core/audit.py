"""Audit trail helper.

Privileged actions, financial corrections, stock adjustments, due-date changes
and support access are all recorded here (PRD 20).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.models.platform import AuditEvent


class AuditAction:
    TENANT_REGISTERED = "tenant.registered"
    TENANT_STATUS_CHANGED = "tenant.status_changed"
    USER_INVITED = "user.invited"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_DISABLED = "user.disabled"
    BRANCH_CREATED = "branch.created"
    PRODUCT_IMPORTED = "product.imported"
    PRICING_RULE_CHANGED = "pricing.rule_changed"
    STOCK_ADJUSTED = "stock.adjusted"
    STOCK_COUNT_POSTED = "stock.count_posted"
    STOCK_TRANSFER_DISPATCHED = "stock.transfer_dispatched"
    STOCK_TRANSFER_RECEIVED = "stock.transfer_received"
    NEGATIVE_STOCK_ALLOWED = "stock.negative_allowed"
    SALE_COMPLETED = "sale.completed"
    SALE_VOIDED = "sale.voided"
    PURCHASE_RECEIVED = "purchase.received"
    PAYMENT_RECORDED = "payment.recorded"
    PAYMENT_REVERSED = "payment.reversed"
    CREDIT_DUE_DATE_CHANGED = "credit.due_date_changed"
    CREDIT_CANCELLED = "credit.cancelled"
    CREDIT_LIMIT_OVERRIDDEN = "credit.limit_overridden"
    DISCOUNT_APPROVED = "discount.approved"
    QUOTATION_SENT = "quotation.sent"
    QUOTATION_CONVERTED = "quotation.converted"
    SUBSCRIPTION_CHANGED = "subscription.changed"
    PLATFORM_SUPPORT_ACCESS = "platform.support_access"


def record_audit(
    db: Session,
    *,
    action: str,
    tenant_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_platform_admin_id: uuid.UUID | None = None,
    actor_label: str | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    summary: str | None = None,
    payload: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        created_at=utcnow(),
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        actor_platform_admin_id=actor_platform_admin_id,
        actor_label=actor_label,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        payload_json=json.dumps(payload, default=str) if payload else None,
        ip_address=ip_address,
    )
    db.add(event)
    # Flush so the trail is queryable immediately; sessions run with autoflush off.
    db.flush()
    return event
