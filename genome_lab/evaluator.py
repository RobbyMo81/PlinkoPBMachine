"""Evaluator (Document 02, build step 5; P-03.01 / EVAL-01).

Only the evaluator receives the full immutable development export. Before
scoring it rechecks the count and fingerprint against the authenticated
DATA-01 publication record. A hit is a development draw whose actual
Powerball is among the genome's three highest-ranked PB values (build
decision B1). Under the fair independent-draw model, expected hits are
N x 3/26 and the standard deviation is sqrt(N x 3/26 x 23/26). Comparisons
stay descriptive: observed rates do not determine MVP success.
"""

import json
import math
from collections.abc import Mapping
from pathlib import Path

from genome_lab.config import CHANCE_P, EXPECTED_DEV_COUNT
from genome_lab.dna import canonical_bytes, sha256_hex
from genome_lab.genomes import is_hit
from genome_lab.identity import Identity
from genome_lab.journal import Journal
from genome_lab.snapshot import fetch_window_rows, open_readonly, rows_digest


class EvaluatorError(RuntimeError):
    """Raised when scoring preconditions fail."""


def expected_and_sd(draw_count: int) -> tuple[float, float]:
    expected = draw_count * CHANCE_P
    sd = math.sqrt(draw_count * CHANCE_P * (1 - CHANCE_P))
    return expected, sd


class Evaluator:
    def __init__(self, journal: Journal, identity: Identity) -> None:
        self._journal = journal
        self._identity = identity

    def recheck_publication(self, export_path, publication: Mapping) -> tuple[int, str]:
        """DATA-01 (evaluator side): independently recount and rehash the export."""
        window = publication["window"]
        conn = open_readonly(export_path)
        try:
            rows = fetch_window_rows(conn, window["start"], window["end"])
        finally:
            conn.close()
        count, digest = len(rows), rows_digest(rows)
        if count != publication["count"] or digest != publication["digest"]:
            raise EvaluatorError(
                f"export does not match the publication record: "
                f"count {count} vs {publication['count']}, digest mismatch"
            )
        if not publication.get("count_matches_expected", False) and count != EXPECTED_DEV_COUNT:
            raise EvaluatorError(
                f"development count {count} differs from expected {EXPECTED_DEV_COUNT};"
                " reconcile before scoring"
            )
        return count, digest

    def tally_fixture(self, fixture_path, ranking: list[int]) -> dict:
        """Tally the limited fixture against a complete PB ranking (EVAL-01)."""
        fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        draws = fixture["draws"]
        hits = sum(1 for draw in draws if is_hit(draw["powerball"], ranking))
        digest = sha256_hex(
            canonical_bytes({"source_digest": fixture["source_digest"], "draws": draws})
        )
        return {
            "fixture_digest": digest,
            "dates": [draw["date"] for draw in draws],
            "denominator": len(draws),
            "hits": hits,
        }

    def score_seed(self, export_path, window: Mapping, ranking: list[int]) -> dict:
        """Historical scoring of one fixed ranking over the full export."""
        conn = open_readonly(export_path)
        try:
            rows = fetch_window_rows(conn, window["start"], window["end"])
        finally:
            conn.close()
        hits = sum(1 for row in rows if is_hit(row["powerball"], ranking))
        denominator = len(rows)
        expected, sd = expected_and_sd(denominator)
        return {
            "hits": hits,
            "denominator": denominator,
            "rate": hits / denominator,
            "expected_hits": expected,
            "standard_deviation": sd,
            "chance_rate": CHANCE_P,
        }

    def distinct_draws(self, draws: Mapping[str, tuple[tuple[int, ...], int]]) -> dict:
        """Count distinct complete draws once; white-ball order is immaterial."""
        seen: dict[tuple[tuple[int, ...], int], list[str]] = {}
        for name, (whites, pb) in draws.items():
            key = (tuple(sorted(whites)), pb)
            seen.setdefault(key, []).append(name)
        duplicates = {str(key): names for key, names in seen.items() if len(names) > 1}
        return {
            "distinct_complete_draws": len(seen),
            "duplicate_events": sum(len(names) - 1 for names in seen.values()),
            "duplicates": duplicates,
        }

    def record_scores(self, run_id: str, candidate_id: str, score: Mapping | None, reason=None):
        payload = dict(score) if score else {"candidate_id": candidate_id, "hits": None}
        payload["candidate_id"] = candidate_id
        if reason:
            payload["reason"] = reason
        self._journal.submit_as(self._identity, "scores", run_id, payload)

    def record_distinct_draws(
        self, run_id: str, draws: Mapping[str, tuple[tuple[int, ...], int]]
    ) -> dict:
        """Journal the once-only distinct-draw count over admitted candidates."""
        result = self.distinct_draws(draws)
        self._journal.submit_as(self._identity, "distinct_draws", run_id, result)
        return result
