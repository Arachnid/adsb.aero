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
    path_agl_ft: list[list[list[float]]] | None = Field(
        default=None,
        description="Above-ground-level (AGL) height timeseries, structured as a list of "
        "sub-sequences. Each sub-sequence is `[[unix_epoch_s, agl_ft], ...]`. "
        "Computed from pressure altitude + QNH correction - GLO-90 terrain elevation. "
        "Step-interpolated: forward-fill each entry to the next within each sub-sequence. "
        "Null when terrain data was unavailable at ingestion time.",
        examples=[[[[1743501600.0, 1200.0], [1743505200.0, 850.0]]]],
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
        description="Opaque continuation token. Present when the current window contained "
        "more results than `limit`; pass unchanged as `cursor` in the next request. "
        "`null` when the window was exhausted — use `window_from` as `end_date` to "
        "continue searching earlier windows."
    )
    window_from: datetime = Field(
        description="The inclusive lower bound on `start_ts` that was actually applied. "
        "Reflects the sliding window floor (cursor position minus `window_days`, "
        "or `start_from` if that is later). Pass this as `end_date` on the next "
        "request to continue searching the preceding window."
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


class Airport(BaseModel):
    """An airport from the OurAirports reference dataset."""

    ident: str = Field(description="OurAirports identifier (primary key).", examples=["EGLL"])
    type: str = Field(description="Airport type.", examples=["large_airport"])
    name: str = Field(description="Airport name.", examples=["London Heathrow Airport"])
    lon: float = Field(description="Longitude (WGS-84).", examples=[-0.461389])
    lat: float = Field(description="Latitude (WGS-84).", examples=[51.4775])
    elevation_ft: int | None = Field(description="Elevation in feet, or null.", examples=[83])
    iso_country: str = Field(description="ISO 3166-1 alpha-2 country code.", examples=["GB"])
    iso_region: str = Field(description="ISO 3166-2 region code.", examples=["GB-ENG"])
    municipality: str | None = Field(description="Nearest city or town.", examples=["London"])
    scheduled_service: bool = Field(
        description="True if the airport has scheduled commercial service."
    )
    icao_code: str | None = Field(
        description="ICAO 4-letter designator, or null.", examples=["EGLL"]
    )
    iata_code: str | None = Field(description="IATA 3-letter code, or null.", examples=["LHR"])


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


class EndpointWithinValue(BaseModel):
    """Spatial and/or temporal filter on departure and/or arrival point.

    At least one constraint must be provided.
    """

    mode: Literal["start", "end", "either", "both"] = Field(
        description="Which endpoint(s) to constrain: 'start' (departure only), 'end' (arrival only), "  # noqa: E501
        "'either' (departure OR arrival), "
        "or 'both' (departure AND arrival must satisfy their respective constraints).",
    )
    geometry: Geometry | None = Field(
        default=None,
        description="GeoJSON geometry or Circle to test the constrained endpoint(s) against. "
        "In 'both'/'either' mode the same geometry is applied to both departure and arrival points.",  # noqa: E501
    )
    start_time_from: datetime | None = Field(
        default=None,
        description="Inclusive lower bound on start_ts. Applied when mode is 'start', 'either', or 'both'.",  # noqa: E501
    )
    start_time_to: datetime | None = Field(
        default=None,
        description="Exclusive upper bound on start_ts. Applied when mode is 'start', 'either', or 'both'.",  # noqa: E501
    )
    end_time_from: datetime | None = Field(
        default=None,
        description="Inclusive lower bound on end_ts. Applied when mode is 'end', 'either', or 'both'.",  # noqa: E501
    )
    end_time_to: datetime | None = Field(
        default=None,
        description="Exclusive upper bound on end_ts. Applied when mode is 'end', 'either', or 'both'.",  # noqa: E501
    )

    @model_validator(mode="after")
    def _require_at_least_one(self) -> EndpointWithinValue:
        if (
            self.geometry is None
            and self.start_time_from is None
            and self.start_time_to is None
            and self.end_time_from is None
            and self.end_time_to is None
        ):
            raise ValueError("at least one of geometry or time constraints must be set")
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
    agl_min_ft: float | None = Field(
        default=None,
        description="Lower AGL height bound (inclusive) in feet. "
        "In `trajectory_intersects`: flight was ever at AGL ≥ this value "
        "(scoped to the geometry when one is provided). "
        "In `trajectory_within`: AGL was never below this value. "
        "Only matches flights for which AGL data was computed.",
    )
    agl_max_ft: float | None = Field(
        default=None,
        description="Upper AGL height bound (inclusive) in feet. "
        "In `trajectory_intersects`: flight ever had AGL ≤ this value "
        "(scoped to the geometry when one is provided). "
        "In `trajectory_within`: AGL never exceeded this value. "
        "Only matches flights for which AGL data was computed.",
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
            and self.agl_min_ft is None
            and self.agl_max_ft is None
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


class EndpointWithin(BaseModel):
    """Flights whose departure and/or arrival point falls within the given geometry and/or time window."""  # noqa: E501

    endpoint_within: EndpointWithinValue = Field(
        description="Spatial and/or temporal constraints on the departure and/or arrival point."
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


class CallsignPrefix(BaseModel):
    """Flights whose callsign starts with the given prefix."""

    callsign_prefix: str = Field(
        description="Case-sensitive prefix matched against the callsign. "
        "Flights with a null callsign never match.",
        examples=["BAW"],
    )


class RegistrationPrefix(BaseModel):
    """Flights whose aircraft registration starts with the given prefix."""

    registration_prefix: str = Field(
        description="Case-sensitive prefix matched against the aircraft registration. "
        "Flights without a linked airframe record never match.",
        examples=["G-"],
    )


class Icao24(BaseModel):
    """Flights operated by one of the given ICAO 24-bit aircraft addresses."""

    icao24: list[str] = Field(
        description="List of ICAO 24-bit addresses (6 hex chars, lower-case) to match. "
        "OR semantics.",
        examples=[["a0b1c2"]],
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
    | EndpointWithin
    | IcaoType
    | EmitterCategory
    | CallsignPrefix
    | RegistrationPrefix
    | Icao24
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

    end_date: datetime = Field(
        description="Exclusive upper bound on flight start time (`start_ts`). "
        "The query returns flights whose `start_ts` is strictly before this value. "
        "Defaults to the most recent date with data.",
        examples=["2025-04-02T00:00:00Z"],
    )
    start_from: datetime | None = Field(
        default=None,
        description="Optional inclusive lower bound on `start_ts`. "
        "When set, overrides the automatic window floor if it falls later. "
        "Must be strictly before `end_date`.",
        examples=["2025-03-01T00:00:00Z"],
    )
    window_days: int = Field(
        default=7,
        ge=1,
        le=7,
        description="Size of the sliding search window in days, measured back from the "
        "current cursor position (or `end_date` on the first page). "
        "Combined with keyset pagination this lets callers walk back through history "
        "one window at a time by passing the previous response's `window_from` as the "
        "next `end_date`.",
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
    def _validate_dates(self) -> QueryRequest:
        if self.start_from is not None and self.start_from >= self.end_date:
            raise ValueError("start_from must be strictly before end_date")
        return self
