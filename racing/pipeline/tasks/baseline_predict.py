"""
Phase 1 baseline predictions.

In Phase 1 (no Punting Form data), the only signal is market-implied probability.
This job writes those market-implied probs directly into the predictions table with
model_version = "phase1_market_baseline" and confidence_score = None, so the API
has something to return and the edge column is meaningful (always 0.0 in Phase 1,
since model_prob == market_prob — the UI shows this as the locked/greyed state).

Once Phase 2 form data is available and a real model is trained, the scheduler
switches to calling the real inference job instead of this one.
"""

import logging
from datetime import date, datetime, timezone

from racing.db.client import get_supabase
from racing.pipeline.betfair.market_utils import implied_probabilities, RunnerOdds

log = logging.getLogger(__name__)

MODEL_VERSION = "phase1_market_baseline"


def run_for_date(race_date: date | None = None) -> None:
    """
    For every upcoming race on race_date, pull the latest odds tick per runner,
    compute overround-adjusted implied probabilities, and upsert into predictions.

    Runs after the nightly batch has seeded races/runners. If no odds ticks exist
    yet (pre-market), writes null probs so the row still exists for the API.
    """
    if race_date is None:
        from datetime import timedelta
        race_date = date.today() + timedelta(days=1)

    log.info("Phase 1 baseline predict for %s", race_date)
    db = get_supabase()
    now = datetime.now(timezone.utc).isoformat()

    races = (
        db.table("races")
        .select("id, betfair_market_id")
        .eq("race_date", race_date.isoformat())
        .in_("status", ["upcoming", "open"])
        .execute()
    )

    total_written = 0
    for race in races.data:
        race_id = race["id"]

        runners_res = (
            db.table("runners")
            .select("id, betfair_selection_id, scratched")
            .eq("race_id", race_id)
            .execute()
        )

        if not runners_res.data:
            continue

        # Pull latest tick per runner in one query, then pick max ticked_at per runner
        runner_ids = [r["id"] for r in runners_res.data]
        ticks_res = (
            db.table("odds_ticks")
            .select("runner_id, win_back, win_lay, ticked_at")
            .in_("runner_id", runner_ids)
            .order("ticked_at", desc=True)
            .execute()
        )

        # Deduplicate to latest tick per runner
        latest_tick: dict[str, dict] = {}
        for t in ticks_res.data:
            rid = t["runner_id"]
            if rid not in latest_tick:
                latest_tick[rid] = t

        # Build RunnerOdds for implied prob calculation
        runner_odds = []
        for r in runners_res.data:
            tick = latest_tick.get(r["id"])
            runner_odds.append(RunnerOdds(
                selection_id=int(r["betfair_selection_id"]),
                name="",
                win_back=tick["win_back"] if tick else None,
                win_lay=tick["win_lay"] if tick else None,
                scratched=r["scratched"],
            ))

        sel_to_runner_id = {
            int(r["betfair_selection_id"]): r["id"] for r in runners_res.data
        }
        implied = implied_probabilities(runner_odds)

        predictions = []
        for sel_id, imp_prob in implied.items():
            runner_id = sel_to_runner_id.get(sel_id)
            if not runner_id:
                continue

            tick = latest_tick.get(runner_id)
            odds_at_pred = tick["win_back"] if tick else None

            predictions.append({
                "runner_id": runner_id,
                "model_version": MODEL_VERSION,
                "predicted_at": now,
                "win_prob": imp_prob if imp_prob > 0 else None,
                "place_prob": None,
                "confidence_score": None,  # Phase 1: locked/greyed in UI
                "market_implied_prob": imp_prob if imp_prob > 0 else None,
                "market_odds_at_pred": odds_at_pred,
                "edge": 0.0,  # Phase 1: model == market, always 0
                "feature_snapshot": None,
            })

        if predictions:
            db.table("predictions").upsert(
                predictions,
                on_conflict="runner_id,model_version,predicted_at",
            ).execute()
            total_written += len(predictions)

    log.info("Phase 1 baseline: wrote %d predictions for %s", total_written, race_date)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    run_for_date()
