"""Tests for the OpenAIP import parsers."""

from __future__ import annotations

import json

from adsb_server.reference_data.openaip import (
    _parse_airports,
    _parse_airspaces,
    _parse_navaids,
    _parse_reporting_points,
    _to_ft,
    _to_mhz,
)

_APT_FEATURE = json.dumps(
    {
        "type": "Feature",
        "properties": {
            "_id": "abc123",
            "name": "LONDON HEATHROW",
            "icaoCode": "EGLL",
            "iataCode": "LHR",
            "type": 3,
            "country": "GB",
            "elevation": {"value": 25, "unit": 0},
        },
        "geometry": {"type": "Point", "coordinates": [-0.461389, 51.4775]},
    }
)

_NAV_FEATURE = json.dumps(
    {
        "type": "Feature",
        "properties": {
            "_id": "nav001",
            "name": "BOVINGDON",
            "identifier": "BNN",
            "type": 3,
            "country": "GB",
            "elevation": {"value": 488, "unit": 1},
            "frequency": {"value": "113.750", "unit": 2},
        },
        "geometry": {"type": "Point", "coordinates": [-0.549, 51.726]},
    }
)

_RPP_FEATURE = json.dumps(
    {
        "type": "Feature",
        "properties": {
            "_id": "rpp001",
            "name": "DIVIS",
            "compulsory": False,
            "country": "GB",
            "elevation": {"value": 365, "unit": 1},
        },
        "geometry": {"type": "Point", "coordinates": [-6.03, 54.59]},
    }
)

_ASP_FEATURE = json.dumps(
    {
        "type": "Feature",
        "properties": {
            "_id": "asp001",
            "name": "LONDON CTR",
            "type": 4,
            "icaoClass": 2,
            "country": "GB",
            "lowerLimit": {"value": 0, "unit": 1, "referenceDatum": 0},
            "upperLimit": {"value": 2500, "unit": 1, "referenceDatum": 1},
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-0.5, 51.4], [-0.4, 51.4], [-0.4, 51.5], [-0.5, 51.4]]],
        },
    }
)


def test_to_ft_metres():
    assert _to_ft(100, 0) == 328


def test_to_ft_feet():
    assert _to_ft(500, 1) == 500


def test_to_ft_none():
    assert _to_ft(None, 1) is None


def test_to_mhz_mhz():
    assert _to_mhz("113.750", 2) == pytest_approx(113.75)


def test_to_mhz_khz():
    assert _to_mhz("348.000", 1) == pytest_approx(0.348)


def test_to_mhz_none():
    assert _to_mhz(None, 2) is None


def test_parse_airports():
    rows = _parse_airports((_APT_FEATURE + "\n").encode())
    assert len(rows) == 1
    r = rows[0]
    assert r[0] == "abc123"  # id
    assert r[1] == "airport"  # kind
    assert r[2] == "LONDON HEATHROW"
    assert r[3] == "EGLL"  # ident
    assert r[4] == "LHR"  # iata_code
    assert r[5] == 3  # type_code
    assert r[6] == "GB"
    assert abs(r[7] - (-0.461389)) < 1e-4  # lon
    assert abs(r[8] - 51.4775) < 1e-4  # lat
    assert r[9] == 82  # elevation_ft: 25m → 82ft
    assert r[10] is None  # frequency_mhz
    assert r[11] is None  # compulsory


def test_parse_navaids():
    rows = _parse_navaids((_NAV_FEATURE + "\n").encode())
    assert len(rows) == 1
    r = rows[0]
    assert r[0] == "nav001"
    assert r[1] == "navaid"
    assert r[3] == "BNN"  # ident
    assert r[5] == 3  # type_code (VOR)
    assert r[9] == 488  # elevation_ft already in feet
    assert abs(r[10] - 113.75) < 0.001  # frequency_mhz


def test_parse_reporting_points():
    rows = _parse_reporting_points((_RPP_FEATURE + "\n").encode())
    assert len(rows) == 1
    r = rows[0]
    assert r[0] == "rpp001"
    assert r[1] == "reporting_point"
    assert r[3] is None  # ident
    assert r[11] is False  # compulsory


def test_parse_airspaces():
    rows = _parse_airspaces((_ASP_FEATURE + "\n").encode())
    assert len(rows) == 1
    r = rows[0]
    assert r[0] == "asp001"
    assert r[1] == "LONDON CTR"
    assert r[2] == 4  # type_code (CTR)
    assert r[3] == 2  # icao_class (C)
    assert r[4] == "GB"
    assert json.loads(r[5])["type"] == "Polygon"
    assert r[6] == 0  # lower_limit_value
    assert r[7] == 1  # lower_limit_unit (ft)
    assert r[8] == 0  # lower_limit_ref (GND)
    assert r[9] == 2500  # upper_limit_value
    assert r[10] == 1  # upper_limit_unit (ft)
    assert r[11] == 1  # upper_limit_ref (MSL)


def test_parse_airports_skips_missing_coords():
    bad = json.dumps(
        {
            "type": "Feature",
            "properties": {"_id": "x", "name": "X", "country": "US", "type": 0},
            "geometry": None,
        }
    )
    rows = _parse_airports((bad + "\n").encode())
    assert rows == []


# Import pytest.approx for float comparison
try:
    from pytest import approx as pytest_approx
except ImportError:

    def pytest_approx(v):  # type: ignore[no-redef]
        return v
