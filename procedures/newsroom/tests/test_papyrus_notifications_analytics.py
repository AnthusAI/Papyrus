"""The notifications plugin's GA4 event script (PPY-5a1607), run in Node, and where the projector loads it."""

from __future__ import annotations

import json

import pytest

from papyrus_content.projection.plugins import plugin_static_files
from papyrus_content.projection.standard import notifications_pages
from procedures.newsroom.tests.notifications_js_support import HAS_NODE, analytics_preamble, run_page
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite, fixture_settings

ANALYTICS = notifications_pages.ANALYTICS_SCRIPT_PATH
STATE = "/api/notifications/state"
EMPTY = {STATE: {"status": 200, "body": {"status": "ready", "lists": []}}}


def site_with(measurement_id: str | None, environment: str = "production") -> ProjectedSite:
    settings = fixture_settings("sectioned")
    if measurement_id is not None:
        settings["chrome"] = {**settings.get("chrome", {}), "ga_measurement_id": measurement_id}
    return ProjectedSite(settings=settings, content=FIXTURES / "sectioned" / "content", plugins=("notifications",), environ={"PAPYRUS_SITE_ENV": environment})


def test_the_plugin_ships_the_event_script():
    files = plugin_static_files(("notifications",))
    assert ANALYTICS in files and b"papyrusNotificationsAnalytics" in files[ANALYTICS]


def test_only_a_site_with_a_measurement_id_loads_it_and_it_comes_first():
    with_id, without_id = site_with("G-ABC123DEF4"), site_with(None)
    try:
        for name in notifications_pages.PAGE_NAMES:
            key = notifications_pages.site_key(name)
            html = with_id.text(key)
            assert html.index(ANALYTICS) < html.index(notifications_pages.PAGES_SCRIPT_PATH), name
            assert ANALYTICS not in without_id.text(key), name
    finally:
        with_id.cleanup()
        without_id.cleanup()


@pytest.mark.skipif(not HAS_NODE, reason="node is not installed")
def test_the_event_goes_out_with_the_path_only_and_no_event_when_gtag_is_missing():
    page = ProjectedSite("sectioned", plugins=("notifications",))
    try:
        html = page.text(notifications_pages.site_key("unsubscribed"))
        body = """window.papyrusNotificationsAnalytics.track("unsubscribe", { kind: "stories", page_type: "unsubscribed" });
        console.log(JSON.stringify(gtagCalls));"""
        sent = run_page(html, "", EMPTY, body, preamble=analytics_preamble(), pathname="/notifications/unsubscribed/")
        assert sent == [["event", "unsubscribe", {"kind": "stories", "page_type": "unsubscribed", "page_location": "https://news.example.com/notifications/unsubscribed/"}]]
        body = """console.log(JSON.stringify({ sent: window.papyrusNotificationsAnalytics.track("unsubscribe", { kind: "stories" }), calls: gtagCalls }));"""
        blocked = run_page(html, "", EMPTY, body, preamble=analytics_preamble(gtag=False), pathname="/notifications/unsubscribed/")
        assert blocked == {"sent": False, "calls": []}
    finally:
        page.cleanup()


@pytest.mark.skipif(not HAS_NODE, reason="node is not installed")
def test_a_browser_without_navigation_timing_counts_the_page_as_freshly_opened():
    page = ProjectedSite("sectioned", plugins=("notifications",))
    try:
        html = page.text(notifications_pages.site_key("unsubscribed"))
        body = 'console.log(JSON.stringify(window.papyrusNotificationsAnalytics.trackLoad("unsubscribe", { kind: "all" })));'
        assert run_page(html, "", EMPTY, body, preamble=analytics_preamble(navigation=None)) is True
        assert json.dumps(run_page(html, "", EMPTY, body, preamble=analytics_preamble(navigation="reload"))) == "false"
    finally:
        page.cleanup()
