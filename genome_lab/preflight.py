"""Preflight entry point (Document 02, build step 1: distinct entry points).

Fail-closed operator entry: verifies the owner's preflight-stage
authorization pins the exact configured runtime image, sandbox profile,
and snapshot scope (absolute canonical database path plus the approved
development window), then runs the six preflight checks through the
enforcing runtime profile (real isolation and resource probes in real
containers) and publishes the DATA-01 development snapshot when the
preflight passes. The experiment stage requires its own separate owner
authorization and is never opened here.

Component identities are session-scoped: the journal verifies each
submission's token at submit time, and committed evidence stays
self-verifying through the append-only hash chain.
"""

import argparse
import json
from pathlib import Path

from genome_lab.adapters import StubCriticalVerifier, StubDiscovery
from genome_lab.authorization import (
    AuthorizationError,
    Gate,
    load_owner_authorization,
)
from genome_lab.config import (
    RUNTIME_IMAGE,
    SANDBOX_PROFILE,
    WINDOW_END,
    WINDOW_START,
    build_lab,
)
from genome_lab.identity import COMPONENTS, GENOME, IdentityRegistry
from genome_lab.journal import Journal
from genome_lab.runtime import DockerSandbox, profile_fingerprint
from genome_lab.sandbox import LocalExecutor
from genome_lab.workflow import ControllerWorkflow

DEFAULT_LAB_ROOT = Path(r"C:\Users\RobMo\GenomeLab")
DEFAULT_PBMACHINE_ROOT = Path(r"C:\Users\RobMo\PBMachine")
PLINKO_ROOT = Path(__file__).resolve().parents[1]


def verify_preflight_bindings(auth) -> dict:
    """Fail closed unless the owner record pins the exact configured profile
    and snapshot scope (Document 01, preflight row of the stage table)."""
    if auth.stage != "preflight":
        raise AuthorizationError(f"record stage {auth.stage!r} does not authorize preflight")
    if auth.binding("image") != RUNTIME_IMAGE:
        raise AuthorizationError("authorization does not pin the configured runtime image")
    if auth.binding("profile") != SANDBOX_PROFILE:
        raise AuthorizationError("authorization does not pin the configured sandbox profile")
    if auth.binding("profile_fingerprint") != profile_fingerprint():
        raise AuthorizationError("authorization does not pin the exact profile parameters")
    canonical = Path(str(auth.binding("canonical_db_path")))
    if not canonical.is_absolute():
        raise AuthorizationError("canonical database path must be absolute")
    if not canonical.is_file():
        raise AuthorizationError(f"canonical database {canonical} does not exist")
    if auth.binding("development_window_start") != WINDOW_START:
        raise AuthorizationError("authorization does not pin the approved window start")
    if auth.binding("development_window_end") != WINDOW_END:
        raise AuthorizationError("authorization does not pin the approved window end")
    return {
        "image": RUNTIME_IMAGE,
        "profile": SANDBOX_PROFILE,
        "profile_fingerprint": profile_fingerprint(),
        "canonical_db_path": str(canonical),
        "development_window": [WINDOW_START, WINDOW_END],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="genome_lab.preflight",
        description="Owner-authorized preflight (distinct entry point).",
    )
    parser.add_argument("--lab-root", type=Path, default=DEFAULT_LAB_ROOT)
    parser.add_argument("--pbmachine-root", type=Path, default=DEFAULT_PBMACHINE_ROOT)
    parser.add_argument("--owner-key-file", type=Path, required=True)
    parser.add_argument("--owner-record", type=Path, required=True)
    parser.add_argument("--owner-signature", type=Path, required=True)
    parser.add_argument("--executor", choices=("docker", "local"), default="docker")
    parser.add_argument(
        "--publish-snapshot",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="publish the DATA-01 development snapshot from the authorized scope",
    )
    args = parser.parse_args(argv)

    paths = build_lab(args.lab_root, PLINKO_ROOT, args.pbmachine_root)
    owner_key = args.owner_key_file.read_text(encoding="utf-8").strip()
    auth = load_owner_authorization(args.owner_record, args.owner_signature, owner_key)
    bindings = verify_preflight_bindings(auth)

    registry = IdentityRegistry()
    for name in (*COMPONENTS, GENOME):
        registry.register(name)
    journal = Journal(paths.journal_path, registry)
    gate = Gate(paths.ledger_path)
    gate.verify_stage_authorization(auth, "preflight")

    image_evidence = None
    if args.executor == "docker":
        sandbox = DockerSandbox(paths)
        image_evidence = sandbox.verify_image()
        if not image_evidence["digest_present"]:
            journal.close()
            gate.close()
            raise AuthorizationError(
                f"pinned runtime image is not present locally: {image_evidence}"
            )
        executor = sandbox
    else:
        executor = LocalExecutor(paths)

    workflow = ControllerWorkflow(
        paths, registry, journal, gate, executor, StubDiscovery(), StubCriticalVerifier()
    )
    preflight = workflow.run_preflight(owner_key)

    publication = None
    if preflight.overall == "PASS" and args.publish_snapshot:
        published = workflow.prepare_inputs(auth)
        publication = published.publication

    summary = {
        "reference": preflight.reference,
        "overall": preflight.overall,
        "outcomes": dict(preflight.outcomes),
        "image": preflight.image,
        "profile": preflight.profile,
        "profile_fingerprint": profile_fingerprint(),
        "owner_authorization": auth.record_id,
        "bindings": bindings,
        "image_evidence": image_evidence,
        "snapshot_publication": publication,
    }
    summary_path = Path(paths.evidence_root) / f"preflight_summary_{preflight.reference}.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    journal.close()
    gate.close()
    print(
        json.dumps(
            {
                "overall": preflight.overall,
                "outcomes": dict(preflight.outcomes),
                "summary_path": str(summary_path),
                "publication": publication["record_id"] if publication else None,
            },
            indent=2,
        )
    )
    return 0 if preflight.overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
