import pytest
from httpx import ASGITransport, AsyncClient

from adsb_server.api.main import app


@pytest.mark.asyncio
async def test_health() -> None:
    app.state.pool = None  # prevent lifespan from connecting to real DB
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
