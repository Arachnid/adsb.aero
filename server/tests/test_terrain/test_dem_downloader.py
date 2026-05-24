"""Unit tests for adsb_server.terrain.dem_downloader."""

from __future__ import annotations

import asyncio
from pathlib import Path  # noqa: TC003
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import numpy as np

from adsb_server.terrain.dem_downloader import (
    _MISSING_SUFFIX,
    _all_tile_coords,
    _download_tile,
    _tif_to_npy,
    download_all,
)
from adsb_server.terrain.tiles import _tile_name


def _fake_tif_to_npy(content: bytes, npy: Path) -> None:
    """Test stand-in: write a synthetic .npy without touching rasterio."""
    data = np.full((20, 20), 328, dtype=np.int16)
    np.save(npy, data)


# ---------------------------------------------------------------------------
# _tile_name (smoke-test via dem_downloader context)
# ---------------------------------------------------------------------------


def test_tile_name_basic() -> None:
    assert _tile_name(51, 4) == "Copernicus_DSM_COG_30_N51_00_E004_00_DEM"


# ---------------------------------------------------------------------------
# _all_tile_coords
# ---------------------------------------------------------------------------


def test_all_tile_coords_count() -> None:
    coords = _all_tile_coords()
    assert len(coords) == 174 * 360  # = 62,640


def test_all_tile_coords_range() -> None:
    coords = _all_tile_coords()
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    assert min(lats) == -90
    assert max(lats) == 83
    assert min(lons) == -180
    assert max(lons) == 179


# ---------------------------------------------------------------------------
# _tif_to_npy
# ---------------------------------------------------------------------------


def _make_tif_bytes() -> bytes:
    """Return in-memory GeoTIFF bytes (20x20, uniform 200 m elevation)."""
    import io

    import rasterio
    from rasterio.transform import from_bounds

    buf = io.BytesIO()
    transform = from_bounds(0, 0, 1, 1, 20, 20)
    data = np.full((20, 20), 200.0, dtype=np.float32)
    with rasterio.open(
        buf,
        "w",
        driver="GTiff",
        height=20,
        width=20,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data, 1)
    return buf.getvalue()


def test_tif_to_npy_from_bytes(tmp_path: Path) -> None:
    """_tif_to_npy converts GeoTIFF bytes to int16-feet .npy without any temp file."""
    npy = tmp_path / "test.npy"
    _tif_to_npy(_make_tif_bytes(), npy)

    assert npy.exists()
    arr = np.load(npy)
    assert arr.dtype == np.int16
    # 200 m / 0.3048 ≈ 656 ft
    assert abs(int(arr.flat[0]) - 656) <= 1
    # No leftover files other than the .npy
    assert list(tmp_path.iterdir()) == [npy]


def test_tif_to_npy_bad_bytes_raises(tmp_path: Path) -> None:
    """_tif_to_npy raises on corrupt input and leaves no partial .npy."""
    import contextlib

    npy = tmp_path / "bad.npy"
    with contextlib.suppress(Exception):
        _tif_to_npy(b"not a tif", npy)

    assert not npy.exists()


# ---------------------------------------------------------------------------
# _download_tile
# ---------------------------------------------------------------------------


def _make_client(status: int, content: bytes = b"TIFFDATA") -> httpx.AsyncClient:
    """Build a mock AsyncClient whose stream() yields the given status and body."""
    mock_resp = MagicMock()
    mock_resp.status_code = status

    async def _aiter_bytes(chunk_size: int = 1 << 20):  # type: ignore[override]
        yield content

    mock_resp.aiter_bytes = _aiter_bytes
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_client.stream.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_client


async def test_download_tile_writes_npy(tmp_path: Path) -> None:
    client = _make_client(200, b"TIFFDATA")
    sem = asyncio.Semaphore(1)

    with patch("adsb_server.terrain.dem_downloader._tif_to_npy", side_effect=_fake_tif_to_npy):
        result = await _download_tile(client, sem, tmp_path, lat=51, lon=4)  # type: ignore[arg-type]

    assert result == "downloaded"
    name = _tile_name(51, 4)
    npy = tmp_path / f"{name}.npy"
    assert npy.exists()
    assert not (tmp_path / f"{name}.tif").exists()


async def test_download_tile_404_writes_missing(tmp_path: Path) -> None:
    client = _make_client(404)
    sem = asyncio.Semaphore(1)

    result = await _download_tile(client, sem, tmp_path, lat=0, lon=0)  # type: ignore[arg-type]

    assert result == "missing"
    name = _tile_name(0, 0)
    missing = tmp_path / f"{name}{_MISSING_SUFFIX}"
    assert missing.exists()
    assert not (tmp_path / f"{name}.npy").exists()


async def test_download_tile_skips_existing_npy(tmp_path: Path) -> None:
    name = _tile_name(10, 20)
    (tmp_path / f"{name}.npy").write_bytes(b"existing")
    client = _make_client(200)
    sem = asyncio.Semaphore(1)

    result = await _download_tile(client, sem, tmp_path, lat=10, lon=20)  # type: ignore[arg-type]

    assert result == "skip"
    client.stream.assert_not_called()


async def test_download_tile_skips_existing_missing_sentinel(tmp_path: Path) -> None:
    name = _tile_name(5, 5)
    (tmp_path / f"{name}{_MISSING_SUFFIX}").touch()
    client = _make_client(200)
    sem = asyncio.Semaphore(1)

    result = await _download_tile(client, sem, tmp_path, lat=5, lon=5)  # type: ignore[arg-type]

    assert result == "skip"
    client.stream.assert_not_called()


async def test_download_tile_returns_error_on_exception(tmp_path: Path) -> None:
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.stream.side_effect = httpx.ConnectError("refused")
    sem = asyncio.Semaphore(1)

    result = await _download_tile(mock_client, sem, tmp_path, lat=1, lon=1)  # type: ignore[arg-type]

    assert result == "error"
    assert list(tmp_path.iterdir()) == []


async def test_download_tile_no_leftover_tmp_on_error(tmp_path: Path) -> None:
    """If writing the downloaded bytes fails, the .tmp file is cleaned up."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()

    async def _aiter_bytes(chunk_size: int = 1 << 20):  # type: ignore[override]
        raise OSError("disk full")
        yield b""  # unreachable — needed to declare this as an async generator

    mock_resp.aiter_bytes = _aiter_bytes

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_client.stream.return_value.__aexit__ = AsyncMock(return_value=False)
    sem = asyncio.Semaphore(1)

    result = await _download_tile(mock_client, sem, tmp_path, lat=2, lon=2)  # type: ignore[arg-type]

    assert result == "error"
    tmps = list(tmp_path.glob("*.tmp"))
    assert tmps == [], "leftover .tmp file should be cleaned up on error"


# ---------------------------------------------------------------------------
# download_all
# ---------------------------------------------------------------------------


async def test_download_all_skips_all_existing(tmp_path: Path) -> None:
    """If all tiles are already present, download_all makes no HTTP requests."""
    subset = [(51, 4), (51, 5)]
    for lat, lon in subset:
        name = _tile_name(lat, lon)
        (tmp_path / f"{name}.npy").write_bytes(b"x")

    with (
        patch("adsb_server.terrain.dem_downloader._all_tile_coords", return_value=subset),
        patch("adsb_server.terrain.dem_downloader.httpx.AsyncClient") as mock_cls,
    ):
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        await download_all(tmp_path, workers=2)

        mock_client.stream.assert_not_called()


async def test_download_all_creates_data_dir(tmp_path: Path) -> None:
    new_dir = tmp_path / "nested" / "terrain"
    subset: list[tuple[int, int]] = []
    with patch("adsb_server.terrain.dem_downloader._all_tile_coords", return_value=subset):
        await download_all(new_dir, workers=1)
    assert new_dir.is_dir()


async def test_download_all_retries_errors(tmp_path: Path) -> None:
    """Tiles that error on the first pass are retried; success on retry is counted."""
    subset = [(51, 4)]
    call_count = 0

    async def _flaky_download_tile(
        client: object,
        sem: object,
        data_dir: Path,
        lat: int,
        lon: int,
    ) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "error"
        name = _tile_name(lat, lon)
        (data_dir / f"{name}.npy").write_bytes(b"NPYDATA")
        return "downloaded"

    with (
        patch("adsb_server.terrain.dem_downloader._all_tile_coords", return_value=subset),
        patch(
            "adsb_server.terrain.dem_downloader._download_tile",
            side_effect=_flaky_download_tile,
        ),
    ):
        await download_all(tmp_path, workers=1, max_retries=2)

    assert call_count == 2
    name = _tile_name(51, 4)
    assert (tmp_path / f"{name}.npy").exists()
