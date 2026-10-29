# AI Agent Directive: Powerball Plinko System Rebuild

**Mission:** Rebuild the existing Powerball analysis and draw-generation engine around the six-ball Master Plinko Theory while preserving the current tracking infrastructure.

**Execution methodology:** Clean Room Development  
**Verification methodology:** TagTeam Independent Review  
**Primary constraint:** Preserve existing production data, tracking history, and operational functionality.

---

## 1. Objective

Replace the existing draw-generation methodology with the Master Plinko Theory established below.

The rebuilt system must:

- Analyze historical Powerball draws using all six balls.
- Establish a master frequency distribution based on total draw sums.
- Decompose each sum bin into Powerball frequency rankings.
- Analyze the associated white-ball frequencies without imposing unsupported patterns.
- Generate nine experimental draws and one independent random control.
- Continue using the existing system's tracking and evaluation methodology.
- Dynamically recalculate distributions as new historical draws are ingested.

**Do not introduce additional prediction theories, player-behavior models, jackpot-sharing assumptions, or alternative optimization strategies.**

The objective is to implement and evaluate the defined theory, not to reinterpret it.

---

# Phase 1A — Mandatory Clean Room Engineering Procedures

**Scope:** All source code, scripts, architectural designs, CLI commands, dependencies, configurations, tests, and generated artifacts.

**Enforcement:** No implementation, execution, modification, or deployment may occur outside the approved Clean Room workflow.

## 1. Clean Room Operating Principle

All development must follow:

**Discover → Isolate → Baseline → Design → Implement → Test → TagTeam Verify → Approve → Integrate → Audit**

The production application is the protected reference system. The Clean Room is the only authorized environment for experimental development and execution.

All changes must be traceable, reversible, and limited to the approved modification scope.

## 2. Source Code Isolation

Before changing source code:

1. Identify the source file, its purpose, and its dependencies.
2. Map its upstream callers and downstream consumers.
3. Record the original file hash and repository commit.
4. Create an isolated working copy or development worktree.
5. Establish baseline tests for affected functionality.
6. Document the intended modification and expected behavior.

During implementation:

- Modify only approved files.
- Preserve public interfaces unless explicitly authorized.
- Avoid unrelated refactoring.
- Do not modify production source code.
- Do not introduce undocumented dependencies.
- Do not change existing data schemas without migration and compatibility analysis.
- Maintain a change manifest identifying every modified file.

After implementation, perform regression tests and independent TagTeam verification.

**Required evidence:** Source diff, file hashes, dependency impact, test results, and verification status.

## 3. Script Isolation

This applies to Python, Bash, PowerShell, JavaScript, Rust utilities, batch files, SQL scripts, and all other executable automation.

Every script must be classified before execution:

| Classification | Execution policy |
|---|---|
| Read-only inspection | Allowed after scope verification |
| Local analysis | Clean Room only |
| File modification | Isolated workspace only |
| Database modification | Disposable test database only |
| Network/API operations | Explicitly approved test endpoints |
| Production operations | Prohibited without human authorization |

Additional requirements:

- Inspect script behavior before execution.
- Identify filesystem writes, subprocess calls, environment-variable use, and network operations.
- Remove embedded credentials and production connection strings.
- Use least-privilege execution.
- Establish execution timeouts and resource limits.
- Capture exit codes, stdout, stderr, and modified artifacts.
- Verify file and database state after execution.

Never execute unreviewed scripts against the operational application.

## 4. Architectural and Design Isolation

All architectural changes must begin as proposals, not implementation.

### Required procedure

1. Document the existing architecture.
2. Identify the precise design problem.
3. Map affected layers, connections, and dependency graphs.
4. Propose the minimum viable architectural change.
5. Analyze compatibility, data integrity, and failure scenarios.
6. Identify rollback requirements.
7. Submit the design to TagTeam for independent review.

Required artifacts:

- `ARCHITECTURE_BASELINE.md`
- `DESIGN_CHANGE_PROPOSAL.md`
- `DEPENDENCY_IMPACT_GRAPH.md`
- `DESIGN_VERIFICATION.md`

**Design guardrails:**

- Preserve existing tracking interfaces.
- Prevent experimental components from modifying production datasets.
- Prefer isolated modules over invasive changes.
- Do not replace working subsystems without demonstrated necessity.
- Keep historical data immutable.
- Preserve clear ownership of data ingestion, analysis, generation, and tracking.

TagTeam must verify the design before implementation begins.

## 5. CLI Capability Isolation

**The CLI is an execution capability, not an unrestricted authority.**

All CLI operations must follow an explicit permission model.

### CLI access levels

| Level | Capability | Authorization |
|---|---|---|
| L0 | Read-only discovery | Permitted within approved scope |
| L1 | Clean Room file creation and modification | Permitted after baseline |
| L2 | Dependency installation and local builds | Permitted in isolated environment |
| L3 | Isolated script and test execution | Permitted with logging |
| L4 | Integration environment modification | Requires TagTeam approval |
| L5 | Production modification or execution | Requires explicit human approval |

### Mandatory CLI preflight

Before every state-changing CLI operation, establish:

- Current working directory.
- Target environment and repository.
- Exact command and arguments.
- Expected files or resources affected.
- Required permissions.
- Anticipated side effects.
- Recovery or rollback procedure.

### CLI execution guardrails

- Never run destructive commands against production.
- Never execute commands from an unverified working directory.
- Never use unrestricted recursive deletion.
- Never run remote scripts directly without inspection.
- Never expose credentials in command output or audit logs.
- Never modify global runtime dependencies when project-local isolation is available.
- Never elevate privileges without explicit authorization.
- Never use a successful exit code as the sole proof of correctness.

Use dry-run modes whenever supported.

State-changing commands must produce an auditable execution record.

### CLI Capability Manifest

Create `CLI_CAPABILITY_MANIFEST.md` containing:

- Available commands and executables.
- Runtime versions and executable paths.
- Required environment variables, with secrets redacted.
- Filesystem and network permissions.
- Authorized execution scope.
- Expected side effects.
- Prohibited operations.
- Capability dependencies and limitations.

The agent must not assume a tool or CLI capability exists without discovering and verifying it.

## 6. Dependency and Runtime Isolation

- Use project-specific virtual environments for Python.
- Respect the repository's declared package manager and lockfile.
- Use isolated build outputs for compiled components.
- Pin dependency versions where applicable.
- Verify runtime and compiler compatibility.
- Avoid global installations unless explicitly authorized.
- Record dependency changes and security findings.
- Confirm that development dependencies cannot overwrite production dependencies.

Where containers are used, mount production resources read-only or do not mount them at all.

External services must use test credentials and isolated endpoints.

## 7. Database and Historical Data Protection

The Powerball historical dataset is authoritative.

Requirements:

1. Preserve original historical records.
2. Use immutable snapshots inside the Clean Room.
3. Verify dataset hashes before and after testing.
4. Perform calculations against isolated copies.
5. Validate ingestion against duplicate records and incorrect draw dates.
6. Never overwrite historical experiment results.
7. Store the exact dataset version used for every generated portfolio.
8. Test migrations against disposable databases.
9. Verify that rollback restores the previous application state without losing recorded observations.

New calculations must not silently modify historical source data.

## 8. TagTeam Verification Protocol

TagTeam must act independently of the implementation agent.

For every major change, the primary agent submits:

- The proposed or completed change.
- Affected files and dependencies.
- Test evidence.
- Known risks.
- Expected behavior.
- Rollback information.

TagTeam independently evaluates:

1. Scope compliance.
2. Mathematical correctness.
3. Source-code correctness.
4. Script side effects.
5. Architectural compatibility.
6. CLI execution safety.
7. Data integrity.
8. Test completeness.
9. Regression impact.
10. Audit completeness.

TagTeam must reproduce critical results rather than merely accept the primary agent's test report.

**Any FAIL or BLOCKED finding prevents promotion to the next stage.**

The implementing agent may correct findings, but the verifier must independently confirm remediation.

If the existing TagTeam framework is unavailable, report `VERIFICATION_BLOCKED`; do not substitute self-certification.

## 9. Mandatory Audit Record

Create `CLEAN_ROOM_AUDIT.md`.

For every state-changing operation, record:

- Timestamp.
- Agent identity and role.
- Task identifier.
- Environment.
- Target files or resources.
- Command or modification performed.
- Before/after hashes where applicable.
- Test results.
- TagTeam verification reference.
- Approval status.
- Rollback reference.

Maintain append-only records where practical, and prohibit silent modifications to prior audit entries.

## 10. Release Gate

No Clean Room artifact may enter the operational system until:

- [ ] The change is within approved scope.
- [ ] Baseline behavior is documented.
- [ ] Dependencies are identified.
- [ ] Source and script modifications are reviewed.
- [ ] CLI operations are auditable.
- [ ] Architectural compatibility is verified.
- [ ] All required tests pass.
- [ ] Historical data integrity is confirmed.
- [ ] TagTeam independently approves the change.
- [ ] Rollback procedures are validated.
- [ ] Explicit human authorization for production integration is recorded.

**Final Enforcement Rule**

No agent may bypass the Clean Room by changing tools, switching shells, spawning subprocesses, delegating execution, or using an alternate runtime.

The same restrictions apply to subagents, automated scripts, CI/CD pipelines, and external execution tools.

A violation must halt affected operations, preserve evidence, and initiate a scope-limited recovery procedure.

**A successful implementation is not considered complete until its correctness, isolation, reproducibility, and auditability are independently verified.**

---

## 2. Phase 0 — Mandatory System Investigation

Before writing or modifying application code:

1. Discover the existing application architecture, entry points, dependencies, databases, configuration, and execution workflows.
2. Identify all subsystems responsible for:
   - Historical draw ingestion and validation.
   - Sum and frequency calculations.
   - Powerball and white-ball analysis.
   - Draw generation.
   - Experimental tracking and performance evaluation.
   - Reporting, dashboards, scheduling, and persistence.
3. Map component dependencies and data flows.
4. Identify which existing components can be reused without modification.
5. Establish a baseline of current functionality and test results.
6. Identify the minimum necessary changes.

Produce:

- `INVESTIGATION_REPORT.md`
- `DEPENDENCY_GRAPH.md`
- `IMPLEMENTATION_PLAN.md`

**Guardrail:** Investigation must be read-only. No production changes are authorized during this phase.

### TagTeam Verification Gate 0

Assign an independent verification agent to challenge the investigation findings.

TagTeam must verify architectural claims against source code, confirm dependencies, identify omitted connections, and approve the proposed modification boundaries.

Do not proceed until discrepancies are resolved.

Use the repository's existing TagTeam mechanism if available. If unavailable, report the missing capability rather than falsely claiming verification.

---

## 3. Phase 1 — Clean Room Environment

Create an isolated development environment.

Requirements:

- Do not directly modify the production application during development.
- Preserve the existing source code and configuration.
- Use isolated dependencies and test databases.
- Use snapshots or copies of historical datasets.
- Prevent experimental execution from placing live lottery orders or changing production tracking records.
- Maintain reproducible builds, deterministic test fixtures, and an audit trail.
- Record the original application version and commit identifier.

The clean room must provide sufficient isolation to conduct development, integration testing, and independent verification without impacting the operational system.

**Exit condition:** A verified baseline exists and the clean room is demonstrably isolated from production.

---

## 4. Phase 2 — Implement Master Plinko Theory

### Step 1 — Master Plinko Distribution

For every historical draw, calculate:

`Total Sum = WB1 + WB2 + WB3 + WB4 + WB5 + PB`

Group draws into bins by their exact Total Sum Value.

Count the occurrence frequency of every sum bin and visualize the resulting distribution as the Master Plinko bell curve.

Preserve each original draw record.

### Step 2 — Sum Frequency Analysis

For every sum bin:

- Record its Total Sum Value.
- Calculate its observed frequency.
- Determine its position within the master distribution.
- Identify the highest-frequency sum.
- Identify the lowest-frequency qualifying sum on each side of the distribution.

Do not substitute the sum of five white balls for the six-ball Total Sum Value.

Handle tied frequencies explicitly and deterministically. Record tie-resolution rules without deleting equally ranked sums from the underlying dataset.

### Step 3 — Nested PB Frequency Distribution

For each Total Sum Value bin:

1. Retrieve every historical draw within that bin.
2. Identify its associated PB number.
3. Count occurrences of PB values 1–26.
4. Produce a frequency distribution specific to that bin.

All PB frequencies within a bin must reconcile with the total historical frequency of that bin.

### Step 4 — Dynamic Top 10 PB Ranking

Within each sum bin:

- Rank PBs by observed occurrence frequency.
- Retain the top 10.
- Group identical frequencies into tied sets.
- Preserve additional PBs tied at the 10th-ranked boundary.
- Mark additional retained boundary entries as `OUTLIER_TIE`.
- Recalculate rankings whenever new historical records are ingested.

Distinguish zero-observation PBs from observed PBs. Preserve the full frequency distribution even when only the top-ranked subset is used for generation.

Never arbitrarily discard tied PBs.

### Step 5 — White-Ball Chaos Theory

For each retained PB within its parent sum bin:

- Retrieve associated historical five-white-ball sets.
- Calculate individual white-ball occurrence frequencies.
- Preserve the original five-ball combinations.
- Record odd/even composition.
- Permit descriptive Hot, Neutral, and Cold classifications where explicit, reproducible thresholds are defined.
- Observe potential relationships without assuming that a meaningful pattern must exist.

**Critical restriction:** Do not force the white-ball sets into a bell curve, invent correlations, or treat observed historical frequency as evidence of future predictive power.

Preserve both individual frequency observations and complete five-ball-set relationships.

### Step 6 — Draw Reconstruction

For every reconstructed observation, retain the complete relationship:

`Total Sum Value → PB Ranking → PB Number → Associated White-Ball Set → Original Historical Draw`

Validate:

`WB1 + WB2 + WB3 + WB4 + WB5 + PB = Parent Total Sum Value`

Each historical draw must remain traceable to its original record.

Reconciliation failures must produce explicit errors rather than silent corrections.

---

## 5. Phase 3 — Ten-Draw Experimental Engine

Implement a generator that constructs exactly ten valid Powerball combinations per experimental cycle.

### Experimental Draws 1–9

1. Identify the highest-frequency Total Sum Value bin.
2. Identify the least frequently occurring qualifying bin from the left tail.
3. Identify the least frequently occurring qualifying bin from the right tail.
4. Allocate nine experimental draws across those three bins using their observed frequencies.
5. Select PB candidates from each bin's retained PB rankings.
6. Construct five-white-ball sets within the White-Ball Chaos framework.
7. Verify each generated six-ball combination satisfies its selected parent Total Sum Value.
8. Ensure all generated six-ball combinations are distinct.

The allocation method must be deterministic, auditable, and documented. Where proportional allocation is underspecified or conflicts with three-bin representation, submit the proposed rule for approval rather than silently inventing it.

Generation must respect normal Powerball constraints:

- Five distinct white balls, numbered 1–69.
- One PB, numbered 1–26.
- No duplicated complete combinations within the ten-draw portfolio.

If a selected bin cannot supply a valid combination, record the constraint failure. Do not silently substitute another bin or alter the requested sum.

### Experimental Draw 10 — Random Control

Generate an independent random control:

- Five unique white balls uniformly sampled without replacement from 1–69.
- One PB uniformly sampled from 1–26.
- No Plinko frequency selection.
- No PB ranking influence.
- No Hot/Cold filtering.
- No sum targeting.

Record the control distinctly as `CONTROL_RANDOM`.

The control must remain methodologically separate from the experimental generator. Use independent random generation and an appropriate source of randomness.

---

## 6. Phase 4 — Preserve Existing Tracking

**Reuse the existing system's tracking methodology. Do not replace it.**

Integrate the new generator with existing tracking interfaces, historical results, reports, and performance evaluation.

Requirements:

- Preserve all previous observations and experimental records.
- Maintain existing identifiers and historical attribution.
- Store the generated ten-draw portfolio before its corresponding real-world drawing.
- Track experimental draws and the random control separately.
- Preserve generation timestamps and the dataset version used.
- Prevent future draw results from influencing previously generated combinations.
- Reuse existing reporting and evaluation metrics.
- Maintain backward compatibility with existing tracking consumers.

Do not change the scoring or outcome-evaluation methodology unless a verified compatibility defect makes a narrowly scoped correction necessary.

New data ingestion must trigger recalculation of the Plinko distributions and rankings without rewriting prior experimental snapshots.

---

## 7. Phase 5 — TagTeam Independent Verification

Use TagTeam as an independent verification mechanism at every major implementation boundary.

### Primary Implementation Agent

Responsible for:

- Investigation and implementation.
- Unit and integration tests.
- Technical documentation.
- Remediation of verified defects.

### TagTeam Verification Agent

Responsible for:

- Independently reviewing implementation against the theory specification.
- Recomputing representative frequency results directly from source data.
- Verifying nested frequency reconciliation.
- Testing tie and outlier handling.
- Verifying white-ball combination integrity.
- Checking all ten generated draws for correctness.
- Confirming control independence.
- Verifying tracking preservation and data isolation.
- Identifying regression risks and undocumented deviations.

The verification agent must not merely repeat the implementing agent's conclusions.

### Required Mathematical Invariants

For every Total Sum Value `S`:

`Sum of all 26 PB occurrence counts within S = Historical frequency of S`

For every PB `P` within `S`:

`Sum of associated individual WB occurrence counts = 5 × Occurrence count of (S, P)`

For every reconstructed or generated draw:

`Sum(WB1...WB5) + PB = S`

For each experimental cycle:

`9 Experimental Draws + 1 Random Control = 10 Valid Draws`

TagTeam must also verify that the experiment uses only historical data available at the generation cutoff.

**Verification status must be evidence-based: PASS, FAIL, or BLOCKED.**

A failed or blocked verification gate prohibits production deployment.

---

## 8. Phase 6 — Clean Room Testing

Complete the following before considering deployment:

1. Unit tests for every mathematical transformation.
2. Independent frequency-reconciliation tests.
3. Boundary tests for minimum and maximum possible sums.
4. Tie-handling and `OUTLIER_TIE` tests.
5. Tests for empty or sparsely populated sum bins.
6. Repeated-ingestion and idempotency tests.
7. Draw-construction validity tests.
8. Control independence tests.
9. Regression tests for existing tracking.
10. End-to-end tests using isolated historical datasets.
11. Reproducibility tests using recorded dataset versions and deterministic test seeds.
12. Leakage tests confirming that future draws cannot influence earlier portfolio construction.

Use independent expected results, exact calculations, or reference fixtures. Do not validate the implementation solely by comparing it against its own outputs.

Report test coverage, failures, and unresolved assumptions.

---

## 9. Phase 7 — Controlled Integration

After clean room development and TagTeam verification:

1. Compare the rebuilt engine against the existing system interfaces.
2. Identify the exact files, components, and configurations requiring changes.
3. Confirm production data and tracking history remain unchanged.
4. Prepare a rollback procedure.
5. Obtain explicit human approval before applying production changes.
6. Deploy only the verified components.
7. Execute post-deployment smoke tests.
8. Confirm normal tracking resumes without historical data loss.

**No unrelated refactoring, dependency upgrades, architecture replacement, or cosmetic changes are authorized.**

---

## 10. Audit Trail and Required Deliverables

Maintain a complete record of the investigation, implementation, verification, and deployment process.

Required artifacts:

- `INVESTIGATION_REPORT.md`
- `DEPENDENCY_GRAPH.md`
- `IMPLEMENTATION_PLAN.md`
- `PLINKO_THEORY_SPEC.md`
- `CLEAN_ROOM_TEST_REPORT.md`
- `TAGTEAM_VERIFICATION_REPORT.md`
- `CHANGE_AUDIT.md`
- `ROLLBACK_PLAN.md`

The change audit must identify:

- Files created and modified.
- Reason for each modification.
- Relevant component dependencies.
- Tests executed and results.
- Verification findings and remediation.
- Remaining limitations.
- Final deployment status.

## 11. Completion Criteria

The project is complete only when:

- [ ] The six-ball Master Plinko distribution is implemented correctly.
- [ ] Sum frequencies are accurately calculated.
- [ ] Nested PB frequencies reconcile with the historical dataset.
- [ ] Dynamic Top 10 PB rankings and tied outliers work correctly.
- [ ] WB Chaos observations preserve the original data relationships.
- [ ] Draw reconstruction passes all mathematical invariants.
- [ ] Nine experimental draws satisfy the approved three-bin allocation.
- [ ] One independent random control is generated.
- [ ] Existing tracking continues without loss of historical records.
- [ ] New ingestion updates rankings without altering past experiment snapshots.
- [ ] Clean Room tests pass.
- [ ] TagTeam independently verifies the implementation.
- [ ] The audit trail and rollback procedure are complete.
- [ ] Human approval is obtained before production deployment.

**Final Directive**

Investigate first. Preserve the current operational system. Build the new Plinko engine in a clean room. Verify each layer independently using TagTeam. Do not invent missing theoretical rules or expand the project's scope.

The Master Plinko Theory is the implementation specification. Historical draw data is the source of truth. All conclusions must be reproducible from the data.

**Do not declare the work complete until implementation, independent verification, tracking compatibility, and audit requirements are satisfied.**