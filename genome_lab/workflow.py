"""Controller workflow (Document 03): the driving loop, gates, and verdicts.

The controller opens the owner-authorized run after passing preflight, runs
the three seeds sequentially, runs the eligible reproductive branches (one
proposal request per branch, zero automatic retries), scores the verified
seeds through the evaluator, and stops and closes under IRC control. Every
launch passes the rule-based gate (single-use approval consumed before the
launch request) and the IRC's fixed limits. Journal events are the only
evidence source for player cards and the final report; the independent
reviewer retains the sealed bundle outside the controller's write access.

Restart semantics: the gate ledger durably records approval consumption, and
saved run state supports an explicit operator-initiated resume. Pending work
never auto-executes - a fresh execute_run against saved state fails closed.
"""

import datetime as dt
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from genome_lab import checks
from genome_lab.adapters import CrossoverProposal, MutationProposal, ProposalRequest
from genome_lab.authorization import (
    APPROVE,
    AuthorizationError,
    Gate,
    GateError,
    PreflightRecord,
)
from genome_lab.config import (
    AI_INTERACTION_SECONDS,
    MAX_CONTAINER_ATTEMPTS,
    RUN_SECONDS,
    RUNTIME_IMAGE,
    SANDBOX_PROFILE,
)
from genome_lab.evaluator import Evaluator, EvaluatorError
from genome_lab.genomes import (
    G1,
    G1_PINNED_PB_RANKING,
    G2,
    G3_GENERATOR_VERSION,
    MUTATION_B_CHOICES,
    SEEDS,
    crossover_offspring,
    g3_input_record,
    mutation_offspring,
)
from genome_lab.identity import IdentityRegistry
from genome_lab.irc import IRC, IRCError
from genome_lab.journal import Journal, derive_final_report, derive_player_cards
from genome_lab.sandbox import AttemptRequest, LocalExecutor
from genome_lab.snapshot import PublishedSnapshot, SnapshotPreparer


class WorkflowError(RuntimeError):
    """Raised when the workflow refuses to proceed (fail-closed)."""


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")


@dataclass
class CandidateOutcome:
    candidate_id: str
    slot: str
    status: str  # admitted / rejected / failed / blocked / timeout / stopped
    admitted: bool
    reason: str | None
    checks: list[str]
    output: dict | None

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "slot": self.slot,
            "status": self.status,
            "admitted": self.admitted,
            "reason": self.reason,
            "checks": list(self.checks),
            "output": self.output,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> CandidateOutcome:
        return cls(
            candidate_id=data["candidate_id"],
            slot=data["slot"],
            status=data["status"],
            admitted=bool(data["admitted"]),
            reason=data.get("reason"),
            checks=list(data.get("checks", [])),
            output=data.get("output"),
        )


@dataclass
class BranchOutcome:
    branch: str
    slot: str
    status: str  # completed / skipped / ended
    reason: str | None
    candidate: CandidateOutcome | None
    cause: dict | None = None

    def to_dict(self) -> dict:
        return {
            "branch": self.branch,
            "slot": self.slot,
            "status": self.status,
            "reason": self.reason,
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "cause": self.cause,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> BranchOutcome:
        candidate = data.get("candidate")
        return cls(
            branch=data["branch"],
            slot=data["slot"],
            status=data["status"],
            reason=data.get("reason"),
            candidate=CandidateOutcome.from_dict(candidate) if candidate else None,
            cause=data.get("cause"),
        )


@dataclass
class RunVerdict:
    outcome: str  # PASS / FAIL / INCOMPLETE
    reasons: dict  # {"fail": [...], "incomplete": [...]}
    candidates: dict  # candidate_id -> CandidateOutcome.to_dict()
    cards: list[dict]
    report: dict
    report_path: str


def _check_payload(result: checks.CheckResult) -> dict:
    return {
        "check_id": result.check_id,
        "outcome": result.outcome,
        "evidence": result.evidence,
    }


class ControllerWorkflow:
    """Driving controller: requests work, obeys the IRC, records everything."""

    def __init__(
        self,
        paths,
        registry: IdentityRegistry,
        journal: Journal,
        gate: Gate,
        executor: LocalExecutor,
        discovery,
        verifier,
        *,
        run_seconds: int = RUN_SECONDS,
        ai_interaction_seconds: float = AI_INTERACTION_SECONDS,
    ) -> None:
        self._paths = paths
        self._registry = registry
        self._journal = journal
        self._gate = gate
        self._executor = executor
        self._discovery = discovery
        self._verifier = verifier
        self._run_seconds = run_seconds
        self._ai_interaction_seconds = ai_interaction_seconds
        self._evaluator = Evaluator(journal, registry.get("evaluator"))
        self._ids = {
            name: registry.get(name)
            for name in (
                "controller",
                "validator",
                "critical_verifier",
                "snapshot_preparer",
                "gate",
                "irc",
                "evaluator",
            )
        }

    def _log(self, identity_name: str, kind: str, run_id: str, payload: Mapping) -> None:
        self._journal.submit_as(self._ids[identity_name], kind, run_id, payload)

    # ------------------------------------------------------------ step 1

    def run_preflight(self, owner_key: str) -> PreflightRecord:
        """Run the six controlled preflight fixtures and the independent review."""
        results = checks.preflight_suite(
            self._paths, self._journal, self._registry, self._executor, owner_key
        )
        outcomes = {result.check_id: result.outcome for result in results}
        decision = self._verifier.review_preflight(outcomes, RUNTIME_IMAGE, SANDBOX_PROFILE)
        record = PreflightRecord(
            reference=f"PF-{uuid.uuid4()}",
            image=RUNTIME_IMAGE,
            profile=SANDBOX_PROFILE,
            outcomes=outcomes,
            overall=decision,
            verified_by="critical_verifier",
            issued_at=_now_iso(),
        )
        self._log(
            "critical_verifier",
            "preflight_review",
            "pre-run",
            {
                "reference": record.reference,
                "check_ids": sorted(outcomes),
                "outcomes": outcomes,
                "decision": decision,
                "reviewer": "critical_verifier",
                "image": RUNTIME_IMAGE,
                "profile": SANDBOX_PROFILE,
            },
        )
        self._log(
            "controller",
            "preflight_accepted",
            "pre-run",
            {"reference": record.reference, "overall": decision},
        )
        return record

    # ------------------------------------------------------------ step 2

    def prepare_inputs(self, preflight_auth) -> PublishedSnapshot:
        """Trusted preparer: WAL-safe export, DATA-01 publication, pinned fixture."""
        preparer = SnapshotPreparer(self._paths, self._ids["snapshot_preparer"], preflight_auth)
        published = preparer.prepare()
        self._log("snapshot_preparer", "snapshot_publication", "pre-run", published.publication)
        return published

    # ------------------------------------------------------------ step 3

    def open_run(self, experiment_auth, preflight_record: PreflightRecord, g3_seed):
        run_id = str(experiment_auth.binding("run_id"))
        self._gate.verify_experiment_authorization(experiment_auth, run_id)
        if preflight_record.overall != "PASS":
            raise WorkflowError(
                f"preflight {preflight_record.reference} is not passing "
                f"({preflight_record.overall!r}); the run cannot open"
            )
        if preflight_record.image != experiment_auth.binding(
            "image"
        ) or preflight_record.profile != experiment_auth.binding("profile"):
            raise WorkflowError("preflight does not match the authorized image and profile")
        irc = IRC(
            self._journal,
            self._ids["irc"],
            run_id,
            run_seconds=self._run_seconds,
            ai_interaction_seconds=self._ai_interaction_seconds,
        )
        irc.open_run(preflight_record.reference)
        self._log(
            "controller",
            "run_authorized_opened",
            run_id,
            {
                "preflight_reference": preflight_record.reference,
                "authorization": experiment_auth.record_id,
                "g3_seed": g3_seed,
                "generator_version": G3_GENERATOR_VERSION,
                "image": RUNTIME_IMAGE,
                "profile": SANDBOX_PROFILE,
            },
        )
        return run_id, irc

    # -------------------------------------------------------- candidates

    def _write_input(self, run_id: str, candidate_id: str, record: Mapping) -> Path:
        directory = Path(self._paths.state_root) / "inputs" / run_id
        return checks.write_input_file(directory, candidate_id, record)

    def _seed_specs(self, g3_seed) -> list[dict]:
        g3_record = g3_input_record(g3_seed)
        return [
            {
                "slot": "SEED-G1",
                "candidate_id": "G1",
                "input_record": G1.record(),
                "contract_record": G1.record(),
                "taxonomy": f"{G1.pb.family}/{G1.white_balls.family}",
                "structural_fingerprint": G1.structural_fingerprint(),
                "full_dna_fingerprint": G1.full_fingerprint(),
                "parentage": "initial seed",
                "method": "seed (Document 01 contract)",
                "lineage": None,
            },
            {
                "slot": "SEED-G2",
                "candidate_id": "G2",
                "input_record": G2.record(),
                "contract_record": G2.record(),
                "taxonomy": f"{G2.pb.family}/{G2.white_balls.family}",
                "structural_fingerprint": G2.structural_fingerprint(),
                "full_dna_fingerprint": G2.full_fingerprint(),
                "parentage": "initial seed",
                "method": "seed (Document 01 contract)",
                "lineage": None,
            },
            {
                "slot": "SEED-G3",
                "candidate_id": "G3",
                "input_record": g3_record,
                "contract_record": g3_record,
                "taxonomy": "random-control",
                "structural_fingerprint": None,
                "full_dna_fingerprint": None,
                "parentage": "random control (excluded from reproduction and selection)",
                "method": f"fixed seed {g3_seed!r} ({G3_GENERATOR_VERSION})",
                "lineage": None,
            },
        ]

    def _run_candidate(
        self,
        irc: IRC,
        experiment_auth,
        preflight_record: PreflightRecord,
        run_id: str,
        *,
        slot: str,
        candidate_id: str,
        input_record: Mapping,
        contract_record: Mapping,
        taxonomy: str,
        structural_fingerprint,
        full_dna_fingerprint,
        parentage: str,
        method: str,
        lineage=None,
    ) -> CandidateOutcome:
        checks_applied: list[str] = []
        self._log(
            "controller",
            "candidate_registered",
            run_id,
            {
                "candidate_id": candidate_id,
                "slot": slot,
                "taxonomy": taxonomy,
                "structural_fingerprint": structural_fingerprint,
                "full_dna_fingerprint": full_dna_fingerprint,
                "parentage": parentage,
                "method": method,
            },
        )
        artifact_fp = self._executor.artifact_fingerprint()
        input_fp = checks.input_fingerprint(input_record)
        art = checks.cand_art(candidate_id, input_record, contract_record, artifact_fp)
        checks_applied.append(art.check_id)
        self._log(
            "validator",
            "check_cand_art",
            run_id,
            _check_payload(art) | {"candidate_id": candidate_id},
        )

        line = None
        if lineage is not None:
            lineage_kind, parents = lineage
            if lineage_kind == "mutation":
                line = checks.cand_line_mutation(candidate_id, input_record, parents[0])
            else:
                line = checks.cand_line_crossover(
                    candidate_id, input_record, parents[0], parents[1]
                )
            checks_applied.append(line.check_id)
            self._log(
                "validator",
                "check_cand_line",
                run_id,
                _check_payload(line) | {"candidate_id": candidate_id},
            )

        # Deterministic pre-launch evidence fails closed before any AI review.
        if art.outcome != "PASS" or (line is not None and line.outcome != "PASS"):
            reason = "pre-launch evidence failed (CAND-ART/CAND-LINE)"
            self._log(
                "controller",
                "candidate_rejected",
                run_id,
                {"candidate_id": candidate_id, "reason": reason},
            )
            return CandidateOutcome(
                candidate_id, slot, "rejected", False, reason, checks_applied, None
            )

        review_evidence = {
            "candidate_id": candidate_id,
            "slot": slot,
            "run_id": run_id,
            "artifact_fingerprint": artifact_fp,
            "input_fingerprint": input_fp,
            "image": RUNTIME_IMAGE,
            "profile": SANDBOX_PROFILE,
            "cand_art": _check_payload(art),
            "cand_line": _check_payload(line) if line is not None else None,
        }
        try:
            ok, decision = irc.ai_interaction(
                lambda: self._verifier.review_candidate(review_evidence),
                phase=f"review:{candidate_id}",
            )
        except IRCError as exc:
            self._log(
                "controller",
                "candidate_stopped",
                run_id,
                {"candidate_id": candidate_id, "reason": str(exc)},
            )
            return CandidateOutcome(
                candidate_id,
                slot,
                "stopped",
                False,
                f"launch review stopped: {exc}",
                checks_applied,
                None,
            )
        self._log(
            "critical_verifier",
            "cv_launch_review",
            run_id,
            {
                "candidate_id": candidate_id,
                "decision": decision if ok else None,
                "timed_out": not ok,
            },
        )
        if not ok:
            return CandidateOutcome(
                candidate_id,
                slot,
                "timeout",
                False,
                "launch review timed out",
                checks_applied,
                None,
            )
        if decision == "REJECT":
            reason = "independent launch review returned REJECT"
            self._log(
                "controller",
                "candidate_rejected",
                run_id,
                {"candidate_id": candidate_id, "reason": reason},
            )
            return CandidateOutcome(
                candidate_id, slot, "rejected", False, reason, checks_applied, None
            )
        if decision != APPROVE:
            reason = f"independent launch review returned {decision!r}"
            self._log(
                "controller",
                "candidate_rejected",
                run_id,
                {"candidate_id": candidate_id, "reason": reason},
            )
            return CandidateOutcome(
                candidate_id, slot, "blocked", False, reason, checks_applied, None
            )

        try:
            approval_id = self._gate.derive_launch_approval(
                auth=experiment_auth,
                run_id=run_id,
                slot=slot,
                attempt=1,
                artifact_fingerprint=artifact_fp,
                dna_fingerprint=input_fp,
                preflight=preflight_record,
                cv_decision=APPROVE,
            )
        except (GateError, AuthorizationError) as exc:
            reason = f"gate refused the launch approval: {exc}"
            self._log(
                "controller",
                "candidate_rejected",
                run_id,
                {"candidate_id": candidate_id, "reason": reason},
            )
            return CandidateOutcome(
                candidate_id, slot, "rejected", False, reason, checks_applied, None
            )
        self._log(
            "gate",
            "approval_issued",
            run_id,
            {
                "approval_id": approval_id,
                "slot": slot,
                "candidate_id": candidate_id,
                "artifact_fingerprint": artifact_fp,
                "input_fingerprint": input_fp,
                "preflight_reference": preflight_record.reference,
                "authorization": experiment_auth.record_id,
            },
        )
        self._gate.consume(approval_id)  # durably consumed BEFORE requesting launch
        self._log("gate", "approval_consumed", run_id, {"approval_id": approval_id, "slot": slot})

        try:
            input_path = self._write_input(run_id, candidate_id, input_record)
            result = irc.execute_attempt(
                self._executor,
                AttemptRequest(run_id=run_id, slot=slot, attempt=1, dna_path=input_path),
            )
        except IRCError as exc:
            self._log(
                "controller",
                "candidate_stopped",
                run_id,
                {"candidate_id": candidate_id, "reason": str(exc)},
            )
            return CandidateOutcome(
                candidate_id, slot, "stopped", False, f"launch stopped: {exc}", checks_applied, None
            )
        if not result.ok:
            reason = "container breach" if result.breach else f"engine exited {result.returncode}"
            self._log(
                "controller",
                "candidate_failed",
                run_id,
                {
                    "candidate_id": candidate_id,
                    "slot": slot,
                    "breach": result.breach,
                    "stopped_confirmed": result.stopped_confirmed,
                    "reason": reason,
                },
            )
            return CandidateOutcome(
                candidate_id, slot, "failed", False, reason, checks_applied, None
            )

        output = json.loads(result.stdout)
        run_output_check = checks.run_output(
            candidate_id,
            input_record,
            output,
            input_fp,
            result.artifact_fingerprint,
            artifact_fp,
        )
        checks_applied.append(run_output_check.check_id)
        self._log(
            "validator",
            "check_run_output",
            run_id,
            _check_payload(run_output_check) | {"candidate_id": candidate_id},
        )

        if run_output_check.outcome != "PASS":
            reason = "RUN-OUTPUT failed: " + "; ".join(run_output_check.evidence["errors"])
            self._log(
                "controller",
                "admission",
                run_id,
                {
                    "candidate_id": candidate_id,
                    "outcome": "rejected",
                    "checks": checks_applied,
                    "reason": reason,
                },
            )
            return CandidateOutcome(
                candidate_id, slot, "rejected", False, reason, checks_applied, None
            )

        admission_evidence = {
            "candidate_id": candidate_id,
            "slot": slot,
            "run_id": run_id,
            "cand_art": _check_payload(art),
            "cand_line": _check_payload(line) if line is not None else None,
            "run_output": _check_payload(run_output_check),
        }
        try:
            ok2, decision2 = irc.ai_interaction(
                lambda: self._verifier.review_candidate(admission_evidence),
                phase=f"admission:{candidate_id}",
            )
        except IRCError as exc:
            self._log(
                "controller",
                "candidate_stopped",
                run_id,
                {"candidate_id": candidate_id, "reason": str(exc)},
            )
            return CandidateOutcome(
                candidate_id,
                slot,
                "stopped",
                False,
                f"admission review stopped: {exc}",
                checks_applied,
                output,
            )
        self._log(
            "critical_verifier",
            "cv_admission_review",
            run_id,
            {
                "candidate_id": candidate_id,
                "decision": decision2 if ok2 else None,
                "timed_out": not ok2,
            },
        )
        if not ok2:
            admitted, status, reason = False, "timeout", "admission review timed out"
        elif decision2 == "REJECT":
            admitted, status, reason = False, "rejected", "admission review returned REJECT"
        elif decision2 == APPROVE:
            admitted, status, reason = True, "admitted", None
        else:
            admitted, status, reason = False, "blocked", f"admission review returned {decision2!r}"
        self._log(
            "controller",
            "admission",
            run_id,
            {
                "candidate_id": candidate_id,
                "outcome": status,
                "checks": checks_applied,
                "reason": reason,
            },
        )
        return CandidateOutcome(
            candidate_id,
            slot,
            status,
            admitted,
            reason,
            checks_applied,
            output if admitted else None,
        )

    # ---------------------------------------------------------- branches

    def _branch_rules(self, branch: str) -> dict:
        if branch == "MUTATION-G2":
            return {
                "operation": "mutation",
                "allowed_change": "shared linear coefficient b",
                "choices": list(MUTATION_B_CHOICES),
                "parents_required": ["G2"],
            }
        return {
            "operation": "crossover",
            "allowed": (
                "inherit the complete pb module from one verified parent and the "
                "complete white_balls module from the other"
            ),
            "donors": ["G1", "G2"],
            "parents_required": ["G1", "G2"],
        }

    def _run_branch(
        self,
        irc: IRC,
        experiment_auth,
        preflight_record: PreflightRecord,
        run_id: str,
        outcomes: Mapping[str, CandidateOutcome],
        branch: str,
    ) -> BranchOutcome:
        slot = branch
        rules = self._branch_rules(branch)
        unavailable = {
            parent_id: (outcomes[parent_id].status if parent_id in outcomes else "not run")
            for parent_id in rules["parents_required"]
            if not (outcomes.get(parent_id) and outcomes[parent_id].admitted)
        }
        if unavailable:
            reason = "required parent(s) not verified: " + ", ".join(
                f"{pid} ({status})" for pid, status in unavailable.items()
            )
            self._log(
                "controller",
                "branch_skipped",
                run_id,
                {"branch": branch, "slot": slot, "reason": reason, "unavailable": unavailable},
            )
            return BranchOutcome(
                branch, slot, "skipped", reason, None, {"unavailable": unavailable}
            )

        request = ProposalRequest(
            run_id,
            branch,
            tuple(rules["parents_required"]),
            {pid: SEEDS[pid].record() for pid in rules["parents_required"]},
            rules,
        )
        try:
            ok, proposal = irc.ai_interaction(
                lambda: self._discovery.propose(request), phase=f"proposal:{branch}"
            )
        except IRCError as exc:
            reason = f"proposal request stopped: {exc}"
            self._log(
                "controller",
                "branch_ended",
                run_id,
                {"branch": branch, "slot": slot, "reason": reason},
            )
            return BranchOutcome(branch, slot, "ended", reason, None, {"proposal": "stopped"})

        def _end(reason: str) -> BranchOutcome:
            self._log(
                "controller",
                "branch_ended",
                run_id,
                {"branch": branch, "slot": slot, "reason": reason},
            )
            return BranchOutcome(branch, slot, "ended", reason, None, {"proposal": "ended"})

        if not ok or proposal is None:
            return _end("proposal timed out" if not ok else "no proposal returned")

        if isinstance(proposal, MutationProposal) and branch == "MUTATION-G2":
            self._log(
                "controller",
                "proposal_received",
                run_id,
                {"branch": branch, "proposal": "MutationProposal", "linear_b": proposal.linear_b},
            )
            if proposal.linear_b not in MUTATION_B_CHOICES:
                return _end(
                    f"invalid proposal: linear b {proposal.linear_b} not in {MUTATION_B_CHOICES}"
                )
            offspring = mutation_offspring(proposal.linear_b)
            candidate_id = f"MUT-{proposal.linear_b}"
            lineage = ("mutation", (G2,))
            parentage = f"G2 (mutation: shared linear coefficient 37 -> {proposal.linear_b})"
            method = "mutation (shared linear coefficient change)"
        elif isinstance(proposal, CrossoverProposal) and branch == "CROSSOVER-G1-G2":
            self._log(
                "controller",
                "proposal_received",
                run_id,
                {
                    "branch": branch,
                    "proposal": "CrossoverProposal",
                    "pb_donor": proposal.pb_donor,
                    "whites_donor": proposal.whites_donor,
                },
            )
            if {proposal.pb_donor, proposal.whites_donor} != {"G1", "G2"}:
                return _end(
                    f"invalid proposal: donors {proposal.pb_donor!r}/{proposal.whites_donor!r} "
                    "must be the two distinct verified parents"
                )
            offspring = crossover_offspring(SEEDS[proposal.pb_donor], SEEDS[proposal.whites_donor])
            candidate_id = f"XOVER-{proposal.pb_donor}PB-{proposal.whites_donor}W"
            lineage = ("crossover", (SEEDS[proposal.pb_donor], SEEDS[proposal.whites_donor]))
            parentage = (
                f"{proposal.pb_donor} (pb module) + "
                f"{proposal.whites_donor} (white_balls module)"
            )
            method = "crossover (complete module inheritance)"
        else:
            return _end(f"invalid proposal type {type(proposal).__name__!r} for branch {branch!r}")

        record = offspring.record()
        outcome = self._run_candidate(
            irc,
            experiment_auth,
            preflight_record,
            run_id,
            slot=slot,
            candidate_id=candidate_id,
            input_record=record,
            contract_record=record,
            taxonomy=f"{offspring.pb.family}/{offspring.white_balls.family}",
            structural_fingerprint=offspring.structural_fingerprint(),
            full_dna_fingerprint=offspring.full_fingerprint(),
            parentage=parentage,
            method=method,
            lineage=lineage,
        )
        return BranchOutcome(branch, slot, "completed", outcome.reason, outcome, None)

    # ---------------------------------------------------------- scoring

    def _score_seeds(self, irc: IRC, run_id: str, published: PublishedSnapshot, outcomes):
        prior_eval01 = self._journal.events(run_id, kind="check_eval01")
        if prior_eval01:
            # Resume after a completed scoring phase: rebuild from the journal.
            evidence = prior_eval01[-1]["payload"].get("evidence", {})
            agreement = (
                checks.eval01_agreement(
                    evidence.get("cv_record", {}), evidence.get("evaluator_record", {})
                )
                if evidence.get("cv_record")
                else None
            )
            prior_data01 = self._journal.events(run_id, kind="data01_recheck")
            data01 = {"recheck": None, "error": None}
            if prior_data01:
                last = prior_data01[-1]["payload"]
                data01 = (
                    {"recheck": last, "error": None}
                    if "error" not in last
                    else {"recheck": None, "error": last["error"]}
                )
            return {"data01": data01, "agreement": agreement}

        data01 = {"recheck": None, "error": None}
        try:
            count, digest = self._evaluator.recheck_publication(
                published.export_path, published.publication
            )
            data01["recheck"] = {"count": count, "digest": digest}
            self._log(
                "evaluator",
                "data01_recheck",
                run_id,
                {
                    "count": count,
                    "digest": digest,
                    "publication_record": published.publication["record_id"],
                },
            )
        except EvaluatorError as exc:
            data01["error"] = str(exc)
            self._log("evaluator", "data01_recheck", run_id, {"error": str(exc)})

        cv_record = None
        cv_ok = False
        if data01["error"] is None:
            try:
                cv_ok, cv_record = irc.ai_interaction(
                    lambda: self._verifier.tally(
                        published.fixture_path, list(G1_PINNED_PB_RANKING)
                    ),
                    phase="cv_tally",
                )
            except IRCError:
                cv_ok = False
            if cv_ok and cv_record is not None:
                self._log("critical_verifier", "cv_tally", run_id, cv_record)
            else:
                self._log(
                    "critical_verifier",
                    "cv_tally",
                    run_id,
                    {"missing": True, "timed_out": not cv_ok},
                )
        else:
            self._log(
                "critical_verifier",
                "cv_tally",
                run_id,
                {"missing": True, "reason": "DATA-01 recheck failed; scoring blocked"},
            )

        if data01["error"] is not None:
            self._log(
                "evaluator",
                "eval_tally",
                run_id,
                {"skipped": True, "reason": f"DATA-01 recheck failed: {data01['error']}"},
            )
            agreement = None
            self._log(
                "validator",
                "check_eval01",
                run_id,
                {
                    "check_id": "EVAL-01",
                    "outcome": "FAIL",
                    "evidence": {"missing": "DATA-01 failed; EVAL-01 blocked"},
                },
            )
        else:
            eval_record = self._evaluator.tally_fixture(
                published.fixture_path, list(G1_PINNED_PB_RANKING)
            )
            self._log("evaluator", "eval_tally", run_id, eval_record)
            agreement = (
                checks.eval01_agreement(cv_record, eval_record) if cv_record is not None else None
            )
            payload = {"check_id": "EVAL-01", "outcome": agreement.outcome if agreement else "FAIL"}
            payload["evidence"] = (
                agreement.evidence if agreement else {"missing": "CV blind tally unavailable"}
            )
            self._log("validator", "check_eval01", run_id, payload)

        for candidate_id in ("G1", "G2", "G3"):
            outcome = outcomes.get(candidate_id)
            if data01["error"] is not None:
                self._evaluator.record_scores(
                    run_id, candidate_id, None, reason=f"DATA-01 recheck failed: {data01['error']}"
                )
            elif outcome is not None and outcome.admitted and outcome.output is not None:
                score = self._evaluator.score_seed(
                    published.export_path,
                    published.publication["window"],
                    outcome.output["pb_ranking"],
                )
                self._evaluator.record_scores(run_id, candidate_id, score)
            else:
                status = outcome.status if outcome is not None else "not run"
                self._evaluator.record_scores(
                    run_id, candidate_id, None, reason=f"seed not verified ({status})"
                )

        draws = {
            candidate_id: (tuple(outcome.output["draw"]["whites"]), outcome.output["draw"]["pb"])
            for candidate_id, outcome in outcomes.items()
            if outcome.admitted and outcome.output is not None
        }
        self._evaluator.record_distinct_draws(run_id, draws)
        return {"data01": data01, "agreement": agreement}

    # ------------------------------------------------------------- close

    def _close(self, irc: IRC, run_id: str, published: PublishedSnapshot) -> dict:
        removed = irc.close_run(self._executor, reason="run complete")
        attempts = self._journal.events(run_id, kind="attempt_result")
        consumed = self._journal.events(run_id, kind="approval_consumed")
        cleanup_confirmed = True  # the executor reported disposal of run resources
        containment_confirmed = all(
            bool(event["payload"].get("stopped_confirmed")) for event in attempts
        )
        attempts_reconciled = (
            len(attempts) == len(consumed) and len(attempts) <= MAX_CONTAINER_ATTEMPTS
        )
        close_check = checks.close01(
            self._paths,
            run_id,
            self._journal,
            self._ids["critical_verifier"],
            {
                "journal": Path(self._paths.journal_path),
                "development_export": published.export_path,
                "development_fixture": published.fixture_path,
                "publication": published.publication_path,
                "publication_signature": published.publication_signature_path,
            },
            cleanup_confirmed,
            containment_confirmed,
            attempts_reconciled,
        )
        cv_close = self._verifier.review_close(
            {
                "cleanup_confirmed": cleanup_confirmed,
                "chain_verified": close_check.evidence["chain_verified"],
                "retained_bundle": close_check.evidence["retained_dir"],
                "attempts_reconciled": attempts_reconciled,
                "containment_confirmed": containment_confirmed,
            }
        )
        self._log(
            "critical_verifier",
            "cv_close_review",
            run_id,
            {
                "decision": cv_close,
                "cleanup_confirmed": cleanup_confirmed,
                "containment_confirmed": containment_confirmed,
                "attempts_reconciled": attempts_reconciled,
                "retained_bundle": close_check.evidence["retained_dir"],
            },
        )
        self._log("controller", "close01", run_id, _check_payload(close_check))
        expired = self._gate.expire_open_approvals(run_id, "run closed")
        if expired:
            self._log(
                "gate", "approvals_expired", run_id, {"count": expired, "reason": "run closed"}
            )
        return {
            "removed": removed,
            "cleanup_confirmed": cleanup_confirmed,
            "containment_confirmed": containment_confirmed,
            "attempts_reconciled": attempts_reconciled,
            "close_check": close_check,
            "cv_close": cv_close,
        }

    # ----------------------------------------------------------- verdict

    def _assemble_verdict(self, run_id, g3_seed, outcomes, branches, scoring, close_info):
        fail: list[str] = []
        incomplete: list[str] = []
        for candidate_id in ("G1", "G2", "G3"):
            outcome = outcomes.get(candidate_id)
            if outcome is None:
                incomplete.append(f"seed {candidate_id} was not run")
            elif outcome.status in ("rejected", "failed"):
                fail.append(f"seed {candidate_id} {outcome.status}: {outcome.reason}")
            elif not outcome.admitted:
                incomplete.append(f"seed {candidate_id} {outcome.status}: {outcome.reason}")
        for branch in ("MUTATION-G2", "CROSSOVER-G1-G2"):
            branch_outcome = branches.get(branch)
            if branch_outcome is None:
                incomplete.append(f"branch {branch} was not run")
            elif branch_outcome.status == "skipped":
                parent_failed = any(
                    status in ("rejected", "failed")
                    for status in (branch_outcome.cause or {}).get("unavailable", {}).values()
                )
                if parent_failed:
                    fail.append(f"branch {branch} skipped: a required parent failed")
                else:
                    incomplete.append(f"branch {branch} skipped: {branch_outcome.reason}")
            elif branch_outcome.status == "ended":
                incomplete.append(f"branch {branch} ended before launch: {branch_outcome.reason}")
            elif branch_outcome.candidate is None:
                incomplete.append(f"branch {branch} has no candidate outcome")
            elif branch_outcome.candidate.status in ("rejected", "failed"):
                fail.append(
                    f"offspring {branch_outcome.candidate.candidate_id} "
                    f"{branch_outcome.candidate.status}: {branch_outcome.candidate.reason}"
                )
            elif not branch_outcome.candidate.admitted:
                incomplete.append(
                    f"offspring {branch_outcome.candidate.candidate_id} "
                    f"{branch_outcome.candidate.status}: {branch_outcome.candidate.reason}"
                )
        if scoring["data01"]["error"]:
            fail.append(f"DATA-01 recheck failed: {scoring['data01']['error']}")
        agreement = scoring["agreement"]
        if agreement is None:
            incomplete.append("EVAL-01: the independent blind tally is missing")
        elif agreement.outcome != "PASS":
            fail.append("EVAL-01: the evaluator does not match the independent tally")
        if not close_info["containment_confirmed"]:
            fail.append("container containment could not be confirmed")
        if not close_info["cleanup_confirmed"]:
            incomplete.append("run cleanup is unconfirmed")
        if not close_info["attempts_reconciled"]:
            incomplete.append("container attempts are not reconciled with approvals")
        close_check = close_info["close_check"]
        if close_check.evidence.get("chain_verified") is False:
            fail.append("the journal hash chain is broken")
        if close_check.outcome != "PASS":
            fail.append("CLOSE-01 failed")
        if close_info["cv_close"] != "PASS":
            incomplete.append(f"independent close review returned {close_info['cv_close']}")
        outcome = "FAIL" if fail else ("PASS" if not incomplete else "INCOMPLETE")

        self._log(
            "controller",
            "verdict",
            run_id,
            {
                "outcome": outcome,
                "fail_reasons": fail,
                "incomplete_reasons": incomplete,
                "g3_seed": g3_seed,
            },
        )
        events = self._journal.events(run_id)
        cards = derive_player_cards(events)
        journal_report = derive_final_report(events)
        report = {
            "run_id": run_id,
            "g3_seed": g3_seed,
            "outcome": outcome,
            "fail_reasons": fail,
            "incomplete_reasons": incomplete,
            "cards": cards,
            "journal_report": journal_report,
            "close01": close_check.evidence,
            "independent_close_review": close_info["cv_close"],
        }
        report_dir = Path(self._paths.state_root) / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"report_{run_id}.json"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        return RunVerdict(
            outcome,
            {"fail": fail, "incomplete": incomplete},
            {candidate_id: o.to_dict() for candidate_id, o in outcomes.items()},
            cards,
            report,
            str(report_path),
        )

    # ------------------------------------------------------------- run

    def execute_run(
        self,
        *,
        experiment_auth,
        preflight_record: PreflightRecord,
        published: PublishedSnapshot,
        g3_seed,
        resume: bool = False,
    ) -> RunVerdict:
        run_id = str(experiment_auth.binding("run_id"))
        saved = self._gate.load_run_state(run_id)
        if saved is not None and saved.get("phase") == "closed":
            raise WorkflowError(f"run {run_id} is already closed")
        if saved is not None and not resume:
            raise WorkflowError(
                f"run {run_id} has saved pending state; pending work cannot auto-execute "
                "- resume explicitly with resume=True"
            )
        if saved is None and resume:
            raise WorkflowError(f"run {run_id} has no saved state to resume")

        run_id, irc = self.open_run(experiment_auth, preflight_record, g3_seed)
        outcomes: dict[str, CandidateOutcome] = {}
        branches: dict[str, BranchOutcome] = {}
        if saved is not None:
            if saved.get("g3_seed") != g3_seed:
                raise WorkflowError("saved run state pins a different G3 seed")
            irc.set_remaining_seconds(float(saved["remaining_seconds"]))
            outcomes = {
                candidate_id: CandidateOutcome.from_dict(data)
                for candidate_id, data in saved.get("outcomes", {}).items()
            }
            branches = {
                branch: BranchOutcome.from_dict(data)
                for branch, data in saved.get("branches", {}).items()
            }

        def save_state(phase: str) -> None:
            self._gate.save_run_state(
                run_id,
                {
                    "phase": phase,
                    "g3_seed": g3_seed,
                    "preflight_reference": preflight_record.reference,
                    "remaining_seconds": irc.remaining_seconds(),
                    "outcomes": {candidate_id: o.to_dict() for candidate_id, o in outcomes.items()},
                    "branches": {branch: b.to_dict() for branch, b in branches.items()},
                },
            )

        for spec in self._seed_specs(g3_seed):
            if spec["candidate_id"] in outcomes:
                continue
            outcomes[spec["candidate_id"]] = self._run_candidate(
                irc, experiment_auth, preflight_record, run_id, **spec
            )
            save_state("seeds")

        for branch in ("MUTATION-G2", "CROSSOVER-G1-G2"):
            if branch in branches:
                continue
            branch_outcome = self._run_branch(
                irc, experiment_auth, preflight_record, run_id, outcomes, branch
            )
            branches[branch] = branch_outcome
            if branch_outcome.candidate is not None:
                # Offspring join the candidate map (state, distinct draws, verdict)
                outcomes[branch_outcome.candidate.candidate_id] = branch_outcome.candidate
            save_state("branches")

        scoring = self._score_seeds(irc, run_id, published, outcomes)
        save_state("scoring")
        close_info = self._close(irc, run_id, published)
        verdict = self._assemble_verdict(run_id, g3_seed, outcomes, branches, scoring, close_info)
        save_state("closed")
        return verdict
