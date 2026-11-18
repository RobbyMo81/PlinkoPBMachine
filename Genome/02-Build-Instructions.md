# 02 — Build Instructions & Testing

**PlinkoBPMachine Cold-Start MVP · Pass-3 handoff**

Companions are [01 — Architecture](01-Architecture.md) and [03 — Loop Workflow Instructions & Independent AI Reviewer](03-Loop-Workflow.md). Document 01 defines the approved contracts and authority. Document 03 defines the execution sequence.

## Build instructions

1. **Set up the standalone laboratory.** Configure an absolute lab root and the absolute roots of both PlinkoBPMachine and PBMachine. Resolve the actual target paths, including symlinks, Windows junctions, and other path-redirecting reparse points, before testing disjointness. Block setup if a path cannot be resolved or either project tree overlaps the lab root. Provide distinct build, preflight, and experiment entry points. Keep configuration, run working files, and authoritative evidence separate. Use a UUID for the run ID, the five fixed slot IDs in Document 01, and stable IDs for candidates and checks. Keep retained evidence outside the controller’s write access.
2. **Enforce both authorization layers.** Read stage authorization from the authenticated, owner-controlled source. Verify the experiment record names exactly the five Document 01 slots. The gate derives each launch approval within its named slot after verifying the required pre-launch evidence and the Critical Verifier’s decision. Bind the approval to the parent authorization, run, slot, attempt, executable-artifact fingerprint, pinned image digest, profile, and passing preflight. Verify those bindings at launch. Durably consume the approval before requesting launch. Consumption survives restarts and launch failures. An approval expires at the run deadline, run close, or preflight invalidation, whichever comes first.
3. **Implement genome outputs and deterministic checks.** Implement the seed contracts and verify mathematical outputs by independently recomputing the expected ranking and draw. Validate types, pool ranges, uniqueness, rank completeness, and mathematical selection. For mutation, compare the canonical G2 record with the offspring and verify the shared linear coefficient is the only change. For crossover, compare each inherited slot fingerprint directly with the designated verified parent’s slot. Check functional output and lineage before admission.
4. **Implement the journal and evidence handoff.** Give the dedicated writer its own identity and exclusive write permission. Expose an authenticated append interface to the controller and Validator. Deny their direct overwrite, truncate, and delete access. Deny genome containers both journal and interface access. Record authorization references, image and candidate fingerprints, timings, resource use, failures, cleanup, and artifact references. Derive player cards and the final report from journaled evidence. At close the reviewer verifies and retains the bundle independently.
5. **Implement the snapshot interface and evaluator.** Use the snapshot procedure below. Report seed hits, verified draw count, rates, G3’s observed control rate, chance rate (3/26), expected hits, and standard deviation. Under the fair independent-draw model, expected hits are N × 3/26 and standard deviation is √[N × (3/26) × (23/26)]. Keep comparisons descriptive. The same verified development draws apply to all three seeds and controlled validation precedes historical scoring.
6. **Connect the Independent Resource Controller (IRC).** The scheduler requests work and obeys IRC decisions. The IRC starts the run clock when the owner-authorized run opens after passing preflight. It owns the run, AI-interaction, and container deadlines and the combined output byte cap. Apply effective container CPU, memory, and process limits before execution and verify the match against the preflighted profile. Bound each AI interaction by the earlier of its 90-second deadline and the run deadline. Discard late AI responses and journal the phase that timed out. On a container breach, the IRC stops the attempt through the runtime and confirms exit before permitting further work. Journal effective limits, usage, breaches, stop requests, and exit confirmation.

## DNA serialization and known-answer fixture

Serialize DNA as compact UTF-8 JSON, with object keys sorted lexicographically at every level, integer parameters in base 10, and no optional whitespace, byte-order mark, or trailing newline. The top-level keys are `pb`, `version`, and `white_balls`, with integer version `1`. Each slot contains `family` and `parameters`. Use `modular` with `a`, `b`, `m` or `quadratic` with `a`, `b`, `c`. The structural projection omits the `parameters` properties. Hash the exact serialized bytes with SHA-256 and record lowercase hexadecimal digests.

| Fixture | Exact UTF-8 content, excluding the surrounding code formatting | Expected SHA-256 |
|---|---|---|
| G1 module | `{"family":"modular","parameters":{"a":5,"b":7,"m":29}}` | `28e89e68cf94eb68a1ae0b76c3902896f465002133ae47b43e343bd95e160304` |
| G1 full DNA | `{"pb":{"family":"modular","parameters":{"a":5,"b":7,"m":29}},"version":1,"white_balls":{"family":"modular","parameters":{"a":5,"b":7,"m":29}}}` | `4c7a907d6274c9e8c5cda398e7a9c9faf99edc98a01fa7bcc31a555a73e2328f` |
| G1 structural | `{"pb":{"family":"modular"},"version":1,"white_balls":{"family":"modular"}}` | `47ad724100ae543359e4fb9bb9693d4bf0be34add8eebdfe07f0bcc54983d0fa` |
| G2 module | `{"family":"quadratic","parameters":{"a":-2,"b":37,"c":11}}` | `7d7655262fc5e4b30d34a30619b3135c93ba9a30534d5867d64aed9692335329` |
| G2 full DNA | `{"pb":{"family":"quadratic","parameters":{"a":-2,"b":37,"c":11}},"version":1,"white_balls":{"family":"quadratic","parameters":{"a":-2,"b":37,"c":11}}}` | `98d95c34cee3014a7d16732a34c38d0bebc21c007f477fae6a75fd2f50308942` |
| G2 structural | `{"pb":{"family":"quadratic"},"version":1,"white_balls":{"family":"quadratic"}}` | `fb3b43de3b2d77af2c77f78fe648c5c941d6d3a40e7fb8fedfd329a34523b8fd` |
| Mutation 36 module | `{"family":"quadratic","parameters":{"a":-2,"b":36,"c":11}}` | `ffa7428e5312503d0276f51158b45dbb02899e8e8cf1b4068674b6cb0d52646a` |
| Mutation 38 module | `{"family":"quadratic","parameters":{"a":-2,"b":38,"c":11}}` | `79e664ba36b4107abb9b6feda26b3aa317346dfed07429025cbcd22ce5e7c62e` |
| Crossover G1 PB + G2 whites | `{"pb":{"family":"modular","parameters":{"a":5,"b":7,"m":29}},"version":1,"white_balls":{"family":"quadratic","parameters":{"a":-2,"b":37,"c":11}}}` | `3e09d28c62106c0a7e045d7ed3c02c0afad298818e87fdc42c27dadc2017c8a5` |
| Crossover G2 PB + G1 whites | `{"pb":{"family":"quadratic","parameters":{"a":-2,"b":37,"c":11}},"version":1,"white_balls":{"family":"modular","parameters":{"a":5,"b":7,"m":29}}}` | `9a9ebfbe3477d0b6756b627a52d38661d88dccee033d83a8513b206447d112ad` |

## Snapshot procedure

- Before the timed run, the trusted snapshot preparer uses its dedicated authenticated identity and verifies the owner’s approved absolute canonical-source path and development window. Open SQLite using `mode=ro` and `PRAGMA query_only`. Use `Connection.backup` to create a consistent staging copy outside the lab’s access. The preparer retains custody of that copy, which may contain protected records. The canonical store remains read-only.
- Count accepted 5/69 + 1/26 draws in the inclusive development window. Require one record per draw date, five distinct integer white balls in 1–69, and one integer PB in 1–26. Treat whites as unordered. Stop publication if there are duplicate dates or invalid records and record the discrepancy.
- Compare the eligible count and deterministic digest of the same canonical development rows across the source before backup, staging copy, source after backup, and final immutable export. Publish only on agreement. Authenticate the publication record under the preparer’s identity and include the owner authorization reference, provenance, dates, count, digest, and fixture identity. The evaluator receives the full development export and rechecks the count and fingerprint against that record before scoring.
- Expect **1,297 eligible development draws**, the count the pass-2 reviewer found in all five snapshots. Verify each export. If the development count differs, record and reconcile it before scoring. The verified export supplies the denominator. The two rows added since the 1,431-draw baseline were the November 11 and 14, 2026 draws. Holdout counts are snapshot-specific and stay outside the evaluator.
- The preparer publishes the small read-only fixture with actual development PB outcomes, draw dates, source snapshot fingerprint, and its own fingerprint. The reviewer records the expected hit count and denominator for the pinned ranking before seeing evaluator results. The Validator submits the same ranking and draw sample to the evaluator and checks exact agreement. Only the evaluator receives the complete development export.

### EVAL-01 pinned input

G1’s complete PB ranking is `[10, 4, 21, 15, 9, 3, 26, 20, 14, 8, 2, 25, 19, 13, 7, 1, 24, 18, 12, 6, 23, 17, 11, 5, 22, 16]`. Use these literal values for the tally and evaluator test. Record the sample dates, fixture fingerprint, and expected hit count and denominator together.

## Limits and test evidence

| Scope | Approved bound |
|---|---|
| Genome attempt | 30 seconds from requested launch through output collection |
| Container | 256 MiB memory, one logical CPU’s compute, 32 processes and threads total |
| Output | 64 KiB combined stdout and stderr per attempt |
| Run | 25 minutes from the IRC opening the authorized run after passing preflight |
| In-run AI interaction | At most 90 seconds, bounded by the remaining run time |
| Reproduction | One proposal request per branch, up to one launch per approved proposal, zero automatic retries |

Budget up to 13 in-run AI interactions at 90 seconds each and five container attempts at 30 seconds each. That allocates 22 minutes and leaves 3 for scoring and coordination. Preparation and preflight precede the run. Confirm containment and seal evidence after stopping even if the deadline has passed.

## Deterministic check catalog

Use the check IDs in approval and evidence records. Identify the exact run, attempt, and artifact for candidate checks and the exact image and profile for preflight checks.

| Check ID | Pass criteria |
|---|---|
| `PF-ISO` | The pinned runtime image and exact profile are verified. Controlled fixtures confirm network, filesystem, and privilege restrictions and demonstrate that the approved runtime can start and return output. |
| `PF-IRC` | Controlled fixtures demonstrate effective CPU, memory, and process limits, AI and container deadlines, output cap, run dispatch cutoff, and exit confirmation after termination. Record measured results and stop reasons. |
| `PF-JRN` | Controlled fixtures show agents and the controller cannot rewrite the journal, genome containers cannot access the journal or append interface, and the reviewer’s retained copy is outside the controller’s write access. |
| `PF-GATE` | Controlled checks accept matching delegated authority once per slot and block untrusted owner records, unknown or reassigned slots, stale or mismatched preflight, mismatched artifacts or profiles, and consumed approvals. Use controlled inputs without real genome launches. |
| `PF-DNA` | All ten canonical fixture hashes match their expected digests. |
| `PF-OUTPUT` | A valid draw paired with a duplicate-and-omission PB ranking is rejected for admission and historical scoring. |
| `CAND-ART` | Before candidate review, independently fingerprint the executable artifact and validate its declared inputs and DNA record against the applicable seed or branch contract. Confirm the runtime bindings. |
| `CAND-LINE` | For offspring, independently compare the candidate DNA with verified parents. Enforce the approved G2 change or compare both inherited module fingerprints against the declared donor slots. |
| `RUN-OUTPUT` | After execution, validate the complete ranking and draw. Independently recompute both outputs for mathematical candidates. Confirm that reported parentage and executable identity match the approved candidate. |
| `DATA-01` | At publication, the authenticated preparer confirms all four eligible-row counts and digests agree and validates the export boundary and expected development count. Before scoring, the evaluator independently recounts and rehashes the export, checks the boundary, and matches the trusted publication record. |
| `EVAL-01` | The evaluator exactly matches the independently recorded hit count and denominator for G1’s pinned permutation and the authenticated development fixture before any historical score is computed. |
| `CLOSE-01` | Reconcile terminal container state, run-owned cleanup, journal entries, and artifact fingerprints. Record protected independent retention before overall PASS. |

For either permitted mutation, expect the same Top-3 set `{8,9,10}` and draw `{7,8,9,10,11} + PB 9` as G2. Check exact rankings against the chosen coefficients. Shared sets or draws do not cause a mutation failure.

Build implementation is approved. Perform controlled sandbox preflight and the experiment only when their respective owner authorizations take effect. Terminal verdicts are defined in Document 03.
