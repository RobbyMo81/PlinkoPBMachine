"""Clean-room experimental portfolio; never writes to the operational application.

Exact-sum white sets are uniform on the feasible set conditional on prior tickets
and successful bounded rejection, not a prediction or an independent nine-way draw.
"""

from __future__ import annotations

import itertools
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import cache
from zoneinfo import ZoneInfo

from plinko.analysis import Analysis, rank_powerballs, rank_sums

DRAW_ZONE = ZoneInfo("America/New_York")
DRAW_TIME = time(22, 59)
DRAW_WEEKDAYS = {0, 2, 5}  # Monday, Wednesday, Saturday


class ConstraintError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Ticket:
    whites: tuple[int, ...]
    pb: int
    kind: str
    total: int | None = None
    sum_rank: int | None = None
    pb_rank: int | None = None


@dataclass(frozen=True)
class Portfolio:
    experimental: tuple[Ticket, ...]
    control: Ticket
    target_date: date
    generated_at: datetime
    dataset_hash: str
    top_sums: tuple[int, ...]
    pb_rankings: tuple[tuple[int, ...], ...]
    overlaps_checked: int
    control_collision: bool
    distinct_pbs: int
    wb_method: str = "uniform_exact_sum_conditional_overlap_v1"


def _ways(pool: tuple[int, ...], target: int):
    @cache
    def count(start: int, slots: int, remaining: int) -> int:
        if slots == 0:
            return int(remaining == 0)
        if remaining < 0 or len(pool) - start < slots:
            return 0
        return sum(
            count(index + 1, slots - 1, remaining - pool[index])
            for index in range(start, len(pool) - slots + 1)
        )

    return count


def _validate_pool(pool: tuple[int, ...]) -> None:
    if len(pool) < 5 or len(set(pool)) != len(pool) or tuple(sorted(pool)) != pool:
        raise ValueError("pool must have at least five distinct ascending values")
    if any(type(ball) is not int or not 1 <= ball <= 69 for ball in pool):
        raise ValueError("pool balls outside valid range")


def count_exact_sum(pool: tuple[int, ...], target: int) -> int:
    _validate_pool(pool)
    return _ways(pool, target)(0, 5, target)


def unrank_exact_sum(pool: tuple[int, ...], target: int, index: int) -> tuple[int, ...]:
    """Map each integer in [0, count) once to a lexicographic valid white set."""
    _validate_pool(pool)
    count = _ways(pool, target)
    total = count(0, 5, target)
    if type(index) is not int or not 0 <= index < total:
        raise ValueError("unranking index out of range")
    chosen = []
    start, slots, remaining = 0, 5, target
    while slots:
        for candidate in range(start, len(pool) - slots + 1):
            branch = count(candidate + 1, slots - 1, remaining - pool[candidate])
            if index >= branch:
                index -= branch
                continue
            chosen.append(pool[candidate])
            remaining -= pool[candidate]
            start = candidate + 1
            slots -= 1
            break
        else:
            raise AssertionError("exact-sum DP count and unrank disagree")
    return tuple(chosen)


def sample_exact_sum(
    target: int,
    *,
    previous: tuple[tuple[int, ...], ...] = (),
    pool: tuple[int, ...] = tuple(range(1, 70)),
    retries: int = 100_000,
    rng=None,
) -> tuple[int, ...]:
    """Rejection sampling yields uniform feasible sets when it succeeds.

    Exhausting attempts is SEARCH_EXHAUSTED, not a proof of impossibility.
    """
    choices = count_exact_sum(pool, target)
    if choices == 0:
        raise ConstraintError("UNSATISFIABLE_SUM", f"no five-ball set sums to {target}")
    if type(retries) is not int or retries < 1:
        raise ValueError("retries must be positive")
    source = rng if rng is not None else secrets.SystemRandom()
    for _ in range(retries):
        selected = unrank_exact_sum(pool, target, source.randrange(choices))
        if all(len(set(selected) & set(prior)) <= 2 for prior in previous):
            return selected
    raise ConstraintError("SEARCH_EXHAUSTED", f"no feasible set found in {retries} attempts")


def next_draw_date(generated_at: datetime) -> date:
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("timezone-aware generation timestamp required")
    local = generated_at.astimezone(DRAW_ZONE)
    for offset in range(8):
        candidate = local.date() + timedelta(days=offset)
        if (
            candidate.weekday() in DRAW_WEEKDAYS
            and datetime.combine(candidate, DRAW_TIME, DRAW_ZONE) > local
        ):
            return candidate
    raise AssertionError("draw calendar calculation failed")


def build_portfolio(
    result: Analysis,
    target_date: date,
    generated_at: datetime,
    *,
    rng=None,
    control_rng=None,
    retries: int = 100_000,
) -> Portfolio:
    """Create 3×3 experimental assignments and an unfiltered independent control."""
    scheduled = next_draw_date(generated_at)
    if target_date != scheduled:
        raise ValueError("target must be the next scheduled draw")
    if result.last_date >= generated_at.astimezone(DRAW_ZONE).date():
        raise ValueError("source draw dates must precede generation date")
    sums = rank_sums(result, require=3)[:3]
    pbs = tuple(rank_powerballs(result, r.total, require=3)[:3] for r in sums)
    selected = []
    white_rng = rng if rng is not None else secrets.SystemRandom()
    for sum_rank, (ranked_sum, ranked_pbs) in enumerate(zip(sums, pbs), 1):
        for pb_rank, ranked_pb in enumerate(ranked_pbs, 1):
            whites = sample_exact_sum(
                ranked_sum.total - ranked_pb.pb,
                previous=tuple(t.whites for t in selected),
                rng=white_rng,
                retries=retries,
            )
            selected.append(
                Ticket(whites, ranked_pb.pb, "EXPERIMENTAL", ranked_sum.total, sum_rank, pb_rank)
            )
    experiments = tuple(selected)
    pairs = tuple(itertools.combinations(experiments, 2))
    if len(pairs) != 36 or any(len(set(a.whites) & set(b.whites)) > 2 for a, b in pairs):
        raise AssertionError("experimental white-ball overlap invariant failed")
    source = control_rng if control_rng is not None else secrets.SystemRandom()
    control = Ticket(
        tuple(sorted(source.sample(range(1, 70), 5))), source.randrange(26) + 1, "CONTROL_RANDOM"
    )
    if len(set(control.whites)) != 5 or not all(1 <= b <= 69 for b in control.whites):
        raise ValueError("control source returned invalid white balls")
    collision = any((t.whites, t.pb) == (control.whites, control.pb) for t in experiments)
    return Portfolio(
        experiments,
        control,
        target_date,
        generated_at,
        result.dataset_hash,
        tuple(r.total for r in sums),
        tuple(tuple(p.pb for p in group) for group in pbs),
        len(pairs),
        collision,
        len({t.pb for t in experiments}),
    )
