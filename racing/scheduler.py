"""
Scheduler entry point — `python -m racing.scheduler`

Manages the full Phase 1 pipeline lifecycle:
  - 18:00 AEST nightly: seed next day's races/runners from The Odds API
  - 18:05 AEST nightly: write Phase 1 baseline predictions (market-implied probs)
  - Every 60s (15s near jump): poll The Odds API for live odds + refresh edge
  - Every 5 min: mark past races as closed; log results gap (Phase 2 fills this)

Run:
    cd ~/Projects/Racing
    source .venv/bin/activate
    python -m racing.scheduler
"""

import logging
import signal
import sys
import time
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from racing.config import settings
from racing.pipeline.tasks import baseline_predict, nightly_batch, results
from racing.pipeline.tasks import live_poll

log = logging.getLogger(__name__)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


def _nightly_job() -> None:
    tomorrow = date.today() + timedelta(days=1)
    nightly_batch.run(for_date=tomorrow)
    baseline_predict.run_for_date(race_date=tomorrow)


def _results_job() -> None:
    results.mark_races_closed()
    results.run()


def main() -> None:
    log.info("Racing Edge scheduler starting (phase=%s)", "2" if settings.is_phase2 else "1")

    if not settings.odds_api_key:
        log.error("ODDS_API_KEY is not set — pipeline cannot run. Check your .env file.")
        sys.exit(1)

    scheduler = BackgroundScheduler(timezone="Australia/Sydney")

    # Nightly batch: seed races + baseline predictions
    scheduler.add_job(
        _nightly_job,
        CronTrigger(hour=settings.nightly_batch_hour_aest, minute=0, timezone="Australia/Sydney"),
        id="nightly_batch",
        name="Nightly race seeding + baseline predict",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Live odds polling: runs every 60s (15s within 10 min of jump)
    scheduler.add_job(
        live_poll.run,
        IntervalTrigger(seconds=settings.live_poll_interval_seconds),
        id="live_poll",
        name="Live odds poll",
        replace_existing=True,
    )

    # Results / race close check: every 5 minutes
    scheduler.add_job(
        _results_job,
        IntervalTrigger(minutes=5),
        id="results_check",
        name="Close races + check results",
        replace_existing=True,
    )

    scheduler.start()
    log.info(
        "Scheduler running — nightly batch at %02d:00 AEST, odds polling every %ds.",
        settings.nightly_batch_hour_aest,
        settings.live_poll_interval_seconds,
    )

    def _shutdown(sig, frame):
        log.info("Shutdown signal received")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("Running. Press Ctrl-C to stop.")
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
