"""
Nightly batch job.

Phase 1: Seeds the races/runners tables from Betfair market catalogue for
the next day's AU thoroughbred WIN markets.

Phase 2 (when PUNTING_FORM_API_KEY is set): additionally pulls form, class,
weight, jockey/trainer data and runs model inference, storing predictions.

The batch is intentionally idempotent — safe to run multiple times; upserts
on betfair_market_id / (race_id, betfair_selection_id).
"""

import logging
from datetime import date, datetime, timezone

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


def _list_au_win_markets(session_token: str, for_date: date) -> list[dict]:
    """Fetch AU thoroughbred WIN markets from Betfair API for the given date."""
    from_dt = datetime(for_date.year, for_date.month, for_date.day, 0, 0, tzinfo=timezone.utc)
    to_dt = datetime(for_date.year, for_date.month, for_date.day, 23, 59, tzinfo=timezone.utc)

    payload = {
        "filter": {
            "eventTypeIds": ["7"],
            "marketCountries": ["AU"],
            "marketTypeCodes": ["WIN"],
            "marketStartTime": {
                "from": from_dt.isoformat(),
                "to": to_dt.isoformat(),
            },
        },
        "marketProjection": [
            "MARKET_START_TIME",
            "EVENT",
            "RUNNER_DESCRIPTION",
            "MARKET_DESCRIPTION",
        ],
        "maxResults": 200,
    }

    resp = httpx.post(
        f"{BETFAIR_API_BASE}/listMarketCatalogue/",
        json=payload,
        headers=_betfair_headers(session_token),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _state_from_country_code(market: dict) -> str:
    """
    Betfair doesn't always expose AU state directly. We infer from venue where possible.
    """
    venue: str = market.get("description", {}).get("venue", "") or ""
    state_hints = {
        "Flemington": "VIC", "Caulfield": "VIC", "Moonee Valley": "VIC", "Sandown": "VIC",
        "Randwick": "NSW", "Rosehill": "NSW", "Warwick Farm": "NSW", "Canterbury": "NSW",
        "Doomben": "QLD", "Eagle Farm": "QLD", "Gold Coast": "QLD", "Sunshine Coast": "QLD",
        "Ascot": "WA", "Belmont": "WA",
        "Morphettville": "SA",
        "Ellerslie": "NZ",  # sometimes included in AU feeds
    }
    for hint, state in state_hints.items():
        if hint.lower() in venue.lower():
            return state
    return "UNK"


def run(for_date: date | None = None) -> None:
    """
    Entry point for the nightly batch.
    Defaults to tomorrow's races if for_date is not provided.
    """
    if for_date is None:
        from datetime import timedelta
        for_date = date.today() + timedelta(days=1)

    log.info("Nightly batch starting for %s", for_date)
    token = _session_token()
    markets = _list_au_win_markets(token, for_date)
    log.info("Found %d AU WIN markets for %s", len(markets), for_date)

    db = get_supabase()
    seeded_races = 0
    seeded_runners = 0

    for m in markets:
        mid = m.get("marketId", "")
        start_time = m.get("marketStartTime", "")
        event = m.get("event", {})
        venue = m.get("description", {}).get("venue") or event.get("venue", "")
        state = _state_from_country_code(m)

        try:
            jump_at = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            log.warning("Could not parse start time for market %s", mid)
            continue

        race_payload = {
            "betfair_market_id": mid,
            "track": venue,
            "state": state,
            "race_name": m.get("marketName", ""),
            "race_date": for_date.isoformat(),
            "scheduled_jump_at": jump_at.isoformat(),
            "status": "upcoming",
        }

        race_res = (
            db.table("races")
            .upsert(race_payload, on_conflict="betfair_market_id")
            .execute()
        )
        race_id = race_res.data[0]["id"]
        seeded_races += 1

        for runner in m.get("runners", []):
            runner_payload = {
                "race_id": race_id,
                "betfair_selection_id": runner["selectionId"],
                "horse_name": runner.get("runnerName", ""),
                "barrier": runner.get("metadata", {}).get("STALL_NAME"),
            }
            db.table("runners").upsert(
                runner_payload,
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
    """
    Phase 2: pull form/class/weight from Punting Form API and run model inference.
    Stub — implemented when PUNTING_FORM_API_KEY is present and Phase 2 begins.
    """
    log.info("Phase 2 form pull (stub) — would call Punting Form API for %s", for_date)
    raise NotImplementedError("Phase 2 form pull not yet implemented")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    run()
