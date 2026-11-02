# Revisit Plan — Master Plinko PB Hit-Rate Experiment

**Created:** 2026-10-30 20:05 PT (2026-10-31 03:05 UTC)
**Owner decision context:** Rob reviewed the WORK-0007 directive verdict and said
"save this thought so that we can revisit this later" (2026-10-30). This file is
the saved thought: what we concluded, what remains open, and the exact
conditions under which we revisit.

## What we concluded (the saved assessment)

1. **The build is sound as a measurement instrument.** Clean-room 3x3 engine,
   isolated tracker, no backdating, fail-closed constraints, uniform WB
   sampling, experimental-vs-control separation. 25 tests PASS. It measures
   honestly; it does not (and cannot) predict.
2. **The theory's honest expectation is the null.** Historical PB frequencies
   nested inside six-ball sum bins have no mechanism to influence future
   draws; prior verified work (bin-invariance proof, 2M-draw Monte Carlo,
   hot/cold shaping null results, Oct 24-25 findings) found exactly this class
   of signal to be zero. The experiment is worth running BECAUSE it generates
   longitudinal evidence against a control — not because we expect an edge.
3. **One design cost noted (not a defect):** the 3x3 structure permits
   duplicate PBs across the nine assignments, so distinct-PB coverage
   self-varies by cycle (u unique PBs -> u/26 draw-level coverage) and
   comparison against the center-zone 10-distinct-PB play is
   coverage-confounded. The tracking design handles this correctly via the
   distinct-count baseline (unique/26).

## The pending measurement (first empirical window)

- Isolated cycle WORK-0007-20261030T051624: 10 tickets (9 experimental + 1
  control), recorded 2026-10-30 05:16 UTC, targeting the Saturday 2026-10-31
  draw. Zero evaluations yet (pending the official draw).
- The real-money center-zone play (10 tickets, books CSV, $20) is separate
  and unaffected by this experiment.

## Statistical power (computed 2026-10-30, scratch/plinko_revisit_power.py)

Null hypothesis: each of the 9 experimental assignments hits PB with
p0 = 1/26 per draw; control 1/26. Two-proportion test, 95% confidence,
80% power:

| True effect | Assignments needed | Draws (9/draw) | Time at 3 draws/week |
|---|---|---|---|
| 2.0x hit rate | 576 | 64 | ~4.4 months |
| 1.5x hit rate | 1,941 | 216 | ~1.4 years |
| 1.2x hit rate | ~12,000 | ~1,330 | ~8.5 years |

One year of data (156 draws, 1,404 assignments) yields a null expectation
of 54 hits with SD 7.2 — a 1-year result must be roughly 2x the null
expectation before it is even 2-sigma interesting. Anything shorter is
noise-hunting.

## Revisit triggers (any one)

1. **Scheduled:** after ~64 recorded draws (~Feb-Mar 2027) — enough power to
   detect a doubled hit rate. Run the formal two-proportion test then.
2. **Early look:** after ~20 draws, check only for gross anomaly (observed
   experimental hits >2 SD above the distinct-PB baseline), with the
   multiple-looks caveat honestly noted.
3. **Owner request:** Rob asks "where does the Plinko experiment stand" —
   report current hits vs baseline with the power table above.
4. **First evaluation window:** after the 2026-10-31 draw closes, evaluate
   the pending cycle, compute the first draw's PB hit-rate record, and
   append the journal event (this is the journal's stated next action).

## Standing verdicts that must not be re-litigated without new evidence

- Tier odds are bin-invariant (proven; cancellation + Monte Carlo).
- Hot/cold and sum shaping have zero win-probability effect (verified null).
- The center-zone pivot (2026-10-29) governs the real-money plays.
- This experiment measures; it does not license "prediction" language.

## Blocked gates to resolve when revisiting

- Independent EXECUTABLE TagTeam verification (reviewer sandbox denied
  Python/SQLite; inspection-only PASS was recorded — do not mislabel).
- OS-level read-only ACL isolation for the reference DB.
- Production integration remains human-gated, separate from all of the above.
- Repository has uncommitted WORK-0007 changes; commit/push decision is
  Rob's (per repo discipline, no silent commits).

## Evidence pointers

- Master_Build_Journal.md EVENT-0008..0010 (directive reconciliation, Gate 0
  PASS, implementation + isolated smoke).
- WORK_0007_VERIFICATION.md (executed evidence, open gates).
- CURRENT_IMPLEMENTATION_PLAN.md (ADR-0009 design).
- Power math preserved in this file (scratch script is 24h-pruned).
- PowerBall skill doctrine: agent_journal/2026-10-29_saturday_center_zone_pivot.md
  in the PowerBall repo (the real-money play this must not disturb).