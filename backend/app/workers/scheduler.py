"""Background job runner for reminders, alerts and trial expiry (PRD 18).

Run it as a separate process:

    python -m app.workers.scheduler            # run the daily jobs once
    python -m app.workers.scheduler --loop     # keep running, once per interval

The jobs are idempotent for a given day, so a missed run catches up on the
next one and a double run does not duplicate anything.
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import asdict, dataclass
from datetime import date

from app.core.db import SessionLocal
from app.services.notifications import run_due_reminders, run_low_stock_alerts
from app.services.subscription import expire_lapsed_trials, warn_expiring_trials

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("estock.worker")

DEFAULT_INTERVAL_SECONDS = 3600


@dataclass(slots=True)
class DailyRunResult:
    run_date: str
    reminders_delivered: int = 0
    reminders_skipped: int = 0
    reminders_failed: int = 0
    low_stock_alerts: int = 0
    trials_expired: int = 0
    trials_warned: int = 0


def run_daily_jobs(*, on: date | None = None) -> DailyRunResult:
    """One pass of the scheduled work, in its own transaction."""
    on = on or date.today()
    result = DailyRunResult(run_date=on.isoformat())

    with SessionLocal() as db:
        try:
            reminders = run_due_reminders(db, on=on)
            result.reminders_delivered = reminders.delivered
            result.reminders_skipped = reminders.skipped_settled
            result.reminders_failed = reminders.failed

            result.low_stock_alerts = run_low_stock_alerts(db).alerts_created
            result.trials_expired = len(expire_lapsed_trials(db, today=on))
            result.trials_warned = warn_expiring_trials(db, today=on)

            db.commit()
        except Exception:
            db.rollback()
            logger.exception("daily_jobs_failed run_date=%s", result.run_date)
            raise

    logger.info("daily_jobs_completed %s", asdict(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Estock background job runner")
    parser.add_argument(
        "--loop", action="store_true", help="keep running instead of exiting after one pass"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"seconds between passes when looping (default {DEFAULT_INTERVAL_SECONDS})",
    )
    args = parser.parse_args()

    if not args.loop:
        run_daily_jobs()
        return

    logger.info("worker_started interval=%ss", args.interval)
    while True:
        try:
            run_daily_jobs()
        except Exception:  # noqa: BLE001 - a failed pass must not kill the worker
            logger.exception("pass_failed; retrying next interval")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
