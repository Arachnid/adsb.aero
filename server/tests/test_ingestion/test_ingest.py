"""Tests for ingest.py argument parsing (no DB required)."""

from __future__ import annotations

from datetime import date

import pytest

from adsb_server.ingestion.ingest import _date_range, _parse_args


class TestDateRange:
    def test_single_day(self) -> None:
        assert _date_range(date(2026, 1, 1), date(2026, 1, 1)) == [date(2026, 1, 1)]

    def test_multi_day(self) -> None:
        result = _date_range(date(2026, 1, 1), date(2026, 1, 3))
        assert result == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]

    def test_empty_when_start_after_end(self) -> None:
        assert _date_range(date(2026, 1, 3), date(2026, 1, 1)) == []


class TestParseArgs:
    def test_no_args_is_discovery_mode(self) -> None:
        args = _parse_args([])
        assert args.dates is None
        assert args.from_date is None
        assert args.to_date is None

    def test_dates_flag(self) -> None:
        args = _parse_args(["--dates", "2026-04-28", "2026-04-29"])
        assert args.dates == [date(2026, 4, 28), date(2026, 4, 29)]

    def test_from_only(self) -> None:
        args = _parse_args(["--from", "2026-01-01"])
        assert args.from_date == date(2026, 1, 1)
        assert args.to_date is None

    def test_from_and_to(self) -> None:
        args = _parse_args(["--from", "2026-01-01", "--to", "2026-01-31"])
        assert args.from_date == date(2026, 1, 1)
        assert args.to_date == date(2026, 1, 31)

    def test_to_without_from_raises(self) -> None:
        with pytest.raises(SystemExit):
            _parse_args(["--to", "2026-01-31"])

    def test_dates_and_from_are_mutually_exclusive(self) -> None:
        with pytest.raises(SystemExit):
            _parse_args(["--dates", "2026-01-01", "--from", "2026-01-01"])
