"""Tests for MobilityDB temporal type construction helpers."""

from __future__ import annotations

from adsb_server.geometry.wkt import tgeompoint_seq, tint_seq, ttext_seq


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


def test_ttext_seq_empty_returns_none() -> None:
    assert ttext_seq([]) is None


def test_ttext_seq_single_run() -> None:
    result = ttext_seq([(1609275898.0, "7700")])
    assert result is not None
    assert result.startswith("[")
    assert result.endswith("]")
    assert '"7700"@' in result


def test_ttext_seq_multiple_runs() -> None:
    result = ttext_seq([(1609275898.0, "7700"), (1609279498.0, "2000")])
    assert result is not None
    assert '"7700"@' in result
    assert '"2000"@' in result
    assert ", " in result


def test_ttext_seq_timestamp_format() -> None:
    result = ttext_seq([(0.0, "1234")])
    assert result is not None
    assert '"1234"@1970-01-01T00:00:00' in result
    assert "+00" in result


def test_ttext_seq_preserves_order() -> None:
    runs = [(100.0, "2000"), (200.0, "7700"), (300.0, "1200")]
    result = ttext_seq(runs)
    assert result is not None
    idx_2000 = result.index('"2000"@')
    idx_7700 = result.index('"7700"@')
    idx_1200 = result.index('"1200"@')
    assert idx_2000 < idx_7700 < idx_1200


from adsb_server.geometry.wkt import tfloat_stepwise_seq  # noqa: E402


def test_tfloat_stepwise_seq_empty_returns_none() -> None:
    assert tfloat_stepwise_seq([], []) is None


def test_tfloat_stepwise_seq_single_value() -> None:
    result = tfloat_stepwise_seq([12.5], [1609275898.0])
    assert result is not None
    assert result.startswith("Interp=Step;[")
    assert result.endswith("]")
    assert "12.5000@" in result


def test_tfloat_stepwise_seq_multiple_values() -> None:
    result = tfloat_stepwise_seq([12.5, -3.0, 27.1], [100.0, 200.0, 300.0])
    assert result is not None
    assert result.startswith("Interp=Step;[")
    assert result.count("@") == 3
    assert "12.5000@" in result
    assert "-3.0000@" in result
    assert "27.1000@" in result


def test_tfloat_stepwise_seq_timestamp_format() -> None:
    result = tfloat_stepwise_seq([0.0], [0.0])
    assert result is not None
    assert "0.0000@1970-01-01T00:00:00" in result
    assert "+00" in result


def test_tfloat_stepwise_seq_preserves_order() -> None:
    result = tfloat_stepwise_seq([1.0, 2.0, 3.0], [100.0, 200.0, 300.0])
    assert result is not None
    assert result.index("1.0000@") < result.index("2.0000@") < result.index("3.0000@")
