# ADS-B historical query platform — design spec

A web-based tool for querying and visualising historical ADS-B trace data. Domain: adsb.aero. Single-operator project, designed for one dedicated server with cloud-portability later.

## Project goal

Ingest the adsb.lol global archive at country-to-continent scale, store flight trajectories with rich metadata, and serve a map-based query UI that supports complex spatial-temporal-attribute queries.

Use cases include "where do people arrive at this airfield from", "what routes do people take from A to B", and arbitrary multi-region queries with per-region predicates (altitude bands, dwell time, aircraft type). "Arrives at airfield X" is expressed as "ends within radius R of point P", not as a distinct origin/destination concept.

## Technology stack

- **Database**: PostgreSQL 17 with PostGIS 3.5+ and MobilityDB. Native partitioning on the trace partitions. Single instance. Containerised.
- **Ingestion**: Python. A long-running scheduler process discovers new adsb.lol releases and runs batch ingestion directly. Multiprocessing for per-aircraft parallelism within a batch (ProcessPoolExecutor).
- **API**: Python with FastAPI and asyncpg. Custom JSON DSL for query expression. Pydantic models for request/response validation.
- **Frontend**: TypeScript + React + Vite + MapLibre GL JS + deck.gl. State via React's built-in primitives plus TanStack Query for server state.
- **Deployment**: Docker Compose for single-host. All services in containers. Configuration via environment variables. Same images deployable to managed Kubernetes/Cloud Run later.
- **Hosting**: OVH dedicated server (EPYC 4244P, 64GB RAM, 4×960GB NVMe in RAID 5 giving ~2.88TB usable). Postgres tuned for NVMe (`random_page_cost=1.1`, `effective_io_concurrency=256`, `shared_buffers=16GB`, etc.). Backups, DR, and machine-level operational concerns are handled via OVHcloud's services and outside the scope of this spec.
- **Observability**: Sentry for errors.

## Altitude representation

All altitudes are stored internally as **pressure altitudes** (referenced to 1013.25 hPa) — exactly what ADS-B broadcasts. QNH-corrected altitude is a derived view, computed at query time when needed.

Rationale: pressure altitude is the source of truth from the aircraft. QNH correction depends on NWP model output (currently GFS) which is fetched after the fact. Storing pressure altitudes lets us:

- Ingest flights without waiting for pressure data
- Re-run corrections later if methodology changes (different reanalysis source, different interpolation)
- Avoid baking a derived value into permanent storage

GFS MSLP data is fetched via Herbie (cfgrib backend) and cached as NetCDFs. At ingest time the correction `correction_ft = (mslp_hpa - 1013.25) × 27.3` is computed per vertex and stored as the `alt_correction_ft` temporal series on the flight row. For typical UK conditions the correction is <300ft.

At query time, altitude bounds can be specified in feet MSL (`ref: "ft"`, QNH-corrected using the stored `alt_correction_ft`) or flight levels (`ref: "fl"`, always pressure altitude: FL × 100 ft). When `ref: "ft"` is used, the stored `alt_correction_ft` is added to the trajectory before comparison — no NWP join is needed at query time because corrections are baked into the flight row at ingest. Flights without correction data fall back to pressure altitude for `ref: "ft"` queries (±300 ft uncertainty).

## Data model

### flights — finalised trajectories

Single table holding completed flights. One row per flight.

Primary key: `(icao24, start_ts)` composite. The `flight_id` used in the API (`icao24:start_ts_utc`, e.g. `4ca7b3:2025-04-15T14:32:18Z`) is derived at query time and is not a stored column. Stable across re-ingestion of the same source data.

Key columns:

- `icao24` VARCHAR NOT NULL — Mode S transponder address
- `callsign` VARCHAR
- `icao_type` VARCHAR — aircraft type designator from Doc 8643
- `emitter_category` VARCHAR — ADS-B emitter category. When the trace doesn't broadcast it, looked up from a Doc 8643 → emitter category mapping table at ingest. Nullable only as a last resort when neither is available.
- `start_ts`, `end_ts` TIMESTAMPTZ
- `path` tgeompoint NOT NULL — MobilityDB temporal geometry point sequence. SRID 4326; Z=pressure altitude in feet; the native temporal dimension carries per-instant timestamps. `startValue(path)` and `endValue(path)` give the first and last positions (used for starts/ends-within queries).
- `path_tracks` tint — track angle in degrees 0–359, as a MobilityDB stepwise temporal integer series. Simplified independently with its own epsilon.
- `path_gs` tint — ground speed in knots (MobilityDB stepwise temporal integer). Null if not broadcast.
- `path_vr` tint — vertical rate in fpm (MobilityDB stepwise temporal integer). Null if not broadcast.
- `path_ias` tint — indicated airspeed in knots (MobilityDB stepwise temporal integer). Sparse: present for ~27% of flights that broadcast IAS.
- `alt_correction_ft` tfloat — QNH altitude correction timeseries in feet (MobilityDB stepwise temporal float). Computed at ingest from GFS MSLP. Null if GFS data was not available for the flight's time window.
- `squawk_seq` ttext — transponder squawk code timeseries (MobilityDB stepwise temporal text). Each instant marks the start of a new code. Run-length encoded; most flights have 1–3 distinct runs.
- `alt_min_pressure_ft`, `alt_max_pressure_ft` FLOAT4 — min/max pressure altitude over the trajectory. Stored as generated columns derived from `getZ(path)`.
- `alt_min_qnh_ft`, `alt_max_qnh_ft` FLOAT4 — min/max QNH-corrected altitude. Stored as generated columns (`getZ(path) + alt_correction_ft`, falling back to pressure altitude if correction is unavailable).
- `raw_point_count` INT — airborne point count before simplification.
- `ingest_batch_date` DATE — provenance
- `path_h3` h3index[] — H3 res-4 cells covering the trajectory, computed at ingest. Drives the GIN spatial pre-filter.
- `squawk_codes` text[] — distinct squawk codes seen on the flight, computed at ingest. Drives the GIN squawk pre-filter.

`start_point` and `end_point` are not stored columns — they are derived at query time via `startValue(path)::geometry` and `endValue(path)::geometry`, with expression GIST indexes to support radius queries. Timestamps are likewise not a separate column: they are extracted from `path`'s native temporal dimension during API serialisation. Mean speed is derivable from the start/end positions and timestamps.

VFR/IFR classification is **not** in this schema. It would require QNH-corrected altitudes for the airspace test, and it's a derived attribute that can be added later as a separate column or table once the methodology is stable.

Indexes:

- GIN on `path_h3 h3index[]` — primary spatial pre-filter for trajectory queries. The query compiler converts the query geometry to a set of H3 res-4 cells and uses `path_h3 && $cells::h3index[]` to narrow candidates before the expensive `eIntersects` check.
- GIN on `squawk_codes text[]` — pre-filter for squawk code queries.
- Expression GIST on `(startValue(path)::geometry)` and `(endValue(path)::geometry)` — supports radius queries against departure/arrival points.
- B-tree on `alt_min_pressure_ft`, `alt_max_pressure_ft`, `alt_min_qnh_ft`, `alt_max_qnh_ft` — fast range scans for altitude-band filters.
- B-tree on `start_ts`, `end_ts`, `icao24`, `icao_type`, `emitter_category`

Partitioned by `start_ts` using native Postgres declarative partitioning. Weekly partitions (7-day intervals, starting from 2022-01-03). `pg_partman` automates partition creation; ~260 partitions for 5 years of data, with PostgreSQL 17's O(log n) pruning keeping planning overhead negligible.

Geometry is **already simplified** at ingest using 2D TD-TR (synchronised Euclidean distance) for spatial fidelity at ε=50m, plus an altitude pass that recursively inserts vertices into each TD-TR-kept inter-vertex span wherever altitude interpolation exceeds ε=100ft (against pressure altitude). Stored result is a `tgeompoint` sequence with vertices that satisfy both spatial and altitude bounds.

Each scalar time series (`path_tracks`, `path_gs`, `path_vr`, `path_ias`) is then independently simplified using TD-TR on the subset of raw points that survived the geometry simplification, with series-specific epsilon values (track: 5°, GS: 5 kt, VR: 100 fpm, IAS: 5 kt). Only vertices where the series value deviates from linear interpolation beyond the epsilon are retained. None-valued points are excluded from each series. The result is a sparse temporal series per scalar, stored as MobilityDB `tint` (stepwise integer).

### flight_staging — in-progress flights

Holds the serialised in-progress flight state for each batch. One row per batch date.

Columns:

- `batch_date` DATE PRIMARY KEY — the date of the batch that wrote this row
- `staging_data` BYTEA — compressed pickle of all in-progress flight state from the previous batch run. Unpacked at the start of the next batch and merged with the new tarball's points.

The per-batch blob replaces the per-flight staging design (a single blob is simpler to write atomically at batch end, and the scheduler always processes one batch at a time). Raw points for in-progress flights are held here until the next batch finalises them.

### ingest_batches — batch state tracking

Records each batch's state for the scheduler. Columns: `batch_date` (PK), `status` (pending/running/succeeded/failed/errored), `started_at`, `finished_at`, `flight_count`, `error_message`, `attempts`, `last_attempt_at`, `release_url`.

The scheduler checks this table on each poll cycle; a batch with status `succeeded` is skipped. Backfilling is "insert pending rows for date range".

### airframes — aircraft metadata

Mapping from `icao24` → registration, type, operator. Sourced from the tar1090-db (Mictronics) aircraft database, refreshed periodically. Used to enrich query results and the `icao_type_stats` aggregation.

### Reference data

Doc 8643 type designators, OpenAIP airspace, OurAirports airports — all loaded once and refreshed periodically. Stored as Postgres tables for joinability.

The Doc 8643 table provides a `type_to_emitter_category` lookup used at ingest to fill in `emitter_category` when the trace doesn't broadcast it. The mapping is derived from Doc 8643's WTC and description fields combined with a small hand-maintained override file for cases the rules don't cover cleanly.

OpenAIP airspace and OurAirports tables are referenced by the UI for overlays and radius queries; they don't participate in ingest.

## Pipeline architecture

### Ingestion (batch)

#### Scheduling

A long-running scheduler process polls the adsb.lol GitHub releases API at a configurable interval (default 12 hours) and runs batches for any dates not yet succeeded. For each unrecognised release it inserts a row into `ingest_batches` with status `pending` and then immediately runs the batch. This handles missed days (the scheduler will pick them up on the next poll) and multiple new releases at once without special-case logic.

The scheduler does not know about "days" or sliding windows — it just maps releases to jobs. The batch date is the unique key on `ingest_batches` so duplicate scans don't re-run completed work.

#### Per-release job

Each batch processes one release tarball. The job is structured as a map/reduce over input points:

**Inputs:**

- The new release tarball (downloaded once, cached on disk)
- The `flight_staging` row for the previous batch date (if any) — the staging blob is unpacked and contributed to the input stream as a prefix to that aircraft's points from the new tarball

**Map phase (parallel):**

Workers stream-process the input, decompressing the tarball and unpacking staging blobs in parallel. Each input point is enriched (apply bbox filter, leave altitudes as pressure altitudes, synthesize emitter category from Doc 8643 if missing) and emitted keyed by `icao24`. Ground points (where `alt_baro` is `"ground"` or null) are **not** dropped here — they carry `new_leg` flags from readsb that the splitter needs to detect flight boundaries. They are excluded from the finalised geometry in the reduce phase. Staging points and tarball points are not distinguished downstream — they feed the same stream and get sorted together by timestamp.

**Shuffle:**

Points are partitioned by `icao24` so that one reducer sees the entire timeline for one aircraft, sorted by timestamp.

**Reduce phase (parallel, one task per aircraft):**

For each aircraft, walk the time-sorted points and split into flights using the `new_leg` flag emitted by readsb:

- readsb sets `new_leg=True` (flags bit 1) on the first point of each new leg — typically a ground-roll point at the start of a new departure. This captures time gaps, spatial discontinuities, and manual leg boundaries without re-implementing readsb's heuristics.
- Ground-level points (where `alt_baro` is null) are included in the point stream so that `new_leg` flags on those points are visible to the splitter. When building the finalised geometry, ground points are excluded — `start_ts`/`end_ts` and vertex positions are derived from airborne points only.
- A squawk change does *not* end a flight. It contributes a new entry to the flight's `squawk_seq` timeseries.

Each finalised flight segment is simplified with TD-TR + altitude pass before geometry storage. The `raw_point_count` column records the pre-simplification airborne point count.

Each flight's classification as "in progress" vs "finalisable" is a property of where its last point falls in time:

- If the last point is ≥10 minutes before the cutoff (the latest timestamp seen anywhere in the input), the flight is **finalised**: simplify with TD-TR + altitude pass, build `squawk_seq`, derive the geometry and start/end points, **commit a single row to `flights`** (UPSERT on `(icao24, start_ts)` for idempotency). Each flight is committed independently as it's finalised — there's no batch-level transaction.
- If the last point is within 10 minutes of the cutoff, the flight is **in progress**: held in memory until all aircraft are processed.

After all aircraft have been processed, all in-progress flight state is serialised and written as a single `flight_staging` blob for this batch date (replacing any prior row). The `ingest_batches` row is marked succeeded.

#### Properties of the algorithm

- **Garbage collection is unnecessary**: an aircraft that never reappears for ≥10 minutes is finalised within the batch that detected the gap. There are no orphan staging blobs to clean up later.
- **Idempotent**: re-running the same batch produces the same `flights` rows (the primary key `(icao24, start_ts)` is deterministic). The staging blob is also reproducible because it derives from the same input.
- **Parallel by construction**: the map/reduce shape means per-aircraft work runs in a ProcessPoolExecutor. The unit of work is small (a few thousand points typically), so a pool of 8–16 workers on the OVH box keeps everything busy.
- **No global transaction**: each finalised flight commits independently. A crash mid-batch loses only in-flight reducer work; already-committed flights persist. The batch is marked succeeded only when all reducers complete; retrying re-runs idempotently.

### Ingestion (streaming, future)

A separate long-running container connects to adsb.lol's live feed, accumulates points, and periodically merges them into `flight_staging` using the same key-by-icao24 / append-points pattern. The next batch run sees the merged points naturally; no special handling needed in the batch path.

## Query API

Primary endpoint: `POST /query`, accepting a JSON DSL. The search window is controlled by `end_date` (defaults to now) and `window_days` (1–7, default 7), defining a sliding window back from `end_date`. An optional `start_from` field sets an explicit lower-bound floor. Returns flight detail (including path) by default; set `include_path: false` for lightweight listing.

### Query DSL

```json
{
  "match": {
    "and": [
      {
        "trajectory_intersects": {
          "geometry": {"type": "Polygon", "coordinates": [...]},
          "altitude_min": 5000,
          "altitude_min_ref": "ft",
          "altitude_max": 180,
          "altitude_max_ref": "fl",
          "time_from": "2025-01-01T00:00:00Z",
          "time_to": "2025-04-01T00:00:00Z",
          "dwell_min_s": 60
        }
      },
      {
        "endpoint_within": {
          "mode": "end",
          "geometry": {"type": "Circle", "coordinates": [-1.18, 50.65], "radius": 3000}
        }
      },
      {"icao_type": ["DA40", "DA42"]},
      {"emitter_category": ["A1"]},
      {"callsign_matches": "^G-"}
    ]
  },
  "limit": 1000,
  "cursor": null
}
```

Predicate types:

- `trajectory_intersects`: flight path ever intersects a geometry. Optional: `altitude_min`/`altitude_max` (with `_ref`: `"ft"` for QNH-corrected feet MSL or `"fl"` for flight level), `time_from`/`time_to`, `squawk_codes`, `dwell_min_s`/`dwell_max_s` (seconds spent inside), `distance_min_m`/`distance_max_m` (path length inside geometry).
- `trajectory_within`: flight path always stays within a geometry (same optional fields).
- `endpoint_within`: spatial/temporal constraints on the start or end point. `mode` is one of `"start"`, `"end"`, `"both"` (start AND end), or `"either"` (start OR end). Geometry types: Circle, Polygon (including airspace-sourced polygons), or viewport rectangle.
- `icao_type`: filter by one or more ICAO type designators.
- `emitter_category`: filter by ADS-B emitter category (A1-A7, B1-B7, C1-C3).
- `callsign_matches`: regex match against callsign.
- `duration`: filter on flight length; accepts `min_s` and/or `max_s` bounds (seconds, both inclusive, both optional).
- `and` / `or` / `not`: boolean composition (recursive).

Altitude bounds with `ref: "ft"` are applied against **QNH-corrected altitude** using the stored `alt_correction_ft`. Flights without correction data fall back to pressure altitude (±300 ft uncertainty). Bounds with `ref: "fl"` are always pressure altitude (FL × 100 ft), regardless of whether correction data is available.

Dwell-time and distance-inside-geometry predicates require a geometry to be specified (server-side validated). Both measures operate on the path clipped to the geometry and altitude/time window — so "dwell ≥ 10 min inside polygon at 2000–5000 ft" correctly measures only time within both constraints simultaneously.

The server compiles the predicate tree to MobilityDB/PostGIS SQL via a Pydantic-based query compiler. Each predicate type emits its WHERE fragment; boolean composition wraps fragments.

Result limits enforced at the API: 1–10,000 flights per page (default 100). Cursor-based pagination, not offset.

### Auxiliary endpoints

- `GET /flights/{flight_id}` — full detail for a single flight. `flight_id` is `icao24:start_ts_utc`.
- `GET /data-range` — returns `first_date` and `last_date` of available flight data (used to constrain the date picker).
- `GET /health` — liveness probe.

Airspace GeoJSON is served by the nginx layer proxying to OpenAIP, not by a dedicated API endpoint.

## Frontend

Map-centric SPA. The UI breaks into:

- **Map**: MapLibre + deck.gl. Layers: basemap (dark/light/satellite), airspace chart overlay (OpenAIP), query results as `LineLayer` segments coloured by the active colour mode. Start points shown as green dots, end points as red dots.
- **Colour modes**: altitude, emitter category, squawk code, vertical rate, ground speed, indicated airspeed (IAS). Switched via a toolbar. VS/GS/IAS use diverging colour scales; flights without data for the active mode are shown grey.
- **Query builder**: structured UI building the JSON DSL. Predicates: aircraft type/emitter, callsign regex, starts-within, ends-within, ever (trajectory_intersects), always (trajectory_within). Each spatial predicate supports circle, drawn polygon, current viewport, or airspace-from-map. Ever/Always predicates support optional altitude range (ft or FL), time window, squawk filter, dwell time, and distance-inside-geometry bounds. Altitude bounds auto-populate from airspace boundaries when an airspace zone is selected. A global departure-date window picker (up to 7-day range) constrains all results.
- **Airspace selection**: clicking on the map while in airspace-pick mode queries OpenAIP candidates near the cursor and lets the user confirm a zone. The zone's polygon becomes the query geometry; its altitude limits (ft or FL) are automatically applied as altitude bounds.
- **Results panel**: list of matching flights ordered by `start_ts` descending. Shows callsign, ICAO24, type, departure time, duration, and an altitude sparkline. Clicking a flight selects it; the selected trace is highlighted and dimmed non-selected traces are shown at 20% opacity.
- **Hover infobox**: hovering over any trace segment shows an infobox with callsign, ICAO24, type, emitter category, interpolated altitude (ft), vertical rate (fpm ↑/↓), ground speed (kt), IAS (kt, if available), heading (degrees + 16-point compass), squawk code, and UTC time — all interpolated to the exact cursor position along the segment. When a flight is selected, hovering over other traces shows no infobox.
- **Pagination**: results panel pages through large result sets via cursor. Each page's flights are plotted as a batch on the map.

State: React's primitives (useState/useReducer). Server state via TanStack Query with cache invalidation when filters change.

Authentication: none (read-only public data). If rate limiting becomes necessary, IP-based via the API.

## Engineering practices

### Repository hygiene

- Standard Python project layout (PEP 621 `pyproject.toml`, src-layout package, no setup.py).
- Standard JS/TS project layout (Vite defaults, ESM modules, strict TypeScript).
- Conventional Commits format for commit messages.
- `.editorconfig` at repo root.
- `.gitignore` covers Python (`__pycache__`, `.venv`, `.pytest_cache`, etc.), Node (`node_modules`, `dist`), editor files, and project-specific paths (`cache/`, `.env`).
- `README.md` with quick-start, architecture summary, and links to the design spec.

### Linting and formatting

- Python: `ruff` for linting and formatting (replaces black, isort, flake8).
- Python: `mypy` in strict mode for type checking. All public functions type-hinted.
- TypeScript: strict mode on, `noImplicitAny`, `strictNullChecks`, etc. ESLint with the project's typescript-eslint config; Prettier for formatting.
- SQL: `sqlfluff` for migrations and embedded SQL.

### Testing

- Python: `pytest`. Unit tests for pure functions (geometry, pressure correction, flight splitting, emitter-category synthesis), integration tests against a real Postgres+PostGIS+MobilityDB in Docker (use `testcontainers`), end-to-end tests for the API.
- TypeScript: `vitest` for unit tests, `playwright` for end-to-end browser tests against a deployed test instance.
- Coverage: `coverage.py` for Python, `vitest` built-in coverage for TS. Coverage reports generated on every CI run and on every commit (via pre-commit).
- Coverage targets: 90%+ on geometry, query DSL compiler, flight splitting, and emitter-category synthesis (the algorithmic core); 80%+ on API route handlers; integration tests cover what unit tests can't.
- Where coverage is below target, write tests to fill gaps as part of the feature work that introduced the gap. No "we'll backfill tests later" — uncovered code blocks PRs.

### Pre-commit hooks

Configured via `pre-commit`:

- Trailing whitespace / EOF / large-file checks
- `ruff check` and `ruff format` on Python
- `mypy` on changed Python files
- `eslint` and `prettier` on TypeScript
- `sqlfluff` on SQL files
- Unit test run with coverage reporting; commit fails if coverage drops on changed files

### CI

GitHub Actions runs the full test suite (including integration tests via testcontainers), produces a combined coverage report, and uploads it as a build artifact. Build fails if coverage targets aren't met or if any check fails. Builds Docker images and pushes to GitHub Container Registry on success.

## Repository layout

Monorepo with three top-level packages:

```
adsb-aero/
├── server/                    # Python: ingestion + API
│   ├── adsb_server/
│   │   ├── ingestion/         # Batch scheduler, parser, splitter, TD-TR
│   │   ├── geometry/          # TD-TR, altitude pass, simplification, WKT helpers
│   │   ├── api/               # FastAPI routes
│   │   ├── query/             # DSL Pydantic models + SQL compiler
│   │   ├── db/                # asyncpg connection pool
│   │   ├── pressure/          # GFS MSLP fetch (Herbie/cfgrib) + QNH correction computation
│   │   ├── era5/              # ERA5 integration (stub)
│   │   ├── reference_data/    # Doc 8643, airspace, airports loaders
│   │   └── config.py          # Pydantic settings
│   ├── alembic/               # Schema migrations
│   ├── tests/
│   └── pyproject.toml
├── web/                       # TypeScript SPA
│   ├── src/
│   ├── tests/
│   ├── package.json
│   └── vite.config.ts
├── infra/
│   ├── docker-compose.yml         # base services (prod)
│   ├── docker-compose.dev.yml     # dev overrides (hot-reload, vite service)
│   ├── postgres/
│   │   └── postgresql.conf    # tuned for NVMe + 64GB RAM
│   ├── nginx/
│   ├── ofelia/
│   └── secrets/               # gitignored runtime secrets
├── docs/
│   ├── design-spec.md         # this document
│   └── dev-setup.md
├── .pre-commit-config.yaml
├── CLAUDE.md
└── README.md
```

## Operational concerns

- **Errors**: Sentry SDK in every backend entry point (API server and all scheduled tasks — add to any new background task or cron job). Free tier sufficient. DSN stored as a Docker secret (`infra/secrets/sentry_dsn`); read via `settings.effective_sentry_dsn`.
- **Logs**: stdout from each container, captured by Docker's json-file driver.
- **Secrets**: Plain text files in `infra/secrets/` (gitignored), mounted by Docker Compose at `/run/secrets/<name>`. Current secrets: `sentry_dsn` (Sentry DSN), `openaip_api_key` (OpenAIP tile/airspace proxy), `origin.crt` and `origin.key` (TLS certificates, prod only). Migrate to `sops` if collaborators are added.
- **CI/CD**: GitHub Actions builds Docker images, pushes to GitHub Container Registry. Deployment to OVH is `git pull && cd infra && docker compose -f docker-compose.yml pull && docker compose -f docker-compose.yml up -d` (run from `infra/`; `infra/.env` is a symlink to the repo-root `.env`) either manually or via a webhook. No Kubernetes.
- **Backups and DR**: handled at infrastructure level via OVHcloud. Out of scope for this spec.

## Cloud migration path

If the OVH server becomes inadequate or operational burden too high:

- **Postgres**: migrate to Crunchy Bridge or Cloud SQL. Schema and queries are portable. PostGIS version compatibility is the only thing to verify.
- **API + ingestion containers**: deploy to Cloud Run, Fargate, or managed Kubernetes. The images are unchanged.
- **Frontend**: already static, deploys to Cloudflare Pages, Netlify, or any static host.
- **Object storage** (for GFS/NWP cache, OpenAIP cache): already S3-compatible, just point at the cloud provider's offering.

The compose file becomes the dev config; cloud deploys use Helm charts or Terraform pointing at the same images.

## Implementation status

### Completed

1. **Repo skeleton + tooling** ✓ — project structure, ruff/mypy/eslint/prettier/sqlfluff configs, pre-commit hooks, Docker Compose with Postgres+PostGIS+MobilityDB.
2. **Schema + Python DB tooling** ✓ — Postgres+MobilityDB schema, Alembic migrations, asyncpg connection pool, Pydantic settings.
3. **Ingestion pipeline** ✓ — tarball download, parse, split into flights, TD-TR simplification (spatial + per-scalar-series), emitter category synthesis from Doc 8643, staging-flight carry-over, batch state tracking. Scalar time series (`path_tracks`, `path_gs`, `path_vr`, `path_ias`) stored as MobilityDB `tint`.
4. **API v1** ✓ — query endpoint with the JSON DSL, flight detail endpoint, data-range endpoint, health check.
5. **Reference data** ✓ — Doc 8643 type designators, OpenAIP airspace (overlay + zone selection in query builder). OpenSky aircraft metadata and OurAirports airports not yet loaded.
6. **GFS altitude correction** ✓ — GFS MSLP fetch via Herbie/cfgrib, per-vertex QNH correction computed at ingest and stored as `alt_correction_ft` tfloat. Query compiler applies stored corrections for altitude-based predicates. Altitude bounds accept ft or FL references.
7. **Frontend** ✓ — full query builder (all DSL predicates, polygon drawing, airspace selection, altitude/time/squawk/dwell/distance optional filters), map with multiple colour modes (alt/cat/VS/GS/IAS/squawk), results panel with altitude sparklines, rich hover infobox, flight selection with trace dimming.

### Remaining

8. **OurAirports integration**: radius-from-airfield pickers in the query builder. Requires loading OurAirports data and a typeahead search UI.
9. **OpenSky aircraft metadata**: enrich callsign and registration from the OpenSky aircraft database. Requires periodic-refresh loader.
10. **Scale up**: ingest whole-world data, validate performance under load, tune indexes and query plans.
12. **Future**: VFR/IFR classification (separate column or table), streaming ingest from adsb.lol live feed, public launch, CI with GitHub Actions, hardening.
