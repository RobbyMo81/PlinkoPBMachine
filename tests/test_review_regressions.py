"""Reviewer regression tests: relationships, immutability and non-tied ranking."""

from datetime import date
from xml.etree import ElementTree

import pytest

from plinko.analysis import Draw, analyze, render_svg


def observation(identity: int, pb: int, alternate: bool = False) -> Draw:
    whites = (1, 2, 3, 5, 34 - pb) if alternate else (1, 2, 3, 4, 35 - pb)
    return Draw(identity, date(2026, 10, identity), whites, pb, "fixture", f"id-{identity}")


def test_full_source_link_and_immutable_results():
    rows = (observation(1, 2), observation(2, 1), observation(3, 2, True))
    result = analyze(rows)
    bucket = result.bins[45]
    assert [(d.identity, d.pb, d.record_hash, d.whites) for d in bucket.observations] == [
        (1, 2, "id-1", (1, 2, 3, 4, 33)),
        (2, 1, "id-2", (1, 2, 3, 4, 34)),
        (3, 2, "id-3", (1, 2, 3, 5, 32)),
    ]
    assert [(r.pb, r.count) for r in bucket.ranking] == [(2, 2), (1, 1)]
    assert sum(bucket.white_counts[2]) == 10
    with pytest.raises(TypeError):
        result.bins[45] = bucket
    with pytest.raises(TypeError):
        bucket.white_counts[2] = (0,) * 69


def test_tenth_position_is_not_a_dense_rank():
    rows = tuple(
        observation(pb * 2 - (0 if alt else 1), pb, alt)
        for pb in range(1, 11)
        for alt in (False, True)
    ) + (
        observation(21, 11),
    )
    result = analyze(rows)
    assert result.bins[45].frequency == 21
    assert len(result.bins[45].ranking) == 10
    assert [r.count for r in result.bins[45].ranking] == [2] * 10
    assert result.bins[45].pb_counts[10] == 1
    assert result.dataset_hash != analyze(rows[:20]).dataset_hash


def test_svg_visualizes_exact_six_ball_distribution():
    rows = (
        Draw(1, date(2026, 10, 1), (1, 2, 3, 4, 5), 1, "fixture", "low"),
        Draw(2, date(2026, 10, 2), (65, 66, 67, 68, 69), 26, "fixture", "high"),
    )
    svg = render_svg(analyze(rows))
    root = ElementTree.fromstring(svg)
    namespace = {"s": "http://www.w3.org/2000/svg"}
    assert root.find("s:title", namespace).text == "Six-ball total-sum distribution"
    bars = root.findall("s:rect", namespace)
    assert len(bars) == 346
    assert [bar.get("data-sum") for bar in bars if bar.get("data-frequency") != "0"] == [
        "16",
        "361",
    ]
    assert [bar.get("data-frequency") for bar in bars if bar.get("data-frequency") != "0"] == [
        "1",
        "1",
    ]
    assert [bar.get("x") for bar in bars if bar.get("data-frequency") != "0"] == ["0", "1035"]
    assert all(bar.get("height") == "180.00" for bar in bars if bar.get("data-frequency") != "0")


def test_svg_rejects_forged_bin_keys():
    class HostileInt(int):
        def __format__(self, spec):
            return '16" onmouseover="alert(1)'

    class ForgedAnalysis:
        def __init__(self):
            self.bins = {HostileInt(16): type("Bin", (), {"frequency": 1})()}

    with pytest.raises(ValueError, match="bin"):
        render_svg(ForgedAnalysis())


def test_endpoint_positions_and_modern_era_rejection():
    low = Draw(1, date(2026, 10, 1), (1, 2, 3, 4, 5), 1, "fixture", "low")
    high = Draw(2, date(2026, 10, 2), (65, 66, 67, 68, 69), 26, "fixture", "high")
    result = analyze((low, high))
    assert result.bins[16].pb_counts[0] == 1
    assert result.bins[361].pb_counts[25] == 1
    assert result.bins[361].white_counts[26][68] == 1
    with pytest.raises(ValueError, match="legacy"):
        analyze((Draw(3, date(2015, 10, 3), (1, 2, 3, 4, 5), 1, "fixture", "old"),))
