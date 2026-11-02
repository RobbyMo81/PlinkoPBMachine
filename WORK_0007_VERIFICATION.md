# WORK-0007 — Clean-room verification and handoff

Scope: isolated `PlinkoPBMachine` only. Production integration and scheduling are NOT authorized. `Instruction.md` is user-authored and left unchanged. No lottery purchase or production ledger write was made.

## Implemented

- `plinko/analysis.py`: 346 six-ball total bins (16–361), current dataset rank by descending frequency then last official draw date; per-sum PB rank and tie metadata. Existing `SumBin.ranking` is a legacy frequency/number, tenth-boundary-tie descriptor retained for compatibility, not the operational selection API.
- `plinko/engine.py`: exact-five-whites sum dynamic-program count/unrank, uniform `SystemRandom` selection with overlap rejection; 100,000 attempts per assignment, `UNSATISFIABLE_SUM` for zero exact-sum candidates and `SEARCH_EXHAUSTED` for bounded search failure. Feasible sets are uniform conditional on preceding accepted tickets and success; the entire nine-ticket portfolio is not uniformly distributed over all globally feasible portfolios. The control uses a separate RNG, is unrestricted and retains collisions.
- `plinko/refresh.py`: fresh isolated SQLite backup of read-only source, schema validation via analyzer. Each refresh needs a new snapshot path; historical snapshots remain intact.
- Follow-up provenance guard: refresh now compares SQLite logical draw digests before/after backup against the validated snapshot, and checks `PRAGMA data_version` for concurrent commits. Failed validation/change removes the provisional snapshot. `source_sha256` is retained solely as an informational hash of the main `.db` file; it excludes uncheckpointed WAL content and must not be interpreted as a source-stability proof. New `source_dataset_hash` and `snapshot_sha256` are the provenance fields for subsequent refreshes. The historical source SHA256 recorded below remains unchanged, but does not establish that the source was stable during that earlier run.
- `plinko/tracking.py`: isolated copy of existing GeneratedPickStorage public API, batch + ten picks, dataset-hash verification against actual snapshot contents, five-minute real-clock persistence check, recorded-at timestamp, reject partial/wrong-target/duplicate-target and uncertain evaluations in PB metrics. Metrics are coverage/draw, ticket/opportunity, control/draw; unique PB / 26 baseline. There is no evaluated future draw yet.

## Executed evidence

- `uv lock && uv sync --locked` installed pinned tzdata 2025.3.
- `python -m ruff check plinko tests` → All checks passed.
- `python -m black --check plinko tests` → 11 files unchanged.
- `python -m pytest -q` → 25 passed (synthetic tracking outcomes explicitly simulated with pre-draw clock).
- Follow-up WAL fix verification: `uv run python -m pytest -q` → 29 passed, including stable WAL commits, concurrent WAL commit, write-and-revert, and failed-validation cleanup; `uv run ruff check plinko tests` and `uv run black --check plinko tests` passed (11 files unchanged). Tests used disposable databases; no production source or ledger write.
- Fresh source read-only SQLite backup at `.cache/cycle_20261030T051624.db`; source SHA256 `a37f94f296c4b13e026879412b1fa340e1a7454c8ef74a6f32b53e22d127ab5d`; 1,426 accepted modern-era draws, latest official 2026-10-28, six legacy excluded. Dataset digest `8ac77adfab08a53c5e29a406b490614f96d8a47c467ba7c3122b67707ca51f6f`.
- Isolated ledger `.cache/plinko_experiment.db` cycle `WORK-0007-20261030T051624` read back with SQL: 1 batch, 9 experimental + 1 control, all 36 white-overlap pairs checked, maximum shared whites = 2; target 2026-10-31, recorded 2026-10-30T05:16:25.742350+00:00. Zero evaluations; metrics state pending=1, evaluated=0, no rates reported. This is a local dry-run portfolio, not a validated prediction or proof of purchase.
- Independent Codex CLI initial read-only review `C:/Users/RobMo/AppData/Local/Temp/plinko-work7-review.log`: FAIL due backdating and unrelated snapshot provenance. Follow-up `C:/Users/RobMo/AppData/Local/Temp/plinko-work7-followup.log`: PASS for those two remediations and duplicate-target guard by code review; sandbox denied SQLite/Python execution, so its independent ledger execution verdict remains FAIL/BLOCKED. Our own SQL readback and full suite above are separate, not mislabeled as TagTeam reproduction.

## Open gates

- No OS-level read-only ACL isolation is proved; source access is enforced by SQLite URI and process convention only.
- No independent executable TagTeam replication of entire real-data cycle; reviewer could only inspect code/ledger bytes due sandbox permissions.
- No continuously running production ingestion/scheduler/dashboard integration; new refresh API must be explicitly invoked per snapshot. No official future PB hit-rate can exist before the target drawing; synthetic fixtures are not empirical results.
- Provenance is local machine time and source snapshot hashing, not an external trusted timestamp or cryptographically attested publication-time history. Do not claim retrospective prediction power.
- Repository not committed/pushed in this cycle; user-authored revised `Instruction.md` remains dirty and is not overwritten. Production approval must be separate and explicit.
