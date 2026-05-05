"""Tests for geometry WKT helpers."""

from __future__ import annotations

from adsb_server.geometry.wkt import linestring_zm, point_zm


def test_point_zm_format() -> None:
    result = point_zm(lon=-0.1278, lat=51.5074, alt_ft=35000.0, ts_epoch=1609275898.0)
    assert result.startswith("POINTZM(")
    assert result.endswith(")")
    assert "-0.1278" in result
    assert "51.5074" in result
    assert "35000.0" in result
    assert "1609275898.0" in result


def test_point_zm_exact() -> None:
    result = point_zm(lon=10.0, lat=20.0, alt_ft=5000.0, ts_epoch=1000.0)
    assert result == "POINTZM(10.0 20.0 5000.0 1000.0)"


def test_linestring_zm_format() -> None:
    vertices = [
        (-0.1278, 51.5074, 35000.0, 1609275898.0),
        (-0.5, 52.0, 36000.0, 1609276000.0),
    ]
    result = linestring_zm(vertices)
    assert result.startswith("LINESTRINGZM(")
    assert result.endswith(")")
    assert "-0.1278 51.5074 35000.0 1609275898.0" in result
    assert "-0.5 52.0 36000.0 1609276000.0" in result
    # Two points separated by a comma
    assert "," in result


def test_linestring_zm_single_vertex() -> None:
    vertices = [(1.0, 2.0, 3.0, 4.0)]
    result = linestring_zm(vertices)
    assert result == "LINESTRINGZM(1.0 2.0 3.0 4.0)"


def test_linestring_zm_three_vertices() -> None:
    vertices = [
        (0.0, 0.0, 0.0, 0.0),
        (1.0, 1.0, 1000.0, 100.0),
        (2.0, 2.0, 2000.0, 200.0),
    ]
    result = linestring_zm(vertices)
    assert result == "LINESTRINGZM(0.0 0.0 0.0 0.0, 1.0 1.0 1000.0 100.0, 2.0 2.0 2000.0 200.0)"
