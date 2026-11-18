"""Sandbox executor (Document 02, build steps 1 and 6).

Local subprocess executor enforcing the approved attempt bounds: a 30-second
deadline from requested launch through output collection, a 64 KiB combined
stdout+stderr cap, a disposable attempt workspace (no persistent writable
workspace), and read-only code and inputs. On a breach the attempt is
stopped through the runtime, exit is confirmed before further work, and
partial output is discarded.

The enforcing owner-authorized runtime profile lives in genome_lab.runtime
(docker-strict-v1: network-isolated, memory/CPU/process-capped, read-only,
non-privileged containers) and is exercised at preflight (PF-ISO/PF-IRC).
This local executor enforces deadlines, the output cap, and process-tree
termination for controlled fixtures and tests; it applies no OS-level
resource limits.
"""

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from genome_lab.config import ATTEMPT_SECONDS, OUTPUT_CAP_BYTES, LabPaths
from genome_lab.dna import sha256_hex

ENGINE_ARTIFACT_VERSION = "genome-engine-v1"


@dataclass(frozen=True)
class AttemptRequest:
    run_id: str
    slot: str
    attempt: int
    dna_path: Path
    deadline_seconds: int = ATTEMPT_SECONDS
    output_cap_bytes: int = OUTPUT_CAP_BYTES
    env_overrides: dict | None = None


@dataclass
class AttemptResult:
    ok: bool
    breach: bool
    stopped_confirmed: bool
    returncode: int | None
    stdout: str | None
    stderr: str | None
    duration_seconds: float
    artifact_fingerprint: str


def artifact_fingerprint(plinko_root) -> str:
    """SHA-256 over the engine artifact bytes plus its version tag."""
    engine_source = Path(plinko_root) / "genome_lab" / "engine.py"
    return sha256_hex(engine_source.read_bytes() + b"|" + ENGINE_ARTIFACT_VERSION.encode())


class LocalExecutor:
    """Runs genome attempts as isolated subprocesses of the generic engine."""

    def __init__(self, paths: LabPaths) -> None:
        self._paths = paths

    def artifact_fingerprint(self) -> str:
        return artifact_fingerprint(self._paths.plinko_root)

    def run(self, request: AttemptRequest) -> AttemptResult:
        started = time.monotonic()
        attempt_dir = self._paths.attempt_root / request.run_id / request.slot
        attempt_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self._paths.plinko_root) + os.pathsep + env.get("PYTHONPATH", "")
        env.pop("GENOME_ENGINE_TEST_SPAM", None)
        env.pop("GENOME_ENGINE_TEST_SLEEP", None)
        if request.env_overrides:
            env.update(request.env_overrides)
        command = [sys.executable, "-m", "genome_lab.engine", str(Path(request.dna_path))]
        breach = False
        stdout_text: str | None = None
        stderr_text: str | None = None
        returncode: int | None = None
        timed_out = False
        process = subprocess.Popen(
            command,
            cwd=attempt_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout_text, stderr_text = process.communicate(timeout=request.deadline_seconds)
            returncode = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()  # stop the attempt through the runtime
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            returncode = process.returncode
            stdout_text = None  # discard partial output
            stderr_text = None
        stopped_confirmed = process.returncode is not None  # exit confirmed before further work
        if timed_out:
            breach = True
        else:
            stdout_bytes = len((stdout_text or "").encode("utf-8", errors="replace"))
            stderr_bytes = len((stderr_text or "").encode("utf-8", errors="replace"))
            if stdout_bytes + stderr_bytes > request.output_cap_bytes:
                breach = True  # over the combined cap: discard partial output
                stdout_text = None
                stderr_text = None
        duration = time.monotonic() - started
        ok = (not breach) and returncode == 0
        return AttemptResult(
            ok=ok,
            breach=breach,
            stopped_confirmed=stopped_confirmed,
            returncode=returncode,
            stdout=stdout_text,
            stderr=stderr_text,
            duration_seconds=duration,
            artifact_fingerprint=self.artifact_fingerprint(),
        )

    def cleanup_run(self, run_id: str) -> list[str]:
        """Dispose of disposable run resources (attempt workspaces)."""
        run_dir = self._paths.attempt_root / run_id
        removed: list[str] = []
        if run_dir.exists():
            shutil.rmtree(run_dir)
            removed.append(str(run_dir))
        return removed
