"""
Nightly batch job.

Seeds the races/runners tables from The Odds API for the next day's
AU thoroughbred events. Runs once nightly; idempotent (upserts).

Phase 2 (when PUNTING_FORM_API_KEY is set): additionally pulls form, class,
weight, jockey/trainer data from Punting Form and runs model inference.
"""

import hashlib
import logging
from datetime import date, datetime, timezone

from racing.config import settings
from racing.db.client import get_supabase
from racing.pipeline.odds_api.client import fetch_au_racing_odds

log = logging.getLogger(__name__)


def _stable_selection_id(event_id: str, runner_name: str) -> int:
    """
    Generate a stable integer ID for a runner from (event_id, runner_name).
    The Odds API identifies runners by name only; we need a stable int for our schema.
    Uses the first 8 hex chars of SHA-256 as a positive 32-bit int.
    """
    digest = hashlib.sha256(f"{event_id}:{runner_name}".encode()).hexdigest()
    return int(digest[:8], 16)


def _parse_track_and_state(race_name: str) -> tuple[str, str]:
    """
    The Odds API race name for AU racing is typically in the form:
      "Flemington R1" / "Randwick Race 3" / "Eagle Farm"
    We do a best-effort parse. Returns (track, state).
    """
    venue_state = {
        "Flemington": "VIC", "Caulfield": "VIC", "Moonee Valley": "VIC",
        "Sandown": "VIC", "Pakenham": "VIC", "Bendigo": "VIC",
        "Randwick": "NSW", "Rosehill": "NSW", "Warwick Farm": "NSW",
        "Canterbury": "NSW", "Kembla": "NSW", "Newcastle": "NSW",
        "Doomben": "QLD", "Eagle Farm": "QLD", "Gold Coast": "QLD",
        "Sunshine Coast": "QLD", "Toowoomba": "QLD",
        "Ascot": "WA", "Belmont": "WA",
        "Morphettville": "SA", "Cheltenham": "SA",
        "Hobart": "TAS", "Launceston": "TAS",
        "Darwin": "NT", "Alice Springs": "NT",
        "Canberra": "ACT",
    }
    raw = race_name.strip()
    for venue, state in venue_state.items():
        if venue.lower() in raw.lower():
            return venue, state
    # Fallback: use the whole name as track, state unknown
    return raw, "UNK"


def run(for_date: date | None = None) -> None:
    """
    Fetch upcoming AU races from The Odds API and upsert into Supabase.
    Defaults to tomorrow if for_date is not provided.
    """
    if for_date is None:
        from datetime import timedelta
        for_date = date.today() + timedelta(days=1)

    log.info("Nightly batch starting for %s", for_date)

    snapshots = fetch_au_racing_odds()
    if not snapshots:
        log.warning("No race data from Odds API — nothing seeded for %s", for_date)
        return

    # Filter to races on for_date (in UTC — close enough for seeding)
    target = snapshots
    if for_date:
        target = [
            s for s in snapshots
            if s.commence_time.date() == for_date
        ]
        log.info("%d of %d snapshots are on %s", len(target), len(snapshots), for_date)

    db = get_supabase()
    seeded_races = 0
    seeded_runners = 0

    for snap in target:
        track, state = _parse_track_and_state(snap.race_name)

        race_payload = {
            "betfair_market_id": snap.event_id,   # reusing column for odds_api event ID
            "track": track,
            "state": state,
            "race_name": snap.race_name,
            "race_date": snap.commence_time.date().isoformat(),
            "scheduled_jump_at": snap.commence_time.isoformat(),
            "status": "upcoming",
        }

        race_res = (
            db.table("races")
            .upsert(race_payload, on_conflict="betfair_market_id")
            .execute()
        )
        race_id = race_res.data[0]["id"]
        seeded_races += 1

        for runner in snap.runners:
            sel_id = _stable_selection_id(snap.event_id, runner.name)
            db.table("runners").upsert(
                {
                    "race_id": race_id,
                    "betfair_selection_id": sel_id,
                    "horse_name": runner.name,
                },
                on_conflict="race_id,betfair_selection_id",
            ).execute()
            seeded_runners += 1

    log.info(
        "Nightly batch complete: %d races, %d runners seeded for %s",
        seeded_races, seeded_runners, for_date,
    )

    if settings.is_phase2:
        _run_phase2_form_pull(db, for_date)


def _run_phase2_form_pull(db, for_date: date) -> None:
    log.info("Phase 2 form pull (stub) — would call Punting Form API for %s", for_date)
    raise NotImplementedError("Phase 2 form pull not yet implemented")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    run()
