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
    source: str | None = None,
    alt_geom: float | None = None,
    geom_vr: float | None = None,
    ias: float | None = None,
    roll: float | None = None,
) -> list[object]:
    """Build a minimal trace entry (indices 0-13)."""
    entry: list[object] = [offset, lat, lon, alt_baro, gs, track, flags, vr, aircraft_obj]
    if any(v is not None for v in (source, alt_geom, geom_vr, ias, roll)):
        entry += [source, alt_geom, geom_vr, ias, roll]
    return entry


class TestParseGroundPoints:
    def test_parse_ground_alt_gives_none(self) -> None:
        """Points with alt_baro='ground' are included with alt_baro=None."""
        data = _make_trace(
            trace_entries=[
                _make_entry(alt_baro="ground"),
                _make_entry(offset=1.0, alt_baro=10000.0),
            ]
        )
        _header, points = _parse_trace_json(data)
        assert len(points) == 2
        assert points[0].alt_baro is None
        assert points[1].alt_baro == 10000.0

    def test_parse_null_alt_gives_none(self) -> None:
        """Points with alt_baro=null are included with alt_baro=None."""
        data = _make_trace(
            trace_entries=[
                _make_entry(alt_baro=None),
                _make_entry(offset=1.0, alt_baro=20000.0),
            ]
        )
        _header, points = _parse_trace_json(data)
        assert len(points) == 2
        assert points[0].alt_baro is None
        assert points[1].alt_baro == 20000.0

    def test_parse_string_alt_gives_none(self) -> None:
        """Any unrecognised string alt_baro is parsed to None but point is kept."""
        data = _make_trace(
            trace_entries=[
                _make_entry(alt_baro="ground"),
                _make_entry(offset=1.0, alt_baro="any_string"),
                _make_entry(offset=2.0, alt_baro=5000.0),
            ]
        )
        _header, points = _parse_trace_json(data)
        assert len(points) == 3
        assert points[0].alt_baro is None
        assert points[1].alt_baro is None
        assert points[2].alt_baro == 5000.0


class TestGroundPointNewLeg:
    def test_ground_point_with_new_leg_preserved(self) -> None:
        """A ground point that carries new_leg=True must reach the splitter.

        readsb emits new_leg on the first point of a new leg, which is typically
        a ground-roll point.  Silently dropping it here destroys the split signal.
        """
        data = _make_trace(
            trace_entries=[
                _make_entry(offset=0.0, alt_baro=35000.0),
                _make_entry(offset=60.0, alt_baro="ground", flags=2),  # new_leg on ground
                _make_entry(offset=120.0, alt_baro=5000.0),
            ]
        )
        _, points = _parse_trace_json(data)
        assert len(points) == 3
        assert points[1].alt_baro is None
        assert points[1].new_leg is True


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


class TestScalarFields:
    def test_gs_parsed_from_index_4(self) -> None:
        data = _make_trace(trace_entries=[_make_entry(gs=482.5)])
        _, points = _parse_trace_json(data)
        assert points[0].gs == 482.5

    def test_gs_null_becomes_none(self) -> None:
        data = _make_trace(trace_entries=[_make_entry(gs=None)])
        _, points = _parse_trace_json(data)
        assert points[0].gs is None

    def test_vr_parsed_from_index_7(self) -> None:
        data = _make_trace(trace_entries=[_make_entry(vr=1984.0)])
        _, points = _parse_trace_json(data)
        assert points[0].vr == 1984.0

    def test_vr_null_becomes_none(self) -> None:
        data = _make_trace(trace_entries=[_make_entry(vr=None)])
        _, points = _parse_trace_json(data)
        assert points[0].vr is None

    def test_ias_parsed_from_index_12(self) -> None:
        data = _make_trace(trace_entries=[_make_entry(ias=275.0)])
        _, points = _parse_trace_json(data)
        assert points[0].ias == 275.0

    def test_ias_null_becomes_none(self) -> None:
        data = _make_trace(trace_entries=[_make_entry(ias=None)])
        _, points = _parse_trace_json(data)
        assert points[0].ias is None

    def test_ias_absent_when_short_entry(self) -> None:
        # Entries with fewer than 13 fields (pre-2022 format) give ias=None.
        data = _make_trace(trace_entries=[_make_entry()])  # only 9 fields
        _, points = _parse_trace_json(data)
        assert points[0].ias is None

    def test_all_three_scalars_together(self) -> None:
        data = _make_trace(
            trace_entries=[_make_entry(gs=450.0, vr=-1536.0, ias=270.0)]
        )
        _, points = _parse_trace_json(data)
        assert points[0].gs == 450.0
        assert points[0].vr == -1536.0
        assert points[0].ias == 270.0
