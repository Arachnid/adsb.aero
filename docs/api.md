# adsb.aero API Reference

## Base URL

All endpoints are served under `/api/v1/` (e.g. `http://localhost:8000/api/v1/` in development).

No authentication is required.

---

## Endpoints

### `GET /api/v1/health`

Returns `{"status": "ok"}` when the server is running.

---

### `POST /api/v1/query`

Query flights matching a filter predicate. Returns a paginated list of flight summaries.

**Request body**

```json
{
  "match": <predicate | null>,
  "limit": 100,
  "cursor": "<opaque string | null>"
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `match` | Predicate | `null` | Filter expression. Omit or set to `null` to return all flights. |
| `limit` | integer | `100` | Max results per page. Range: 1–10000. |
| `cursor` | string | `null` | Continuation token from the previous page's `cursor` field. |

**Response body**

```json
{
  "flights": [<FlightSummary>, ...],
  "cursor": "<string | null>"
}
```

`cursor` is `null` when there are no more pages. Pass it unchanged as `cursor` in the next request to retrieve the next page. Results are ordered by `start_ts` descending, then `icao24` descending.

**FlightSummary object**

```json
{
  "flight_id": "aabbcc:2025-04-01T10:00:00Z",
  "icao24": "aabbcc",
  "callsign": "BAW123",
  "icao_type": "B738",
  "emitter_category": "A3",
  "start_ts": "2025-04-01T10:00:00Z",
  "end_ts": "2025-04-01T12:00:00Z",
  "start_point": {"type": "Point", "coordinates": [-0.1275, 51.5072, 35000.0]},
  "end_point":   {"type": "Point", "coordinates": [-2.2667, 53.4667, 35000.0]}
}
```

| Field | Type | Notes |
|---|---|---|
| `flight_id` | string | Stable identifier: `<icao24>:<start_ts_utc>`. Use this to fetch the full detail. |
| `icao24` | string | 6-hex Mode S address. |
| `callsign` | string \| null | Most common callsign observed during the flight. |
| `icao_type` | string \| null | ICAO aircraft type designator (e.g. `B738`, `A320`). |
| `emitter_category` | string \| null | ADS-B emitter category (e.g. `A3` = large aircraft). |
| `start_ts` / `end_ts` | ISO 8601 UTC | First and last observed timestamps for this leg. |
| `start_point` / `end_point` | GeoJSON Point | First and last position. Coordinates are `[lon, lat, altitude_ft]`. |

---

### `GET /api/v1/flights/{flight_id}`

Fetch the full trajectory for a single flight.

**Path parameter**

`flight_id` — the `flight_id` string returned by `/api/v1/query`, e.g. `aabbcc:2025-04-01T10:00:00Z`.

**Response body** — a **FlightDetail** object, which extends FlightSummary with:

```json
{
  "flight_id": "aabbcc:2025-04-01T10:00:00Z",
  "icao24": "aabbcc",
  "callsign": "BAW123",
  "icao_type": "B738",
  "emitter_category": "A3",
  "start_ts": "2025-04-01T10:00:00Z",
  "end_ts": "2025-04-01T12:00:00Z",
  "start_point": {"type": "Point", "coordinates": [-0.1275, 51.5072, 35000.0]},
  "end_point":   {"type": "Point", "coordinates": [-2.2667, 53.4667, 35000.0]},
  "path": {
    "type": "LineString",
    "coordinates": [
      [-0.1275, 51.5072, 35000.0],
      [-1.2,    52.5,    36000.0],
      [-2.2667, 53.4667, 35000.0]
    ]
  },
  "timestamps": [1743501600.0, 1743505200.0, 1743508800.0],
  "path_tracks": [90, 315, 315],
  "squawk_runs": [[1743501600.0, "1234"]],
  "raw_point_count": 3000,
  "ingest_batch_date": "2025-04-01"
}
```

| Field | Type | Notes |
|---|---|---|
| `path` | GeoJSON LineString | Simplified flight path. Coordinates are `[lon, lat, altitude_ft]`. Altitude is pressure altitude in feet (QNH correction not yet applied). |
| `timestamps` | array of float | Unix epoch seconds (UTC) for each vertex in `path.coordinates`. Same length as `coordinates`. |
| `path_tracks` | array of integer | Magnetic track (heading) in degrees 0–359 for each vertex. Same length as `coordinates`. |
| `squawk_runs` | array of `[timestamp, squawk]` | Run-length encoding of transponder codes. Each entry marks the start of a new squawk code. `timestamp` is Unix epoch seconds. |
| `raw_point_count` | integer | Number of raw ADS-B messages ingested for this leg, including ground-roll points not in the path geometry. |
| `ingest_batch_date` | ISO 8601 date | The archive date this flight was ingested from. |

**Errors**

| Status | Condition |
|---|---|
| `404` | No flight exists for the given `flight_id`. |
| `422` | `flight_id` is malformed (missing `:` separator or invalid timestamp). |

---

## Query DSL

The `match` field in `POST /api/v1/query` accepts a **predicate** — a JSON object with exactly one key naming the predicate type.

### Geometry types

Several predicates accept a geometry object. Two geometry types are supported:

**GeoJSON Polygon** (and any other standard GeoJSON geometry):

```json
{
  "type": "Polygon",
  "coordinates": [[[-2, 50], [2, 50], [2, 52], [-2, 52], [-2, 50]]]
}
```

**Circle** (extension — not standard GeoJSON):

```json
{
  "type": "Circle",
  "coordinates": [-0.4543, 51.4775],
  "radius": 5000
}
```

`coordinates` is `[longitude, latitude]`. `radius` is in metres.

---

### Spatial predicates

All three path predicates share the same structure: a `geometry` field and optional altitude bounds. Both `altitude_min_ft` and `altitude_max_ft` are independently optional — you can supply either, neither, or both.

Altitude comparisons are against the bounding box of the simplified path, so they are an approximation rather than a precise per-point check.

#### `trajectory_intersects`

Flights whose path crosses the given geometry.

```json
{
  "trajectory_intersects": {
    "geometry": {
      "type": "Polygon",
      "coordinates": [[[-2, 50], [2, 50], [2, 52], [-2, 52], [-2, 50]]]
    },
    "altitude_min_ft": 10000,
    "altitude_max_ft": 40000
  }
}
```

---

#### `trajectory_within`

Flights whose entire path lies within the given geometry. Accepts the same optional altitude bounds.

```json
{
  "trajectory_within": {
    "geometry": {
      "type": "Polygon",
      "coordinates": [[[-2, 50], [2, 50], [2, 52], [-2, 52], [-2, 50]]]
    },
    "altitude_min_ft": 5000
  }
}
```

---

#### `trajectory_disjoint`

Flights whose path does not intersect the given geometry. Accepts the same optional altitude bounds.

```json
{
  "trajectory_disjoint": {
    "geometry": {
      "type": "Circle",
      "coordinates": [-0.4543, 51.4775],
      "radius": 20000
    },
    "altitude_max_ft": 18000
  }
}
```

---

### Departure and arrival predicates

`starts_within` and `ends_within` apply to the departure point / time and arrival point / time respectively. Each accepts either a **geometry** (spatial check) or a **time window** (temporal check). The value structure determines which interpretation is used.

#### Spatial: point within a geometry

```json
{"starts_within": {"type": "Circle", "coordinates": [-0.4543, 51.4775], "radius": 8000}}
```

```json
{"ends_within": {"type": "Polygon", "coordinates": [...]}}
```

The first or last position of the flight must fall within the given geometry.

#### Temporal: point within a time window

Use `"type": "TimeRange"` to filter by departure or arrival time. Both bounds are optional — omit `from` for "any time before `to`", omit `to` for "any time after `from`".

```json
{"starts_within": {"type": "TimeRange", "from": "2025-04-01T00:00:00Z", "to": "2025-04-02T00:00:00Z"}}
```

```json
{"ends_within": {"type": "TimeRange", "to": "2025-04-01T12:00:00Z"}}
```

`from` is inclusive; `to` is exclusive. `starts_within` filters on `start_ts`; `ends_within` filters on `end_ts`.

---

### Attribute predicates

#### `icao_type`

Flights by one or more ICAO type designators.

```json
{"icao_type": ["B738", "B737"]}
```

---

#### `emitter_category`

Flights by ADS-B emitter category code.

```json
{"emitter_category": ["A3", "A5"]}
```

---

#### `callsign_matches`

Flights whose callsign matches a POSIX regular expression (case-sensitive).

```json
{"callsign_matches": "^BAW"}
```

---

#### `duration`

Flights whose duration falls within the given bounds. Both `min_s` and `max_s` are independently optional.

```json
{"duration": {"min_s": 3600, "max_s": 14400}}
```

Duration is `end_ts - start_ts` in seconds.

---

### Logical predicates

#### `and`

All child predicates must be true.

```json
{
  "and": [
    {"icao_type": ["B738"]},
    {"ends_within": {"type": "Circle", "coordinates": [-0.4543, 51.4775], "radius": 10000}}
  ]
}
```

---

#### `or`

At least one child predicate must be true.

```json
{
  "or": [
    {"icao_type": ["B738"]},
    {"icao_type": ["A320"]}
  ]
}
```

---

#### `not`

Negates a child predicate.

```json
{"not": {"callsign_matches": "^[A-Z]{3}[0-9]"}}
```

Logical predicates can be nested arbitrarily deep.

---

## Pagination

`POST /api/v1/query` uses keyset-based cursor pagination.

1. Make an initial request with `cursor` omitted (or `null`).
2. If the response includes a non-null `cursor`, there are more results. Repeat the request with the same `match` and `limit`, passing the returned `cursor` value unchanged.
3. Stop when `cursor` is `null`.

The cursor is an opaque string. Do not attempt to construct or parse it.

---

## Examples

### All B737s landing at Heathrow on a given day

```bash
curl -s -X POST http://localhost:8000/api/v1/query \
  -H 'Content-Type: application/json' \
  -d '{
    "match": {
      "and": [
        {"icao_type": ["B738", "B737", "B737M"]},
        {"ends_within": {"type": "Circle", "coordinates": [-0.4543, 51.4775], "radius": 8000}},
        {"starts_within": {"type": "TimeRange", "from": "2025-04-01T00:00:00Z", "to": "2025-04-02T00:00:00Z"}}
      ]
    },
    "limit": 50
  }'
```

### Fetch full path for a flight

```bash
curl -s http://localhost:8000/api/v1/flights/aabbcc:2025-04-01T10:00:00Z
```

### Page through all flights over the UK yesterday

```bash
# First page
curl -s -X POST http://localhost:8000/api/v1/query \
  -H 'Content-Type: application/json' \
  -d '{
    "match": {"trajectory_intersects": {"geometry": {"type": "Polygon", "coordinates": [[[-8,49],[2,49],[2,61],[-8,61],[-8,49]]]}}},
    "limit": 500
  }'

# Subsequent pages: add "cursor": "<value from previous response>"
```
