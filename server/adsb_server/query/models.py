"""Pydantic models for the query DSL, request, and response."""

from __future__ import annotations

import base64
import json
from datetime import date, datetime
from typing import Any, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class FlightSummary(BaseModel):
    flight_id: str
    icao24: str
    callsign: str | None
    icao_type: str | None
    emitter_category: str | None
    start_ts: datetime
    end_ts: datetime
    start_point: dict[str, Any]
    end_point: dict[str, Any]


class FlightDetail(FlightSummary):
    path: dict[str, Any]
    timestamps: list[float]
    path_tracks: list[int]
    squawk_runs: list[list[Any]]
    raw_point_count: int
    ingest_batch_date: date


class QueryResponse(BaseModel):
    flights: list[FlightSummary]
    cursor: str | None
    sampled: bool = False


# ---------------------------------------------------------------------------
# Cursor encoding / decoding
# ---------------------------------------------------------------------------


def encode_cursor(start_ts: datetime, icao24: str) -> str:
    """Encode (start_ts, icao24) as URL-safe base64 JSON."""
    payload = {"t": start_ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "i": icao24}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode a cursor string into (start_ts, icao24)."""
    payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    return datetime.fromisoformat(payload["t"]), payload["i"]


# ---------------------------------------------------------------------------
# DSL predicate models — leaf types first
# ---------------------------------------------------------------------------


class SpatialPredicateValue(BaseModel):
    geometry: dict[str, Any]
    altitude_min_ft: float | None = None
    altitude_max_ft: float | None = None


class TrajectoryIntersects(BaseModel):
    trajectory_intersects: SpatialPredicateValue


class TrajectoryWithin(BaseModel):
    trajectory_within: SpatialPredicateValue


class TrajectoryDisjoint(BaseModel):
    trajectory_disjoint: SpatialPredicateValue


class StartsWithin(BaseModel):
    # Accepts a geometry object OR a time window {"from": ..., "to": ...}
    starts_within: dict[str, Any]


class EndsWithin(BaseModel):
    # Accepts a geometry object OR a time window {"from": ..., "to": ...}
    ends_within: dict[str, Any]


class IcaoType(BaseModel):
    icao_type: list[str]


class EmitterCategory(BaseModel):
    emitter_category: list[str]


class CallsignMatches(BaseModel):
    callsign_matches: str


class DurationValue(BaseModel):
    min_s: float | None = None
    max_s: float | None = None


class Duration(BaseModel):
    duration: DurationValue


# ---------------------------------------------------------------------------
# Recursive (compound) predicates — defined after leaf types
# ---------------------------------------------------------------------------


class AndPredicate(BaseModel):
    and_: list[Predicate] = Field(alias="and")

    model_config = {"populate_by_name": True}


class OrPredicate(BaseModel):
    or_: list[Predicate] = Field(alias="or")

    model_config = {"populate_by_name": True}


class NotPredicate(BaseModel):
    not_: Predicate = Field(alias="not")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Union of all predicate types
# ---------------------------------------------------------------------------

Predicate = Union[
    TrajectoryIntersects,
    TrajectoryWithin,
    TrajectoryDisjoint,
    StartsWithin,
    EndsWithin,
    IcaoType,
    EmitterCategory,
    CallsignMatches,
    Duration,
    AndPredicate,
    OrPredicate,
    NotPredicate,
]

# Rebuild models that reference Predicate recursively
AndPredicate.model_rebuild()
OrPredicate.model_rebuild()
NotPredicate.model_rebuild()


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    match: Predicate | None = None
    limit: int = Field(100, ge=1, le=10000)
    cursor: str | None = None
    # accepted but unused in v1:
    select: list[str] | None = None
    order_by: list[dict[str, str]] | None = None
