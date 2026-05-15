"""Tests for CLI argument parsing (no DB required)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from adsb_server.ingestion.cli import _parse_args


class TestParseArgs:
    def test_minimal_args(self, tmp_path: Path) -> None:
        """Minimal invocation: just the tarball path."""
        tar = tmp_path / "data.tar.gz"
        tar.touch()
        args = _parse_args([str(tar)])
        assert args.tarball_path == tar
        assert args.batch_date == date.today()
        assert args.workers is None

    def test_with_batch_date(self, tmp_path: Path) -> None:
        tar = tmp_path / "data.tar.gz"
        tar.touch()
        args = _parse_args([str(tar), "--batch-date", "2025-05-18"])
        assert args.batch_date == date(2025, 5, 18)

    def test_with_workers(self, tmp_path: Path) -> None:
        tar = tmp_path / "data.tar.gz"
        tar.touch()
        args = _parse_args([str(tar), "--workers", "4"])
        assert args.workers == 4
