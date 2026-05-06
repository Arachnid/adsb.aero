# ADS-B historical query platform — design spec

A web-based tool for querying and visualising historical ADS-B trace data. Domain: adsb.aero. Single-operator project, designed for one dedicated server with cloud-portability later.

## Project goal

Ingest the adsb.lol global archive at country-to-continent scale, store flight trajectories with rich metadata, and serve a map-based query UI that supports complex spatial-temporal-attribute queries.

Use cases include "where do people arrive at this airfield from", "what routes do people take from A to B", and arbitrary multi-region queries with per-region predicates (altitude bands, dwell time, aircraft type). "Arrives at airfield X" is expressed as "ends within radius R of point P", not as a distinct origin/destination concept.

## Technology stack

- **Database**: PostgreSQL 17 with PostGIS 3.5+. Native partitioning on the trace partitions. Single instance. Containerised.
- **Ingestion**: Python with Dramatiq + Redis for task queueing. Multiprocessing for per-aircraft parallelism within a batch.
- **API**: Python with FastAPI and asyncpg. Custom JSON DSL for query expression. Pydantic models for request/response validation.
- **Frontend**: TypeScript + React + Vite + MapLibre GL JS + deck.gl + TailwindCSS. State via React's built-in primitives plus TanStack Query for server state.
- **Deployment**: Docker Compose for single-host. All services in containers. Configuration via environment variables. Same images deployable to managed Kubernetes/Cloud Run later.
- **Hosting**: OVH dedicated server (EPYC 4244P, 64GB RAM, 4×960GB NVMe in RAID 5 giving ~2.88TB usable). Postgres tuned for NVMe (`random_page_cost=1.1`, `effective_io_concurrency=256`, `shared_buffers=16GB`, etc.). Backups, DR, and machine-level operational concerns are handled via OVHcloud's services and outside the scope of this spec.
- **Observability**: Prometheus + Grafana + Loki for metrics and logs. Sentry for errors.

## Altitude representation

All altitudes are stored internally as **pressure altitudes** (referenced to 1013.25 hPa) — exactly what ADS-B broadcasts. QNH-corrected altitude is a derived view, computed at query time when needed.

Rationale: pressure altitude is the source of truth from the aircraft. QNH correction depends on ERA5 reanalysis data which has a multi-day publication lag. Storing pressure altitudes lets us:

- Ingest flights without waiting for pressure data
- Re-run corrections later if methodology changes (different reanalysis source, different interpolation)
- Avoid baking a derived value into permanent storage

ERA5 data is loaded into a separate `pressure_field` table or kept as cached NetCDFs. When a query needs QNH-corrected altitude — for display or for any altitude-based filtering — the API joins to ERA5 and applies `qnh_alt = pressure_alt + (mslp_hpa - 1013.25) × 27.3` on the fly. For typical UK conditions the correction is <300ft and well within most query tolerances.

## Data model

### flights — finalised trajectories

Single table holding completed flights. One row per flight.

Key columns:

- `flight_id` TEXT PRIMARY KEY — concatenation of `icao24` and ISO 8601 `start_ts`, separated by `:`. Example: `4ca7b3:2025-04-15T14:32:18Z`. Stable across re-ingestion of the same source data, human-readable in logs.
- `icao24` VARCHAR — Mode S transponder address
- `callsign` VARCHAR
- `icao_type` VARCHAR — aircraft type designator from Doc 8643
- `emitter_category` VARCHAR — ADS-B emitter category. When the trace doesn't broadcast it, looked up from a Doc 8643 → emitter category mapping table at ingest. Nullable only as a last resort when neither is available.
- `start_ts`, `end_ts` TIMESTAMPTZ
- `start_point`, `end_point` GEOMETRY(POINTZM, 4326) — first and last vertices of the trajectory. X=lon, Y=lat, Z=pressure-alt-ft, M=unix-epoch-seconds. Used for "starts/ends within radius R of point P" queries.
- `path_geom` GEOMETRY(LINESTRINGZM, 4326) — X=lon, Y=lat, Z=pressure-alt-ft, M=unix-epoch-seconds. Single geometry encoding position, altitude, and time per vertex.
- `path_tracks` SMALLINT[] — per-vertex track angle in degrees (0–359), sampled from ADS-B's broadcast track value (Airborne Velocity message)
- `squawk_runs` JSONB — array of `[start_ts, squawk]` pairs marking each squawk change. A flight that never changes squawk has a single-entry array. Most flights have 1–3 entries.
- `ingest_batch_date` DATE — provenance

Min/max altitude are not stored as columns; they're queryable via expression indexes on `ST_ZMin(path_geom)` and `ST_ZMax(path_geom)` (see indexes below). Mean speed is similarly derivable from start_point, end_point, start_ts, end_ts at query time. Per-vertex speed is derivable from consecutive vertex positions and timestamps.

VFR/IFR classification is **not** in this schema. It would require ERA5-corrected altitudes for the airspace test, and it's a derived attribute that can be added later as a separate column or table once the methodology is stable.

Indexes:

- GIST on `path_geom` using `gist_geometry_ops_nd` (4D bounding-volume index). This serves both 4D queries (lat/lon/alt/time) and 2D-only queries; PostGIS treats missing dimensions in the query geometry as unbounded. For pure 2D-heavy workloads a separate 2D GIST index gives 2-3× speedup, but for v1 the single ND index is sufficient. Add a 2D index later if profiling shows need.
- GIST on `start_point` and `end_point` (for radius queries against airfields)
- B-tree on `start_ts`, `end_ts`, `icao24`, `icao_type`, `emitter_category`
- Expression indexes on `ST_ZMin(path_geom)` and `ST_ZMax(path_geom)` to support altitude-range filters without storing min/max columns
- Composite indexes per query pattern as profiling reveals need

Partitioned by `start_ts` using native Postgres declarative partitioning. Monthly partitions. `pg_partman` automates partition creation.

Geometry is **already simplified** at ingest using 2D TD-TR (synchronised Euclidean distance) for spatial fidelity at ε=50m, plus an altitude pass that recursively inserts vertices into each TD-TR-kept inter-vertex span wherever altitude interpolation exceeds ε=100ft (against pressure altitude). Stored result is a LINESTRINGZM with vertices that satisfy both bounds. The `path_tracks` array has one entry per vertex, taken from the closest broadcast track sample to that vertex's timestamp.

### staging_flights — in-progress flights

Holds the raw input points for flights whose last seen point is recent enough that more points may still arrive (regardless of source — batch or future streaming). Each row is a partial flight that will be reprocessed in the next batch alongside any newly-arrived points.

Columns:

- `flight_id` TEXT PRIMARY KEY — same format as `flights.flight_id` (`icao24:start_ts`)
- `icao24` VARCHAR
- `start_ts`, `last_ts` TIMESTAMPTZ — timestamps of first and most-recently-seen point
- `points` JSONB — the raw input points held over from previous batches, in the original schema (timestamp, lat, lon, alt_baro, track, squawk, etc.). This is the complete state needed to reprocess the flight; nothing is lost between batches.
- `source` VARCHAR — `batch` | `stream`

A flight in this table is a flight-in-progress, not a finalised one. There is no `squawk_runs` here because squawk transitions are a property of finalised flights — staging just holds raw points and lets the pipeline derive runs at finalisation time.

Index on `icao24` for the merge step at the start of each batch.

### ingest_batches — batch state tracking

Records each batch's state for the scheduler. Columns: `batch_date` (PK), `status` (pending/running/succeeded/failed), `started_at`, `finished_at`, `flight_count`, `error_message`, `attempts`, `last_attempt_at`.

The scheduler polls this table to decide what to run; backfilling is "insert pending rows for date range".

### Aircraft metadata table

Mapping from `icao24` → registration, type, owner. Sourced from the OpenSky aircraft database, refreshed periodically. Used to enrich incoming traces where adsb.lol's metadata is incomplete.

### Reference data

Doc 8643 type designators, OpenAIP airspace, OurAirports airports — all loaded once and refreshed periodically. Stored as Postgres tables for joinability.

The Doc 8643 table provides a `type_to_emitter_category` lookup used at ingest to fill in `emitter_category` when the trace doesn't broadcast it. The mapping is derived from Doc 8643's WTC and description fields combined with a small hand-maintained override file for cases the rules don't cover cleanly.

OpenAIP airspace and OurAirports tables are referenced by the UI for overlays and radius queries; they don't participate in ingest.

## Pipeline architecture

### Ingestion (batch)

#### Scheduling

A cron job runs periodically (e.g. every 30 minutes) and scans the adsb.lol GitHub releases page for tarballs not yet ingested. For each unrecognised release, it inserts a row into `ingest_batches` with status `pending` and enqueues a Dramatiq task. This handles missed days (the cron will pick them up on the next run) and multiple new releases at once (each gets its own task) without special-case logic.

The scheduler does not know about "days" or sliding windows — it just maps releases to jobs. The release identifier (typically a date string from adsb.lol's release naming) is stored as a unique key on `ingest_batches` so duplicate scans don't enqueue duplicate work.

#### Per-release job

Each Dramatiq task processes one release tarball. The job is structured as a map/reduce over input points:

**Inputs:**

- The new release tarball (downloaded once, cached on disk)
- The entire `staging_flights` table — every row's `points` blob is unpacked and contributed to the input stream as a prefix to that aircraft's points from the new tarball

**Map phase (parallel):**

Workers stream-process the input, decompressing the tarball and unpacking staging blobs in parallel. Each input point is enriched (apply bbox filter, leave altitudes as pressure altitudes, synthesize emitter category from Doc 8643 if missing) and emitted keyed by `icao24`. Ground points (where `alt_baro` is `"ground"` or null) are **not** dropped here — they carry `new_leg` flags from readsb that the splitter needs to detect flight boundaries. They are excluded from the finalised geometry in the reduce phase. Staging points and tarball points are not distinguished downstream — they feed the same stream and get sorted together by timestamp.

**Shuffle:**

Points are partitioned by `icao24` so that one reducer sees the entire timeline for one aircraft, sorted by timestamp.

**Reduce phase (parallel, one task per aircraft):**

For each aircraft, walk the time-sorted points and split into flights using the `new_leg` flag emitted by readsb:

- readsb sets `new_leg=True` (flags bit 1) on the first point of each new leg — typically a ground-roll point at the start of a new departure. This captures time gaps, spatial discontinuities, and manual leg boundaries without re-implementing readsb's heuristics.
- Ground-level points (where `alt_baro` is null) are included in the point stream so that `new_leg` flags on those points are visible to the splitter. When building the finalised geometry, ground points are excluded — `start_ts`/`end_ts` and vertex positions are derived from airborne points only.
- A squawk change does *not* end a flight. It contributes a new entry to the flight's `squawk_runs` array.

Each finalised flight segment is simplified with TD-TR + altitude pass before geometry storage. The `raw_point_count` column records the pre-simplification airborne point count.

Each flight's classification as "in progress" vs "finalisable" is a property of where its last point falls in time:

- If the last point is ≥10 minutes before the cutoff (the latest timestamp seen anywhere in the input), the flight is **finalised**: simplify with TD-TR + altitude pass, build `squawk_runs`, derive the geometry and start/end points, **commit a single row to `flights`** (UPSERT on `flight_id` for idempotency). Each flight is committed independently as it's finalised — there's no batch-level transaction.
- If the last point is within 10 minutes of the cutoff, the flight is **in progress**: serialize its raw input points to a new `staging_flights` row.

After all aircraft have been processed, `staging_flights` is replaced with the new set of in-progress flights for this batch (the old rows were already consumed as input). The `ingest_batches` row is marked succeeded.

#### Properties of the algorithm

- **Garbage collection is unnecessary**: an aircraft that never reappears for ≥10 minutes is finalised within the batch that detected the gap. There are no orphan staging rows to clean up later.
- **Idempotent**: re-running the same batch produces the same `flights` rows (the `flight_id` is deterministic). The staging rows are also reproducible because they're derived from the same input.
- **Parallel by construction**: the map/reduce shape means the batch scales horizontally with worker count. For per-aircraft reducers, the unit of work is small (a few thousand points typically), so a pool of 8-16 workers on the OVH box keeps everything busy.
- **No global transaction**: each finalised flight commits independently. A worker crash mid-batch loses only the in-flight reducer's work; already-committed flights persist. The batch is marked succeeded only when all reducers complete; if it fails partway, retrying re-runs the reducers, which idempotently produce the same output.

### Ingestion (streaming, future)

A separate long-running container connects to adsb.lol's live feed, accumulates points, and periodically merges them into `staging_flights` using the same key-by-icao24 / append-points pattern. The next batch run sees the merged points naturally; no special handling needed in the batch path.

## Query API

Single endpoint, `POST /query`, accepting a JSON DSL. Returns flight summaries by default; full path geometry fetched separately.

### Query DSL

```json
{
  "match": {
    "and": [
      {
        "trajectory_intersects": {
          "geometry": {"type": "Polygon", "coordinates": [...]},
          "altitude_min_ft": 5000,
          "min_duration_seconds": 60
        }
      },
      {
        "ends_within": {
          "center": [-1.18, 50.65],
          "radius_m": 3000
        }
      },
      {"aircraft": {"icao_type": ["DA40", "DA42"]}},
      {"time_range": {"from": "2025-01-01", "to": "2025-04-01"}},
      {"emitter_category": ["A1"]}
    ]
  },
  "select": ["flight_id", "callsign", "start_point", "end_point",
             "start_ts", "end_ts"],
  "order_by": [{"field": "start_ts", "direction": "desc"}],
  "limit": 1000,
  "cursor": null
}
```

Predicate types:

- `trajectory_intersects`: GeoJSON geometry plus optional altitude band (interpreted as QNH at query time), time window, minimum duration in region
- `trajectory_within`, `trajectory_disjoint`: spatial relations
- `starts_within`, `ends_within`: radius queries against `start_point` / `end_point`
- `aircraft`: type / category filters
- `emitter_category`: filter by ADS-B emitter category (A1-A7, B1-B4, etc.)
- `time_range`: start/end window
- `callsign_matches`: regex match
- `and` / `or` / `not`: boolean composition (recursive)

The server compiles the predicate tree to PostGIS SQL via a Pydantic-based query compiler. Each predicate type knows how to emit its WHERE fragment; boolean composition wraps fragments. Field selection becomes the SELECT clause with appropriate joins.

For altitude-based predicates, the compiler joins to ERA5 data to apply QNH correction within the SQL where ERA5 coverage exists; for time ranges where ERA5 is missing, predicates fall back to comparing against pressure altitude with a documented ±300ft uncertainty.

Result limits enforced at the API: max 10,000 flights per response. For "passed through London" type queries that match millions, return a sampled subset with a flag indicating the result is sampled.

Cursor-based pagination, not offset.

### Auxiliary endpoints

- `GET /flights/{flight_id}` — full detail including high-fidelity path geometry
- `POST /flights/paths` — bulk fetch of paths for a list of flight IDs (for plotting search results)
- `GET /airspace` — current airspace GeoJSON for map overlay
- `GET /health` — liveness probe

## Frontend

Map-centric SPA. The UI breaks into:

- **Map**: MapLibre + deck.gl. Layers — basemap, airspace overlay, query results as trajectories via `PathLayer`.
- **Query builder**: structured UI for building DSL queries. Polygon drawing tools, attribute filters, time range pickers, radius-from-airport pickers. Compiles to JSON DSL and posts to `/query`.
- **Results panel**: list of matching flights ordered by `start_ts` descending. Clicking a flight highlights it; by default all results in the current page are plotted simultaneously.
- **Pagination**: results panel pages through large result sets via the cursor. Each page's flights are plotted as a batch on the map.
- **Flight inspection**: detail popup with metadata, altitude/speed profile.

State: React's primitives. Server state via TanStack Query with smart cache invalidation when filters change.

Authentication: none initially (read-only public data). If rate limiting becomes necessary, IP-based via the API.

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

- Python: `pytest`. Unit tests for pure functions (geometry, ERA5 lookup, flight splitting, emitter-category synthesis), integration tests against a real Postgres+PostGIS in Docker (use `testcontainers`), end-to-end tests for the API.
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
│   │   ├── ingestion/         # Batch worker + Dramatiq tasks
│   │   ├── geometry/          # TD-TR, altitude pass, simplification
│   │   ├── api/               # FastAPI routes
│   │   ├── query/             # DSL Pydantic models + SQL compiler
│   │   ├── db/                # asyncpg, schema migrations (Alembic)
│   │   ├── era5/              # Pressure data fetch + lookup
│   │   └── reference_data/    # Doc 8643, airspace, airports loaders
│   ├── config/
│   ├── tests/
│   └── pyproject.toml
├── web/                       # TypeScript SPA
│   ├── src/
│   ├── tests/
│   ├── package.json
│   └── vite.config.ts
├── infra/
│   ├── docker-compose.yml     # dev / single-host prod
│   ├── postgres/
│   │   └── postgresql.conf    # tuned for NVMe + 64GB RAM
│   ├── prometheus/
│   ├── grafana/
│   └── loki/
├── docs/
│   ├── design-spec.md         # this document
│   ├── query-dsl.md
│   └── runbook.md
├── .github/workflows/         # CI: build images, push to GHCR
├── .pre-commit-config.yaml
├── CLAUDE.md
└── README.md
```

## Operational concerns

- **Monitoring**: Prometheus scrapes Postgres, Redis, the FastAPI app, the Dramatiq workers, and node_exporter. Grafana dashboards for system health, ingest progress, and query latency. Alertmanager → email/SMS for critical alerts.
- **Logs**: stdout from each container, scraped by Loki, queryable via Grafana.
- **Errors**: Sentry SDK in both API and ingestion code. Free tier sufficient.
- **Secrets**: `.env` files (gitignored) for now. Migrate to `sops` if collaborators are added.
- **CI/CD**: GitHub Actions builds Docker images, pushes to GitHub Container Registry. Deployment to OVH is `git pull && docker compose pull && docker compose up -d` either manually or via a webhook. No Kubernetes.
- **Backups and DR**: handled at infrastructure level via OVHcloud. Out of scope for this spec.

## Cloud migration path

If the OVH server becomes inadequate or operational burden too high:

- **Postgres**: migrate to Crunchy Bridge or Cloud SQL. Schema and queries are portable. PostGIS version compatibility is the only thing to verify.
- **Redis**: managed Redis at any provider.
- **API + ingestion containers**: deploy to Cloud Run, Fargate, or managed Kubernetes. The images are unchanged.
- **Frontend**: already static, deploys to Cloudflare Pages, Netlify, or any static host.
- **Object storage** (for ERA5 cache, OpenAIP cache): already S3-compatible, just point at the cloud provider's offering.

The compose file becomes the dev config; cloud deploys use Helm charts or Terraform pointing at the same images.

## Initial implementation order

1. **Repo skeleton + tooling**: project structure, ruff/mypy/eslint/prettier/sqlfluff configs, pre-commit hooks, CI pipeline with coverage reporting, Docker Compose with Postgres+PostGIS.
2. **Schema + Python DB tooling**: Postgres schema with pg_partman, Alembic migrations, asyncpg connection pool, Pydantic settings. No reference data tables yet.
3. **Ingestion pipeline**: tarball download, parse, split into flights, simplify, synthesize emitter category, write to `flights`. Staging flights included from the start — in-progress flights feed back into the next batch naturally. Backfill 30 days of UK data as proof-of-concept. `emitter_category` derived from Doc 8643 inline.
4. **API v1**: query endpoint with the JSON DSL, flight detail and bulk-path endpoints, health check. Flight data only — no airspace or airport endpoints yet.
5. **Frontend v1**: map, basic query builder (bbox + time + emitter-category filters), results plotting with paging. Flight data only — no airspace overlays or radius-from-airport pickers yet.
6. **Reference data + enrichment**: Doc 8643 type designators (type → emitter category mapping table), OpenSky aircraft metadata, OurAirports airports, OpenAIP airspace. Each as its own loader with periodic-refresh scheduling. API endpoints for airspace and airport lookup. Frontend gains airspace overlay and radius-from-airport query support.
7. **ERA5 + on-demand QNH correction**: pressure data fetch, on-demand correction in the query layer for altitude-based predicates and for display.
8. **Frontend v2**: polygon drawing, multi-region queries, full radius-from-airfield pickers.
9. **Operational stack**: monitoring, alerting, runbooks.
10. **Scale up**: ingest whole-world data, validate performance, tune.
11. **Future**: VFR/IFR classification (separate column or table), streaming ingest, public launch, hardening.