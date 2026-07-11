import math

import pytest

from racing.pipeline.betfair.market_utils import (
    RunnerOdds,
    edge,
    implied_probabilities,
    mid_price,
    overround,
)


def make_runner(sid: int, back: float, lay: float | None = None, scratched: bool = False):
    return RunnerOdds(
        selection_id=sid, name=f"Horse {sid}",
        win_back=back, win_lay=lay, scratched=scratched,
    )


class TestMidPrice:
    def test_geometric_mid_when_both_sides(self):
        r = make_runner(1, back=4.0, lay=4.2)
        assert mid_price(r) == pytest.approx(math.sqrt(4.0 * 4.2), rel=1e-6)

    def test_falls_back_to_back_when_no_lay(self):
        r = make_runner(1, back=4.0, lay=None)
        assert mid_price(r) == 4.0

    def test_none_when_no_prices(self):
        r = RunnerOdds(selection_id=1, name="x", win_back=None, win_lay=None)
        assert mid_price(r) is None


class TestOverround:
    def test_three_even_runners_overround(self):
        runners = [make_runner(i, back=3.1) for i in range(3)]
        # 3 × (1/3.1) ≈ 0.968 — slight underround due to rounding; real markets > 1.0
        assert 0.9 < overround(runners) < 1.1

    def test_scratched_runners_excluded(self):
        runners = [
            make_runner(1, back=2.0),
            make_runner(2, back=2.0, scratched=True),
        ]
        # Only runner 1 counts: 1/2.0 = 0.5
        assert overround(runners) == pytest.approx(0.5, rel=1e-4)


class TestImpliedProbabilities:
    def test_probs_sum_to_one(self):
        runners = [make_runner(i, back=float(i + 2)) for i in range(5)]
        probs = implied_probabilities(runners)
        assert sum(probs.values()) == pytest.approx(1.0, rel=1e-6)

    def test_scratched_runner_gets_zero(self):
        runners = [
            make_runner(1, back=2.0),
            make_runner(2, back=3.0, scratched=True),
            make_runner(3, back=4.0),
        ]
        probs = implied_probabilities(runners)
        assert probs[2] == 0.0
        assert probs[1] + probs[3] == pytest.approx(1.0, rel=1e-6)

    def test_favourite_has_higher_prob_than_outsider(self):
        runners = [make_runner(1, back=2.0), make_runner(2, back=8.0)]
        probs = implied_probabilities(runners)
        assert probs[1] > probs[2]

    def test_renormalises_after_scratching(self):
        """
        §6.3: On detecting a scratching, remaining field probs should renormalise.
        This tests the pure maths — scratching detection is in live_poll.py.
        """
        active = [make_runner(1, back=2.0), make_runner(3, back=4.0)]
        probs_2 = implied_probabilities(active)
        assert sum(probs_2.values()) == pytest.approx(1.0, rel=1e-6)


class TestEdge:
    def test_positive_edge_when_model_higher(self):
        assert edge(model_prob=0.35, implied_prob=0.25) == pytest.approx(0.10)

    def test_negative_edge_when_market_higher(self):
        assert edge(model_prob=0.10, implied_prob=0.25) == pytest.approx(-0.15)

    def test_zero_edge_when_equal(self):
        assert edge(model_prob=0.25, implied_prob=0.25) == pytest.approx(0.0)
