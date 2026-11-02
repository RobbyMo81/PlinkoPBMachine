"""Compatibility adapter for an isolated copy of the existing pick ledger.

Caller supplies an existing GeneratedPickStorage instance. Only disposable paths
under an explicit workspace root are accepted. No production import or writes.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from plinko.analysis import Analysis, analyze, load_draws, rank_powerballs, rank_sums
from plinko.engine import Portfolio, next_draw_date

SOURCE = "plinko_3x3_v1"
PRODUCTION_ROOT = Path("C:/Users/RobMo/OneDrive/Documents/PowerBall")
DRAW_ZONE = ZoneInfo("America/New_York")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _isolated(path: Path, root: Path) -> Path:
    resolved = Path(path).resolve()
    workspace = Path(root).resolve()
    if not resolved.is_relative_to(workspace) or resolved.is_relative_to(PRODUCTION_ROOT):
        raise ValueError("database must be within isolated workspace and outside production")
    return resolved


def persist_cycle(
    portfolio: Portfolio,
    result: Analysis,
    snapshot: Path,
    ledger,
    *,
    workspace_root: Path,
    cycle_id: str,
) -> str:
    """Use existing public batch/pick API; reject incomplete/misbound cycles.

    Underlying API commits per row. An interrupted batch remains visible but
    read_pb_metrics excludes it rather than deleting historical observations.
    """
    database = _isolated(snapshot, workspace_root)
    ledger_path = _isolated(ledger.storage_path, workspace_root)
    if not database.is_file() or not ledger_path.is_file():
        raise ValueError("isolated snapshot and ledger must already exist")
    if not cycle_id or not isinstance(cycle_id, str):
        raise ValueError("cycle_id required")
    if portfolio.dataset_hash != result.dataset_hash or len(portfolio.experimental) != 9:
        raise ValueError("analysis provenance or ticket count mismatch")
    if portfolio.generated_at.tzinfo is None or portfolio.generated_at.utcoffset() is None:
        raise ValueError("timezone-aware generation timestamp required")
    recorded_at = _utc_now()
    if (
        not timedelta(0)
        <= recorded_at - portfolio.generated_at.astimezone(UTC)
        <= timedelta(minutes=5)
    ):
        raise ValueError("generation timestamp must be current at persistence")
    if portfolio.target_date != next_draw_date(recorded_at):
        raise ValueError("generation timestamp is after or targets wrong draw")
    if portfolio.dataset_hash != analyze(load_draws(database).rows).dataset_hash:
        raise ValueError("snapshot content does not match portfolio dataset hash")
    # Never silently reuse a partially persisted identifier.
    with closing(sqlite3.connect(ledger_path.as_uri() + "?mode=ro", uri=True)) as conn:
        if conn.execute("SELECT 1 FROM generation_batches WHERE id=?", (cycle_id,)).fetchone():
            raise ValueError("cycle already exists; inspect and reconcile before retrying")
    ranks = rank_sums(result)[:10]
    strategy = {
        "schema": 1,
        "recorded_at": recorded_at.isoformat(),
        "target_date": portfolio.target_date.isoformat(),
        "dataset_hash": result.dataset_hash,
        "sum_rankings": [
            {
                "sum": r.total,
                "frequency": r.frequency,
                "last_date": r.last_date.isoformat(),
                "rank": r.rank,
                "frequency_tie": r.frequency_tie,
            }
            for r in ranks
        ],
        "selected_sums": list(portfolio.top_sums),
        "pb_rankings": [
            [
                {
                    "pb": p.pb,
                    "count": p.count,
                    "last_date": p.last_date.isoformat(),
                    "rank": p.rank,
                    "frequency_tie": p.frequency_tie,
                }
                for p in rank_powerballs(result, total)
            ]
            for total in portfolio.top_sums
        ],
        "wb_method": portfolio.wb_method,
        "wb_hot_neutral_cold": "observational only; pair-specific thresholds unavailable",
        "overlaps_checked": portfolio.overlaps_checked,
        "control_collision": portfolio.control_collision,
        "distinct_pbs": portfolio.distinct_pbs,
    }
    ledger.create_batch(
        source=SOURCE,
        generated_at=portfolio.generated_at,
        target_weekday=portfolio.target_date.strftime("%A"),
        seed=None,
        database_path=database,
        database_range=(result.first_date.isoformat(), result.last_date.isoformat()),
        generator_version=SOURCE,
        strategy=strategy,
        batch_id=cycle_id,
    )
    for index, ticket in enumerate((*portfolio.experimental, portfolio.control), 1):
        ledger.save_pick(
            {
                "white_balls": list(ticket.whites),
                "powerball": ticket.pb,
                "type": "plinko_experimental" if index <= 9 else "plinko_control",
                "target_weekday": portfolio.target_date.strftime("%A"),
                "target_date": portfolio.target_date.isoformat(),
                "ticket_index": index,
                "assigned_sum": ticket.total,
                "sum_rank": ticket.sum_rank,
                "pb_rank": ticket.pb_rank,
                "dataset_hash": portfolio.dataset_hash,
                "control_collision": portfolio.control_collision,
            },
            source=SOURCE,
            generated_at=portfolio.generated_at,
            batch_id=cycle_id,
            source_artifact=f"plinko:{cycle_id}",
            source_row=index,
        )
    with closing(sqlite3.connect(ledger_path.as_uri() + "?mode=ro", uri=True)) as conn:
        rows = conn.execute(
            "SELECT source_row,pick_type FROM generated_picks WHERE batch_id=? ORDER BY source_row",
            (cycle_id,),
        ).fetchall()
    if rows != [(i, "plinko_experimental" if i <= 9 else "plinko_control") for i in range(1, 11)]:
        raise ValueError("incomplete cycle; leave it for reconciliation, do not score")
    return cycle_id


def read_pb_metrics(ledger_path: Path, *, workspace_root: Path) -> dict:
    """Read current verified outcomes for complete, correctly attributed cycles."""
    path = _isolated(ledger_path, workspace_root)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        batches = conn.execute(
            "SELECT * FROM generation_batches WHERE source=? ORDER BY id", (SOURCE,)
        ).fetchall()
        complete = pending = incomplete = mismatched = duplicate = 0
        coverage_hits = experimental_hits = control_hits = 0
        baseline_sum = 0.0
        targets = Counter(
            json.loads(batch["strategy_json"]).get("target_date")
            for batch in batches
            if conn.execute(
                "SELECT COUNT(*) FROM generated_picks WHERE batch_id=?", (batch["id"],)
            ).fetchone()[0]
            == 10
        )
        for batch in batches:
            picks = conn.execute(
                "SELECT * FROM generated_picks WHERE batch_id=? ORDER BY source_row", (batch["id"],)
            ).fetchall()
            if (
                len(picks) != 10
                or [p["source_row"] for p in picks] != list(range(1, 11))
                or any(
                    p["pick_type"] != ("plinko_experimental" if i < 9 else "plinko_control")
                    for i, p in enumerate(picks)
                )
            ):
                incomplete += 1
                continue
            strategy = json.loads(batch["strategy_json"])
            target = strategy["target_date"]
            if targets[target] > 1:
                duplicate += 1
                continue
            if any(json.loads(p["metadata_json"]).get("target_date") != target for p in picks):
                mismatched += 1
                continue
            outcomes = [
                conn.execute(
                    "SELECT draw_date,draw_timestamp,powerball_match,timing_status,input_sha256 "
                    "FROM pick_evaluations WHERE pick_id=? AND is_current=1",
                    (p["id"],),
                ).fetchone()
                for p in picks
            ]
            if any(o and o["draw_date"] != target for o in outcomes):
                mismatched += 1
                continue
            if any(o is None for o in outcomes):
                pending += 1
                continue
            generated = datetime.fromisoformat(batch["generated_at"])
            recorded_text = strategy.get("recorded_at")
            recorded = datetime.fromisoformat(recorded_text) if recorded_text else None
            if (
                generated.tzinfo is None
                or recorded is None
                or recorded.tzinfo is None
                or not timedelta(0) <= recorded - generated.astimezone(UTC) <= timedelta(minutes=5)
                or any(
                    o["timing_status"] != "prospective"
                    or not o["input_sha256"]
                    or recorded >= datetime.fromisoformat(o["draw_timestamp"])
                    for o in outcomes
                )
            ):
                mismatched += 1
                continue
            complete += 1
            hits = sum(o["powerball_match"] for o in outcomes[:9])
            experimental_hits += hits
            coverage_hits += int(hits > 0)
            control_hits += outcomes[9]["powerball_match"]
            baseline_sum += len({p["powerball"] for p in picks[:9]}) / 26
    return {
        "evaluated_cycles": complete,
        "pending_cycles": pending,
        "incomplete_cycles": incomplete,
        "duplicate_target_cycles": duplicate,
        "mismatched_cycles": mismatched,
        "coverage_hits": coverage_hits,
        "experimental_hits": experimental_hits,
        "control_hits": control_hits,
        "experimental_opportunities": 9 * complete,
        "control_opportunities": complete,
        "coverage_rate": coverage_hits / complete if complete else None,
        "experimental_ticket_rate": experimental_hits / (9 * complete) if complete else None,
        "control_rate": control_hits / complete if complete else None,
        "distinct_pb_baseline": baseline_sum / complete if complete else None,
    }
