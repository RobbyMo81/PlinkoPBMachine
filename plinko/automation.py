"""Bounded, isolated once-runner for prospective Plinko generation and scoring.

The canonical draw database is read only. All writes remain under workspace_root.
No lottery purchase or model tuning is performed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import os
import shutil
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from plinko.analysis import analyze, load_draws
from plinko.engine import DRAW_WEEKDAYS, DRAW_ZONE, build_portfolio, next_draw_date
from plinko.refresh import refresh_analysis, sha256
from plinko.tracking import _isolated, persist_cycle, read_pb_metrics


def _tracker(path: Path, ledger_path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"isolated tracker missing: {path}")
    spec = importlib.util.spec_from_file_location("isolated_plinko_tracker", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load isolated tracker: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GeneratedPickStorage(str(ledger_path))


def _batches(ledger_path: Path):
    with closing(sqlite3.connect(ledger_path.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        batches = conn.execute(
            "SELECT id, generated_at, strategy_json FROM generation_batches "
            "WHERE source='plinko_3x3_v1' ORDER BY id"
        ).fetchall()
        records = []
        for batch in batches:
            target = date.fromisoformat(json.loads(batch["strategy_json"])["target_date"])
            picks = conn.execute(
                "SELECT id, source_row, pick_type, metadata_json FROM generated_picks "
                "WHERE batch_id=? ORDER BY source_row",
                (batch["id"],),
            ).fetchall()
            if (
                len(picks) != 10
                or [p["source_row"] for p in picks] != list(range(1, 11))
                or any(
                    p["pick_type"] != ("plinko_experimental" if n < 10 else "plinko_control")
                    or json.loads(p["metadata_json"]).get("target_date") != target.isoformat()
                    for n, p in enumerate(picks, 1)
                )
            ):
                raise ValueError(f"incomplete or wrong target cycle: {batch['id']}")
            generated = datetime.fromisoformat(batch["generated_at"])
            if generated.tzinfo is None or next_draw_date(generated) != target:
                raise ValueError(f"target binding invalid for cycle: {batch['id']}")
            evaluations = [
                conn.execute(
                    "SELECT draw_date, timing_status, input_json FROM pick_evaluations "
                    "WHERE pick_id=? AND is_current=1",
                    (p["id"],),
                ).fetchall()
                for p in picks
            ]
            if any(len(rows) > 1 for rows in evaluations):
                raise ValueError(f"multiple current evaluations for cycle: {batch['id']}")
            if any(rows for rows in evaluations) and not all(rows for rows in evaluations):
                raise ValueError(f"partial evaluations for cycle: {batch['id']}")
            if all(evaluations) and any(
                rows[0]["draw_date"] != target.isoformat()
                or rows[0]["timing_status"] != "prospective"
                for rows in evaluations
            ):
                raise ValueError(f"wrong target evaluation for cycle: {batch['id']}")
            stored_draw = (
                json.loads(evaluations[0][0]["input_json"])["draw"] if all(evaluations) else None
            )
            records.append((batch["id"], target, not all(evaluations), stored_draw))
        return records


def _unique_target_index(ledger_path: Path, root: Path) -> Path | None:
    """Enforce one target across manual and scheduled writers at SQLite level."""
    with closing(sqlite3.connect(ledger_path)) as conn:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='plinko_target_unique'"
        ).fetchone():
            return None
        backup = root / f"auto_before_index_{uuid.uuid4().hex}.db"
        with closing(sqlite3.connect(backup)) as destination:
            conn.backup(destination)
        with conn:
            conn.execute(
                "CREATE UNIQUE INDEX plinko_target_unique ON generation_batches("
                "json_extract(strategy_json, '$.target_date')) "
                "WHERE source='plinko_3x3_v1'"
            )
        return backup


def _official_draws(source: Path) -> dict[str, dict]:
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        return {
            row["draw_date"]: {
                "draw_date": row["draw_date"],
                "white_balls": sorted(row[f"ball{i}"] for i in range(1, 6)),
                "powerball": row["powerball"],
                "multiplier": row["multiplier"],
                "source": row["source"],
            }
            for row in conn.execute("SELECT * FROM draws")
        }


def _ledger_digest(conn: sqlite3.Connection) -> str:
    """Fingerprint scoring rows and schema before publishing staged results."""
    digest = hashlib.sha256()
    schema = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
    ).fetchall()
    digest.update(json.dumps([tuple(row) for row in schema], separators=(",", ":")).encode())
    # SQLite's backup API may reset schema_version even for identical schemas.
    for table in ("generation_batches", "generated_picks", "pick_evaluations"):
        digest.update(table.encode())
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        digest.update(json.dumps([tuple(row) for row in rows], separators=(",", ":")).encode())
    return digest.hexdigest()


def _promote_evaluations(ledger_path: Path, backup: Path, staged: Path) -> None:
    """Only publish staged evaluations if the live ledger is still the backup."""
    with closing(sqlite3.connect(backup)) as original:
        baseline = _ledger_digest(original)
    with closing(sqlite3.connect(ledger_path)) as live:
        live.execute("ATTACH DATABASE ? AS staged", (str(staged),))
        try:
            live.execute("BEGIN IMMEDIATE")
            if _ledger_digest(live) != baseline:
                raise ValueError("isolated ledger changed during scoring; no evaluations published")
            # Preserve every old and revised row; only the evaluation table changes.
            live.execute("DELETE FROM main.pick_evaluations")
            live.execute("INSERT INTO main.pick_evaluations SELECT * FROM staged.pick_evaluations")
            live.commit()
        except BaseException:
            live.rollback()
            raise
        finally:
            live.execute("DETACH DATABASE staged")


def _previous_draw(day: date) -> date:
    candidate = day - timedelta(days=1)
    while candidate.weekday() not in DRAW_WEEKDAYS:
        candidate -= timedelta(days=1)
    return candidate


def run_once(source: Path, workspace_root: Path, *, now: datetime | None = None) -> dict:
    """Score recorded cycles with official results; persist one set for the
    next scheduled drawing whenever no cycle targets it.

    Repeated invocations are idempotent. A lock prevents concurrent jobs. A stale
    lock is intentionally not auto-broken: inspect the ledger before removing it.
    """
    moment = now if now is not None else datetime.now(UTC)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("timezone-aware clock required")
    root = Path(workspace_root).resolve()
    ledger_path = _isolated(root / "plinko_experiment.db", root)
    tracker_path = _isolated(root / "isolated_generated_pick_storage.py", root)
    if not root.is_dir() or not ledger_path.is_file():
        raise ValueError("existing isolated workspace and ledger required")
    lock_path = root / ".cycle.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("cycle lock exists; inspect and reconcile before removing") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(moment.isoformat())
        return _run_locked(Path(source), root, ledger_path, tracker_path, moment)
    finally:
        lock_path.unlink()


def _run_locked(source: Path, root: Path, ledger_path: Path, tracker_path: Path, now: datetime):
    local = now.astimezone(DRAW_ZONE)
    schema_backup = _unique_target_index(ledger_path, root)
    existing = _batches(ledger_path)
    target = next_draw_date(now)
    if sum(cycle_target == local.date() for _, cycle_target, _, _ in existing) > 1:
        raise ValueError("duplicate target cycles need reconciliation")
    loaded = load_draws(source)
    current = analyze(loaded.rows)
    if current.last_date > local.date():
        raise ValueError("future source draw date")
    dates = {draw.draw_date for draw in loaded.rows}
    pending = [(cycle, day) for cycle, day, is_pending, _ in existing if is_pending]
    for cycle, day in pending:
        if day not in dates and current.last_date >= day:
            raise ValueError(f"missing official target draw for cycle: {cycle}")
    official = _official_draws(source)
    for cycle, day, is_pending, _ in existing:
        if not is_pending and day.isoformat() not in official:
            raise ValueError(f"missing scored official target draw for cycle: {cycle}")
    ready = [(cycle, day) for cycle, day in pending if day in dates]
    ready.extend(
        (cycle, day)
        for cycle, day, is_pending, stored_draw in existing
        if not is_pending and stored_draw != official[day.isoformat()]
    )
    # Coverage policy: every run that observes no cycle for the next
    # scheduled drawing generates one, so a scoring pass after a drawing
    # closes also stocks the following drawing — no draw is skipped when
    # runs happen off the target's own day. Deferrals are recorded, never
    # silent, and never block scoring.
    needs_generation = not any(day == target for _, day, _, _ in existing)
    reason = None
    if needs_generation and _previous_draw(target) not in dates:
        needs_generation = False
        reason = "stale_source"
    elif needs_generation and current.last_date >= local.date():
        # The frozen pre-draw snapshot must predate the generation day: a
        # source already holding a draw dated today defers generation to the
        # next calendar day's run. Scoring below is unaffected.
        needs_generation = False
        reason = "generation_day_conflict"
    result = {"generated": None, "scored": False, "reason": reason, "metrics": None}
    if schema_backup is not None:
        result["schema_backup"] = str(schema_backup)
        result["schema_backup_sha256"] = sha256(schema_backup)
    if not ready and not needs_generation:
        result["metrics"] = read_pb_metrics(ledger_path, workspace_root=root)
        return result
    suffix = uuid.uuid4().hex
    snapshot = root / f"auto_snapshot_{suffix}.db"
    analysis, provenance = refresh_analysis(source, snapshot, workspace_root=root)
    if not (analysis.dataset_hash == current.dataset_hash == provenance["source_dataset_hash"]):
        raise ValueError("source changed before snapshot")
    result["source_dataset_hash"] = provenance["source_dataset_hash"]
    result["snapshot_sha256"] = provenance["snapshot_sha256"]
    if ready or needs_generation:
        backup = root / f"auto_ledger_before_{suffix}.db"
        with (
            closing(sqlite3.connect(ledger_path.as_uri() + "?mode=ro", uri=True)) as upstream,
            closing(sqlite3.connect(backup)) as destination,
        ):
            upstream.backup(destination)
        result["snapshot"] = str(snapshot)
        result["ledger_backup"] = str(backup)
        result["ledger_backup_sha256"] = sha256(backup)
    if ready:
        staged = root / f"auto_staged_evaluations_{suffix}.db"
        shutil.copyfile(backup, staged)
        staged_storage = _tracker(tracker_path, staged)
        outcome = staged_storage.evaluate_against_draws(str(snapshot))
        after = _batches(staged)
        if any(is_pending for cycle, _, is_pending, _ in after if cycle in {r[0] for r in ready}):
            raise ValueError("official cycle not fully evaluated in staging")
        staged_metrics = read_pb_metrics(staged, workspace_root=root)
        if staged_metrics["mismatched_cycles"] or staged_metrics["incomplete_cycles"]:
            raise ValueError("staged scoring failed cycle validation")
        _promote_evaluations(ledger_path, backup, staged)
        result["staged_evaluations"] = str(staged)
        result["scored"] = bool(outcome["evaluated"])
        result["evaluation"] = outcome
    if needs_generation:
        storage = _tracker(tracker_path, ledger_path)
        generated_at = now
        portfolio = build_portfolio(analysis, target, generated_at)
        if len(tuple(itertools.combinations(portfolio.experimental, 2))) != 36:
            raise AssertionError("incomplete overlap audit")
        cycle = f"plinko-auto-{target:%Y%m%d}"
        persist_cycle(portfolio, analysis, snapshot, storage, workspace_root=root, cycle_id=cycle)
        after = _batches(ledger_path)
        if (cycle, target, True, None) not in after:
            raise ValueError("new cycle not completely saved")
        result["generated"] = cycle
    result["metrics"] = read_pb_metrics(ledger_path, workspace_root=root)
    return result


def main() -> None:
    repo = Path(__file__).resolve().parent.parent
    root = repo / ".cache"
    source = root / "unified_storage.db"
    try:
        if not source.is_file():
            raise FileNotFoundError(f"local copied draw database missing: {source}")
        outcome = run_once(source, root)
        record = {"at": datetime.now(UTC).isoformat(), "status": "ok", **outcome}
    except Exception as exc:  # noqa: BLE001 - scheduled runs must log unexpected failures
        record = {"at": datetime.now(UTC).isoformat(), "status": "error", "error": str(exc)}
    root.mkdir(exist_ok=True)
    with (root / "automation_runs.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
    print(json.dumps(record, sort_keys=True))
    if record["status"] != "ok":
        sys.exit(1)


if __name__ == "__main__":
    main()
