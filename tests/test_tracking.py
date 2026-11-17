"""Exercise the existing storage contract only against disposable local databases."""

import importlib.util
import json
import shutil
import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from plinko.analysis import Draw, analyze
from plinko.engine import build_portfolio
from plinko.monte_carlo import review_portfolio, review_saved_cycle
from plinko.tracking import persist_cycle, read_pb_metrics, score_prize

REFERENCE = Path("C:/Users/RobMo/PBMachine/core/generated_pick_storage.py")


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


def test_nine_base_prize_levels_and_unpriced_jackpot():
    expected = {
        (0, True): ("powerball_only", 400),
        (1, True): ("match_1_powerball", 400),
        (2, True): ("match_2_powerball", 700),
        (3, False): ("match_3", 700),
        (3, True): ("match_3_powerball", 10_000),
        (4, False): ("match_4", 10_000),
        (4, True): ("match_4_powerball", 5_000_000),
        (5, False): ("match_5", 100_000_000),
        (5, True): ("jackpot", None),
    }
    assert {key: score_prize(*key) for key in expected} == expected
    assert score_prize(2, False) == ("no_prize", 0)
    with pytest.raises(ValueError, match="white"):
        score_prize(6, False)


def test_prize_summary_excludes_tampered_tier(tmp_path):
    storage = reference_storage(tmp_path)
    analysis, portfolio, snapshot, draws = fixture(tmp_path)
    persist_cycle(
        portfolio, analysis, snapshot, storage, workspace_root=tmp_path, cycle_id="prizes"
    )
    storage.evaluate_against_draws(str(draws))
    metrics = read_pb_metrics(storage.storage_path, workspace_root=tmp_path)
    with storage._connect() as connection:
        stored = connection.execute(
            "SELECT pick_type,prize_tier,COUNT(*) AS count FROM pick_evaluations e "
            "JOIN generated_picks p ON p.id=e.pick_id WHERE e.is_current=1 "
            "GROUP BY pick_type,prize_tier"
        ).fetchall()
        connection.execute(
            "UPDATE pick_evaluations SET prize_tier='jackpot' WHERE id=("
            "SELECT e.id FROM pick_evaluations e JOIN generated_picks p ON p.id=e.pick_id "
            "WHERE p.batch_id='prizes' ORDER BY p.source_row LIMIT 1)"
        )
    expected_experimental = {
        row["prize_tier"]: row["count"]
        for row in stored
        if row["pick_type"] == "plinko_experimental"
    }
    assert metrics["experimental_prize_tiers"] == expected_experimental
    assert metrics["control_prize_tiers"] == {
        row["prize_tier"]: row["count"] for row in stored if row["pick_type"] == "plinko_control"
    }
    assert metrics["experimental_known_base_cents"] >= 0
    tampered = read_pb_metrics(storage.storage_path, workspace_root=tmp_path)
    assert tampered["evaluated_cycles"] == 0
    assert tampered["mismatched_cycles"] == 1


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
    review = json.loads(batches[0]["strategy_json"])["monte_carlo_review"]
    assert review["status"] == "passed"
    assert review["samples"] == 20_000
    assert review["distinct_experimental_pbs"] == portfolio.distinct_pbs
    assert review["dataset_hash"] == analysis.dataset_hash
    assert (
        review_saved_cycle(storage.storage_path, "fixture-cycle", workspace_root=tmp_path) == review
    )
    assert (
        review_saved_cycle(
            storage.storage_path, "fixture-cycle", workspace_root=tmp_path, samples=100
        )["samples"]
        == 100
    )
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


def test_reviewer_failure_prevents_any_batch_or_pick_write(tmp_path, monkeypatch):
    storage = reference_storage(tmp_path)
    analysis, portfolio, snapshot, _ = fixture(tmp_path)

    def fail_review(_portfolio):
        raise ValueError("Monte Carlo reviewer failed")

    monkeypatch.setattr("plinko.tracking.review_portfolio", fail_review)
    with pytest.raises(ValueError, match="reviewer failed"):
        persist_cycle(
            portfolio, analysis, snapshot, storage, workspace_root=tmp_path, cycle_id="blocked"
        )
    with storage._connect() as connection:
        assert connection.execute("SELECT count(*) FROM generation_batches").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM generated_picks").fetchone()[0] == 0


def test_ranking_swapped_portfolio_cannot_pass_final_review_or_persist(tmp_path):
    storage = reference_storage(tmp_path)
    analysis, portfolio, snapshot, _ = fixture(tmp_path)
    swapped = replace(
        portfolio,
        experimental=(
            *(replace(ticket, sum_rank=1) for ticket in portfolio.experimental[3:6]),
            *(replace(ticket, sum_rank=2) for ticket in portfolio.experimental[:3]),
            *portfolio.experimental[6:],
        ),
        top_sums=(portfolio.top_sums[1], portfolio.top_sums[0], portfolio.top_sums[2]),
        pb_rankings=(
            portfolio.pb_rankings[1],
            portfolio.pb_rankings[0],
            portfolio.pb_rankings[2],
        ),
    )
    assert review_portfolio(swapped, samples=100)["status"] == "passed"
    with pytest.raises(ValueError, match="ranking"):
        persist_cycle(
            swapped, analysis, snapshot, storage, workspace_root=tmp_path, cycle_id="swapped"
        )
    with storage._connect() as connection:
        assert connection.execute("SELECT count(*) FROM generation_batches").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM generated_picks").fetchone()[0] == 0


def test_pb_ranking_swapped_portfolio_cannot_persist(tmp_path):
    storage = reference_storage(tmp_path)
    analysis, portfolio, snapshot, _ = fixture(tmp_path)
    reordered = replace(
        portfolio,
        experimental=(
            replace(portfolio.experimental[1], pb_rank=1),
            replace(portfolio.experimental[0], pb_rank=2),
            *portfolio.experimental[2:],
        ),
        pb_rankings=(
            (portfolio.pb_rankings[0][1], portfolio.pb_rankings[0][0], portfolio.pb_rankings[0][2]),
            *portfolio.pb_rankings[1:],
        ),
    )
    assert review_portfolio(reordered, samples=100)["status"] == "passed"
    with pytest.raises(ValueError, match="ranking"):
        persist_cycle(
            reordered, analysis, snapshot, storage, workspace_root=tmp_path, cycle_id="bad-pb"
        )
    with storage._connect() as connection:
        assert connection.execute("SELECT count(*) FROM generation_batches").fetchone()[0] == 0


def test_saved_cycle_review_rejects_snapshot_at_generation_date(tmp_path):
    storage = reference_storage(tmp_path)
    analysis, portfolio, snapshot, _ = fixture(tmp_path)
    persist_cycle(portfolio, analysis, snapshot, storage, workspace_root=tmp_path, cycle_id="as-of")
    earlier = "2026-10-09T12:00:00+00:00"
    with storage._connect() as connection:
        connection.execute(
            "UPDATE generation_batches SET generated_at=? WHERE id='as-of'", (earlier,)
        )
        connection.execute(
            "UPDATE generated_picks SET generated_at=? WHERE batch_id='as-of'", (earlier,)
        )
    with pytest.raises(ValueError, match="snapshot"):
        review_saved_cycle(storage.storage_path, "as-of", workspace_root=tmp_path, samples=100)


def test_saved_cycle_review_refuses_modified_predraw_snapshot(tmp_path):
    storage = reference_storage(tmp_path)
    analysis, portfolio, snapshot, _ = fixture(tmp_path)
    persist_cycle(
        portfolio, analysis, snapshot, storage, workspace_root=tmp_path, cycle_id="frozen"
    )
    with sqlite3.connect(snapshot) as connection:
        connection.execute("UPDATE draws SET ball1=9 WHERE id=1")
    with pytest.raises(ValueError, match="snapshot"):
        review_saved_cycle(storage.storage_path, "frozen", workspace_root=tmp_path, samples=100)


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


def test_malformed_cycle_does_not_shadow_valid_cycle_for_same_draw(tmp_path):
    storage = reference_storage(tmp_path)
    analysis, portfolio, snapshot, draws = fixture(tmp_path)
    for cycle in ("valid", "malformed"):
        persist_cycle(
            portfolio, analysis, snapshot, storage, workspace_root=tmp_path, cycle_id=cycle
        )
    with storage._connect() as connection:
        connection.execute(
            "UPDATE generated_picks SET source_row=11 "
            "WHERE batch_id='malformed' AND source_row=10"
        )
    storage.evaluate_against_draws(str(draws))
    metrics = read_pb_metrics(storage.storage_path, workspace_root=tmp_path)
    assert metrics["incomplete_cycles"] == 1
    assert metrics["duplicate_target_cycles"] == 0
    assert metrics["evaluated_cycles"] == 1


def test_mismatched_cycle_does_not_shadow_valid_cycle_for_same_draw(tmp_path):
    storage = reference_storage(tmp_path)
    analysis, portfolio, snapshot, draws = fixture(tmp_path)
    for cycle in ("valid", "mismatched"):
        persist_cycle(
            portfolio, analysis, snapshot, storage, workspace_root=tmp_path, cycle_id=cycle
        )
    with storage._connect() as connection:
        row = connection.execute(
            "SELECT id, metadata_json FROM generated_picks "
            "WHERE batch_id='mismatched' AND source_row=10"
        ).fetchone()
        metadata = json.loads(row["metadata_json"])
        metadata["target_date"] = "2026-10-17"
        connection.execute(
            "UPDATE generated_picks SET metadata_json=? WHERE id=?",
            (json.dumps(metadata), row["id"]),
        )
    storage.evaluate_against_draws(str(draws))
    metrics = read_pb_metrics(storage.storage_path, workspace_root=tmp_path)
    assert metrics["mismatched_cycles"] == 1
    assert metrics["duplicate_target_cycles"] == 0
    assert metrics["evaluated_cycles"] == 1


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
