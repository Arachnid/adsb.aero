"""Tests for stream_tarball_raw and parse_trace_bytes with synthetic tar archives."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from adsb_server.ingestion.parser import (
    _is_tar_part,
    _parse_trace_json,
    parse_trace_bytes,
    stream_tarball_raw,
)


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
        "trace": trace_entries
        or [
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


class TestStreamTarballRawFile:
    def test_stream_tarball_raw_file_yields_aircraft(self, tmp_path: Path) -> None:
        """stream_tarball_raw on a .tar.gz file yields raw bytes that parse correctly."""
        tar_bytes = _make_tar_with_trace("aabbcc")
        tar_path = tmp_path / "test.tar.gz"
        tar_path.write_bytes(tar_bytes)

        results = list(stream_tarball_raw(tar_path))
        assert len(results) == 1
        name, raw_bytes = results[0]
        assert "aabbcc" in name
        header, points = parse_trace_bytes(raw_bytes)
        assert header.icao24 == "aabbcc"
        assert len(points) == 2

    def test_stream_tarball_raw_file_nonexistent_raises(self, tmp_path: Path) -> None:
        """stream_tarball_raw raises FileNotFoundError for non-existent path."""
        with pytest.raises(FileNotFoundError):
            list(stream_tarball_raw(tmp_path / "does_not_exist.tar.gz"))

    def test_stream_tarball_raw_skips_non_trace_members(self, tmp_path: Path) -> None:
        """stream_tarball_raw ignores members not under traces/ or not .json.gz."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            content = b"some other file"
            ti = tarfile.TarInfo(name="other/file.txt")
            ti.size = len(content)
            tf.addfile(ti, io.BytesIO(content))
        tar_path = tmp_path / "other.tar.gz"
        tar_path.write_bytes(buf.getvalue())

        results = list(stream_tarball_raw(tar_path))
        assert results == []


class TestParseTraceBytes:
    def test_parse_gzip_compressed_bytes(self) -> None:
        """parse_trace_bytes decompresses gzip and parses correctly."""
        raw = _make_trace_bytes(icao="aabbcc")
        header, points = parse_trace_bytes(raw)
        assert header.icao24 == "aabbcc"
        assert len(points) == 2

    def test_parse_uncompressed_bytes(self) -> None:
        """parse_trace_bytes handles plain (non-gzip) JSON bytes."""
        data = {
            "icao": "aabbcc",
            "t": "B738",
            "timestamp": 1609275898.0,
            "trace": [[0.0, 51.5, -0.1, 35000.0, 450.0, 90.0, 0, None, None]],
        }
        raw = json.dumps(data).encode()
        header, points = parse_trace_bytes(raw)
        assert header.icao24 == "aabbcc"
        assert len(points) == 1

    def test_parse_bad_json_raises(self) -> None:
        """parse_trace_bytes raises on non-JSON content."""
        with pytest.raises(Exception):
            parse_trace_bytes(gzip.compress(b"not json"))


def _make_two_part_archive(
    tmp_path: Path,
    icaos: list[str],
    split_after_member: int,
) -> None:
    """
    Write an uncompressed tar containing one trace per icao, split into
    archive.tar.aa (first `split_after_member` members) and archive.tar.ab (rest).
    """
    traces = {icao: _make_trace_bytes(icao=icao) for icao in icaos}

    raw_buf = io.BytesIO()
    with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
        for icao in icaos:
            ti = tarfile.TarInfo(name=f"traces/{icao[:2]}/trace_full_{icao}.json.gz")
            ti.size = len(traces[icao])
            tf.addfile(ti, io.BytesIO(traces[icao]))
    raw_bytes = raw_buf.getvalue()

    buf = io.BytesIO(raw_bytes)
    with tarfile.open(fileobj=buf, mode="r:") as tf:
        members = list(tf.getmembers())
    split_at = members[split_after_member].offset

    (tmp_path / "archive.tar.aa").write_bytes(raw_bytes[:split_at])
    (tmp_path / "archive.tar.ab").write_bytes(raw_bytes[split_at:])


class TestStreamTarballRawDirectory:
    def test_stream_tarball_raw_dir_yields_aircraft(self, tmp_path: Path) -> None:
        """stream_tarball_raw on a directory of tar parts yields raw bytes."""
        trace_bytes = _make_trace_bytes(icao="cc1122")

        raw_buf = io.BytesIO()
        with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
            member_name = "traces/cc/trace_full_cc1122.json.gz"
            ti = tarfile.TarInfo(name=member_name)
            ti.size = len(trace_bytes)
            tf.addfile(ti, io.BytesIO(trace_bytes))
        raw_bytes = raw_buf.getvalue()

        mid = len(raw_bytes) // 2
        (tmp_path / "archive.tar.aa").write_bytes(raw_bytes[:mid])
        (tmp_path / "archive.tar.ab").write_bytes(raw_bytes[mid:])

        results = list(stream_tarball_raw(tmp_path))
        assert len(results) == 1
        _name, rb = results[0]
        header, points = parse_trace_bytes(rb)
        assert header.icao24 == "cc1122"
        assert len(points) == 2

    def test_stream_tarball_raw_empty_dir_yields_nothing(self, tmp_path: Path) -> None:
        """Empty directory → no results."""
        results = list(stream_tarball_raw(tmp_path))
        assert results == []

    def test_stream_tarball_raw_dir_multiple_aircraft(self, tmp_path: Path) -> None:
        """Directory with two aircraft in the same tar."""
        trace1 = _make_trace_bytes(icao="aabbcc")
        trace2 = _make_trace_bytes(icao="ddeeff")

        raw_buf = io.BytesIO()
        with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
            for icao, tb in [("aabbcc", trace1), ("ddeeff", trace2)]:
                ti = tarfile.TarInfo(name=f"traces/{icao[:2]}/trace_full_{icao}.json.gz")
                ti.size = len(tb)
                tf.addfile(ti, io.BytesIO(tb))
        (tmp_path / "archive.tar.aa").write_bytes(raw_buf.getvalue())

        results = list(stream_tarball_raw(tmp_path))
        assert len(results) == 2
        icaos = {parse_trace_bytes(rb)[0].icao24 for _, rb in results}
        assert icaos == {"aabbcc", "ddeeff"}

    def test_stream_tarball_raw_dir_split_at_member_boundary(self, tmp_path: Path) -> None:
        """Split exactly between two members yields both."""
        _make_two_part_archive(tmp_path, ["aabbcc", "ddeeff"], split_after_member=0)

        results = list(stream_tarball_raw(tmp_path))
        assert len(results) == 2
        icaos = {parse_trace_bytes(rb)[0].icao24 for _, rb in results}
        assert icaos == {"aabbcc", "ddeeff"}

    def test_stream_tarball_raw_dir_many_members_across_parts(self, tmp_path: Path) -> None:
        """All members are yielded when the split falls between members mid-archive."""
        icaos = [f"aa{i:04x}" for i in range(10)]
        _make_two_part_archive(tmp_path, icaos, split_after_member=4)

        results = list(stream_tarball_raw(tmp_path))
        assert len(results) == 10
        parsed_icaos = {parse_trace_bytes(rb)[0].icao24 for _, rb in results}
        assert parsed_icaos == set(icaos)


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
