"""Deterministic check catalog (Document 02).

Twelve check IDs. The six preflight checks run as controlled fixtures without
real genome launches; candidate checks identify the exact run, attempt, and
artifact. Every check returns a CheckResult carrying tool-verified evidence.
"""

import datetime as dt
import json
import shutil
import sqlite3
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from genome_lab.authorization import (
    AuthorizationError,
    Gate,
    GateError,
    PreflightRecord,
    load_owner_authorization,
    mint_owner_authorization,
)
from genome_lab.config import LAUNCH_SLOTS, RUNTIME_IMAGE, SANDBOX_PROFILE
from genome_lab.dna import (
    canonical_bytes,
    dna_from_record,
    sha256_hex,
    verify_canonical_fixtures,
)
from genome_lab.genomes import (
    G1,
    G1_PINNED_PB_RANKING,
    expected_output_for_input,
    pinned_ranking_matches,
    validate_crossover,
    validate_mutation,
    validate_output,
)
from genome_lab.identity import AuthError, Identity, IdentityRegistry
from genome_lab.irc import IRC, IRCError
from genome_lab.journal import Journal, JournalError
from genome_lab.sandbox import AttemptRequest, LocalExecutor


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    outcome: str  # PASS / FAIL
    evidence: dict


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")


def _pass(check_id: str, evidence: dict) -> CheckResult:
    return CheckResult(check_id, "PASS", evidence)


def _fail(check_id: str, evidence: dict) -> CheckResult:
    return CheckResult(check_id, "FAIL", evidence)


def write_input_file(directory, name: str, record: Mapping) -> Path:
    """Write a candidate input record as canonical read-only input bytes."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    path.write_bytes(canonical_bytes(dict(record)))
    return path


def input_fingerprint(record: Mapping) -> str:
    return sha256_hex(canonical_bytes(dict(record)))


# ---------------------------------------------------------------- candidates


def cand_art(
    candidate_id: str,
    input_record: Mapping,
    expected_record: Mapping,
    artifact_fingerprint: str,
) -> CheckResult:
    """CAND-ART: fingerprint the executable artifact and validate the declared
    inputs and DNA record against the applicable seed or branch contract."""
    errors: list[str] = []
    if canonical_bytes(dict(input_record)) != canonical_bytes(dict(expected_record)):
        errors.append("input record does not match the applicable contract")
    if not artifact_fingerprint:
        errors.append("missing executable-artifact fingerprint")
    return CheckResult(
        "CAND-ART",
        "PASS" if not errors else "FAIL",
        {
            "candidate_id": candidate_id,
            "input_fingerprint": input_fingerprint(input_record),
            "artifact_fingerprint": artifact_fingerprint,
            "errors": errors,
        },
    )


def cand_line_mutation(candidate_id: str, offspring_record: Mapping, parent) -> CheckResult:
    """CAND-LINE (mutation): enforce the approved G2 change."""
    errors = validate_mutation(dna_from_record(offspring_record), parent)
    return CheckResult(
        "CAND-LINE",
        "PASS" if not errors else "FAIL",
        {"candidate_id": candidate_id, "lineage": "mutation", "errors": errors},
    )


def cand_line_crossover(
    candidate_id: str, offspring_record: Mapping, pb_parent, whites_parent
) -> CheckResult:
    """CAND-LINE (crossover): compare both inherited module fingerprints with
    the declared donor slots."""
    errors = validate_crossover(dna_from_record(offspring_record), pb_parent, whites_parent)
    return CheckResult(
        "CAND-LINE",
        "PASS" if not errors else "FAIL",
        {"candidate_id": candidate_id, "lineage": "crossover", "errors": errors},
    )


def run_output(
    candidate_id: str,
    input_record: Mapping,
    output: Mapping,
    approved_input_fingerprint: str,
    executed_artifact_fingerprint: str,
    approved_artifact_fingerprint: str,
) -> CheckResult:
    """RUN-OUTPUT: validate the complete ranking and draw, independently
    recompute both outputs, and confirm reported parentage and executable
    identity match the approved candidate."""
    errors = validate_output(output)
    expected = expected_output_for_input(input_record)
    if dict(output) != expected:
        errors.append("output does not match independent recomputation")
    if output.get("input_fingerprint") != approved_input_fingerprint:
        errors.append("reported candidate identity does not match the approved candidate")
    if executed_artifact_fingerprint != approved_artifact_fingerprint:
        errors.append("executed artifact does not match the approved artifact")
    return CheckResult(
        "RUN-OUTPUT",
        "PASS" if not errors else "FAIL",
        {
            "candidate_id": candidate_id,
            "approved_input_fingerprint": approved_input_fingerprint,
            "executed_artifact_fingerprint": executed_artifact_fingerprint,
            "errors": errors,
        },
    )


def eval01_agreement(cv_record: Mapping, evaluator_record: Mapping) -> CheckResult:
    """EVAL-01: the evaluator must exactly match the independently recorded hit
    count and denominator for G1's pinned permutation."""
    mismatches = [
        field
        for field in ("fixture_digest", "denominator", "hits")
        if cv_record.get(field) != evaluator_record.get(field)
    ]
    return CheckResult(
        "EVAL-01",
        "PASS" if not mismatches else "FAIL",
        {
            "cv_record": {k: cv_record.get(k) for k in ("fixture_digest", "denominator", "hits")},
            "evaluator_record": {
                k: evaluator_record.get(k) for k in ("fixture_digest", "denominator", "hits")
            },
            "mismatches": mismatches,
        },
    )


def close01(
    paths,
    run_id: str,
    journal: Journal,
    verifier_identity: Identity,
    artifacts: Mapping[str, Path],
    cleanup_confirmed: bool,
    containment_confirmed: bool,
    attempts_reconciled: bool,
) -> CheckResult:
    """CLOSE-01: reconcile terminal container state, cleanup, journal, and
    artifact fingerprints; record protected independent retention."""
    chain_verified = journal.verify_chain()
    retained_dir = Path(paths.evidence_root) / "retained" / run_id
    retained_dir.mkdir(parents=True, exist_ok=True)
    fingerprints: dict[str, str] = {}
    for name, path in artifacts.items():
        target = retained_dir / Path(path).name
        shutil.copyfile(path, target)
        fingerprints[name] = sha256_hex(Path(path).read_bytes())
    journal.submit_as(
        verifier_identity,
        "close01_retention",
        run_id,
        {
            "retained_dir": str(retained_dir),
            "fingerprints": fingerprints,
            "cleanup_confirmed": cleanup_confirmed,
            "containment_confirmed": containment_confirmed,
            "attempts_reconciled": attempts_reconciled,
            "chain_verified": chain_verified,
        },
    )
    ok = chain_verified and cleanup_confirmed and containment_confirmed and attempts_reconciled
    return CheckResult(
        "CLOSE-01",
        "PASS" if ok else "FAIL",
        {
            "retained_dir": str(retained_dir),
            "fingerprints": fingerprints,
            "cleanup_confirmed": cleanup_confirmed,
            "containment_confirmed": containment_confirmed,
            "attempts_reconciled": attempts_reconciled,
            "chain_verified": chain_verified,
        },
    )


# --------------------------------------------------------------- preflight


def _pf_iso(paths, journal, registry, executor: LocalExecutor) -> CheckResult:
    stable = executor.artifact_fingerprint() == executor.artifact_fingerprint()
    g1_path = write_input_file(Path(paths.state_root) / "preflight_inputs", "g1", G1.record())
    smoke = executor.run(AttemptRequest(run_id="PF-ISO", slot="SMOKE", attempt=0, dna_path=g1_path))
    output = None
    if smoke.stdout:
        try:
            output = json.loads(smoke.stdout)
        except json.JSONDecodeError:
            output = None
    valid = bool(output) and validate_output(output) == []
    evidence = {
        "runtime_image": RUNTIME_IMAGE,
        "sandbox_profile": SANDBOX_PROFILE,
        "artifact_fingerprint_stable": stable,
        "smoke_ok": smoke.ok,
        "smoke_output_valid": valid,
        "smoke_returncode": smoke.returncode,
    }
    return (
        _pass("PF-ISO", evidence) if (stable and smoke.ok and valid) else _fail("PF-ISO", evidence)
    )


def _pf_irc(paths, journal, registry, executor: LocalExecutor) -> CheckResult:
    g1_path = write_input_file(Path(paths.state_root) / "preflight_inputs", "g1", G1.record())
    irc = IRC(
        journal, registry.get("irc"), "PF-IRC-FIXTURE", run_seconds=60, ai_interaction_seconds=0.5
    )
    irc.open_run("PF-IRC-CTRL")
    fast = irc.execute_attempt(
        executor,
        AttemptRequest("PF-IRC-FIXTURE", "FAST", 1, g1_path, deadline_seconds=20),
    )
    spam = irc.execute_attempt(
        executor,
        AttemptRequest(
            "PF-IRC-FIXTURE",
            "SPAM",
            1,
            g1_path,
            env_overrides={"GENOME_ENGINE_TEST_SPAM": str(64 * 1024 + 4096)},
        ),
    )
    slow = irc.execute_attempt(
        executor,
        AttemptRequest(
            "PF-IRC-FIXTURE",
            "SLOW",
            1,
            g1_path,
            deadline_seconds=2,
            env_overrides={"GENOME_ENGINE_TEST_SLEEP": "6"},
        ),
    )

    def late_response():
        time.sleep(3)
        return "late"

    ai_ok, _ = irc.ai_interaction(late_response, phase="pf-irc-ai-deadline")
    irc.close_run(reason="fixture complete")

    cutoff = IRC(journal, registry.get("irc"), "PF-IRC-CUTOFF", run_seconds=0)
    cutoff.open_run("PF-IRC-CTRL")
    cutoff_raised = False
    try:
        cutoff.guard_dispatch("pf-irc-cutoff-probe")
    except IRCError:
        cutoff_raised = True
    cutoff.close_run(reason="cutoff fixture")

    evidence = {
        "fast_attempt_ok": fast.ok,
        "output_cap_breach_detected": spam.breach,
        "output_cap_partial_discarded": spam.stdout is None,
        "output_cap_exit_confirmed": spam.stopped_confirmed,
        "deadline_breach_detected": slow.breach,
        "deadline_exit_confirmed": slow.stopped_confirmed,
        "deadline_measured_seconds": round(slow.duration_seconds, 3),
        "ai_deadline_enforced": ai_ok is False,
        "run_dispatch_cutoff_raised": cutoff_raised,
        "profile": SANDBOX_PROFILE,
    }
    ok = (
        fast.ok
        and spam.breach
        and spam.stdout is None
        and spam.stopped_confirmed
        and slow.breach
        and slow.stopped_confirmed
        and not ai_ok
        and cutoff_raised
    )
    return _pass("PF-IRC", evidence) if ok else _fail("PF-IRC", evidence)


def _pf_jrn(paths, journal: Journal, registry: IdentityRegistry) -> CheckResult:
    controller = registry.get("controller")
    probes: dict[str, bool] = {}

    journal.submit_as(controller, "pf_jrn_probe", "pre-run", {"probe": "allowed"})
    probes["authorized_append_accepted"] = True

    try:
        genome = registry.get("genome")
    except AuthError:
        genome = None
    probes["genome_denied"] = genome is None
    if genome is not None:
        try:
            journal.submit_as(genome, "pf_jrn_probe", "pre-run", {"probe": "genome"})
            probes["genome_denied"] = False
        except JournalError:
            probes["genome_denied"] = True

    forged = json.dumps(
        {"identity": "controller", "payload": {"probe": "forged"}, "mac": "deadbeef"}
    )
    try:
        journal.submit(forged, "pf_jrn_probe", "pre-run", {"probe": "forged"})
        probes["forged_token_rejected"] = False
    except JournalError:
        probes["forged_token_rejected"] = True

    try:
        journal.submit_as(genome, "pf_jrn_probe", "pre-run", {"probe": "genome"})
        probes["genome_denied"] = False
    except JournalError:
        probes["genome_denied"] = True

    replay_token = controller.issue_token(
        {"kind": "pf_jrn_probe", "run_id": "pre-run", "payload": {"probe": "other"}}
    )
    try:
        journal.submit(replay_token, "pf_jrn_probe", "pre-run", {"probe": "different"})
        probes["replayed_token_rejected"] = False
    except JournalError:
        probes["replayed_token_rejected"] = True

    conn = sqlite3.connect(journal._path)  # controlled direct-access probe
    try:
        update_aborted = False
        try:
            conn.execute("UPDATE events SET kind = 'tampered'")
            conn.commit()
        except sqlite3.Error:
            update_aborted = True
        delete_aborted = False
        try:
            conn.execute("DELETE FROM events")
            conn.commit()
        except sqlite3.Error:
            delete_aborted = True
    finally:
        conn.close()
    probes["direct_update_aborted"] = update_aborted
    probes["direct_delete_aborted"] = delete_aborted
    probes["no_mutation_api"] = all(
        not hasattr(journal, name) for name in ("update_event", "delete_event", "truncate")
    )
    probes["chain_verified"] = journal.verify_chain()
    probes["journal_under_evidence_root"] = str(Path(journal._path)).startswith(
        str(Path(paths.evidence_root))
    )

    ok = all(probes.values())
    return _pass("PF-JRN", probes) if ok else _fail("PF-JRN", probes)


def _pf_gate(paths, journal, registry, owner_key: str) -> CheckResult:
    probes: dict[str, bool] = {}
    ledger = Path(paths.state_root) / "preflight_gate_ledger.db"
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(ledger) + suffix)
        if candidate.exists():
            candidate.unlink()
    gate = Gate(ledger)

    def mint(stage, run_id, slots, image, profile, expires_in_seconds=3600):
        record = {
            "record_id": f"pf-gate-{uuid.uuid4()}",
            "stage": stage,
            "issued_at": _now_iso(),
            "expires_at": (
                dt.datetime.now(dt.UTC) + dt.timedelta(seconds=expires_in_seconds)
            ).isoformat(timespec="milliseconds"),
            "bindings": {
                "run_id": run_id,
                "slots": list(slots),
                "image": image,
                "profile": profile,
            },
        }
        record_path = Path(paths.owner_dir) / f"{record['record_id']}.json"
        sig_path = record_path.with_suffix(".json.sig")
        record_json, signature = mint_owner_authorization(record, owner_key)
        record_path.write_text(record_json, encoding="utf-8")
        sig_path.write_text(signature, encoding="utf-8")
        return record_path, sig_path

    rec_path, sig_path = mint(
        "experiment", "pf-gate-run", LAUNCH_SLOTS, RUNTIME_IMAGE, SANDBOX_PROFILE
    )
    auth = load_owner_authorization(rec_path, sig_path, owner_key)
    probes["valid_owner_record_accepted"] = auth.stage == "experiment"

    tampered_sig = Path(paths.owner_dir) / "tampered.sig"
    tampered_sig.write_text("0" * 64, encoding="utf-8")
    try:
        load_owner_authorization(rec_path, tampered_sig, owner_key)
        probes["untrusted_record_rejected"] = False
    except AuthorizationError:
        probes["untrusted_record_rejected"] = True

    pf_pass = PreflightRecord(
        reference="PF-GATE-CTRL",
        image=RUNTIME_IMAGE,
        profile=SANDBOX_PROFILE,
        outcomes={
            check: "PASS"
            for check in ("PF-ISO", "PF-IRC", "PF-JRN", "PF-GATE", "PF-DNA", "PF-OUTPUT")
        },
        overall="PASS",
        verified_by="critical_verifier",
        issued_at=_now_iso(),
    )
    approval_ids = {}
    for slot in LAUNCH_SLOTS:
        approval_ids[slot] = gate.derive_launch_approval(
            auth=auth,
            run_id="pf-gate-run",
            slot=slot,
            attempt=1,
            artifact_fingerprint="artifact-fp",
            dna_fingerprint="input-fp",
            preflight=pf_pass,
            cv_decision="APPROVE",
        )
    probes["delegated_authority_once_per_slot"] = True

    try:
        gate.derive_launch_approval(
            auth=auth,
            run_id="pf-gate-run",
            slot="SEED-G1",
            attempt=1,
            artifact_fingerprint="artifact-fp",
            dna_fingerprint="input-fp",
            preflight=pf_pass,
            cv_decision="APPROVE",
        )
        probes["reassigned_slot_blocked"] = False
    except GateError:
        probes["reassigned_slot_blocked"] = True

    try:
        gate.derive_launch_approval(
            auth=auth,
            run_id="pf-gate-run",
            slot="SEED-G9",
            attempt=1,
            artifact_fingerprint="artifact-fp",
            dna_fingerprint="input-fp",
            preflight=pf_pass,
            cv_decision="APPROVE",
        )
        probes["unknown_slot_blocked"] = False
    except GateError:
        probes["unknown_slot_blocked"] = True

    pf_fail = PreflightRecord(
        reference="PF-GATE-CTRL-FAIL",
        image=RUNTIME_IMAGE,
        profile=SANDBOX_PROFILE,
        outcomes={},
        overall="FAIL",
        verified_by="critical_verifier",
        issued_at=_now_iso(),
    )
    try:
        gate.derive_launch_approval(
            auth=auth,
            run_id="pf-gate-run",
            slot="SEED-G1",
            attempt=1,
            artifact_fingerprint="artifact-fp",
            dna_fingerprint="input-fp",
            preflight=pf_fail,
            cv_decision="APPROVE",
        )
        probes["stale_preflight_blocked"] = False
    except GateError:
        probes["stale_preflight_blocked"] = True

    pf_mismatch = PreflightRecord(
        reference="PF-GATE-CTRL-MISMATCH",
        image=RUNTIME_IMAGE,
        profile="other-profile-v9",
        outcomes={},
        overall="PASS",
        verified_by="critical_verifier",
        issued_at=_now_iso(),
    )
    try:
        gate.derive_launch_approval(
            auth=auth,
            run_id="pf-gate-run",
            slot="SEED-G2",
            attempt=1,
            artifact_fingerprint="artifact-fp",
            dna_fingerprint="input-fp",
            preflight=pf_mismatch,
            cv_decision="APPROVE",
        )
        probes["mismatched_profile_blocked"] = False
    except GateError:
        probes["mismatched_profile_blocked"] = True

    try:
        gate.derive_launch_approval(
            auth=auth,
            run_id="pf-gate-run",
            slot="SEED-G2",
            attempt=1,
            artifact_fingerprint="artifact-fp",
            dna_fingerprint="input-fp",
            preflight=pf_pass,
            cv_decision="REJECT",
        )
        probes["rejected_review_blocked"] = False
    except GateError:
        probes["rejected_review_blocked"] = True

    gate.consume(approval_ids["SEED-G1"])
    probes["approval_consumed"] = True
    try:
        gate.consume(approval_ids["SEED-G1"])
        probes["consumed_approval_not_replayable"] = False
    except GateError:
        probes["consumed_approval_not_replayable"] = True

    restarted = Gate(ledger)  # restart: consumption must survive
    row = restarted.approval_for_slot("pf-gate-run", "SEED-G1")
    probes["consumption_survives_restart"] = bool(row and row["consumed_at"])
    try:
        restarted.derive_launch_approval(
            auth=auth,
            run_id="pf-gate-run",
            slot="SEED-G1",
            attempt=1,
            artifact_fingerprint="artifact-fp",
            dna_fingerprint="input-fp",
            preflight=pf_pass,
            cv_decision="APPROVE",
        )
        probes["post_restart_reissue_blocked"] = False
    except GateError:
        probes["post_restart_reissue_blocked"] = True

    expired_path, expired_sig = mint(
        "experiment",
        "pf-gate-run-2",
        LAUNCH_SLOTS,
        RUNTIME_IMAGE,
        SANDBOX_PROFILE,
        expires_in_seconds=-3600,
    )
    expired_auth = load_owner_authorization(expired_path, expired_sig, owner_key)
    try:
        restarted.verify_experiment_authorization(expired_auth, "pf-gate-run-2")
        probes["expired_authorization_blocked"] = False
    except AuthorizationError:
        probes["expired_authorization_blocked"] = True

    ok = all(probes.values())
    return _pass("PF-GATE", probes) if ok else _fail("PF-GATE", probes)


def _pf_dna(paths, journal, registry) -> CheckResult:
    from genome_lab.dna import CANONICAL_FIXTURES

    failures = verify_canonical_fixtures()
    pinned = pinned_ranking_matches()
    idempotent = all(
        canonical_bytes(json.loads(content)) == content.encode("utf-8")
        for content, _ in CANONICAL_FIXTURES.values()
    )
    evidence = {
        "fixture_failures": failures,
        "pinned_eval01_ranking_matches": pinned,
        "canonical_encoding_idempotent": idempotent,
        "fixture_count": len(CANONICAL_FIXTURES),
    }
    ok = not failures and pinned and idempotent
    return _pass("PF-DNA", evidence) if ok else _fail("PF-DNA", evidence)


def _pf_output(paths, journal, registry, executor: LocalExecutor) -> CheckResult:
    good = expected_output_for_input(G1.record())
    bad_ranking = list(G1_PINNED_PB_RANKING)
    bad_ranking[15] = bad_ranking[0]  # duplicate PB 10, PB 16 omitted
    bad_output = {
        "pb_ranking": bad_ranking,
        "draw": good["draw"],
        "input_fingerprint": good["input_fingerprint"],
    }
    artifact = executor.artifact_fingerprint()
    good_check = run_output(
        "PF-OUTPUT-GOOD", G1.record(), good, good["input_fingerprint"], artifact, artifact
    )
    bad_check = run_output(
        "PF-OUTPUT-BAD", G1.record(), bad_output, good["input_fingerprint"], artifact, artifact
    )
    evidence = {
        "valid_output_accepted": good_check.outcome == "PASS",
        "duplicate_and_omission_ranking_rejected": bad_check.outcome == "FAIL",
        "bad_ranking_errors": bad_check.evidence["errors"],
    }
    ok = good_check.outcome == "PASS" and bad_check.outcome == "FAIL"
    return _pass("PF-OUTPUT", evidence) if ok else _fail("PF-OUTPUT", evidence)


def preflight_suite(
    paths,
    journal: Journal,
    registry: IdentityRegistry,
    executor: LocalExecutor,
    owner_key: str,
) -> list[CheckResult]:
    """The six preflight checks as controlled fixtures (Document 03, step 1)."""
    results = [
        _pf_iso(paths, journal, registry, executor),
        _pf_irc(paths, journal, registry, executor),
        _pf_jrn(paths, journal, registry),
        _pf_gate(paths, journal, registry, owner_key),
        _pf_dna(paths, journal, registry),
        _pf_output(paths, journal, registry, executor),
    ]
    validator = registry.get("validator")
    for result in results:
        journal.submit_as(
            validator,
            "preflight_check",
            "pre-run",
            {
                "check_id": result.check_id,
                "outcome": result.outcome,
                "evidence": result.evidence,
            },
        )
    return results
