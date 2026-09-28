"""Poll the Telegram bot for shop owners pressing Start (PRD 14).

    python -m app.workers.telegram            # one pass
    python -m app.workers.telegram --loop     # keep polling

Only needed when the bot has no webhook.  With TELEGRAM_WEBHOOK_SECRET set,
point the bot's webhook at /api/v1/public/telegram/webhook instead.
"""

from __future__ import annotations

import argparse
import logging
import time

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.messaging import sync_telegram_links

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("estock.telegram")


def run_once() -> int:
    with SessionLocal() as db:
        try:
            linked = sync_telegram_links(db)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("telegram_sync_failed")
            raise
    if linked:
        logger.info("telegram_links_completed count=%s", linked)
    return linked


def main() -> None:
    parser = argparse.ArgumentParser(description="Estock Telegram link poller")
    parser.add_argument("--loop", action="store_true", help="keep polling")
    parser.add_argument("--interval", type=int, default=10, help="seconds between polls")
    args = parser.parse_args()
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN is not set; nothing to poll")
        return
    if settings.telegram_webhook_secret:
        logger.warning("TELEGRAM_WEBHOOK_SECRET is set; the webhook receives updates, not this poller")
    while True:
        run_once()
        if not args.loop:
            break
        time.sleep(max(args.interval, 1))


if __name__ == "__main__":
    main()
