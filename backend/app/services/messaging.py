"""Getting an order or a proforma request in front of a shop owner (PRD 14).

Email goes through the same transport seam as everything else.  Telegram goes
through a bot: the Bot API can only message a chat that has opened the bot, so
an owner links their shop once by pressing *Start* with a one-time code, and
from then on every order or request for that shop is delivered to that chat.
A username alone is not enough for delivery, which is why the link step
exists.  Without a bot token both channels are logged rather than sent, so
development and CI never depend on a provider.
"""

from __future__ import annotations

import html
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_share_token
from app.models.commerce import OnlineStore
from app.models.platform import Tenant
from app.services.notifications import send_email

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class TelegramSender:
    """Transport seam.  The default logs instead of sending."""

    def send(self, *, chat_id: str, text: str) -> bool:
        logger.info("telegram.not_configured chat_id=%s text=%s", chat_id, text[:80])
        return False

    def updates(self, *, offset: int | None = None) -> list[dict]:
        return []


class BotApiTelegramSender(TelegramSender):
    """The real thing, over the Bot API with httpx."""

    def __init__(self, token: str):
        self.token = token

    def _call(self, method: str, payload: dict) -> dict | None:
        import httpx

        try:
            response = httpx.post(
                f"{TELEGRAM_API}/bot{self.token}/{method}", json=payload, timeout=10
            )
            data = response.json()
        except Exception:  # network trouble is logged, never raised into a checkout
            logger.exception("telegram.%s_failed", method)
            return None
        if not data.get("ok"):
            logger.warning("telegram.%s_rejected %s", method, data.get("description"))
            return None
        return data

    def send(self, *, chat_id: str, text: str) -> bool:
        data = self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        return data is not None

    def updates(self, *, offset: int | None = None) -> list[dict]:
        payload: dict = {"timeout": 0, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        data = self._call("getUpdates", payload)
        return list(data.get("result", [])) if data else []


def default_telegram_sender() -> TelegramSender:
    if settings.telegram_bot_token:
        return BotApiTelegramSender(settings.telegram_bot_token)
    return TelegramSender()


_telegram_sender: TelegramSender | None = None


def telegram_sender() -> TelegramSender:
    global _telegram_sender
    if _telegram_sender is None:
        _telegram_sender = default_telegram_sender()
    return _telegram_sender


def set_telegram_sender(sender: TelegramSender | None) -> None:
    global _telegram_sender
    _telegram_sender = sender


def send_telegram(*, chat_id: str, text: str) -> bool:
    return telegram_sender().send(chat_id=chat_id, text=text)


# --------------------------------------------------------------------------- #
# Linking a shop to a Telegram chat
# --------------------------------------------------------------------------- #


def telegram_start_url(code: str) -> str | None:
    if not settings.telegram_bot_username:
        return None
    return f"https://t.me/{settings.telegram_bot_username.lstrip('@')}?start={code}"


def begin_telegram_link(db: Session, store: OnlineStore) -> str:
    """Mint the one-time code the owner sends to the bot with /start."""
    store.telegram_link_code = generate_share_token(16)
    db.flush()
    return store.telegram_link_code


def unlink_telegram(db: Session, store: OnlineStore) -> None:
    store.telegram_chat_id = None
    store.telegram_link_code = None
    db.flush()


def complete_telegram_link(
    db: Session, *, code: str, chat_id: str, username: str | None = None
) -> OnlineStore | None:
    store = db.execute(
        select(OnlineStore).where(OnlineStore.telegram_link_code == code)
    ).scalar_one_or_none()
    if store is None:
        return None
    store.telegram_chat_id = str(chat_id)
    store.telegram_link_code = None
    if username and not store.telegram_username:
        store.telegram_username = username
    db.flush()
    send_telegram(
        chat_id=str(chat_id),
        text=(
            f"✅ <b>{html.escape(store.display_name)}</b> is connected. New orders and "
            "proforma requests from your online shop will arrive here."
        ),
    )
    return store


def process_telegram_update(db: Session, update: dict) -> OnlineStore | None:
    """Handle one Bot API update: only ``/start <code>`` does anything."""
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    if not text.startswith("/start") or not chat.get("id"):
        return None
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        send_telegram(
            chat_id=str(chat["id"]),
            text="Open your shop's settings in Estock and use the Connect Telegram link.",
        )
        return None
    return complete_telegram_link(
        db,
        code=parts[1].strip(),
        chat_id=str(chat["id"]),
        username=(message.get("from") or {}).get("username"),
    )


def sync_telegram_links(db: Session, *, sender: TelegramSender | None = None) -> int:
    """Poll the bot for /start messages (for deployments without a webhook)."""
    sender = sender or telegram_sender()
    updates = sender.updates()
    linked = 0
    last_id: int | None = None
    for update in updates:
        last_id = update.get("update_id", last_id)
        if process_telegram_update(db, update) is not None:
            linked += 1
    if last_id is not None:
        # Confirm the batch so the bot does not hand it back next time.
        sender.updates(offset=last_id + 1)
    return linked


# --------------------------------------------------------------------------- #
# Telling a shop about an order or a request
# --------------------------------------------------------------------------- #


def notify_store(
    db: Session,
    store: OnlineStore,
    tenant: Tenant,
    *,
    subject: str,
    lines: list[str],
    link: str,
) -> dict[str, bool]:
    """Email the shop, and message its Telegram chat when one is linked.

    ``lines`` is the body, one item per element; it only ever contains this
    shop's part of a checkout.
    """
    body = "\n".join(lines)
    to = store.contact_email or tenant.email
    email_sent = bool(to) and send_email(
        to=to, subject=subject, body=f"{body}\n\nOpen it: {link}\n"
    )
    telegram_sent = False
    if store.telegram_chat_id:
        text = f"<b>{html.escape(subject)}</b>\n" + "\n".join(
            html.escape(line) for line in lines
        )
        telegram_sent = send_telegram(
            chat_id=store.telegram_chat_id, text=f"{text}\n\n{html.escape(link)}"
        )
    return {"email": email_sent, "telegram": telegram_sent}


def store_and_tenant(db: Session, tenant_id: uuid.UUID) -> tuple[OnlineStore, Tenant] | None:
    store = db.execute(
        select(OnlineStore).where(OnlineStore.tenant_id == tenant_id)
    ).scalar_one_or_none()
    tenant = db.get(Tenant, tenant_id)
    if store is None or tenant is None:
        return None
    return store, tenant
