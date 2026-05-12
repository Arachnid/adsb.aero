"""Tests for MobilityDB temporal type construction helpers."""

from __future__ import annotations

from adsb_server.geometry.wkt import tgeompoint_seq, tint_seq


def test_tgeompoint_seq_format() -> None:
    vertices = [
        (-0.1278, 51.5074, 35000.0, 1609275898.0),
        (-0.5, 52.0, 36000.0, 1609276000.0),
    ]
    result = tgeompoint_seq(vertices)
    assert result.startswith("SRID=4326;[")
    assert result.endswith("]")
    assert "POINT Z" in result
    assert "-0.1278" in result
    assert "51.5074" in result
    assert "35000.0" in result
    assert "36000.0" in result
    # Two instants separated by a comma
    assert ", " in result


def test_tgeompoint_seq_single_vertex() -> None:
    vertices = [(10.0, 20.0, 5000.0, 1609275898.0)]
    result = tgeompoint_seq(vertices)
    assert result.startswith("SRID=4326;[")
    assert result.endswith("]")
    assert "POINT Z (10.0 20.0 5000.0)@" in result


def test_tgeompoint_seq_timestamp_format() -> None:
    # unix epoch 0 = 1970-01-01T00:00:00+00:00
    vertices = [(0.0, 0.0, 0.0, 0.0)]
    result = tgeompoint_seq(vertices)
    assert "1970-01-01T00:00:00" in result
    assert "+00" in result


def test_tgeompoint_seq_three_vertices() -> None:
    vertices = [
        (0.0, 0.0, 0.0, 0.0),
        (1.0, 1.0, 1000.0, 100.0),
        (2.0, 2.0, 2000.0, 200.0),
    ]
    result = tgeompoint_seq(vertices)
    assert result.count("POINT Z") == 3
    assert result.count("@") == 3


def test_tint_seq_format() -> None:
    values = [90, 315]
    timestamps = [1609275898.0, 1609276000.0]
    result = tint_seq(values, timestamps)
    assert result.startswith("[")
    assert result.endswith("]")
    assert "90@" in result
    assert "315@" in result
    assert ", " in result


def test_tint_seq_single_value() -> None:
    result = tint_seq([180], [1609275898.0])
    assert result.startswith("[")
    assert result.endswith("]")
    assert "180@" in result


def test_tint_seq_timestamp_format() -> None:
    result = tint_seq([0], [0.0])
    assert "0@1970-01-01T00:00:00" in result
    assert "+00" in result


def test_tint_seq_zero_track() -> None:
    result = tint_seq([0, 0, 0], [100.0, 200.0, 300.0])
    assert result.count("0@") == 3
