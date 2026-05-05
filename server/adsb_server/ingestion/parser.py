"""Parser for ADS-B trace JSON files from the adsb.lol archive."""

from __future__ import annotations

import gzip
import io
import logging
import tarfile
from collections.abc import Iterator  # noqa: TC003
from pathlib import Path  # noqa: TC003
from typing import Any

import orjson

from adsb_server.ingestion.models import RawPoint, TraceHeader

logger = logging.getLogger(__name__)


def _parse_alt_baro(raw: Any) -> float | None:
    """Parse alt_baro field: float → float, "ground" → None, null → None."""
    if raw is None:
        return None
    if isinstance(raw, str):
        # "ground" or any string → treat as ground
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_aircraft_obj(
    obj: Any,
) -> tuple[str | None, str | None, str | None]:
    """
    Extract (callsign, squawk, emitter_category) from an aircraft_obj dict.
    Returns (None, None, None) if obj is None or not a dict.
    """
    if not isinstance(obj, dict):
        return None, None, None

    raw_flight: Any = obj.get("flight")
    callsign: str | None = None
    if isinstance(raw_flight, str):
        stripped = raw_flight.strip()
        callsign = stripped if stripped else None

    raw_squawk: Any = obj.get("squawk")
    squawk: str | None = None
    if isinstance(raw_squawk, str) and raw_squawk:
        squawk = raw_squawk
    elif raw_squawk is not None:
        squawk = str(raw_squawk)

    raw_cat: Any = obj.get("category")
    emitter_category: str | None = None
    if isinstance(raw_cat, str) and raw_cat:
        emitter_category = raw_cat

    return callsign, squawk, emitter_category


def _parse_trace_json(data: dict[str, Any]) -> tuple[TraceHeader, list[RawPoint]]:
    """
    Parse a trace JSON dict into (TraceHeader, list[RawPoint]).

    Skips points where:
    - alt_baro is "ground" or null
    - lat/lon are missing

    Raises ValueError on malformed input.
    """
    icao24_raw: Any = data.get("icao")
    if not isinstance(icao24_raw, str):
        raise ValueError(f"Missing or non-string icao field: {icao24_raw!r}")
    icao24 = icao24_raw.lower()

    icao_type_raw: Any = data.get("t")
    icao_type: str | None = (
        icao_type_raw if isinstance(icao_type_raw, str) and icao_type_raw else None
    )

    header = TraceHeader(icao24=icao24, icao_type=icao_type)

    base_ts_raw: Any = data.get("timestamp")
    try:
        base_ts = float(base_ts_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid timestamp: {base_ts_raw!r}") from exc

    raw_trace: Any = data.get("trace", [])
    if not isinstance(raw_trace, list):
        raise ValueError(f"trace field is not a list: {type(raw_trace)}")

    points: list[RawPoint] = []

    for entry in raw_trace:
        if not isinstance(entry, list) or len(entry) < 3:
            continue

        # [offset, lat, lon, alt_baro, gs, track, flags, vr, aircraft_obj, ...]
        offset_raw = entry[0]
        lat_raw = entry[1]
        lon_raw = entry[2]

        # Skip if lat/lon are missing
        if lat_raw is None or lon_raw is None:
            continue
        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except (TypeError, ValueError):
            continue

        try:
            ts = base_ts + float(offset_raw)
        except (TypeError, ValueError):
            continue

        alt_baro = _parse_alt_baro(entry[3] if len(entry) > 3 else None)

        # Skip ground and missing altitude points
        if alt_baro is None:
            continue

        # track at index 5
        track_raw = entry[5] if len(entry) > 5 else None
        track: float | None = None
        if track_raw is not None:
            try:
                track = float(track_raw)
            except (TypeError, ValueError):
                track = None

        # flags at index 6
        flags_raw = entry[6] if len(entry) > 6 else None
        try:
            flags = int(flags_raw or 0)
        except (TypeError, ValueError):
            flags = 0
        new_leg = bool(flags & 2)

        # aircraft_obj at index 8
        aircraft_obj = entry[8] if len(entry) > 8 else None
        callsign, squawk, emitter_category = _parse_aircraft_obj(aircraft_obj)

        points.append(
            RawPoint(
                ts=ts,
                lat=lat,
                lon=lon,
                alt_baro=alt_baro,
                track=track,
                squawk=squawk,
                new_leg=new_leg,
                callsign=callsign,
                emitter_category=emitter_category,
            )
        )

    return header, points


class _ChainedStream(io.RawIOBase):
    """
    An io.RawIOBase that reads from a sequence of files sequentially,
    used to present multi-part tarballs as a single stream.
    """

    def __init__(self, paths: list[Path]) -> None:
        super().__init__()
        self._paths = paths
        self._idx = 0
        self._current: io.BufferedReader | None = None
        self._open_next()

    def _open_next(self) -> None:
        if self._current is not None:
            self._current.close()
            self._current = None
        if self._idx < len(self._paths):
            self._current = open(self._paths[self._idx], "rb")  # noqa: SIM115
            self._idx += 1

    def readinto(self, b: bytearray | memoryview) -> int:  # type: ignore[override]
        while True:
            if self._current is None:
                return 0
            n = self._current.readinto(b)
            if n is None:
                return 0
            if n > 0:
                return n
            # Current file exhausted, open next
            self._open_next()

    def readable(self) -> bool:
        return True


def stream_tarball(path: Path) -> Iterator[tuple[TraceHeader, list[RawPoint]]]:
    """
    Stream all trace files from a tarball or directory of tarball parts.

    If path is a file: open with tarfile.open(path, "r:*") (auto-detect compression).
    If path is a directory: find all *.tar.* files sorted by suffix, chain them
    via _ChainedStream, open with tarfile.open(fileobj=stream, mode="r|").

    Yields (TraceHeader, list[RawPoint]) for each aircraft with non-empty points.
    Skips trace files that fail to parse.
    """
    if path.is_file():
        with tarfile.open(path, "r:*") as tf:
            yield from _iter_tarfile(tf)
    elif path.is_dir():
        # Find and sort all tar parts by their extension suffix (e.g., .tar.aa < .tar.ab)
        parts = sorted(
            [p for p in path.iterdir() if _is_tar_part(p)],
            key=lambda p: p.suffix,
        )
        if not parts:
            logger.warning("No tar parts found in directory: %s", path)
            return
        stream = _ChainedStream(parts)
        with tarfile.open(fileobj=stream, mode="r|") as tf:  # streaming, uncompressed
            yield from _iter_tarfile(tf)
    else:
        raise FileNotFoundError(f"Path does not exist: {path}")


_COMPRESSION_SUFFIXES = frozenset({"gz", "bz2", "xz", "zst", "lz4", "lzma"})


def _is_tar_part(path: Path) -> bool:
    """
    Return True if path looks like a split tar part (e.g. archive.tar.aa, .tar.ab).

    Split archives (created by `split`) use sequential two-letter suffixes such as
    aa, ab, ac, ..., az, ba, ... zz. Compressed tarballs (.tar.gz, .tar.bz2, etc.)
    are excluded by checking against known compression suffixes.
    """
    name = path.name
    # Match files ending in .tar.XX where XX is alphabetic
    parts = name.rsplit(".", 2)
    if len(parts) != 3 or parts[1] != "tar":
        return False
    suffix = parts[2]
    if suffix in _COMPRESSION_SUFFIXES:
        return False
    return suffix.isalpha() and suffix.islower()


def _is_trace_member(name: str) -> bool:
    """Return True if a tar member name is a trace JSON file under traces/."""
    normalized = name.lstrip("./")
    return normalized.startswith("traces/") and (
        name.endswith(".json.gz") or name.endswith(".json")
    )


def _iter_tarfile(tf: tarfile.TarFile) -> Iterator[tuple[TraceHeader, list[RawPoint]]]:
    """Iterate over members of a TarFile and yield parsed trace data."""
    for member in tf:
        name = member.name
        if not _is_trace_member(name):
            continue
        try:
            f = tf.extractfile(member)
            if f is None:
                continue
            raw_bytes = f.read()
            if name.endswith(".json.gz") or raw_bytes[:2] == b"\x1f\x8b":
                raw_bytes = gzip.decompress(raw_bytes)
            data: dict[str, Any] = orjson.loads(raw_bytes)
            header, points = _parse_trace_json(data)
            if points:
                yield header, points
        except Exception:
            logger.exception("Failed to parse trace file: %s", name)
            continue
