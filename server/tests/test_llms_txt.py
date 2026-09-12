"""Guard `web/public/llms.txt` against drifting from the real API.

`llms.txt` is the entry point agents read instead of the OpenAPI schema, so a
stale vocabulary there produces confidently-wrong requests rather than an
obvious error. The prose is hand-written; these tests only check that the
machine-checkable facts in it still match the code.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest

from adsb_server.api.main import app
from adsb_server.query.models import Predicate

LLMS_TXT = Path(__file__).resolve().parents[2] / "web" / "public" / "llms.txt"


@pytest.fixture(scope="module")
def llms_text() -> str:
    return LLMS_TXT.read_text(encoding="utf-8")


def _predicate_keys() -> set[str]:
    """The JSON key naming each predicate, as the DSL accepts it."""
    keys: set[str] = set()
    for model in get_args(Predicate):
        for field_name, field in model.model_fields.items():
            keys.add(field.alias or field_name)
    return keys


def test_llms_txt_exists() -> None:
    assert LLMS_TXT.is_file(), f"{LLMS_TXT} is missing"


def test_every_predicate_is_documented(llms_text: str) -> None:
    """Each predicate key appears in llms.txt as `key` or "key"."""
    missing = sorted(
        key for key in _predicate_keys() if not re.search(rf'[`"]{re.escape(key)}[`"]', llms_text)
    )
    assert not missing, (
        f"Predicates missing from web/public/llms.txt: {missing}. "
        "Add them (with their fields and a worked example) so agents can use them."
    )


def test_no_undocumented_predicate_names(llms_text: str) -> None:
    """llms.txt must not advertise predicates the API doesn't implement.

    Catches the failure that bit docs/design-spec.md, which still documented
    `callsign_matches` long after the code shipped `callsign_prefix`.
    """
    known = _predicate_keys()
    # Predicate-shaped backticked identifiers: snake_case, no spaces.
    candidates = set(re.findall(r"`([a-z][a-z0-9_]{3,})`", llms_text))
    suspicious = {
        name
        for name in candidates
        if name.endswith(("_within", "_intersects", "_matches", "_prefix")) and name not in known
    }
    assert not suspicious, f"llms.txt names predicates that do not exist: {sorted(suspicious)}"


def test_every_route_is_documented(llms_text: str) -> None:
    """Each public API path appears in llms.txt."""
    missing = []
    for path in app.openapi()["paths"]:
        # Strip the version prefix and any path parameter braces; the doc writes
        # paths relative to the documented base URL.
        doc_path = path.removeprefix("/api/v1")
        stem = doc_path.split("{")[0].rstrip("/")
        if stem and stem not in llms_text:
            missing.append(path)
    assert not missing, f"API paths missing from web/public/llms.txt: {missing}"


def test_documents_the_window_days_cap(llms_text: str) -> None:
    """The 7-day cap silently truncates results, so it must be stated."""
    from adsb_server.query.models import QueryRequest

    cap = QueryRequest.model_fields["window_days"].metadata
    le_values = [getattr(m, "le", None) for m in cap]
    max_days = next(v for v in le_values if v is not None)
    assert str(max_days) in llms_text, f"llms.txt must state the window_days maximum ({max_days})"


def test_documents_the_geometry_cell_cap(llms_text: str) -> None:
    """An undocumented cap reads as an arbitrary refusal mid-task, so state the number."""
    from adsb_server.query.compiler import MAX_QUERY_H3_CELLS

    assert str(MAX_QUERY_H3_CELLS) in llms_text, (
        f"llms.txt must state the geometry cell cap ({MAX_QUERY_H3_CELLS}) "
        "and how to work around it."
    )


def test_aerodrome_airspace_types_are_documented(llms_text: str) -> None:
    """The airspace types /airports/{code} can return are named in the doc."""
    from adsb_server.query.models import AERODROME_AIRSPACE_TYPES

    missing = [n for n in AERODROME_AIRSPACE_TYPES.values() if n not in llms_text]
    assert not missing, f"Airspace types missing from llms.txt: {missing}"
