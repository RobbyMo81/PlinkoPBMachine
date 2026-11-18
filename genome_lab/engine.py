"""Generic genome engine - the executable artifact (Document 01 contracts).

Build decision (red-team B2): the lab ships ONE generic engine; a candidate
is a DNA record passed as a read-only input. The gate binds launch approvals
to this artifact's fingerprint plus the candidate's full-DNA fingerprint, so
no per-candidate artifact build is required inside the run clock.

Test hooks behind GENOME_ENGINE_TEST_* environment variables support the
controlled PF-IRC fixtures (output-cap breach, deadline breach) and are part
of the fingerprinted artifact.
"""

import json
import os
import sys
import time


def evaluate_file(dna_path: str) -> dict:
    """Execute one candidate input record (DNA or G3 control) and return the
    complete PB ranking, draw, and input fingerprint binding the executed
    content to the approved candidate."""
    import json
    from pathlib import Path

    from genome_lab.dna import canonical_bytes, dna_from_record, sha256_hex
    from genome_lab.genomes import evaluate_genome, g3_outputs

    record = json.loads(Path(dna_path).read_text(encoding="utf-8"))
    if isinstance(record, dict) and "g3" in record:
        output = dict(g3_outputs(record["g3"]["seed"]))
    else:
        output = evaluate_genome(dna_from_record(record))
    output["input_fingerprint"] = sha256_hex(canonical_bytes(record))
    return output


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        sys.stderr.write("usage: python -m genome_lab.engine <dna-record.json>\n")
        return 2

    spam = os.environ.get("GENOME_ENGINE_TEST_SPAM")
    if spam:
        sys.stdout.write("X" * int(spam))
        sys.stdout.flush()

    nap = os.environ.get("GENOME_ENGINE_TEST_SLEEP")
    if nap:
        time.sleep(float(nap))

    output = evaluate_file(argv[0])
    sys.stdout.write(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
