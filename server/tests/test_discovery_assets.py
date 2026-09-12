"""Guard the discovery routes an agent finds when handed only the domain.

These assert on static assets — the landing page and the nginx config — rather
than on the running app, so they need neither a database nor an event loop.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX_HTML = REPO_ROOT / "web" / "index.html"
NGINX_PROD_CONF = REPO_ROOT / "infra" / "nginx" / "prod.conf.template"

DISCOVERY_TARGETS = ("/llms.txt", "/api/docs", "/api/openapi.json")


def test_discovery_links_survive_head_and_noscript_being_dropped() -> None:
    """The links must appear in ordinary body markup, not only <head>/<noscript>.

    An agent handed just the domain arrives through an HTML-to-markdown fetcher,
    and those routinely render <body> while discarding both <head> and
    <noscript>. With the links confined to those two places, such a tool saw a
    page with nothing to follow — on a site built specifically to have somewhere
    to go.
    """
    html = INDEX_HTML.read_text(encoding="utf-8")
    body = html.split("<body>", 1)[1]
    # Drop <noscript> content so we assert on what a converter actually keeps.
    kept = re.sub(r"<noscript>.*?</noscript>", "", body, flags=re.S)
    for target in DISCOVERY_TARGETS:
        assert f'href="{target}"' in kept, f"{target} unreachable from plain body markup"


def test_discovery_fallback_is_inside_the_react_root() -> None:
    """It has to be markup React clears on mount, or it would double the UI."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert '<div id="root"></div>' not in html, "fallback content should live inside #root"
    root = html.split('<div id="root">', 1)[1]
    # The same hrefs appear in <head> as <link rel> hints, so search after #root.
    for target in DISCOVERY_TARGETS:
        assert f'href="{target}"' in root, f"{target} should be inside #root, not only in <head>"


def test_discovery_links_are_also_response_headers() -> None:
    """Headers are the one discovery channel an HTML transform cannot drop."""
    conf = NGINX_PROD_CONF.read_text(encoding="utf-8")
    link_headers = [line for line in conf.splitlines() if "add_header Link" in line]
    assert link_headers, "prod nginx config should advertise the API via Link headers"
    advertised = "\n".join(link_headers)
    for target in DISCOVERY_TARGETS:
        assert target in advertised, f"{target} missing from the Link header"
