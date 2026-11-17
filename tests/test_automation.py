"""Isolated automation: duplicate safety, freshness, and official scoring."""

import importlib.util
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from plinko.automation import run_once
from plinko.tracking import read_pb_metrics

REFERENCE = Path("C:/Users/RobMo/PBMachine/core/generated_pick_storage.py")


def test_main_uses_only_local_copy_and_fails_closed_if_missing(tmp_path, monkeypatch):
    from plinko import automation

    monkeypatch.setattr(automation, "__file__", str(tmp_path / "plinko" / "automation.py"))
    root = tmp_path / ".cache"
    root.mkdir()
    source = root / "unified_storage.db"
    calls = []

    def fake_run_once(path, workspace_root):
        calls.append((path, workspace_root))
        return {"generated": None, "scored": False}

    monkeypatch.setattr(automation, "run_once", fake_run_once)
    with pytest.raises(SystemExit) as exc:
        automation.main()
    assert exc.value.code == 1
    assert calls == []
    assert (
        json.loads((root / "automation_runs.jsonl").read_text().splitlines()[0])["status"]
        == "error"
    )

    source.write_text("fixture", encoding="utf-8")
    automation.main()
    assert calls == [(source, root)]
    assert (
        json.loads((root / "automation_runs.jsonl").read_text().splitlines()[1])["status"] == "ok"
    )


def workspace(tmp_path):
    if not REFERENCE.exists():
        pytest.skip("reference tracker source absent")
    root = tmp_path / "isolated"
    root.mkdir()
    shutil.copyfile(REFERENCE, root / "isolated_generated_pick_storage.py")
    spec = importlib.util.spec_from_file_location(
        "tracker_test", root / "isolated_generated_pick_storage.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.GeneratedPickStorage(str(root / "plinko_experiment.db"))
    source = tmp_path / "draws.db"
    with sqlite3.connect(source) as conn:
        conn.execute(
            "CREATE TABLE draws (id INTEGER, draw_date TEXT, ball1 INTEGER, ball2 INTEGER, "
            "ball3 INTEGER, ball4 INTEGER, ball5 INTEGER, powerball INTEGER, "
            "source TEXT, record_hash TEXT, multiplier INTEGER)"
        )
        for i in range(1, 10):
            total, pb = (160, 165, 170)[(i - 1) // 3], (1, 2, 3)[(i - 1) % 3]
            conn.execute(
                "INSERT INTO draws VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    i,
                    f"2026-10-{i:02}",
                    10,
                    20,
                    30,
                    40,
                    total - pb - 100,
                    pb,
                    "fixture",
                    f"hash-{i}",
                    2,
                ),
            )
        conn.execute("INSERT INTO draws VALUES (10,'2026-10-10',1,2,3,4,5,20,'fixture','prior',2)")
    return source, root


def test_generation_is_saved_once_then_scores_only_after_official_draw(tmp_path, monkeypatch):
    source, root = workspace(tmp_path)
    clock = {"now": datetime(2026, 10, 12, 12, tzinfo=UTC)}
    monkeypatch.setattr("plinko.tracking._utc_now", lambda: clock["now"])
    first = run_once(source, root, now=clock["now"])
    assert first["generated"] == "plinko-auto-20261012"
    assert first["scored"] is False
    assert Path(first["snapshot"]).is_file()
    assert Path(first["ledger_backup"]).is_file()
    assert len(first["source_dataset_hash"]) == 64
    assert len(first["snapshot_sha256"]) == 64
    assert len(first["ledger_backup_sha256"]) == 64
    assert Path(first["schema_backup"]).is_file()
    second = run_once(source, root, now=clock["now"])
    assert second["generated"] is None
    with sqlite3.connect(root / "plinko_experiment.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM generation_batches").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM generated_picks").fetchone()[0] == 10
        assert conn.execute("SELECT COUNT(*) FROM pick_evaluations").fetchone()[0] == 0
    with sqlite3.connect(source) as conn:
        conn.execute(
            "INSERT INTO draws VALUES (11,'2026-10-12',1,2,3,4,5,2,'fixture','official',2)"
        )
    clock["now"] = datetime(2026, 10, 13, 12, tzinfo=UTC)
    scored = run_once(source, root, now=clock["now"])
    # A scoring pass is also the generation pass: the run that scores the
    # closed drawing stocks the next scheduled drawing in the same invocation.
    assert scored["scored"] is True
    assert scored["generated"] == "plinko-auto-20261014"
    assert (
        read_pb_metrics(root / "plinko_experiment.db", workspace_root=root)["evaluated_cycles"] == 1
    )
    again = run_once(source, root, now=clock["now"])
    assert again["scored"] is False
    assert again["generated"] is None
    with sqlite3.connect(root / "plinko_experiment.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM pick_evaluations").fetchone()[0] == 10
        assert conn.execute("SELECT COUNT(*) FROM generation_batches").fetchone()[0] == 2


def test_stale_source_refuses_generation_and_lock_refuses_concurrent_run(tmp_path):
    source, root = workspace(tmp_path)
    with sqlite3.connect(source) as conn:
        conn.execute("DELETE FROM draws WHERE draw_date='2026-10-10'")
    result = run_once(source, root, now=datetime(2026, 10, 12, 12, tzinfo=UTC))
    assert result["generated"] is None and result["reason"] == "stale_source"
    with sqlite3.connect(root / "plinko_experiment.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM generation_batches").fetchone()[0] == 0
    lock = root / ".cycle.lock"
    lock.write_text("held")
    with pytest.raises(RuntimeError, match="lock"):
        run_once(source, root, now=datetime(2026, 10, 12, 12, tzinfo=UTC))
    assert lock.read_text() == "held"


def test_off_draw_day_run_generates_the_next_draw_set(tmp_path, monkeypatch):
    source, root = workspace(tmp_path)
    with sqlite3.connect(source) as conn:
        conn.execute(
            "INSERT INTO draws VALUES (11,'2026-10-12',1,2,3,4,5,2,'fixture','official',2)"
        )
    clock = {"now": datetime(2026, 10, 13, 12, tzinfo=UTC)}  # Tuesday: no drawing today
    monkeypatch.setattr("plinko.tracking._utc_now", lambda: clock["now"])
    result = run_once(source, root, now=clock["now"])
    assert result["reason"] is None
    assert result["scored"] is False
    assert result["generated"] == "plinko-auto-20261014"
    with sqlite3.connect(root / "plinko_experiment.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM generation_batches").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM generated_picks").fetchone()[0] == 10
        strategy = json.loads(
            conn.execute("SELECT strategy_json FROM generation_batches").fetchone()[0]
        )
    assert strategy["target_date"] == "2026-10-14"
    metrics = read_pb_metrics(root / "plinko_experiment.db", workspace_root=root)
    assert metrics["pending_cycles"] == 1
    repeat = run_once(source, root, now=clock["now"])
    assert repeat["generated"] is None
    with sqlite3.connect(root / "plinko_experiment.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM generation_batches").fetchone()[0] == 1


def test_post_draw_same_day_source_defers_generation_but_scores(tmp_path, monkeypatch):
    source, root = workspace(tmp_path)
    clock = {"now": datetime(2026, 10, 12, 12, tzinfo=UTC)}  # Monday 08:00 ET, pre-draw
    monkeypatch.setattr("plinko.tracking._utc_now", lambda: clock["now"])
    assert run_once(source, root, now=clock["now"])["generated"] == "plinko-auto-20261012"
    with sqlite3.connect(source) as conn:
        conn.execute(
            "INSERT INTO draws VALUES (11,'2026-10-12',1,2,3,4,5,2,'fixture','official',2)"
        )
    # Monday 23:30 ET: today's drawing has closed and the local copy already
    # holds a draw dated today. Scoring must proceed; same-day generation must
    # defer (the frozen snapshot must predate the generation day).
    clock["now"] = datetime(2026, 10, 13, 3, 30, tzinfo=UTC)
    result = run_once(source, root, now=clock["now"])
    assert result["scored"] is True
    assert result["generated"] is None
    assert result["reason"] == "generation_day_conflict"
    with sqlite3.connect(root / "plinko_experiment.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM generation_batches").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM pick_evaluations").fetchone()[0] == 10
    # The next calendar day's run generates the following drawing's set.
    clock["now"] = datetime(2026, 10, 14, 12, tzinfo=UTC)  # Wednesday 08:00 ET, pre-draw
    resumed = run_once(source, root, now=clock["now"])
    assert resumed["reason"] is None
    assert resumed["generated"] == "plinko-auto-20261014"


def test_corrected_official_draw_revises_scoring(tmp_path, monkeypatch):
    source, root = workspace(tmp_path)
    clock = {"now": datetime(2026, 10, 12, 12, tzinfo=UTC)}
    monkeypatch.setattr("plinko.tracking._utc_now", lambda: clock["now"])
    run_once(source, root, now=clock["now"])
    with sqlite3.connect(source) as conn:
        conn.execute(
            "INSERT INTO draws VALUES (11,'2026-10-12',1,2,3,4,5,2,'fixture','official',2)"
        )
    after = datetime(2026, 10, 13, 12, tzinfo=UTC)
    clock["now"] = after
    assert run_once(source, root, now=after)["scored"] is True
    with sqlite3.connect(source) as conn:
        conn.execute(
            "UPDATE draws SET powerball=26,record_hash='corrected' " "WHERE draw_date='2026-10-12'"
        )
    corrected = run_once(source, root, now=after)
    assert corrected["scored"] is True
    with sqlite3.connect(root / "plinko_experiment.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM pick_evaluations").fetchone()[0] == 20
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM pick_evaluations WHERE is_current=1 AND "
                "json_extract(input_json, '$.draw.powerball')=26"
            ).fetchone()[0]
            == 10
        )


def test_concurrent_manual_target_cannot_create_duplicate(tmp_path, monkeypatch):
    from plinko import automation

    source, root = workspace(tmp_path)
    now = datetime(2026, 10, 12, 12, tzinfo=UTC)
    monkeypatch.setattr("plinko.tracking._utc_now", lambda: now)
    original = automation.refresh_analysis

    def competing_refresh(*args, **kwargs):
        result = original(*args, **kwargs)
        with sqlite3.connect(root / "plinko_experiment.db") as conn:
            conn.execute(
                "INSERT INTO generation_batches "
                "(id,generated_at,source,generator_version,strategy_json) "
                "VALUES (?,?,?,?,?)",
                (
                    "manual-concurrent",
                    now.isoformat(),
                    "plinko_3x3_v1",
                    "fixture",
                    json.dumps({"target_date": "2026-10-12"}),
                ),
            )
        return result

    monkeypatch.setattr(automation, "refresh_analysis", competing_refresh)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        run_once(source, root, now=now)
    with sqlite3.connect(root / "plinko_experiment.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM generation_batches").fetchone()[0] == 1


def test_target_changed_during_refresh_cannot_commit_evaluations(tmp_path, monkeypatch):
    from plinko import automation

    source, root = workspace(tmp_path)
    generated = datetime(2026, 10, 12, 12, tzinfo=UTC)
    monkeypatch.setattr("plinko.tracking._utc_now", lambda: generated)
    run_once(source, root, now=generated)
    with sqlite3.connect(source) as conn:
        conn.execute(
            "INSERT INTO draws VALUES (11,'2026-10-12',1,2,3,4,5,2,'fixture','official',2)"
        )
    original = automation._tracker

    def concurrent_change(path, ledger_path):
        with sqlite3.connect(root / "plinko_experiment.db") as conn:
            conn.execute(
                "UPDATE generation_batches SET strategy_json=? WHERE id='plinko-auto-20261012'",
                (json.dumps({"target_date": "2026-10-14"}),),
            )
            for row_id, text in conn.execute(
                "SELECT id,metadata_json FROM generated_picks "
                "WHERE batch_id='plinko-auto-20261012'"
            ).fetchall():
                metadata = json.loads(text)
                metadata["target_date"] = "2026-10-14"
                conn.execute(
                    "UPDATE generated_picks SET metadata_json=? WHERE id=?",
                    (json.dumps(metadata), row_id),
                )
        return original(path, ledger_path)

    monkeypatch.setattr(automation, "_tracker", concurrent_change)
    with pytest.raises(ValueError, match="changed|target"):
        run_once(source, root, now=datetime(2026, 10, 13, 12, tzinfo=UTC))
    with sqlite3.connect(root / "plinko_experiment.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM pick_evaluations").fetchone()[0] == 0


def test_schema_changed_during_scoring_cannot_publish_evaluations(tmp_path, monkeypatch):
    from plinko import automation

    source, root = workspace(tmp_path)
    generated = datetime(2026, 10, 12, 12, tzinfo=UTC)
    monkeypatch.setattr("plinko.tracking._utc_now", lambda: generated)
    run_once(source, root, now=generated)
    with sqlite3.connect(source) as conn:
        conn.execute(
            "INSERT INTO draws VALUES (11,'2026-10-12',1,2,3,4,5,2,'fixture','official',2)"
        )
    original = automation._tracker
    ledger = root / "plinko_experiment.db"

    def concurrent_schema_change(path, ledger_path):
        with sqlite3.connect(ledger) as conn:
            conn.execute("CREATE TABLE side_effects (id INTEGER PRIMARY KEY)")
            conn.execute(
                "CREATE TRIGGER evaluation_side_effect AFTER INSERT ON pick_evaluations "
                "BEGIN INSERT INTO side_effects(id) VALUES (NULL); END"
            )
        return original(path, ledger_path)

    monkeypatch.setattr(automation, "_tracker", concurrent_schema_change)
    with pytest.raises(ValueError, match="changed during scoring"):
        run_once(source, root, now=datetime(2026, 10, 13, 12, tzinfo=UTC))
    with sqlite3.connect(ledger) as conn:
        assert conn.execute("SELECT COUNT(*) FROM pick_evaluations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM side_effects").fetchone()[0] == 0


def test_misbound_complete_cycle_fails_before_any_evaluation_write(tmp_path, monkeypatch):
    source, root = workspace(tmp_path)
    generated = datetime(2026, 10, 12, 12, tzinfo=UTC)
    monkeypatch.setattr("plinko.tracking._utc_now", lambda: generated)
    run_once(source, root, now=generated)
    ledger = root / "plinko_experiment.db"
    with sqlite3.connect(ledger) as conn:
        conn.execute(
            "UPDATE generation_batches SET strategy_json=? WHERE id='plinko-auto-20261012'",
            (json.dumps({"target_date": "2026-10-14"}),),
        )
        for row_id, text in conn.execute(
            "SELECT id,metadata_json FROM generated_picks WHERE batch_id='plinko-auto-20261012'"
        ).fetchall():
            metadata = json.loads(text)
            metadata["target_date"] = "2026-10-14"
            conn.execute(
                "UPDATE generated_picks SET metadata_json=? WHERE id=?",
                (json.dumps(metadata), row_id),
            )
    with sqlite3.connect(source) as conn:
        conn.execute(
            "INSERT INTO draws VALUES (11,'2026-10-12',1,2,3,4,5,2,'fixture','official',2)"
        )
        conn.execute("INSERT INTO draws VALUES (12,'2026-10-14',1,2,3,4,5,3,'fixture','later',2)")
    with pytest.raises(ValueError, match="target"):
        run_once(source, root, now=datetime(2026, 10, 15, 12, tzinfo=UTC))
    with sqlite3.connect(ledger) as conn:
        assert conn.execute("SELECT COUNT(*) FROM pick_evaluations").fetchone()[0] == 0


def test_existing_target_is_not_overwritten_and_wrong_target_is_not_scored(tmp_path, monkeypatch):
    source, root = workspace(tmp_path)
    monkeypatch.setattr("plinko.tracking._utc_now", lambda: datetime(2026, 10, 12, 12, tzinfo=UTC))
    run_once(source, root, now=datetime(2026, 10, 12, 12, tzinfo=UTC))
    with sqlite3.connect(root / "plinko_experiment.db") as conn:
        conn.execute(
            "UPDATE generation_batches SET strategy_json=? WHERE id='plinko-auto-20261012'",
            (json.dumps({"target_date": "2026-10-14"}),),
        )
    with sqlite3.connect(source) as conn:
        conn.execute(
            "INSERT INTO draws VALUES (11,'2026-10-12',1,2,3,4,5,2,'fixture','official',2)"
        )
    with pytest.raises(ValueError, match="target"):
        run_once(source, root, now=datetime(2026, 10, 13, 12, tzinfo=UTC))
    with sqlite3.connect(root / "plinko_experiment.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM pick_evaluations").fetchone()[0] == 0
