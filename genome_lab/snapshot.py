"""Snapshot interface and known-answer fixture (Document 02, build step 5).

The trusted snapshot preparer uses its dedicated authenticated identity.
The canonical store is opened read-only (mode=ro + query_only) and copied
with Connection.backup; the preparer retains custody of the staging copy.
Eligible development draws are counted and validated in the inclusive window;
counts and digests must agree across source-before-backup, staging copy,
source-after-backup, and the final immutable export before publication.
Publication stops on duplicate dates or invalid records, and on any four-way
disagreement. Build decision (red-team H1): the authenticated publication
record pins the store identity and an as-of timestamp so the baseline
narrative cannot drift silently.
"""

import datetime as dt
import json
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from genome_lab.authorization import AuthorizationError, OwnerAuthorization
from genome_lab.config import EXPECTED_DEV_COUNT, FIXTURE_SIZE
from genome_lab.dna import canonical_bytes, sha256_hex
from genome_lab.identity import Identity

WINDOW_QUERY = (
    "SELECT draw_date, ball1, ball2, ball3, ball4, ball5, powerball FROM draws "
    "WHERE draw_date >= ? AND draw_date <= ? ORDER BY draw_date"
)


class SnapshotError(RuntimeError):
    """Raised when the snapshot procedure must stop."""


def open_readonly(path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    return conn


def fetch_window_rows(conn: sqlite3.Connection, window_start: str, window_end: str) -> list[dict]:
    rows = conn.execute(WINDOW_QUERY, (window_start, window_end)).fetchall()
    return [
        {
            "draw_date": r[0],
            "whites": [r[i] for i in range(1, 6)],
            "powerball": r[6],
        }
        for r in rows
    ]


def validate_window_rows(rows: list[dict]) -> list[str]:
    errors: list[str] = []
    seen_dates: set[str] = set()
    for row in rows:
        date = str(row["draw_date"])
        if date in seen_dates and f"duplicate draw date {date}" not in errors:
            errors.append(f"duplicate draw date {date}")
        seen_dates.add(date)
        whites = row["whites"]
        if (
            len(whites) != 5
            or len(set(whites)) != 5
            or any(not isinstance(w, int) or not 1 <= w <= 69 for w in whites)
        ):
            errors.append(f"invalid white balls at {date}: {whites}")
        pb = row["powerball"]
        if not isinstance(pb, int) or not 1 <= pb <= 26:
            errors.append(f"invalid powerball at {date}: {pb}")
    return errors


def rows_digest(rows: list[dict]) -> str:
    return sha256_hex(canonical_bytes(rows))


def scan(path, window_start: str, window_end: str) -> tuple[int, str, list[str]]:
    conn = open_readonly(path)
    try:
        rows = fetch_window_rows(conn, window_start, window_end)
    finally:
        conn.close()
    errors = validate_window_rows(rows)
    return len(rows), rows_digest(rows), errors


@dataclass(frozen=True)
class PublishedSnapshot:
    export_path: Path
    fixture_path: Path
    publication_path: Path
    publication_signature_path: Path
    publication: dict


class SnapshotPreparer:
    """Trusted preparer: development export plus limited fixture, pre-run."""

    def __init__(self, paths, identity: Identity, auth: OwnerAuthorization) -> None:
        if auth.stage != "preflight":
            raise AuthorizationError("snapshot preparation requires preflight-stage authorization")
        if auth.expired():
            raise AuthorizationError("owner authorization has expired")
        self._paths = paths
        self._identity = identity
        self._auth = auth
        self._source = Path(auth.binding("canonical_db_path"))
        self._window_start = auth.binding("development_window_start")
        self._window_end = auth.binding("development_window_end")

    @property
    def source(self) -> Path:
        return self._source

    @property
    def window(self) -> tuple[str, str]:
        return (self._window_start, self._window_end)

    def prepare(self) -> PublishedSnapshot:
        record_id = f"DATA01-{uuid.uuid4()}"
        count_before, digest_before, errors = scan(
            self._source, self._window_start, self._window_end
        )
        if errors:
            raise SnapshotError(f"invalid canonical development rows: {errors}")

        staging = self._paths.snapshot_root / "preparer_custody" / f"{record_id}.db"
        staging.parent.mkdir(parents=True, exist_ok=True)
        source_conn = open_readonly(self._source)
        try:
            staging_conn = sqlite3.connect(staging)
            try:
                source_conn.backup(staging_conn)
            finally:
                staging_conn.close()
        finally:
            source_conn.close()

        count_staging, digest_staging, staging_errors = scan(
            staging, self._window_start, self._window_end
        )
        count_after, digest_after, after_errors = scan(
            self._source, self._window_start, self._window_end
        )
        if staging_errors or after_errors:
            raise SnapshotError("canonical rows changed or became invalid during preparation")

        export_path = self._paths.evidence_root / f"development_export_{record_id}.db"
        shutil.copyfile(staging, export_path)
        count_export, digest_export, export_errors = scan(
            export_path, self._window_start, self._window_end
        )
        if export_errors:
            raise SnapshotError(f"final export invalid: {export_errors}")

        comparisons = {
            "source_before": (count_before, digest_before),
            "staging_copy": (count_staging, digest_staging),
            "source_after": (count_after, digest_after),
            "final_export": (count_export, digest_export),
        }
        if len(set(comparisons.values())) != 1:
            raise SnapshotError(f"four-way agreement failed: {comparisons}")

        fixture_rows = fetch_window_rows(
            open_readonly(export_path), self._window_start, self._window_end
        )[-FIXTURE_SIZE:]
        fixture = {
            "window": {"start": self._window_start, "end": self._window_end},
            "source_digest": digest_export,
            "draws": [{"date": r["draw_date"], "powerball": r["powerball"]} for r in fixture_rows],
        }
        fixture_digest = sha256_hex(
            canonical_bytes({"source_digest": fixture["source_digest"], "draws": fixture["draws"]})
        )
        fixture_path = self._paths.evidence_root / f"development_fixture_{record_id}.json"
        fixture_path.write_text(json.dumps(fixture, sort_keys=True), encoding="utf-8")

        publication = {
            "record_id": record_id,
            "owner_authorization": self._auth.record_id,
            "store_identity": str(Path(self._source).resolve()),
            "as_of": dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds"),
            "window": {"start": self._window_start, "end": self._window_end},
            "count": count_export,
            "digest": digest_export,
            "expected_count": EXPECTED_DEV_COUNT,
            "count_matches_expected": count_export == EXPECTED_DEV_COUNT,
            "fixture_digest": fixture_digest,
            "fixture_size": len(fixture_rows),
            "export_name": export_path.name,
            "fixture_name": fixture_path.name,
            "issued_at": dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds"),
            "preparer": self._identity.name,
        }
        publication_path = self._paths.evidence_root / f"publication_{record_id}.json"
        publication_path.write_text(
            json.dumps(publication, sort_keys=True, indent=2), encoding="utf-8"
        )
        signature = self._identity.sign(canonical_bytes(publication))
        signature_path = publication_path.with_suffix(".json.sig")
        signature_path.write_text(signature, encoding="utf-8")

        return PublishedSnapshot(
            export_path=export_path,
            fixture_path=fixture_path,
            publication_path=publication_path,
            publication_signature_path=signature_path,
            publication=publication,
        )
