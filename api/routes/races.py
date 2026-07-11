from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from racing.db.client import get_supabase

router = APIRouter()


class RaceSummary(BaseModel):
    id: str
    betfair_market_id: str
    track: str
    state: str
    race_name: str | None
    race_number: int | None
    scheduled_jump_at: str
    distance_m: int | None
    going: str | None
    field_size: int | None
    status: str
    form_fetched_at: str | None


class RunnerSummary(BaseModel):
    id: str
    horse_name: str
    barrier: int | None
    jockey: str | None
    trainer: str | None
    weight_kg: float | None
    scratched: bool
    win_prob: float | None
    market_implied_prob: float | None
    edge: float | None
    confidence_score: float | None
    win_back: float | None       # latest tick price
    data_age_seconds: float | None   # None = no live data yet


@router.get("/", response_model=list[RaceSummary])
def list_races(
    race_date: date = Query(default_factory=date.today),
    state: str | None = None,
):
    """List all races for a given date, optionally filtered by state."""
    db = get_supabase()
    q = db.table("races").select("*").eq("race_date", race_date.isoformat())
    if state:
        q = q.eq("state", state.upper())
    q = q.order("scheduled_jump_at")
    res = q.execute()
    return res.data


@router.get("/{race_id}", response_model=RaceSummary)
def get_race(race_id: str):
    db = get_supabase()
    res = db.table("races").select("*").eq("id", race_id).maybe_single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Race not found")
    return res.data


@router.get("/{race_id}/runners", response_model=list[RunnerSummary])
def get_race_runners(race_id: str):
    """
    Returns all runners for a race, with their latest model prediction and
    live odds tick merged in. Ranked by win_prob descending.

    Returns data-freshness metadata so the UI can flag stale odds.
    Uses 3 bulk queries (runners, predictions, ticks) rather than N+1 per runner.
    """
    from datetime import datetime, timezone

    db = get_supabase()

    race_res = db.table("races").select("id").eq("id", race_id).maybe_single().execute()
    if not race_res.data:
        raise HTTPException(status_code=404, detail="Race not found")

    runners_res = db.table("runners").select("*").eq("race_id", race_id).execute()
    if not runners_res.data:
        return []

    runner_ids = [r["id"] for r in runners_res.data]

    # Bulk fetch latest prediction per runner
    preds_res = (
        db.table("predictions")
        .select("runner_id, win_prob, market_implied_prob, edge, confidence_score, predicted_at")
        .in_("runner_id", runner_ids)
        .order("predicted_at", desc=True)
        .execute()
    )
    # Deduplicate to most recent prediction per runner
    latest_pred: dict[str, dict] = {}
    for p in preds_res.data:
        if p["runner_id"] not in latest_pred:
            latest_pred[p["runner_id"]] = p

    # Bulk fetch latest tick per runner
    ticks_res = (
        db.table("odds_ticks")
        .select("runner_id, win_back, ticked_at")
        .in_("runner_id", runner_ids)
        .order("ticked_at", desc=True)
        .execute()
    )
    latest_tick: dict[str, dict] = {}
    for t in ticks_res.data:
        if t["runner_id"] not in latest_tick:
            latest_tick[t["runner_id"]] = t

    now = datetime.now(timezone.utc)
    output = []

    for r in runners_res.data:
        runner_id = r["id"]
        pred = latest_pred.get(runner_id)
        tick = latest_tick.get(runner_id)

        data_age = None
        win_back = None
        if tick:
            ticked_at = datetime.fromisoformat(tick["ticked_at"])
            data_age = (now - ticked_at).total_seconds()
            win_back = tick["win_back"]

        output.append(RunnerSummary(
            id=runner_id,
            horse_name=r["horse_name"],
            barrier=r.get("barrier"),
            jockey=r.get("jockey"),
            trainer=r.get("trainer"),
            weight_kg=r.get("weight_kg"),
            scratched=r["scratched"],
            win_prob=pred["win_prob"] if pred else None,
            market_implied_prob=pred["market_implied_prob"] if pred else None,
            edge=pred["edge"] if pred else None,
            confidence_score=pred["confidence_score"] if pred else None,
            win_back=win_back,
            data_age_seconds=data_age,
        ))

    # Sort by win_prob descending (nulls last)
    output.sort(key=lambda x: (x.win_prob is None, -(x.win_prob or 0)))
    return output
