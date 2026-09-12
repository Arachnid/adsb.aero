"""Identifier normalization, shared by ingestion and the query layer."""

from __future__ import annotations


def normalize_ident(value: str) -> str:
    """Normalize a callsign, registration, type designator or emitter category.

    These are published upper-case, and hyphens in them are punctuation rather
    than part of the identifier: `G-ABCD` is registered as such but broadcast as
    `GABCD`, and type designators and emitter categories never contain one.

    Stored values keep the spelling they were published with; a query value is
    normalized here and compared against the same normalization of the column,
    which migration 0006 indexes (see compiler._norm). So `g-abcd` matches an
    aircraft registered `G-ABCD` and one broadcasting `GABCD` alike.
    """
    return value.strip().upper().replace("-", "")


def normalize_icao24(value: str) -> str:
    """Normalize an ICAO 24-bit address, which is stored as lower-case hex."""
    return value.strip().lower()
