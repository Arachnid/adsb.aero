"""SQL for measuring a flight across its coverage gaps.

The splitter starts a new sub-sequence at every airborne gap longer than 60 s,
so a stored path is a sequence set with holes wherever the aircraft went
unobserved.  Measuring that directly — duration(getTime(path)), the length of
trajectory(path) — silently drops every gap, which under-reports both time and
distance for any flight with patchy coverage.

Measurements here are taken on the *stitched* path instead: the same instants
rebuilt as one continuous sequence, so each gap is bridged by a straight
segment between the last point before it and the first point after it.  The
stored path keeps its gaps — they are what the map draws — so stitching happens
only when something is measured.

Stitching must happen before any clipping: gaps introduced by clipping (the
aircraft leaving a region or altitude band) are real absences and must stay.
"""

from __future__ import annotations


def stitched_path_sql(path: str) -> str:
    """SQL for a tgeompoint expression rebuilt as one linear sequence across its gaps."""
    return f"tgeompointSeq(instants({path}))"


def stitched_tfloat_sql(series: str) -> str:
    """SQL for a tfloat expression rebuilt as one sequence, keeping its interpolation.

    Stepwise series (alt_correction_ft, path_agl_ft) carry their last value
    across a gap; linear ones interpolate across it.
    """
    return f"tfloatSeq(instants({series}), interp({series}))"


def path_length_m_sql(path: str) -> str:
    """SQL for the geodesic length in metres of a tgeompoint expression.

    ST_Force2D is required: the path's Z is altitude in feet, and the geography
    cast would otherwise fold it into the length as though it were metres.
    """
    return f"ST_Length(ST_Force2D(trajectory({path}))::geography)"


def stitched_length_m_sql(path: str) -> str:
    """SQL for the whole-flight track length in metres, gaps bridged.

    Shared by ingest and backfill-path-length so the stored path_length_m has
    one definition.
    """
    return path_length_m_sql(stitched_path_sql(path))
