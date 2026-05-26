"""Tests for the scheduler: tag parsing, HTTP interactions, and coordination logic."""

from __future__ import annotations

from collections.abc import AsyncGenerator  # noqa: TC003
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from adsb_server.ingestion.scheduler import (
    _download_asset,
    _fetch_release_assets,
    _get_latest_succeeded_date,
    _get_releases,
    _is_batch_already_processed,
    _process_downloaded_release,
    _tag_to_date,
    check_and_run_new_batches,
    reimport_specific_dates,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_chunks(*chunks: bytes) -> AsyncGenerator[bytes]:
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


# Fake return value for _prefetch_release in scheduler loop tests.
_FAKE_PREFETCH: tuple[str, Path, None] = ("https://api.github.com/fake", Path("/fake"), None)


def _dpdr_collector(
    recorded: list[date],
    *,
    fail_on: date | None = None,
) -> object:
    """Return a side_effect for _process_downloaded_release that records batch_dates."""

    async def _impl(
        conn: object,
        batch_date: date,
        dest_dir: object,
        mslp: object,
        release_api_url: object,
        keep_traces: bool = False,
        workers: int | None = None,
    ) -> bool:
        recorded.append(batch_date)
        return fail_on is None or batch_date != fail_on

    return _impl


# ---------------------------------------------------------------------------
# _tag_to_date
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

    async def test_passes_page_number_to_api(self) -> None:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = []
        client = MagicMock()
        client.get = AsyncMock(return_value=resp)

        await _get_releases(client, 2025, page=3)

        params: dict[str, object] = client.get.call_args[1]["params"]
        assert params["page"] == 3

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

    async def test_status_running_returns_false(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"status": "running"}

        result = await _is_batch_already_processed(conn, date(2025, 4, 1))

        assert result is False

    async def test_status_failed_returns_false(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"status": "failed"}

        result = await _is_batch_already_processed(conn, date(2025, 4, 1))

        assert result is False

    async def test_status_errored_returns_false(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"status": "errored"}

        result = await _is_batch_already_processed(conn, date(2025, 4, 1))

        assert result is False


# ---------------------------------------------------------------------------
# _download_asset
# ---------------------------------------------------------------------------


_UPDATED_AT = "2026-04-01T12:00:00Z"


def _write_with_etag(dest: Path, content: bytes, updated_at: str = _UPDATED_AT) -> None:
    """Write content to dest and create the matching .etag sidecar."""
    dest.write_bytes(content)
    etag_path = Path(str(dest) + ".etag")
    etag_path.write_text(updated_at)


class TestDownloadAsset:
    async def test_skips_when_file_and_etag_match(self, tmp_path: Path) -> None:
        """Skip download when file, size, and etag all match."""
        dest = tmp_path / "archive.tar.aa"
        content = b"x" * 500
        _write_with_etag(dest, content)

        client = _make_stream_client()
        await _download_asset(client, "https://example.com/archive.tar.aa", dest, 500, _UPDATED_AT)

        client.stream.assert_not_called()
        assert dest.read_bytes() == content

    async def test_redownloads_when_etag_missing(self, tmp_path: Path) -> None:
        """Redownload when file exists with correct size but no etag sidecar."""
        dest = tmp_path / "archive.tar.aa"
        dest.write_bytes(b"x" * 500)  # no etag sidecar
        content = b"fresh content"
        client = _make_stream_client(content)

        await _download_asset(client, "https://example.com/archive.tar.aa", dest, 500, _UPDATED_AT)

        client.stream.assert_called_once()
        assert dest.read_bytes() == content

    async def test_redownloads_when_updated_at_differs(self, tmp_path: Path) -> None:
        """Redownload when etag sidecar records a different updated_at than GitHub."""
        dest = tmp_path / "archive.tar.aa"
        _write_with_etag(dest, b"x" * 500, updated_at="2026-03-01T00:00:00Z")

        content = b"updated content"
        client = _make_stream_client(content)

        await _download_asset(client, "https://example.com/archive.tar.aa", dest, 500, _UPDATED_AT)

        client.stream.assert_called_once()
        assert dest.read_bytes() == content

    async def test_creates_etag_after_download(self, tmp_path: Path) -> None:
        """A .etag sidecar containing the updated_at string is written after download."""
        dest = tmp_path / "archive.tar.aa"
        content = b"tarball bytes"
        client = _make_stream_client(content)

        await _download_asset(client, "https://example.com/archive.tar.aa", dest, 999, _UPDATED_AT)

        etag_path = Path(str(dest) + ".etag")
        assert etag_path.exists()
        assert etag_path.read_text().strip() == _UPDATED_AT

    async def test_downloads_when_file_missing(self, tmp_path: Path) -> None:
        dest = tmp_path / "archive.tar.aa"
        content = b"tarball bytes"
        client = _make_stream_client(content)

        await _download_asset(client, "https://example.com/archive.tar.aa", dest, 999, _UPDATED_AT)

        assert dest.exists()
        assert dest.read_bytes() == content

    async def test_redownloads_when_size_mismatch(self, tmp_path: Path) -> None:
        dest = tmp_path / "archive.tar.aa"
        _write_with_etag(dest, b"x" * 10)  # correct etag but wrong size vs expected
        content = b"correct content"
        client = _make_stream_client(content)

        await _download_asset(client, "https://example.com/archive.tar.aa", dest, 100, _UPDATED_AT)

        assert dest.read_bytes() == content

    async def test_creates_parent_directories(self, tmp_path: Path) -> None:
        dest = tmp_path / "2025-04-01" / "archive.tar.aa"
        content = b"data"
        client = _make_stream_client(content)

        await _download_asset(client, "https://example.com/archive.tar.aa", dest, 999, _UPDATED_AT)

        assert dest.exists()
        assert dest.read_bytes() == content


# ---------------------------------------------------------------------------
# _fetch_release_assets
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


class TestFetchReleaseAssets:
    async def test_returns_url_and_dest_dir_on_success(self, tmp_path: Path) -> None:
        client = _release_client(_SAMPLE_RELEASE)
        with patch("adsb_server.ingestion.scheduler._download_asset", new=AsyncMock()):
            result = await _fetch_release_assets(client, 2025, _SAMPLE_TAG, _SAMPLE_DATE, tmp_path)
        assert result is not None
        url, dest_dir = result
        assert _SAMPLE_TAG in url
        assert dest_dir == tmp_path / "2025-04-01"

    async def test_returns_url_with_none_dest_for_empty_assets(self, tmp_path: Path) -> None:
        client = _release_client({"assets": []})
        result = await _fetch_release_assets(client, 2025, _SAMPLE_TAG, _SAMPLE_DATE, tmp_path)
        assert result is not None
        _url, dest_dir = result
        assert dest_dir is None

    async def test_returns_none_on_http_error(self, tmp_path: Path) -> None:
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.HTTPError("404"))
        result = await _fetch_release_assets(client, 2025, _SAMPLE_TAG, _SAMPLE_DATE, tmp_path)
        assert result is None

    async def test_returns_none_on_download_failure(self, tmp_path: Path) -> None:
        client = _release_client(_SAMPLE_RELEASE)
        with patch(
            "adsb_server.ingestion.scheduler._download_asset",
            new=AsyncMock(side_effect=OSError("disk full")),
        ):
            result = await _fetch_release_assets(client, 2025, _SAMPLE_TAG, _SAMPLE_DATE, tmp_path)
        assert result is None

    async def test_skips_asset_without_url(self, tmp_path: Path) -> None:
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
        with patch("adsb_server.ingestion.scheduler._download_asset", new=AsyncMock()) as mock_dl:
            await _fetch_release_assets(client, 2025, _SAMPLE_TAG, _SAMPLE_DATE, tmp_path)
        assert mock_dl.call_count == 1
        assert "good.tar.aa" in mock_dl.call_args[0][1]


# ---------------------------------------------------------------------------
# _process_downloaded_release
# ---------------------------------------------------------------------------


class TestProcessDownloadedRelease:
    async def test_happy_path_runs_batch_and_returns_true(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / "2025-04-01"
        dest_dir.mkdir()
        conn = AsyncMock()
        with patch(
            "adsb_server.ingestion.scheduler.run_batch", new=AsyncMock(return_value=3)
        ) as mock_rb:
            result = await _process_downloaded_release(
                conn, _SAMPLE_DATE, dest_dir, None, "https://example.com/release"
            )
        assert result is True
        mock_rb.assert_called_once()

    async def test_deletes_dest_dir_on_success(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / "2025-04-01"
        dest_dir.mkdir()
        conn = AsyncMock()
        with patch("adsb_server.ingestion.scheduler.run_batch", new=AsyncMock(return_value=3)):
            await _process_downloaded_release(
                conn, _SAMPLE_DATE, dest_dir, None, "https://example.com/release"
            )
        assert not dest_dir.exists()

    async def test_keep_traces_preserves_dest_dir(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / "2025-04-01"
        dest_dir.mkdir()
        conn = AsyncMock()
        with patch("adsb_server.ingestion.scheduler.run_batch", new=AsyncMock(return_value=3)):
            await _process_downloaded_release(
                conn,
                _SAMPLE_DATE,
                dest_dir,
                None,
                "https://example.com/release",
                keep_traces=True,
            )
        assert dest_dir.exists()

    async def test_keeps_dest_dir_on_run_batch_failure(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / "2025-04-01"
        dest_dir.mkdir()
        conn = AsyncMock()
        with patch(
            "adsb_server.ingestion.scheduler.run_batch",
            new=AsyncMock(side_effect=RuntimeError("db error")),
        ):
            await _process_downloaded_release(
                conn, _SAMPLE_DATE, dest_dir, None, "https://example.com/release"
            )
        assert dest_dir.exists()

    async def test_run_batch_failure_marks_errored(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / "2025-04-01"
        dest_dir.mkdir()
        conn = AsyncMock()
        with patch(
            "adsb_server.ingestion.scheduler.run_batch",
            new=AsyncMock(side_effect=RuntimeError("db error")),
        ):
            await _process_downloaded_release(
                conn, _SAMPLE_DATE, dest_dir, None, "https://example.com/release"
            )
        conn.execute.assert_called_once()
        sql: str = conn.execute.call_args[0][0]
        assert "errored" in sql.lower()

    async def test_run_batch_failure_stores_release_url(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / "2025-04-01"
        dest_dir.mkdir()
        release_url = "https://api.github.com/repos/adsblol/releases/tags/v2025.04.01"
        conn = AsyncMock()
        with patch(
            "adsb_server.ingestion.scheduler.run_batch",
            new=AsyncMock(side_effect=RuntimeError("err")),
        ):
            await _process_downloaded_release(conn, _SAMPLE_DATE, dest_dir, None, release_url)
        stored_url: str = conn.execute.call_args[0][3]
        assert stored_url == release_url

    async def test_passes_mslp_to_run_batch(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / "2025-04-01"
        dest_dir.mkdir()
        conn = AsyncMock()
        fake_mslp = MagicMock()
        with patch(
            "adsb_server.ingestion.scheduler.run_batch", new=AsyncMock(return_value=0)
        ) as mock_rb:
            await _process_downloaded_release(
                conn, _SAMPLE_DATE, dest_dir, fake_mslp, "https://example.com"
            )
        assert mock_rb.call_args[1].get("mslp") is fake_mslp


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
    async def test_processes_new_unprocessed_release(self, tmp_path: Path) -> None:
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
                "adsb_server.ingestion.scheduler._get_latest_succeeded_date",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "adsb_server.ingestion.scheduler.get_settings",
                return_value=MagicMock(herbie_cache_dir=tmp_path),
            ),
            patch(
                "adsb_server.ingestion.scheduler._prefetch_release",
                new=AsyncMock(return_value=_FAKE_PREFETCH),
            ),
            patch(
                "adsb_server.ingestion.scheduler._process_downloaded_release",
                new=AsyncMock(return_value=True),
            ) as mock_pdr,
        ):
            await check_and_run_new_batches(AsyncMock(), tmp_path)

        assert mock_pdr.call_count >= 1

    async def test_skips_already_processed_release(self, tmp_path: Path) -> None:
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
                "adsb_server.ingestion.scheduler._get_latest_succeeded_date",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "adsb_server.ingestion.scheduler.get_settings",
                return_value=MagicMock(herbie_cache_dir=tmp_path),
            ),
            patch(
                "adsb_server.ingestion.scheduler._process_downloaded_release",
                new=AsyncMock(return_value=True),
            ) as mock_pdr,
        ):
            await check_and_run_new_batches(AsyncMock(), tmp_path)

        mock_pdr.assert_not_called()

    async def test_skips_releases_with_invalid_tags(self, tmp_path: Path) -> None:
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
                "adsb_server.ingestion.scheduler._get_latest_succeeded_date",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "adsb_server.ingestion.scheduler.get_settings",
                return_value=MagicMock(herbie_cache_dir=tmp_path),
            ),
            patch(
                "adsb_server.ingestion.scheduler._process_downloaded_release",
                new=AsyncMock(return_value=True),
            ) as mock_pdr,
        ):
            await check_and_run_new_batches(AsyncMock(), tmp_path)

        mock_pdr.assert_not_called()

    async def test_fetches_second_page_when_first_page_is_full(self, tmp_path: Path) -> None:
        """A release that only appears on page 2 is discovered and processed."""
        page1 = [{"tag_name": "not-valid"} for _ in range(100)]  # full page, no matches
        page2 = [{"tag_name": _SAMPLE_TAG}]  # valid unprocessed release

        pages_fetched: list[int] = []

        async def mock_get_releases(
            client: object, year: int, page: int = 1
        ) -> list[dict[str, object]]:
            pages_fetched.append(page)
            return {1: page1, 2: page2}.get(page, [])  # type: ignore[return-value]

        with (
            patch(
                "adsb_server.ingestion.scheduler.httpx.AsyncClient",
                return_value=_patch_httpx_client(),
            ),
            patch(
                "adsb_server.ingestion.scheduler._get_releases",
                side_effect=mock_get_releases,
            ),
            patch(
                "adsb_server.ingestion.scheduler._is_batch_already_processed",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "adsb_server.ingestion.scheduler._get_latest_succeeded_date",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "adsb_server.ingestion.scheduler.get_settings",
                return_value=MagicMock(herbie_cache_dir=tmp_path),
            ),
            patch(
                "adsb_server.ingestion.scheduler._prefetch_release",
                new=AsyncMock(return_value=_FAKE_PREFETCH),
            ),
            patch(
                "adsb_server.ingestion.scheduler._process_downloaded_release",
                new=AsyncMock(return_value=True),
            ) as mock_pdr,
        ):
            await check_and_run_new_batches(AsyncMock(), tmp_path)

        assert any(p == 2 for p in pages_fetched), "page 2 was never fetched"
        assert mock_pdr.call_count >= 1, "release on page 2 was not processed"

    async def test_stops_fetching_pages_when_page_is_not_full(self, tmp_path: Path) -> None:
        """Page 3 is never fetched when page 2 returns fewer entries than the page size."""
        page1 = [{"tag_name": "not-valid"} for _ in range(100)]
        page2 = [{"tag_name": _SAMPLE_TAG}]  # valid but already processed

        pages_fetched: list[int] = []

        async def mock_get_releases(
            client: object, year: int, page: int = 1
        ) -> list[dict[str, object]]:
            pages_fetched.append(page)
            return {1: page1, 2: page2}.get(  # type: ignore[return-value]
                page, [{"tag_name": "v2025.03.31-planes-readsb-prod-0"}]
            )

        with (
            patch(
                "adsb_server.ingestion.scheduler.httpx.AsyncClient",
                return_value=_patch_httpx_client(),
            ),
            patch(
                "adsb_server.ingestion.scheduler._get_releases",
                side_effect=mock_get_releases,
            ),
            patch(
                "adsb_server.ingestion.scheduler._is_batch_already_processed",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "adsb_server.ingestion.scheduler._get_latest_succeeded_date",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "adsb_server.ingestion.scheduler.get_settings",
                return_value=MagicMock(herbie_cache_dir=tmp_path),
            ),
            patch(
                "adsb_server.ingestion.scheduler._process_downloaded_release",
                new=AsyncMock(return_value=True),
            ) as mock_pdr,
        ):
            await check_and_run_new_batches(AsyncMock(), tmp_path)

        assert any(p == 2 for p in pages_fetched), "page 2 was never fetched"
        assert not any(p >= 3 for p in pages_fetched), "page 3 should not have been fetched"
        mock_pdr.assert_not_called()

    async def test_processes_in_ascending_date_order(self, tmp_path: Path) -> None:
        """Unprocessed releases are ingested oldest-first regardless of API sort order."""
        # GitHub returns newest-first
        releases: list[dict[str, object]] = [
            {"tag_name": "v2025.04.03-planes-readsb-prod-0"},
            {"tag_name": "v2025.04.02-planes-readsb-prod-0"},
            {"tag_name": "v2025.04.01-planes-readsb-prod-0"},
        ]

        processed_dates: list[date] = []

        async def mock_get_releases(
            client: object, year: int, page: int = 1
        ) -> list[dict[str, object]]:
            return releases if year == 2025 and page == 1 else []

        with (
            patch(
                "adsb_server.ingestion.scheduler.httpx.AsyncClient",
                return_value=_patch_httpx_client(),
            ),
            patch(
                "adsb_server.ingestion.scheduler._get_releases",
                side_effect=mock_get_releases,
            ),
            patch(
                "adsb_server.ingestion.scheduler._is_batch_already_processed",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "adsb_server.ingestion.scheduler._get_latest_succeeded_date",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "adsb_server.ingestion.scheduler.get_settings",
                return_value=MagicMock(herbie_cache_dir=tmp_path),
            ),
            patch(
                "adsb_server.ingestion.scheduler._prefetch_release",
                new=AsyncMock(return_value=_FAKE_PREFETCH),
            ),
            patch(
                "adsb_server.ingestion.scheduler._process_downloaded_release",
                side_effect=_dpdr_collector(processed_dates),
            ),
        ):
            await check_and_run_new_batches(AsyncMock(), tmp_path)

        assert len(processed_dates) == 3
        assert processed_dates == sorted(processed_dates)

    async def test_continues_after_batch_failure(self, tmp_path: Path) -> None:
        """If a batch errors, subsequent days are still processed."""
        releases: list[dict[str, object]] = [
            {"tag_name": "v2025.04.03-planes-readsb-prod-0"},
            {"tag_name": "v2025.04.02-planes-readsb-prod-0"},
            {"tag_name": "v2025.04.01-planes-readsb-prod-0"},
        ]
        processed_dates: list[date] = []

        async def mock_get_releases(
            client: object, year: int, page: int = 1
        ) -> list[dict[str, object]]:
            return releases if year == 2025 and page == 1 else []

        with (
            patch(
                "adsb_server.ingestion.scheduler.httpx.AsyncClient",
                return_value=_patch_httpx_client(),
            ),
            patch(
                "adsb_server.ingestion.scheduler._get_releases",
                side_effect=mock_get_releases,
            ),
            patch(
                "adsb_server.ingestion.scheduler._is_batch_already_processed",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "adsb_server.ingestion.scheduler._get_latest_succeeded_date",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "adsb_server.ingestion.scheduler.get_settings",
                return_value=MagicMock(herbie_cache_dir=tmp_path),
            ),
            patch(
                "adsb_server.ingestion.scheduler._prefetch_release",
                new=AsyncMock(return_value=_FAKE_PREFETCH),
            ),
            patch(
                "adsb_server.ingestion.scheduler._process_downloaded_release",
                side_effect=_dpdr_collector(processed_dates, fail_on=date(2025, 4, 2)),
            ),
        ):
            await check_and_run_new_batches(AsyncMock(), tmp_path)

        # All three dates attempted; Apr 2 fails but Apr 3 is still processed.
        assert date(2025, 4, 1) in processed_dates
        assert date(2025, 4, 2) in processed_dates
        assert date(2025, 4, 3) in processed_dates

    async def test_lookback_days_skips_old_batches(self, tmp_path: Path) -> None:
        """Releases older than lookback_days are not processed."""
        releases = [{"tag_name": "v2025.04.01-planes-readsb-prod-0"}]

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
                "adsb_server.ingestion.scheduler._get_latest_succeeded_date",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "adsb_server.ingestion.scheduler.get_settings",
                return_value=MagicMock(herbie_cache_dir=tmp_path),
            ),
            patch(
                "adsb_server.ingestion.scheduler._process_downloaded_release",
                new=AsyncMock(return_value=True),
            ) as mock_pdr,
            patch("adsb_server.ingestion.scheduler.date") as mock_date,
        ):
            # today=Apr 10, lookback=7 → cutoff=Apr 3 → Apr 1 is before cutoff
            mock_date.today.return_value = date(2025, 4, 10)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            await check_and_run_new_batches(AsyncMock(), tmp_path, lookback_days=7)

        mock_pdr.assert_not_called()

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
            patch(
                "adsb_server.ingestion.scheduler._get_latest_succeeded_date",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "adsb_server.ingestion.scheduler.get_settings",
                return_value=MagicMock(herbie_cache_dir=tmp_path),
            ),
        ):
            await check_and_run_new_batches(AsyncMock(), tmp_path)

        assert get_releases_mock.call_count == 2

    async def test_skips_previous_year_when_scan_boundary_reached(self, tmp_path: Path) -> None:
        """When the scan boundary (latest success) is reached in year N, year N-1 is not queried."""
        releases_by_year: dict[int, list[dict[str, object]]] = {
            2025: [{"tag_name": "v2025.04.02-planes-readsb-prod-0"}],
            2024: [{"tag_name": "v2024.12.31-planes-readsb-prod-0"}],
        }

        get_releases_mock = AsyncMock(
            side_effect=lambda client, year, page=1: (
                releases_by_year.get(year, []) if page == 1 else []
            )
        )

        with (
            patch(
                "adsb_server.ingestion.scheduler.httpx.AsyncClient",
                return_value=_patch_httpx_client(),
            ),
            patch(
                "adsb_server.ingestion.scheduler._get_releases",
                new=get_releases_mock,
            ),
            patch(
                # scan_from = Apr 2; scanner hits batch_date <= scan_from and stops
                "adsb_server.ingestion.scheduler._get_latest_succeeded_date",
                new=AsyncMock(return_value=date(2025, 4, 2)),
            ),
            patch(
                "adsb_server.ingestion.scheduler.get_settings",
                return_value=MagicMock(herbie_cache_dir=tmp_path),
            ),
            patch(
                "adsb_server.ingestion.scheduler._process_downloaded_release",
                new=AsyncMock(return_value=True),
            ),
        ):
            await check_and_run_new_batches(AsyncMock(), tmp_path)

        # Only year 2025 should have been queried; 2024 never reached
        queried_years = [call.args[1] for call in get_releases_mock.call_args_list]
        assert 2025 in queried_years
        assert 2024 not in queried_years

    async def test_errored_batch_retried_when_no_later_success(self, tmp_path: Path) -> None:
        """Errored batches after the latest success are retried; older ones are not.

        Scan order (newest-first): Apr 3 (not processed), Apr 2 (errored/not succeeded),
        Apr 1 (scan boundary = latest_success, stops scan). Expected: Apr 2 and Apr 3 processed.
        """
        releases: list[dict[str, object]] = [
            {"tag_name": "v2025.04.03-planes-readsb-prod-0"},  # not yet processed
            {"tag_name": "v2025.04.02-planes-readsb-prod-0"},  # errored (status != succeeded)
            {"tag_name": "v2025.04.01-planes-readsb-prod-0"},  # scan boundary
        ]
        processed_dates: list[date] = []

        async def mock_get_releases(
            client: object, year: int, page: int = 1
        ) -> list[dict[str, object]]:
            return releases if year == 2025 and page == 1 else []

        with (
            patch(
                "adsb_server.ingestion.scheduler.httpx.AsyncClient",
                return_value=_patch_httpx_client(),
            ),
            patch(
                "adsb_server.ingestion.scheduler._get_releases",
                side_effect=mock_get_releases,
            ),
            patch(
                "adsb_server.ingestion.scheduler._is_batch_already_processed",
                new=AsyncMock(return_value=False),
            ),
            patch(
                # Apr 1 is the latest success → scan_from = Apr 1 → stop there
                "adsb_server.ingestion.scheduler._get_latest_succeeded_date",
                new=AsyncMock(return_value=date(2025, 4, 1)),
            ),
            patch(
                "adsb_server.ingestion.scheduler.get_settings",
                return_value=MagicMock(herbie_cache_dir=tmp_path),
            ),
            patch(
                "adsb_server.ingestion.scheduler._prefetch_release",
                new=AsyncMock(return_value=_FAKE_PREFETCH),
            ),
            patch(
                "adsb_server.ingestion.scheduler._process_downloaded_release",
                side_effect=_dpdr_collector(processed_dates),
            ),
        ):
            await check_and_run_new_batches(AsyncMock(), tmp_path)

        assert date(2025, 4, 2) in processed_dates, "errored batch after latest success not retried"
        assert date(2025, 4, 3) in processed_dates, "unprocessed batch after latest success skipped"
        assert date(2025, 4, 1) not in processed_dates, (
            "scan-boundary batch should not be processed"
        )
        assert processed_dates == sorted(processed_dates), "batches processed out of order"


# ---------------------------------------------------------------------------
# reimport_specific_dates
# ---------------------------------------------------------------------------


class TestReimportSpecificDates:
    async def test_processes_each_date_in_order(self, tmp_path: Path) -> None:
        processed: list[date] = []

        async def mock_fetch(client: object, year: int) -> dict[date, str]:
            dates = [date(2025, 4, 1), date(2025, 4, 2), date(2025, 4, 3)]
            return {d: f"v{d.year}.{d.month:02d}.{d.day:02d}-planes-readsb-prod-0" for d in dates}

        with (
            patch(
                "adsb_server.ingestion.scheduler.httpx.AsyncClient",
                return_value=_patch_httpx_client(),
            ),
            patch(
                "adsb_server.ingestion.scheduler._fetch_releases_by_date",
                side_effect=mock_fetch,
            ),
            patch(
                "adsb_server.ingestion.scheduler.get_settings",
                return_value=MagicMock(herbie_cache_dir=tmp_path),
            ),
            patch(
                "adsb_server.ingestion.scheduler._prefetch_release",
                new=AsyncMock(return_value=_FAKE_PREFETCH),
            ),
            patch(
                "adsb_server.ingestion.scheduler._process_downloaded_release",
                side_effect=_dpdr_collector(processed),
            ),
        ):
            await reimport_specific_dates(
                AsyncMock(),
                [date(2025, 4, 3), date(2025, 4, 1), date(2025, 4, 2)],
                tmp_path,
            )

        assert processed == [date(2025, 4, 1), date(2025, 4, 2), date(2025, 4, 3)]

    async def test_skips_date_with_no_release(self, tmp_path: Path) -> None:
        async def mock_fetch(client: object, year: int) -> dict[date, str]:
            return {date(2025, 4, 1): "v2025.04.01-planes-readsb-prod-0"}

        with (
            patch(
                "adsb_server.ingestion.scheduler.httpx.AsyncClient",
                return_value=_patch_httpx_client(),
            ),
            patch(
                "adsb_server.ingestion.scheduler._fetch_releases_by_date",
                side_effect=mock_fetch,
            ),
            patch(
                "adsb_server.ingestion.scheduler.get_settings",
                return_value=MagicMock(herbie_cache_dir=tmp_path),
            ),
            patch(
                "adsb_server.ingestion.scheduler._prefetch_release",
                new=AsyncMock(return_value=_FAKE_PREFETCH),
            ),
            patch(
                "adsb_server.ingestion.scheduler._process_downloaded_release",
                new=AsyncMock(return_value=True),
            ) as mock_pdr,
        ):
            await reimport_specific_dates(
                AsyncMock(), [date(2025, 4, 1), date(2025, 4, 2)], tmp_path
            )

        assert mock_pdr.call_count == 1
        called_date: date = mock_pdr.call_args[0][1]
        assert called_date == date(2025, 4, 1)


# ---------------------------------------------------------------------------
# check_and_run_new_batches — scan boundary and errored-batch semantics
# ---------------------------------------------------------------------------


class TestCheckAndRunNewBatchesScanBoundary:
    async def test_errored_batch_before_latest_success_not_retried(self, tmp_path: Path) -> None:
        """Errored batches that pre-date the latest success are left alone."""
        # Apr 5 is the latest success (scan_from).  Apr 3 errored but is before Apr 5,
        # so the scan stops at Apr 5 and never reaches Apr 3.
        releases: list[dict[str, object]] = [
            {"tag_name": "v2025.04.06-planes-readsb-prod-0"},  # new, unprocessed
            {"tag_name": "v2025.04.05-planes-readsb-prod-0"},  # scan boundary
            {"tag_name": "v2025.04.04-planes-readsb-prod-0"},
            {"tag_name": "v2025.04.03-planes-readsb-prod-0"},  # errored, before boundary
        ]
        processed_dates: list[date] = []

        async def mock_get_releases(
            client: object, year: int, page: int = 1
        ) -> list[dict[str, object]]:
            return releases if year == 2025 and page == 1 else []

        with (
            patch(
                "adsb_server.ingestion.scheduler.httpx.AsyncClient",
                return_value=_patch_httpx_client(),
            ),
            patch(
                "adsb_server.ingestion.scheduler._get_releases",
                side_effect=mock_get_releases,
            ),
            patch(
                "adsb_server.ingestion.scheduler._is_batch_already_processed",
                new=AsyncMock(return_value=False),
            ),
            patch(
                # Apr 5 is the latest succeeded batch → scan_from = Apr 5
                "adsb_server.ingestion.scheduler._get_latest_succeeded_date",
                new=AsyncMock(return_value=date(2025, 4, 5)),
            ),
            patch(
                "adsb_server.ingestion.scheduler.get_settings",
                return_value=MagicMock(herbie_cache_dir=tmp_path),
            ),
            patch(
                "adsb_server.ingestion.scheduler._prefetch_release",
                new=AsyncMock(return_value=_FAKE_PREFETCH),
            ),
            patch(
                "adsb_server.ingestion.scheduler._process_downloaded_release",
                side_effect=_dpdr_collector(processed_dates),
            ),
        ):
            await check_and_run_new_batches(AsyncMock(), tmp_path)

        assert date(2025, 4, 6) in processed_dates, "unprocessed batch after boundary not queued"
        assert date(2025, 4, 5) not in processed_dates, "scan-boundary batch should not be re-run"
        assert date(2025, 4, 3) not in processed_dates, (
            "errored batch before boundary should be ignored"
        )


# ---------------------------------------------------------------------------
# _get_latest_succeeded_date
# ---------------------------------------------------------------------------


class TestGetLatestSucceededDate:
    async def test_returns_date_when_row_present(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"d": date(2025, 4, 5)}

        result = await _get_latest_succeeded_date(conn)

        assert result == date(2025, 4, 5)

    async def test_returns_none_when_no_succeeded_batches(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"d": None}

        result = await _get_latest_succeeded_date(conn)

        assert result is None

    async def test_returns_none_when_fetchrow_returns_none(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None

        result = await _get_latest_succeeded_date(conn)

        assert result is None
