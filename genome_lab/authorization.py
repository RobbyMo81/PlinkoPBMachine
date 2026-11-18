"""Both authorization layers (Document 02, build step 2).

Stage authorization is read from authenticated, owner-controlled records.
The owner's authority is key possession: minting requires the owner key,
which lab components never hold, so AI participants cannot create or modify
authorization. The rule-based gate derives one single-use launch approval
per named slot under delegation, binds it to the parent authorization, run,
slot, attempt, executable-artifact fingerprint, DNA fingerprint, pinned image
digest, profile, and passing preflight, durably consumes it before launch
(consumption survives restarts and launch failures), and never reassigns
slots. Approvals expire at the run deadline, run close, or preflight
invalidation, whichever comes first.
"""

import datetime as dt
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from genome_lab.config import LAUNCH_SLOTS
from genome_lab.identity import canonical_bytes

STAGES = ("preflight", "experiment")


class AuthorizationError(RuntimeError):
    """Raised when an owner record fails validation or is untrusted."""


class GateError(RuntimeError):
    """Raised when the gate refuses to derive or consume an approval."""


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")


def _parse_ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(str(value))


@dataclass(frozen=True)
class OwnerAuthorization:
    record: Mapping

    @property
    def stage(self) -> str:
        return str(self.record["stage"])

    @property
    def record_id(self) -> str:
        return str(self.record["record_id"])

    @property
    def expires_at(self) -> str:
        return str(self.record["expires_at"])

    def binding(self, key: str):
        return self.record["bindings"][key]

    def expired(self, now: str | None = None) -> bool:
        moment = _parse_ts(now if now is not None else _now_iso())
        return moment >= _parse_ts(self.expires_at)


def mint_owner_authorization(record: Mapping, owner_key: str) -> tuple[str, str]:
    """OWNER-SIDE TOOLING - never called by lab components or the workflow.

    The owner (or a controlled test fixture) mints a record plus its detached
    signature using the owner key. Without that key no valid record can be
    produced, so this function existing in the package grants the lab no
    authority it did not already have.
    """
    for field in ("record_id", "stage", "issued_at", "expires_at", "bindings"):
        if field not in record:
            raise AuthorizationError(f"owner record missing required field {field!r}")
    if record["stage"] not in STAGES:
        raise AuthorizationError(f"unknown stage {record['stage']!r}")
    body = canonical_bytes(dict(record))
    signature = hmac_sha(key_bytes(owner_key), body)
    return json.dumps(record, sort_keys=True, indent=2), signature


def load_owner_authorization(record_path, signature_path, owner_key: str) -> OwnerAuthorization:
    """Verify the owner's authorization record. Untrusted records fail closed."""
    record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    if not isinstance(record, Mapping):
        raise AuthorizationError("owner record must be a JSON object")
    for field in ("record_id", "stage", "issued_at", "expires_at", "bindings"):
        if field not in record:
            raise AuthorizationError(f"owner record missing required field {field!r}")
    if record["stage"] not in STAGES:
        raise AuthorizationError(f"unknown stage {record['stage']!r}")
    provided = Path(signature_path).read_text(encoding="utf-8").strip()
    expected = hmac_sha(key_bytes(owner_key), canonical_bytes(dict(record)))
    if provided.lower() != expected:
        raise AuthorizationError("untrusted owner record: signature mismatch")
    return OwnerAuthorization(record)


def key_bytes(key: str) -> bytes:
    return sha256(key.encode("utf-8")).digest()


def hmac_sha(key: bytes, body: bytes) -> str:
    import hmac as _hmac

    return _hmac.new(key, body, "sha256").hexdigest()


@dataclass(frozen=True)
class PreflightRecord:
    reference: str
    image: str
    profile: str
    outcomes: Mapping[str, str]
    overall: str
    verified_by: str
    issued_at: str


APPROVE = "APPROVE"


class Gate:
    """Rule-based gate: verifies owner authorization and evidence, issues and
    consumes single-use launch approvals under delegation, governs admission."""

    def __init__(self, ledger_path) -> None:
        self._conn = sqlite3.connect(Path(ledger_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS approvals (
                approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_authorization TEXT NOT NULL,
                run_id TEXT NOT NULL,
                slot TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                artifact_fingerprint TEXT NOT NULL,
                dna_fingerprint TEXT NOT NULL,
                image TEXT NOT NULL,
                profile TEXT NOT NULL,
                preflight_reference TEXT NOT NULL,
                cv_decision TEXT NOT NULL,
                issued_at TEXT NOT NULL,
                expires_at TEXT,
                consumed_at TEXT,
                status TEXT NOT NULL DEFAULT 'issued',
                UNIQUE (run_id, slot)
            )
            """)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS run_state (run_id TEXT PRIMARY KEY, state TEXT NOT NULL)"
        )
        self._conn.commit()

    def verify_stage_authorization(self, auth: OwnerAuthorization, stage: str) -> None:
        if auth.stage != stage:
            raise AuthorizationError(f"record stage {auth.stage!r} does not authorize {stage!r}")
        if auth.expired():
            raise AuthorizationError("owner authorization has expired")

    def verify_experiment_authorization(self, auth: OwnerAuthorization, run_id: str) -> None:
        self.verify_stage_authorization(auth, "experiment")
        if auth.binding("run_id") != run_id:
            raise AuthorizationError("authorization does not name this run")
        slots = list(auth.binding("slots"))
        if sorted(slots) != sorted(LAUNCH_SLOTS):
            raise AuthorizationError(
                f"authorization must name exactly the five slots {LAUNCH_SLOTS}, got {slots}"
            )

    def derive_launch_approval(
        self,
        *,
        auth: OwnerAuthorization,
        run_id: str,
        slot: str,
        attempt: int,
        artifact_fingerprint: str,
        dna_fingerprint: str,
        preflight: PreflightRecord,
        cv_decision: str,
        expires_at: str | None = None,
    ) -> int:
        self.verify_experiment_authorization(auth, run_id)
        if slot not in LAUNCH_SLOTS:
            raise GateError(f"unknown launch slot {slot!r}")
        if preflight.overall != "PASS":
            raise GateError("preflight record is not passing")
        if preflight.image != auth.binding("image") or preflight.profile != auth.binding("profile"):
            raise GateError("preflight record does not match the authorized image and profile")
        if cv_decision != APPROVE:
            raise GateError(f"independent review returned {cv_decision!r}, approval refused")
        if self.approval_for_slot(run_id, slot) is not None:
            raise GateError(
                f"slot {slot!r} already has an approval for this run; slots cannot be reassigned"
            )
        cursor = self._conn.execute(
            """
            INSERT INTO approvals (parent_authorization, run_id, slot, attempt,
                artifact_fingerprint, dna_fingerprint, image, profile,
                preflight_reference, cv_decision, issued_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                auth.record_id,
                run_id,
                slot,
                attempt,
                artifact_fingerprint,
                dna_fingerprint,
                preflight.image,
                preflight.profile,
                preflight.reference,
                cv_decision,
                _now_iso(),
                expires_at,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def approval_for_slot(self, run_id: str, slot: str) -> dict | None:
        row = self._conn.execute(
            "SELECT approval_id, run_id, slot, attempt, artifact_fingerprint, dna_fingerprint,"
            " image, profile, preflight_reference, status, consumed_at"
            " FROM approvals WHERE run_id = ? AND slot = ?",
            (run_id, slot),
        ).fetchone()
        if row is None:
            return None
        return {
            "approval_id": row[0],
            "run_id": row[1],
            "slot": row[2],
            "attempt": row[3],
            "artifact_fingerprint": row[4],
            "dna_fingerprint": row[5],
            "image": row[6],
            "profile": row[7],
            "preflight_reference": row[8],
            "status": row[9],
            "consumed_at": row[10],
        }

    def consume(self, approval_id: int) -> None:
        """Durably consume an approval before requesting launch. Survives restarts."""
        cursor = self._conn.execute(
            "UPDATE approvals SET consumed_at = ?, status = 'consumed'"
            " WHERE approval_id = ? AND consumed_at IS NULL AND status = 'issued'",
            (_now_iso(), approval_id),
        )
        self._conn.commit()
        if cursor.rowcount != 1:
            raise GateError(f"approval {approval_id} is unknown, already consumed, or expired")

    def expire_open_approvals(self, run_id: str, reason: str) -> int:
        """Expire unconsumed approvals (run deadline, run close, preflight invalidation)."""
        cursor = self._conn.execute(
            "UPDATE approvals SET status = 'expired', expires_at = ?"
            " WHERE run_id = ? AND consumed_at IS NULL AND status = 'issued'",
            (_now_iso() + "|" + reason, run_id),
        )
        self._conn.commit()
        return int(cursor.rowcount)

    def save_run_state(self, run_id: str, state: Mapping) -> None:
        self._conn.execute(
            "INSERT INTO run_state (run_id, state) VALUES (?, ?)"
            " ON CONFLICT(run_id) DO UPDATE SET state = excluded.state",
            (run_id, json.dumps(state, sort_keys=True)),
        )
        self._conn.commit()

    def load_run_state(self, run_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT state FROM run_state WHERE run_id = ?", (run_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def close(self) -> None:
        self._conn.close()
