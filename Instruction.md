# AI Agent Implementation Directive
## Powerball Master Plinko — PB Hit-Rate Experimental Engine

**Project:** `C:\Users\RobMo\PlinkoPBMachine`

**Mission:** Rebuild the existing Powerball generation and analysis engine around the approved Master Plinko Theory, prioritizing the measurement of Powerball (PB) hit rates.

**Engineering methodology:** Clean Room Development  
**Verification methodology:** Independent TagTeam Review  
**Application memory:** `Master_Build_Journal.md`  
**Governing policy:** `Clean_Room_Policy.md`

**Status:** Implementation authorized within the Clean Room. Production changes require separate human approval.

---

# 1. Primary Objective

Build a continuously updating, data-driven Powerball experiment that:

1. Calculates the Master Plinko distribution using the sum of all six balls.
2. Ranks Total Sum Values by observed frequency and recency.
3. Selects the Top 3 ranked Master Sum Values.
4. Calculates nested PB frequency rankings within each selected sum.
5. Selects the Top 3 ranked PBs per selected sum.
6. Constructs nine experimental tickets from those nine Sum/PB pairs.
7. Applies the WB Chaos Theory without inventing unsupported predictive rules.
8. Limits white-ball overlap between experimental tickets.
9. Generates one independent random control ticket.
10. Measures the PB hit rate of the experimental portfolio against actual future draws.

**Primary measurement: PB Hit Rate.**

Secondary measurements may include white-ball matches, prize outcomes, distribution movement, and ranking stability, using the existing tracking infrastructure.

The objective is to measure the theory's performance, not assume that historical frequencies predict future outcomes.

---

# 2. Mandatory Phase 0 — Investigate Before Implementing

Perform read-only investigation of the current application.

Discover and document:

- Existing draw ingestion and validation.
- Historical data storage and schemas.
- Sum calculations and frequency-ranking implementations.
- PB and white-ball analysis modules.
- Existing ticket generator and control logic.
- Experimental tracking and reporting.
- Dashboard, scheduled tasks, and CLI entry points.
- Existing TagTeam verification infrastructure.
- Dependency graph and data flow.

Identify components requiring modification and components that must remain untouched.

Run baseline tests where they can execute without altering production state.

**Do not assume that an existing function, script, or capability works merely because it exists. Verify its behavior.**

Required investigation deliverables:

- `INVESTIGATION_REPORT.md`
- `DEPENDENCY_GRAPH.md`
- `IMPLEMENTATION_PLAN.md`

Record findings and decisions in `Master_Build_Journal.md`.

### Gate 0 — TagTeam

Independent TagTeam verification must confirm the investigation, dependency boundaries, and proposed change scope before implementation.

---

# 3. Mandatory Clean Room Procedures

All code, scripts, design changes, CLI operations, dependency installations, and test execution must comply with `Clean_Room_Policy.md`.

## 3.1 Source Code

- Create an isolated worktree or working copy.
- Record baseline commit IDs and source hashes.
- Modify only approved components.
- Keep production source untouched during development.
- Use incremental changes with testable boundaries.
- Preserve existing public interfaces unless an approved change requires otherwise.
- Do not perform unrelated refactoring.

## 3.2 Scripts

Before executing a script:

1. Inspect its source and intended behavior.
2. Identify filesystem, database, network, and subprocess side effects.
3. Confirm it targets the isolated workspace.
4. Verify required dependencies and environment variables.
5. Execute with least-privilege permissions.
6. Capture exit codes, errors, and affected artifacts.
7. Verify the resulting application and data state.

Unreviewed or destructive scripts must not execute against production.

## 3.3 Architectural Design

Before implementation, document affected layers, their connections, downstream consumers, and recovery implications.

Preserve the existing tracking infrastructure wherever compatible.

Do not replace a working subsystem merely to simplify implementation.

## 3.4 CLI Execution

Use verified CLI capabilities only.

Before state-changing commands, confirm:

- Working directory.
- Target environment.
- Exact command.
- Expected side effects.
- Permissions.
- Rollback or recovery path.

Do not execute unrestricted deletion, global dependency changes, production database modifications, or privileged commands without appropriate approval.

Subagents and TagTeam reviewers are subject to the same controls.

## 3.5 Historical Data

- Use isolated copies of historical datasets.
- Preserve original draw records.
- Record source versions and checksums.
- Validate new draw ingestion.
- Detect duplicate or inconsistent draw records.
- Never silently rewrite past observations.
- Recalculate current rankings when new records arrive.
- Preserve historical snapshots of previously generated portfolios.

**Clean Room completion is a prerequisite for production integration, not permission to deploy.**

---

# 4. Implement Master Plinko Distribution

## 4.1 Six-Ball Sum

For each historical draw calculate:

`TOTAL_SUM = WB1 + WB2 + WB3 + WB4 + WB5 + PB`

The PB must be included.

Do not revert to a five-white-ball-only sum.

## 4.2 Frequency Distribution

Group historical draws by exact `TOTAL_SUM`.

Calculate:

`SUM_FREQUENCY(S) = number of historical draws with TOTAL_SUM = S`

Retain every mathematically possible sum bin, including bins with zero observed occurrences.

Visualize the complete distribution using:

- X-axis: Six-ball Total Sum Value.
- Y-axis: Historical occurrence frequency.

The observed distribution defines the Master Plinko curve.

### Mathematical invariants

For the current Powerball format:

- Five distinct white balls from 1–69.
- One PB from 1–26.
- Minimum Total Sum: 16.
- Maximum Total Sum: 361.

Validate these bounds against the applicable historical game rules before combining records from different Powerball formats.

The sum of all bin frequencies must equal the number of accepted historical draws.

---

# 5. Master Plinko Top 10 Rankings

Rank observed Total Sum Values using:

**Primary criterion:** Historical frequency, descending.

**Secondary criterion:** Most recent official draw date associated with the sum, descending.

Retain the Top 10 ranked sums.

Zero-frequency bins remain in the Master Plinko distribution but are not treated as observed ranking candidates.

When frequencies tie, the more recently occurring sum takes precedence.

The timestamp used for recency must be the official drawing date, not the ingestion date.

If frequency and official draw date both tie, retain an explicit unresolved tie and use only an approved deterministic resolution rule. Do not invent a meaningful ranking difference.

Every ranking must preserve:

- Total Sum Value.
- Observed frequency.
- Last observed draw date.
- Current rank.
- Dataset version.

Recalculate rankings whenever new verified historical data is ingested.

**The Top 10 is a dynamic ranking, not a permanent filter on historical data.**

---

# 6. Select the Top 3 Master Sum Values

From the Master Plinko Top 10 ranking, select ranks 1, 2, and 3.

Each selected sum contributes three experimental tickets.

This establishes:

- Master Sum Rank 1 → Tickets 1–3.
- Master Sum Rank 2 → Tickets 4–6.
- Master Sum Rank 3 → Tickets 7–9.

**Do not use the previous left-tail, center-peak, or right-tail ticket allocation algorithm.**

The current approved allocation is:

`3 MASTER SUMS × 3 PB SELECTIONS = 9 EXPERIMENTAL TICKETS`

---

# 7. Nested Powerball Frequency Rankings

For each of the three selected Master Sum Values:

1. Retrieve every historical draw associated with that exact Total Sum Value.
2. Extract its PB.
3. Count occurrences of PB values 1–26.
4. Calculate the PB frequency distribution.
5. Rank PBs by descending observed frequency.
6. Use most recent official occurrence as the secondary ranking criterion.
7. Maintain the complete PB frequency distribution and Top 10 PB ranking.
8. Select the Top 3 ranked PBs for ticket construction.

Preserve the frequency-set relationships and tie information for analysis, even when deterministic recency ranking resolves a selection boundary.

### PB frequency invariant

For each Total Sum Value `S`:

`SUM(PB_FREQUENCY(S, PB=1..26)) = SUM_FREQUENCY(S)`

TagTeam must independently verify this invariant.

---

# 8. Nine Experimental Ticket Assignments

Use this structure:

| Ticket | Master Sum | PB Selection |
|---|---|---|
| 1 | Master Sum Rank 1 | PB Rank 1 |
| 2 | Master Sum Rank 1 | PB Rank 2 |
| 3 | Master Sum Rank 1 | PB Rank 3 |
| 4 | Master Sum Rank 2 | PB Rank 1 |
| 5 | Master Sum Rank 2 | PB Rank 2 |
| 6 | Master Sum Rank 2 | PB Rank 3 |
| 7 | Master Sum Rank 3 | PB Rank 1 |
| 8 | Master Sum Rank 3 | PB Rank 2 |
| 9 | Master Sum Rank 3 | PB Rank 3 |
| 10 | Independent control | Random PB |

Duplicate PB numbers across experimental tickets are permitted.

For each experimental ticket, preserve its assigned Master Sum and PB.

Calculate the required white-ball sum:

`REQUIRED_WB_SUM = MASTER_SUM - SELECTED_PB`

Every completed ticket must satisfy this relationship.

---

# 9. White-Ball Chaos Theory

The WB Chaos Theory remains the approved observational framework.

For each selected Sum/PB pair:

- Retrieve associated historical five-white-ball sets.
- Count individual white-ball occurrences.
- Analyze odd/even distribution.
- Observe Hot, Neutral, and Cold frequency characteristics where definitions exist.
- Preserve observed five-ball combinations.
- Examine possible relationships without requiring a pattern to exist.

**Do not manufacture correlations, impose an assumed distribution, or claim that the observations establish predictive power.**

The final WB Chaos selection algorithm remains open for further research.

### Interim generation policy

Ticket generation must remain operational.

Until a distinct WB Chaos selection algorithm is approved, use an explicitly identified **provisional, unbiased selection method** that constructs valid five-white-ball combinations satisfying the selected Sum/PB pair and the overlap constraints below.

The provisional method must not be represented as a validated WB Chaos predictive algorithm.

Document the sampling method, randomness source, constraints, and implementation decision in the Master Build Journal.

TagTeam must independently verify that the provisional method introduces no undocumented weighting or preference.

If the application already has a compatible, approved white-ball generator, investigate whether it can serve as the provisional mechanism before building a replacement.

---

## Amendment — Complete WB Chaos Integration in Current Build Cycle

**Priority:** Mandatory  
**Implementation cycle:** Current  
**Status:** Approved for Clean Room development

The agent must implement the WB Chaos observation engine and provisional white-ball generator during the current build cycle.

### Requirements

1. Analyze historical white-ball frequencies associated with each selected Master Sum/PB pair.
2. Preserve Hot, Neutral, Cold, Odd, and Even observations without imposing unsupported predictive patterns.
3. Generate valid five-white-ball combinations satisfying the assigned Total Sum Value minus the selected PB.
4. Enforce the maximum two-white-ball overlap restriction across experimental Tickets 1–9.
5. Preserve duplicate PB selections when produced by the rankings.
6. Generate Ticket 10 independently as the random control.
7. Integrate all ten tickets with the existing tracking system.
8. Record PB hit rates separately for experimental tickets and the control.

### Clean Room and TagTeam Requirements

- Implement and test the generator in the isolated Clean Room.
- Verify mathematical constraints and ticket validity.
- Independently reproduce results through TagTeam.
- Document the provisional white-ball selection procedure.
- Record all decisions, code modifications, tests, and verification results in `Master_Build_Journal.md`.

### Completion Gate

The current build cycle is **not complete** until the system can generate ten tickets, enforce all approved constraints, and track their PB hit rates.

Do not defer generator integration to a future cycle.

Do not represent the provisional white-ball generator as a validated predictive model.

Production deployment remains subject to separate human approval.

---

# 10. Mandatory White-Ball Overlap Restriction

**Applies exclusively to experimental Tickets 1–9.**

Each experimental ticket must contain five distinct white balls.

For any two experimental tickets, a maximum of two white-ball numbers may appear in both sets.

Formally:

`COUNT(INTERSECTION(WB_SET_A, WB_SET_B)) <= 2`

The system must verify all 36 unique pairwise comparisons among the nine experimental tickets.

Examples:

- Zero shared white balls: PASS.
- One shared white ball: PASS.
- Two shared white balls: PASS.
- Three shared white balls: FAIL.
- Four shared white balls: FAIL.
- Five shared white balls: FAIL.

### Powerball duplicates

PB duplication is allowed when separate ranked selections identify the same PB number.

The overlap restriction applies to white-ball values only.

### Constraint resolution

Use a bounded, auditable construction procedure that searches for valid sets without modifying assigned Master Sum/PB pairs.

The generator must detect unsatisfiable constraints and report structured errors.

Do not silently change selected sums, PB rankings, overlap limits, or historical observations to force success.

The search procedure, retry limit, and failure response must be documented and verified.

---

# 11. Ticket 10 — Independent Random Control

Generate an independent random Powerball ticket:

- Five distinct white balls uniformly selected from 1–69.
- One PB uniformly selected from 1–26.
- No Master Plinko sum targeting.
- No PB frequency ranking influence.
- No WB Chaos selection influence.

Ticket 10 is exempt from the two-white-ball overlap rule.

Do not modify the control to match experimental constraints.

If the control duplicates an experimental ticket, preserve and record the collision instead of silently regenerating it.

The control is a baseline for longitudinal comparison.

---

# 12. Primary Experimental Metric — PB Hit Rate

The central purpose of the rebuilt system is to observe the PB hit rate.

For each actual future Powerball drawing:

1. Retrieve the nine experimental PB selections stored before that drawing.
2. Retrieve the independently selected control PB.
3. Compare each selected PB against the official drawn PB.
4. Record ticket-level matches.
5. Record whether at least one experimental ticket matched the PB.
6. Record the number of distinct PB values covered.
7. Compare the experimental group against the control.
8. Append the results to the existing tracking infrastructure.

### Required measurements

**Experimental PB coverage hit rate**

`DRAW_HIT_RATE = Draws with >=1 experimental PB match / Total evaluated draws`

**Ticket-level PB hit rate**

`TICKET_PB_HIT_RATE = Total matching experimental ticket PBs / Total experimental ticket opportunities`

**Control PB hit rate**

`CONTROL_PB_HIT_RATE = Control PB matches / Total evaluated draws`

Track these as separate metrics.

Nine PB selections may contain duplicates. Do not confuse nine assignments with nine distinct PB values.

Also calculate and report the theoretical random PB-coverage baseline based on the number of unique experimental PB selections.

The system must not confuse a PB match with a paid prize. Prize outcomes require separate official prize-tier evaluation.

### Historical integrity

Every portfolio must be generated and recorded before the drawing against which it is evaluated.

Do not use future outcomes to construct historical predictions.

Retrospective analysis must be distinguished from prospective experimental results.

---

# 13. Preserve Existing Tracking and Reporting

Reuse the current application's tracking system.

Maintain:

- Existing experiment records.
- Historical draw results.
- Performance measurements.
- Existing reporting formats where compatible.
- Dashboard functionality.
- Data-ingestion schedules.
- Historical attribution.

Extend tracking only where required to record the new Master Plinko configuration.

Every experimental cycle must record:

- Cycle identifier.
- Target drawing date.
- Generation timestamp.
- Dataset version.
- Master Top 10 Sum rankings.
- Selected Top 3 Sum Values.
- Nested PB rankings.
- Nine experimental Sum/PB assignments.
- Generated white-ball sets.
- Pairwise overlap verification.
- Independent control ticket.
- Actual draw result.
- PB hit-rate measurements.
- TagTeam verification status.

Previously generated portfolios must remain immutable.

---

# 14. Independent TagTeam Verification

TagTeam must independently verify each layer.

### Verification targets

**Master Plinko**
- Correct six-ball sum calculations.
- Complete sum frequency distribution.
- Correct total record reconciliation.

**Master rankings**
- Frequency-first ordering.
- Recency tie-breaking.
- Correct Top 10 and Top 3 selection.

**PB analysis**
- Correct nested PB counts.
- Ranking accuracy.
- Correct selection of three PBs per Master Sum.

**WB Chaos**
- Correct source records and frequencies.
- No unsupported predictive assertions.
- Valid constructed white-ball combinations.

**Experimental tickets**
- Exactly nine Sum/PB assignments.
- Correct sum reconciliation.
- Valid Powerball numbers.
- Maximum two shared white balls between any two experimental tickets.
- Permitted duplicate PBs.

**Control**
- Independent generation.
- No application of experimental filters.

**Tracking**
- Correct PB hit-rate calculations.
- No historical data loss.
- No future-data leakage.
- Correct separation of experimental and control performance.

A verification failure must be recorded and resolved before integration.

---

# 15. Master Build Journal — Mandatory Agent Memory

`Master_Build_Journal.md` is the single authoritative document for the application's engineering memory.

All participating agents must consult it before beginning work and update it at required workflow boundaries.

Record:

1. Current application state.
2. Approved theory and selection rules.
3. Investigation findings.
4. Architecture and dependency decisions.
5. Implementation plans.
6. Source modifications.
7. Script and CLI execution.
8. Tests and results.
9. TagTeam findings.
10. Defects and remediation.
11. Unresolved decisions.
12. Human approvals.
13. Integration and rollback outcomes.

Use unique entry identifiers, timestamps, responsible agents, and references to supporting evidence.

**Do not silently change previous decisions.**

Superseded decisions must retain their history and identify the replacement decision.

Keep detailed logs and generated evidence in supporting artifacts, referenced from the journal. The journal remains the authoritative index and decision record.

---

# 16. Implementation Acceptance Criteria

The implementation must demonstrate:

- [ ] Accurate six-ball Master Plinko distribution.
- [ ] Complete preservation of all sum bins.
- [ ] Correct frequency/recency rankings.
- [ ] Top 3 Master Sum selection.
- [ ] Top 3 PB selection per Master Sum.
- [ ] Nine valid experimental Sum/PB assignments.
- [ ] WB Chaos observation and provisional generation correctly separated.
- [ ] No more than two shared white balls between any two experimental tickets.
- [ ] Duplicate PB numbers accepted.
- [ ] Independent Ticket 10 control.
- [ ] Valid PB hit-rate tracking.
- [ ] Historical experiment records preserved.
- [ ] Continuous ingestion and ranking recalculation.
- [ ] Clean Room tests completed.
- [ ] Independent TagTeam verification completed.
- [ ] Master Build Journal updated.
- [ ] Production integration approved by the human operator.

---

# 17. Execution Instructions

Proceed through the following controlled stages:

**Stage 0:** Investigate existing application and current tracking system.

**Stage 1:** Establish and verify Clean Room isolation.

**Stage 2:** Implement and independently verify Master Plinko sum calculations and rankings.

**Stage 3:** Implement nested PB frequencies and rankings.

**Stage 4:** Integrate WB Chaos observations and the provisional white-ball generator.

**Stage 5:** Implement the nine experimental tickets and two-white-ball overlap enforcement.

**Stage 6:** Implement the independent random control.

**Stage 7:** Integrate PB hit-rate measurements with existing tracking.

**Stage 8:** Run independent TagTeam verification and regression testing.

**Stage 9:** Prepare the deployment plan, rollback procedure, and final audit.

**Stage 10:** Obtain explicit human approval before production integration.

## Final Engineering Guardrails

- Do not reinterpret the Master Plinko Theory.
- Do not restore the superseded left-tail/center/right-tail generator.
- Do not invent predictive white-ball patterns.
- Do not claim a mathematical advantage without supporting calculations.
- Do not silently resolve unapproved design decisions.
- Do not modify unrelated application components.
- Do not bypass Clean Room restrictions through scripts, CLI commands, subprocesses, or delegated agents.
- Do not fabricate TagTeam results.
- Do not alter historical experiments.
- Do not replace the existing tracking methodology without approval.
- Do not claim successful completion without verified implementation evidence.

**Start with read-only discovery, verify the architecture, and then rebuild the required components in the Clean Room.**

**Every engineering decision and state transition must be recorded in `Master_Build_Journal.md`.**