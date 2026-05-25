"""MobilityDB temporal type construction helpers for DB insertion."""

from __future__ import annotations

from datetime import UTC, datetime


def _fmt_ts(ts_epoch: float) -> str:
    """Format a unix epoch float as an ISO 8601 UTC timestamp for MobilityDB."""
    return datetime.fromtimestamp(ts_epoch, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f+00")


def tgeompoint_seq(vertices: list[tuple[float, float, float, float]]) -> str:
    """Return a MobilityDB tgeompoint sequence string (SRID 4326, linear interpolation).

    vertices: list of (lon, lat, alt_ft, ts_epoch) tuples.
    Output: 'SRID=4326;[POINT Z (lon lat alt)@ts, ...]'
    """
    instants = [
        f"POINT Z ({lon} {lat} {alt_ft})@{_fmt_ts(ts)}" for lon, lat, alt_ft, ts in vertices
    ]
    return f"SRID=4326;[{', '.join(instants)}]"


def ttext_seq(runs: list[tuple[float, str]]) -> str | None:
    """Return a MobilityDB ttext sequence string from squawk run-length data.

    runs: list of (unix_ts, squawk_code) pairs (stepwise — squawks don't interpolate).
    Returns None when runs is empty so the caller can store NULL for flights with no squawk.
    Output: '[code@ts, ...]'
    """
    if not runs:
        return None
    instants = [f'"{code}"@{_fmt_ts(ts)}' for ts, code in runs]
    return f"[{', '.join(instants)}]"


def tint_seq(values: list[int], timestamps: list[float]) -> str:
    """Return a MobilityDB tint sequence string (stepwise by type).

    values: integer values at each instant (e.g. track angles 0-359).
    timestamps: corresponding unix epoch floats, same length as values.
    Output: '[val@ts, ...]'
    """
    instants = [f"{v}@{_fmt_ts(ts)}" for v, ts in zip(values, timestamps, strict=True)]
    return f"[{', '.join(instants)}]"


def tint_from_series(series: list[tuple[float, float]]) -> str | None:
    """Return a MobilityDB tint (stepwise) sequence from (ts, value) pairs, or None if empty.

    Values are rounded to the nearest integer.
    series: list of (ts_epoch, value) pairs.
    Output: '[val@ts, ...]'
    """
    if not series:
        return None
    instants = [f"{round(v)}@{_fmt_ts(ts)}" for ts, v in series]
    return f"[{', '.join(instants)}]"


def tfloat_seq(values: list[float], timestamps: list[float]) -> str:
    """Return a MobilityDB tfloat linear-interpolation sequence string.

    values: float values at each instant.
    timestamps: corresponding unix epoch floats, same length as values.
    Output: '[val@ts, ...]'
    """
    instants = [f"{v:.4f}@{_fmt_ts(ts)}" for v, ts in zip(values, timestamps, strict=True)]
    return f"[{', '.join(instants)}]"


def tfloat_stepwise_seq(values: list[float], timestamps: list[float]) -> str | None:
    """Return a MobilityDB tfloat stepwise sequence string, or None if empty.

    values: float values at each instant (e.g. altitude corrections in feet).
    timestamps: corresponding unix epoch floats, same length as values.
    Output: 'Interp=Step;[val@ts, ...]'
    """
    if not values:
        return None
    instants = [f"{v:.4f}@{_fmt_ts(ts)}" for v, ts in zip(values, timestamps, strict=True)]
    return f"Interp=Step;[{', '.join(instants)}]"


# ---------------------------------------------------------------------------
# Seqset variants — used for all DB writes; allow explicit coverage gaps.
# ---------------------------------------------------------------------------


def tgeompoint_seqset(vertex_sequences: list[list[tuple[float, float, float, float]]]) -> str:
    """Return a MobilityDB tgeompoint_seqset string (SRID 4326, linear interpolation).

    vertex_sequences: one list of (lon, lat, alt_ft, ts_epoch) tuples per sub-sequence.
    Output: 'SRID=4326;{[POINT Z (lon lat alt)@ts, ...], [...]}'
    """
    seq_strs = []
    for verts in vertex_sequences:
        instants = [
            f"POINT Z ({lon} {lat} {alt_ft})@{_fmt_ts(ts)}" for lon, lat, alt_ft, ts in verts
        ]
        seq_strs.append(f"[{', '.join(instants)}]")
    return f"SRID=4326;{{{', '.join(seq_strs)}}}"


def ttext_seqset(runs_per_seq: list[list[tuple[float, str]]]) -> str | None:
    """Return a MobilityDB ttext_seqset string from per-sub-sequence squawk run-length data.

    Returns None when all sub-sequences are empty (no squawk data).
    Output: '{["code"@ts, ...], [...]}'
    """
    seq_strs = []
    for runs in runs_per_seq:
        if not runs:
            continue
        instants = [f'"{code}"@{_fmt_ts(ts)}' for ts, code in runs]
        seq_strs.append(f"[{', '.join(instants)}]")
    if not seq_strs:
        return None
    return f"{{{', '.join(seq_strs)}}}"


def tint_seqset(series_per_seq: list[list[tuple[float, float]]]) -> str | None:
    """Return a MobilityDB tint_seqset (stepwise) string from per-sub-sequence (ts, value) pairs.

    Values are rounded to the nearest integer. Returns None when all sub-sequences are empty.
    Output: '{[val@ts, ...], [...]}'
    """
    seq_strs = []
    for series in series_per_seq:
        if not series:
            continue
        instants = [f"{round(v)}@{_fmt_ts(ts)}" for ts, v in series]
        seq_strs.append(f"[{', '.join(instants)}]")
    if not seq_strs:
        return None
    return f"{{{', '.join(seq_strs)}}}"


def tfloat_stepwise_seqset(
    series_per_seq: list[tuple[list[float], list[float]]],
) -> str | None:
    """Return a MobilityDB tfloat stepwise seqset string, or None if all sub-sequences are empty.

    series_per_seq: list of (values, timestamps) pairs, one per sub-sequence.
    Output: 'Interp=Step;{[val@ts, ...], [...]}'
    """
    seq_strs = []
    for vals, tss in series_per_seq:
        if not vals:
            continue
        instants = [f"{v:.4f}@{_fmt_ts(ts)}" for v, ts in zip(vals, tss, strict=True)]
        seq_strs.append(f"[{', '.join(instants)}]")
    if not seq_strs:
        return None
    return f"Interp=Step;{{{', '.join(seq_strs)}}}"
