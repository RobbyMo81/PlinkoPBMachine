"""The final reviewer measures fixed tickets, never chooses or changes them."""

import random
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from plinko.analysis import Draw, analyze
from plinko.engine import build_portfolio
from plinko.monte_carlo import review_portfolio


def portfolio_fixture():
    rows = []
    for index, (total, pb) in enumerate(
        ((total, pb) for total in (160, 165, 170) for pb in (1, 2, 3)), 1
    ):
        rows.append(
            Draw(
                index,
                date(2026, 10, index),
                (10, 20, 30, 40, total - pb - 100),
                pb,
                "fixture",
                f"row-{index}",
            )
        )
    analysis = analyze(tuple(rows))
    return build_portfolio(
        analysis,
        date(2026, 10, 10),
        datetime(2026, 10, 10, 12, tzinfo=UTC),
        rng=random.Random(1),
        control_rng=random.Random(2),
    )


def test_review_is_reproducible_and_uses_uniform_draw_null():
    portfolio = portfolio_fixture()
    original = repr(portfolio)
    result = review_portfolio(portfolio, samples=2000)
    assert result == review_portfolio(portfolio, samples=2000)
    assert repr(portfolio) == original
    assert result["status"] == "passed"
    assert result["samples"] == 2000
    assert result["target_date"] == "2026-10-10"
    assert result["dataset_hash"] == portfolio.dataset_hash
    assert result["distinct_experimental_pbs"] == portfolio.distinct_pbs
    assert result["exact_pb_coverage"] == pytest.approx(portfolio.distinct_pbs / 26)
    assert result["null_ticket_pb_rate"] == pytest.approx(1 / 26)
    assert result["experimental_ticket_trials"] == 18000
    assert result["control_ticket_trials"] == 2000
    assert 0 <= result["simulated_pb_coverage"] <= 1
    assert 0 <= result["experimental_any_prize_rate"] <= 1
    assert 0 <= result["control_any_prize_rate"] <= 1
    assert result["overlap_pairs_checked"] == 36
    assert (
        result["review_seed_sha256"]
        != review_portfolio(portfolio, samples=2001)["review_seed_sha256"]
    )


def test_review_rejects_bad_sum_before_any_persistence():
    portfolio = portfolio_fixture()
    changed = replace(portfolio.experimental[0], total=portfolio.experimental[0].total + 1)
    invalid = replace(portfolio, experimental=(changed, *portfolio.experimental[1:]))
    with pytest.raises(ValueError, match="sum"):
        review_portfolio(invalid, samples=100)
    with pytest.raises(ValueError, match="samples"):
        review_portfolio(portfolio, samples=0)


def test_control_collision_is_reported_without_redraw():
    portfolio = portfolio_fixture()
    duplicate = replace(
        portfolio.experimental[0],
        kind="CONTROL_RANDOM",
        total=None,
        sum_rank=None,
        pb_rank=None,
    )
    changed = replace(portfolio, control=duplicate, control_collision=True)
    review = review_portfolio(changed, samples=100)
    assert review["control_collision"] is True
    assert changed.control == duplicate


def test_review_fails_if_simulator_disagrees_with_exact_pb_null(monkeypatch):
    portfolio = portfolio_fixture()

    class BrokenDraws:
        def __init__(self, seed):
            self.seed = seed

        def sample(self, pool, count):
            return [1, 2, 3, 4, 5]

        def randrange(self, start, stop):
            return 26

    monkeypatch.setattr("plinko.monte_carlo.random.Random", BrokenDraws)
    with pytest.raises(ValueError, match="disagrees"):
        review_portfolio(portfolio, samples=1000)
