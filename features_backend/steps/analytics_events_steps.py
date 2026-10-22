from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "src", ROOT / "procedures" / "newsroom" / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from papyrus_content.markus_renderer.consent import ConsentModeSettings  # noqa: E402
from papyrus_content.markus_renderer.docs_site import DocsSiteConfig, build_docs_site  # noqa: E402
from test_markus_docs_site import write_documentation_tree  # noqa: E402
from test_markus_renderer_analytics_events import MEASUREMENT_ID, render, run_events  # noqa: E402


def _outcome(context) -> dict:
    return run_events(**context.visit)


@given("a page built without a measurement id")
def page_without_id(context) -> None:
    context.page = render()


@given("a page built with a measurement id and consent mode")
def page_with_id(context) -> None:
    context.page = render(ga_measurement_id=MEASUREMENT_ID, consent_mode=ConsentModeSettings())
    context.visit = {"clicks": [], "calls": []}


@then("the page mentions no gtag, no data layer and no analytics script")
def no_analytics(context) -> None:
    for fragment in ("gtag", "dataLayer", "papyrusAnalytics", "googletagmanager"):
        assert fragment not in context.page, fragment


@then("the consent defaults come before the analytics loader")
def defaults_first(context) -> None:
    assert context.page.index("consent','default'") < context.page.index("googletagmanager.com/gtag/js")


@then("the location redaction comes before the analytics loader")
def redaction_first(context) -> None:
    assert context.page.index("page_location") < context.page.index("googletagmanager.com/gtag/js")


@when('a visitor opens "{url}"')
def visitor_opens(context, url: str) -> None:
    context.visit["url"] = url


@then('the recorded page location is "{expected}"')
def recorded_location(context, expected: str) -> None:
    assert _outcome(context)["setCommand"][1]["page_location"] == expected


@when('a visitor clicks the link "{text}" marked "{location}" to "{href}"')
def visitor_clicks(context, text: str, location: str, href: str) -> None:
    context.visit["clicks"].append({"href": href, "text": text, "location": location})


@when('a visitor clicks the link "{text}" marked "{location}" to "{href}" inside a sponsor unit')
def visitor_clicks_sponsor(context, text: str, location: str, href: str) -> None:
    context.visit["clicks"].append({"href": href, "text": text, "location": location, "sponsor": True})


@then('the event "{name}" is sent with link_url "{link_url}" and cta_location "{location}"')
def event_sent(context, name: str, link_url: str, location: str) -> None:
    events = _outcome(context)["events"]
    assert len(events) == 1 and events[0][1] == name, events
    assert events[0][2]["link_url"] == link_url and events[0][2]["cta_location"] == location, events


@then("no event is sent")
def no_event(context) -> None:
    assert _outcome(context)["events"] == []


@when('the page reports "{name}" with method "{method}" and a user_id')
def reports_with_user_id(context, name: str, method: str) -> None:
    context.visit["calls"].append([name, {"method": method, "user_id": "u-1"}])


@when('the page reports "{name}" with no parameters')
def reports_bare(context, name: str) -> None:
    context.visit["calls"].append([name, {"a": 1}])


@then('exactly these events were sent: "{names}"')
def exactly_events(context, names: str) -> None:
    sent = [event[1] for event in _outcome(context)["events"]]
    assert sent == names.split(","), sent


@then("no event carries a user_id")
def no_user_id(context) -> None:
    assert "user_id" not in json.dumps(_outcome(context)["events"])


def _docs_page(**config: object) -> str:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        write_documentation_tree(root / "docs")
        build_docs_site(DocsSiteConfig("Demo", "tag", root / "docs", "https://x", **config), root / "out")
        return (root / "out" / "index.html").read_text(encoding="utf-8")


@given('a documentation site built with the measurement id "{identifier}"')
def docs_with_id(context, identifier: str) -> None:
    assert shutil.which("markus"), "the markus executable is required"
    context.with_id = _docs_page(ga_measurement_id=identifier)
    context.without_id = _docs_page()


@then("its pages carry the consent banner, the cookie settings link and a privacy link")
def docs_have_banner(context) -> None:
    assert 'id="papyrus-consent-banner"' in context.with_id
    assert "data-papyrus-consent-reopen" in context.with_id
    assert 'href="https://anth.us/privacy/"' in context.with_id


@then("a documentation site built without one carries none of them")
def docs_without(context) -> None:
    for fragment in ("papyrus-consent-banner", "data-papyrus-consent-reopen", "gtag"):
        assert fragment not in context.without_id, fragment


@then('the consent script reopens the choices from links to "{href}"')
def reopen_link(context, href: str) -> None:
    assert f'a[href="{href}"]' in context.page


@given("a page built with a measurement id and analytics-only consent")
def page_analytics_only(context) -> None:
    context.settings = ConsentModeSettings(analytics_only=True)
    context.page = render(ga_measurement_id=MEASUREMENT_ID, consent_mode=context.settings)


@then("accepting grants only analytics storage")
def accept_analytics_only(context) -> None:
    assert "ad_storage:'denied',ad_user_data:'denied',ad_personalization:'denied',analytics_storage:v" in context.page
    assert "ad_storage:v" not in context.page


@then("rejecting denies every signal")
def reject_denies(context) -> None:
    assert "var v=granted?'granted':'denied'" in context.page


@then("the banner text does not offer advertising")
def no_advertising_text(context) -> None:
    assert "for advertising" not in context.settings.banner_message or "do not use them for advertising" in context.settings.banner_message
    assert "if you agree, for advertising" not in context.settings.banner_message
