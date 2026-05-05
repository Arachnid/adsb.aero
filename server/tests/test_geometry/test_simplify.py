"""Tests for TD-TR trajectory simplification."""

from __future__ import annotations

import pytest

from adsb_server.geometry.simplify import (
    DeviationFn,
    _td_tr,
    altitude_deviation,
    simplify_flight,
    spatial_deviation,
)
from adsb_server.ingestion.models import RawFlight, RawPoint


def _pt(
    lat: float,
    lon: float,
    ts: float,
    alt_baro: float | None = 10000.0,
    track: float | None = None,
    squawk: str | None = None,
) -> RawPoint:
    return RawPoint(
        ts=ts,
        lat=lat,
        lon=lon,
        alt_baro=alt_baro,
        track=track,
        squawk=squawk,
        new_leg=False,
        callsign=None,
        emitter_category=None,
    )


def _flight(points: list[RawPoint]) -> RawFlight:
    return RawFlight(
        icao24="aabbcc",
        callsign=None,
        icao_type=None,
        emitter_category=None,
        points=points,
    )


def _run_td_tr(points: list[RawPoint], epsilon: float, dev_fn: DeviationFn) -> list[int]:
    n = len(points)
    kept: set[int] = {0, n - 1}
    _td_tr(points, 0, n - 1, epsilon, dev_fn, kept)
    return sorted(kept)


# ---------------------------------------------------------------------------
# spatial_deviation
# ---------------------------------------------------------------------------


class TestSpatialDeviation:
    def test_collinear_midpoint_zero_deviation(self) -> None:
        a = _pt(0.0, 0.0, ts=0.0)
        p = _pt(0.005, 0.0, ts=1.0)
        b = _pt(0.01, 0.0, ts=2.0)
        assert spatial_deviation(p, a, b) < 1.0  # sub-metre for exact midpoint

    def test_offset_point_nonzero_deviation(self) -> None:
        # lon offset of 0.0009° at equator ≈ 100 m
        a = _pt(0.0, 0.0, ts=0.0)
        p = _pt(0.005, 0.0009, ts=1.0)
        b = _pt(0.01, 0.0, ts=2.0)
        assert 80.0 < spatial_deviation(p, a, b) < 120.0


# ---------------------------------------------------------------------------
# altitude_deviation
# ---------------------------------------------------------------------------


class TestAltitudeDeviation:
    def test_exact_interpolation_zero(self) -> None:
        a = _pt(0.0, 0.0, ts=0.0, alt_baro=10000.0)
        p = _pt(0.0, 0.0, ts=1.0, alt_baro=11000.0)
        b = _pt(0.0, 0.0, ts=2.0, alt_baro=12000.0)
        assert altitude_deviation(p, a, b) == 0.0

    def test_spike_returns_correct_deviation(self) -> None:
        a = _pt(0.0, 0.0, ts=0.0, alt_baro=10000.0)
        p = _pt(0.0, 0.0, ts=1.0, alt_baro=11000.0)  # 500 ft above midpoint (10500)
        b = _pt(0.0, 0.0, ts=2.0, alt_baro=11000.0)
        assert altitude_deviation(p, a, b) == pytest.approx(500.0)

    def test_missing_alt_returns_zero(self) -> None:
        a = _pt(0.0, 0.0, ts=0.0, alt_baro=10000.0)
        p = _pt(0.0, 0.0, ts=1.0, alt_baro=None)
        b = _pt(0.0, 0.0, ts=2.0, alt_baro=12000.0)
        assert altitude_deviation(p, a, b) == 0.0


# ---------------------------------------------------------------------------
# _td_tr (via spatial_deviation)
# ---------------------------------------------------------------------------


class TestTdTrSpatial:
    def test_collinear_only_endpoints_kept(self) -> None:
        points = [_pt(i * 0.01, 0.0, ts=float(i)) for i in range(5)]
        assert _run_td_tr(points, 1.0, spatial_deviation) == [0, 4]

    def test_offset_kept_below_epsilon(self) -> None:
        points = [_pt(0.0, 0.0, ts=0.0), _pt(0.005, 0.0009, ts=1.0), _pt(0.01, 0.0, ts=2.0)]
        assert 1 in _run_td_tr(points, 50.0, spatial_deviation)
        assert 1 not in _run_td_tr(points, 200.0, spatial_deviation)

    def test_returns_sorted_indices(self) -> None:
        import random

        random.seed(42)
        points = [
            _pt(random.uniform(50.0, 55.0), random.uniform(-5.0, 2.0), ts=float(i))
            for i in range(20)
        ]
        kept = _run_td_tr(points, 50.0, spatial_deviation)
        assert kept == sorted(kept)
        assert kept[0] == 0
        assert kept[-1] == 19

    def test_two_points_always_kept(self) -> None:
        points = [_pt(0.0, 0.0, ts=0.0), _pt(1.0, 1.0, ts=1.0)]
        assert _run_td_tr(points, 1.0, spatial_deviation) == [0, 1]

    def test_large_offset_always_kept(self) -> None:
        points = [_pt(0.0, 0.0, ts=0.0), _pt(0.5, 0.009, ts=1.0), _pt(1.0, 0.0, ts=2.0)]
        assert 1 in _run_td_tr(points, 100.0, spatial_deviation)


# ---------------------------------------------------------------------------
# simplify_flight (end-to-end, points already interpolated by caller)
# ---------------------------------------------------------------------------


class TestSimplifyFlight:
    def test_altitude_pass_adds_spike(self) -> None:
        base = 51.5
        # Middle point is on the spatial interpolated line → dropped spatially
        # but 500 ft above → kept by altitude pass
        points = [
            _pt(base, -0.1, ts=0.0, alt_baro=10000.0),
            _pt(base, -0.1 + 0.001, ts=1.0, alt_baro=11000.0),
            _pt(base, -0.1 + 0.002, ts=2.0, alt_baro=11000.0),
        ]
        assert 1 in simplify_flight(points)

    def test_altitude_pass_ignores_small_deviation(self) -> None:
        base = 51.5
        points = [
            _pt(base, -0.1, ts=0.0, alt_baro=10000.0),
            _pt(base, -0.1 + 0.001, ts=1.0, alt_baro=10050.0),
            _pt(base, -0.1 + 0.002, ts=2.0, alt_baro=10000.0),
        ]
        assert 1 not in simplify_flight(points)

    def test_short_flight_kept_in_full(self) -> None:
        points = [_pt(0.0, 0.0, ts=0.0), _pt(1.0, 1.0, ts=1.0)]
        assert simplify_flight(points) == [0, 1]

    def test_many_collinear_points_reduced_to_endpoints(self) -> None:
        points = [_pt(i * 0.001, 0.0, ts=float(i), alt_baro=10000.0) for i in range(100)]
        assert simplify_flight(points) == [0, 99]

    def test_squawk_change_point_always_kept(self) -> None:
        # All points on a straight line at constant altitude — would normally
        # collapse to just the two endpoints.  The point where squawk changes
        # must be preserved regardless.
        base = 51.5
        points = [
            _pt(base, -0.1 + i * 0.001, ts=float(i), squawk="2000" if i < 2 else "7700")
            for i in range(4)
        ]
        kept = simplify_flight(points)
        assert 2 in kept  # first point of new squawk must be preserved

    def test_squawk_change_divides_simplification(self) -> None:
        # Eight collinear, constant-altitude points with a squawk change at index 4.
        # Without squawk awareness, only endpoints would be kept.
        # With squawk awareness, index 4 (squawk change) is also kept.
        base = 51.5
        points = [
            _pt(base, -0.1 + i * 0.001, ts=float(i), squawk="1234" if i < 4 else "5678")
            for i in range(8)
        ]
        kept = simplify_flight(points)
        assert kept == [0, 4, 7]

    def test_no_squawk_behaviour_unchanged(self) -> None:
        # All-None squawk: no boundaries added, identical to original algorithm.
        points = [_pt(i * 0.001, 0.0, ts=float(i), alt_baro=10000.0) for i in range(50)]
        assert simplify_flight(points) == [0, 49]
