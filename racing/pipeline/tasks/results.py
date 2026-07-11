"""
Post-race results ingestion.

The Odds API does not provide finishing positions or settlement data.
Results will be sourced from Punting Form API in Phase 2.

For Phase 1, this module:
  - Marks past races as 'closed' based on scheduled jump time
  - Leaves outcomes table empty (no ground truth until Phase 2)
  - Logs a clear message so the operator knows why outcomes are absent

When Phase 2 (Punting Form API) is active, _fetch_punting_form_results()
will be called to populate the outcomes table with real finishing positions.
"""

import logging
from datetime import datetime, timezone

from racing.config import settings
from racing.db.client import get_supabase

log = logging.getLogger(__name__)


def mark_races_closed() -> None:
    """Mark races whose scheduled_jump_at has passed as 'closed'."""
    db = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    result = (
        db.table("races")
        .update({"status": "closed"})
        .eq("status", "open")
        .lt("scheduled_jump_at", now)
        .execute()
    )
    if result.data:
        log.info("Marked %d races as closed", len(result.data))


def run() -> None:
    """
    Attempt to ingest results for closed races.
    Phase 1: no results source available — logs a warning.
    Phase 2: calls Punting Form API for finishing positions.
    """
    if settings.is_phase2:
        _fetch_punting_form_results()
        return

    db = get_supabase()
    closed = (
        db.table("races")
        .select("id, betfair_market_id, race_name")
        .eq("status", "closed")
        .execute()
    )

    # Find which have no outcomes yet
    unsettled = []
    for race in closed.data:
        existing = (
            db.table("outcomes")
            .select("id")
            .eq("race_id", race["id"])
            .limit(1)
            .execute()
        )
        if not existing.data:
            unsettled.append(race)

    if unsettled:
        log.info(
            "%d closed races have no outcomes yet — results require Phase 2 (Punting Form API). "
            "Race IDs: %s",
            len(unsettled),
            [r["id"] for r in unsettled],
        )
    else:
        log.debug("No unsettled races found")


def _fetch_punting_form_results() -> None:
    """Phase 2 stub — fetch finishing positions from Punting Form API."""
    log.info("Phase 2 results ingestion (stub) — Punting Form API not yet implemented")
    raise NotImplementedError("Phase 2 results ingestion not yet implemented")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    mark_races_closed()
    run()
