"""Tests for the scheduler: tag parsing, HTTP interactions, and coordination logic."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from adsb_server.ingestion.scheduler import (
    _download_and_process_release,
    _download_asset,
    _get_releases,
    _is_batch_already_processed,
    _tag_to_date,
    check_and_run_new_batches,
    scheduler_loop,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_chunks(*chunks: bytes) -> AsyncGenerator[bytes, None]:
    for chunk in chunks:
        yield chunk


def _make_stream_client(content: bytes = b"data") -> MagicMock:
    """Mock httpx client whose .stream() yields a single chunk."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.aiter_bytes = MagicMock(return_value=_async_chunks(content))

    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=resp)
    stream_cm.__aexit__ = AsyncMock(return_value=False)

    client = MagicMock()
    client.stream = MagicMock(return_value=stream_cm)
    return client


# ---------------------------------------------------------------------------
# _tag_to_date (existing tests retained here)
# ---------------------------------------------------------------------------


class TestTagToDate:
    def test_valid_tag(self) -> None:
        result = _tag_to_date("v2025.05.18-planes-readsb-prod-0")
        assert result == date(2025, 5, 18)

    def test_valid_tag_other_date(self) -> None:
        result = _tag_to_date("v2024.12.31-planes-readsb-prod-0")
        assert result == date(2024, 12, 31)

    def test_invalid_tag_returns_none(self) -> None:
        assert _tag_to_date("not-a-tag") is None

    def test_wrong_format_returns_none(self) -> None:
        assert _tag_to_date("v2025-05-18-planes-readsb-prod-0") is None

    def test_missing_v_prefix_returns_none(self) -> None:
        assert _tag_to_date("2025.05.18-planes-readsb-prod-0") is None

    def test_extra_prod_number(self) -> None:
        result = _tag_to_date("v2025.05.18-planes-readsb-prod-1")
        assert result == date(2025, 5, 18)

    def test_invalid_month_returns_none(self) -> None:
        assert _tag_to_date("v2025.13.01-planes-readsb-prod-0") is None

    def test_invalid_day_returns_none(self) -> None:
        assert _tag_to_date("v2025.01.32-planes-readsb-prod-0") is None


# ---------------------------------------------------------------------------
# _get_releases
# ---------------------------------------------------------------------------


class TestGetReleases:
    async def test_returns_release_list_on_success(self) -> None:
        expected = [{"tag_name": "v2025.04.01-planes-readsb-prod-0"}]
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = expected

        client = MagicMock()
        client.get = AsyncMock(return_value=resp)

        result = await _get_releases(client, 2025)

        assert result == expected
        url = client.get.call_args[0][0]
        assert "2025" in url

    async def test_returns_empty_list_on_http_error(self) -> None:
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.HTTPError("connection refused"))

        result = await _get_releases(client, 2025)

        assert result == []

    async def test_returns_empty_list_on_bad_status(self) -> None:
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403 Forbidden", request=MagicMock(), response=MagicMock()
        )
        client = MagicMock()
        client.get = AsyncMock(return_value=resp)

        result = await _get_releases(client, 2024)

        assert result == []


# ---------------------------------------------------------------------------
# _is_batch_already_processed
# ---------------------------------------------------------------------------


class TestIsBatchAlreadyProcessed:
    async def test_not_in_db_returns_false(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None

        result = await _is_batch_already_processed(conn, date(2025, 4, 1))

        assert result is False

    async def test_status_succeeded_returns_true(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"status": "succeeded"}

        result = await _is_batch_already_processed(conn, date(2025, 4, 1))

        assert result is True

    async def test_status_running_returns_true(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"status": "running"}

        result = await _is_batch_already_processed(conn, date(2025, 4, 1))

        assert result is True

    async def test_status_failed_returns_false(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"status": "failed"}

        result = await _is_batch_already_processed(conn, date(2025, 4, 1))

        assert result is False


# ---------------------------------------------------------------------------
# _download_asset
# ---------------------------------------------------------------------------


class TestDownloadAsset:
    async def test_skips_when_file_exists_with_correct_size(
        self, tmp_path: Path
    ) -> None:
        dest = tmp_path / "archive.tar.aa"
        dest.write_bytes(b"x" * 500)

        client = _make_stream_client()
        await _download_asset(client, "https://example.com/archive.tar.aa", dest, 500)

        client.stream.assert_not_called()

    async def test_downloads_when_file_missing(self, tmp_path: Path) -> None:
        dest = tmp_path / "archive.tar.aa"
        content = b"tarball bytes"
        client = _make_stream_client(content)

        await _download_asset(client, "https://example.com/archive.tar.aa", dest, 999)

        assert dest.exists()
        assert dest.read_bytes() == content

    async def test_redownloads_when_size_mismatch(self, tmp_path: Path) -> None:
        dest = tmp_path / "archive.tar.aa"
        dest.write_bytes(b"x" * 10)  # wrong size
        content = b"correct content"
        client = _make_stream_client(content)

        await _download_asset(client, "https://example.com/archive.tar.aa", dest, 100)

        assert dest.read_bytes() == content

    async def test_creates_parent_directories(self, tmp_path: Path) -> None:
        dest = tmp_path / "2025-04-01" / "archive.tar.aa"
        content = b"data"
        client = _make_stream_client(content)

        await _download_asset(client, "https://example.com/archive.tar.aa", dest, 999)

        assert dest.exists()
        assert dest.read_bytes() == content


# ---------------------------------------------------------------------------
# _download_and_process_release
# ---------------------------------------------------------------------------

_SAMPLE_TAG = "v2025.04.01-planes-readsb-prod-0"
_SAMPLE_DATE = date(2025, 4, 1)
_SAMPLE_RELEASE = {
    "assets": [
        {
            "name": "2025-04-01.tar.aa",
            "browser_download_url": "https://gh.example.com/2025-04-01.tar.aa",
            "size": 1000,
        }
    ]
}


def _release_client(release_data: dict) -> MagicMock:  # type: ignore[type-arg]
    """Mock client whose .get() returns the given release JSON."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = release_data
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    return client


class TestDownloadAndProcessRelease:
    async def test_happy_path_downloads_and_runs_batch(
        self, tmp_path: Path
    ) -> None:
        client = _release_client(_SAMPLE_RELEASE)
        conn = AsyncMock()

        with (
            patch(
                "adsb_server.ingestion.scheduler._download_asset",
                new=AsyncMock(),
            ) as mock_dl,
            patch(
                "adsb_server.ingestion.scheduler.run_batch",
                new=AsyncMock(return_value=3),
            ) as mock_rb,
        ):
            await _download_and_process_release(
                conn, client, 2025, _SAMPLE_TAG, _SAMPLE_DATE, tmp_path
            )

        mock_dl.assert_called_once()
        mock_rb.assert_called_once()

    async def test_release_fetch_failure_returns_early(
        self, tmp_path: Path
    ) -> None:
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.HTTPError("404"))
        conn = AsyncMock()

        with patch(
            "adsb_server.ingestion.scheduler.run_batch", new=AsyncMock()
        ) as mock_rb:
            await _download_and_process_release(
                conn, client, 2025, _SAMPLE_TAG, _SAMPLE_DATE, tmp_path
            )

        mock_rb.assert_not_called()

    async def test_empty_assets_returns_early(self, tmp_path: Path) -> None:
        client = _release_client({"assets": []})
        conn = AsyncMock()

        with patch(
            "adsb_server.ingestion.scheduler.run_batch", new=AsyncMock()
        ) as mock_rb:
            await _download_and_process_release(
                conn, client, 2025, _SAMPLE_TAG, _SAMPLE_DATE, tmp_path
            )

        mock_rb.assert_not_called()

    async def test_asset_download_failure_returns_early(
        self, tmp_path: Path
    ) -> None:
        client = _release_client(_SAMPLE_RELEASE)
        conn = AsyncMock()

        with (
            patch(
                "adsb_server.ingestion.scheduler._download_asset",
                new=AsyncMock(side_effect=OSError("disk full")),
            ) as mock_dl,
            patch(
                "adsb_server.ingestion.scheduler.run_batch", new=AsyncMock()
            ) as mock_rb,
        ):
            await _download_and_process_release(
                conn, client, 2025, _SAMPLE_TAG, _SAMPLE_DATE, tmp_path
            )

        mock_dl.assert_called_once()
        mock_rb.assert_not_called()

    async def test_asset_without_url_is_skipped(self, tmp_path: Path) -> None:
        release_data = {
            "assets": [
                {"name": "bad.tar.aa", "browser_download_url": "", "size": 0},
                {
                    "name": "good.tar.aa",
                    "browser_download_url": "https://gh.example.com/good.tar.aa",
                    "size": 100,
                },
            ]
        }
        client = _release_client(release_data)
        conn = AsyncMock()

        with (
            patch(
                "adsb_server.ingestion.scheduler._download_asset",
                new=AsyncMock(),
            ) as mock_dl,
            patch(
                "adsb_server.ingestion.scheduler.run_batch",
                new=AsyncMock(return_value=1),
            ),
        ):
            await _download_and_process_release(
                conn, client, 2025, _SAMPLE_TAG, _SAMPLE_DATE, tmp_path
            )

        # Only the asset with a real URL should be downloaded
        assert mock_dl.call_count == 1
        call_url = mock_dl.call_args[0][1]
        assert "good.tar.aa" in call_url

    async def test_run_batch_failure_marks_batch_failed(
        self, tmp_path: Path
    ) -> None:
        client = _release_client(_SAMPLE_RELEASE)
        conn = AsyncMock()

        with (
            patch(
                "adsb_server.ingestion.scheduler._download_asset",
                new=AsyncMock(),
            ),
            patch(
                "adsb_server.ingestion.scheduler.run_batch",
                new=AsyncMock(side_effect=RuntimeError("db error")),
            ),
        ):
            await _download_and_process_release(
                conn, client, 2025, _SAMPLE_TAG, _SAMPLE_DATE, tmp_path
            )

        conn.execute.assert_called_once()
        sql: str = conn.execute.call_args[0][0]
        assert "failed" in sql.lower()


# ---------------------------------------------------------------------------
# check_and_run_new_batches
# ---------------------------------------------------------------------------


def _patch_httpx_client() -> MagicMock:
    """Return a mock that can stand in for httpx.AsyncClient used as async CM."""
    mock_client = MagicMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    return mock_cm


class TestCheckAndRunNewBatches:
    async def test_processes_new_unprocessed_release(
        self, tmp_path: Path
    ) -> None:
        releases = [{"tag_name": _SAMPLE_TAG}]

        with (
            patch(
                "adsb_server.ingestion.scheduler.httpx.AsyncClient",
                return_value=_patch_httpx_client(),
            ),
            patch(
                "adsb_server.ingestion.scheduler._get_releases",
                new=AsyncMock(return_value=releases),
            ),
            patch(
                "adsb_server.ingestion.scheduler._is_batch_already_processed",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "adsb_server.ingestion.scheduler._download_and_process_release",
                new=AsyncMock(),
            ) as mock_dapr,
        ):
            await check_and_run_new_batches(AsyncMock(), tmp_path)

        assert mock_dapr.call_count >= 1

    async def test_skips_already_processed_release(
        self, tmp_path: Path
    ) -> None:
        releases = [{"tag_name": _SAMPLE_TAG}]

        with (
            patch(
                "adsb_server.ingestion.scheduler.httpx.AsyncClient",
                return_value=_patch_httpx_client(),
            ),
            patch(
                "adsb_server.ingestion.scheduler._get_releases",
                new=AsyncMock(return_value=releases),
            ),
            patch(
                "adsb_server.ingestion.scheduler._is_batch_already_processed",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "adsb_server.ingestion.scheduler._download_and_process_release",
                new=AsyncMock(),
            ) as mock_dapr,
        ):
            await check_and_run_new_batches(AsyncMock(), tmp_path)

        mock_dapr.assert_not_called()

    async def test_skips_releases_with_invalid_tags(
        self, tmp_path: Path
    ) -> None:
        releases = [{"tag_name": "not-a-valid-tag"}, {"tag_name": ""}]

        with (
            patch(
                "adsb_server.ingestion.scheduler.httpx.AsyncClient",
                return_value=_patch_httpx_client(),
            ),
            patch(
                "adsb_server.ingestion.scheduler._get_releases",
                new=AsyncMock(return_value=releases),
            ),
            patch(
                "adsb_server.ingestion.scheduler._download_and_process_release",
                new=AsyncMock(),
            ) as mock_dapr,
        ):
            await check_and_run_new_batches(AsyncMock(), tmp_path)

        mock_dapr.assert_not_called()

    async def test_checks_two_years(self, tmp_path: Path) -> None:
        get_releases_mock = AsyncMock(return_value=[])

        with (
            patch(
                "adsb_server.ingestion.scheduler.httpx.AsyncClient",
                return_value=_patch_httpx_client(),
            ),
            patch(
                "adsb_server.ingestion.scheduler._get_releases",
                new=get_releases_mock,
            ),
        ):
            await check_and_run_new_batches(AsyncMock(), tmp_path)

        assert get_releases_mock.call_count == 2


# ---------------------------------------------------------------------------
# scheduler_loop
# ---------------------------------------------------------------------------


class TestSchedulerLoop:
    async def test_calls_check_then_sleeps(self, tmp_path: Path) -> None:
        check_count = 0

        async def mock_check(conn: object, cache_dir: object) -> None:
            nonlocal check_count
            check_count += 1

        async def mock_sleep(seconds: float) -> None:
            raise asyncio.CancelledError

        conn = AsyncMock()
        with (
            patch(
                "adsb_server.ingestion.scheduler.check_and_run_new_batches",
                side_effect=mock_check,
            ),
            patch("asyncio.sleep", side_effect=mock_sleep),pytest.raises(asyncio.CancelledError)
        ):
            await scheduler_loop(conn, tmp_path, interval_seconds=60)

        assert check_count == 1

    async def test_continues_after_check_exception(
        self, tmp_path: Path
    ) -> None:
        """Exception from check_and_run_new_batches is caught; loop continues."""
        check_count = 0
        sleep_count = 0

        async def mock_check(conn: object, cache_dir: object) -> None:
            nonlocal check_count
            check_count += 1
            if check_count == 1:
                raise RuntimeError("transient network failure")

        async def mock_sleep(seconds: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                raise asyncio.CancelledError

        conn = AsyncMock()
        with (
            patch(
                "adsb_server.ingestion.scheduler.check_and_run_new_batches",
                side_effect=mock_check,
            ),
            patch("asyncio.sleep", side_effect=mock_sleep),pytest.raises(asyncio.CancelledError)
        ):
            await scheduler_loop(conn, tmp_path, interval_seconds=60)

        assert check_count == 2
        assert sleep_count == 2
