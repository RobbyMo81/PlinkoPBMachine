"""Enforcing runtime profile: docker-strict-v1 (Documents 01 and 02).

The owner-authorized sandbox profile. Genome attempts execute inside pinned
Linux containers that enforce, at the OS level, everything Document 02's
limits table requires: no network (--network none), 256 MiB memory with no
swap bypass, one logical CPU of compute (--cpus 1), at most 32 processes and
threads (--pids-limit 32), a read-only root filesystem, read-only code and
inputs (only the genome_lab package and the candidate input are mounted),
and no privileges (--user 65534:65534, --cap-drop ALL,
--security-opt no-new-privileges). Containers cannot reach production data,
the authoritative journal, or the network.

The runtime image is content-addressed by SHA-256 digest; PF-ISO verifies the
pinned digest is present locally before any launch, so a retag cannot
silently change the runtime. The profile fingerprint covers the profile
name, image, and exact parameters, so the owner authorization binds the
exact profile, not just its name.

Preflight probes (PF-ISO / PF-IRC) are negative tests run in real containers
under the exact profile: each probe must observe the restriction it claims
(network denied, filesystem read-only, non-root user, memory limit kill,
process limit block, CPU cap). Probes that cannot demonstrate enforcement
fail the check - preflight never passes on unverified claims.
"""

import shutil
import subprocess
import time
import uuid
from collections.abc import Mapping
from pathlib import Path

from genome_lab.config import PROFILE_PARAMETERS, RUNTIME_IMAGE, SANDBOX_PROFILE
from genome_lab.dna import canonical_bytes, sha256_hex
from genome_lab.sandbox import (
    AttemptRequest,
    AttemptResult,
    artifact_fingerprint,
)

# 4 children x 2.0 s busy burn ~= 8.0 CPU-seconds unrestricted on a
# multi-core host; ~= 2.0 under --cpus 1. Anything below the threshold
# demonstrates the CPU cap; the measured value is recorded either way.
CPU_CAP_DEMONSTRATION_THRESHOLD = 3.5
DOCKER_TIMEOUT_SECONDS = 60.0


class SandboxRuntimeError(RuntimeError):
    """Raised when the enforcing runtime cannot be used safely."""


def docker_available() -> bool:
    """True when a docker daemon answers. Probes and launches fail closed otherwise."""
    try:
        completed = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return False
    return completed.returncode == 0 and bool((completed.stdout or "").strip())


def profile_fingerprint(parameters: Mapping | None = None) -> str:
    """SHA-256 over the profile name, image, and exact parameters."""
    spec = {
        "profile": SANDBOX_PROFILE,
        "image": RUNTIME_IMAGE,
        "parameters": dict(parameters if parameters is not None else PROFILE_PARAMETERS),
    }
    return sha256_hex(canonical_bytes(spec))


def container_name_for(request: AttemptRequest) -> str:
    """Run-scoped, collision-free container name (docker name charset)."""
    slug = f"{str(request.run_id)[:12]}-{str(request.slot).lower()}-{int(request.attempt)}"
    return f"genome-{slug}-{uuid.uuid4().hex[:8]}"


def build_run_command(
    *,
    image: str,
    parameters: Mapping,
    package_dir,
    input_path,
    container_name: str,
    env_overrides: Mapping | None = None,
) -> list[str]:
    """The exact docker command for one attempt under the enforcing profile."""
    input_path = Path(input_path)
    flags = [
        "--name",
        container_name,
        "--network",
        str(parameters["network"]),
        "--memory",
        f"{parameters['memory_mib']}m",
        "--memory-swap",
        f"{parameters['memory_swap_mib']}m",
        "--cpus",
        str(parameters["cpus"]),
        "--pids-limit",
        str(parameters["pids_limit"]),
        "--user",
        str(parameters["user"]),
        "--cap-drop",
        str(parameters["cap_drop"]),
        "--security-opt",
        str(parameters["security_opt"]),
    ]
    if parameters["read_only"]:
        flags.append("--read-only")
    flags += [
        "-v",
        f"{package_dir}:/lab/genome_lab:ro",
        "-v",
        f"{input_path.parent}:/inputs:ro",
        "-w",
        "/lab",
    ]
    for key in sorted(env_overrides or {}):
        flags += ["-e", f"{key}={env_overrides[key]}"]
    return [
        "docker",
        "run",
        *flags,
        image,
        "python",
        "-m",
        "genome_lab.engine",
        f"/inputs/{input_path.name}",
    ]


# In-container probe payloads. Each must demonstrate its own restriction and
# exit non-zero when the restriction is absent (fail-closed probes).
_NETWORK_PROBE = """\
import socket
import sys

try:
    socket.create_connection(("1.1.1.1", 53), timeout=3)
except OSError as exc:
    print("NETWORK_DENIED", type(exc).__name__)
    sys.exit(0)
print("NETWORK_REACHABLE")
sys.exit(1)
"""

_FILESYSTEM_PROBE = """\
import os
import sys

writable = []
for target in ("/lab/x", "/inputs/x", "/x"):
    try:
        with open(target, "w") as handle:
            handle.write("probe")
        writable.append(target)
    except OSError:
        pass
readable = False
try:
    names = sorted(os.listdir("/inputs"))
    with open("/inputs/" + names[0], encoding="utf-8") as handle:
        readable = bool(handle.read(16))
except OSError:
    readable = False
print("WRITABLE_COUNT", len(writable))
print("INPUT_READABLE", readable)
sys.exit(1 if writable or not readable else 0)
"""

_UID_PROBE = """\
import os

print("UID", os.getuid())
"""

_MEMORY_PROBE = """\
import sys

chunks = []
allocated = 0
try:
    while allocated < 512:
        chunks.append(bytearray(1024 * 1024))
        allocated += 1
except MemoryError:
    print("MEMORYERROR_AT", allocated)
    sys.exit(3)
print("ALLOCATED_ALL", allocated)
sys.exit(0)
"""

_PROCESS_PROBE = """\
import subprocess
import sys

spawned = 0
for _ in range(40):
    try:
        subprocess.Popen(["/bin/sh", "-c", "sleep 60"])
        spawned += 1
    except OSError:
        print("SPAWN_BLOCKED_AT", spawned)
        sys.exit(0)
print("SPAWNED_ALL", spawned)
sys.exit(0)
"""

_CPU_PROBE = """\
import os
import time

for _ in range(4):
    pid = os.fork()
    if pid == 0:
        end = time.monotonic() + 2.0
        while time.monotonic() < end:
            pass
        os._exit(0)
for _ in range(4):
    os.wait()
times = os.times()
used = times.children_user + times.children_system
print("CHILDREN_CPU_SECONDS", round(used, 2))
"""


class DockerSandbox:
    """Enforcing executor: same interface as LocalExecutor, real containers."""

    def __init__(self, paths, *, image: str = RUNTIME_IMAGE, parameters=PROFILE_PARAMETERS) -> None:
        self._paths = paths
        self._image = str(image)
        self._parameters = dict(parameters)
        self._package_dir = str(Path(paths.plinko_root) / "genome_lab")

    def artifact_fingerprint(self) -> str:
        return artifact_fingerprint(self._paths.plinko_root)

    def _docker(
        self, *args: str, timeout: float = DOCKER_TIMEOUT_SECONDS
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
        )

    def _inspect(self, name: str, go_template: str) -> str | None:
        completed = self._docker("inspect", "-f", go_template, name)
        if completed.returncode != 0:
            return None
        return completed.stdout

    def verify_image(self) -> dict:
        """Evidence that the pinned image digest is present locally (PF-ISO)."""
        name, _, digest = self._image.partition("@")
        if not digest:
            raise SandboxRuntimeError(f"runtime image {self._image!r} is not digest-pinned")
        repo_digests = self._inspect(name, "{{.RepoDigests}}")
        image_id = self._inspect(name, "{{.Id}}")
        present = repo_digests is not None and digest in repo_digests
        return {
            "image": name,
            "pinned_digest": digest,
            "digest_present": present,
            "image_id": (image_id or "").strip() or None,
        }

    def _container_running(self, name: str) -> bool | None:
        state = self._inspect(name, "{{.State.Running}}")
        if state is None:
            return None
        return state.strip().lower() == "true"

    def _container_exit_code(self, name: str) -> int | None:
        code = self._inspect(name, "{{.State.ExitCode}}")
        if code is None or not code.strip().lstrip("-").isdigit():
            return None
        return int(code.strip())

    def _stop_and_confirm(self, name: str, timeout: float = 30.0) -> tuple[bool, int | None]:
        """Stop the attempt through the runtime and confirm exit (Document 02 step 6)."""
        self._docker("kill", name)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._container_running(name) is False:
                return True, self._container_exit_code(name)
            time.sleep(0.2)
        return False, self._container_exit_code(name)

    def run(self, request: AttemptRequest) -> AttemptResult:
        started = time.monotonic()
        attempt_dir = Path(self._paths.attempt_root) / request.run_id / request.slot
        attempt_dir.mkdir(parents=True, exist_ok=True)
        name = container_name_for(request)
        command = build_run_command(
            image=self._image,
            parameters=self._parameters,
            package_dir=self._package_dir,
            input_path=request.dna_path,
            container_name=name,
            env_overrides=request.env_overrides,
        )
        breach = False
        timed_out = False
        stdout_text: str | None = None
        stderr_text: str | None = None
        returncode: int | None = None
        stopped_confirmed = False
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        try:
            stdout_text, stderr_text = process.communicate(timeout=request.deadline_seconds)
            returncode = process.returncode
            stopped_confirmed = True
        except subprocess.TimeoutExpired:
            timed_out = breach = True
            confirmed, exit_code = self._stop_and_confirm(name)
            stopped_confirmed = confirmed
            returncode = exit_code
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        finally:
            self._docker("rm", "-f", name)
        if not timed_out:
            stdout_bytes = len((stdout_text or "").encode("utf-8", errors="replace"))
            stderr_bytes = len((stderr_text or "").encode("utf-8", errors="replace"))
            if stdout_bytes + stderr_bytes > request.output_cap_bytes:
                breach = True
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
        """Terminate and remove any containers still held for the run."""
        removed: list[str] = []
        prefix = f"genome-{str(run_id)[:12]}"
        listing = self._docker("ps", "-a", "--format", "{{.Names}}")
        for name in (listing.stdout or "").split():
            if name.startswith(prefix):
                self._docker("rm", "-f", name)
                removed.append(name)
        run_dir = Path(self._paths.attempt_root) / run_id
        if run_dir.exists():
            shutil.rmtree(run_dir)
            removed.append(str(run_dir))
        return removed

    # ------------------------------------------------------------ probes

    def _run_probe_container(
        self, code: str, *, input_dir=None, timeout: float = 120.0
    ) -> tuple[int | None, str | None, str | None]:
        """Run one probe under the exact enforcing profile and dispose of it."""
        name = f"genome-probe-{uuid.uuid4().hex[:12]}"
        parameters = self._parameters
        flags = [
            "--name",
            name,
            "--network",
            str(parameters["network"]),
            "--memory",
            f"{parameters['memory_mib']}m",
            "--memory-swap",
            f"{parameters['memory_swap_mib']}m",
            "--cpus",
            str(parameters["cpus"]),
            "--pids-limit",
            str(parameters["pids_limit"]),
            "--user",
            str(parameters["user"]),
            "--cap-drop",
            str(parameters["cap_drop"]),
            "--security-opt",
            str(parameters["security_opt"]),
        ]
        if parameters["read_only"]:
            flags.append("--read-only")
        flags += ["-v", f"{self._package_dir}:/lab/genome_lab:ro", "-w", "/lab"]
        if input_dir is not None:
            flags += ["-v", f"{input_dir}:/inputs:ro"]
        command = ["docker", "run", *flags, self._image, "python", "-c", code]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout, check=False
            )
            result = (completed.returncode, completed.stdout, completed.stderr)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", name], capture_output=True, timeout=30, check=False)
            result = (None, None, None)
        finally:
            subprocess.run(
                ["docker", "rm", "-f", name], capture_output=True, timeout=30, check=False
            )
        return result

    def _probe_image_digest(self) -> dict:
        evidence = self.verify_image()
        return {"ok": bool(evidence["digest_present"]), **evidence}

    def _probe_network_denied(self) -> dict:
        code, out, _err = self._run_probe_container(_NETWORK_PROBE, timeout=30)
        denied = code == 0 and "NETWORK_DENIED" in (out or "")
        return {"ok": denied, "exit_code": code, "observed": (out or "").strip()}

    def _probe_filesystem_read_only(self, input_dir) -> dict:
        code, out, err = self._run_probe_container(
            _FILESYSTEM_PROBE, input_dir=input_dir, timeout=60
        )
        read_only = code == 0 and "WRITABLE_COUNT 0" in (out or "")
        return {
            "ok": read_only,
            "exit_code": code,
            "observed": (out or "").strip(),
            "probe_stderr": (err or "").strip()[:200] or None,
        }

    def _probe_non_root_user(self) -> dict:
        expected = int(str(self._parameters["user"]).split(":")[0])
        code, out, _err = self._run_probe_container(_UID_PROBE, timeout=30)
        parts = (out or "").split()
        uid = int(parts[-1]) if parts and parts[-1].lstrip("-").isdigit() else None
        return {
            "ok": uid is not None and uid == expected and uid != 0,
            "expected_uid": expected,
            "observed_uid": uid,
            "exit_code": code,
        }

    def _probe_memory_limit(self) -> dict:
        code, out, _err = self._run_probe_container(_MEMORY_PROBE, timeout=60)
        blocked = code not in (0, None) and "ALLOCATED_ALL" not in (out or "")
        return {
            "ok": blocked,
            "exit_code": code,
            "limit_mib": self._parameters["memory_mib"],
            "observed": (out or "").strip(),
            "stop_reason": "cgroup memory limit" if blocked else "no enforcement observed",
        }

    def _probe_process_limit(self) -> dict:
        code, out, _err = self._run_probe_container(_PROCESS_PROBE, timeout=60)
        blocked_at = None
        if "SPAWN_BLOCKED_AT" in (out or ""):
            blocked_at = int(out.split("SPAWN_BLOCKED_AT")[1].split()[0])
        return {
            "ok": blocked_at is not None and blocked_at < 40,
            "blocked_at": blocked_at,
            "limit_tasks": self._parameters["pids_limit"],
            "exit_code": code,
        }

    def _probe_cpu_cap(self) -> dict:
        code, out, _err = self._run_probe_container(_CPU_PROBE, timeout=60)
        used = None
        if "CHILDREN_CPU_SECONDS" in (out or ""):
            used = float(out.split("CHILDREN_CPU_SECONDS")[1].split()[0])
        enforced = used is not None and used < CPU_CAP_DEMONSTRATION_THRESHOLD
        return {
            "ok": enforced,
            "children_cpu_seconds": used,
            "threshold": CPU_CAP_DEMONSTRATION_THRESHOLD,
            "exit_code": code,
            "note": "4 children burning 2 s each: ~8.0 unrestricted on multi-core, ~2.0 capped",
        }

    def profile_iso_probes(self, input_dir) -> dict:
        """PF-ISO isolation probes, run as real containers under the exact profile."""
        probes = {
            "image_digest_verified": self._probe_image_digest,
            "network_denied": self._probe_network_denied,
            "filesystem_read_only": lambda: self._probe_filesystem_read_only(input_dir),
            "non_root_user": self._probe_non_root_user,
        }
        results: dict[str, dict] = {}
        for key, probe in probes.items():
            try:
                results[key] = probe()
            except (SandboxRuntimeError, OSError, subprocess.SubprocessError) as exc:
                results[key] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return results

    def profile_irc_probes(self) -> dict:
        """PF-IRC resource-limit probes with measured results and stop reasons."""
        probes = {
            "memory_limit_enforced": self._probe_memory_limit,
            "process_limit_enforced": self._probe_process_limit,
            "cpu_cap_enforced": self._probe_cpu_cap,
        }
        results: dict[str, dict] = {}
        for key, probe in probes.items():
            try:
                results[key] = probe()
            except (SandboxRuntimeError, OSError, subprocess.SubprocessError) as exc:
                results[key] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return results
