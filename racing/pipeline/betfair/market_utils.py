"""
Market probability utilities.

Betfair odds are back prices (decimal). The market-implied win probability
for a single runner is 1/odds, but the raw sum across a field exceeds 1 due
to Betfair's commission margin (the overround). We adjust by dividing each
runner's raw implied probability by the total overround, so probabilities
sum to 1.0 across the field.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence


@dataclass
class RunnerOdds:
    selection_id: int
    name: str
    win_back: float | None   # best available back price
    win_lay: float | None    # best available lay price
    traded_vol: float = 0.0
    scratched: bool = False


@dataclass
class MarketSnapshot:
    market_id: str
    captured_at: datetime
    runners: list[RunnerOdds]
    is_stale: bool = False


def mid_price(runner: RunnerOdds) -> float | None:
    """Geometric mid of back/lay spread; falls back to back if no lay."""
    if runner.win_back and runner.win_lay:
        import math
        return math.sqrt(runner.win_back * runner.win_lay)
    return runner.win_back


def overround(runners: Sequence[RunnerOdds]) -> float:
    """Sum of raw implied probs across non-scratched runners. >1.0 = margin."""
    total = 0.0
    for r in runners:
        if not r.scratched:
            price = mid_price(r)
            if price and price > 1.0:
                total += 1.0 / price
    return total if total > 0 else 1.0


def implied_probabilities(runners: Sequence[RunnerOdds]) -> dict[int, float]:
    """
    Overround-adjusted win probabilities, summing to 1.0 across active runners.
    Scratched runners get 0.0 and are excluded from renormalisation.
    """
    raw: dict[int, float] = {}
    for r in runners:
        if r.scratched:
            raw[r.selection_id] = 0.0
            continue
        price = mid_price(r)
        raw[r.selection_id] = (1.0 / price) if (price and price > 1.0) else 0.0

    total = sum(raw.values())
    if total <= 0:
        return {sid: 0.0 for sid in raw}

    return {sid: p / total for sid, p in raw.items()}


def edge(model_prob: float, implied_prob: float) -> float:
    """Signed edge: positive = model rates runner higher than market."""
    return model_prob - implied_prob
