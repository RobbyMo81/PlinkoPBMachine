"""Isolated repeated refreshes preserve old portfolio data provenance."""

import sqlite3
from pathlib import Path

import pytest

from plinko.refresh import refresh_analysis, sha256

DRAW_SCHEMA = (
    "CREATE TABLE draws (id INTEGER, draw_date TEXT, ball1 INTEGER, "
    "ball2 INTEGER, ball3 INTEGER, ball4 INTEGER, ball5 INTEGER, "
    "powerball INTEGER, source TEXT, record_hash TEXT)"
)
DRAW_1 = "INSERT INTO draws VALUES (1,'2026-10-07',1,2,3,4,5,1,'fixture','a')"
DRAW_2 = "INSERT INTO draws VALUES (2,'2026-10-10',1,2,3,4,6,2,'fixture','b')"


def test_new_snapshot_for_each_refresh_and_old_snapshot_immutable(tmp_path: Path):
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as conn:
        conn.execute(
            "CREATE TABLE draws (id INTEGER, draw_date TEXT, ball1 INTEGER, "
            "ball2 INTEGER, ball3 INTEGER, ball4 INTEGER, ball5 INTEGER, "
            "powerball INTEGER, source TEXT, record_hash TEXT)"
        )
        conn.execute("INSERT INTO draws VALUES (1,'2026-10-07',1,2,3,4,5,1,'fixture','a')")
    first = tmp_path / "first.db"
    old, old_hash = refresh_analysis(source, first, workspace_root=tmp_path)
    with sqlite3.connect(source) as conn:
        conn.execute("INSERT INTO draws VALUES (2,'2026-10-10',1,2,3,4,6,2,'fixture','b')")
    second, new_hash = refresh_analysis(source, tmp_path / "second.db", workspace_root=tmp_path)
    assert old.draw_count == 1 and second.draw_count == 2
    assert old.dataset_hash != second.dataset_hash
    assert old_hash["snapshot_sha256"] != new_hash["snapshot_sha256"]
    assert first.exists()
    with pytest.raises(ValueError, match="new path"):
        refresh_analysis(source, first, workspace_root=tmp_path)
    with pytest.raises(ValueError, match="workspace"):
        refresh_analysis(source, tmp_path.parent / "outside.db", workspace_root=tmp_path)


def test_wal_commits_change_source_provenance_without_checkpoint(tmp_path: Path):
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(DRAW_SCHEMA)
        writer.execute(DRAW_1)
        writer.commit()
        main_file_hash = sha256(source)
        first, first_provenance = refresh_analysis(
            source, tmp_path / "first.db", workspace_root=tmp_path
        )
        writer.execute(DRAW_2)
        writer.commit()
        second, second_provenance = refresh_analysis(
            source, tmp_path / "second.db", workspace_root=tmp_path
        )
        assert sha256(source) == main_file_hash
    assert first.draw_count == 1 and second.draw_count == 2
    assert first_provenance["source_dataset_hash"] == first.dataset_hash
    assert second_provenance["source_dataset_hash"] == second.dataset_hash
    assert first_provenance["source_dataset_hash"] != second_provenance["source_dataset_hash"]


def test_wal_source_change_during_refresh_is_rejected_and_snapshot_removed(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "source.db"
    snapshot = tmp_path / "snapshot.db"
    with sqlite3.connect(source) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(DRAW_SCHEMA)
        writer.execute(DRAW_1)
        writer.commit()
        original_hash = sha256(source)
        from plinko import refresh

        real_load_draws = refresh.load_draws

        def load_and_update(path):
            loaded = real_load_draws(path)
            if path == snapshot:
                writer.execute(DRAW_2)
                writer.commit()
            return loaded

        monkeypatch.setattr(refresh, "load_draws", load_and_update)
        with pytest.raises(ValueError, match="source changed"):
            refresh_analysis(source, snapshot, workspace_root=tmp_path)
        assert sha256(source) == original_hash
    assert not snapshot.exists()


def test_wal_write_and_revert_still_fails_stability_guard(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.db"
    snapshot = tmp_path / "snapshot.db"
    with sqlite3.connect(source) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute(DRAW_SCHEMA)
        writer.execute(DRAW_1)
        writer.commit()
        from plinko import refresh

        real_load_draws = refresh.load_draws

        def load_and_revert(path):
            loaded = real_load_draws(path)
            if path == snapshot:
                writer.execute("UPDATE draws SET record_hash='changed' WHERE id=1")
                writer.commit()
                writer.execute("UPDATE draws SET record_hash='a' WHERE id=1")
                writer.commit()
            return loaded

        monkeypatch.setattr(refresh, "load_draws", load_and_revert)
        with pytest.raises(ValueError, match="source changed"):
            refresh_analysis(source, snapshot, workspace_root=tmp_path)
    assert not snapshot.exists()


def test_failed_snapshot_validation_removes_provisional_file(tmp_path: Path):
    source = tmp_path / "invalid.db"
    snapshot = tmp_path / "snapshot.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE unrelated (value INTEGER)")
    with pytest.raises(sqlite3.OperationalError, match="no such table: draws"):
        refresh_analysis(source, snapshot, workspace_root=tmp_path)
    assert not snapshot.exists()
