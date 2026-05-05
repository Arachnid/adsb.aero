"""Tests for the ADS-B trace JSON parser."""

from __future__ import annotations

from adsb_server.ingestion.parser import _parse_trace_json


def _make_trace(
    icao: str = "4ca7b3",
    t: str | None = "A320",
    timestamp: float = 1609275898.0,
    trace_entries: list[list[object]] | None = None,
) -> dict[str, object]:
    """Build a minimal trace JSON dict."""
    return {
        "icao": icao,
        "t": t,
        "timestamp": timestamp,
        "trace": trace_entries or [],
    }


def _make_entry(
    offset: float = 0.0,
    lat: float = 51.5,
    lon: float = -0.1,
    alt_baro: object = 35000.0,
    gs: float | None = 450.0,
    track: float | None = 90.0,
    flags: int = 0,
    vr: float | None = None,
    aircraft_obj: object = None,
) -> list[object]:
    """Build a minimal trace entry."""
    return [offset, lat, lon, alt_baro, gs, track, flags, vr, aircraft_obj]


class TestParseGroundPoints:
    def test_parse_ground_points_skipped(self) -> None:
        """Points with alt_baro='ground' should be excluded."""
        data = _make_trace(
            trace_entries=[
                _make_entry(alt_baro="ground"),
                _make_entry(offset=1.0, alt_baro=10000.0),
            ]
        )
        _header, points = _parse_trace_json(data)
        assert len(points) == 1
        assert points[0].alt_baro == 10000.0

    def test_parse_null_alt_skipped(self) -> None:
        """Points with alt_baro=null should be excluded."""
        data = _make_trace(
            trace_entries=[
                _make_entry(alt_baro=None),
                _make_entry(offset=1.0, alt_baro=20000.0),
            ]
        )
        _header, points = _parse_trace_json(data)
        assert len(points) == 1
        assert points[0].alt_baro == 20000.0

    def test_parse_ground_string_excluded(self) -> None:
        """Any string alt_baro value should result in the point being excluded."""
        data = _make_trace(
            trace_entries=[
                _make_entry(alt_baro="ground"),
                _make_entry(offset=1.0, alt_baro="any_string"),
                _make_entry(offset=2.0, alt_baro=5000.0),
            ]
        )
        _header, points = _parse_trace_json(data)
        assert len(points) == 1


class TestParseFlagFields:
    def test_parse_new_leg_flag(self) -> None:
        """flags=2 → new_leg=True."""
        data = _make_trace(
            trace_entries=[
                _make_entry(flags=2),
            ]
        )
        _, points = _parse_trace_json(data)
        assert len(points) == 1
        assert points[0].new_leg is True

    def test_parse_stale_flag_not_new_leg(self) -> None:
        """flags=1 (stale) → new_leg=False."""
        data = _make_trace(
            trace_entries=[
                _make_entry(flags=1),
            ]
        )
        _, points = _parse_trace_json(data)
        assert len(points) == 1
        assert points[0].new_leg is False

    def test_parse_both_flags_new_leg_true(self) -> None:
        """flags=3 (stale + new_leg) → new_leg=True."""
        data = _make_trace(
            trace_entries=[
                _make_entry(flags=3),
            ]
        )
        _, points = _parse_trace_json(data)
        assert len(points) == 1
        assert points[0].new_leg is True

    def test_parse_no_flags_new_leg_false(self) -> None:
        """flags=0 → new_leg=False."""
        data = _make_trace(
            trace_entries=[
                _make_entry(flags=0),
            ]
        )
        _, points = _parse_trace_json(data)
        assert len(points) == 1
        assert points[0].new_leg is False


class TestParseAircraftObj:
    def test_parse_squawk_extracted(self) -> None:
        """aircraft_obj with squawk='2000' → RawPoint.squawk=='2000'."""
        data = _make_trace(
            trace_entries=[
                _make_entry(aircraft_obj={"squawk": "2000", "flight": "BAW123"}),
            ]
        )
        _, points = _parse_trace_json(data)
        assert len(points) == 1
        assert points[0].squawk == "2000"

    def test_parse_callsign_stripped(self) -> None:
        """aircraft_obj with flight='BAW123  ' → callsign=='BAW123'."""
        data = _make_trace(
            trace_entries=[
                _make_entry(aircraft_obj={"flight": "BAW123  "}),
            ]
        )
        _, points = _parse_trace_json(data)
        assert len(points) == 1
        assert points[0].callsign == "BAW123"

    def test_parse_callsign_empty_after_strip(self) -> None:
        """aircraft_obj with flight='   ' → callsign==None."""
        data = _make_trace(
            trace_entries=[
                _make_entry(aircraft_obj={"flight": "   "}),
            ]
        )
        _, points = _parse_trace_json(data)
        assert len(points) == 1
        assert points[0].callsign is None

    def test_parse_emitter_category(self) -> None:
        """aircraft_obj with category='A3' → emitter_category=='A3'."""
        data = _make_trace(
            trace_entries=[
                _make_entry(aircraft_obj={"category": "A3"}),
            ]
        )
        _, points = _parse_trace_json(data)
        assert len(points) == 1
        assert points[0].emitter_category == "A3"

    def test_parse_no_aircraft_obj(self) -> None:
        """No aircraft_obj → squawk=None, callsign=None, emitter_category=None."""
        data = _make_trace(
            trace_entries=[
                _make_entry(aircraft_obj=None),
            ]
        )
        _, points = _parse_trace_json(data)
        assert len(points) == 1
        assert points[0].squawk is None
        assert points[0].callsign is None
        assert points[0].emitter_category is None


class TestParseHeader:
    def test_parse_icao24_lowercased(self) -> None:
        """icao is lowercased."""
        data = _make_trace(icao="4CA7B3")
        _, _points = _parse_trace_json(data)
        # Even with no points, header should work
        header, _ = _parse_trace_json(data)
        assert header.icao24 == "4ca7b3"

    def test_parse_icao_type(self) -> None:
        """t field becomes icao_type."""
        data = _make_trace(t="B738")
        header, _ = _parse_trace_json(data)
        assert header.icao_type == "B738"

    def test_parse_missing_icao_type(self) -> None:
        """Missing t field → icao_type=None."""
        data = _make_trace(t=None)
        header, _ = _parse_trace_json(data)
        assert header.icao_type is None

    def test_parse_timestamp_offsets(self) -> None:
        """ts = timestamp + offset."""
        base = 1609275898.0
        data = _make_trace(
            timestamp=base,
            trace_entries=[
                _make_entry(offset=0.0),
                _make_entry(offset=5.5),
                _make_entry(offset=10.0),
            ],
        )
        _, points = _parse_trace_json(data)
        assert len(points) == 3
        assert points[0].ts == base
        assert points[1].ts == base + 5.5
        assert points[2].ts == base + 10.0

    def test_parse_missing_lat_lon_skipped(self) -> None:
        """Points with None lat or lon should be skipped."""
        data = _make_trace(
            trace_entries=[
                [0.0, None, -0.1, 10000.0, None, None, 0, None, None],  # None lat
                [1.0, 51.5, None, 10000.0, None, None, 0, None, None],  # None lon
                [2.0, 51.5, -0.1, 10000.0, None, None, 0, None, None],  # valid
            ]
        )
        _, points = _parse_trace_json(data)
        assert len(points) == 1
