"""Fixtures for ingestion integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest
import xarray as xr

if TYPE_CHECKING:
    from collections.abc import Generator

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


@pytest.fixture(autouse=True)
def mock_fetch_mslp() -> Generator[None, None, None]:
    """Patch fetch_mslp_for_batch so batch tests don't hit the network or /data."""
    with patch(
        "adsb_server.ingestion.batch.fetch_mslp_for_batch",
        new_callable=AsyncMock,
        return_value=_make_test_mslp(),
    ):
        yield
