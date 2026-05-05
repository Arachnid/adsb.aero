"""Tests for CLI argument parsing (no DB required)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from adsb_server.ingestion.cli import _parse_args, _parse_bbox


class TestParseBbox:
    def test_valid_bbox(self) -> None:
        result = _parse_bbox("-10,49,2,61")
        assert result == (-10.0, 49.0, 2.0, 61.0)

    def test_valid_bbox_floats(self) -> None:
        result = _parse_bbox("-10.5,49.5,2.5,61.5")
        assert result == (-10.5, 49.5, 2.5, 61.5)

    def test_wrong_number_of_parts(self) -> None:
        import argparse

        with pytest.raises(argparse.ArgumentTypeError):
            _parse_bbox("1,2,3")

    def test_non_numeric_parts(self) -> None:
        import argparse

        with pytest.raises(argparse.ArgumentTypeError):
            _parse_bbox("a,b,c,d")


class TestParseArgs:
    def test_minimal_args(self, tmp_path: Path) -> None:
        """Minimal invocation: just the tarball path."""
        tar = tmp_path / "data.tar.gz"
        tar.touch()
        args = _parse_args([str(tar)])
        assert args.tarball_path == tar
        assert args.batch_date == date.today()
        assert args.bbox is None
        assert args.workers == 1

    def test_with_batch_date(self, tmp_path: Path) -> None:
        tar = tmp_path / "data.tar.gz"
        tar.touch()
        args = _parse_args([str(tar), "--batch-date", "2025-05-18"])
        assert args.batch_date == date(2025, 5, 18)

    def test_with_bbox(self, tmp_path: Path) -> None:
        tar = tmp_path / "data.tar.gz"
        tar.touch()
        # Use --bbox=VALUE to avoid argparse treating -10,... as a flag
        args = _parse_args([str(tar), "--bbox=-10,49,2,61"])
        assert args.bbox == (-10.0, 49.0, 2.0, 61.0)

    def test_with_workers(self, tmp_path: Path) -> None:
        tar = tmp_path / "data.tar.gz"
        tar.touch()
        args = _parse_args([str(tar), "--workers", "4"])
        assert args.workers == 4
