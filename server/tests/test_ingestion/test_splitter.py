"""Tests for flight splitting logic."""

from __future__ import annotations

from datetime import UTC

from adsb_server.ingestion.models import RawPoint, TraceHeader
from adsb_server.ingestion.splitter import interpolate_missing_values, split_flights


def _make_point(
    ts: float,
    lat: float = 51.5,
    lon: float = -0.1,
    alt_baro: float | None = 10000.0,
    new_leg: bool = False,
    squawk: str | None = None,
    callsign: str | None = None,
    emitter_category: str | None = None,
    track: float | None = None,
) -> RawPoint:
    return RawPoint(
        ts=ts,
        lat=lat,
        lon=lon,
        alt_baro=alt_baro,
        track=track,
        squawk=squawk,
        new_leg=new_leg,
        callsign=callsign,
        emitter_category=emitter_category,
    )


def _make_header(icao24: str = "aabbcc", icao_type: str | None = "B738") -> TraceHeader:
    return TraceHeader(icao24=icao24, icao_type=icao_type)


def _make_cutoff(base_ts: float, offset: float = 0.0) -> float:
    """Make a cutoff timestamp well past all points."""
    return base_ts + offset


class TestNewLegFlag:
    def test_new_leg_flag_splits(self) -> None:
        """Point with new_leg=True → 2 flights."""
        points = [
            _make_point(ts=1000.0),
            _make_point(ts=1060.0),
            _make_point(ts=1120.0, new_leg=True),
            _make_point(ts=1180.0),
        ]
        header = _make_header()
        cutoff = 10000.0

        finalized, _in_progress = split_flights(header, points, cutoff)
        assert len(finalized) == 2

    def test_new_leg_on_first_point_ignored(self) -> None:
        """new_leg on the second point of a segment starts a new segment."""
        points = [
            _make_point(ts=1000.0),
            _make_point(ts=1060.0, new_leg=True),
            _make_point(ts=1120.0),
            _make_point(ts=1180.0),
        ]
        header = _make_header()
        cutoff = 10000.0

        finalized, _in_progress = split_flights(header, points, cutoff)
        # First segment has 1 point (ts=1000) → too short, skipped
        # Second segment has 3 points → finalized
        assert len(finalized) == 1
        assert finalized[0].start_ts.timestamp() == 1060.0


class TestInProgress:
    def test_in_progress_flight(self) -> None:
        """Last point within 10 min of cutoff → in_progress not None."""
        # Points end 5 minutes before cutoff
        cutoff = 2000.0
        points = [
            _make_point(ts=1700.0),
            _make_point(ts=1760.0),
            _make_point(ts=1700.0 + 300.0),  # ts=2000 - 300 = 1700, well within window
        ]
        # Actually last point ts = 1700 + 300 = 2000; cutoff - 600 = 1400
        # 2000 >= 1400 → in-progress
        # Wait, let me recalculate:
        # cutoff = 2000, last_ts = 2000, cutoff - 600 = 1400
        # last_ts (2000) >= cutoff - 600 (1400) → in-progress ✓

        header = _make_header()
        finalized, in_progress = split_flights(header, points, cutoff)
        assert in_progress is not None
        assert len(finalized) == 0

    def test_finalized_flight(self) -> None:
        """Last airborne point >1 h before cutoff → finalized, in_progress is None."""
        # Airborne in-progress window is 1 h (3600 s); last_ts must be < cutoff - 3600.
        cutoff = 10000.0
        points = [
            _make_point(ts=2000.0),
            _make_point(ts=2100.0),
            _make_point(ts=2200.0),  # 2200 < 10000 - 3600 = 6400 → finalized
        ]
        header = _make_header()
        finalized, in_progress = split_flights(header, points, cutoff)
        assert in_progress is None
        assert len(finalized) == 1

    def test_in_progress_only_last_segment(self) -> None:
        """Multiple segments: only the last can be in-progress."""
        cutoff = 3000.0
        # cutoff - 600 = 2400
        points = [
            _make_point(ts=100.0),
            _make_point(ts=200.0),
            _make_point(ts=1200.0, new_leg=True),
            _make_point(ts=1300.0),
            _make_point(ts=2400.0, new_leg=True),  # last_ts == cutoff - 600 → in-progress
            _make_point(ts=2500.0),
        ]
        header = _make_header()
        finalized, in_progress = split_flights(header, points, cutoff)
        assert in_progress is not None
        assert len(finalized) == 2


class TestSquawkRuns:
    def test_squawk_runs_built_correctly(self) -> None:
        """Points with squawk changes → correct squawk_runs."""
        cutoff = 10000.0
        points = [
            _make_point(ts=1000.0, squawk="2000"),
            _make_point(ts=1060.0, squawk="2000"),  # no change
            _make_point(ts=1120.0, squawk="7700"),  # change!
            _make_point(ts=1180.0, squawk="7700"),  # no change
            _make_point(ts=1240.0, squawk="2200"),  # change!
        ]
        header = _make_header()
        finalized, _ = split_flights(header, points, cutoff)
        assert len(finalized) == 1
        runs = finalized[0].squawk_runs
        # Should have 3 runs: 2000, 7700, 2200
        assert len(runs) == 3
        assert runs[0] == (1000.0, "2000")
        assert runs[1] == (1120.0, "7700")
        assert runs[2] == (1240.0, "2200")

    def test_no_squawk_no_runs(self) -> None:
        """Points with no squawk → empty squawk_runs."""
        cutoff = 10000.0
        points = [
            _make_point(ts=1000.0, squawk=None),
            _make_point(ts=1060.0, squawk=None),
            _make_point(ts=1120.0, squawk=None),
        ]
        header = _make_header()
        finalized, _ = split_flights(header, points, cutoff)
        assert len(finalized) == 1
        assert finalized[0].squawk_runs == []

    def test_squawk_runs_single_value(self) -> None:
        """Constant squawk → start entry plus closing instant at flight end."""
        cutoff = 10000.0
        points = [
            _make_point(ts=1000.0, squawk="1234"),
            _make_point(ts=1060.0, squawk="1234"),
            _make_point(ts=1120.0, squawk="1234"),
        ]
        header = _make_header()
        finalized, _ = split_flights(header, points, cutoff)
        assert len(finalized) == 1
        runs = finalized[0].squawk_runs
        assert runs[0] == (1000.0, "1234")
        assert runs[-1][1] == "1234"  # closing instant: same code
        assert runs[-1][0] > 1000.0  # closing instant: after the start


class TestCallsignResolution:
    def test_callsign_most_common(self) -> None:
        """Most common callsign wins."""
        cutoff = 10000.0
        points = [
            _make_point(ts=1000.0, callsign="BAW123"),
            _make_point(ts=1060.0, callsign="BAW123"),
            _make_point(ts=1120.0, callsign="BAW456"),
        ]
        header = _make_header()
        finalized, _ = split_flights(header, points, cutoff)
        assert len(finalized) == 1
        assert finalized[0].callsign == "BAW123"

    def test_callsign_none_when_all_null(self) -> None:
        """No callsigns → callsign is None."""
        cutoff = 10000.0
        points = [
            _make_point(ts=1000.0, callsign=None),
            _make_point(ts=1060.0, callsign=None),
        ]
        header = _make_header()
        finalized, _ = split_flights(header, points, cutoff)
        assert len(finalized) == 1
        assert finalized[0].callsign is None


class TestFinalizedFlightShape:
    def test_finalized_flight_has_start_end_ts(self) -> None:
        """FinalizedFlight start_ts and end_ts are UTC datetimes."""

        cutoff = 10000.0
        points = [
            _make_point(ts=1000.0),
            _make_point(ts=1060.0),
            _make_point(ts=1120.0),
        ]
        header = _make_header()
        finalized, _ = split_flights(header, points, cutoff)
        assert len(finalized) == 1
        f = finalized[0]
        assert f.start_ts.tzinfo == UTC
        assert f.end_ts.tzinfo == UTC
        assert f.start_ts.timestamp() == 1000.0
        assert f.end_ts.timestamp() == 1120.0

    def test_finalized_flight_vertices_shape(self) -> None:
        """Vertices are (lon, lat, alt_ft, ts) tuples."""
        cutoff = 10000.0
        points = [
            _make_point(ts=1000.0, lat=51.0, lon=-0.1, alt_baro=10000.0),
            _make_point(ts=1060.0, lat=51.1, lon=-0.2, alt_baro=11000.0),
        ]
        header = _make_header()
        finalized, _ = split_flights(header, points, cutoff)
        assert len(finalized) == 1
        v = finalized[0].vertices
        assert len(v) >= 2
        # First vertex: (lon, lat, alt_ft, ts)
        assert v[0][0] == -0.1  # lon
        assert v[0][1] == 51.0  # lat
        assert v[0][2] == 10000.0  # alt_ft
        assert v[0][3] == 1000.0  # ts

    def test_single_point_segment_skipped(self) -> None:
        """Segments with < 2 points are skipped."""
        cutoff = 10000.0
        # After a new_leg split, first segment has only 1 point
        points = [
            _make_point(ts=1000.0),
            _make_point(ts=1060.0, new_leg=True),
            _make_point(ts=1120.0),
        ]
        header = _make_header()
        finalized, _ = split_flights(header, points, cutoff)
        # First segment: [ts=1000] → 1 point → skipped
        # Second segment: [ts=1060, ts=1120] → 2 points → finalized
        assert len(finalized) == 1
        assert finalized[0].start_ts.timestamp() == 1060.0


# ---------------------------------------------------------------------------
# Ground point handling
# ---------------------------------------------------------------------------


class TestGroundPointHandling:
    def test_new_leg_on_ground_yields_two_flights(self) -> None:
        """Two airborne sequences separated by a ground new_leg point → 2 flights.

        The ground point must not appear as a 0-altitude vertex in either flight,
        and the second flight's start_ts must be the first airborne point after
        the ground, not the ground point itself.
        """
        points = [
            _make_point(ts=1000.0, alt_baro=35000.0),
            _make_point(ts=1060.0, alt_baro=30000.0),
            _make_point(ts=1120.0, alt_baro=None, new_leg=True),  # ground landing
            _make_point(ts=1180.0, alt_baro=5000.0),
            _make_point(ts=1240.0, alt_baro=10000.0),
        ]
        header = _make_header()
        finalized, _ = split_flights(header, points, 10000.0)
        assert len(finalized) == 2
        assert finalized[1].start_ts.timestamp() == 1180.0
        for flight in finalized:
            assert all(v[2] > 0 for v in flight.vertices)

    def test_segment_leading_ground_excluded_from_geometry(self) -> None:
        """Segment whose first point is ground: geometry starts at first airborne point."""
        points = [
            _make_point(ts=1000.0, alt_baro=None),  # ground
            _make_point(ts=1060.0, alt_baro=5000.0),
            _make_point(ts=1120.0, alt_baro=10000.0),
        ]
        header = _make_header()
        finalized, _ = split_flights(header, points, 10000.0)
        assert len(finalized) == 1
        f = finalized[0]
        assert f.start_ts.timestamp() == 1060.0
        assert all(v[2] > 0 for v in f.vertices)


# ---------------------------------------------------------------------------
# Gap-based splitting (fallback when readsb does not set new_leg)
# ---------------------------------------------------------------------------


class TestGapBasedSplitting:
    # --- ground gap ---

    def test_ground_gap_over_10min_splits(self) -> None:
        """Two ground points >10 min apart → new leg, yielding two flights."""
        points = [
            _make_point(ts=1000.0, alt_baro=30000.0),
            _make_point(ts=1060.0, alt_baro=20000.0),
            _make_point(ts=1120.0, alt_baro=None),  # landing
            _make_point(ts=1800.0, alt_baro=None),  # ground, 680 s > 10 min gap
            _make_point(ts=1860.0, alt_baro=5000.0),
            _make_point(ts=1920.0, alt_baro=10000.0),
        ]
        finalized, _ = split_flights(_make_header(), points, 10000.0)
        assert len(finalized) == 2

    def test_ground_gap_at_threshold_no_split(self) -> None:
        """Ground gap of exactly 600 s does NOT split (threshold is strict >)."""
        points = [
            _make_point(ts=1000.0, alt_baro=30000.0),
            _make_point(ts=1060.0, alt_baro=None),  # landing
            _make_point(ts=1660.0, alt_baro=None),  # ground, 600 s gap exactly
            _make_point(ts=1720.0, alt_baro=5000.0),
            _make_point(ts=1780.0, alt_baro=10000.0),
        ]
        finalized, _ = split_flights(_make_header(), points, 10000.0)
        assert len(finalized) == 1

    # --- air gap ---

    def test_air_gap_over_1h_splits(self) -> None:
        """Two airborne points >1 h apart → new leg, yielding two flights."""
        points = [
            _make_point(ts=1000.0, alt_baro=35000.0),
            _make_point(ts=1060.0, alt_baro=35000.0),
            _make_point(ts=4700.0, alt_baro=35000.0),  # 3640 s > 1 h
            _make_point(ts=4760.0, alt_baro=35000.0),
        ]
        finalized, _ = split_flights(_make_header(), points, 10000.0)
        assert len(finalized) == 2

    def test_air_gap_at_threshold_no_split(self) -> None:
        """Air gap of exactly 3600 s does NOT split (threshold is strict >)."""
        points = [
            _make_point(ts=1000.0, alt_baro=35000.0),
            _make_point(ts=1060.0, alt_baro=35000.0),
            _make_point(ts=4660.0, alt_baro=35000.0),  # 3600 s gap exactly
            _make_point(ts=4720.0, alt_baro=35000.0),
        ]
        finalized, _ = split_flights(_make_header(), points, 10000.0)
        assert len(finalized) == 1

    # --- 24-hour duration cap ---

    def test_24h_duration_cap_splits(self) -> None:
        """A segment spanning >24 h is force-split regardless of gap size."""
        # 27 hourly points: split fires at point 25 (25*3600 > 86400),
        # leaving pts[25] and pts[26] as a second 2-point segment that can finalize.
        step = 3600.0  # 1-point-per-hour, gap well under air threshold
        pts = [_make_point(ts=float(i * step), alt_baro=35000.0) for i in range(27)]
        finalized, _ = split_flights(_make_header(), pts, 999999.0)
        assert len(finalized) >= 2, "25-hour span should produce at least two segments"

    def test_24h_duration_cap_boundary_no_split(self) -> None:
        """A segment just under 24 h is NOT split by the duration cap alone."""
        step = 3600.0
        pts = [_make_point(ts=float(i * step), alt_baro=35000.0) for i in range(24)]
        # last point is at 23 * 3600 = 82800 s < 86400 s
        finalized, _ = split_flights(_make_header(), pts, 999999.0)
        assert len(finalized) == 1, "23-hour span should be a single segment"

    # --- in-progress window ---

    def test_in_progress_window_airborne_uses_1h(self) -> None:
        """Airborne last segment within 1 h of cutoff is kept as in-progress."""
        cutoff = 10000.0
        # Last point 1800 s (30 min) before cutoff — inside the 1-h window.
        points = [
            _make_point(ts=8000.0, alt_baro=35000.0),
            _make_point(ts=8200.0, alt_baro=35000.0),
        ]
        _, in_progress = split_flights(_make_header(), points, cutoff)
        assert in_progress is not None

    def test_in_progress_window_airborne_over_1h_finalizes(self) -> None:
        """Airborne last segment more than 1 h before cutoff is finalized."""
        cutoff = 10000.0
        # Last point 5400 s (90 min) before cutoff — outside the 1-h window.
        points = [
            _make_point(ts=4000.0, alt_baro=35000.0),
            _make_point(ts=4600.0, alt_baro=35000.0),
        ]
        finalized, in_progress = split_flights(_make_header(), points, cutoff)
        assert in_progress is None
        assert len(finalized) == 1

    def test_in_progress_window_ground_uses_10min(self) -> None:
        """Ground-ending last segment uses the 10-min window, not the 1-h window."""
        cutoff = 10000.0
        # Last point is ground, 1200 s (20 min) before cutoff.
        # 20 min > 10-min ground window → finalized, not in-progress.
        points = [
            _make_point(ts=8000.0, alt_baro=35000.0),
            _make_point(ts=8800.0, alt_baro=None),  # ground landing
        ]
        _, in_progress = split_flights(_make_header(), points, cutoff)
        assert in_progress is None


# ---------------------------------------------------------------------------
# interpolate_missing_values
# ---------------------------------------------------------------------------


class TestInterpolateMissingValues:
    def test_fills_alt_baro_gap(self) -> None:
        points = [
            _make_point(ts=0.0, alt_baro=10000.0),
            _make_point(ts=1.0, alt_baro=None),
            _make_point(ts=2.0, alt_baro=12000.0),
        ]
        out = interpolate_missing_values(points)
        assert out[1].alt_baro == 11000.0
        assert out[1].alt_baro_interpolated is True
        assert out[0].alt_baro_interpolated is False
        assert out[2].alt_baro_interpolated is False

    def test_leading_none_stays_none(self) -> None:
        """Points before the first known alt_baro are left as None."""
        points = [
            _make_point(ts=0.0, alt_baro=None),
            _make_point(ts=1.0, alt_baro=10000.0),
            _make_point(ts=2.0, alt_baro=12000.0),
        ]
        out = interpolate_missing_values(points)
        assert out[0].alt_baro is None

    def test_fills_track_gap_circular_wraparound(self) -> None:
        """Track interpolation takes the short arc through 0°."""
        points = [
            _make_point(ts=0.0, track=350.0),
            _make_point(ts=1.0, track=None),
            _make_point(ts=2.0, track=10.0),
        ]
        out = interpolate_missing_values(points)
        assert out[1].track is not None
        assert out[1].track_interpolated is True
        # Shortest arc 350→10 goes through 0°; midpoint ≈ 0°
        assert abs(out[1].track % 360) < 1.0 or abs(out[1].track - 360.0) < 1.0

    def test_fills_squawk_gap_by_forward_fill(self) -> None:
        points = [
            _make_point(ts=0.0, squawk="2000"),
            _make_point(ts=1.0, squawk=None),
            _make_point(ts=2.0, squawk=None),
        ]
        out = interpolate_missing_values(points)
        assert out[1].squawk == "2000"
        assert out[2].squawk == "2000"

    def test_leading_none_squawk_stays_none(self) -> None:
        points = [
            _make_point(ts=0.0, squawk=None),
            _make_point(ts=1.0, squawk="1234"),
        ]
        out = interpolate_missing_values(points)
        assert out[0].squawk is None

    def test_squawk_forward_fill_stops_at_new_value(self) -> None:
        points = [
            _make_point(ts=0.0, squawk="2000"),
            _make_point(ts=1.0, squawk=None),
            _make_point(ts=2.0, squawk="7700"),
            _make_point(ts=3.0, squawk=None),
        ]
        out = interpolate_missing_values(points)
        assert out[1].squawk == "2000"  # filled from prior "2000"
        assert out[3].squawk == "7700"  # filled from prior "7700"

    def test_original_points_not_mutated(self) -> None:
        p = _make_point(ts=1.0, alt_baro=None)
        points = [
            _make_point(ts=0.0, alt_baro=9000.0),
            p,
            _make_point(ts=2.0, alt_baro=11000.0),
        ]
        interpolate_missing_values(points)
        assert p.alt_baro is None  # original untouched
