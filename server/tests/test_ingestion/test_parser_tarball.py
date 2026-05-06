"""Tests for stream_tarball with synthetic tar archives."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from adsb_server.ingestion.parser import _is_tar_part, _parse_trace_json, stream_tarball


def _make_trace_bytes(
    icao: str = "aabbcc",
    t: str = "B738",
    timestamp: float = 1609275898.0,
    trace_entries: list[list[object]] | None = None,
) -> bytes:
    """Build a gzip-compressed trace JSON bytes."""
    data = {
        "icao": icao,
        "t": t,
        "timestamp": timestamp,
        "trace": trace_entries or [
            [0.0, 51.5, -0.1, 35000.0, 450.0, 90.0, 0, None, None],
            [10.0, 51.6, -0.2, 35100.0, 455.0, 91.0, 0, None, None],
        ],
    }
    return gzip.compress(json.dumps(data).encode())


def _make_tar_with_trace(
    icao: str = "aabbcc",
    compress: bool = True,
) -> bytes:
    """Create an in-memory tar archive containing one trace file."""
    trace_bytes = _make_trace_bytes(icao=icao)
    hex2 = icao[:2].lower()

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz" if compress else "w:") as tf:
        member_name = f"traces/{hex2}/trace_full_{icao}.json.gz"
        ti = tarfile.TarInfo(name=member_name)
        ti.size = len(trace_bytes)
        tf.addfile(ti, io.BytesIO(trace_bytes))
    return buf.getvalue()


class TestStreamTarballFile:
    def test_stream_tarball_file_yields_aircraft(self, tmp_path: Path) -> None:
        """stream_tarball on a .tar.gz file yields trace data."""
        tar_bytes = _make_tar_with_trace("aabbcc")
        tar_path = tmp_path / "test.tar.gz"
        tar_path.write_bytes(tar_bytes)

        results = list(stream_tarball(tar_path))
        assert len(results) == 1
        header, points = results[0]
        assert header.icao24 == "aabbcc"
        assert len(points) == 2

    def test_stream_tarball_file_nonexistent_raises(self, tmp_path: Path) -> None:
        """stream_tarball raises FileNotFoundError for non-existent path."""
        with pytest.raises(FileNotFoundError):
            list(stream_tarball(tmp_path / "does_not_exist.tar.gz"))

    def test_stream_tarball_skips_bad_json(self, tmp_path: Path) -> None:
        """stream_tarball skips files that fail to parse."""
        bad_bytes = gzip.compress(b"not json")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            ti = tarfile.TarInfo(name="traces/aa/trace_full_aabbcc.json.gz")
            ti.size = len(bad_bytes)
            tf.addfile(ti, io.BytesIO(bad_bytes))
        tar_path = tmp_path / "bad.tar.gz"
        tar_path.write_bytes(buf.getvalue())

        results = list(stream_tarball(tar_path))
        assert results == []

    def test_stream_tarball_skips_non_trace_members(self, tmp_path: Path) -> None:
        """stream_tarball ignores members not under traces/ or not .json.gz."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            content = b"some other file"
            ti = tarfile.TarInfo(name="other/file.txt")
            ti.size = len(content)
            tf.addfile(ti, io.BytesIO(content))
        tar_path = tmp_path / "other.tar.gz"
        tar_path.write_bytes(buf.getvalue())

        results = list(stream_tarball(tar_path))
        assert results == []


class TestStreamTarballDirectory:
    def test_stream_tarball_dir_yields_aircraft(self, tmp_path: Path) -> None:
        """stream_tarball on a directory of tar parts yields trace data."""
        # Create an uncompressed tar split into two parts
        trace_bytes = _make_trace_bytes(icao="cc1122")
        hex2 = "cc"

        # Build a raw (uncompressed) tar
        raw_buf = io.BytesIO()
        with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
            member_name = f"traces/{hex2}/trace_full_cc1122.json.gz"
            ti = tarfile.TarInfo(name=member_name)
            ti.size = len(trace_bytes)
            tf.addfile(ti, io.BytesIO(trace_bytes))
        raw_bytes = raw_buf.getvalue()

        # Split at midpoint
        mid = len(raw_bytes) // 2
        part_aa = tmp_path / "archive.tar.aa"
        part_ab = tmp_path / "archive.tar.ab"
        part_aa.write_bytes(raw_bytes[:mid])
        part_ab.write_bytes(raw_bytes[mid:])

        results = list(stream_tarball(tmp_path))
        assert len(results) == 1
        header, points = results[0]
        assert header.icao24 == "cc1122"
        assert len(points) == 2

    def test_stream_tarball_empty_dir_yields_nothing(self, tmp_path: Path) -> None:
        """Empty directory → no results."""
        results = list(stream_tarball(tmp_path))
        assert results == []

    def test_stream_tarball_dir_multiple_aircraft(self, tmp_path: Path) -> None:
        """Directory with two aircraft in the same tar."""
        trace1 = _make_trace_bytes(icao="aabbcc")
        trace2 = _make_trace_bytes(icao="ddeeff")

        raw_buf = io.BytesIO()
        with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
            for icao, tb in [("aabbcc", trace1), ("ddeeff", trace2)]:
                hex2 = icao[:2]
                member_name = f"traces/{hex2}/trace_full_{icao}.json.gz"
                ti = tarfile.TarInfo(name=member_name)
                ti.size = len(tb)
                tf.addfile(ti, io.BytesIO(tb))
        raw_bytes = raw_buf.getvalue()

        # Don't split: write as single part
        (tmp_path / "archive.tar.aa").write_bytes(raw_bytes)

        results = list(stream_tarball(tmp_path))
        assert len(results) == 2
        icaos = {h.icao24 for h, _ in results}
        assert icaos == {"aabbcc", "ddeeff"}


class TestIsTarPart:
    def test_tar_aa_is_part(self, tmp_path: Path) -> None:
        p = tmp_path / "archive.tar.aa"
        assert _is_tar_part(p) is True

    def test_tar_gz_is_not_part(self, tmp_path: Path) -> None:
        p = tmp_path / "archive.tar.gz"
        assert _is_tar_part(p) is False

    def test_plain_tar_is_not_part(self, tmp_path: Path) -> None:
        p = tmp_path / "archive.tar"
        assert _is_tar_part(p) is False

    def test_txt_is_not_part(self, tmp_path: Path) -> None:
        p = tmp_path / "file.txt"
        assert _is_tar_part(p) is False

    def test_tar_ab_is_part(self, tmp_path: Path) -> None:
        p = tmp_path / "data.tar.ab"
        assert _is_tar_part(p) is True


class TestParseTraceJsonEdgeCases:
    def test_invalid_icao_raises(self) -> None:
        with pytest.raises(ValueError, match="icao"):
            _parse_trace_json({"icao": 123, "timestamp": 0, "trace": []})

    def test_invalid_timestamp_raises(self) -> None:
        with pytest.raises(ValueError, match="timestamp"):
            _parse_trace_json({"icao": "aabbcc", "timestamp": "not_a_number", "trace": []})

    def test_non_list_trace_raises(self) -> None:
        with pytest.raises(ValueError):
            _parse_trace_json({"icao": "aabbcc", "timestamp": 0, "trace": "bad"})

    def test_short_entry_skipped(self) -> None:
        """Entries with fewer than 3 elements are skipped."""
        data = {
            "icao": "aabbcc",
            "timestamp": 0.0,
            "trace": [
                [0.0, 51.5],  # only 2 elements → skipped
                [1.0, 51.5, -0.1, 35000.0],  # valid
            ],
        }
        _, points = _parse_trace_json(data)
        assert len(points) == 1

    def test_alt_baro_non_numeric_non_string_object(self) -> None:
        """alt_baro value that can't be converted to float → treated as ground."""
        data = {
            "icao": "aabbcc",
            "timestamp": 0.0,
            "trace": [
                [0.0, 51.5, -0.1, [], None, None, 0, None, None],  # alt_baro=[] → None
                [1.0, 51.5, -0.1, 35000.0, None, None, 0, None, None],  # valid
            ],
        }
        _, points = _parse_trace_json(data)
        assert len(points) == 2
        assert points[0].alt_baro is None

    def test_invalid_flags_treated_as_zero(self) -> None:
        """Non-integer flags field → treated as 0, new_leg=False."""
        data = {
            "icao": "aabbcc",
            "timestamp": 0.0,
            "trace": [
                [0.0, 51.5, -0.1, 35000.0, None, None, "bad_flags", None, None],
            ],
        }
        _, points = _parse_trace_json(data)
        assert len(points) == 1
        assert points[0].new_leg is False

    def test_empty_trace(self) -> None:
        """Empty trace → empty points list."""
        data = {"icao": "aabbcc", "timestamp": 0.0, "trace": []}
        header, points = _parse_trace_json(data)
        assert header.icao24 == "aabbcc"
        assert points == []
