"""Parser for ADS-B trace JSON files from the adsb.lol archive."""

from __future__ import annotations

import gzip
import io
import logging
import tarfile
from collections.abc import Iterator  # noqa: TC003
from pathlib import Path  # noqa: TC003
from typing import IO, Any, cast

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
    except TypeError, ValueError:
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
        except TypeError, ValueError:
            continue

        try:
            ts = base_ts + float(offset_raw)
        except TypeError, ValueError:
            continue

        alt_baro = _parse_alt_baro(entry[3] if len(entry) > 3 else None)

        # gs at index 4
        gs_raw = entry[4] if len(entry) > 4 else None
        gs: float | None = None
        if gs_raw is not None:
            try:
                gs = float(gs_raw)
            except TypeError, ValueError:
                gs = None

        # track at index 5
        track_raw = entry[5] if len(entry) > 5 else None
        track: float | None = None
        if track_raw is not None:
            try:
                track = float(track_raw)
            except TypeError, ValueError:
                track = None

        # flags at index 6
        flags_raw = entry[6] if len(entry) > 6 else None
        try:
            flags = int(flags_raw or 0)
        except TypeError, ValueError:
            flags = 0
        new_leg = bool(flags & 2)

        # vr at index 7
        vr_raw = entry[7] if len(entry) > 7 else None
        vr: float | None = None
        if vr_raw is not None:
            try:
                vr = float(vr_raw)
            except TypeError, ValueError:
                vr = None

        # aircraft_obj at index 8
        aircraft_obj = entry[8] if len(entry) > 8 else None
        callsign, squawk, emitter_category = _parse_aircraft_obj(aircraft_obj)

        # ias at index 12 (2022+ format only)
        ias_raw = entry[12] if len(entry) > 12 else None
        ias: float | None = None
        if ias_raw is not None:
            try:
                ias = float(ias_raw)
            except TypeError, ValueError:
                ias = None

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
                gs=gs,
                vr=vr,
                ias=ias,
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


def count_traces(path: Path) -> int:
    """
    Return the number of trace files in a tarball without parsing their content.

    Uses seeking mode ("r") on single-file tars so only headers are read.
    Returns 0 for directory-based (split) archives — count is treated as unknown.
    """
    if not path.is_file():
        return 0
    with tarfile.open(path, "r") as tf:
        return sum(1 for m in tf if _is_trace_member(m.name))


def parse_trace_bytes(raw_bytes: bytes) -> tuple[TraceHeader, list[RawPoint]]:
    """Decompress if gzip-compressed and parse trace JSON into (TraceHeader, list[RawPoint])."""
    json_bytes = gzip.decompress(raw_bytes) if raw_bytes[:2] == b"\x1f\x8b" else raw_bytes
    data: dict[str, Any] = orjson.loads(json_bytes)
    return _parse_trace_json(data)


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


def _iter_tarfile_raw(tf: tarfile.TarFile) -> Iterator[tuple[str, bytes]]:
    """Yield (member_name, raw_bytes) for each trace member without parsing."""
    for member in tf:
        name = member.name
        if not _is_trace_member(name):
            continue
        try:
            f = tf.extractfile(member)
            if f is None:
                continue
            yield name, f.read()
        except Exception:
            logger.exception("Failed to read trace file: %s", name)
            continue


def stream_tarball_raw(path: Path) -> Iterator[tuple[str, bytes]]:
    """
    Stream raw trace bytes from a tarball or directory of tarball parts.

    Yields (member_name, raw_bytes) where raw_bytes is the file content as stored
    in the tarball (typically gzip-compressed JSON). Callers should parse with
    parse_trace_bytes().
    """
    if path.is_file():
        with tarfile.open(path, "r:*") as tf:
            yield from _iter_tarfile_raw(tf)
    elif path.is_dir():
        parts = sorted(
            [p for p in path.iterdir() if _is_tar_part(p)],
            key=lambda p: p.suffix,
        )
        if not parts:
            logger.warning("No tar parts found in directory: %s", path)
            return
        stream = _ChainedStream(parts)
        with tarfile.open(fileobj=cast("IO[bytes]", stream), mode="r|") as tf:
            yield from _iter_tarfile_raw(tf)
    else:
        raise FileNotFoundError(f"Path does not exist: {path}")
