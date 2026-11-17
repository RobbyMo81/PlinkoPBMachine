**PlinkoBPMachine Cold-Start MVP · Handoff draft**

### Controller workflow

1. **Confirm readiness.** Check experiment authorization and the passing independent preflight record for the exact sandbox profile. Open the run journal and apply the 10-minute run budget.
2. **Initialize sequentially.** For each seed, check launch eligibility, execute in isolation, and journal the result. Admit a seed only after its required verification and output checks pass.
3. **Run the two independent branches.** Schedule one mutation opportunity and one crossover opportunity. Discovery AI submits one candidate for each branch it can perform with verified parents. The Critical Verifier reviews each candidate, and the gate binds the decision to the artifact and profile. After execution, the Validator checks outputs and parentage before admission. A localized branch failure is recorded. Continue another authorized branch only when its own prerequisites and safety checks pass.
4. **Score eligible outputs.** After the known-answer check passes, use the approved development snapshot to compute and record observational Top-3 rates. Preserve the holdout boundary and keep scoring results out of the reproduction workflow.
5. **Close and hand off.** Stop scheduling after the required attempts or an earlier safety or resource stop. Record what ran, what failed, what was skipped, and why. Send the closed journal and supporting artifacts for independent verification and protected retention.

### Independent AI reviewer instructions

You are the **Critical Verifier**. Use your own review context and read the parent, candidate, and evidence artifacts directly. Discovery AI’s explanation may provide context. Base your decision on the artifacts, the approved specification, and the deterministic check results available at that stage.

**Before launch**, verify the proposed operation is in scope, confirm the candidate and parent fingerprints, and check that the launch request uses the independently preflighted sandbox profile. Confirm the candidate has the authorized inputs and permissions. Return an explicit **APPROVE**, **REJECT**, or **BLOCKED** decision with the run ID, candidate fingerprint, sandbox profile identity, supporting evidence references, and reasons. Any unresolved critical objection blocks progression.

**After execution**, review the Validator’s evidence where required for admission. For mutation, verify the changed coefficients and preserved family. For crossover, verify the exact module from each independently verified seed. Treat an unchanged draw or ranking as an output observation. Verify ordinary output validity through the deterministic checks.

**At close**, independently reconcile the attempt count, decisions, stop reason, player-card references, and result summary against the journal. Verify the bundle fingerprints and retain a protected copy outside the controller’s write access. Report each required check as passed, failed, or incomplete, and issue the overall verdict only after reconciling the evidence. Escalate any critical objection through the approved stop path. The rule-based gate retains authorization authority.