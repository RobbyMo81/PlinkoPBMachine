"""Pure, descriptive six-ball Powerball frequency analysis.

No draw generation, historical backtesting, reference imports, or ledger writes.
The 2015-10-07 rule is the start of the present 69/26 ball era.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType

MODERN_ERA_START = date(2015, 10, 7)


@dataclass(frozen=True)
class Draw:
    identity: int
    draw_date: date
    whites: tuple[int, ...]
    pb: int
    source: str
    record_hash: str

    def __post_init__(self) -> None:
        if type(self.identity) is not int or self.identity < 1:
            raise ValueError("invalid draw identity")
        if type(self.draw_date) is not date:
            raise TypeError("invalid draw date")
        if len(self.whites) != 5 or len(set(self.whites)) != 5:
            raise ValueError("five distinct white balls required")
        if any(type(v) is not int or not 1 <= v <= 69 for v in self.whites):
            raise ValueError("white ball outside 1-69 range")
        if type(self.pb) is not int or not 1 <= self.pb <= 26:
            raise ValueError("powerball outside 1-26 range")
        if not self.source or not self.record_hash:
            raise ValueError("source and record hash required")
        object.__setattr__(self, "whites", tuple(sorted(self.whites)))

    @property
    def total(self) -> int:
        return sum(self.whites) + self.pb


@dataclass(frozen=True)
class LoadedDraws:
    rows: tuple[Draw, ...]
    excluded_legacy: int


@dataclass(frozen=True)
class Ranking:
    pb: int
    count: int
    label: str


@dataclass(frozen=True)
class SumBin:
    total: int
    frequency: int
    pb_counts: tuple[int, ...]  # index pb-1, includes zero-observation values
    ranking: tuple[Ranking, ...]
    white_counts: Mapping[int, tuple[int, ...]]  # index ball-1, only observed PBs
    white_sets: Mapping[int, tuple[tuple[int, ...], ...]]
    odd_counts: Mapping[int, tuple[int, ...]]
    draw_ids: tuple[int, ...]
    observations: tuple[Draw, ...]  # original provenance and set relationship retained


@dataclass(frozen=True)
class Analysis:
    bins: Mapping[int, SumBin]
    dataset_hash: str
    draw_count: int
    first_date: date
    last_date: date


def load_draws(database: Path) -> LoadedDraws:
    """Load from the canonical draw schema, never initialize or modify it.

    This is a descriptive current-data reader; it does not assert when records
    were first publicly available. Callers must not use it for a historical
    generation cutoff or a production operation.
    """
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute(
            "SELECT id, draw_date, ball1, ball2, ball3, ball4, ball5, "
            "powerball, source, record_hash FROM draws ORDER BY draw_date, id"
        ).fetchall()
    parsed: list[Draw] = []
    excluded = 0
    for row in rows:
        try:
            when = date.fromisoformat(row[1])
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid draw date in source database") from exc
        if when < MODERN_ERA_START:
            excluded += 1
            continue
        parsed.append(Draw(row[0], when, tuple(row[2:7]), row[7], row[8], row[9]))
    return LoadedDraws(tuple(parsed), excluded)


def analyze(draws: tuple[Draw, ...]) -> Analysis:
    """Count six-ball sum bins, nested PBs, and observed white sets.

    Sorting canonical rows ensures snapshot hashes are insensitive to input order.
    No frequency is represented as predictive power.
    """
    if not draws:
        raise ValueError("empty modern-era draw dataset")
    sorted_rows = sorted(draws, key=lambda row: (row.draw_date, row.identity))
    if len({d.identity for d in sorted_rows}) != len(sorted_rows):
        raise ValueError("duplicate draw identity")
    if len({d.draw_date for d in sorted_rows}) != len(sorted_rows):
        raise ValueError("duplicate draw date")
    if any(d.draw_date < MODERN_ERA_START for d in sorted_rows):
        raise ValueError("legacy-era draw in modern-era analysis")
    payload = [
        [d.identity, d.draw_date.isoformat(), *d.whites, d.pb, d.source, d.record_hash]
        for d in sorted_rows
    ]
    digest = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
    grouped: dict[int, list[Draw]] = defaultdict(list)
    for row in sorted_rows:
        grouped[row.total].append(row)
    bins = {}
    for total, members in sorted(grouped.items()):
        pb_counts = Counter(row.pb for row in members)
        ranked = sorted(pb_counts.items(), key=lambda item: (-item[1], item[0]))
        boundary = ranked[9][1] if len(ranked) >= 10 else None
        retained = tuple(
            Ranking(pb, count, "TOP_10" if i < 10 else "OUTLIER_TIE")
            for i, (pb, count) in enumerate(ranked)
            if i < 10 or count == boundary
        )
        white_counts = {}
        white_sets = {}
        odd_counts = {}
        for pb in pb_counts:
            group = [row for row in members if row.pb == pb]
            freq = Counter(ball for row in group for ball in row.whites)
            white_counts[pb] = tuple(freq.get(i, 0) for i in range(1, 70))
            white_sets[pb] = tuple(row.whites for row in group)
            odd_counts[pb] = tuple(sum(ball % 2 for ball in row.whites) for row in group)
            if sum(white_counts[pb]) != 5 * pb_counts[pb]:
                raise ValueError("white occurrence reconciliation failed")
        vector = tuple(pb_counts.get(i, 0) for i in range(1, 27))
        if sum(vector) != len(members):
            raise ValueError("nested PB reconciliation failed")
        bins[total] = SumBin(
            total,
            len(members),
            vector,
            retained,
            MappingProxyType(white_counts),
            MappingProxyType(white_sets),
            MappingProxyType(odd_counts),
            tuple(row.identity for row in members),
            tuple(members),
        )
    return Analysis(
        MappingProxyType(bins),
        digest,
        len(sorted_rows),
        sorted_rows[0].draw_date,
        sorted_rows[-1].draw_date,
    )


def render_svg(result: Analysis) -> str:
    """Render the exact six-ball sum histogram as standalone, in-memory SVG."""
    if not result.bins or any(
        type(total) is not int
        or not 16 <= total <= 361
        or type(bucket.frequency) is not int
        or bucket.frequency < 1
        for total, bucket in result.bins.items()
    ):
        raise ValueError("invalid sum bin for SVG")
    maximum = max(bucket.frequency for bucket in result.bins.values())
    bars = []
    for total in sorted(result.bins):
        count = result.bins[total].frequency
        height = 180 * count / maximum
        bars.append(
            f'<rect data-sum="{total}" data-frequency="{count}" '
            f'x="{(total - 16) * 3}" y="{190 - height:.2f}" '
            f'width="2" height="{height:.2f}" fill="#3567a8"/>'
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1038 220">'
        "<title>Six-ball total-sum distribution</title>"
        '<text x="0" y="215" font-size="12">Total sum (16 to 361)</text>' + "".join(bars) + "</svg>"
    )
