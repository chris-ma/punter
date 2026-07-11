"""
The Odds API client — replaces Betfair streaming for live AU horse racing odds.

Docs: https://the-odds-api.com/liveapi/guides/v4/

Key design decisions:
- Horse racing events: each race is an event, each runner is an outcome in the h2h market.
- We poll on a schedule (60s default, 15s near jump) rather than streaming.
- We request only the bookmakers we care about to preserve API quota.
- Quota usage is logged after each call (the API returns remaining quota in headers).

Free tier: 500 requests/month. Paid from ~$50/month.
Each call to /odds uses quota proportional to (events × bookmakers × markets).
Specifying `bookmakers=tab,sportsbet` and `markets=h2h` minimises usage.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from racing.config import settings

log = logging.getLogger(__name__)

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
HORSE_RACING_SPORT_KEYS = [
    "horseracing_au",
    "horseracing",
]


@dataclass
class RunnerOdds:
    name: str
    price: float | None   # decimal win odds (best across requested bookmakers)


@dataclass
class RaceSnapshot:
    event_id: str
    sport_key: str
    race_name: str
    commence_time: datetime   # UTC
    runners: list[RunnerOdds]
    captured_at: datetime
    bookmaker: str | None = None   # which bookmaker supplied the price


def _best_price(outcomes: list[dict], runner_name: str) -> float | None:
    """Highest back price seen for this runner across all bookmakers."""
    prices = [o["price"] for o in outcomes if o["name"] == runner_name and o.get("price")]
    return max(prices) if prices else None


def fetch_au_racing_odds() -> list[RaceSnapshot]:
    """
    Fetch current AU horse racing odds from The Odds API.
    Returns one RaceSnapshot per upcoming event.
    Tries each known sport key until one returns data.
    """
    headers = {"Accept": "application/json"}
    params = {
        "apiKey": settings.odds_api_key,
        "regions": settings.odds_api_regions,
        "markets": "h2h",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    if settings.bookmakers_list:
        params["bookmakers"] = ",".join(settings.bookmakers_list)

    snapshots: list[RaceSnapshot] = []
    now = datetime.now(timezone.utc)

    for sport_key in HORSE_RACING_SPORT_KEYS:
        try:
            resp = httpx.get(
                f"{ODDS_API_BASE}/sports/{sport_key}/odds",
                params=params,
                headers=headers,
                timeout=15,
            )

            remaining = resp.headers.get("x-requests-remaining", "?")
            used = resp.headers.get("x-requests-used", "?")
            log.debug("Odds API quota — used: %s, remaining: %s", used, remaining)

            if resp.status_code == 404:
                log.debug("Sport key %s not found, trying next", sport_key)
                continue

            resp.raise_for_status()
            events = resp.json()

            if not events:
                log.debug("No events for sport key %s", sport_key)
                continue

            log.info("Fetched %d events from Odds API (sport=%s)", len(events), sport_key)

            for event in events:
                runners = _parse_runners(event)
                if not runners:
                    continue

                snapshots.append(RaceSnapshot(
                    event_id=event["id"],
                    sport_key=sport_key,
                    race_name=event.get("home_team") or event.get("sport_title", ""),
                    commence_time=datetime.fromisoformat(
                        event["commence_time"].replace("Z", "+00:00")
                    ),
                    runners=runners,
                    captured_at=now,
                ))

            # If we got data, don't try additional sport keys
            if snapshots:
                break

        except httpx.HTTPError:
            log.exception("Odds API request failed for sport_key=%s", sport_key)
            continue

    if not snapshots:
        log.warning("No AU horse racing events found from Odds API")

    return snapshots


def _parse_runners(event: dict) -> list[RunnerOdds]:
    """
    Extract best win price per runner across all returned bookmakers.
    The Odds API h2h market lists each runner as an outcome.
    """
    best: dict[str, float] = {}

    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "")
                price = outcome.get("price")
                if name and price and price > 1.0:
                    if name not in best or price > best[name]:
                        best[name] = price

    return [RunnerOdds(name=name, price=price) for name, price in best.items()]


def list_available_sports() -> list[dict]:
    """Utility: list all sports available in The Odds API for this key."""
    resp = httpx.get(
        f"{ODDS_API_BASE}/sports",
        params={"apiKey": settings.odds_api_key},
        timeout=10,
    )
    resp.raise_for_status()
    return [s for s in resp.json() if s.get("active")]
