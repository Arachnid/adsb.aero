"""Pydantic models for the query DSL, request, and response."""

from __future__ import annotations

import base64
import json
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Response geometry types
# ---------------------------------------------------------------------------


class GeoJSONPointZ(BaseModel):
    """GeoJSON Point with a mandatory altitude component, as returned in flight position fields."""

    type: Literal["Point"]
    coordinates: tuple[float, float, float] = Field(
        description="`[longitude, latitude, altitude_ft]`."
    )


class GeoJSONLineStringZ(BaseModel):
    """GeoJSON LineString with a mandatory altitude on every vertex, as returned in path fields."""

    type: Literal["LineString"]
    coordinates: list[tuple[float, float, float]] = Field(
        description="Sequence of `[longitude, latitude, altitude_ft]` vertices."
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class FlightSummary(BaseModel):
    """Core identity and bounding timestamps/positions for a single flight leg."""

    flight_id: str = Field(
        description="Stable identifier: `<icao24>:<start_ts_utc>`. "
        "Pass this to `GET /api/v1/flights/{flight_id}` to retrieve the full trajectory.",
        examples=["aabbcc:2025-04-01T10:00:00Z"],
    )
    icao24: str = Field(
        description="24-bit Mode S transponder address in lowercase hex.",
        examples=["aabbcc"],
    )
    callsign: str | None = Field(
        description="Most common callsign observed during the flight, or null if none was broadcast.",  # noqa: E501
        examples=["BAW123"],
    )
    icao_type: str | None = Field(
        description="ICAO aircraft type designator (e.g. `B738`, `A320`), or null if unknown.",
        examples=["B738"],
    )
    emitter_category: str | None = Field(
        description="ADS-B emitter category code (e.g. `A3` = large aircraft), or null if unknown.",
        examples=["A3"],
    )
    start_ts: datetime = Field(
        description="UTC timestamp of the first observed position in this leg."
    )
    end_ts: datetime = Field(
        description="UTC timestamp of the last observed position in this leg."
    )
    start_point: GeoJSONPointZ = Field(
        description="GeoJSON Point of the first observed position. "
        "Coordinates are `[longitude, latitude, altitude_ft]`.",
        examples=[{"type": "Point", "coordinates": [-0.1275, 51.5072, 35000.0]}],
    )
    end_point: GeoJSONPointZ = Field(
        description="GeoJSON Point of the last observed position. "
        "Coordinates are `[longitude, latitude, altitude_ft]`.",
        examples=[{"type": "Point", "coordinates": [-2.2667, 53.4667, 35000.0]}],
    )


class FlightDetail(FlightSummary):
    """Full trajectory detail for a single flight leg, extending FlightSummary."""

    point_count: int = Field(
        description="Number of vertices in the simplified path geometry. "
        "Always present, even when `include_path` is false."
    )
    path: GeoJSONLineStringZ | None = Field(
        default=None,
        description="Simplified flight path as a GeoJSON LineString. "
        "Coordinates are `[longitude, latitude, altitude_ft]`. "
        "Altitude is pressure altitude in feet (QNH correction not applied). "
        "Ground-roll points are excluded. "
        "Omitted when the request sets `include_path` to false.",
        examples=[{
            "type": "LineString",
            "coordinates": [
                [-0.1275, 51.5072, 35000.0],
                [-1.2, 52.5, 36000.0],
                [-2.2667, 53.4667, 35000.0],
            ],
        }],
    )
    timestamps: list[float] | None = Field(
        default=None,
        description="Unix epoch seconds (UTC) for each vertex in `path.coordinates`. "
        "Same length as `coordinates`. Omitted when `include_path` is false.",
        examples=[[1743501600.0, 1743505200.0, 1743508800.0]],
    )
    path_tracks: list[int] | None = Field(
        default=None,
        description="Magnetic track (heading) in degrees 0-359 for each vertex in `path.coordinates`. "  # noqa: E501
        "Same length as `coordinates`. Omitted when `include_path` is false.",
        examples=[[90, 315, 315]],
    )
    squawk_runs: list[tuple[float, str]] | None = Field(
        default=None,
        description="Run-length encoding of transponder squawk codes. "
        "Each entry is `[unix_timestamp, squawk_code]` and marks the start of a new code. "
        "Forward-fill from each entry to the next to determine the code in effect at any point. "
        "Omitted when `include_path` is false.",
        examples=[[[1743501600.0, "1234"]]],
    )
    raw_point_count: int = Field(
        description="Number of raw ADS-B messages ingested for this leg, "
        "including ground-roll points not present in the simplified path geometry."
    )
    ingest_batch_date: date = Field(
        description="Calendar date of the archive batch this flight was ingested from.",
        examples=["2025-04-01"],
    )


class QueryResponse(BaseModel):
    """Paginated list of flights matching a query."""

    flights: list[FlightDetail] = Field(
        description="Flights on this page, ordered by `start_ts` descending then `icao24` descending."  # noqa: E501
    )
    cursor: str | None = Field(
        description="Opaque continuation token. Pass unchanged as `cursor` in the next request "
        "to retrieve the next page. `null` when there are no more results."
    )


class DataRange(BaseModel):
    """Date range of available flight data."""

    first_date: date | None = Field(
        description="Earliest date for which flight data is available, or null if the table is empty.",
        examples=["2025-01-01"],
    )
    last_date: date | None = Field(
        description="Most recent date for which flight data is available, or null if the table is empty.",
        examples=["2026-05-01"],
    )


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
# Geometry types (standard GeoJSON + Circle extension)
# ---------------------------------------------------------------------------


class GeoJSONPoint(BaseModel):
    """GeoJSON Point geometry."""

    type: Literal["Point"]
    coordinates: list[float] = Field(
        description="`[longitude, latitude]` or `[longitude, latitude, altitude]`."
    )


class GeoJSONMultiPoint(BaseModel):
    """GeoJSON MultiPoint geometry."""

    type: Literal["MultiPoint"]
    coordinates: list[list[float]] = Field(description="Array of Point coordinate arrays.")


class GeoJSONLineString(BaseModel):
    """GeoJSON LineString geometry."""

    type: Literal["LineString"]
    coordinates: list[list[float]] = Field(description="Array of `[longitude, latitude]` pairs.")


class GeoJSONMultiLineString(BaseModel):
    """GeoJSON MultiLineString geometry."""

    type: Literal["MultiLineString"]
    coordinates: list[list[list[float]]] = Field(description="Array of LineString coordinate arrays.")  # noqa: E501


class GeoJSONPolygon(BaseModel):
    """GeoJSON Polygon geometry."""

    type: Literal["Polygon"]
    coordinates: list[list[list[float]]] = Field(
        description="Array of linear rings. First ring is the exterior boundary; "
        "subsequent rings are interior holes. Each ring is closed (first == last position)."
    )


class GeoJSONMultiPolygon(BaseModel):
    """GeoJSON MultiPolygon geometry."""

    type: Literal["MultiPolygon"]
    coordinates: list[list[list[list[float]]]] = Field(description="Array of Polygon coordinate arrays.")  # noqa: E501


class CircleGeometry(BaseModel):
    """Circle geometry extension (not part of the GeoJSON standard)."""

    type: Literal["Circle"]
    coordinates: list[float] = Field(description="`[longitude, latitude]` of the circle centre.")
    radius: float = Field(description="Radius in metres.", gt=0)


class GeoJSONGeometryCollection(BaseModel):
    """GeoJSON GeometryCollection — a heterogeneous collection of geometries."""

    type: Literal["GeometryCollection"]
    geometries: list[Geometry] = Field(description="Array of geometry objects.")


# Plain union (no Pydantic metadata) — use this in non-field type annotations.
AnyGeometry = (
    GeoJSONPoint
    | GeoJSONMultiPoint
    | GeoJSONLineString
    | GeoJSONMultiLineString
    | GeoJSONPolygon
    | GeoJSONMultiPolygon
    | GeoJSONGeometryCollection
    | CircleGeometry
)

# Discriminated union for use as a Pydantic model field.
Geometry = Annotated[AnyGeometry, Field(discriminator="type")]

# GeoJSONGeometryCollection.geometries references Geometry, so rebuild after Geometry is defined.
GeoJSONGeometryCollection.model_rebuild()


# ---------------------------------------------------------------------------
# DSL predicate models — leaf types first
# ---------------------------------------------------------------------------


class SpatioTemporalValue(BaseModel):
    """Spatial and/or temporal filter without altitude — used by starts_within / ends_within.

    At least one of geometry, time_from, or time_to must be provided.
    """

    geometry: Geometry | None = Field(
        default=None,
        description="GeoJSON geometry or Circle to test the departure/arrival point against. "
        "Omit for a time-only filter.",
    )
    time_from: datetime | None = Field(
        default=None,
        description="Inclusive lower bound on start_ts (starts_within) or end_ts (ends_within).",
    )
    time_to: datetime | None = Field(
        default=None,
        description="Exclusive upper bound on start_ts or end_ts.",
    )

    @model_validator(mode="after")
    def _require_at_least_one(self) -> SpatioTemporalValue:
        if self.geometry is None and self.time_from is None and self.time_to is None:
            raise ValueError("at least one of geometry, time_from, or time_to must be set")
        return self


class SpatioTemporalAltitudeValue(BaseModel):
    """Spatial, altitude, and/or temporal filter for trajectory predicates.

    At least one constraint must be provided.
    """

    geometry: Geometry | None = Field(
        default=None,
        description="GeoJSON geometry or Circle to test the flight path against. "
        "Omit for a time- or altitude-only filter.",
    )
    altitude_min_ft: float | None = Field(
        default=None,
        description="Minimum altitude bound in feet (inclusive). "
        "Compared against the bounding box of the simplified path — an approximation.",
    )
    altitude_max_ft: float | None = Field(
        default=None,
        description="Maximum altitude bound in feet (inclusive). "
        "Compared against the bounding box of the simplified path — an approximation.",
    )
    time_from: datetime | None = Field(
        default=None,
        description="Inclusive lower bound: the flight must still be active at this time "
        "(end_ts >= time_from).",
    )
    time_to: datetime | None = Field(
        default=None,
        description="Exclusive upper bound: the flight must have started by this time "
        "(start_ts < time_to).",
    )

    @model_validator(mode="after")
    def _require_at_least_one(self) -> SpatioTemporalAltitudeValue:
        if (
            self.geometry is None
            and self.altitude_min_ft is None
            and self.altitude_max_ft is None
            and self.time_from is None
            and self.time_to is None
        ):
            raise ValueError("at least one constraint must be set")
        return self


class TrajectoryIntersects(BaseModel):
    """Flights whose simplified path crosses the given geometry and/or were active during the given time window."""  # noqa: E501

    trajectory_intersects: SpatioTemporalAltitudeValue


class TrajectoryWithin(BaseModel):
    """Flights whose entire simplified path lies within the given geometry and/or were active during the given time window."""  # noqa: E501

    trajectory_within: SpatioTemporalAltitudeValue


class TrajectoryDisjoint(BaseModel):
    """Flights whose simplified path does not intersect the given geometry and/or were active during the given time window."""  # noqa: E501

    trajectory_disjoint: SpatioTemporalAltitudeValue


class StartsWithin(BaseModel):
    """Flights whose departure point falls within the given geometry and/or departs within the given time window."""  # noqa: E501

    starts_within: SpatioTemporalValue = Field(
        description="Spatial and/or temporal constraints on the departure point and time."
    )


class EndsWithin(BaseModel):
    """Flights whose arrival point falls within the given geometry and/or arrives within the given time window."""  # noqa: E501

    ends_within: SpatioTemporalValue = Field(
        description="Spatial and/or temporal constraints on the arrival point and time."
    )


class IcaoType(BaseModel):
    """Flights matching one or more ICAO aircraft type designators."""

    icao_type: list[str] = Field(
        description="List of ICAO type designators to match (case-sensitive). OR semantics.",
        examples=[["B738", "B737"]],
    )


class EmitterCategory(BaseModel):
    """Flights matching one or more ADS-B emitter category codes."""

    emitter_category: list[str] = Field(
        description="List of ADS-B emitter category codes to match. OR semantics.",
        examples=[["A3", "A5"]],
    )


class CallsignMatches(BaseModel):
    """Flights whose callsign matches a POSIX regular expression."""

    callsign_matches: str = Field(
        description="POSIX regular expression matched against the callsign (case-sensitive). "
        "Flights with a null callsign never match.",
        examples=["^BAW"],
    )


class DurationValue(BaseModel):
    """Bounds for a flight duration filter. Both bounds are optional."""

    min_s: float | None = Field(default=None, description="Minimum duration in seconds (inclusive).")  # noqa: E501
    max_s: float | None = Field(default=None, description="Maximum duration in seconds (inclusive).")  # noqa: E501


class Duration(BaseModel):
    """Flights whose duration (`end_ts - start_ts`) falls within the given bounds."""

    duration: DurationValue


# ---------------------------------------------------------------------------
# Recursive (compound) predicates — defined after leaf types
# ---------------------------------------------------------------------------


class AndPredicate(BaseModel):
    """All child predicates must be true (logical AND)."""

    and_: list[Predicate] = Field(alias="and", description="All of these predicates must match.")

    model_config = {"populate_by_name": True}


class OrPredicate(BaseModel):
    """At least one child predicate must be true (logical OR)."""

    or_: list[Predicate] = Field(alias="or", description="At least one of these predicates must match.")  # noqa: E501

    model_config = {"populate_by_name": True}


class NotPredicate(BaseModel):
    """Negates a child predicate (logical NOT)."""

    not_: Predicate = Field(alias="not", description="This predicate must not match.")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Union of all predicate types
# ---------------------------------------------------------------------------

Predicate = (
    TrajectoryIntersects
    | TrajectoryWithin
    | TrajectoryDisjoint
    | StartsWithin
    | EndsWithin
    | IcaoType
    | EmitterCategory
    | CallsignMatches
    | Duration
    | AndPredicate
    | OrPredicate
    | NotPredicate
)

# Rebuild models that reference Predicate recursively
AndPredicate.model_rebuild()
OrPredicate.model_rebuild()
NotPredicate.model_rebuild()


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    """Request body for `POST /api/v1/query`."""

    match: Predicate | None = Field(
        default=None,
        description="Filter predicate. Omit or set to `null` to return all flights.",
    )
    limit: int = Field(
        default=100, ge=1, le=10000,
        description="Maximum number of flights to return per page.",
    )
    cursor: str | None = Field(
        default=None,
        description="Continuation token from the previous page's `cursor` field.",
    )
    include_path: bool = Field(
        default=True,
        description="Whether to include `path`, `timestamps`, `path_tracks`, and `squawk_runs` in each result. "  # noqa: E501
        "Set to `false` for lightweight listing queries where trajectory data is not needed.",
    )
