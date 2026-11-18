"""Deterministic tests for the enforcing runtime profile and entry points.

Covers the pinned docker-strict-v1 profile (fingerprint, command
construction, container naming), owner-side keygen and mint tooling, the
preflight entry point's fail-closed binding verification, and - when a
docker daemon answers - a real-container smoke and deadline-kill
integration through DockerSandbox. The full probe suite runs in the
operator preflight (journaled evidence), not here.
"""

import json
import re
from itertools import pairwise
from pathlib import Path

import pytest

from genome_lab.authorization import (
    AuthorizationError,
    load_owner_authorization,
    mint_owner_authorization,
)
from genome_lab.config import (
    EXPECTED_DEV_COUNT,
    PROFILE_PARAMETERS,
    RUNTIME_IMAGE,
    SANDBOX_PROFILE,
    WINDOW_END,
    WINDOW_START,
    build_lab,
)
from genome_lab.genomes import G1
from genome_lab.owner import keygen, mint_record, preflight_record_spec
from genome_lab.preflight import verify_preflight_bindings
from genome_lab.runtime import (
    DockerSandbox,
    build_run_command,
    container_name_for,
    docker_available,
    profile_fingerprint,
)
from genome_lab.sandbox import AttemptRequest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OWNER_KEY = "test-owner-key"


def _minted_preflight_auth(
    tmp_path: Path, canonical_name: str = "canonical.db", **binding_overrides
):
    """Simulate the owner minting a preflight authorization out of band."""
    canonical = tmp_path / canonical_name
    canonical.write_bytes(b"canonical-store-placeholder")
    record = preflight_record_spec(
        canonical_db_path=str(canonical),
        expires_hours=6,
        authorized_by="owner directive (test)",
    )
    bindings = dict(record["bindings"])
    bindings.update(binding_overrides)
    record["bindings"] = bindings
    record_json, signature = mint_owner_authorization(record, OWNER_KEY)
    record_path = tmp_path / f"{record['record_id']}.json"
    signature_path = record_path.with_suffix(".json.sig")
    record_path.write_text(record_json, encoding="utf-8")
    signature_path.write_text(signature, encoding="utf-8")
    return load_owner_authorization(record_path, signature_path, OWNER_KEY), record


# ------------------------------------------------------------- profile


def test_profile_fingerprint_is_deterministic_and_parameter_sensitive():
    baseline = profile_fingerprint()
    assert baseline == profile_fingerprint()
    assert re.fullmatch(r"[0-9a-f]{64}", baseline)
    drifted = dict(PROFILE_PARAMETERS)
    drifted["memory_mib"] = drifted["memory_mib"] + 1
    assert profile_fingerprint(drifted) != baseline


def test_build_run_command_pins_every_profile_parameter():
    command = build_run_command(
        image=RUNTIME_IMAGE,
        parameters=PROFILE_PARAMETERS,
        package_dir="C:/lab/plinko/genome_lab",
        input_path="C:/lab/state/inputs/run-1/g1.json",
        container_name="genome-run-1-seed-g1-1-ab",
        env_overrides={"GENOME_ENGINE_TEST_SLEEP": "6"},
    )
    assert command[:2] == ["docker", "run"]
    for flag in (
        "--network",
        "--memory",
        "--memory-swap",
        "--cpus",
        "--pids-limit",
        "--user",
        "--cap-drop",
        "--security-opt",
    ):
        assert flag in command
    pairs = dict(pairwise(command))
    assert pairs["--network"] == "none"
    assert pairs["--memory"] == "256m"
    assert pairs["--memory-swap"] == "256m"
    assert pairs["--cpus"] == "1"
    assert pairs["--pids-limit"] == "32"
    assert pairs["--user"] == "65534:65534"
    assert pairs["--cap-drop"] == "ALL"
    assert pairs["--security-opt"] == "no-new-privileges"
    assert "--read-only" in command
    assert "C:/lab/plinko/genome_lab:/lab/genome_lab:ro" in command
    # Path.parent stringifies with backslashes on Windows; docker accepts both forms.
    assert f"{Path('C:/lab/state/inputs/run-1')}:/inputs:ro" in command
    assert pairs["-w"] == "/lab"
    assert pairs["-e"] == "GENOME_ENGINE_TEST_SLEEP=6"
    assert command[-5:] == [
        RUNTIME_IMAGE,
        "python",
        "-m",
        "genome_lab.engine",
        "/inputs/g1.json",
    ]


def test_container_name_is_run_scoped_and_unique():
    request = AttemptRequest(run_id="IT-1234567890ab", slot="SEED-G1", attempt=1, dna_path="x")
    first = container_name_for(request)
    second = container_name_for(request)
    assert first.startswith("genome-IT-123456789-seed-g1-1-")
    assert first != second  # collision-free suffix


# ---------------------------------------------------------------- owner


def test_owner_keygen_writes_once_and_never_overwrites(tmp_path):
    key_file = tmp_path / "owner" / "owner.key"
    first = keygen(key_file)
    assert first["created"] is True
    content = key_file.read_text(encoding="utf-8")
    assert re.fullmatch(r"[0-9a-f]{64}", content.strip())
    second = keygen(key_file)
    assert second["created"] is False
    assert key_file.read_text(encoding="utf-8") == content


def test_preflight_record_spec_binds_the_snapshot_scope(tmp_path):
    canonical = tmp_path / "canonical.db"
    canonical.write_bytes(b"store")
    record = preflight_record_spec(
        canonical_db_path=str(canonical), authorized_by="owner directive (test)"
    )
    assert record["stage"] == "preflight"
    bindings = record["bindings"]
    assert bindings["image"] == RUNTIME_IMAGE
    assert bindings["profile"] == SANDBOX_PROFILE
    assert bindings["profile_fingerprint"] == profile_fingerprint()
    assert Path(bindings["canonical_db_path"]).is_absolute()
    assert bindings["development_window_start"] == WINDOW_START
    assert bindings["development_window_end"] == WINDOW_END
    assert bindings["expected_development_count"] == EXPECTED_DEV_COUNT
    assert record["authorized_by"] == "owner directive (test)"


def test_mint_record_writes_record_and_detached_signature(tmp_path):
    record = preflight_record_spec(
        canonical_db_path=str(tmp_path / "canonical.db"), authorized_by="owner directive (test)"
    )
    (tmp_path / "canonical.db").write_bytes(b"store")
    minted = mint_record(record, OWNER_KEY, tmp_path / "owner")
    auth = load_owner_authorization(minted["record_path"], minted["signature_path"], OWNER_KEY)
    assert auth.stage == "preflight"
    assert auth.binding("profile") == SANDBOX_PROFILE
    # A wrong owner key must fail closed.
    with pytest.raises(AuthorizationError):
        load_owner_authorization(minted["record_path"], minted["signature_path"], "other-key")


# ------------------------------------------------------ entry bindings


def test_verify_preflight_bindings_accepts_the_exact_record(tmp_path):
    auth, record = _minted_preflight_auth(tmp_path)
    verified = verify_preflight_bindings(auth)
    assert verified["image"] == RUNTIME_IMAGE
    assert verified["profile"] == SANDBOX_PROFILE
    assert verified["profile_fingerprint"] == record["bindings"]["profile_fingerprint"]
    assert Path(verified["canonical_db_path"]).is_absolute()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("image", "python:3.14.7-slim@sha256:" + "0" * 64),
        ("profile", "local-python-subprocess-v1"),
        ("profile_fingerprint", "0" * 64),
        ("development_window_start", "2015-10-08"),
        ("development_window_end", "2026-01-01"),
        ("canonical_db_path", "relative.db"),
        ("canonical_db_path", r"C:\Users\RobMo\missing-store.db"),
    ],
)
def test_verify_preflight_bindings_rejects_drift(tmp_path, field, value):
    auth, _ = _minted_preflight_auth(tmp_path, **{field: value})
    with pytest.raises(AuthorizationError):
        verify_preflight_bindings(auth)


def test_verify_preflight_bindings_rejects_the_experiment_stage(tmp_path):
    _auth, record = _minted_preflight_auth(tmp_path)
    drifted = dict(record)
    drifted["stage"] = "experiment"
    record_json, signature = mint_owner_authorization(drifted, OWNER_KEY)
    record_path = tmp_path / "experiment.json"
    signature_path = tmp_path / "experiment.sig"
    record_path.write_text(record_json, encoding="utf-8")
    signature_path.write_text(signature, encoding="utf-8")
    experiment_auth = load_owner_authorization(record_path, signature_path, OWNER_KEY)
    with pytest.raises(AuthorizationError):
        verify_preflight_bindings(experiment_auth)


# --------------------------------------------------- docker integration


requires_docker = pytest.mark.skipif(
    not docker_available(), reason="docker daemon not running: real-profile integration skipped"
)


@requires_docker
def test_docker_sandbox_smoke_and_deadline_stop(tmp_path):
    paths = build_lab(tmp_path / "lab", PROJECT_ROOT, tmp_path / "pbmachine")
    sandbox = DockerSandbox(paths)

    image_evidence = sandbox.verify_image()
    assert image_evidence["digest_present"], image_evidence

    input_dir = Path(paths.state_root) / "preflight_inputs"
    input_dir.mkdir(parents=True)
    input_path = input_dir / "g1.json"
    input_path.write_text(
        json.dumps(G1.record(), sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    smoke = sandbox.run(
        AttemptRequest(run_id="IT-SMOKE-0123456789", slot="SMOKE", attempt=1, dna_path=input_path)
    )
    assert smoke.ok, smoke
    output = json.loads(smoke.stdout)
    assert output["pb_ranking"][0] == 10
    assert output["draw"]["whites"] == [4, 10, 33, 39, 68]
    assert smoke.artifact_fingerprint == sandbox.artifact_fingerprint()

    slow = sandbox.run(
        AttemptRequest(
            run_id="IT-DEADLINE-01234567",
            slot="SLOW",
            attempt=1,
            dna_path=input_path,
            deadline_seconds=3,
            env_overrides={"GENOME_ENGINE_TEST_SLEEP": "12"},
        )
    )
    assert slow.breach is True
    assert slow.stopped_confirmed is True
    assert slow.stdout is None  # partial output is discarded
    assert slow.returncode not in (0, None)

    assert sandbox.cleanup_run("IT-SMOKE-0123456789")
    assert sandbox.cleanup_run("IT-DEADLINE-01234567")


@requires_docker
def test_profile_probes_demonstrate_enforcement(tmp_path):
    paths = build_lab(tmp_path / "lab", PROJECT_ROOT, tmp_path / "pbmachine")
    sandbox = DockerSandbox(paths)
    input_dir = Path(paths.state_root) / "preflight_inputs"
    input_dir.mkdir(parents=True)
    input_path = input_dir / "g1.json"
    input_path.write_text(
        json.dumps(G1.record(), sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    iso = sandbox.profile_iso_probes(input_dir)
    assert {name: probe["ok"] for name, probe in iso.items()} == {
        "image_digest_verified": True,
        "network_denied": True,
        "filesystem_read_only": True,
        "non_root_user": True,
    }, iso

    irc = sandbox.profile_irc_probes()
    assert {name: probe["ok"] for name, probe in irc.items()} == {
        "memory_limit_enforced": True,
        "process_limit_enforced": True,
        "cpu_cap_enforced": True,
    }, irc
