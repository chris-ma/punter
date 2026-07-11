"""
Scheduler entry point — `python -m racing.scheduler`

Manages the full Phase 1 pipeline lifecycle:
  - 18:00 AEST nightly: seed next day's races/runners from Betfair API
  - 18:05 AEST nightly: write Phase 1 baseline predictions (market-implied probs)
  - Continuous: Betfair streaming client for live odds
  - Every 5 min: mark past races as closed; ingest results for settled markets

All times are in AEST (Australia/Sydney) per §6.4. QLD does not observe daylight
saving but AEST/AEDT is the dominant zone for VIC/NSW which host most major racing.
For a future multi-state scheduler, each race's scheduled_jump_at is stored as UTC
and the per-race timezone is derivable from the state column.

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
from racing.pipeline.betfair.streaming import BetfairStreamClient
from racing.pipeline.tasks import baseline_predict, nightly_batch, results
from racing.pipeline.tasks.live_poll import on_snapshot

log = logging.getLogger(__name__)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


def _nightly_job() -> None:
    """Seed tomorrow's races then immediately write baseline predictions."""
    tomorrow = date.today() + timedelta(days=1)
    nightly_batch.run(for_date=tomorrow)
    baseline_predict.run_for_date(race_date=tomorrow)


def _results_job() -> None:
    """Close past races and ingest any settled results."""
    results.mark_races_closed()
    results.run()


def main() -> None:
    log.info("Racing Edge scheduler starting (phase=%s)", "2" if settings.is_phase2 else "1")

    scheduler = BackgroundScheduler(timezone="Australia/Sydney")

    # Nightly batch: seed races + baseline predictions
    scheduler.add_job(
        _nightly_job,
        CronTrigger(hour=settings.nightly_batch_hour_aest, minute=0, timezone="Australia/Sydney"),
        id="nightly_batch",
        name="Nightly race seeding + baseline predict",
        replace_existing=True,
        misfire_grace_time=3600,  # if missed, still run within 1 hour
    )

    # Results ingestion: every 5 minutes
    scheduler.add_job(
        _results_job,
        IntervalTrigger(minutes=5),
        id="results_ingestion",
        name="Close races + ingest results",
        replace_existing=True,
    )

    # Betfair streaming client — runs on its own thread, feeds on_snapshot callback
    stream_client = BetfairStreamClient(on_snapshot=on_snapshot)

    scheduler.start()
    log.info("Scheduler running. Nightly batch at %02d:00 AEST.", settings.nightly_batch_hour_aest)

    try:
        stream_client.start()
        log.info("Betfair streaming client started")
    except Exception:
        log.exception("Could not start Betfair streaming client — check credentials and certs")

    # Block until SIGINT/SIGTERM
    def _shutdown(sig, frame):
        log.info("Shutdown signal received")
        stream_client.stop()
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("Running. Press Ctrl-C to stop.")
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
