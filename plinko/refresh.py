"""Read-only refresh of canonical draw history into an isolated snapshot."""

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

from plinko.analysis import analyze, load_draws
from plinko.tracking import _isolated


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def refresh_analysis(source: Path, snapshot: Path, *, workspace_root: Path):
    """Read source via SQLite mode=ro; create a fresh isolated snapshot.

    The caller must supply a verified canonical source. Refuse a source change
    observed during refresh; provenance is bound to the validated snapshot.
    """
    destination = _isolated(snapshot, workspace_root)
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError("snapshot must be a new path in an existing workspace directory")
    original = Path(source).resolve()
    if not original.is_file() or destination == original:
        raise ValueError("source must be an existing distinct database")
    created = False
    try:
        with closing(sqlite3.connect(original.as_uri() + "?mode=ro", uri=True)) as upstream:
            upstream.execute("PRAGMA query_only=ON")
            if upstream.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("source SQLite quick_check failed")
            version_before = upstream.execute("PRAGMA data_version").fetchone()[0]
            source_hash = analyze(load_draws(original).rows).dataset_hash
            # Historical main-file checksum is informational: WAL commits need
            # not change these bytes. Never use it as the stability guard.
            main_file_hash = sha256(original)
            # Mode=rw fails closed rather than creating an unapproved path.
            destination.touch(exist_ok=False)
            created = True
            with closing(sqlite3.connect(destination.as_uri() + "?mode=rw", uri=True)) as local:
                upstream.backup(local)
                if local.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("snapshot SQLite quick_check failed")
            loaded = load_draws(destination)
            result = analyze(loaded.rows)
            source_hash_after = analyze(load_draws(original).rows).dataset_hash
            version_after = upstream.execute("PRAGMA data_version").fetchone()[0]
            if version_before != version_after or not (
                source_hash == source_hash_after == result.dataset_hash
            ):
                raise ValueError("source changed during snapshot; do not generate from it")
        return result, {
            "source_sha256": main_file_hash,
            "source_sha256_scope": "main_db_file_only_not_wal",
            "source_dataset_hash": source_hash,
            "snapshot_sha256": sha256(destination),
            "dataset_hash": result.dataset_hash,
            "excluded_legacy": loaded.excluded_legacy,
        }
    except Exception:
        if created:
            destination.unlink()
        raise
