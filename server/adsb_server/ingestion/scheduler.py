"""Scheduler: discover new adsb.lol releases and kick off batch ingestion."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from datetime import date
from pathlib import Path  # noqa: TC003

import asyncpg  # noqa: TC002
import httpx

from adsb_server.ingestion.batch import run_batch

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
        resp = await client.get(
            url, params={"per_page": _GITHUB_RELEASES_PER_PAGE, "page": page}
        )
        resp.raise_for_status()
        result: list[dict[str, object]] = resp.json()
        return result
    except httpx.HTTPError:
        logger.warning("Failed to fetch releases for year %d", year, exc_info=True)
        return []


async def _is_batch_already_processed(
    conn: asyncpg.Connection,    batch_date: date,
) -> bool:
    """Return True if this batch_date has status 'running' or 'succeeded'."""
    row = await conn.fetchrow(
        "SELECT status FROM ingest_batches WHERE batch_date = $1",
        batch_date,
    )
    if row is None:
        return False
    status: str = row["status"]
    return status in ("running", "succeeded")


async def _download_asset(
    client: httpx.AsyncClient,
    asset_url: str,
    dest: Path,
    expected_size: int,
) -> None:
    """Download a release asset to dest, skipping if already present with correct size."""
    if dest.exists() and dest.stat().st_size == expected_size:
        logger.debug("Asset already downloaded: %s", dest)
        return

    logger.info("Downloading %s → %s", asset_url, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    async with client.stream("GET", asset_url) as resp:
        resp.raise_for_status()
        with dest.open("wb") as f:
            async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                f.write(chunk)


async def _download_and_process_release(
    conn: asyncpg.Connection,    client: httpx.AsyncClient,
    year: int,
    tag: str,
    batch_date: date,
    cache_dir: Path,
) -> None:
    """Download all tar parts for a release and run the batch ingestion."""
    repo = _REPO_TEMPLATE.format(year=year)
    release_url = f"{_GITHUB_API_BASE}/repos/{repo}/releases/tags/{tag}"

    try:
        resp = await client.get(release_url)
        resp.raise_for_status()
        release_data: dict[str, object] = resp.json()
    except httpx.HTTPError:
        logger.error("Failed to fetch release %s", tag, exc_info=True)
        return

    assets: list[dict[str, object]] = release_data.get("assets", [])  # type: ignore[assignment]
    if not assets:
        logger.warning("No assets found for release %s", tag)
        return

    batch_date_str = batch_date.isoformat()
    dest_dir = cache_dir / batch_date_str

    for asset in assets:
        asset_name: str = str(asset.get("name", ""))
        asset_url: str = str(asset.get("browser_download_url", ""))
        asset_size: int = int(str(asset.get("size", 0)))

        if not asset_url:
            continue

        dest = dest_dir / asset_name
        try:
            await _download_asset(client, asset_url, dest, asset_size)
        except Exception:
            logger.error("Failed to download asset %s", asset_name, exc_info=True)
            return

    logger.info("Starting batch ingestion for %s", batch_date_str)
    try:
        count = await run_batch(conn, dest_dir, batch_date)
        logger.info("Batch %s: %d flights ingested", batch_date_str, count)
        shutil.rmtree(dest_dir, ignore_errors=True)
    except Exception:
        logger.error("Batch %s failed", batch_date_str, exc_info=True)
        await conn.execute(
            """
            UPDATE ingest_batches
            SET status='failed', finished_at=NOW(), error_message=$2
            WHERE batch_date=$1
            """,
            batch_date,
            "Batch processing failed; see server logs.",
        )


async def check_and_run_new_batches(
    conn: asyncpg.Connection,    cache_dir: Path,
) -> None:
    """
    Query the GitHub API for new adsb.lol releases and process any unprocessed ones.
    Checks current year and previous year (to handle year boundaries).
    Paginates through releases (newest-first) until a processed batch is found,
    then ingests all discovered batches oldest-first.
    """
    today = date.today()
    years_to_check = [today.year, today.year - 1]

    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"Accept": "application/vnd.github+json"},
    ) as client:
        for year in years_to_check:
            to_process: list[tuple[str, date]] = []
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

                    if await _is_batch_already_processed(conn, batch_date):
                        logger.debug("Batch %s already processed, stopping scan", batch_date)
                        stop = True
                        break

                    to_process.append((tag, batch_date))

                if len(releases) < _GITHUB_RELEASES_PER_PAGE:
                    break

                page += 1

            to_process.sort(key=lambda item: item[1])
            for tag, batch_date in to_process:
                logger.info("New batch found: %s (tag=%s)", batch_date, tag)
                await _download_and_process_release(
                    conn, client, year, tag, batch_date, cache_dir
                )

            if stop:
                break  # processed release found; all earlier years are also done


async def scheduler_loop(
    conn: asyncpg.Connection,    cache_dir: Path,
    interval_seconds: int = 1800,
) -> None:
    """
    Loop that calls check_and_run_new_batches every interval_seconds.
    Handles errors gracefully, continuing to loop after failures.
    """
    logger.info("Scheduler loop started (interval=%ds)", interval_seconds)
    while True:
        try:
            await check_and_run_new_batches(conn, cache_dir)
        except Exception:
            logger.error("Error in check_and_run_new_batches", exc_info=True)
        await asyncio.sleep(interval_seconds)
