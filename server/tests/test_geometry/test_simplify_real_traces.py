"""
Simplification tests using real ADS-B trace fixtures.

Traces extracted from the 2025-04-01 adsb.lol release (gzip-compressed JSON):
  - 4b2fe9  DA40  HB-SDT   365 pts  3950-10050 ft   single leg
  - aeede9  (unknown type) 452 pts  17750-25025 ft   single leg
  - a028e9  BL8   N1093E   471 pts  0-1300 ft        3 legs

Run with -s to see the printed simplification tables.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from adsb_server.geometry.simplify import simplify_flight
from adsb_server.ingestion.parser import _parse_trace_json
from adsb_server.ingestion.splitter import interpolate_missing_values

if TYPE_CHECKING:
    from adsb_server.ingestion.models import RawPoint

FIXTURES = Path(__file__).parent.parent / "fixtures" / "traces"

_EPSILONS: list[tuple[float, float]] = [
    (10.0, 50.0),
    (50.0, 100.0),   # production defaults
    (100.0, 200.0),
    (200.0, 500.0),
]


def _load(filename: str) -> tuple[str, list[RawPoint]]:
    """Return (label, airborne_points) for a fixture trace file."""
    path = FIXTURES / filename
    with gzip.open(path) as f:
        data = json.load(f)
    header, points = _parse_trace_json(data)
    airborne = [p for p in points if p.alt_baro is not None]
    label = f"{header.icao24}  type={data.get('t') or '?':6s}  reg={data.get('r') or '?':10s}"
    return label, interpolate_missing_values(airborne)


def _print_table(label: str, points: list[RawPoint]) -> None:
    n = len(points)
    print(f"\n{label}  ({n} airborne points)")
    print(f"  {'spatial_m':>10}  {'alt_ft':>8}  {'kept':>6}  {'dropped':>8}  {'reduction':>10}")
    for spatial_m, alt_ft in _EPSILONS:
        kept_idx = simplify_flight(points, spatial_m=spatial_m, alt_ft=alt_ft)
        kept = len(kept_idx)
        print(
            f"  {spatial_m:>10.0f}  {alt_ft:>8.0f}  {kept:>6}  {n - kept:>8}  "
            f"{(n - kept) / n * 100:>9.1f}%"
            + ("  [default]" if (spatial_m, alt_ft) == (50.0, 100.0) else "")
        )


# ---------------------------------------------------------------------------
# DA40 HB-SDT (4b2fe9) — medium-altitude GA flight, single leg
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spatial_m,alt_ft", _EPSILONS)
def test_da40_simplification(spatial_m: float, alt_ft: float) -> None:
    _label, points = _load("trace_full_4b2fe9.json")
    kept = simplify_flight(points, spatial_m=spatial_m, alt_ft=alt_ft)
    assert len(kept) >= 2, "must keep at least 2 points"
    assert kept[0] == 0
    assert kept[-1] == len(points) - 1
    # Looser epsilons should never keep more points than tighter ones
    if (spatial_m, alt_ft) != _EPSILONS[0]:
        prev_spatial, prev_alt = _EPSILONS[_EPSILONS.index((spatial_m, alt_ft)) - 1]
        prev_kept = simplify_flight(points, spatial_m=prev_spatial, alt_ft=prev_alt)
        assert len(kept) <= len(prev_kept), (
            f"looser epsilons ({spatial_m}m/{alt_ft}ft) kept more points "
            f"than tighter ({prev_spatial}m/{prev_alt}ft)"
        )


@pytest.fixture(scope="module", autouse=True)
def print_da40(request: pytest.FixtureRequest) -> None:  # type: ignore[return]
    label, points = _load("trace_full_4b2fe9.json")
    _print_table(label, points)


# ---------------------------------------------------------------------------
# Unknown high-altitude aircraft (aeede9) — jet cruise profile
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spatial_m,alt_ft", _EPSILONS)
def test_highalt_simplification(spatial_m: float, alt_ft: float) -> None:
    _label, points = _load("trace_full_aeede9.json")
    kept = simplify_flight(points, spatial_m=spatial_m, alt_ft=alt_ft)
    assert len(kept) >= 2
    assert kept[0] == 0
    assert kept[-1] == len(points) - 1
    if (spatial_m, alt_ft) != _EPSILONS[0]:
        prev_spatial, prev_alt = _EPSILONS[_EPSILONS.index((spatial_m, alt_ft)) - 1]
        prev_kept = simplify_flight(points, spatial_m=prev_spatial, alt_ft=prev_alt)
        assert len(kept) <= len(prev_kept)


@pytest.fixture(scope="module", autouse=True)
def print_highalt(request: pytest.FixtureRequest) -> None:  # type: ignore[return]
    label, points = _load("trace_full_aeede9.json")
    _print_table(label, points)


# ---------------------------------------------------------------------------
# Bellanca BL8 N1093E (a028e9) — low-altitude VFR, multiple legs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spatial_m,alt_ft", _EPSILONS)
def test_lowalt_multileg_simplification(spatial_m: float, alt_ft: float) -> None:
    _label, points = _load("trace_full_a028e9.json")
    kept = simplify_flight(points, spatial_m=spatial_m, alt_ft=alt_ft)
    assert len(kept) >= 2
    assert kept[0] == 0
    assert kept[-1] == len(points) - 1
    if (spatial_m, alt_ft) != _EPSILONS[0]:
        prev_spatial, prev_alt = _EPSILONS[_EPSILONS.index((spatial_m, alt_ft)) - 1]
        prev_kept = simplify_flight(points, spatial_m=prev_spatial, alt_ft=prev_alt)
        assert len(kept) <= len(prev_kept)


@pytest.fixture(scope="module", autouse=True)
def print_lowalt(request: pytest.FixtureRequest) -> None:  # type: ignore[return]
    label, points = _load("trace_full_a028e9.json")
    _print_table(label, points)


# ---------------------------------------------------------------------------
# Boeing 777-300ER B-2002 (780560) — wide-body long-haul cruise
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spatial_m,alt_ft", _EPSILONS)
def test_b77w_simplification(spatial_m: float, alt_ft: float) -> None:
    _label, points = _load("trace_full_780560.json")
    kept = simplify_flight(points, spatial_m=spatial_m, alt_ft=alt_ft)
    assert len(kept) >= 2
    assert kept[0] == 0
    assert kept[-1] == len(points) - 1
    if (spatial_m, alt_ft) != _EPSILONS[0]:
        prev_spatial, prev_alt = _EPSILONS[_EPSILONS.index((spatial_m, alt_ft)) - 1]
        prev_kept = simplify_flight(points, spatial_m=prev_spatial, alt_ft=prev_alt)
        assert len(kept) <= len(prev_kept)


@pytest.fixture(scope="module", autouse=True)
def print_b77w(request: pytest.FixtureRequest) -> None:  # type: ignore[return]
    label, points = _load("trace_full_780560.json")
    _print_table(label, points)


# ---------------------------------------------------------------------------
# Airbus A350-900 DQ-FAI (c8809c) — modern wide-body, Fiji Airways
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spatial_m,alt_ft", _EPSILONS)
def test_a359_simplification(spatial_m: float, alt_ft: float) -> None:
    _label, points = _load("trace_full_c8809c.json")
    kept = simplify_flight(points, spatial_m=spatial_m, alt_ft=alt_ft)
    assert len(kept) >= 2
    assert kept[0] == 0
    assert kept[-1] == len(points) - 1
    if (spatial_m, alt_ft) != _EPSILONS[0]:
        prev_spatial, prev_alt = _EPSILONS[_EPSILONS.index((spatial_m, alt_ft)) - 1]
        prev_kept = simplify_flight(points, spatial_m=prev_spatial, alt_ft=prev_alt)
        assert len(kept) <= len(prev_kept)


@pytest.fixture(scope="module", autouse=True)
def print_a359(request: pytest.FixtureRequest) -> None:  # type: ignore[return]
    label, points = _load("trace_full_c8809c.json")
    _print_table(label, points)


# ---------------------------------------------------------------------------
# Boeing 737-900 N428AS (a51968) — narrow-body, Alaska Airlines
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spatial_m,alt_ft", _EPSILONS)
def test_b739_simplification(spatial_m: float, alt_ft: float) -> None:
    _label, points = _load("trace_full_a51968.json")
    kept = simplify_flight(points, spatial_m=spatial_m, alt_ft=alt_ft)
    assert len(kept) >= 2
    assert kept[0] == 0
    assert kept[-1] == len(points) - 1
    if (spatial_m, alt_ft) != _EPSILONS[0]:
        prev_spatial, prev_alt = _EPSILONS[_EPSILONS.index((spatial_m, alt_ft)) - 1]
        prev_kept = simplify_flight(points, spatial_m=prev_spatial, alt_ft=prev_alt)
        assert len(kept) <= len(prev_kept)


@pytest.fixture(scope="module", autouse=True)
def print_b739(request: pytest.FixtureRequest) -> None:  # type: ignore[return]
    label, points = _load("trace_full_a51968.json")
    _print_table(label, points)
