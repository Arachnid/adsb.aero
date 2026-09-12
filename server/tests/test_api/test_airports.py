"""Integration tests for the waypoint and airport lookup endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    import asyncpg
    from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_INSERT_WAYPOINT = """
    INSERT INTO waypoints
        (id, kind, name, ident, iata_code, type_code, country,
         location, elevation_ft, fetched_at)
    VALUES ($1, $2, $3, $4, $5, $6, $7,
            ST_SetSRID(ST_MakePoint($8, $9), 4326), $10, NOW())
    ON CONFLICT (id) DO NOTHING
"""

_NOW = datetime.now(UTC)

_WAYPOINTS = [
    ("wp-egll", "airport", "LONDON HEATHROW", "EGLL", "LHR", 3, "GB", -0.461389, 51.4775, 83),
    ("wp-ksfo", "airport", "SAN FRANCISCO INTL", "KSFO", "SFO", 3, "US", -122.375, 37.619, 13),
    ("wp-eglt", "airport", "ASCOT RACECOURSE HELIPORT", "EGLT", None, 7, "GB", -0.668, 51.409, 50),
    ("wp-bnn", "navaid", "BOVINGDON", "BNN", None, 3, "GB", -0.549, 51.726, 488),
    ("wp-divis", "reporting_point", "DIVIS", None, None, None, "GB", -6.030, 54.590, 365),
]


@pytest_asyncio.fixture(scope="session")
async def waypoint_data(pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    for row in _WAYPOINTS:
        await pool.execute(_INSERT_WAYPOINT, *row)


@pytest_asyncio.fixture(scope="session")
async def wp_client(
    pool: asyncpg.Pool,
    waypoint_data: None,
) -> AsyncClient:
    from httpx import ASGITransport, AsyncClient

    from adsb_server.api.main import app

    app.state.pool = pool
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client  # type: ignore[misc]


async def test_search_returns_matching_waypoints(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/search", params={"q": "heathrow"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["ident"] == "EGLL"
    assert data[0]["iata_code"] == "LHR"
    assert data[0]["kind"] == "airport"
    assert data[0]["lon"] == pytest.approx(-0.461389, abs=1e-4)


async def test_search_prefix_match(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/search", params={"q": "egll"})
    assert resp.status_code == 200
    idents = {r["ident"] for r in resp.json()}
    assert "EGLL" in idents


async def test_search_navaid(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/search", params={"q": "BNN"})
    assert resp.status_code == 200
    hits = resp.json()
    bnn = next((r for r in hits if r["ident"] == "BNN"), None)
    assert bnn is not None
    assert bnn["kind"] == "navaid"


async def test_search_kind_filter(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/search", params={"q": "bov", "kinds": "navaid"})
    assert resp.status_code == 200
    assert all(r["kind"] == "navaid" for r in resp.json())


async def test_search_limit(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/search", params={"q": "london", "limit": 1})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_search_empty_after_strip(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/search", params={"q": "!!!"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_missing_q(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/search")
    assert resp.status_code == 422


async def test_get_waypoint_happy_path(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/wp-egll")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "wp-egll"
    assert data["ident"] == "EGLL"
    assert data["kind"] == "airport"
    assert data["country"] == "GB"


async def test_get_waypoint_not_found(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /airports/{code} — code lookup plus aerodrome airspace polygons
# ---------------------------------------------------------------------------

_INSERT_AIRSPACE = """
    INSERT INTO airspaces
        (id, name, type_code, icao_class, country, geometry,
         lower_limit_value, lower_limit_unit, lower_limit_ref,
         upper_limit_value, upper_limit_unit, upper_limit_ref, fetched_at)
    VALUES ($1, $2, $3, $4, $5,
            ST_SetSRID(ST_MakeEnvelope($6, $7, $8, $9), 4326),
            $10, $11, $12, $13, $14, $15, NOW())
    ON CONFLICT (id) DO NOTHING
"""

# Synthetic airspaces around EGLL (-0.461389, 51.4775). Envelopes, not real
# boundaries — the endpoint's job is selection and ordering, not geometry.
#
# id, name, type, class, country, (min_lon, min_lat, max_lon, max_lat),
#   lower (value, unit, ref), upper (value, unit, ref)
_AIRSPACES = [
    # ATZ: smallest, contains EGLL → expected first.
    ("as-egll-atz", "HEATHROW ATZ", 13, 3, "GB", -0.50, 51.45, -0.42, 51.51, 0, 1, 0, 2500, 1, 1),
    # CTR: larger, also contains EGLL → expected second.
    ("as-egll-ctr", "LONDON CTR", 4, 3, "GB", -0.70, 51.35, -0.20, 51.60, 0, 1, 0, 2500, 1, 1),
    # TMA: contains EGLL but serves a whole terminal area → must be excluded.
    ("as-london-tma", "LONDON TMA", 7, 1, "GB", -1.50, 51.00, 0.50, 52.00, 3500, 1, 1, 245, 6, 2),
    # Danger area nowhere near EGLL → must be excluded.
    ("as-danger", "D138 SALISBURY", 2, 8, "GB", 2.00, 52.00, 2.10, 52.10, 0, 1, 0, 5000, 1, 1),
    # ATZ around EGLT carrying an unrecognised unit code (9) on its upper limit.
    ("as-eglt-atz", "ASCOT ATZ", 13, 6, "GB", -0.70, 51.39, -0.64, 51.43, 0, 1, 0, 1500, 9, 1),
]


@pytest_asyncio.fixture(scope="session")
async def airspace_data(pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    for row in _AIRSPACES:
        await pool.execute(_INSERT_AIRSPACE, *row)
    # Synthetic precedence case: this field's IATA code collides with EGLL's
    # ICAO code, so a lookup of "EGLL" must still resolve to Heathrow.
    await pool.execute(
        _INSERT_WAYPOINT,
        "wp-collide",
        "airport",
        "COLLIDING FIELD",
        "ZZZZ",
        "EGLL",
        2,
        "GB",
        10.0,
        45.0,
        100,
    )


async def test_airport_by_icao_code(wp_client: AsyncClient, airspace_data: None) -> None:
    resp = await wp_client.get("/api/v1/airports/EGLL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ident"] == "EGLL"
    assert data["kind"] == "airport"
    assert data["lon"] == pytest.approx(-0.461389, abs=1e-4)


async def test_airport_by_iata_code(wp_client: AsyncClient, airspace_data: None) -> None:
    resp = await wp_client.get("/api/v1/airports/LHR")
    assert resp.status_code == 200
    assert resp.json()["ident"] == "EGLL"


async def test_airport_code_is_case_insensitive(
    wp_client: AsyncClient, airspace_data: None
) -> None:
    resp = await wp_client.get("/api/v1/airports/egll")
    assert resp.status_code == 200
    assert resp.json()["ident"] == "EGLL"


async def test_icao_code_beats_iata_collision(wp_client: AsyncClient, airspace_data: None) -> None:
    """A field whose IATA code equals another's ICAO code must not win."""
    resp = await wp_client.get("/api/v1/airports/EGLL")
    assert resp.status_code == 200
    assert resp.json()["name"] == "LONDON HEATHROW"


async def test_airport_returns_aerodrome_airspaces_smallest_first(
    wp_client: AsyncClient, airspace_data: None
) -> None:
    resp = await wp_client.get("/api/v1/airports/EGLL")
    assert resp.status_code == 200
    spaces = resp.json()["airspaces"]

    names = [a["name"] for a in spaces]
    assert names == ["HEATHROW ATZ", "LONDON CTR"], (
        "expected only aerodrome airspaces containing the field, smallest first"
    )
    assert [a["type_name"] for a in spaces] == ["ATZ", "CTR"]
    assert spaces[0]["area_km2"] < spaces[1]["area_km2"]


async def test_airport_excludes_tma_and_distant_airspace(
    wp_client: AsyncClient, airspace_data: None
) -> None:
    resp = await wp_client.get("/api/v1/airports/EGLL")
    names = {a["name"] for a in resp.json()["airspaces"]}
    assert "LONDON TMA" not in names, "TMA serves a terminal area, not one field"
    assert "D138 SALISBURY" not in names


async def test_airspace_geometry_is_usable_as_a_query_predicate(
    wp_client: AsyncClient, airspace_data: None
) -> None:
    """The returned polygon must validate as an `endpoint_within` geometry."""
    from adsb_server.query.models import EndpointWithin

    resp = await wp_client.get("/api/v1/airports/EGLL")
    geometry = resp.json()["airspaces"][0]["geometry"]
    assert geometry["type"] in {"Polygon", "MultiPolygon"}

    predicate = EndpointWithin.model_validate(
        {"endpoint_within": {"mode": "end", "geometry": geometry}}
    )
    assert predicate.endpoint_within.geometry is not None


async def test_airspace_limits_are_decoded(wp_client: AsyncClient, airspace_data: None) -> None:
    resp = await wp_client.get("/api/v1/airports/EGLL")
    atz = resp.json()["airspaces"][0]
    assert atz["lower_limit"] == {"value": 0, "unit": "ft", "ref": "gnd"}
    assert atz["upper_limit"] == {"value": 2500, "unit": "ft", "ref": "msl"}
    assert atz["icao_class"] == 3


async def test_unknown_limit_unit_is_dropped_not_guessed(
    wp_client: AsyncClient, airspace_data: None
) -> None:
    """An unrecognised unit code yields null — a wrong altitude is worse."""
    resp = await wp_client.get("/api/v1/airports/EGLT")
    assert resp.status_code == 200
    atz = resp.json()["airspaces"][0]
    assert atz["name"] == "ASCOT ATZ"
    assert atz["upper_limit"] is None
    assert atz["lower_limit"] == {"value": 0, "unit": "ft", "ref": "gnd"}


async def test_airport_without_airspace_returns_empty_list(
    wp_client: AsyncClient, airspace_data: None
) -> None:
    resp = await wp_client.get("/api/v1/airports/KSFO")
    assert resp.status_code == 200
    assert resp.json()["airspaces"] == []


async def test_airport_not_found_suggests_search(
    wp_client: AsyncClient, airspace_data: None
) -> None:
    resp = await wp_client.get("/api/v1/airports/XXXX")
    assert resp.status_code == 404
    assert "waypoints/search" in resp.json()["detail"]


async def test_navaid_ident_is_not_an_airport(wp_client: AsyncClient, airspace_data: None) -> None:
    """BNN is a navaid; the airport lookup must not return it."""
    resp = await wp_client.get("/api/v1/airports/BNN")
    assert resp.status_code == 404
