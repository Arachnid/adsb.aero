"""Identifier normalization, shared by ingestion and the query layer."""

from __future__ import annotations


def normalize_ident(value: str) -> str:
    """Normalize a callsign, registration, type designator or emitter category.

    These are all broadcast or published upper-case, and hyphens in them are
    punctuation people add rather than part of the identifier: `G-ABCD` is
    registered as such but broadcast as `GABCD`, and type designators and
    emitter categories never contain one. Stored values are normalized at
    ingestion and query values on the way in, so a lookup for `g-abcd` matches
    an aircraft stored as `GABCD`.
    """
    return value.strip().upper().replace("-", "")


def normalize_icao24(value: str) -> str:
    """Normalize an ICAO 24-bit address, which is stored as lower-case hex."""
    return value.strip().lower()
