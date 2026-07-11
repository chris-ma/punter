"""
Post-race results ingestion.

Betfair makes BSP (Betfair Starting Price) and final runner statuses available
via the REST API after a market settles. This job:
  1. Finds closed races that don't yet have outcomes recorded
  2. Fetches the settled market data (final runner statuses + BSP)
  3. Writes finishing positions and win/place flags to the outcomes table

This is the ground truth required by the model evaluation harness (evaluate.py)
and the live validation requirement (§7.4).

Finishing position is derived from Betfair runner status:
  WINNER  → position 1, won=True,  placed=True
  PLACED  → position 2–3, won=False, placed=True  (Betfair marks top 3 for place markets)
  LOSER   → won=False, placed=False (position inferred from order, not guaranteed accurate)
  REMOVED → scratched

For exact finishing order beyond 1st/2nd/3rd, the data is not reliable — consistent
with §5.1 (model targets win probability, not exact finishing order).
"""

import logging
from datetime import datetime, timezone

import httpx

from racing.config import settings
from racing.db.client import get_supabase

log = logging.getLogger(__name__)

BETFAIR_API_BASE = "https://api.betfair.com/exchange/betting/rest/v1.0"


def _betfair_headers(session_token: str) -> dict[str, str]:
    return {
        "X-Application": settings.betfair_app_key,
        "X-Authentication": session_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _session_token() -> str:
    resp = httpx.post(
        "https://identitysso-cert.betfair.com/api/certlogin",
        data={"username": settings.betfair_username, "password": settings.betfair_password},
        headers={"X-Application": settings.betfair_app_key},
        cert=(settings.betfair_cert_path, settings.betfair_key_path),
        timeout=10,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("loginStatus") != "SUCCESS":
        raise RuntimeError(f"Betfair login failed: {body}")
    return body["sessionToken"]


def _fetch_settled_market(session_token: str, market_id: str) -> list[dict]:
    """
    Returns runner list with status and BSP from a settled Betfair market.
    Uses listMarketBook with priceProjection to get BSP.
    """
    resp = httpx.post(
        f"{BETFAIR_API_BASE}/listMarketBook/",
        json={
            "marketIds": [market_id],
            "priceProjection": {"priceData": ["SP_TRADED"]},
            "orderProjection": "ALL",
            "matchProjection": "NO_ROLLUP",
        },
        headers=_betfair_headers(session_token),
        timeout=15,
    )
    resp.raise_for_status()
    books = resp.json()
    if not books:
        return []
    return books[0].get("runners", [])


def run() -> None:
    """
    Ingests results for all races that have closed but not yet been settled
    in the outcomes table. Designed to be called ~1 hour after jump time.
    """
    db = get_supabase()
    now = datetime.now(timezone.utc)

    # Find closed races with no outcomes yet
    closed_races = (
        db.table("races")
        .select("id, betfair_market_id, scheduled_jump_at")
        .eq("status", "closed")
        .execute()
    )

    # Filter to races that have no outcomes yet
    unsettled = []
    for race in closed_races.data:
        existing = (
            db.table("outcomes")
            .select("id")
            .eq("race_id", race["id"])
            .limit(1)
            .execute()
        )
        if not existing.data:
            unsettled.append(race)

    if not unsettled:
        log.info("No unsettled races found")
        return

    log.info("Fetching results for %d unsettled races", len(unsettled))
    token = _session_token()

    for race in unsettled:
        market_id = race["betfair_market_id"]
        race_id = race["id"]

        try:
            runner_books = _fetch_settled_market(token, market_id)
        except Exception:
            log.exception("Failed to fetch market %s", market_id)
            continue

        if not runner_books:
            log.warning("Empty market book for %s — may not be settled yet", market_id)
            continue

        # Load DB runners for this race
        runners_res = (
            db.table("runners")
            .select("id, betfair_selection_id")
            .eq("race_id", race_id)
            .execute()
        )
        sel_to_runner_id = {
            int(r["betfair_selection_id"]): r["id"] for r in runners_res.data
        }

        # Sort: WINNER first, PLACED next, LOSER last — gives approximate finishing order
        status_order = {"WINNER": 0, "PLACED": 1, "LOSER": 2, "REMOVED": 3}
        runner_books.sort(key=lambda r: status_order.get(r.get("status", ""), 9))

        outcomes = []
        position = 1
        for rb in runner_books:
            sel_id = rb.get("selectionId")
            runner_id = sel_to_runner_id.get(int(sel_id)) if sel_id else None
            if not runner_id:
                continue

            status = rb.get("status", "")
            if status == "REMOVED":
                continue  # scratched runners don't get an outcome row

            bsp = rb.get("sp", {}).get("actualSP")

            outcomes.append({
                "runner_id": runner_id,
                "race_id": race_id,
                "finish_position": position,
                "won": status == "WINNER",
                "placed": status in ("WINNER", "PLACED"),
                "bsp": float(bsp) if bsp else None,
                "settled_at": now.isoformat(),
            })
            position += 1

        if outcomes:
            db.table("outcomes").upsert(outcomes, on_conflict="runner_id").execute()
            log.info("Settled %d runners for market %s", len(outcomes), market_id)

        # Mark race as settled
        db.table("races").update({"status": "settled"}).eq("id", race_id).execute()

    log.info("Results ingestion complete")


def mark_races_closed() -> None:
    """
    Marks races whose scheduled_jump_at has passed as 'closed'.
    Called by the scheduler before results ingestion so newly finished
    races are picked up without waiting for the next cycle.
    """
    db = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    db.table("races").update({"status": "closed"}).eq("status", "open").lt(
        "scheduled_jump_at", now
    ).execute()


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    mark_races_closed()
    run()
