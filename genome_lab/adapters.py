"""Discovery and Critical Verifier adapters (Document 03).

The controller drives the loop; the Discovery AI and the independent
Critical Verifier AI are behind adapter interfaces. Discovery receives only
the approved operation rules and authorized parent IDs, DNA, and structural
records - never player cards, historical draws, fitness, or novelty records.
The Critical Verifier uses a separate review context, inspects actual
records, and treats candidate source, comments, explanations, logs, and
outputs as untrusted evidence.

The deterministic stubs implement the documented duties with independent
recomputation so controlled fixtures and tests can exercise the whole loop
before any real AI participant is authorized.
"""

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from genome_lab.dna import canonical_bytes, sha256_hex


class DiscoveryError(RuntimeError):
    """Raised when a proposal request is malformed or unauthorized."""


class MutationProposal:
    __slots__ = ("linear_b",)

    def __init__(self, linear_b: int) -> None:
        self.linear_b = linear_b


class CrossoverProposal:
    __slots__ = ("pb_donor", "whites_donor")

    def __init__(self, pb_donor: str, whites_donor: str) -> None:
        self.pb_donor = pb_donor
        self.whites_donor = whites_donor


class ProposalRequest:
    """Restricted Discovery inputs: authorized parents and operation rules only."""

    __slots__ = ("branch", "operation_rules", "parent_ids", "parent_records", "run_id")

    def __init__(
        self,
        run_id: str,
        branch: str,
        parent_ids: tuple[str, ...],
        parent_records: Mapping[str, dict],
        operation_rules: Mapping,
    ) -> None:
        self.run_id = run_id
        self.branch = branch
        self.parent_ids = parent_ids
        self.parent_records = dict(parent_records)
        self.operation_rules = dict(operation_rules)


class DiscoveryAdapter(Protocol):
    def propose(self, request: ProposalRequest): ...


class StubDiscovery:
    """Deterministic Discovery stand-in for controlled fixtures.

    behavior: "ok" (default), "missing" (no proposal), "invalid" (contract-
    violating proposal), or "slow" (misses the interaction deadline).
    """

    def __init__(
        self,
        mutation_b: int = 36,
        crossover_orientation: tuple[str, str] = ("G1", "G2"),
        behavior: str = "ok",
        sleep_seconds: float = 0.0,
    ) -> None:
        self.mutation_b = mutation_b
        self.crossover_orientation = crossover_orientation
        self.behavior = behavior
        self.sleep_seconds = sleep_seconds

    def propose(self, request: ProposalRequest):
        if self.behavior == "slow":
            time.sleep(self.sleep_seconds)
            return None
        if self.behavior == "missing":
            return None
        if request.branch == "MUTATION-G2":
            if self.behavior == "invalid":
                return MutationProposal(linear_b=99)
            return MutationProposal(linear_b=self.mutation_b)
        if request.branch == "CROSSOVER-G1-G2":
            if self.behavior == "invalid":
                return CrossoverProposal(pb_donor="G1", whites_donor="G1")
            pb_donor, whites_donor = self.crossover_orientation
            return CrossoverProposal(pb_donor=pb_donor, whites_donor=whites_donor)
        raise DiscoveryError(f"unknown branch {request.branch!r}")


class CriticalVerifierAdapter(Protocol):
    def review_preflight(self, outcomes: Mapping[str, str], image: str, profile: str) -> str: ...

    def review_candidate(self, evidence: Mapping) -> str: ...

    def tally(self, fixture_path, ranking: list[int]) -> dict: ...

    def review_close(self, evidence: Mapping) -> str: ...


class StubCriticalVerifier:
    """Deterministic Critical Verifier: separate review context, independent
    recomputation, blind tally recorded before evaluator output."""

    def __init__(self, reject_candidate_ids: frozenset[str] = frozenset()) -> None:
        self.reject_candidate_ids = set(reject_candidate_ids)
        self.tally_records: list[dict] = []

    def review_preflight(self, outcomes: Mapping[str, str], image: str, profile: str) -> str:
        required = ("PF-ISO", "PF-IRC", "PF-JRN", "PF-GATE", "PF-DNA", "PF-OUTPUT")
        for check_id in required:
            if check_id not in outcomes:
                return "BLOCKED"
        if any(outcomes[cid] != "PASS" for cid in required):
            return "FAIL"
        if not image or not profile:
            return "BLOCKED"
        return "PASS"

    def review_candidate(self, evidence: Mapping) -> str:
        candidate_id = evidence.get("candidate_id")
        if candidate_id in self.reject_candidate_ids:
            return "REJECT"
        for key in ("cand_art", "cand_line"):
            result = evidence.get(key)
            if result is not None and result.get("outcome") != "PASS":
                return "REJECT"
        if evidence.get("cand_art") is None:
            return "BLOCKED"
        return "APPROVE"

    def tally(self, fixture_path, ranking: list[int]) -> dict:
        """Known-answer tally (independent implementation, Document 03).

        Uses only the authenticated fixture and the pinned literal ranking;
        records source and fixture fingerprints, sample dates, expected hit
        count, and denominator - kept as EVAL-01 evidence before reading any
        evaluator output.
        """
        fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        top = set(ranking[:3])
        hits = sum(1 for draw in fixture["draws"] if draw["powerball"] in top)
        record = {
            "fixture_digest": sha256_hex(
                canonical_bytes(
                    {"source_digest": fixture["source_digest"], "draws": fixture["draws"]}
                )
            ),
            "source_digest": fixture["source_digest"],
            "dates": [draw["date"] for draw in fixture["draws"]],
            "denominator": len(fixture["draws"]),
            "hits": hits,
            "recorded_before_evaluator_output": True,
        }
        self.tally_records.append(record)
        return record

    def review_close(self, evidence: Mapping) -> str:
        if not evidence.get("cleanup_confirmed"):
            return "BLOCKED"
        if not evidence.get("chain_verified"):
            return "FAIL"
        if not evidence.get("retained_bundle"):
            return "BLOCKED"
        return "PASS"
