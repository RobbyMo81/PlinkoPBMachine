"""Reproducible null-model review of a fixed Plinko draw set.

This review never selects tickets, changes the control, or claims an edge.
Uniform independent official draws are the only simulated outcomes.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

from plinko.analysis import Analysis, analyze, load_draws, rank_powerballs, rank_sums
from plinko.engine import DRAW_ZONE, Portfolio, Ticket, next_draw_date

REVIEW_VERSION = "uniform_draw_null_v1"
DEFAULT_SAMPLES = 20_000


def validate_source_rankings(portfolio: Portfolio, analysis: Analysis) -> None:
    """Bind the claimed 3x3 ranking order to the frozen pre-draw observations."""
    expected_sums = tuple(item.total for item in rank_sums(analysis, require=3)[:3])
    expected_pbs = tuple(
        tuple(item.pb for item in rank_powerballs(analysis, total, require=3)[:3])
        for total in expected_sums
    )
    if (
        portfolio.dataset_hash != analysis.dataset_hash
        or portfolio.top_sums != expected_sums
        or portfolio.pb_rankings != expected_pbs
    ):
        raise ValueError("portfolio ranking differs from verified source analysis")


def review_portfolio(portfolio: Portfolio, *, samples: int = DEFAULT_SAMPLES) -> dict:
    """Validate a fixed 9+1 set, then simulate independent uniform draws."""
    if type(samples) is not int or not 1 <= samples <= 100_000:
        raise ValueError("samples must be an integer in [1, 100000]")
    if len(portfolio.experimental) != 9 or portfolio.control.kind != "CONTROL_RANDOM":
        raise ValueError("review requires nine experimental tickets and one independent control")
    if len(portfolio.top_sums) != 3 or len(portfolio.pb_rankings) != 3:
        raise ValueError("review requires three ranked sum/PB groups")
    tickets = (*portfolio.experimental, portfolio.control)
    for index, ticket in enumerate(tickets):
        whites = ticket.whites
        if (
            len(whites) != 5
            or len(set(whites)) != 5
            or tuple(sorted(whites)) != whites
            or any(type(ball) is not int or not 1 <= ball <= 69 for ball in whites)
            or type(ticket.pb) is not int
            or not 1 <= ticket.pb <= 26
        ):
            raise ValueError("invalid ticket ball structure")
        if index < 9:
            group, slot = divmod(index, 3)
            if (
                ticket.kind != "EXPERIMENTAL"
                or ticket.total != sum(whites) + ticket.pb
                or ticket.total != portfolio.top_sums[group]
            ):
                raise ValueError("experimental sum assignment mismatch")
            if (
                ticket.sum_rank != group + 1
                or ticket.pb_rank != slot + 1
                or len(portfolio.pb_rankings[group]) != 3
                or ticket.pb != portfolio.pb_rankings[group][slot]
            ):
                raise ValueError("experimental PB ranking mismatch")
        elif ticket.total is not None or ticket.sum_rank is not None or ticket.pb_rank is not None:
            raise ValueError("control must be untargeted")
    pairs = tuple(itertools.combinations(portfolio.experimental, 2))
    if (
        len(pairs) != 36
        or portfolio.overlaps_checked != 36
        or any(len(set(a.whites) & set(b.whites)) > 2 for a, b in pairs)
    ):
        raise ValueError("experimental overlap invariant failed")
    distinct = len({ticket.pb for ticket in portfolio.experimental})
    collision = any(
        (ticket.whites, ticket.pb) == (portfolio.control.whites, portfolio.control.pb)
        for ticket in portfolio.experimental
    )
    if distinct != portfolio.distinct_pbs or collision != portfolio.control_collision:
        raise ValueError("PB coverage or control collision metadata mismatch")

    payload = {
        "version": REVIEW_VERSION,
        "samples": samples,
        "target_date": portfolio.target_date.isoformat(),
        "dataset_hash": portfolio.dataset_hash,
        "tickets": [(ticket.whites, ticket.pb) for ticket in tickets],
    }
    seed_sha256 = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    rng = random.Random(int(seed_sha256, 16))
    white_sets = tuple(set(ticket.whites) for ticket in tickets)
    pb_coverage = exp_pb_hits = control_pb_hits = exp_prizes = control_prizes = 0
    for _ in range(samples):
        winning_whites = set(rng.sample(range(1, 70), 5))
        winning_pb = rng.randrange(1, 27)
        if winning_pb in {ticket.pb for ticket in portfolio.experimental}:
            pb_coverage += 1
        for index, (ticket, whites) in enumerate(zip(tickets, white_sets)):
            pb_hit = ticket.pb == winning_pb
            white_hits = len(whites & winning_whites)
            if index < 9:
                exp_pb_hits += pb_hit
                exp_prizes += pb_hit or white_hits >= 3
            else:
                control_pb_hits += pb_hit
                control_prizes += pb_hit or white_hits >= 3
    exact_coverage = distinct / 26
    coverage_tolerance = 6 * math.sqrt(exact_coverage * (1 - exact_coverage) / samples)
    if abs(pb_coverage / samples - exact_coverage) > coverage_tolerance:
        raise ValueError("Monte Carlo PB coverage disagrees with exact null baseline")
    return {
        "status": "passed",
        "version": REVIEW_VERSION,
        "target_date": portfolio.target_date.isoformat(),
        "dataset_hash": portfolio.dataset_hash,
        "review_seed_sha256": seed_sha256,
        "samples": samples,
        "overlap_pairs_checked": len(pairs),
        "control_collision": collision,
        "distinct_experimental_pbs": distinct,
        "exact_pb_coverage": exact_coverage,
        "pb_coverage_six_sigma_tolerance": coverage_tolerance,
        "null_ticket_pb_rate": 1 / 26,
        "simulated_pb_coverage": pb_coverage / samples,
        "experimental_ticket_trials": 9 * samples,
        "control_ticket_trials": samples,
        "experimental_ticket_pb_rate": exp_pb_hits / (9 * samples),
        "control_ticket_pb_rate": control_pb_hits / samples,
        "experimental_any_prize_rate": exp_prizes / (9 * samples),
        "control_any_prize_rate": control_prizes / samples,
        "interpretation": "Uniform-draw sanity check only; no predictive edge or ticket selection.",
    }


def review_saved_cycle(
    ledger_path: Path, cycle_id: str, *, workspace_root: Path, samples: int = DEFAULT_SAMPLES
) -> dict:
    """Reconstruct an immutable recorded cycle for read-only retrospective review."""
    root = Path(workspace_root).resolve()
    ledger = Path(ledger_path).resolve()
    if not ledger.is_relative_to(root) or not ledger.is_file():
        raise ValueError("review ledger must exist inside isolated workspace")
    with closing(sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        batch = conn.execute(
            "SELECT * FROM generation_batches WHERE id=? AND source=?",
            (cycle_id, "plinko_3x3_v1"),
        ).fetchone()
        if batch is None:
            raise ValueError("isolated cycle not found")
        rows = conn.execute(
            "SELECT * FROM generated_picks WHERE batch_id=? ORDER BY source_row",
            (cycle_id,),
        ).fetchall()
        if len(rows) != 10 or [row["source_row"] for row in rows] != list(range(1, 11)):
            raise ValueError("saved cycle is incomplete")
        strategy = json.loads(batch["strategy_json"])
        target = date.fromisoformat(strategy["target_date"])
        generated_at = datetime.fromisoformat(batch["generated_at"])
        if next_draw_date(generated_at) != target:
            raise ValueError("saved cycle target binding invalid")
        snapshot = Path(batch["database_path"]).resolve()
        if not snapshot.is_relative_to(root) or not snapshot.is_file():
            raise ValueError("saved snapshot outside isolated workspace or missing")
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != batch["database_sha256"]:
            raise ValueError("saved snapshot checksum changed")
        analysis = analyze(load_draws(snapshot).rows)
        if analysis.dataset_hash != strategy["dataset_hash"]:
            raise ValueError("saved snapshot draw dataset changed")
        if analysis.last_date >= generated_at.astimezone(DRAW_ZONE).date():
            raise ValueError("saved snapshot includes draw on/after generation date")
        tickets = []
        for index, row in enumerate(rows, 1):
            metadata = json.loads(row["metadata_json"])
            expected_kind = "plinko_experimental" if index <= 9 else "plinko_control"
            if (
                row["source"] != "plinko_3x3_v1"
                or row["pick_type"] != expected_kind
                or datetime.fromisoformat(row["generated_at"]) != generated_at
                or metadata.get("ticket_index") != index
                or metadata.get("target_date") != target.isoformat()
                or metadata.get("dataset_hash") != strategy["dataset_hash"]
            ):
                raise ValueError("saved ticket provenance mismatch")
            tickets.append(
                Ticket(
                    tuple(row[f"ball{number}"] for number in range(1, 6)),
                    row["powerball"],
                    "EXPERIMENTAL" if index <= 9 else "CONTROL_RANDOM",
                    metadata.get("assigned_sum"),
                    metadata.get("sum_rank"),
                    metadata.get("pb_rank"),
                )
            )
    portfolio = Portfolio(
        tuple(tickets[:9]),
        tickets[9],
        target,
        generated_at,
        strategy["dataset_hash"],
        tuple(strategy["selected_sums"]),
        tuple(tuple(item["pb"] for item in group[:3]) for group in strategy["pb_rankings"]),
        strategy["overlaps_checked"],
        strategy["control_collision"],
        strategy["distinct_pbs"],
        strategy["wb_method"],
    )
    validate_source_rankings(portfolio, analysis)
    review = review_portfolio(portfolio, samples=samples)
    recorded = strategy.get("monte_carlo_review")
    if recorded is not None and samples == recorded["samples"] and review != recorded:
        raise ValueError("saved Monte Carlo review does not match recorded tickets")
    return review
