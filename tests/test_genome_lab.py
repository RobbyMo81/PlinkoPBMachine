"""Deterministic tests for the genome_lab cold-start MVP (Documents 01-03).

Covers the whole loop: preflight fixtures, snapshot publication, the
owner-authorized run, seed/branch candidates through the gate and IRC,
EVAL-01/DATA-01 scoring, CLOSE-01 retention, the terminal verdicts, and
restart-resume semantics (single-use approvals, no auto-execution).
"""

import datetime as dt
import json
import random
import sqlite3
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from genome_lab import checks
from genome_lab.adapters import StubCriticalVerifier, StubDiscovery
from genome_lab.authorization import (
    AuthorizationError,
    Gate,
    GateError,
    load_owner_authorization,
    mint_owner_authorization,
)
from genome_lab.config import (
    AI_INTERACTION_SECONDS,
    EXPECTED_DEV_COUNT,
    LAUNCH_SLOTS,
    PREFLIGHT_CHECKS,
    RUN_SECONDS,
    RUNTIME_IMAGE,
    SANDBOX_PROFILE,
    WINDOW_END,
    WINDOW_START,
    build_lab,
)
from genome_lab.dna import DNARecord, Slot, verify_canonical_fixtures
from genome_lab.genomes import (
    G1,
    G2,
    crossover_offspring,
    expected_output_for_input,
    g3_outputs,
    pinned_ranking_matches,
    validate_crossover,
    validate_mutation,
)
from genome_lab.identity import COMPONENTS, GENOME, IdentityRegistry
from genome_lab.journal import Journal, JournalError
from genome_lab.sandbox import LocalExecutor
from genome_lab.snapshot import SnapshotError
from genome_lab.workflow import ControllerWorkflow, WorkflowError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PBMACHINE_ROOT = Path("C:/Users/RobMo/PBMachine")
OWNER_KEY = "test-owner-key"
G3_SEED = "g3-fixed-seed"


# --------------------------------------------------------------- helpers


def build_registry():
    registry = IdentityRegistry()
    for name in (*COMPONENTS, GENOME):
        registry.register(name)
    return registry


def schedule_dates(count):
    """In-window draw dates mimicking the verified real schedule: Wednesday
    and Saturday draws throughout, Monday draws added from August 2021."""
    dates = []
    day = dt.date.fromisoformat(WINDOW_START)
    final = dt.date.fromisoformat(WINDOW_END)
    first_monday = dt.date(2021, 8, 2)
    while len(dates) < count and day <= final:
        if day.weekday() in (0, 2, 5) and (day.weekday() != 0 or day >= first_monday):
            dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    assert len(dates) == count, f"window schedule yields only {len(dates)} of {count} dates"
    return dates


def build_synthetic_store(
    path, in_window_count=EXPECTED_DEV_COUNT, extra_dates=("2026-01-05", "2026-01-07")
):
    """A canonical store with the verified development-window row count."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE draws (draw_date TEXT, ball1 INTEGER, ball2 INTEGER, "
        "ball3 INTEGER, ball4 INTEGER, ball5 INTEGER, powerball INTEGER)"
    )
    rng = random.Random(20260101)
    rows = []
    for date in schedule_dates(in_window_count):
        whites = sorted(rng.sample(range(1, 70), 5))
        rows.append((date, *whites, rng.randint(1, 26)))
    for date in extra_dates:  # out-of-window rows exercise the export boundary
        whites = sorted(rng.sample(range(1, 70), 5))
        rows.append((date, *whites, rng.randint(1, 26)))
    conn.executemany("INSERT INTO draws VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def mint_auth(paths, stage, bindings, expires_hours=6):
    """Simulate the owner minting an authorization record out of band."""
    record = {
        "record_id": f"{stage}-{uuid.uuid4()}",
        "stage": stage,
        "issued_at": dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds"),
        "expires_at": (dt.datetime.now(dt.UTC) + dt.timedelta(hours=expires_hours)).isoformat(
            timespec="milliseconds"
        ),
        "bindings": bindings,
    }
    record_json, signature = mint_owner_authorization(record, OWNER_KEY)
    record_path = Path(paths.owner_dir) / f"{record['record_id']}.json"
    signature_path = record_path.with_suffix(".json.sig")
    record_path.write_text(record_json, encoding="utf-8")
    signature_path.write_text(signature, encoding="utf-8")
    return record_path, signature_path


def load_auth(record_path, signature_path):
    return load_owner_authorization(record_path, signature_path, OWNER_KEY)


def setup_lab(
    tmp_path,
    *,
    discovery=None,
    verifier=None,
    workflow_cls=ControllerWorkflow,
    workflow_kwargs=None,
    in_window_count=EXPECTED_DEV_COUNT,
    run_seconds=RUN_SECONDS,
    ai_seconds=AI_INTERACTION_SECONDS,
    stop_after=None,
    g3_seed=G3_SEED,
):
    paths = build_lab(tmp_path / "lab", PROJECT_ROOT, PBMACHINE_ROOT)
    registry = build_registry()
    journal = Journal(paths.journal_path, registry)
    gate = Gate(paths.ledger_path)
    executor = LocalExecutor(paths)
    store = tmp_path / "unified_storage.db"
    build_synthetic_store(store, in_window_count)
    preflight_record_path, preflight_sig_path = mint_auth(
        paths,
        "preflight",
        {
            "canonical_db_path": str(store),
            "development_window_start": WINDOW_START,
            "development_window_end": WINDOW_END,
            "image": RUNTIME_IMAGE,
            "profile": SANDBOX_PROFILE,
        },
    )
    workflow = workflow_cls(
        paths,
        registry,
        journal,
        gate,
        executor,
        discovery if discovery is not None else StubDiscovery(),
        verifier if verifier is not None else StubCriticalVerifier(),
        run_seconds=run_seconds,
        ai_interaction_seconds=ai_seconds,
        **(workflow_kwargs or {}),
    )
    preflight = workflow.run_preflight(OWNER_KEY)
    ns = SimpleNamespace(
        paths=paths,
        registry=registry,
        journal=journal,
        gate=gate,
        executor=executor,
        workflow=workflow,
        preflight=preflight,
        store=store,
        g3_seed=g3_seed,
        published=None,
        run_id=None,
        experiment_auth=None,
        preflight_record_path=preflight_record_path,
        preflight_sig_path=preflight_sig_path,
    )
    if stop_after == "preflight":
        return ns
    ns.published = workflow.prepare_inputs(load_auth(preflight_record_path, preflight_sig_path))
    ns.run_id = str(uuid.uuid4())
    experiment_record_path, experiment_sig_path = mint_auth(
        paths,
        "experiment",
        {
            "run_id": ns.run_id,
            "slots": list(LAUNCH_SLOTS),
            "image": RUNTIME_IMAGE,
            "profile": SANDBOX_PROFILE,
        },
    )
    ns.experiment_auth = load_auth(experiment_record_path, experiment_sig_path)
    return ns


def drive(ns, *, resume=False, workflow=None):
    wf = workflow or ns.workflow
    return wf.execute_run(
        experiment_auth=ns.experiment_auth,
        preflight_record=ns.preflight,
        published=ns.published,
        g3_seed=ns.g3_seed,
        resume=resume,
    )


# ----------------------------------------------------------- unit checks


def test_contracts_unit_checks():
    assert verify_canonical_fixtures() == []
    assert pinned_ranking_matches()
    assert g3_outputs("seed-a") == g3_outputs("seed-a")
    assert g3_outputs("seed-a") != g3_outputs("seed-b")

    good = expected_output_for_input(G1.record())
    assert (
        checks.run_output("T", G1.record(), good, good["input_fingerprint"], "fp", "fp").outcome
        == "PASS"
    )
    bad = dict(good)
    ranking = list(good["pb_ranking"])
    ranking[1] = ranking[0]  # duplicate-and-omission PB ranking
    bad["pb_ranking"] = ranking
    assert (
        checks.run_output("T", G1.record(), bad, good["input_fingerprint"], "fp", "fp").outcome
        == "FAIL"
    )
    assert (
        checks.run_output("T", G1.record(), good, "other-fp", "fp", "fp").outcome == "FAIL"
    )  # reported identity must match the approved candidate
    assert (
        checks.run_output("T", G1.record(), good, good["input_fingerprint"], "e", "a").outcome
        == "FAIL"
    )  # executed artifact must match the approved artifact

    cv = {"fixture_digest": "d", "denominator": 50, "hits": 6}
    assert checks.eval01_agreement(cv, cv).outcome == "PASS"
    assert (
        checks.eval01_agreement(cv, {"fixture_digest": "d", "denominator": 50, "hits": 7}).outcome
        == "FAIL"
    )

    child = DNARecord(
        pb=Slot("quadratic", {"a": -3, "b": 36, "c": 11}),
        white_balls=Slot("quadratic", {"a": -3, "b": 36, "c": 11}),
    )
    assert validate_mutation(child, G2)  # only the shared linear coefficient may change
    offspring = crossover_offspring(G1, G2)
    assert validate_crossover(offspring, G1, G2) == []
    assert validate_crossover(offspring, G2, G1) != []


def test_journal_is_append_only(tmp_path):
    registry = build_registry()
    journal = Journal(tmp_path / "journal.db", registry)
    controller = registry.get("controller")
    journal.submit_as(controller, "probe", "run", {"n": 1})
    conn = sqlite3.connect(tmp_path / "journal.db")
    with pytest.raises(sqlite3.Error):
        conn.execute("UPDATE events SET kind = 'tampered'")
        conn.commit()
    with pytest.raises(sqlite3.Error):
        conn.execute("DELETE FROM events")
        conn.commit()
    conn.close()
    genome = registry.get("genome")
    with pytest.raises(JournalError):
        journal.submit_as(genome, "probe", "run", {"n": 2})
    forged = json.dumps({"identity": "controller", "payload": {}, "mac": "bad"})
    with pytest.raises(JournalError):
        journal.submit(forged, "probe", "run", {})
    assert journal.verify_chain()


def test_snapshot_stops_on_duplicate_dates(tmp_path):
    paths = build_lab(tmp_path / "lab", PROJECT_ROOT, PBMACHINE_ROOT)
    registry = build_registry()
    journal = Journal(paths.journal_path, registry)
    gate = Gate(paths.ledger_path)
    executor = LocalExecutor(paths)
    store = tmp_path / "store.db"
    conn = sqlite3.connect(store)
    conn.execute(
        "CREATE TABLE draws (draw_date TEXT, ball1 INTEGER, ball2 INTEGER, "
        "ball3 INTEGER, ball4 INTEGER, ball5 INTEGER, powerball INTEGER)"
    )
    conn.executemany(
        "INSERT INTO draws VALUES (?, ?, ?, ?, ?, ?, ?)",
        [("2025-01-01", 1, 2, 3, 4, 5, 6), ("2025-01-01", 7, 8, 9, 10, 11, 12)],
    )
    conn.commit()
    conn.close()
    record_path, signature_path = mint_auth(
        paths,
        "preflight",
        {
            "canonical_db_path": str(store),
            "development_window_start": WINDOW_START,
            "development_window_end": WINDOW_END,
            "image": RUNTIME_IMAGE,
            "profile": SANDBOX_PROFILE,
        },
    )
    workflow = ControllerWorkflow(
        paths, registry, journal, gate, executor, StubDiscovery(), StubCriticalVerifier()
    )
    with pytest.raises(SnapshotError):
        workflow.prepare_inputs(load_auth(record_path, signature_path))


# ------------------------------------------------------------ full loop


def test_full_pass_run(tmp_path):
    ns = setup_lab(tmp_path)
    verdict = drive(ns)

    assert ns.preflight.overall == "PASS"
    assert all(ns.preflight.outcomes[cid] == "PASS" for cid in PREFLIGHT_CHECKS)
    assert ns.published.publication["count"] == EXPECTED_DEV_COUNT
    assert ns.published.publication["count_matches_expected"]

    assert verdict.outcome == "PASS", verdict.reasons
    for candidate_id in ("G1", "G2", "G3", "MUT-36", "XOVER-G1PB-G2W"):
        assert verdict.candidates[candidate_id]["admitted"], verdict.candidates[candidate_id]

    g1_out = verdict.candidates["G1"]["output"]
    g2_out = verdict.candidates["G2"]["output"]
    mut_out = verdict.candidates["MUT-36"]["output"]
    xover_out = verdict.candidates["XOVER-G1PB-G2W"]["output"]
    # Document 02: either mutation keeps G2's Top-3 set and draw
    assert set(mut_out["pb_ranking"][:3]) == {8, 9, 10}
    assert mut_out["draw"] == g2_out["draw"] == {"whites": [7, 8, 9, 10, 11], "pb": 9}
    # Crossover inherits complete modules: G1's PB ranking, G2's white draw
    assert xover_out["pb_ranking"] == g1_out["pb_ranking"]
    assert xover_out["draw"] == {"whites": [7, 8, 9, 10, 11], "pb": 10}

    assert ns.journal.verify_chain()
    attempts = ns.journal.events(ns.run_id, kind="attempt_result")
    assert len(attempts) == 5
    ai = ns.journal.events(ns.run_id, kind="ai_interaction")
    assert len(ai) == 13
    assert ns.journal.events(ns.run_id, kind="ai_timeout") == []

    eval01 = ns.journal.events(ns.run_id, kind="check_eval01")
    assert eval01[-1]["payload"]["outcome"] == "PASS"
    scores = ns.journal.events(ns.run_id, kind="scores")
    assert len(scores) == 3
    assert all(event["payload"]["denominator"] == EXPECTED_DEV_COUNT for event in scores)
    assert all(event["payload"]["hits"] is not None for event in scores)

    # G2 and its mutation intentionally share a draw; that is not a failure
    distinct = ns.journal.events(ns.run_id, kind="distinct_draws")
    assert distinct[-1]["payload"]["distinct_complete_draws"] == 4
    assert distinct[-1]["payload"]["duplicate_events"] == 1
    assert any(
        set(names) == {"G2", "MUT-36"} for names in distinct[-1]["payload"]["duplicates"].values()
    )

    # Single-use launch approvals, all durably consumed before launch
    for slot in LAUNCH_SLOTS:
        approval = ns.gate.approval_for_slot(ns.run_id, slot)
        assert approval is not None and approval["consumed_at"] is not None
    with pytest.raises(GateError):
        ns.gate.derive_launch_approval(
            auth=ns.experiment_auth,
            run_id=ns.run_id,
            slot="SEED-G1",
            attempt=1,
            artifact_fingerprint="any",
            dna_fingerprint="any",
            preflight=ns.preflight,
            cv_decision="APPROVE",
        )

    assert len(verdict.cards) == 5
    for card in verdict.cards:
        assert len(card) == 12
        assert card["record_version"] == 1
    close_retention = ns.journal.events(ns.run_id, kind="close01_retention")
    assert close_retention and close_retention[-1]["payload"]["cleanup_confirmed"]
    assert Path(verdict.report["close01"]["retained_dir"]).is_dir()
    assert Path(verdict.report_path).is_file()


def test_expected_count_mismatch_fails_scoring(tmp_path):
    ns = setup_lab(tmp_path, in_window_count=1296)
    verdict = drive(ns)
    assert ns.published.publication["count"] == 1296
    assert not ns.published.publication["count_matches_expected"]
    assert verdict.outcome == "FAIL"
    assert any("DATA-01" in reason for reason in verdict.reasons["fail"])
    scores = ns.journal.events(ns.run_id, kind="scores")
    assert len(scores) == 3
    assert all(event["payload"]["hits"] is None for event in scores)
    assert all("DATA-01" in event["payload"]["reason"] for event in scores)


def test_cv_reject_blocks_seed_and_descendants(tmp_path):
    ns = setup_lab(tmp_path, verifier=StubCriticalVerifier(reject_candidate_ids=frozenset({"G2"})))
    verdict = drive(ns)
    assert verdict.outcome == "FAIL"
    assert verdict.candidates["G2"]["status"] == "rejected"
    assert verdict.candidates["G1"]["admitted"]
    assert verdict.candidates["G3"]["admitted"]
    assert ns.gate.approval_for_slot(ns.run_id, "SEED-G2") is None  # never launched
    for branch in ("MUTATION-G2", "CROSSOVER-G1-G2"):
        assert ns.gate.approval_for_slot(ns.run_id, branch) is None  # slots stay unused
    g2_scores = [
        event
        for event in ns.journal.events(ns.run_id, kind="scores")
        if event["payload"]["candidate_id"] == "G2"
    ]
    assert g2_scores and g2_scores[0]["payload"]["hits"] is None
    assert any("G2 rejected" in reason for reason in verdict.reasons["fail"])


def test_invalid_proposals_end_branches(tmp_path):
    ns = setup_lab(tmp_path, discovery=StubDiscovery(behavior="invalid"))
    verdict = drive(ns)
    assert verdict.outcome == "INCOMPLETE"
    admitted = {cid for cid, oc in verdict.candidates.items() if oc["admitted"]}
    assert admitted == {"G1", "G2", "G3"}
    for branch in ("MUTATION-G2", "CROSSOVER-G1-G2"):
        assert ns.gate.approval_for_slot(ns.run_id, branch) is None
    ended = ns.journal.events(ns.run_id, kind="branch_ended")
    assert len(ended) == 2
    assert any("linear b 99" in event["payload"]["reason"] for event in ended)
    assert any("donors" in event["payload"]["reason"] for event in ended)


def test_slow_discovery_times_out(tmp_path):
    ns = setup_lab(
        tmp_path,
        discovery=StubDiscovery(behavior="slow", sleep_seconds=4),
        ai_seconds=0.5,
    )
    verdict = drive(ns)
    assert verdict.outcome == "INCOMPLETE"
    phases = {
        event["payload"]["phase"] for event in ns.journal.events(ns.run_id, kind="ai_timeout")
    }
    assert "proposal:MUTATION-G2" in phases
    assert "proposal:CROSSOVER-G1-G2" in phases
    # Independent authorized work continues safely after the timeouts
    assert verdict.candidates["G1"]["admitted"]
    assert verdict.candidates["G3"]["admitted"]
    scores = ns.journal.events(ns.run_id, kind="scores")
    assert len(scores) == 3
    assert any(event["payload"]["hits"] is not None for event in scores)


def test_run_deadline_stops_work(tmp_path):
    ns = setup_lab(tmp_path, run_seconds=0)
    verdict = drive(ns)
    assert verdict.outcome == "INCOMPLETE"
    assert all(outcome["status"] == "stopped" for outcome in verdict.candidates.values())
    assert ns.journal.events(ns.run_id, kind="approval_consumed") == []
    assert ns.journal.events(ns.run_id, kind="attempt_result") == []


def test_restart_resume_completes_without_auto_execute(tmp_path):
    class InterruptingWorkflow(ControllerWorkflow):
        def __init__(self, *args, stop_before, **kwargs):
            super().__init__(*args, **kwargs)
            self._stop_before = stop_before
            self._interrupted = False

        def _run_candidate(self, irc, experiment_auth, preflight_record, run_id, **kwargs):
            if kwargs.get("candidate_id") == self._stop_before and not self._interrupted:
                self._interrupted = True
                raise KeyboardInterrupt(f"simulated interrupt before {self._stop_before}")
            return super()._run_candidate(irc, experiment_auth, preflight_record, run_id, **kwargs)

    ns = setup_lab(
        tmp_path,
        discovery=StubDiscovery(mutation_b=38),
        workflow_cls=InterruptingWorkflow,
        workflow_kwargs={"stop_before": "G3"},
    )
    with pytest.raises(KeyboardInterrupt):
        drive(ns)
    # Pending work cannot auto-execute after the restart
    with pytest.raises(WorkflowError):
        drive(ns)
    # An explicit resume with a fresh controller completes the run
    resumed = ControllerWorkflow(
        ns.paths,
        ns.registry,
        ns.journal,
        ns.gate,
        ns.executor,
        StubDiscovery(mutation_b=38),
        StubCriticalVerifier(),
        run_seconds=RUN_SECONDS,
        ai_interaction_seconds=AI_INTERACTION_SECONDS,
    )
    verdict = drive(ns, resume=True, workflow=resumed)
    assert verdict.outcome == "PASS", verdict.reasons
    admitted = {cid for cid, oc in verdict.candidates.items() if oc["admitted"]}
    assert admitted == {"G1", "G2", "G3", "MUT-38", "XOVER-G1PB-G2W"}

    # Approvals stay single-use across the restart: exactly one per slot
    for slot in LAUNCH_SLOTS:
        approval = ns.gate.approval_for_slot(ns.run_id, slot)
        assert approval is not None and approval["consumed_at"] is not None
    assert len(ns.journal.events(ns.run_id, kind="run_opened")) == 2
    attempts = ns.journal.events(ns.run_id, kind="attempt_result")
    assert len(attempts) == 5
    assert len({event["payload"]["slot"] for event in attempts}) == 5
    assert ns.journal.verify_chain()
    # A closed run cannot be executed again
    with pytest.raises(WorkflowError):
        drive(ns, resume=True, workflow=resumed)


def test_preflight_review_failure_blocks_run(tmp_path):
    class FailingPreflightVerifier(StubCriticalVerifier):
        def review_preflight(self, outcomes, image, profile):
            return "FAIL"

    ns = setup_lab(tmp_path, verifier=FailingPreflightVerifier(), stop_after="preflight")
    assert ns.preflight.overall == "FAIL"
    assert all(ns.preflight.outcomes[cid] == "PASS" for cid in PREFLIGHT_CHECKS)
    # The rule-based gate refuses to derive any approval from a failing preflight
    experiment_record_path, experiment_sig_path = mint_auth(
        ns.paths,
        "experiment",
        {
            "run_id": "blocked-run",
            "slots": list(LAUNCH_SLOTS),
            "image": RUNTIME_IMAGE,
            "profile": SANDBOX_PROFILE,
        },
    )
    experiment_auth = load_auth(experiment_record_path, experiment_sig_path)
    with pytest.raises(GateError):
        ns.gate.derive_launch_approval(
            auth=experiment_auth,
            run_id="blocked-run",
            slot="SEED-G1",
            attempt=1,
            artifact_fingerprint="fp",
            dna_fingerprint="fp",
            preflight=ns.preflight,
            cv_decision="APPROVE",
        )
    with pytest.raises(WorkflowError):
        ns.workflow.open_run(experiment_auth, ns.preflight, G3_SEED)


def test_authorization_failures(tmp_path):
    ns = setup_lab(tmp_path)
    # Authorization naming only a subset of the five slots
    partial_path, partial_sig = mint_auth(
        ns.paths,
        "experiment",
        {
            "run_id": "partial-run",
            "slots": ["SEED-G1"],
            "image": RUNTIME_IMAGE,
            "profile": SANDBOX_PROFILE,
        },
    )
    with pytest.raises(AuthorizationError):
        ns.workflow.open_run(load_auth(partial_path, partial_sig), ns.preflight, G3_SEED)
    # Expired authorization
    expired_path, expired_sig = mint_auth(
        ns.paths,
        "experiment",
        {
            "run_id": "expired-run",
            "slots": list(LAUNCH_SLOTS),
            "image": RUNTIME_IMAGE,
            "profile": SANDBOX_PROFILE,
        },
        expires_hours=-1,
    )
    with pytest.raises(AuthorizationError):
        ns.workflow.open_run(load_auth(expired_path, expired_sig), ns.preflight, G3_SEED)
    # Tampered owner record
    tampered_sig = Path(ns.paths.owner_dir) / "tampered.sig"
    tampered_sig.write_text("0" * 64, encoding="utf-8")
    with pytest.raises(AuthorizationError):
        load_owner_authorization(ns.preflight_record_path, tampered_sig, OWNER_KEY)
