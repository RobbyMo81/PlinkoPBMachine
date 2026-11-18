"""OWNER-SIDE TOOLING - stage authorization minting (Documents 01 and 02).

Never called by lab components or the workflow: the owner's authority is
key possession, and the owner key is never issued by the lab. `keygen`
writes the owner key out of band (once, restricted to the current user);
`mint` signs an authorization record with that key. Lab code only ever
VERIFIES these records (load_owner_authorization) - it cannot create or
modify them.

The record's `authorized_by` field records the human-controlled channel
that authorized it (the owner's authenticated directive), so the mint is
attributable and auditable alongside the journal evidence.
"""

import argparse
import datetime as dt
import getpass
import json
import secrets
import subprocess
from collections.abc import Mapping
from pathlib import Path

from genome_lab.authorization import mint_owner_authorization
from genome_lab.config import (
    EXPECTED_DEV_COUNT,
    RUNTIME_IMAGE,
    SANDBOX_PROFILE,
    WINDOW_END,
    WINDOW_START,
)
from genome_lab.runtime import profile_fingerprint


def keygen(path) -> dict:
    """Write the owner key once, out of band; never overwrite, never print it."""
    path = Path(path)
    if path.exists():
        return {"path": str(path), "created": False}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(secrets.token_hex(32), encoding="utf-8")
    try:
        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{getpass.getuser()}:F",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except OSError, subprocess.SubprocessError:
        # ACL restriction is best-effort; the key file must never enter a repo.
        pass
    return {"path": str(path), "created": True}


def preflight_record_spec(
    *,
    canonical_db_path,
    expires_hours: float = 72.0,
    authorized_by: str,
    record_id: str | None = None,
) -> dict:
    """Preflight-stage authorization content: the exact runtime image and
    sandbox profile plus the snapshot scope (absolute canonical database
    path and approved development window) that Document 01 requires."""
    now = dt.datetime.now(dt.UTC)
    return {
        "record_id": record_id or f"AUTH-PREFLIGHT-{now:%Y%m%dT%H%M%SZ}",
        "stage": "preflight",
        "issued_at": now.isoformat(timespec="milliseconds"),
        "expires_at": (now + dt.timedelta(hours=expires_hours)).isoformat(timespec="milliseconds"),
        "authorized_by": authorized_by,
        "bindings": {
            "image": RUNTIME_IMAGE,
            "profile": SANDBOX_PROFILE,
            "profile_fingerprint": profile_fingerprint(),
            "canonical_db_path": str(Path(canonical_db_path).resolve()),
            "development_window_start": WINDOW_START,
            "development_window_end": WINDOW_END,
            "expected_development_count": EXPECTED_DEV_COUNT,
        },
    }


def mint_record(record: Mapping, owner_key: str, out_dir) -> dict:
    """Sign the record with the owner key; write record + detached signature."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record_json, signature = mint_owner_authorization(dict(record), owner_key)
    record_path = out_dir / f"{record['record_id']}.json"
    signature_path = record_path.with_suffix(".json.sig")
    record_path.write_text(record_json, encoding="utf-8")
    signature_path.write_text(signature, encoding="utf-8")
    return {"record_path": str(record_path), "signature_path": str(signature_path)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="genome_lab.owner",
        description="Owner-side stage-authorization tooling (out of band).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    keygen_parser = subparsers.add_parser("keygen", help="write the owner key once")
    keygen_parser.add_argument("--key-file", required=True)

    mint_parser = subparsers.add_parser("mint", help="mint a signed preflight-stage authorization")
    mint_parser.add_argument("--key-file", required=True)
    mint_parser.add_argument("--canonical-db-path", required=True)
    mint_parser.add_argument(
        "--authorized-by",
        required=True,
        help="provenance: the human-controlled channel authorizing this record",
    )
    mint_parser.add_argument("--expires-hours", type=float, default=72.0)
    mint_parser.add_argument("--record-id")
    mint_parser.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    if args.command == "keygen":
        print(json.dumps(keygen(args.key_file)))
        return 0

    owner_key = Path(args.key_file).read_text(encoding="utf-8").strip()
    record = preflight_record_spec(
        canonical_db_path=args.canonical_db_path,
        expires_hours=args.expires_hours,
        authorized_by=args.authorized_by,
        record_id=args.record_id,
    )
    minted = mint_record(record, owner_key, args.out)
    print(json.dumps({"record": record, **minted}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
