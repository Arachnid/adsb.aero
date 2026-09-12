"""Download OpenAIP data from the public GCS bucket and upsert into the
waypoints and airspaces tables.

The bucket contains per-country newline-delimited GeoJSON files:
  {cc}_{apt|nav|rpp|asp}.ndgeojson

  apt = airports  → waypoints (kind='airport')
  nav = navaids   → waypoints (kind='navaid')
  rpp = reporting points → waypoints (kind='reporting_point')
  asp = airspaces → airspaces table

Elevation unit codes: 0=metres (converted to ft), 1=feet (kept as-is).
Frequency unit codes: 1=kHz (converted to MHz), 2=MHz (kept as-is).
Altitude limit unit codes: 0=m, 1=ft, 6=FL.  ref codes: 0=GND, 1=MSL, 2=STD.

Usage:
    python -m adsb_server.reference_data.openaip
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import sys

import asyncpg
import httpx
import sentry_sdk

from adsb_server.config import get_settings

# fmt: off
# Airport type_code values (OpenAIP):
#  0 Airport      1 Glider Site     2 Airfield Civil    3 International Airport
#  4 Heliport Mil 5 Military Aero   6 Ultra Light       7 Heliport Civil
#  8 Closed       9 Airport IFR    10 Airfield Water    11 Landing Strip
# 12 Agri Strip  13 Altiport
#
# Navaid type_code values:
#  0 DME  1 TACAN  2 NDB  3 VOR  4 VOR-DME  5 VORTAC  6 DVOR  7 DVOR-DME  8 DVORTAC
#
# Airspace type_code values (selected):
#  0 Other  1 Restricted  2 Danger  3 Prohibited  4 CTR  5 TMZ  6 RMZ
#  7 TMA    8 TRA         9 TSA    10 FIR        11 UIR 12 ADIZ 13 ATZ
# 14 MATZ  15 Airway     20 HTZ   26 CTA
#
# Airspace icao_class: 0=A 1=B 2=C 3=D 4=E 5=F 6=G 8=Unclassified/SUA
# fmt: on

GCS_BASE = "https://storage.googleapis.com/29f98e10-a489-4c82-ae5e-489dbcd4912f"
GCS_API = "https://storage.googleapis.com/storage/v1/b/29f98e10-a489-4c82-ae5e-489dbcd4912f/o"
BATCH_SIZE = 2_000
# Max concurrent country-file downloads per dataset type.
MAX_CONCURRENT = 10

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_ft(value: int | float | None, unit: int | None) -> int | None:
    if value is None:
        return None
    if unit == 1:
        return round(value)
    if unit == 0:
        return round(value * 3.28084)
    return round(value)


def _to_mhz(value: str | None, unit: int | None) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except ValueError, TypeError:
        return None
    if unit == 1:
        return v / 1000.0
    return v


# ---------------------------------------------------------------------------
# Listing bucket files
# ---------------------------------------------------------------------------


async def _list_files(client: httpx.AsyncClient, suffix: str) -> list[str]:
    """Return all object names in the bucket ending with `suffix`."""
    names: list[str] = []
    params: dict[str, str] = {"maxResults": "9999"}
    while True:
        r = await client.get(GCS_API, params=params)
        r.raise_for_status()
        data = r.json()
        for item in data.get("items", []):
            if item["name"].endswith(suffix):
                names.append(item["name"])
        token = data.get("nextPageToken")
        if not token:
            break
        params["pageToken"] = token
    return names


# ---------------------------------------------------------------------------
# Parsers: ndgeojson → row lists
# ---------------------------------------------------------------------------

WaypointRow = tuple[
    str,
    str,
    str,
    str | None,
    str | None,
    int | None,
    str,
    float,
    float,
    int | None,
    float | None,
    bool | None,
]

AirspaceRow = tuple[
    str,
    str,
    int,
    int | None,
    str,
    str,  # WKT geometry
    int | None,
    int | None,
    int | None,
    int | None,
    int | None,
    int | None,
]


def _parse_airports(data: bytes) -> list[WaypointRow]:
    rows: list[WaypointRow] = []
    for line in io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            feat = json.loads(line)
        except json.JSONDecodeError:
            continue
        p = feat.get("properties", {})
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        elev = p.get("elevation") or {}
        rows.append(
            (
                p["_id"],
                "airport",
                p.get("name", ""),
                (p.get("icaoCode") or "").strip().upper() or None,
                (p.get("iataCode") or "").strip().upper() or None,
                p.get("type"),
                (p.get("country") or "").upper(),
                float(coords[0]),
                float(coords[1]),
                _to_ft(elev.get("value"), elev.get("unit")),
                None,  # frequency_mhz
                None,  # compulsory
            )
        )
    return rows


def _parse_navaids(data: bytes) -> list[WaypointRow]:
    rows: list[WaypointRow] = []
    for line in io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            feat = json.loads(line)
        except json.JSONDecodeError:
            continue
        p = feat.get("properties", {})
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        elev = p.get("elevation") or {}
        freq = p.get("frequency") or {}
        rows.append(
            (
                p["_id"],
                "navaid",
                p.get("name", ""),
                (p.get("identifier") or "").strip().upper() or None,
                None,  # iata_code
                p.get("type"),
                (p.get("country") or "").upper(),
                float(coords[0]),
                float(coords[1]),
                _to_ft(elev.get("value"), elev.get("unit")),
                _to_mhz(freq.get("value"), freq.get("unit")),
                None,  # compulsory
            )
        )
    return rows


def _parse_reporting_points(data: bytes) -> list[WaypointRow]:
    rows: list[WaypointRow] = []
    for line in io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            feat = json.loads(line)
        except json.JSONDecodeError:
            continue
        p = feat.get("properties", {})
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        elev = p.get("elevation") or {}
        rows.append(
            (
                p["_id"],
                "reporting_point",
                p.get("name", ""),
                None,  # ident
                None,  # iata_code
                None,  # type_code
                (p.get("country") or "").upper(),
                float(coords[0]),
                float(coords[1]),
                _to_ft(elev.get("value"), elev.get("unit")),
                None,  # frequency_mhz
                p.get("compulsory"),
            )
        )
    return rows


def _parse_airspaces(data: bytes) -> list[AirspaceRow]:
    rows: list[AirspaceRow] = []
    for line in io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            feat = json.loads(line)
        except json.JSONDecodeError:
            continue
        p = feat.get("properties", {})
        geom = feat.get("geometry")
        if not geom:
            continue
        geom_json = json.dumps(geom)
        lo = p.get("lowerLimit") or {}
        hi = p.get("upperLimit") or {}
        rows.append(
            (
                p["_id"],
                p.get("name", ""),
                p.get("type", 0),
                p.get("icaoClass"),
                (p.get("country") or "").upper(),
                geom_json,
                lo.get("value"),
                lo.get("unit"),
                lo.get("referenceDatum"),
                hi.get("value"),
                hi.get("unit"),
                hi.get("referenceDatum"),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

_UPSERT_WAYPOINT = """
INSERT INTO waypoints
    (id, kind, name, ident, iata_code, type_code, country,
     location, elevation_ft, frequency_mhz, compulsory, fetched_at)
VALUES
    ($1, $2, $3, $4, $5, $6, $7,
     ST_SetSRID(ST_MakePoint($8, $9), 4326), $10, $11, $12, NOW())
ON CONFLICT (id) DO UPDATE SET
    kind          = EXCLUDED.kind,
    name          = EXCLUDED.name,
    ident         = EXCLUDED.ident,
    iata_code     = EXCLUDED.iata_code,
    type_code     = EXCLUDED.type_code,
    country       = EXCLUDED.country,
    location      = EXCLUDED.location,
    elevation_ft  = EXCLUDED.elevation_ft,
    frequency_mhz = EXCLUDED.frequency_mhz,
    compulsory    = EXCLUDED.compulsory,
    fetched_at    = EXCLUDED.fetched_at
"""

_UPSERT_AIRSPACE = """
INSERT INTO airspaces
    (id, name, type_code, icao_class, country, geometry,
     lower_limit_value, lower_limit_unit, lower_limit_ref,
     upper_limit_value, upper_limit_unit, upper_limit_ref,
     fetched_at)
VALUES
    ($1, $2, $3, $4, $5, ST_GeomFromGeoJSON($6),
     $7, $8, $9, $10, $11, $12, NOW())
ON CONFLICT (id) DO UPDATE SET
    name              = EXCLUDED.name,
    type_code         = EXCLUDED.type_code,
    icao_class        = EXCLUDED.icao_class,
    country           = EXCLUDED.country,
    geometry          = EXCLUDED.geometry,
    lower_limit_value = EXCLUDED.lower_limit_value,
    lower_limit_unit  = EXCLUDED.lower_limit_unit,
    lower_limit_ref   = EXCLUDED.lower_limit_ref,
    upper_limit_value = EXCLUDED.upper_limit_value,
    upper_limit_unit  = EXCLUDED.upper_limit_unit,
    upper_limit_ref   = EXCLUDED.upper_limit_ref,
    fetched_at        = EXCLUDED.fetched_at
"""


async def _upsert_waypoints(
    conn: asyncpg.Connection[asyncpg.Record],
    rows: list[WaypointRow],
) -> None:
    for i in range(0, len(rows), BATCH_SIZE):
        await conn.executemany(_UPSERT_WAYPOINT, rows[i : i + BATCH_SIZE])


async def _upsert_airspaces(
    conn: asyncpg.Connection[asyncpg.Record],
    rows: list[AirspaceRow],
) -> None:
    for i in range(0, len(rows), BATCH_SIZE):
        await conn.executemany(_UPSERT_AIRSPACE, rows[i : i + BATCH_SIZE])


# ---------------------------------------------------------------------------
# Download + parse + store one file
# ---------------------------------------------------------------------------


async def _process_file(
    client: httpx.AsyncClient,
    conn: asyncpg.Connection[asyncpg.Record],
    name: str,
    dl_sem: asyncio.Semaphore,
    db_sem: asyncio.Semaphore,
) -> int:
    # Download + parse concurrently (limited by dl_sem).
    async with dl_sem:
        r = await client.get(f"{GCS_BASE}/{name}")
        r.raise_for_status()
        data = r.content

    if name.endswith("_apt.ndgeojson"):
        rows_w: list[WaypointRow] = _parse_airports(data)
        async with db_sem:
            await _upsert_waypoints(conn, rows_w)
        return len(rows_w)
    elif name.endswith("_nav.ndgeojson"):
        rows_w = _parse_navaids(data)
        async with db_sem:
            await _upsert_waypoints(conn, rows_w)
        return len(rows_w)
    elif name.endswith("_rpp.ndgeojson"):
        rows_w = _parse_reporting_points(data)
        async with db_sem:
            await _upsert_waypoints(conn, rows_w)
        return len(rows_w)
    elif name.endswith("_asp.ndgeojson"):
        rows_a: list[AirspaceRow] = _parse_airspaces(data)
        async with db_sem:
            await _upsert_airspaces(conn, rows_a)
        return len(rows_a)
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


@sentry_sdk.monitor(
    monitor_slug="import-openaip",
    monitor_config={
        "schedule": {"type": "crontab", "value": "0 2 * * *"},
        "timezone": "UTC",
        "checkin_margin": 30,
        "max_runtime": 60,
    },
)
async def _main() -> None:
    settings = get_settings()
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(settings.asyncpg_dsn)
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            # List all ndgeojson files in the bucket
            print("Listing bucket…", file=sys.stderr)
            all_files = await _list_files(client, ".ndgeojson")
            relevant = [
                f
                for f in all_files
                if any(
                    f.endswith(s)
                    for s in (
                        "_apt.ndgeojson",
                        "_nav.ndgeojson",
                        "_rpp.ndgeojson",
                        "_asp.ndgeojson",
                    )
                )
            ]
            print(f"Found {len(relevant)} files to import", file=sys.stderr)

            dl_sem = asyncio.Semaphore(MAX_CONCURRENT)
            db_sem = asyncio.Semaphore(1)
            tasks = [_process_file(client, conn, name, dl_sem, db_sem) for name in relevant]
            total = 0
            for done, coro in enumerate(asyncio.as_completed(tasks), 1):
                try:
                    n = await coro
                except Exception as exc:
                    logger.warning("File failed: %s", exc)
                    n = 0
                total += n
                if done % 50 == 0 or done == len(tasks):
                    print(
                        f"  {done}/{len(tasks)} files  {total:,} records",
                        file=sys.stderr,
                        flush=True,
                    )

        wp_count: int = await conn.fetchval("SELECT COUNT(*) FROM waypoints")
        as_count: int = await conn.fetchval("SELECT COUNT(*) FROM airspaces")
        print(
            f"Done. waypoints={wp_count:,}  airspaces={as_count:,}",
            file=sys.stderr,
        )
    except Exception:
        logger.exception("Import failed")
        raise
    finally:
        await conn.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    settings = get_settings()
    settings.init_sentry()
    try:
        asyncio.run(_main())
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
