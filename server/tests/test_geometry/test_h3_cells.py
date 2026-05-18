"""Unit tests for H3 cell coverage functions."""

from __future__ import annotations

import h3

from adsb_server.geometry.h3_cells import (
    H3_RES,
    path_h3_cells,
    query_disk,
    query_polygon_cells,
)

# London Heathrow and Paris CDG — ~340 km apart, well over _MAX_SEGMENT_M.
_LHR = (-0.45, 51.47, 35000.0, 0.0)
_CDG = (2.55, 49.0, 35000.0, 1.0)

# Simple 4x2 degree box roughly over southern England.
_SQUARE = [[(-2.0, 50.0), (2.0, 50.0), (2.0, 52.0), (-2.0, 52.0), (-2.0, 50.0)]]


class TestPathH3Cells:
    def test_empty_input_returns_empty(self) -> None:
        assert path_h3_cells([]) == []

    def test_empty_subsequence_skipped(self) -> None:
        assert path_h3_cells([[]]) == []

    def test_single_point_returns_one_cell(self) -> None:
        cells = path_h3_cells([[(0.0, 51.5, 0.0, 0.0)]])
        assert len(cells) == 1
        assert h3.is_valid_cell(cells[0])

    def test_short_segment_returns_cells(self) -> None:
        cells = path_h3_cells([[(0.0, 51.5, 0.0, 0.0), (0.001, 51.501, 0.0, 0.0)]])
        assert len(cells) >= 1

    def test_long_segment_densified_covers_path(self) -> None:
        cells = path_h3_cells([[_LHR, _CDG]])
        # ~340 km at H3 res 4 should produce several cells.
        assert len(cells) >= 5
        lhr_cell = h3.latlng_to_cell(_LHR[1], _LHR[0], H3_RES)
        cdg_cell = h3.latlng_to_cell(_CDG[1], _CDG[0], H3_RES)
        assert lhr_cell in cells
        assert cdg_cell in cells

    def test_multiple_subsequences_combined(self) -> None:
        seq1 = [(0.0, 51.0, 0.0, 0.0), (1.0, 51.0, 0.0, 1.0)]
        seq2 = [(10.0, 51.0, 0.0, 0.0), (11.0, 51.0, 0.0, 1.0)]
        combined = set(path_h3_cells([seq1, seq2]))
        individual = set(path_h3_cells([seq1])) | set(path_h3_cells([seq2]))
        assert combined == individual

    def test_no_duplicate_cells(self) -> None:
        cells = path_h3_cells([[_LHR, _CDG]])
        assert len(cells) == len(set(cells))

    def test_all_cells_valid_res4(self) -> None:
        cells = path_h3_cells([[_LHR, _CDG]])
        for cell in cells:
            assert h3.is_valid_cell(cell)
            assert h3.get_resolution(cell) == H3_RES


class TestQueryDisk:
    def test_returns_nonempty(self) -> None:
        assert len(query_disk(51.5, -0.1, 10_000)) > 0

    def test_center_cell_included(self) -> None:
        lat, lon = 51.5, -0.1
        cells = query_disk(lat, lon, 10_000)
        assert h3.latlng_to_cell(lat, lon, H3_RES) in cells

    def test_larger_radius_more_cells(self) -> None:
        lat, lon = 51.5, -0.1
        assert len(query_disk(lat, lon, 200_000)) > len(query_disk(lat, lon, 10_000))

    def test_zero_radius_still_returns_disk(self) -> None:
        # k is clamped to at least 1, so we always get center + 1 ring (≥ 7 cells).
        assert len(query_disk(51.5, -0.1, 0)) >= 7

    def test_all_cells_valid_res4(self) -> None:
        for cell in query_disk(51.5, -0.1, 50_000):
            assert h3.is_valid_cell(cell)
            assert h3.get_resolution(cell) == H3_RES


class TestQueryPolygonCells:
    def test_returns_nonempty(self) -> None:
        assert len(query_polygon_cells(_SQUARE)) > 0

    def test_interior_cell_covered(self) -> None:
        interior = h3.latlng_to_cell(51.0, 0.0, H3_RES)
        assert interior in query_polygon_cells(_SQUARE)

    def test_boundary_corner_cell_covered(self) -> None:
        corner = h3.latlng_to_cell(50.0, -2.0, H3_RES)
        assert corner in query_polygon_cells(_SQUARE)

    def test_no_duplicates(self) -> None:
        cells = query_polygon_cells(_SQUARE)
        assert len(cells) == len(set(cells))

    def test_all_cells_valid_res4(self) -> None:
        for cell in query_polygon_cells(_SQUARE):
            assert h3.is_valid_cell(cell)
            assert h3.get_resolution(cell) == H3_RES

    def test_thin_polygon_nonempty(self) -> None:
        # 0.1° wide strip running ~440 km north: polygon_to_cells may return nothing,
        # but the boundary-path step should still produce cells.
        thin = [[(0.0, 51.0), (0.1, 51.0), (0.1, 55.0), (0.0, 55.0), (0.0, 51.0)]]
        assert len(query_polygon_cells(thin)) > 0

    def test_polygon_with_hole(self) -> None:
        outer = [(-3.0, 49.0), (3.0, 49.0), (3.0, 53.0), (-3.0, 53.0), (-3.0, 49.0)]
        hole = [(-1.0, 50.5), (1.0, 50.5), (1.0, 51.5), (-1.0, 51.5), (-1.0, 50.5)]
        assert len(query_polygon_cells([outer, hole])) > 0

    def test_open_ring_closed_automatically(self) -> None:
        # Ring without repeated first/last vertex should be handled identically
        # to the closed version.
        closed = [[(-2.0, 50.0), (2.0, 50.0), (2.0, 52.0), (-2.0, 52.0), (-2.0, 50.0)]]
        open_ = [[(-2.0, 50.0), (2.0, 50.0), (2.0, 52.0), (-2.0, 52.0)]]
        assert set(query_polygon_cells(open_)) == set(query_polygon_cells(closed))
