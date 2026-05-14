"""Data models for the ADS-B ingestion pipeline."""

from __future__ import annotations

import dataclasses
from datetime import datetime  # noqa: TC003


@dataclasses.dataclass
class RawPoint:
    """A single ADS-B position report."""

    ts: float
    lat: float
    lon: float
    alt_baro: float | None  # None means ground or missing
    track: float | None
    squawk: str | None
    new_leg: bool
    callsign: str | None  # stripped, from aircraft_obj["flight"]
    emitter_category: str | None  # from aircraft_obj["category"]
    gs: float | None = None   # ground speed in knots
    vr: float | None = None   # vertical rate in fpm (barometric, or geometric when flags & 4)
    ias: float | None = None  # indicated airspeed in knots (Mode S EHS, sparse)
    alt_baro_interpolated: bool = False  # True when alt_baro was filled by interpolation
    track_interpolated: bool = False  # True when track was filled by interpolation


@dataclasses.dataclass
class TraceHeader:
    """Top-level metadata from a trace JSON file."""

    icao24: str
    icao_type: str | None


@dataclasses.dataclass
class RawFlight:
    """A candidate flight segment, before simplification."""

    icao24: str
    callsign: str | None
    icao_type: str | None
    emitter_category: str | None
    points: list[RawPoint]  # sorted by ts, non-empty


@dataclasses.dataclass
class FinalizedFlight:
    """A flight ready to be written to the database."""

    icao24: str
    callsign: str | None
    icao_type: str | None
    emitter_category: str | None
    start_ts: datetime  # UTC
    end_ts: datetime  # UTC
    vertices: list[tuple[float, float, float, float]]  # (lon, lat, alt_ft, ts)
    squawk_runs: list[tuple[float, str]]  # [(unix_ts, squawk_code), ...] run-length encoding
    raw_point_count: int  # number of points before simplification
    # Scalar time-series derived from points surviving path simplification,
    # then further reduced by their own TD-TR pass. Empty list → NULL column.
    path_tracks_series: list[tuple[float, float]]   # [(ts, degrees), ...]  NOT NULL in DB
    path_gs_series: list[tuple[float, float]]        # [(ts, knots), ...]
    path_vr_series: list[tuple[float, float]]        # [(ts, fpm), ...]
    path_ias_series: list[tuple[float, float]]       # [(ts, knots), ...]
