"""Tests for TD-TR trajectory simplification."""

from __future__ import annotations

import pytest

from adsb_server.geometry.simplify import (
    DeviationFn,
    _td_tr,
    altitude_deviation,
    gs_deviation,
    ias_deviation,
    simplify_flight,
    simplify_series,
    spatial_deviation,
    track_deviation,
    vr_deviation,
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


# ---------------------------------------------------------------------------
# Scalar deviation functions
# ---------------------------------------------------------------------------


def _pt_scalar(
    ts: float,
    gs: float | None = None,
    vr: float | None = None,
    ias: float | None = None,
    track: float | None = None,
) -> RawPoint:
    return RawPoint(
        ts=ts,
        lat=0.0,
        lon=0.0,
        alt_baro=10000.0,
        track=track,
        squawk=None,
        new_leg=False,
        callsign=None,
        emitter_category=None,
        gs=gs,
        vr=vr,
        ias=ias,
    )


class TestGsDeviation:
    def test_exact_interpolation_zero(self) -> None:
        a = _pt_scalar(0.0, gs=400.0)
        b = _pt_scalar(10.0, gs=500.0)
        mid = _pt_scalar(5.0, gs=450.0)
        assert gs_deviation(mid, a, b) == pytest.approx(0.0)

    def test_spike_returns_deviation(self) -> None:
        a = _pt_scalar(0.0, gs=400.0)
        b = _pt_scalar(10.0, gs=400.0)
        spike = _pt_scalar(5.0, gs=450.0)
        assert gs_deviation(spike, a, b) == pytest.approx(50.0)

    def test_missing_gs_returns_zero(self) -> None:
        a = _pt_scalar(0.0, gs=400.0)
        b = _pt_scalar(10.0, gs=500.0)
        null_mid = _pt_scalar(5.0, gs=None)
        assert gs_deviation(null_mid, a, b) == 0.0


class TestVrDeviation:
    def test_exact_interpolation_zero(self) -> None:
        a = _pt_scalar(0.0, vr=0.0)
        b = _pt_scalar(10.0, vr=2000.0)
        mid = _pt_scalar(5.0, vr=1000.0)
        assert vr_deviation(mid, a, b) == pytest.approx(0.0)

    def test_spike_returns_deviation(self) -> None:
        a = _pt_scalar(0.0, vr=0.0)
        b = _pt_scalar(10.0, vr=0.0)
        spike = _pt_scalar(5.0, vr=200.0)
        assert vr_deviation(spike, a, b) == pytest.approx(200.0)


class TestIasDeviation:
    def test_exact_interpolation_zero(self) -> None:
        a = _pt_scalar(0.0, ias=250.0)
        b = _pt_scalar(10.0, ias=300.0)
        mid = _pt_scalar(5.0, ias=275.0)
        assert ias_deviation(mid, a, b) == pytest.approx(0.0)

    def test_missing_ias_returns_zero(self) -> None:
        a = _pt_scalar(0.0, ias=250.0)
        b = _pt_scalar(10.0, ias=300.0)
        null_mid = _pt_scalar(5.0, ias=None)
        assert ias_deviation(null_mid, a, b) == 0.0


class TestTrackDeviation:
    def test_straight_flight_zero(self) -> None:
        a = _pt_scalar(0.0, track=90.0)
        b = _pt_scalar(10.0, track=90.0)
        mid = _pt_scalar(5.0, track=90.0)
        assert track_deviation(mid, a, b) == pytest.approx(0.0)

    def test_turning_midpoint_zero_when_exact(self) -> None:
        a = _pt_scalar(0.0, track=80.0)
        b = _pt_scalar(10.0, track=100.0)
        mid = _pt_scalar(5.0, track=90.0)
        assert track_deviation(mid, a, b) == pytest.approx(0.0)

    def test_wrap_around_handled(self) -> None:
        # 350° → 10° turn: midpoint should be ~0°, not 180°
        a = _pt_scalar(0.0, track=350.0)
        b = _pt_scalar(10.0, track=10.0)
        mid = _pt_scalar(5.0, track=0.0)
        assert track_deviation(mid, a, b) == pytest.approx(0.0)

    def test_missing_track_returns_zero(self) -> None:
        a = _pt_scalar(0.0, track=90.0)
        b = _pt_scalar(10.0, track=90.0)
        null_mid = _pt_scalar(5.0, track=None)
        assert track_deviation(null_mid, a, b) == 0.0


# ---------------------------------------------------------------------------
# simplify_series
# ---------------------------------------------------------------------------


class TestSimplifySeriesGs:
    def test_two_points_unchanged(self) -> None:
        sub = [_pt_scalar(0.0, gs=400.0), _pt_scalar(10.0, gs=500.0)]
        assert simplify_series(sub, 5.0, gs_deviation) == [0, 1]

    def test_constant_gs_only_endpoints(self) -> None:
        # Five points at constant gs — only endpoints needed.
        sub = [_pt_scalar(float(i), gs=450.0) for i in range(5)]
        assert simplify_series(sub, 5.0, gs_deviation) == [0, 4]

    def test_spike_kept(self) -> None:
        # Middle point spikes 20 kt above constant line → kept with epsilon=5.
        sub = [
            _pt_scalar(0.0, gs=400.0),
            _pt_scalar(5.0, gs=420.0),  # 20 kt above interpolation
            _pt_scalar(10.0, gs=400.0),
        ]
        kept = simplify_series(sub, 5.0, gs_deviation)
        assert 1 in kept

    def test_small_deviation_removed(self) -> None:
        # Middle point only 2 kt above line → removed with epsilon=5.
        sub = [
            _pt_scalar(0.0, gs=400.0),
            _pt_scalar(5.0, gs=402.0),
            _pt_scalar(10.0, gs=400.0),
        ]
        kept = simplify_series(sub, 5.0, gs_deviation)
        assert kept == [0, 2]

    def test_null_gs_not_selected(self) -> None:
        # Points with gs=None have deviation 0, so they're never selected as
        # the max-deviation point. Endpoints are always included though.
        sub = [
            _pt_scalar(0.0, gs=400.0),
            _pt_scalar(5.0, gs=None),
            _pt_scalar(10.0, gs=400.0),
        ]
        kept = simplify_series(sub, 5.0, gs_deviation)
        assert kept == [0, 2]
