"""Fetch global MSLP fields from GFS via Herbie for a given time range."""

from __future__ import annotations

import asyncio
import importlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np
import xarray as xr

if TYPE_CHECKING:
    from datetime import date
    from pathlib import Path

logger = logging.getLogger(__name__)

# Parallel download workers. 8 is enough to saturate a typical connection
# without hammering the upstream server.
_DOWNLOAD_WORKERS = 8


def _fetch_hour(
    run_date: date,
    run_hour: int,
    fxx: int,
    valid_ts: np.datetime64,
    cache_dir: Path,
) -> tuple[np.datetime64, xr.DataArray] | None:
    """
    Fetch one MSLP slice (blocking). Returns (valid_ts, DataArray) or None.

    Values are converted to hPa and tagged with a valid_time coordinate.
    Herbie-supplied run-time coordinates are dropped so slices from different
    run cycles can be concatenated without conflicts.
    """
    from herbie import Herbie

    logger.debug("Downloading MSLP %s %02dZ+%d", run_date, run_hour, fxx)
    try:
        herbie = Herbie(
            f"{run_date!s} {run_hour:02d}:00",
            model="gfs",
            product="pgrb2.0p25",
            fxx=fxx,
            save_dir=cache_dir,
            verbose=False,
        )
        ds: xr.Dataset = herbie.xarray("PRMSL:mean sea level")
        var_name = next(iter(ds.data_vars))
        da: xr.DataArray = ds[var_name].squeeze(drop=True)

        # GFS PRMSL is in Pa; convert to hPa
        if float(da.max().item()) > 2000.0:
            da = da / 100.0

        da = (
            da.drop_vars([c for c in da.coords if c not in ("latitude", "longitude")])
            .assign_coords(valid_time=valid_ts)
            .expand_dims("valid_time")
        )
        logger.debug("Fetched MSLP %s %02dZ+%d OK", run_date, run_hour, fxx)
        return valid_ts, da
    except Exception:
        logger.warning(
            "Failed to fetch MSLP %s %02dZ+%d",
            run_date,
            run_hour,
            fxx,
            exc_info=True,
        )
        return None


def _build_mslp_range(
    start_date: date,
    n_hours: int,
    cache_dir: Path,
) -> xr.DataArray | None:
    """
    Fetch n_hours consecutive UTC hours of GFS MSLP starting at start_date 00:00 (blocking).

    Each hour is served by the analysis cycle with the shortest forecast lag
    (00Z covers 0-5h, 06Z covers 6-11h, etc.).  When n_hours spans multiple
    calendar days the correct run date is derived automatically.

    Downloads run in parallel (_DOWNLOAD_WORKERS threads).
    Returns a DataArray with dims (valid_time, latitude, longitude), values
    in hPa, with the longitude axis padded to [-0.25, 360.0] so that
    bilinear interpolation across the 0°/360° seam is continuous.
    Returns None if no data could be retrieved.
    """
    try:
        importlib.import_module("herbie")
    except Exception:
        logger.error("herbie-data is not installed; cannot fetch MSLP")
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Fetching GFS MSLP %s +%dh (workers: %d)",
        start_date,
        n_hours,
        _DOWNLOAD_WORKERS,
    )

    # Map each required hour to (run_date, run_hour, fxx, valid_ts).
    # Assign each valid hour to the analysis cycle with the shortest lag.
    base = datetime(start_date.year, start_date.month, start_date.day)
    tasks: list[tuple[date, int, int, np.datetime64]] = []
    seen: set[np.datetime64] = set()
    for h in range(n_hours):
        valid_dt = base + timedelta(hours=h)
        run_hour = (valid_dt.hour // 6) * 6
        fxx = valid_dt.hour - run_hour
        run_date = valid_dt.date()
        valid_ts = np.datetime64(valid_dt.strftime("%Y-%m-%dT%H:00:00"), "ns")
        if valid_ts not in seen:
            tasks.append((run_date, run_hour, fxx, valid_ts))
            seen.add(valid_ts)

    slices: dict[np.datetime64, xr.DataArray] = {}
    with ThreadPoolExecutor(max_workers=_DOWNLOAD_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_hour, rd, rh, fx, vts, cache_dir): (rd, rh, fx)
            for rd, rh, fx, vts in tasks
        }
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                vts, da = result
                slices[vts] = da

    if not slices:
        logger.error("No MSLP data retrieved for %s +%dh", start_date, n_hours)
        return None

    sorted_slices = [slices[ts] for ts in sorted(slices)]
    logger.info(
        "Fetched %d/%d MSLP hours from %s; shape %s",
        len(sorted_slices),
        n_hours,
        start_date,
        sorted_slices[0].shape,
    )

    mslp: xr.DataArray = xr.concat(sorted_slices, dim="valid_time", coords="minimal").sortby(
        "valid_time"
    )

    # Pad the longitude axis so that bilinear interpolation is continuous
    # across the 0°/360° seam.  After padding, longitude runs from -0.25
    # to 360.0 with 1442 columns instead of 1440.
    east_pad = mslp.isel(longitude=0).assign_coords(longitude=360.0)
    west_pad = mslp.isel(longitude=-1).assign_coords(longitude=-0.25)
    return xr.concat([west_pad, mslp, east_pad], dim="longitude")


async def fetch_mslp_day(batch_date: date, cache_dir: Path) -> xr.DataArray | None:
    """Fetch 25 hours of GFS MSLP for batch_date (00:00 through next day 00:00)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _build_mslp_range, batch_date, 25, cache_dir)


async def fetch_mslp_for_batch(batch_date: date, cache_dir: Path) -> xr.DataArray | None:
    """
    Fetch 49 hours of GFS MSLP for a batch ingestion run.

    Covers (batch_date - 1) 00:00 through batch_date 24:00, giving:
      - full previous-day coverage for in-progress flights carried over from staging
      - an extra hour past midnight for flights at 23:30 on batch_date

    The previous day's GRIBs are typically already cached from their own run,
    so only ~25 new files need to be downloaded from the network.
    Returns None only if no data at all could be retrieved.
    """
    prev_date = batch_date - timedelta(days=1)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _build_mslp_range, prev_date, 49, cache_dir)
