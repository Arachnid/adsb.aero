"""Unit tests for OpenAIP airspace limit decoding.

`/airports/{code}` turns OpenAIP's numeric unit/reference codes into symbolic
ones so callers don't have to carry a lookup table. Getting this wrong would
publish a confidently wrong altitude, so the decoder fails closed.
"""

from __future__ import annotations

import pytest

from adsb_server.api.main import _airspace_limit


def test_decodes_feet_above_mean_sea_level() -> None:
    limit = _airspace_limit(2500, 1, 1)
    assert limit is not None
    assert (limit.value, limit.unit, limit.ref) == (2500, "ft", "msl")


def test_decodes_ground_reference() -> None:
    limit = _airspace_limit(0, 1, 0)
    assert limit is not None
    assert limit.ref == "gnd"


def test_decodes_metres() -> None:
    limit = _airspace_limit(900, 0, 1)
    assert limit is not None
    assert limit.unit == "m"


def test_decodes_flight_level_as_standard_pressure() -> None:
    limit = _airspace_limit(245, 6, 2)
    assert limit is not None
    assert (limit.unit, limit.ref) == ("fl", "std")


@pytest.mark.parametrize("value,unit", [(None, 1), (2500, None), (None, None)])
def test_missing_value_or_unit_yields_none(value: int | None, unit: int | None) -> None:
    assert _airspace_limit(value, unit, 1) is None


def test_unknown_unit_yields_none_rather_than_a_guess() -> None:
    """An unrecognised unit code must not be silently treated as feet."""
    assert _airspace_limit(2500, 99, 1) is None


def test_zero_is_a_real_limit_not_a_missing_one() -> None:
    """Surface level is 0 ft GND — it must not be confused with absent."""
    limit = _airspace_limit(0, 1, 0)
    assert limit is not None
    assert limit.value == 0


def test_unknown_reference_falls_back_to_msl() -> None:
    """A limit with an odd datum is still worth returning; MSL is the safe read."""
    limit = _airspace_limit(2500, 1, 99)
    assert limit is not None
    assert limit.ref == "msl"


def test_null_reference_falls_back_to_msl() -> None:
    limit = _airspace_limit(2500, 1, None)
    assert limit is not None
    assert limit.ref == "msl"
