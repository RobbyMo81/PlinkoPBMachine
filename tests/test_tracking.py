"""Exercise the existing storage contract only against disposable local databases."""

import importlib.util
import json
import shutil
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from plinko.analysis import Draw, analyze
from plinko.engine import build_portfolio
from plinko.tracking import persist_cycle, read_pb_metrics

REFERENCE = Path("C:/Users/RobMo/OneDrive/Documents/PowerBall/core/generated_pick_storage.py")


def reference_storage(tmp_path):
    if not REFERENCE.exists():
        pytest.skip("reference tracker source is absent")
    isolated = tmp_path / "generated_pick_storage.py"
    shutil.copyfile(REFERENCE, isolated)
    spec = importlib.util.spec_from_file_location("isolated_generated_pick_storage", isolated)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GeneratedPickStorage(str(tmp_path / "ledger.db"))


@pytest.fixture(autouse=True)
def simulated_pre_draw_clock(monkeypatch):
    """Synthetic outcome fixtures use a simulated pre-draw clock, never real scoring."""
    monkeypatch.setattr("plinko.tracking._utc_now", lambda: datetime(2026, 10, 10, 12, tzinfo=UTC))


def fixture(tmp_path):
    rows = []
    draw_db = tmp_path / "draws.db"
    with sqlite3.connect(draw_db) as connection:
        connection.execute(
            "CREATE TABLE draws (draw_date TEXT, ball1 INTEGER, ball2 INTEGER, "
            "ball3 INTEGER, ball4 INTEGER, ball5 INTEGER, powerball INTEGER, "
            "multiplier INTEGER)"
        )
        for i in range(1, 10):
            total, pb = (160, 165, 170)[(i - 1) // 3], (1, 2, 3)[(i - 1) % 3]
            whites = (10, 20, 30, 40, total - pb - 100)
            rows.append(Draw(i, date(2026, 10, i), whites, pb, "fixture", f"row-{i}"))
        connection.execute("INSERT INTO draws VALUES ('2026-10-10', 1, 2, 3, 4, 5, 3, 2)")
    snapshot_db = tmp_path / "snapshot.db"
    with sqlite3.connect(snapshot_db) as connection:
        connection.execute(
            "CREATE TABLE draws (id INTEGER, draw_date TEXT, ball1 INTEGER, ball2 INTEGER, "
            "ball3 INTEGER, ball4 INTEGER, ball5 INTEGER, powerball INTEGER, "
            "source TEXT, record_hash TEXT)"
        )
        connection.executemany(
            "INSERT INTO draws VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                (r.identity, r.draw_date.isoformat(), *r.whites, r.pb, r.source, r.record_hash)
                for r in rows
            ),
        )
    analysis = analyze(tuple(rows))
    generated = datetime(2026, 10, 10, 12, tzinfo=UTC)
    import random

    portfolio = build_portfolio(
        analysis,
        date(2026, 10, 10),
        generated,
        rng=random.Random(1234),
        control_rng=random.Random(5678),
    )
    return analysis, portfolio, snapshot_db, draw_db


def test_existing_ledger_roundtrip_pb_metrics_and_idempotent_evaluation(tmp_path):
    storage = reference_storage(tmp_path)
    analysis, portfolio, snapshot, draws = fixture(tmp_path)
    persist_cycle(
        portfolio, analysis, snapshot, storage, workspace_root=tmp_path, cycle_id="fixture-cycle"
    )
    with storage._connect() as connection:
        batches = connection.execute("SELECT * FROM generation_batches").fetchall()
        picks = connection.execute("SELECT * FROM generated_picks ORDER BY id").fetchall()
    assert len(batches) == 1 and len(picks) == 10
    assert [p["pick_type"] for p in picks] == ["plinko_experimental"] * 9 + ["plinko_control"]
    assert all(p["batch_id"] == "fixture-cycle" for p in picks)
    assert all(json.loads(p["metadata_json"])["target_date"] == "2026-10-10" for p in picks)
    assert storage.evaluate_against_draws(str(draws))["evaluated"] == 10
    assert storage.evaluate_against_draws(str(draws))["unchanged"] == 10
    result = read_pb_metrics(storage.storage_path, workspace_root=tmp_path)
    assert result["evaluated_cycles"] == 1
    assert result["experimental_opportunities"] == 9
    assert result["control_opportunities"] == 1
    assert result["distinct_pb_baseline"] == pytest.approx(3 / 26)
    assert result["experimental_ticket_rate"] == result["experimental_hits"] / 9
    assert result["control_rate"] == result["control_hits"]
    assert result["coverage_rate"] == float(result["coverage_hits"])
    assert read_pb_metrics(storage.storage_path, workspace_root=tmp_path) == result


def test_incomplete_batch_and_wrong_target_are_excluded(tmp_path):
    storage = reference_storage(tmp_path)
    analysis, portfolio, snapshot, draws = fixture(tmp_path)
    persist_cycle(
        portfolio, analysis, snapshot, storage, workspace_root=tmp_path, cycle_id="incomplete"
    )
    with storage._connect() as connection:
        connection.execute(
            "DELETE FROM generated_picks WHERE batch_id='incomplete' AND source_row=10"
        )
    result = read_pb_metrics(storage.storage_path, workspace_root=tmp_path)
    assert result["evaluated_cycles"] == 0 and result["incomplete_cycles"] == 1
    # A complete portfolio attributed to the wrong future draw must not score as valid.
    persist_cycle(
        portfolio, analysis, snapshot, storage, workspace_root=tmp_path, cycle_id="mismatched"
    )
    with sqlite3.connect(draws) as connection:
        connection.execute("UPDATE draws SET draw_date='2026-10-17'")
    storage.evaluate_against_draws(str(draws))
    result = read_pb_metrics(storage.storage_path, workspace_root=tmp_path)
    assert result["evaluated_cycles"] == 0 and result["mismatched_cycles"] >= 1


def test_snapshot_mismatch_rejected_before_ledger_write(tmp_path):
    storage = reference_storage(tmp_path)
    analysis, portfolio, snapshot, _ = fixture(tmp_path)
    with sqlite3.connect(snapshot) as conn:
        conn.execute("UPDATE draws SET powerball=26 WHERE id=1")
    with pytest.raises(ValueError, match="snapshot"):
        persist_cycle(
            portfolio, analysis, snapshot, storage, workspace_root=tmp_path, cycle_id="tampered"
        )
    assert storage.count() == 0


def test_backdated_generation_cannot_persist(tmp_path, monkeypatch):
    storage = reference_storage(tmp_path)
    analysis, portfolio, snapshot, _ = fixture(tmp_path)
    monkeypatch.setattr("plinko.tracking._utc_now", lambda: datetime(2026, 10, 30, 12, tzinfo=UTC))
    with pytest.raises(ValueError, match="generation timestamp"):
        persist_cycle(
            portfolio, analysis, snapshot, storage, workspace_root=tmp_path, cycle_id="backdated"
        )
    assert storage.count() == 0


def test_duplicate_complete_cycles_cannot_double_count_one_draw(tmp_path):
    storage = reference_storage(tmp_path)
    analysis, portfolio, snapshot, draws = fixture(tmp_path)
    for cycle in ("a", "b"):
        persist_cycle(
            portfolio, analysis, snapshot, storage, workspace_root=tmp_path, cycle_id=cycle
        )
    storage.evaluate_against_draws(str(draws))
    metrics = read_pb_metrics(storage.storage_path, workspace_root=tmp_path)
    assert metrics["evaluated_cycles"] == 0
    assert metrics["duplicate_target_cycles"] == 2


def test_production_path_guard(tmp_path):
    storage = reference_storage(tmp_path)
    analysis, portfolio, snapshot, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match="workspace"):
        persist_cycle(
            portfolio,
            analysis,
            snapshot,
            storage,
            workspace_root=tmp_path / "other",
            cycle_id="denied",
        )
    assert storage.count() == 0
