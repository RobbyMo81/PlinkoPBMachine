"""Clean-room provisional generation and 3×3 assignment contracts."""

import itertools
import random
from datetime import UTC, date, datetime

import pytest

from plinko.analysis import Draw, analyze
from plinko.engine import (
    ConstraintError,
    build_portfolio,
    count_exact_sum,
    sample_exact_sum,
    unrank_exact_sum,
)


def fixture():
    draws = []
    for i, (total, pb) in enumerate(itertools.product((160, 165, 170), (1, 2, 3)), 1):
        draws.append(
            Draw(
                i, date(2026, 10, i), (10, 20, 30, 40, total - pb - 100), pb, "fixture", f"row-{i}"
            )
        )
    return analyze(tuple(draws))


def test_exact_sum_unranking_is_bijective_without_frequency_preferences():
    pool = tuple(range(1, 9))
    expected = [c for c in itertools.combinations(pool, 5) if sum(c) == 20]
    assert count_exact_sum(pool, 20) == len(expected)
    assert [unrank_exact_sum(pool, 20, i) for i in range(len(expected))] == expected
    with pytest.raises(ConstraintError) as exc:
        sample_exact_sum(1, pool=pool)
    assert exc.value.code == "UNSATISFIABLE_SUM"


def test_overlap_rejection_exhaustion_is_not_proof_of_impossibility():
    pool = (1, 2, 3, 4, 5, 6)

    class AlwaysFirst:
        def randrange(self, n):
            return 0

    with pytest.raises(ConstraintError) as exc:
        sample_exact_sum(15, previous=((1, 2, 3, 4, 5),), pool=pool, retries=3, rng=AlwaysFirst())
    assert exc.value.code == "SEARCH_EXHAUSTED"


def test_full_portfolio_assignments_overlap_and_independent_control():
    result = fixture()
    generated = datetime(2026, 10, 10, 12, tzinfo=UTC)
    portfolio = build_portfolio(
        result,
        date(2026, 10, 10),
        generated,
        rng=random.Random(1234),
        control_rng=random.Random(5678),
    )
    assert len(portfolio.experimental) == 9
    assert [t.total for t in portfolio.experimental] == [170] * 3 + [165] * 3 + [160] * 3
    assert [t.pb for t in portfolio.experimental] == [3, 2, 1] * 3
    assert portfolio.overlaps_checked == 36
    assert all(t.total == sum(t.whites) + t.pb for t in portfolio.experimental)
    assert all(len(set(t.whites)) == 5 for t in portfolio.experimental)
    assert all(
        len(set(a.whites) & set(b.whites)) <= 2
        for a, b in itertools.combinations(portfolio.experimental, 2)
    )
    assert portfolio.distinct_pbs == 3
    assert portfolio.control.kind == "CONTROL_RANDOM"
    assert portfolio.dataset_hash == result.dataset_hash


def test_control_collision_is_preserved_not_regenerated():
    class DuplicateControl:
        def __init__(self):
            self.ticket = None
            self.calls = 0

        def sample(self, values, count):
            self.calls += 1
            return list(self.ticket.whites)

        def randrange(self, count):
            return self.ticket.pb - 1

    control = DuplicateControl()
    generated = datetime(2026, 10, 10, 12, tzinfo=UTC)
    first = build_portfolio(
        fixture(),
        date(2026, 10, 10),
        generated,
        rng=random.Random(44),
        control_rng=random.Random(1),
    )
    control.ticket = first.experimental[0]
    second = build_portfolio(
        fixture(), date(2026, 10, 10), generated, rng=random.Random(44), control_rng=control
    )
    assert second.control_collision is True
    assert control.calls == 1
    assert (second.control.whites, second.control.pb) == (
        first.experimental[0].whites,
        first.experimental[0].pb,
    )


def test_next_draw_and_source_cutoff_guard():
    result = fixture()
    with pytest.raises(ValueError, match="next scheduled"):
        build_portfolio(result, date(2026, 10, 12), datetime(2026, 10, 10, 12, tzinfo=UTC))
    with pytest.raises(ValueError, match="timezone"):
        build_portfolio(result, date(2026, 10, 10), datetime.fromisoformat("2026-10-10T12:00"))
    with pytest.raises(ValueError, match="source"):
        build_portfolio(result, date(2026, 10, 10), datetime(2026, 10, 9, 12, tzinfo=UTC))
