"""Fixtures for ingestion integration tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from adsb_server.pressure.correct import _ISA_HPA


def _make_test_mslp() -> xr.DataArray:
    """ISA-standard MSLP DataArray covering a wide time range for testing."""
    lons = np.array([-0.25, 0.0, 90.0, 180.0, 270.0, 359.75, 360.0])
    lats = np.array([-90.0, 0.0, 90.0])
    times = pd.to_datetime(["2000-01-01", "2030-01-01"])
    data = np.full((len(times), len(lats), len(lons)), _ISA_HPA)
    return xr.DataArray(
        data,
        dims=("valid_time", "latitude", "longitude"),
        coords={"valid_time": times, "latitude": lats, "longitude": lons},
    )


@pytest.fixture
def mslp() -> xr.DataArray:
    """ISA-standard MSLP DataArray for use as prefetched_mslp in batch tests."""
    return _make_test_mslp()
