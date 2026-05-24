"""Unit tests for adsb_server.terrain.backfill_agl."""

from __future__ import annotations

from adsb_server.terrain.backfill_agl import _reconstruct_vertex_sequences


def test_reconstruct_single_sequence() -> None:
    """Single sequence: all points have seq_n=1."""
    path_points = [
        [1.0, 10.0, 20.0, 5000.0, 1000.0],
        [1.0, 10.1, 20.0, 5100.0, 1060.0],
    ]
    seqs = _reconstruct_vertex_sequences(path_points)
    assert len(seqs) == 1
    assert seqs[0] == [(10.0, 20.0, 5000.0, 1000.0), (10.1, 20.0, 5100.0, 1060.0)]


def test_reconstruct_multiple_sequences() -> None:
    """Multiple sub-sequences: grouped by seq_n."""
    path_points = [
        [1.0, 10.0, 20.0, 5000.0, 1000.0],
        [1.0, 10.1, 20.0, 5100.0, 1060.0],
        [2.0, 20.0, 30.0, 35000.0, 3600.0],
        [2.0, 20.5, 30.0, 35000.0, 3660.0],
        [2.0, 21.0, 30.0, 35000.0, 3720.0],
    ]
    seqs = _reconstruct_vertex_sequences(path_points)
    assert len(seqs) == 2
    assert len(seqs[0]) == 2
    assert len(seqs[1]) == 3
    assert seqs[1][0] == (20.0, 30.0, 35000.0, 3600.0)


def test_reconstruct_empty() -> None:
    assert _reconstruct_vertex_sequences([]) == []


def test_reconstruct_preserves_order() -> None:
    """Points within each sub-sequence preserve the order from the DB query."""
    path_points = [
        [1.0, 1.0, 1.0, 100.0, 0.0],
        [1.0, 2.0, 1.0, 200.0, 10.0],
        [1.0, 3.0, 1.0, 300.0, 20.0],
    ]
    seqs = _reconstruct_vertex_sequences(path_points)
    assert len(seqs) == 1
    lons = [p[0] for p in seqs[0]]
    assert lons == [1.0, 2.0, 3.0]
