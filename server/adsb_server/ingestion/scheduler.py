"""Scheduler: discover new adsb.lol releases and kick off batch ingestion."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    import asyncpg
    import xarray as xr

from adsb_server.config import get_settings
from adsb_server.ingestion.batch import run_batch
from adsb_server.pressure.fetch import fetch_mslp_for_batch

logger = logging.getLogger(__name__)

_GITHUB_API_BASE = "https://api.github.com"
_REPO_TEMPLATE = "adsblol/globe_history_{year}"
_TAG_PATTERN = re.compile(r"^v(\d{4})\.(\d{2})\.(\d{2})-planes-readsb-prod-\d+$")

# Default timeout for HTTP requests (seconds)
_HTTP_TIMEOUT = 60.0
_GITHUB_RELEASES_PER_PAGE = 100


def _tag_to_date(tag: str) -> date | None:
    """Extract date from release tag. Returns None if tag doesn't match."""
    m = _TAG_PATTERN.match(tag)
    if m is None:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


async def _get_releases(
    client: httpx.AsyncClient,
    year: int,
    page: int = 1,
) -> list[dict[str, object]]:
    """Fetch one page of releases from the GitHub API for the given year's repo."""
    repo = _REPO_TEMPLATE.format(year=year)
    url = f"{_GITHUB_API_BASE}/repos/{repo}/releases"
    try:
        resp = await client.get(url, params={"per_page": _GITHUB_RELEASES_PER_PAGE, "page": page})
        resp.raise_for_status()
        result: list[dict[str, object]] = resp.json()
        return result
    except httpx.HTTPError:
        logger.warning("Failed to fetch releases for year %d", year, exc_info=True)
        return []


async def _is_batch_already_processed(
    conn: asyncpg.Connection,
    batch_date: date,
) -> bool:
    """Return True if this batch_date has status 'succeeded'."""
    row = await conn.fetchrow(
        "SELECT status FROM ingest_batches WHERE batch_date = $1",
        batch_date,
    )
    if row is None:
        return False
    status: str = row["status"]
    return status == "succeeded"


async def _get_errored_dates(conn: asyncpg.Connection) -> set[date]:
    """Return the set of batch dates currently in 'errored' status."""
    rows = await conn.fetch("SELECT batch_date FROM ingest_batches WHERE status = 'errored'")
    return {row["batch_date"] for row in rows}


async def _fetch_releases_by_date(
    client: httpx.AsyncClient,
    year: int,
) -> dict[date, str]:
    """Fetch all releases for a year and return a date → newest-tag mapping.

    Releases are returned newest-first by the API, so setdefault keeps the
    latest revision when multiple tags exist for the same date.
    """
    releases_by_date: dict[date, str] = {}
    page = 1
    while True:
        releases = await _get_releases(client, year, page=page)
        if not releases:
            break
        for release in releases:
            tag = str(release.get("tag_name", ""))
            batch_date = _tag_to_date(tag)
            if batch_date is not None:
                releases_by_date.setdefault(batch_date, tag)
        if len(releases) < _GITHUB_RELEASES_PER_PAGE:
            break
        page += 1
    return releases_by_date


async def _find_tag_for_date(
    client: httpx.AsyncClient,
    year: int,
    target: date,
) -> str | None:
    """Return the newest release tag for a specific date, or None if not found."""
    page = 1
    while True:
        releases = await _get_releases(client, year, page=page)
        if not releases:
            return None
        for release in releases:
            tag = str(release.get("tag_name", ""))
            batch_date = _tag_to_date(tag)
            if batch_date == target:
                return tag  # newest-first, so first match is the latest revision
            if batch_date is not None and batch_date < target:
                return None  # passed the target date without finding it
        if len(releases) < _GITHUB_RELEASES_PER_PAGE:
            return None
        page += 1


async def _download_asset(
    client: httpx.AsyncClient,
    asset_url: str,
    dest: Path,
    expected_size: int,
    updated_at: str,
) -> None:
    """Download a release asset to dest.

    Skips the download when the file exists at the expected size and its .etag
    sidecar records the same updated_at timestamp as the GitHub API returns.
    Redownloads if the file is missing, the wrong size, the sidecar is absent,
    or updated_at has changed (indicating the asset was replaced on GitHub).
    """
    etag_path = Path(str(dest) + ".etag")

    if dest.exists() and dest.stat().st_size == expected_size and etag_path.exists():
        if etag_path.read_text().strip() == updated_at:
            logger.debug("Asset already downloaded and current: %s", dest.name)
            return
        logger.info(
            "Asset %s has changed on GitHub (updated_at differs) — redownloading",
            dest.name,
        )

    if dest.exists():
        dest.unlink()
    if etag_path.exists():
        etag_path.unlink()

    logger.info("Downloading %s → %s", asset_url, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    async with client.stream("GET", asset_url) as resp:
        resp.raise_for_status()
        with dest.open("wb") as f:
            async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                f.write(chunk)

    etag_path.write_text(updated_at)


async def _fetch_release_assets(
    client: httpx.AsyncClient,
    year: int,
    tag: str,
    batch_date: date,
    cache_dir: Path,
) -> tuple[str, Path | None] | None:
    """Fetch release metadata and download all assets.

    Returns:
        None on HTTP error or asset download failure.
        (release_api_url, None) when the release has no assets.
        (release_api_url, dest_dir) when all assets are downloaded.
    """
    repo = _REPO_TEMPLATE.format(year=year)
    release_api_url = f"{_GITHUB_API_BASE}/repos/{repo}/releases/tags/{tag}"

    try:
        resp = await client.get(release_api_url)
        resp.raise_for_status()
        release_data: dict[str, object] = resp.json()
    except httpx.HTTPError:
        logger.error("Failed to fetch release %s", tag, exc_info=True)
        return None

    assets: list[dict[str, object]] = release_data.get("assets", [])  # type: ignore[assignment]
    if not assets:
        logger.warning("No assets found for release %s", tag)
        return release_api_url, None

    batch_date_str = batch_date.isoformat()
    dest_dir = cache_dir / batch_date_str

    for asset in assets:
        asset_name: str = str(asset.get("name", ""))
        asset_url: str = str(asset.get("browser_download_url", ""))
        asset_size: int = int(str(asset.get("size", 0)))
        asset_updated_at: str = str(asset.get("updated_at", ""))

        if not asset_url:
            continue

        dest = dest_dir / asset_name
        try:
            await _download_asset(client, asset_url, dest, asset_size, asset_updated_at)
        except Exception:
            logger.error("Failed to download asset %s", asset_name, exc_info=True)
            return None

    return release_api_url, dest_dir


async def _prefetch_release(
    client: httpx.AsyncClient,
    year: int,
    tag: str,
    batch_date: date,
    cache_dir: Path,
    herbie_cache_dir: Path,
) -> tuple[str, Path | None, xr.DataArray | None] | None:
    """Download release assets and fetch MSLP data in parallel.

    Returns:
        None if the asset download fails (caller should clean up ingest_batches).
        (release_api_url, None, mslp) when the release has no assets.
        (release_api_url, dest_dir, mslp) on success; mslp may be None if the
        MSLP fetch failed (run_batch will retry from settings cache dir).
    """
    asset_result, mslp = await asyncio.gather(
        _fetch_release_assets(client, year, tag, batch_date, cache_dir),
        fetch_mslp_for_batch(batch_date, herbie_cache_dir),
    )
    if asset_result is None:
        return None
    release_api_url, dest_dir = asset_result
    return release_api_url, dest_dir, mslp


async def _process_downloaded_release(
    conn: asyncpg.Connection,
    batch_date: date,
    dest_dir: Path,
    mslp: xr.DataArray | None,
    release_api_url: str,
    keep_traces: bool = False,
    workers: int | None = None,
) -> bool:
    """Run batch ingestion on already-downloaded assets and update DB state.

    Returns True on success, False on failure (batch marked 'errored').
    Downloaded files are kept on failure to allow resuming on the next attempt.
    """
    batch_date_str = batch_date.isoformat()
    logger.info("Starting batch ingestion for %s", batch_date_str)
    try:
        count = await run_batch(conn, dest_dir, batch_date, workers=workers, mslp=mslp)
        logger.info("Batch %s: %d flights ingested", batch_date_str, count)
        if not keep_traces:
            shutil.rmtree(dest_dir, ignore_errors=True)
        return True
    except Exception:
        logger.error("Batch %s failed", batch_date_str, exc_info=True)
        await conn.execute(
            """
            UPDATE ingest_batches
            SET status='errored', finished_at=NOW(), error_message=$2, release_url=$3
            WHERE batch_date=$1
            """,
            batch_date,
            "Batch processing failed; see server logs.",
            release_api_url,
        )
        # Keep dest_dir so verified downloads can be reused on the next attempt.
        return False


async def _process_date_queue(
    conn: asyncpg.Connection,
    client: httpx.AsyncClient,
    year: int,
    queue: list[tuple[date, str]],
    cache_dir: Path,
    herbie_cache_dir: Path,
    keep_traces: bool,
    workers: int | None,
    *,
    log_verb: str,
) -> None:
    """Pipeline-process a sorted list of (batch_date, tag) pairs oldest-first.

    Prefetches each date's assets and MSLP data while the previous date is being
    ingested so download I/O overlaps with CPU-bound trace processing.
    """
    if not queue:
        return
    prefetch_task = asyncio.create_task(
        _prefetch_release(client, year, queue[0][1], queue[0][0], cache_dir, herbie_cache_dir)
    )
    for i, (batch_date, tag) in enumerate(queue):
        logger.info("%s %s (tag=%s)", log_verb, batch_date, tag)
        fetch_result = await prefetch_task
        if i + 1 < len(queue):
            next_date, next_tag = queue[i + 1]
            prefetch_task = asyncio.create_task(
                _prefetch_release(client, year, next_tag, next_date, cache_dir, herbie_cache_dir)
            )
        if fetch_result is None:
            logger.error("Failed to fetch release for %s — skipping", batch_date)
            await conn.execute("DELETE FROM ingest_batches WHERE batch_date = $1", batch_date)
            continue
        release_api_url, dest_dir, mslp = fetch_result
        if dest_dir is None:
            continue
        ok = await _process_downloaded_release(
            conn,
            batch_date,
            dest_dir,
            mslp,
            release_api_url,
            keep_traces=keep_traces,
            workers=workers,
        )
        if not ok:
            logger.warning("Batch %s errored — continuing", batch_date)


async def check_and_run_new_batches(
    conn: asyncpg.Connection,
    cache_dir: Path,
    lookback_days: int = 0,
    keep_traces: bool = False,
    workers: int | None = None,
) -> None:
    """
    Query the GitHub API for new adsb.lol releases and process any unprocessed ones.
    Checks current year and previous year (to handle year boundaries).
    Paginates through releases (newest-first) until a processed batch is found,
    then ingests all discovered batches oldest-first.

    If lookback_days > 0, releases older than that many days are ignored.

    Previously errored batches are re-queued automatically.  Their follow-up
    day (the day immediately after each errored date) is also re-queued so that
    any in-progress flights which spilled across the boundary are corrected.
    Processing continues past failures — each failed batch is marked 'errored'
    and the scheduler moves on to the next pending date.
    """
    today = date.today()
    cutoff = today - timedelta(days=lookback_days) if lookback_days > 0 else None
    years_to_check = [today.year, today.year - 1]

    # Dates that must be (re-)processed even if their status is already 'succeeded':
    # errored batches and the day after each (to fix in-progress flight data).
    errored_dates = await _get_errored_dates(conn)
    force_dates = errored_dates | {d + timedelta(days=1) for d in errored_dates}
    herbie_cache_dir = get_settings().herbie_cache_dir

    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"Accept": "application/vnd.github+json"},
    ) as client:
        for year in years_to_check:
            # Use a dict to deduplicate by date (newest tag wins via newest-first scan).
            to_process: dict[date, str] = {}
            page = 1
            stop = False

            while not stop:
                releases = await _get_releases(client, year, page=page)
                if not releases:
                    break

                for release in releases:
                    tag: str = str(release.get("tag_name", ""))
                    batch_date = _tag_to_date(tag)
                    if batch_date is None:
                        continue

                    if cutoff is not None and batch_date < cutoff:
                        stop = True
                        break

                    if await _is_batch_already_processed(conn, batch_date):
                        if batch_date not in force_dates:
                            logger.debug("Batch %s already processed, stopping scan", batch_date)
                            stop = True
                            break
                        # Succeeded but in force_dates (follow-up of an errored batch):
                        # queue for reprocessing and keep scanning.
                        to_process.setdefault(batch_date, tag)
                        continue

                    to_process.setdefault(batch_date, tag)

                if len(releases) < _GITHUB_RELEASES_PER_PAGE:
                    break

                page += 1

            # The main scan stops at the first succeeded non-force batch, so
            # force_dates older than that frontier are never encountered.  Look
            # them up explicitly so they are always retried.
            missed_force = {d for d in force_dates if d.year == year and d not in to_process}
            for fd in sorted(missed_force):
                fd_tag = await _find_tag_for_date(client, year, fd)
                if fd_tag:
                    to_process[fd] = fd_tag
                else:
                    logger.debug("No release found for force date %s", fd)

            await _process_date_queue(
                conn,
                client,
                year,
                [(d, to_process[d]) for d in sorted(to_process)],
                cache_dir,
                herbie_cache_dir,
                keep_traces,
                workers,
                log_verb="New batch found:",
            )

            if stop:
                break  # processed release found; all earlier years are also done


async def reimport_specific_dates(
    conn: asyncpg.Connection,
    dates: list[date],
    cache_dir: Path,
    keep_traces: bool = False,
    workers: int | None = None,
) -> None:
    """Download and reprocess specific batch dates, bypassing normal discovery.

    Useful for manually recovering dates that were skipped due to transient
    network errors or that fall behind the normal scan frontier.
    """
    dates_by_year: dict[int, list[date]] = {}
    for d in sorted(dates):
        dates_by_year.setdefault(d.year, []).append(d)

    herbie_cache_dir = get_settings().herbie_cache_dir

    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"Accept": "application/vnd.github+json"},
    ) as client:
        for year, year_dates in sorted(dates_by_year.items()):
            releases_by_date = await _fetch_releases_by_date(client, year)
            processable = [(d, releases_by_date[d]) for d in year_dates if d in releases_by_date]
            for d in year_dates:
                if d not in releases_by_date:
                    logger.warning("No release found for %s — skipping", d)
            if not processable:
                continue
            await _process_date_queue(
                conn,
                client,
                year,
                processable,
                cache_dir,
                herbie_cache_dir,
                keep_traces,
                workers,
                log_verb="Reimporting",
            )
