"""
Live polling task — fetches odds snapshots from The Odds API and writes
odds ticks + recomputes edge against cached nightly-batch predictions.

Called by the scheduler on an adaptive interval (60s default, 15s near jump).
"""

import logging
from datetime import datetime, timedelta, timezone

from racing.config import settings
from racing.db.client import get_supabase
from racing.pipeline.betfair.market_utils import implied_probabilities, RunnerOdds, edge
from racing.pipeline.odds_api.client import RaceSnapshot, fetch_au_racing_odds

log = logging.getLogger(__name__)


def run() -> None:
    """
    Fetch current AU racing odds from The Odds API, persist ticks,
    detect scratchings, and refresh edge for all active races.
    """
    snapshots = fetch_au_racing_odds()
    if not snapshots:
        log.debug("No snapshots returned from Odds API")
        return

    db = get_supabase()
    for snap in snapshots:
        _process_snapshot(db, snap)


def _process_snapshot(db, snap: RaceSnapshot) -> None:
    now = snap.captured_at.isoformat()

    race_res = (
        db.table("races")
        .select("id")
        .eq("betfair_market_id", snap.event_id)
        .maybe_single()
        .execute()
    )
    if not race_res.data:
        log.debug("Unknown event %s — not yet seeded, skipping tick", snap.event_id)
        return

    race_id = race_res.data["id"]

    runners_res = (
        db.table("runners")
        .select("id, horse_name, scratched")
        .eq("race_id", race_id)
        .execute()
    )
    name_to_runner: dict[str, dict] = {r["horse_name"]: r for r in runners_res.data}

    # Detect scratchings: runners in DB but absent from current odds snapshot
    snap_names = {r.name for r in snap.runners}
    for db_runner in runners_res.data:
        if not db_runner["scratched"] and db_runner["horse_name"] not in snap_names:
            _mark_scratched(db, db_runner["id"], race_id)

    # Build RunnerOdds for implied prob calc
    runner_odds_list = [
        RunnerOdds(
            selection_id=0,  # not used in implied_probabilities by name
            name=r.name,
            win_back=r.price,
            win_lay=None,
            scratched=(r.name not in snap_names),
        )
        for r in snap.runners
    ]

    # Compute implied probs by name (not selection_id) for Odds API data
    name_probs = _implied_probs_by_name(snap.runners)

    ticks = []
    for runner in snap.runners:
        db_runner = name_to_runner.get(runner.name)
        if not db_runner:
            continue

        ticks.append({
            "runner_id": db_runner["id"],
            "ticked_at": now,
            "win_back": runner.price,
            "win_lay": None,
            "win_traded_vol": None,
            "data_source": "odds_api",
        })

    if ticks:
        db.table("odds_ticks").insert(ticks).execute()

    # Refresh edge against cached model predictions
    _refresh_edge(db, race_id, name_to_runner, name_probs, snap.captured_at)


def _implied_probs_by_name(runners: list) -> dict[str, float]:
    """Overround-adjusted win probabilities keyed by runner name."""
    raw: dict[str, float] = {}
    for r in runners:
        if r.price and r.price > 1.0:
            raw[r.name] = 1.0 / r.price

    total = sum(raw.values())
    if total <= 0:
        return {}
    return {name: p / total for name, p in raw.items()}


def _mark_scratched(db, runner_id: str, race_id: str) -> None:
    log.info("Scratching detected: runner %s in race %s", runner_id, race_id)
    db.table("runners").update({
        "scratched": True,
        "scratched_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", runner_id).execute()


def _refresh_edge(
    db,
    race_id: str,
    name_to_runner: dict[str, dict],
    name_probs: dict[str, float],
    at: datetime,
) -> None:
    for name, imp_prob in name_probs.items():
        db_runner = name_to_runner.get(name)
        if not db_runner or imp_prob <= 0:
            continue

        pred_res = (
            db.table("predictions")
            .select("id, win_prob")
            .eq("runner_id", db_runner["id"])
            .order("predicted_at", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )
        if not pred_res.data:
            continue

        new_edge = edge(float(pred_res.data["win_prob"]), imp_prob)
        db.table("predictions").update({
            "market_implied_prob": imp_prob,
            "edge": new_edge,
        }).eq("id", pred_res.data["id"]).execute()


def poll_interval_for(jump_at: datetime) -> int:
    now = datetime.now(timezone.utc)
    mins_to_jump = (jump_at - now).total_seconds() / 60
    if mins_to_jump <= settings.live_poll_near_jump_window_minutes:
        return settings.live_poll_near_jump_seconds
    return settings.live_poll_interval_seconds


def staleness_threshold() -> timedelta:
    return timedelta(seconds=settings.live_poll_interval_seconds * 3)
