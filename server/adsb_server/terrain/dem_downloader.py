"""Bulk downloader for the Copernicus GLO-90 DEM dataset.

Downloads all 1x1 degree tiles from the AWS Open Data bucket, converts each
from float32-metres GeoTIFF to a compact int16-feet .npy file, and writes it
to a local directory.  No .tif files are kept on disk; conversion happens
in-memory via rasterio.MemoryFile.

Usage:
    download-terrain
    download-terrain --data-dir /data/terrain --workers 32

The download is safe to interrupt and resume: tiles that already have a .npy
file or a confirmed-absent marker (.missing) are skipped.  HTTP errors and
timeouts are logged as warnings and retried automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import httpx
import numpy as np

from adsb_server.config import get_settings
from adsb_server.terrain.tiles import _tile_name

logger = logging.getLogger(__name__)

_BASE_URL = "https://copernicus-dem-90m.s3.amazonaws.com"
_MISSING_SUFFIX = ".missing"

# GLO-90 covers -90 to +84 latitude, -180 to +179 longitude.
_LAT_RANGE = range(-90, 84)
_LON_RANGE = range(-180, 180)


def _all_tile_coords() -> list[tuple[int, int]]:
    return [(lat, lon) for lat in _LAT_RANGE for lon in _LON_RANGE]


def _tif_to_npy(content: bytes, npy_path: Path) -> None:
    """Convert GeoTIFF bytes to an int16-feet .npy file.

    Uses rasterio.MemoryFile so no temporary file touches disk.
    Cleans up a partial npy_path and re-raises on any error.
    """
    from rasterio.io import MemoryFile

    try:
        with MemoryFile(content) as memfile, memfile.open() as ds:
            data = ds.read(1)  # float32 metres
            nodata = ds.nodata
        if nodata is not None:
            data = np.where(data == nodata, np.float32(0.0), data)
        feet = np.round(data * np.float32(1.0 / 0.3048)).clip(-32768, 32767).astype(np.int16)
        np.save(npy_path, feet)
    except Exception:
        npy_path.unlink(missing_ok=True)
        raise


async def _download_tile(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    data_dir: Path,
    lat: int,
    lon: int,
) -> str:
    """Download and convert one tile. Returns 'skip', 'downloaded', 'missing', or 'error'."""
    name = _tile_name(lat, lon)
    npy_path = data_dir / f"{name}.npy"
    missing_path = data_dir / f"{name}{_MISSING_SUFFIX}"

    if npy_path.exists() or missing_path.exists():
        return "skip"

    url = f"{_BASE_URL}/{name}/{name}.tif"
    async with sem:
        try:
            async with client.stream("GET", url) as resp:
                if resp.status_code == 404:
                    missing_path.touch()
                    return "missing"
                resp.raise_for_status()
                chunks: list[bytes] = []
                async for chunk in resp.aiter_bytes(chunk_size=1 << 20):
                    chunks.append(chunk)
            _tif_to_npy(b"".join(chunks), npy_path)
            return "downloaded"
        except Exception:
            logger.warning("Failed to download tile lat=%d lon=%d", lat, lon, exc_info=True)
            return "error"


async def download_all(data_dir: Path, workers: int = 16, max_retries: int = 3) -> None:
    """Download and convert all GLO-90 tiles into data_dir with concurrent connections.

    Error tiles are retried automatically up to max_retries times within the same run.
    """
    data_dir.mkdir(parents=True, exist_ok=True)

    total_counts: dict[str, int] = {"downloaded": 0, "missing": 0, "skip": 0}
    sem = asyncio.Semaphore(workers)
    limits = httpx.Limits(max_connections=workers, max_keepalive_connections=workers)

    async with httpx.AsyncClient(timeout=120, follow_redirects=True, limits=limits) as client:
        pending: list[tuple[int, int]] = _all_tile_coords()

        for attempt in range(1 + max_retries):
            if not pending:
                break
            if attempt > 0:
                logger.info("Retry %d/%d: %d tiles to retry", attempt, max_retries, len(pending))

            errors: list[tuple[int, int]] = []
            n = len(pending)
            done = 0

            async def _run(
                lat: int,
                lon: int,
                _errors: list[tuple[int, int]] = errors,
                _n: int = n,
            ) -> None:
                nonlocal done
                result = await _download_tile(client, sem, data_dir, lat, lon)
                if result == "error":
                    _errors.append((lat, lon))
                else:
                    total_counts[result] += 1
                done += 1
                if done % 500 == 0 or done == _n:
                    logger.info(
                        "%d / %d  (downloaded=%d  not-on-land=%d  skip=%d  error=%d)",
                        done,
                        _n,
                        total_counts["downloaded"],
                        total_counts["missing"],
                        total_counts["skip"],
                        len(_errors),
                    )

            await asyncio.gather(*[asyncio.create_task(_run(lat, lon)) for lat, lon in pending])
            pending = errors

    logger.info(
        "Download complete: %d downloaded, %d not-on-land, %d skipped, %d persistent errors",
        total_counts["downloaded"],
        total_counts["missing"],
        total_counts["skip"],
        len(pending),
    )
    if pending:
        logger.warning(
            "%d tiles still failing after %d retries: %s …",
            len(pending),
            max_retries,
            pending[:5],
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Download Copernicus GLO-90 DEM tiles as int16-feet .npy files"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=settings.terrain_data_dir,
        metavar="DIR",
        help=f"Directory to write .npy tiles into (default: {settings.terrain_data_dir})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=16,
        metavar="N",
        help="Number of concurrent HTTP connections (default: 16)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        metavar="N",
        help="Number of times to retry failed tiles within the same run (default: 3)",
    )
    return parser.parse_args(argv)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    args = _parse_args()
    logger.info("Downloading GLO-90 tiles to %s with %d workers", args.data_dir, args.workers)
    asyncio.run(download_all(args.data_dir, workers=args.workers, max_retries=args.max_retries))


if __name__ == "__main__":
    main()
