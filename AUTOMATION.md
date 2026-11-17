# Isolated Plinko cycle automation

This is a measurement workflow, not a lottery-purchase service or a predictor.
`run_plinko.py` invokes `plinko.automation.main` once. Its draw input is the
owner-supplied `.cache/unified_storage.db` copy, opened read-only; output is
confined to this repository's `.cache/` directory. The runner never opens the
production PowerBall database (`C:\Users\RobMo\PBMachine`) or its legacy
OneDrive location, and never falls back to either if the copy is missing.
It never invokes the production PowerBall pick generator or ledger.
The copy must be refreshed separately after official draws are updated, using
a consistent SQLite backup rather than a plain copy of an active WAL database.
The runner does not publish or refresh this source copy. A missing prior draw
prevents new generation; a missing target draw leaves its cycle pending.

A run checks the pre-existing isolated batches before doing work. If an official
target draw has arrived, it creates a fresh validated SQLite snapshot and a
consistent isolated ledger backup. It runs the copied tracker's
`evaluate_against_draws` against a staged ledger copy, verifies all ten
prospective evaluations refer to the recorded target date and validates the
base-game prize tiers. Only if the live ledger still matches the pre-score
backup does a SQLite transaction publish the staged evaluation history.
Concurrent manual ledger changes therefore fail closed without publishing
scores. Already-scored cycles are revisited if the official
draw fields change; the tracker supersedes the previous evaluations rather than
counting both versions. Generation is a function of the run itself: whenever a run observes that
the next scheduled drawing has no existing cycle, it explicitly calls
`build_portfolio` and `persist_cycle` once for that drawing — whether or not
today is that drawing's own day — so a scoring pass after a drawing closes
also stocks the following drawing and no drawing is skipped when runs happen
off the target's day. If that target's preceding official draw is missing
from the local copy, generation defers with reason `stale_source`; if the
copy already contains a draw dated today, generation defers with reason
`generation_day_conflict` (the frozen pre-draw snapshot must predate the
generation day) and the next calendar day's run generates instead. An
existing target (including a manually generated target) is never overwritten. Before any scoring write, the
runner also checks that each saved target was the next scheduled drawing at
its recorded generation timestamp; a misbound but otherwise complete cycle
fails without adding evaluations. Missing prior draw data
prevents generation rather than using a stale ranking. An incomplete batch,
wrong-target result or stale lock is an error requiring manual reconciliation.

A successful no-op means the current target was already generated or the
next official result has not arrived. Each invocation prints one JSON status
record, appends it to `.cache/automation_runs.jsonl`, and exits nonzero on
failure. A scheduled invocation therefore exposes failure through Task
Scheduler's Last Result as well as the local log. Snapshot and ledger backup
paths appear in the status record for any write. Do not delete the frozen
pre-draw snapshots: they establish what was available when the set was made.

Manual run from the repository root:

    .venv/Scripts/python.exe run_plinko.py

Windows Task Scheduler may run the same absolute-path entry point daily at
07:15, 12:15 and 17:15 local time to consume a separately refreshed copy.
Do not install the task until OS isolation and human release gates pass; the
account must not be able to access the original PowerBall database. Configure
it not to start a second concurrent instance. The `.cache/.cycle.lock` is a second
fail-closed guard; a stale lock is not removed automatically. A SQLite unique
index on the isolated ledger also prevents a concurrently added manual cycle
from claiming the same draw target. Its one-time migration is backed up first.
The reference PowerBall refresh task is separate: this automation reads only
the local copy of its official data, never triggers a network refresh, and
never changes that task. Signed-out task
execution is not guaranteed with an interactive token. Inspect the task's
Last Result, `.cache/automation_runs.jsonl`, and the isolated ledger after
the first scheduled runs; don't infer a working schedule from task presence.

The local runner is not an adaptive model. Outcomes are retained for later
review through `read_pb_metrics`, which reports experimental and control PB
rates separately and validates the tracker-produced base-game prize tier for
each ticket. The nine paid tiers use fixed base awards of $4, $7, $100,
$50,000 or $1,000,000 as applicable; the jackpot tier has no fixed value and
is excluded from known-base-award totals. These are hypothetical base awards,
not proof of purchase, net return, Power Play payout or jurisdiction-specific
entitlement. Outcomes do not change the ranking algorithm.

Before each new set is persisted (manual `persist_cycle` and runner generation
both use this path), `plinko.monte_carlo.review_portfolio` validates the fixed
9+1 ticket structure, sum assignments, PB rankings, control independence
metadata, and experimental overlap limit. Persistence separately recomputes
sum and per-bin PB ranking order from the frozen pre-draw snapshot, rejecting
a self-consistent but source-misranked set before the first ledger write. The
review then simulates 20,000 uniform, independent draws using a deterministic
seed derived from the recorded set,
target and dataset hash. The report records experimental/control per-ticket PB
and any-prize rates, the draw-level experimental PB coverage, and its exact
null baseline (distinct experimental PBs / 26). A gross Monte Carlo PB
coverage inconsistency fails closed before the batch is written. The report
is saved in `generation_batches.strategy_json.monte_carlo_review`; older
cycles can be reviewed read-only with `review_saved_cycle` against their
frozen pre-draw snapshots, which must also predate the recorded generation day
and match the source-derived rankings. Neither this study nor the random
control is used to select, reject for apparent performance, or regenerate tickets. Simulated
rates are not a forecast, an advantage, or a human/independent code review.

Production integration, purchases, and automatic strategy tuning remain out
of scope. Before enabling scheduling, require independent executable review
and the clean-room isolation gates in `Clean_Room_Policy.md`. Disable any
installed `PlinkoCleanRoom*` tasks to pause without altering recorded cycles.
