**PlinkoBPMachine Cold-Start MVP · Handoff draft**

### Build sequence

1. **Create the standalone laboratory.** Provide a build entry point, a sandbox preflight entry point, and an experiment entry point. Capture the resolved runtime image identity and sandbox profile. Keep laboratory code and storage separate from the existing application.
2. **Build the controller and deterministic enforcement.** Schedule one container at a time and apply the approved limits below. Bind the launch gate to the independently reviewed candidate fingerprint and preflight-verified profile. Track launch authorization separately from admission after output and lineage checks.
3. **Implement the genomes and validation.** Produce the two required outputs for G1, G2, and G3. Independently recompute expected mathematical rankings and draws. Validate G3’s output and retain the seed and runtime information needed to reproduce it.
4. **Implement the evaluator.** Accept a read-only development snapshot confined to the approved rules and dates. Record its fingerprint and evaluated draw count. Report Top-3 hits, evaluated draws, observed rate, G3’s observed rate, and the theoretical chance rate of \(3/26 \approx 11.54\%\).
5. **Implement evidence and reporting.** Journal the candidate identities, approvals, results, resource use, failures, stop reason, and artifact fingerprints. Preserve lineage in player cards and reference the authoritative records. Support independent retention of the sealed bundle outside the controller’s write access, including for early stops.

### Approved limits

| Scope | Limit |
|---|---|
| Genome attempt | 30 seconds from launch request through output collection |
| Container | 256 MiB memory, one logical CPU’s worth of compute, 32 processes and threads total |
| Output | 64 KiB combined standard output and standard error per attempt |
| Experiment | 10-minute wall-clock budget following passing sandbox preflight |
| Attempts | Three seed executions, one mutation attempt, one crossover attempt. Zero automatic retries. |

On a deadline or output breach, terminate the affected container and confirm exit before dispatching more work. Reject partial outputs. A localized failure allows unaffected authorized work to continue when containment is confirmed. A critical integrity event, unconfirmed containment, or exhaustion of the run budget stops experimental work.

### Verification matrix

| Check | Expected result |
|---|---|
| **Sandbox preflight** | An independent reviewer checks the exact runtime configuration. Controlled fixtures confirm network, filesystem, privilege, and resource restrictions, including cleanup after a forced stop. |
| **Approval binding** | An approval for a different artifact fingerprint or sandbox profile blocks launch. |
| **Acceptance gate** | A valid draw paired with a PB ranking containing a repeated and an omitted number is rejected for both admission and historical scoring. |
| **Evaluator known answer** | Use a small set of actual development-window draws and a fixed complete ranking. The evaluator matches an independently tallied hit count and draw count exactly. |
| **Reproduction checks** | Verify a real coefficient change for mutation and exact module inheritance from both parents for crossover. Validate both outputs from each offspring. |
| **Evidence protection** | Verify append-only access during execution, confirm genome containers lack write access, and validate the closed bundle and its referenced fingerprints. |

A full pass requires valid seed results, both verified offspring, the required gates and evaluator checks, and independently protected evidence. Report failed checks and uncompleted checks explicitly. The build approval covers implementation. Sandbox preflight and the experiment require their established separate authorizations.