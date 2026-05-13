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
        f"POINT Z ({lon} {lat} {alt_ft})@{_fmt_ts(ts)}"
        for lon, lat, alt_ft, ts in vertices
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


def tfloat_stepwise_seq(values: list[float], timestamps: list[float]) -> str | None:
    """Return a MobilityDB tfloat stepwise sequence string, or None if empty.

    values: float values at each instant (e.g. altitude corrections in feet).
    timestamps: corresponding unix epoch floats, same length as values.
    Output: 'Interp=Step;[val@ts, ...]'
    """
    if not values:
        return None
    instants = [
        f"{v:.4f}@{_fmt_ts(ts)}"
        for v, ts in zip(values, timestamps, strict=True)
    ]
    return f"Interp=Step;[{', '.join(instants)}]"
