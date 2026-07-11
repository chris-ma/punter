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
    """
    from datetime import datetime, timezone

    db = get_supabase()

    race_res = db.table("races").select("id").eq("id", race_id).maybe_single().execute()
    if not race_res.data:
        raise HTTPException(status_code=404, detail="Race not found")

    runners_res = (
        db.table("runners").select("*").eq("race_id", race_id).execute()
    )

    now = datetime.now(timezone.utc)
    output = []

    for r in runners_res.data:
        runner_id = r["id"]

        # Latest model prediction
        pred = (
            db.table("predictions")
            .select("win_prob, market_implied_prob, edge, confidence_score")
            .eq("runner_id", runner_id)
            .order("predicted_at", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )

        # Latest odds tick
        tick = (
            db.table("odds_ticks")
            .select("win_back, ticked_at")
            .eq("runner_id", runner_id)
            .order("ticked_at", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )

        data_age = None
        win_back = None
        if tick.data:
            ticked_at = datetime.fromisoformat(tick.data["ticked_at"])
            data_age = (now - ticked_at).total_seconds()
            win_back = tick.data["win_back"]

        output.append(RunnerSummary(
            id=runner_id,
            horse_name=r["horse_name"],
            barrier=r.get("barrier"),
            jockey=r.get("jockey"),
            trainer=r.get("trainer"),
            weight_kg=r.get("weight_kg"),
            scratched=r["scratched"],
            win_prob=pred.data.get("win_prob") if pred.data else None,
            market_implied_prob=pred.data.get("market_implied_prob") if pred.data else None,
            edge=pred.data.get("edge") if pred.data else None,
            confidence_score=pred.data.get("confidence_score") if pred.data else None,
            win_back=win_back,
            data_age_seconds=data_age,
        ))

    # Sort by win_prob descending (nulls last)
    output.sort(key=lambda x: (x.win_prob is None, -(x.win_prob or 0)))
    return output
