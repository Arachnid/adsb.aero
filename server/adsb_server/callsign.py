"""Callsign normalization, shared by ingestion and the query layer."""

from __future__ import annotations


def normalize_callsign(value: str) -> str:
    """Normalize a callsign (or callsign prefix) to its stored form.

    Callsigns are broadcast upper-case and without punctuation, but neither the
    feed nor the people typing queries are consistent about it. Stored callsigns
    are normalized at ingestion and query prefixes on the way in, so a lookup
    for `g-abcd` matches a flight that broadcast `GABCD`.
    """
    return value.strip().upper().replace("-", "")
