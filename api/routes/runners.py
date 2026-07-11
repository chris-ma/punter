from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from racing.db.client import get_supabase

router = APIRouter()


class RunnerDetail(BaseModel):
    id: str
    race_id: str
    horse_name: str
    barrier: int | None
    jockey: str | None
    trainer: str | None
    weight_kg: float | None
    scratched: bool
    # Model output
    win_prob: float | None
    place_prob: float | None
    market_implied_prob: float | None
    edge: float | None
    confidence_score: float | None
    model_version: str | None
    predicted_at: str | None
    feature_snapshot: dict | None   # Phase 2: populated when form data available
    # Live odds
    win_back: float | None
    win_lay: float | None
    data_age_seconds: float | None


class OddsTick(BaseModel):
    ticked_at: str
    win_back: float | None
    win_lay: float | None
    win_traded_vol: float | None


@router.get("/{runner_id}", response_model=RunnerDetail)
def get_runner(runner_id: str):
    """Runner detail: model output, features, and latest tick."""
    from datetime import datetime, timezone

    db = get_supabase()
    r = db.table("runners").select("*").eq("id", runner_id).maybe_single().execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Runner not found")

    pred = (
        db.table("predictions")
        .select("*")
        .eq("runner_id", runner_id)
        .order("predicted_at", desc=True)
        .limit(1)
        .maybe_single()
        .execute()
    )

    tick = (
        db.table("odds_ticks")
        .select("win_back, win_lay, ticked_at")
        .eq("runner_id", runner_id)
        .order("ticked_at", desc=True)
        .limit(1)
        .maybe_single()
        .execute()
    )

    now = datetime.now(timezone.utc)
    data_age = None
    if tick.data:
        ticked_at = datetime.fromisoformat(tick.data["ticked_at"])
        data_age = (now - ticked_at).total_seconds()

    p = pred.data or {}
    t = tick.data or {}

    return RunnerDetail(
        id=runner_id,
        race_id=r.data["race_id"],
        horse_name=r.data["horse_name"],
        barrier=r.data.get("barrier"),
        jockey=r.data.get("jockey"),
        trainer=r.data.get("trainer"),
        weight_kg=r.data.get("weight_kg"),
        scratched=r.data["scratched"],
        win_prob=p.get("win_prob"),
        place_prob=p.get("place_prob"),
        market_implied_prob=p.get("market_implied_prob"),
        edge=p.get("edge"),
        confidence_score=p.get("confidence_score"),
        model_version=p.get("model_version"),
        predicted_at=p.get("predicted_at"),
        feature_snapshot=p.get("feature_snapshot"),
        win_back=t.get("win_back"),
        win_lay=t.get("win_lay"),
        data_age_seconds=data_age,
    )


@router.get("/{runner_id}/ticks", response_model=list[OddsTick])
def get_runner_ticks(runner_id: str, limit: int = 60):
    """Recent odds ticks for a runner — used for sparkline chart in the UI."""
    db = get_supabase()
    res = (
        db.table("odds_ticks")
        .select("ticked_at, win_back, win_lay, win_traded_vol")
        .eq("runner_id", runner_id)
        .order("ticked_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(res.data))
