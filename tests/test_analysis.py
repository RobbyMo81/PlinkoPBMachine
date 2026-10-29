"""Independent expectations for the isolated six-ball analytical engine."""

import sqlite3
from datetime import date

import pytest

from plinko.analysis import Draw, analyze, load_draws


def draw(day: int, whites: tuple[int, ...], pb: int) -> Draw:
    return Draw(day, date(2026, 10, day), whites, pb, "fixture", f"record-{day}")


def test_exact_six_ball_boundaries_and_invalid_balls():
    assert draw(1, (1, 2, 3, 4, 5), 1).total == 16
    assert draw(2, (65, 66, 67, 68, 69), 26).total == 361
    with pytest.raises(ValueError, match="distinct"):
        draw(3, (1, 1, 3, 4, 5), 1)
    with pytest.raises(ValueError, match="range"):
        draw(3, (1, 2, 3, 4, 70), 1)
    with pytest.raises(ValueError, match="range"):
        draw(3, (1, 2, 3, 4, 5), 27)


def test_counts_white_relationships_and_sparse_pb():
    # All three are sum 16+? Explicitly: 1+2+3+4+6+2 = 18,
    # 1+2+3+5+6+1 = 18, 1+2+3+4+5+3 = 18.
    rows = (
        draw(1, (1, 2, 3, 4, 6), 2),
        draw(2, (1, 2, 3, 5, 6), 1),
        draw(3, (1, 2, 3, 4, 5), 3),
    )
    result = analyze(rows)
    bin18 = result.bins[18]
    assert bin18.frequency == 3
    assert len(bin18.pb_counts) == 26
    assert bin18.pb_counts[0:4] == (1, 1, 1, 0)
    assert [item.pb for item in bin18.ranking] == [1, 2, 3]
    assert all(item.label == "TOP_10" for item in bin18.ranking)
    assert bin18.white_counts[2][0:6] == (1, 1, 1, 1, 0, 1)
    assert bin18.white_sets[2] == ((1, 2, 3, 4, 6),)
    assert bin18.odd_counts[2] == (2,)
    assert sum(bin18.pb_counts) == 3
    assert sum(bin18.white_counts[2]) == 5
    assert result.dataset_hash == analyze(tuple(reversed(rows))).dataset_hash


def test_tenth_boundary_ties_retain_every_observed_pb():
    # eleven distinct PBs in a bin; identical six-ball total 45.
    rows = tuple(draw(day, (1, 2, 3, 4, 35 - day), day) for day in range(1, 12))
    result = analyze(rows)
    ranking = result.bins[45].ranking
    assert len(ranking) == 11
    assert [item.pb for item in ranking] == list(range(1, 12))
    assert ranking[9].label == "TOP_10"
    assert ranking[10].label == "OUTLIER_TIE"


def test_duplicate_date_or_identity_rejected():
    row = draw(1, (1, 2, 3, 4, 5), 1)
    with pytest.raises(ValueError, match="duplicate"):
        analyze((row, row))
    with pytest.raises(ValueError, match="duplicate"):
        analyze((row, Draw(2, row.draw_date, (1, 2, 3, 4, 5), 2, "fixture", "other")))


def test_sqlite_readonly_and_era_exclusion(tmp_path):
    path = tmp_path / "draws.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE draws (id INTEGER, draw_date TEXT, ball1 INTEGER, ball2 INTEGER, "
            "ball3 INTEGER, ball4 INTEGER, ball5 INTEGER, powerball INTEGER, "
            "source TEXT, record_hash TEXT)"
        )
        db.executemany(
            "INSERT INTO draws VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                (1, "2015-10-03", 1, 2, 3, 4, 5, 1, "fixture", "old"),
                (2, "2015-10-07", 1, 2, 3, 4, 5, 1, "fixture", "new"),
            ),
        )
    loaded = load_draws(path)
    assert loaded.excluded_legacy == 1
    assert len(loaded.rows) == 1
    assert loaded.rows[0].record_hash == "new"
    assert analyze(loaded.rows).bins[16].frequency == 1
    with (
        sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db,
        pytest.raises(sqlite3.OperationalError, match="readonly"),
    ):
        db.execute("INSERT INTO draws(id) VALUES (99)")


def test_missing_source_or_empty_dataset_fails():
    with pytest.raises(ValueError, match="empty"):
        analyze(())
    with pytest.raises(ValueError, match="source"):
        Draw(1, date(2026, 10, 1), (1, 2, 3, 4, 5), 1, "", "record")
