"""Revised directive regression tests for complete bins and recency rankings."""

from datetime import date

import pytest

from plinko.analysis import Draw, analyze, rank_powerballs, rank_sums


def make(identity: int, day: int, whites: tuple[int, ...], pb: int) -> Draw:
    return Draw(identity, date(2026, 10, day), whites, pb, "fixture", f"hash-{identity}")


def test_complete_bins_and_official_draw_recency():
    rows = (
        make(1, 1, (1, 2, 3, 4, 5), 1),  # S=16 (one)
        make(2, 2, (1, 2, 3, 4, 6), 1),  # S=17 (two)
        make(3, 3, (1, 2, 3, 4, 5), 2),  # S=17
        make(4, 4, (1, 2, 3, 4, 5), 3),  # S=18 (one, most recent)
    )
    result = analyze(rows)
    assert len(result.bins) == 346
    assert min(result.bins) == 16 and max(result.bins) == 361
    assert result.bins[361].frequency == 0
    assert sum(b.frequency for b in result.bins.values()) == 4
    ranking = rank_sums(result)
    assert [(r.total, r.frequency, r.last_date, r.rank) for r in ranking] == [
        (17, 2, date(2026, 10, 3), 1),
        (18, 1, date(2026, 10, 4), 2),
        (16, 1, date(2026, 10, 1), 3),
    ]
    assert all(r.dataset_hash == result.dataset_hash for r in ranking)


def test_pb_rank_uses_recent_official_date_and_preserves_ties():
    rows = (
        make(1, 1, (1, 2, 3, 4, 8), 1),  # S=19
        make(2, 2, (1, 2, 3, 4, 7), 2),  # S=19
        make(3, 3, (1, 2, 3, 4, 8), 1),  # S=19
        make(4, 4, (1, 2, 3, 4, 7), 2),  # S=19, latest
        make(5, 5, (1, 2, 3, 4, 6), 3),  # S=19
    )
    result = analyze(rows)
    ranked = rank_powerballs(result, 19)
    assert [(p.pb, p.count, p.last_date, p.rank) for p in ranked] == [
        (2, 2, date(2026, 10, 4), 1),
        (1, 2, date(2026, 10, 3), 2),
        (3, 1, date(2026, 10, 5), 3),
    ]
    assert rank_powerballs(result, 361) == ()
    with pytest.raises(ValueError, match="observed"):
        rank_powerballs(result, 361, require=3)
