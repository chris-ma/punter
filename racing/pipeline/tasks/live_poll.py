"""
Live polling task — receives streaming snapshots and writes odds ticks + recomputes edge.

Called by the scheduler. The BetfairStreamClient runs on its own thread and
pushes MarketSnapshots here via on_snapshot(). This module handles persistence
and edge computation against the cached nightly-batch model predictions.
"""

import logging
from datetime import datetime, timedelta, timezone

from racing.config import settings
from racing.db.client import get_supabase
from racing.pipeline.betfair.market_utils import MarketSnapshot, implied_probabilities, edge

log = logging.getLogger(__name__)


def on_snapshot(snapshot: MarketSnapshot) -> None:
    """
    Callback invoked by BetfairStreamClient on every market update.
    Persists odds ticks and refreshes edge against cached model predictions.
    """
    if snapshot.is_stale:
        _flag_stale(snapshot.market_id)
        return

    db = get_supabase()
    implied = implied_probabilities(snapshot.runners)
    now = snapshot.captured_at.isoformat()

    # Look up runner DB IDs for this market
    race_res = (
        db.table("races")
        .select("id")
        .eq("betfair_market_id", snapshot.market_id)
        .maybe_single()
        .execute()
    )
    if not race_res.data:
        log.debug("Unknown market %s — skipping tick", snapshot.market_id)
        return

    race_id = race_res.data["id"]

    runners_res = (
        db.table("runners")
        .select("id, betfair_selection_id, scratched")
        .eq("race_id", race_id)
        .execute()
    )
    runner_map: dict[int, str] = {
        int(r["betfair_selection_id"]): r["id"] for r in runners_res.data
    }

    ticks = []
    for r in snapshot.runners:
        runner_id = runner_map.get(r.selection_id)
        if not runner_id:
            continue

        # Handle scratching detection
        existing = next(
            (row for row in runners_res.data if row["id"] == runner_id), None
        )
        if existing and not existing["scratched"] and r.scratched:
            _mark_scratched(db, runner_id, race_id)

        ticks.append({
            "runner_id": runner_id,
            "ticked_at": now,
            "win_back": r.win_back,
            "win_lay": r.win_lay,
            "win_traded_vol": r.traded_vol,
            "data_source": "betfair_stream",
        })

    if ticks:
        db.table("odds_ticks").insert(ticks).execute()

    # Refresh edge for each runner against cached model prediction
    _refresh_edge(db, race_id, runner_map, implied, snapshot.captured_at)


def _mark_scratched(db, runner_id: str, race_id: str) -> None:
    """Marks a runner as scratched and logs the event."""
    log.info("Scratching detected: runner %s in race %s", runner_id, race_id)
    db.table("runners").update({
        "scratched": True,
        "scratched_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", runner_id).execute()


def _refresh_edge(
    db,
    race_id: str,
    runner_map: dict[int, str],
    implied: dict[int, float],
    at: datetime,
) -> None:
    """
    Recomputes and upserts edge for each runner against the most recent
    model prediction (from nightly batch). No-op if no prediction exists.
    """
    for sel_id, runner_id in runner_map.items():
        imp_prob = implied.get(sel_id, 0.0)
        if imp_prob <= 0:
            continue

        pred_res = (
            db.table("predictions")
            .select("id, win_prob")
            .eq("runner_id", runner_id)
            .order("predicted_at", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )
        if not pred_res.data:
            continue

        win_prob = pred_res.data["win_prob"]
        new_edge = edge(float(win_prob), imp_prob)

        db.table("predictions").update({
            "market_implied_prob": imp_prob,
            "edge": new_edge,
        }).eq("id", pred_res.data["id"]).execute()


def _flag_stale(market_id: str) -> None:
    log.warning("Stale snapshot received for market %s — UI should show staleness", market_id)


def staleness_threshold() -> timedelta:
    """How long before we consider live data stale."""
    return timedelta(seconds=settings.live_poll_interval_seconds * 3)


def poll_interval_for(jump_at: datetime) -> int:
    """Returns the appropriate polling interval in seconds given time to jump."""
    now = datetime.now(timezone.utc)
    mins_to_jump = (jump_at - now).total_seconds() / 60
    if mins_to_jump <= settings.live_poll_near_jump_window_minutes:
        return settings.live_poll_near_jump_seconds
    return settings.live_poll_interval_seconds
