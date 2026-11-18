"""Append-only journal and evidence handoff (Document 02, build step 4).

The journal writer owns an append-only SQLite journal and accepts
authenticated event submissions from the controller, Validator, gate, IRC,
preparer, evaluator, and Critical Verifier. Direct overwrite, truncate, and
delete are denied - there is no mutation API and database triggers abort any
UPDATE or DELETE. Genome containers are denied both the journal and the
append interface. Retained evidence lives under the evidence root, outside
the controller's write access (enforced by identity grants).
"""

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path

from genome_lab.dna import sha256_hex
from genome_lab.identity import GENOME, AuthError, Identity, IdentityRegistry, canonical_bytes

ALLOWED_SUBMITTERS = frozenset(
    {
        "controller",
        "validator",
        "critical_verifier",
        "snapshot_preparer",
        "gate",
        "irc",
        "journal_writer",
        "evaluator",
    }
)
GENESIS_HASH = "0" * 64


class JournalError(RuntimeError):
    """Raised on denied or malformed journal submissions."""


class Journal:
    def __init__(self, path, registry: IdentityRegistry) -> None:
        self._path = Path(path)
        self._registry = registry
        self._conn = sqlite3.connect(self._path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                run_id TEXT NOT NULL,
                identity TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                entry_hash TEXT NOT NULL
            )
            """)
        self._conn.execute(
            "CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON events "
            "BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END"
        )
        self._conn.execute(
            "CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON events "
            "BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END"
        )
        self._conn.commit()

    def submit(self, token: str, kind: str, run_id: str, payload: Mapping) -> int:
        """Authenticated append interface. The token must cover this exact submission."""
        try:
            envelope = self._registry.verify_token(token)
        except AuthError as exc:
            raise JournalError(f"submission rejected: {exc}") from exc
        identity = envelope["identity"]
        if identity == GENOME:
            raise JournalError("genome containers have no journal or append-interface access")
        if identity not in ALLOWED_SUBMITTERS:
            raise JournalError(f"identity {identity!r} may not submit journal events")
        covered = envelope["payload"]
        if (
            covered.get("kind") != kind
            or covered.get("run_id") != run_id
            or covered.get("payload") != dict(payload)
        ):
            raise JournalError("token does not cover this submission (replay or tamper)")
        row = self._conn.execute(
            "SELECT entry_hash FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_hash = row[0] if row else GENESIS_HASH
        ts = _now_iso()
        entry_hash = sha256_hex(
            canonical_bytes(
                {
                    "ts": ts,
                    "run_id": run_id,
                    "identity": identity,
                    "kind": kind,
                    "payload": dict(payload),
                    "prev_hash": prev_hash,
                }
            )
        )
        cursor = self._conn.execute(
            "INSERT INTO events (ts, run_id, identity, kind, payload, prev_hash, entry_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ts,
                run_id,
                identity,
                kind,
                json.dumps(payload, sort_keys=True),
                prev_hash,
                entry_hash,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def submit_as(self, identity: Identity, kind: str, run_id: str, payload: Mapping) -> int:
        """Convenience for components holding an Identity: mint and submit a token."""
        token = identity.issue_token({"kind": kind, "run_id": run_id, "payload": dict(payload)})
        return self.submit(token, kind, run_id, payload)

    def events(self, run_id: str | None = None, kind: str | None = None) -> list[dict]:
        query = "SELECT id, ts, run_id, identity, kind, payload, prev_hash, entry_hash FROM events"
        clauses, params = [], []
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id"
        rows = self._conn.execute(query, params).fetchall()
        return [
            {
                "id": r[0],
                "ts": r[1],
                "run_id": r[2],
                "identity": r[3],
                "kind": r[4],
                "payload": json.loads(r[5]),
                "prev_hash": r[6],
                "entry_hash": r[7],
            }
            for r in rows
        ]

    def verify_chain(self) -> bool:
        prev = GENESIS_HASH
        for event in self.events():
            expected = sha256_hex(
                canonical_bytes(
                    {
                        "ts": event["ts"],
                        "run_id": event["run_id"],
                        "identity": event["identity"],
                        "kind": event["kind"],
                        "payload": event["payload"],
                        "prev_hash": prev,
                    }
                )
            )
            if event["prev_hash"] != prev or event["entry_hash"] != expected:
                return False
            prev = event["entry_hash"]
        return True

    def close(self) -> None:
        self._conn.close()


def derive_player_cards(events: list[dict]) -> list[dict]:
    """Derive G-018 player cards (12 fields) from journaled evidence."""
    cards: dict[str, dict] = {}
    order: list[str] = []
    for event in events:
        payload = event["payload"]
        candidate = payload.get("candidate_id")
        if event["kind"] == "candidate_registered" and candidate:
            cards[candidate] = {
                "genome_id": candidate,
                "taxonomy": payload.get("taxonomy"),
                "structural_fingerprint": payload.get("structural_fingerprint"),
                "full_dna_fingerprint": payload.get("full_dna_fingerprint"),
                "parentage": payload.get("parentage"),
                "method": payload.get("method"),
                "fitness": "unassessed",
                "novelty": "unverified (G-017 certification outside MVP)",
                "verification": [],
                "lifecycle": "registered",
                "evidence_references": [event["id"]],
                "record_version": 1,
            }
            order.append(candidate)
        elif event["kind"] == "admission" and candidate in cards:
            card = cards[candidate]
            card["lifecycle"] = payload.get("outcome", "unknown")
            card["verification"] = list(payload.get("checks", []))
            card["evidence_references"].append(event["id"])
        elif event["kind"] == "scores" and candidate in cards:
            card = cards[candidate]
            if payload.get("hits") is None:
                card["fitness"] = f"unavailable: {payload.get('reason', 'not scored')}"
            else:
                card["fitness"] = {
                    "hits": payload["hits"],
                    "denominator": payload.get("denominator"),
                    "rate": payload.get("rate"),
                }
            card["evidence_references"].append(event["id"])
    return [cards[candidate] for candidate in order]


def derive_final_report(events: list[dict]) -> dict:
    """Derive the final report from journaled evidence only."""
    report: dict = {"event_count": len(events)}
    for event in reversed(events):
        if event["kind"] == "verdict":
            report["verdict"] = event["payload"]
            break
    scores = [e["payload"] for e in events if e["kind"] == "scores"]
    if scores:
        report["scores"] = scores
    distinct = [e["payload"] for e in events if e["kind"] == "distinct_draws"]
    if distinct:
        report["distinct_draws"] = distinct[-1]
    return report


def _now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.UTC).isoformat(timespec="milliseconds")
