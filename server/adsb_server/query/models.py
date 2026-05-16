"""Pydantic models for the query DSL, request, and response."""

from __future__ import annotations

import base64
import json
from datetime import date, datetime, timedelta
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


class GeoJSONMultiLineStringZ(BaseModel):
    """GeoJSON MultiLineString with altitude on every vertex, as returned in flight path fields.

    Each element of `coordinates` is one contiguous sub-sequence of ADS-B coverage.
    Gaps between sub-sequences (e.g. oceanic blackout) are explicit: no interpolation
    is performed across them.
    """

    type: Literal["MultiLineString"]
    coordinates: list[list[tuple[float, float, float]]] = Field(
        description="List of sub-sequences; each is a list of `[longitude, latitude, altitude_ft]` vertices."  # noqa: E501
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
    registration: str | None = Field(
        description="Aircraft registration mark (tail number), from the airframes reference table. "
        "Null when the icao24 is not in the database.",
        examples=["G-EUOF"],
    )
    model: str | None = Field(
        description="Aircraft model description from the airframes reference table. "
        "Null when the icao24 is not in the database.",
        examples=["AIRBUS A-319"],
    )
    year: int | None = Field(
        description="Year of manufacture from the airframes reference table. "
        "Null when unknown or not in the database.",
        examples=[2003],
    )
    operator: str | None = Field(
        description="Owner or operator name from the airframes reference table. "
        "Null when unknown or not in the database.",
        examples=["British Airways"],
    )
    start_ts: datetime = Field(
        description="UTC timestamp of the first observed position in this leg."
    )
    end_ts: datetime = Field(description="UTC timestamp of the last observed position in this leg.")
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
    path: GeoJSONMultiLineStringZ | None = Field(
        default=None,
        description="Simplified flight path as a GeoJSON MultiLineString. "
        "Each element of `coordinates` is one contiguous sub-sequence of ADS-B coverage. "
        "Coordinates are `[longitude, latitude, altitude_ft]`. "
        "Altitude is pressure altitude in feet (QNH correction not applied). "
        "Ground-roll points are excluded. "
        "Simplified using two-pass TD-TR: spatial pass with ε=50 m (cross-track error), "
        "then altitude pass with ε=100 ft on the surviving vertices. "
        "Squawk change points are always preserved and divide simplification intervals. "
        "Coverage gaps >60 s produce separate sub-sequences with no interpolation across them. "
        "Omitted when the request sets `include_path` to false.",
        examples=[
            {
                "type": "MultiLineString",
                "coordinates": [
                    [
                        [-0.1275, 51.5072, 35000.0],
                        [-1.2, 52.5, 36000.0],
                    ],
                    [
                        [-30.0, 55.0, 37000.0],
                        [-52.0, 47.0, 37000.0],
                    ],
                ],
            }
        ],
    )
    timestamps: list[list[float]] | None = Field(
        default=None,
        description="Unix epoch seconds (UTC) for each vertex in `path.coordinates`, "
        "structured as a list of sub-sequences matching `path.coordinates`. "
        "`timestamps[i][j]` is the timestamp for `path.coordinates[i][j]`. "
        "Omitted when `include_path` is false.",
        examples=[[[1743501600.0, 1743505200.0], [1743530000.0, 1743540000.0]]],
    )
    path_tracks: list[list[list[float]]] | None = Field(
        default=None,
        description="Ground track (heading) timeseries, structured as a list of sub-sequences "
        "matching `path.coordinates`. Each sub-sequence is `[[unix_epoch_s, degrees_0_359], ...]`. "
        "Rounded to the nearest integer degree. "
        "Derived from the path-simplified points, then further reduced by TD-TR with ε=5°. "
        "Step-interpolated: forward-fill each entry to the next within each sub-sequence. "
        "Timestamps are independent of `timestamps` (different simplification pass). "
        "Omitted when `include_path` is false.",
        examples=[[[[1743501600.0, 90], [1743505200.0, 315]]]],
    )
    path_gs: list[list[list[float]]] | None = Field(
        default=None,
        description="Ground speed timeseries, structured as a list of sub-sequences "
        "matching `path.coordinates`. Each sub-sequence is `[[unix_epoch_s, knots], ...]`. "
        "Rounded to the nearest integer knot. "
        "Derived from the path-simplified points, then further reduced by TD-TR with ε=5 kt. "
        "Step-interpolated: forward-fill each entry to the next within each sub-sequence. "
        "Null when no ground speed data was available for this flight.",
        examples=[[[[1743501600.0, 450], [1743505200.0, 460]]]],
    )
    path_vr: list[list[list[float]]] | None = Field(
        default=None,
        description="Vertical rate timeseries, structured as a list of sub-sequences "
        "matching `path.coordinates`. Each sub-sequence is `[[unix_epoch_s, fpm], ...]`. "
        "Rounded to the nearest integer fpm. Positive = climbing, negative = descending. "
        "Derived from the path-simplified points, then further reduced by TD-TR with ε=100 fpm. "
        "Step-interpolated: forward-fill each entry to the next within each sub-sequence. "
        "Null when no vertical rate data was available for this flight.",
        examples=[[[[1743501600.0, 0], [1743505200.0, -512]]]],
    )
    path_ias: list[list[list[float]]] | None = Field(
        default=None,
        description="Indicated airspeed timeseries, structured as a list of sub-sequences "
        "matching `path.coordinates`. Each sub-sequence is `[[unix_epoch_s, knots], ...]`. "
        "Rounded to the nearest integer knot. "
        "Derived from the path-simplified points, then further reduced by TD-TR with ε=5 kt. "
        "Sparse: only available for aircraft broadcasting Mode S EHS (~27% of flights). "
        "Step-interpolated: forward-fill each entry to the next within each sub-sequence. "
        "Null when no IAS data was available for this flight.",
        examples=[[[[1743501600.0, 275]]]],
    )
    squawk_runs: list[list[tuple[float, str]]] | None = Field(
        default=None,
        description="Run-length encoding of transponder squawk codes, structured as a list of "
        "sub-sequences matching `path.coordinates`. "
        "Each sub-sequence is `[[unix_timestamp, squawk_code], ...]` marking code changes. "
        "Forward-fill from each entry to the next within a sub-sequence. "
        "Omitted when `include_path` is false.",
        examples=[[[[1743501600.0, "1234"], [1743508800.0, "1234"]]]],
    )
    alt_correction_ft: list[list[list[float]]] | None = Field(
        default=None,
        description="QNH altitude correction timeseries, structured as a list of sub-sequences "
        "matching `path.coordinates`. Each sub-sequence is `[[unix_epoch_s, correction_ft], ...]`. "
        "Step-interpolated: forward-fill each entry to the next within each sub-sequence. "
        "Add to the pressure altitude from `path.coordinates[i][j][2]` to obtain feet MSL. "
        "Null when no correction data was available at ingestion time.",
        examples=[[[[1743501600.0, 14.5], [1743505200.0, 14.5]]]],
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
        description=(
            "Earliest date for which flight data is available, or null if the table is empty."
        ),
        examples=["2025-01-01"],
    )
    last_date: date | None = Field(
        description=(
            "Most recent date for which flight data is available, or null if the table is empty."
        ),
        examples=["2026-05-01"],
    )


class IcaoTypeStat(BaseModel):
    """Flight count and model name for one ICAO type designator over a date range."""

    icao_type: str = Field(
        description="ICAO aircraft type designator (e.g. `B738`).",
        examples=["B738"],
    )
    model: str | None = Field(
        description="Most common model description from the airframes table, or null if unknown.",
        examples=["BOEING 737-800"],
    )
    count: int = Field(
        description="Total number of flights of this type in the requested date range.",
        examples=[1234],
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
    coordinates: list[list[list[float]]] = Field(
        description="Array of LineString coordinate arrays."
    )


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
    coordinates: list[list[list[list[float]]]] = Field(
        description="Array of Polygon coordinate arrays."
    )


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
    altitude_min: float | None = Field(
        default=None,
        description="Lower altitude bound (inclusive). "
        "Interpretation depends on `altitude_min_ref`.",
    )
    altitude_min_ref: Literal["fl", "ft"] = Field(
        default="ft",
        description=(
            "Reference system for `altitude_min`. "
            "`'fl'`: flight level (e.g. `100` = FL100 = 10 000 ft pressure altitude). "
            "`'ft'` (default): feet MSL using the stored QNH correction."
        ),
    )
    altitude_max: float | None = Field(
        default=None,
        description="Upper altitude bound (inclusive). "
        "Interpretation depends on `altitude_max_ref`.",
    )
    altitude_max_ref: Literal["fl", "ft"] = Field(
        default="ft",
        description=(
            "Reference system for `altitude_max`. "
            "`'fl'`: flight level (e.g. `100` = FL100 = 10 000 ft pressure altitude). "
            "`'ft'` (default): feet MSL using the stored QNH correction."
        ),
    )
    time_from: datetime | None = Field(
        default=None,
        description="Inclusive lower bound on the time window. "
        "When combined with `geometry` or altitude, constrains the intersection to "
        "occur within this window. Without geometry/altitude, filters by activity "
        "window (end_ts >= time_from).",
    )
    time_to: datetime | None = Field(
        default=None,
        description="Exclusive upper bound on the time window. "
        "When combined with `geometry` or altitude, constrains the intersection to "
        "occur within this window. Without geometry/altitude, filters by activity "
        "window (start_ts < time_to).",
    )
    squawk_codes: list[str] | None = Field(
        default=None,
        description="Transponder squawk codes to match (OR semantics). "
        "When `geometry` is set, only squawk codes broadcast while the flight was "
        "inside the geometry (and within any altitude/time window) are checked. "
        "Without `geometry`, any code broadcast during the flight matches.",
        examples=[["7700", "7600"]],
    )
    dwell_min_s: float | None = Field(
        default=None,
        description="Minimum time the flight must spend inside the geometry (seconds, inclusive). "
        "Measured as the total duration of the path clipped to the geometry plus any "
        "altitude and time constraints. Requires `geometry`.",
    )
    dwell_max_s: float | None = Field(
        default=None,
        description="Maximum time the flight may spend inside the geometry (seconds, inclusive). "
        "Requires `geometry`.",
    )
    distance_min_m: float | None = Field(
        default=None,
        description=(
            "Minimum distance the flight must cover inside the geometry "
            "(metres, inclusive). Measured along the clipped path. Requires `geometry`."
        ),
    )
    distance_max_m: float | None = Field(
        default=None,
        description=(
            "Maximum distance the flight may cover inside the geometry "
            "(metres, inclusive). Requires `geometry`."
        ),
    )

    @model_validator(mode="after")
    def _require_at_least_one(self) -> SpatioTemporalAltitudeValue:
        if (
            self.geometry is None
            and self.altitude_min is None
            and self.altitude_max is None
            and self.time_from is None
            and self.time_to is None
            and not self.squawk_codes
            and self.dwell_min_s is None
            and self.dwell_max_s is None
            and self.distance_min_m is None
            and self.distance_max_m is None
        ):
            raise ValueError("at least one constraint must be set")
        return self

    @model_validator(mode="after")
    def _dwell_distance_require_geometry(self) -> SpatioTemporalAltitudeValue:
        if (
            self.dwell_min_s is not None
            or self.dwell_max_s is not None
            or self.distance_min_m is not None
            or self.distance_max_m is not None
        ) and self.geometry is None:
            raise ValueError(
                "dwell_min_s, dwell_max_s, distance_min_m, and distance_max_m require geometry"
            )
        return self


class TrajectoryIntersects(BaseModel):
    """Flights whose simplified path intersects the given constraints.

    When geometry, altitude, and/or time are combined, all constraints are applied
    simultaneously — the intersection must occur at the right altitude and within the
    time window, not just at any point during the flight. Squawk codes are similarly
    checked only at instants when the path was inside the geometry (if provided).
    """

    trajectory_intersects: SpatioTemporalAltitudeValue


class TrajectoryWithin(BaseModel):
    """Flights whose entire simplified path lies within the given geometry.

    Altitude and time constraints narrow the portion of the path that must lie within
    the geometry; squawk codes are checked only at instants when the path was inside
    the geometry (if provided).
    """

    trajectory_within: SpatioTemporalAltitudeValue


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

    min_s: float | None = Field(
        default=None, description="Minimum duration in seconds (inclusive)."
    )
    max_s: float | None = Field(
        default=None, description="Maximum duration in seconds (inclusive)."
    )


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

    or_: list[Predicate] = Field(
        alias="or", description="At least one of these predicates must match."
    )

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


_MAX_DATE_RANGE = timedelta(days=7)


class QueryRequest(BaseModel):
    """Request body for `POST /api/v1/query`."""

    start_from: datetime = Field(
        description="Inclusive lower bound on flight start time (`start_ts`). Required.",
        examples=["2025-03-25T00:00:00Z"],
    )
    start_to: datetime = Field(
        description="Exclusive upper bound on flight start time (`start_ts`). "
        "Must be strictly after `start_from` and within 7 days of it.",
        examples=["2025-04-01T00:00:00Z"],
    )
    match: Predicate | None = Field(
        default=None,
        description="Filter predicate. Omit or set to `null` to return all flights.",
    )
    limit: int = Field(
        default=100,
        ge=1,
        le=10000,
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

    @model_validator(mode="after")
    def _validate_start_range(self) -> QueryRequest:
        if self.start_to <= self.start_from:
            raise ValueError("start_to must be strictly after start_from")
        if self.start_to - self.start_from > _MAX_DATE_RANGE:
            raise ValueError("date range (start_to - start_from) must not exceed 7 days")
        return self
