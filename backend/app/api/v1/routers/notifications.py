"""In-app notifications (PRD 9, 11.4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.deps import Ctx, DbSession
from app.models.system import Notification
from app.services.notifications import mark_read

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    ctx: Ctx,
    db: DbSession,
    unread_only: bool = False,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    stmt = select(Notification).where(
        Notification.tenant_id == ctx.tenant_id, Notification.user_id == ctx.user_id
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    unread = db.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.tenant_id == ctx.tenant_id,
            Notification.user_id == ctx.user_id,
            Notification.read_at.is_(None),
        )
    ).scalar_one()
    rows = db.execute(
        stmt.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    ).scalars()

    return {
        "total": total,
        "unread": unread,
        "items": [
            {
                "id": str(n.id),
                "kind": str(n.kind),
                "title": n.title,
                "body": n.body,
                "link": n.link,
                "created_at": n.created_at.isoformat(),
                "read": n.read_at is not None,
            }
            for n in rows
        ],
    }


@router.post("/{notification_id}/read")
def read(notification_id: uuid.UUID, ctx: Ctx, db: DbSession) -> dict:
    mark_read(db, ctx.tenant_id, ctx.user_id, notification_id)
    return {"ok": True}
