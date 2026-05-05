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
    path_tracks: list[int]  # per-vertex track in degrees (0-359), same length as vertices
    squawk_runs: list[tuple[float, str]]  # [(unix_ts, squawk_code), ...] run-length encoding
    raw_point_count: int  # number of points before simplification
