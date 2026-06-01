"""Tests for AirportIndex nearest-airport lookup."""

from __future__ import annotations

import pytest

from adsb_server.ingestion.airport_index import MATCH_RADIUS_M, AirportIndex

# Heathrow (EGLL): -0.461389, 51.4775
# Gatwick  (EGKK): -0.190278, 51.148056  (~44 km from EGLL)
# Ascot heliport (EGLT): -0.668056, 51.408611 (~16 km from EGLL)

_AIRPORTS: list[tuple[str, float, float, str]] = [
    ("EGLL", -0.461389, 51.4775, "large_airport"),
    ("EGKK", -0.190278, 51.148056, "large_airport"),
    ("EGLT", -0.668056, 51.408611, "heliport"),
]

# Co-located airport + heliport: airport XAPT at (10.000, 51.000),
# heliport XHEL at (10.004, 51.000) ~280 m east.  A test point at
# (9.997, 51.000) is ~210 m from XAPT and ~490 m from XHEL — the
# airport is closer, but a helicopter should still prefer the heliport.
_COLLOCATED: list[tuple[str, float, float, str]] = [
    ("XAPT", 10.000, 51.000, "large_airport"),
    ("XHEL", 10.004, 51.000, "heliport"),
]


@pytest.fixture
def index() -> AirportIndex:
    return AirportIndex.from_rows(_AIRPORTS)


@pytest.fixture
def collocated_index() -> AirportIndex:
    return AirportIndex.from_rows(_COLLOCATED)


def test_nearest_finds_close_airport(index: AirportIndex) -> None:
    # ~1 km north of EGLL
    result = index.nearest(-0.461389, 51.487)
    assert result == "EGLL"


def test_nearest_returns_none_beyond_radius(index: AirportIndex) -> None:
    # Middle of the English Channel — far from any airport in the index
    result = index.nearest(1.0, 50.5)
    assert result is None


def test_nearest_fixed_wing_excludes_heliport(index: AirportIndex) -> None:
    # ~1 km north of EGLT (heliport); EGLL is ~16 km away.
    # Fixed-wing should skip the heliport and return None (nothing else within 5 km).
    result = index.nearest(-0.668056, 51.418, emitter_category="A3")
    assert result is None


def test_nearest_rotorcraft_prefers_heliport(index: AirportIndex) -> None:
    # Same point: A7 (rotorcraft) should match the heliport.
    result = index.nearest(-0.668056, 51.418, emitter_category="A7")
    assert result == "EGLT"


def test_nearest_rotorcraft_prefers_heliport_over_closer_airport(
    collocated_index: AirportIndex,
) -> None:
    # Point is closer to the airport (XAPT) than the heliport (XHEL), but
    # a helicopter should still prefer XHEL since it's within the radius.
    result = collocated_index.nearest(9.997, 51.000, emitter_category="A7")
    assert result == "XHEL"


def test_nearest_rotorcraft_falls_back_to_airport_when_no_heliport(
    index: AirportIndex,
) -> None:
    # ~1 km north of EGLL; EGLT (heliport) is ~16 km away — out of range.
    # A7 helicopter should fall back to EGLL.
    result = index.nearest(-0.461389, 51.487, emitter_category="A7")
    assert result == "EGLL"


def test_nearest_default_category_excludes_heliport(index: AirportIndex) -> None:
    result = index.nearest(-0.668056, 51.418)
    assert result is None


def test_nearest_tie_breaks_by_distance(index: AirportIndex) -> None:
    # ~2 km north of EGLL, well within the 5 km radius and closer to EGLL than EGKK.
    result = index.nearest(-0.461389, 51.495)
    assert result == "EGLL"


def test_empty_index_returns_none() -> None:
    idx = AirportIndex.from_rows([])
    assert idx.nearest(0.0, 51.0) is None


def test_match_radius_constant_is_5km() -> None:
    assert MATCH_RADIUS_M == 5_000.0
