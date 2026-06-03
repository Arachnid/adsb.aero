"""Tests for AirportIndex nearest-airport lookup."""

from __future__ import annotations

import pytest

from adsb_server.ingestion.airport_index import (
    AGL_MATCH_MAX_FT,
    MATCH_RADIUS_M,
    AirportIndex,
)

# Heathrow EGLL (type 3 = International Airport): -0.461389, 51.4775
# Gatwick  EGKK (type 3): -0.190278, 51.148056  (~44 km from EGLL)
# Ascot civil heliport EGLT (type 7): -0.668056, 51.408611 (~16 km from EGLL)

_AIRPORTS: list[tuple[str, float, float, int]] = [
    ("id-egll", -0.461389, 51.4775, 3),
    ("id-egkk", -0.190278, 51.148056, 3),
    ("id-eglt", -0.668056, 51.408611, 7),  # civil heliport
]

# Co-located airport (type 3) + civil heliport (type 7), ~280 m apart.
# A point ~210 m from the airport and ~490 m from the heliport should
# still prefer the heliport for rotorcraft (A7).
_COLLOCATED: list[tuple[str, float, float, int]] = [
    ("id-xapt", 10.000, 51.000, 3),
    ("id-xhel", 10.004, 51.000, 7),
]


@pytest.fixture
def index() -> AirportIndex:
    return AirportIndex.from_rows(_AIRPORTS)


@pytest.fixture
def collocated_index() -> AirportIndex:
    return AirportIndex.from_rows(_COLLOCATED)


def test_nearest_finds_close_airport(index: AirportIndex) -> None:
    result = index.nearest(-0.461389, 51.487)  # ~1 km north of EGLL
    assert result == "id-egll"


def test_nearest_returns_none_beyond_radius(index: AirportIndex) -> None:
    result = index.nearest(1.0, 50.5)  # English Channel
    assert result is None


def test_nearest_fixed_wing_excludes_heliport(index: AirportIndex) -> None:
    # ~1 km north of EGLT (heliport); EGLL is ~16 km away → no match.
    result = index.nearest(-0.668056, 51.418, emitter_category="A3")
    assert result is None


def test_nearest_rotorcraft_prefers_heliport(index: AirportIndex) -> None:
    result = index.nearest(-0.668056, 51.418, emitter_category="A7")
    assert result == "id-eglt"


def test_nearest_rotorcraft_prefers_heliport_over_closer_airport(
    collocated_index: AirportIndex,
) -> None:
    result = collocated_index.nearest(9.997, 51.000, emitter_category="A7")
    assert result == "id-xhel"


def test_nearest_rotorcraft_falls_back_to_airport_when_no_heliport(
    index: AirportIndex,
) -> None:
    # ~1 km north of EGLL; EGLT (heliport) is ~16 km away → falls back.
    result = index.nearest(-0.461389, 51.487, emitter_category="A7")
    assert result == "id-egll"


def test_nearest_default_category_excludes_heliport(index: AirportIndex) -> None:
    result = index.nearest(-0.668056, 51.418)
    assert result is None


def test_nearest_tie_breaks_by_distance(index: AirportIndex) -> None:
    result = index.nearest(-0.461389, 51.495)  # ~2 km north of EGLL
    assert result == "id-egll"


def test_nearest_excludes_closed_type(index: AirportIndex) -> None:
    # Build an index with a closed airport (type 8) only.
    idx = AirportIndex.from_rows([("closed", -0.461389, 51.4775, 8)])
    assert idx.nearest(-0.461389, 51.4775) is None


def test_empty_index_returns_none() -> None:
    idx = AirportIndex.from_rows([])
    assert idx.nearest(0.0, 51.0) is None


def test_match_radius_constant_is_5km() -> None:
    assert MATCH_RADIUS_M == 5_000.0


def test_agl_match_max_ft_constant() -> None:
    assert AGL_MATCH_MAX_FT == 1_000.0
