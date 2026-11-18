"""Lab configuration, limits, and identifiers (Document 02, build step 1).

Implements the standalone laboratory: absolute lab root plus the absolute
roots of both projects, path resolution through reparse points before
disjointness testing, run/slot/check identifiers, and the approved bounds.
"""

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

# Approved bounds (Document 02, "Limits and test evidence").
RUN_SECONDS = 25 * 60
AI_INTERACTION_SECONDS = 90
ATTEMPT_SECONDS = 30
OUTPUT_CAP_BYTES = 64 * 1024
CONTAINER_MEMORY_MIB = 256
CONTAINER_CPU_SHARE = 1
CONTAINER_PROCESS_LIMIT = 32
MAX_AI_INTERACTIONS = 13
MAX_CONTAINER_ATTEMPTS = 5

# Development window and evaluation constants (Documents 01 and 02).
WINDOW_START = "2015-10-07"
WINDOW_END = "2025-12-31"
EXPECTED_DEV_COUNT = 1297
CHANCE_P = 3 / 26
# Build decision B1: a hit is a development draw whose actual Powerball is
# among the genome's HIT_SET_SIZE highest-ranked PB values. Evidence: the
# pass-2 draft said "Report Top-3 hits" (git 7e1e7f9), the 3/26 null, and the
# Top-3-preservation language in Documents 01/02.
HIT_SET_SIZE = 3
# Build decision: pinned fixture membership rule (doc left it to the
# preparer) - the most recent FIXTURE_SIZE in-window development draws.
FIXTURE_SIZE = 50

# The five single-use launch slots (Document 01).
LAUNCH_SLOTS = ("SEED-G1", "SEED-G2", "SEED-G3", "MUTATION-G2", "CROSSOVER-G1-G2")

# Deterministic check catalog (Document 02) - 12 IDs.
CHECK_IDS = (
    "PF-ISO",
    "PF-IRC",
    "PF-JRN",
    "PF-GATE",
    "PF-DNA",
    "PF-OUTPUT",
    "CAND-ART",
    "CAND-LINE",
    "RUN-OUTPUT",
    "DATA-01",
    "EVAL-01",
    "CLOSE-01",
)
PREFLIGHT_CHECKS = ("PF-ISO", "PF-IRC", "PF-JRN", "PF-GATE", "PF-DNA", "PF-OUTPUT")

# Runtime image identity and sandbox profile bound by owner authorization.
RUNTIME_IMAGE = "genome-lab-local-v1"
SANDBOX_PROFILE = "local-python-subprocess-v1"


class LabSetupError(RuntimeError):
    """Raised when the laboratory cannot be set up safely."""


def resolve_actual(path) -> Path:
    """Resolve a path through symlinks, junctions, and other reparse points."""
    return Path(os.path.realpath(os.path.abspath(str(path))))


@dataclass(frozen=True)
class LabPaths:
    """Absolute, resolved laboratory layout.

    Configuration (state), run working files (attempts), and authoritative
    evidence (journal, snapshots, exports) are kept separate. The evidence
    root is outside the controller's write access (journal append interface
    only; enforced by identity grants in the journal and evidence store).
    """

    lab_root: Path
    plinko_root: Path
    pbmachine_root: Path

    @property
    def project_roots(self) -> tuple[Path, ...]:
        return (self.plinko_root, self.pbmachine_root)

    @property
    def evidence_root(self) -> Path:
        return self.lab_root / "evidence"

    @property
    def state_root(self) -> Path:
        return self.lab_root / "state"

    @property
    def snapshot_root(self) -> Path:
        return self.lab_root / "snapshots"

    @property
    def attempt_root(self) -> Path:
        return self.lab_root / "attempts"

    @property
    def owner_dir(self) -> Path:
        return self.lab_root / "owner"

    @property
    def ledger_path(self) -> Path:
        return self.state_root / "gate_ledger.db"

    @property
    def journal_path(self) -> Path:
        return self.evidence_root / "journal.db"

    def ensure_dirs(self) -> None:
        for directory in (
            self.evidence_root,
            self.state_root,
            self.snapshot_root,
            self.attempt_root,
            self.owner_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _contains(parent: Path, child: Path) -> bool:
    return parent == child or parent in child.parents


def validate_disjointness(lab_root, project_roots) -> None:
    """Block setup unless the resolved lab root is disjoint from every project root.

    Resolves every path through reparse points first; fails closed when a
    path cannot be resolved or the lab root overlaps a project tree.
    """
    lab = resolve_actual(lab_root)
    for raw_root in project_roots:
        root = resolve_actual(raw_root)
        if _contains(lab, root) or _contains(root, lab):
            raise LabSetupError(f"lab root {lab} overlaps project root {root}")


def build_lab(lab_root, plinko_root, pbmachine_root) -> LabPaths:
    """Create and validate the standalone laboratory layout."""
    validate_disjointness(lab_root, (plinko_root, pbmachine_root))
    paths = LabPaths(
        lab_root=resolve_actual(lab_root),
        plinko_root=resolve_actual(plinko_root),
        pbmachine_root=resolve_actual(pbmachine_root),
    )
    paths.ensure_dirs()
    return paths


def new_run_id() -> str:
    return str(uuid.uuid4())


def new_check_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"
