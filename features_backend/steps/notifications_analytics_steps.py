from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.plugins import PLUGIN_ASSET_DIRECTORY  # noqa: E402
from papyrus_content.projection.standard import notifications_pages  # noqa: E402
from procedures.newsroom.tests.notifications_js_support import (  # noqa: E402
    OFFERED_TWO,
    analytics_preamble,
    run_component,
    run_page,
)
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite, fixture_settings  # noqa: E402

ANALYTICS = notifications_pages.ANALYTICS_SCRIPT_PATH
PAGES = notifications_pages.PAGES_SCRIPT_PATH
STATE = "/api/notifications/state"
SUBSCRIBE = "/api/notifications/subscribe"
MEASUREMENT_ID = "G-ABC123DEF4"
TOKEN = "tk" + "A1b2C3d4" * 5  # a long opaque token, as in a real confirm link
ORIGIN = "https://news.example.com"
EVENT_NAMES = {"subscribe_start", "subscribe_submitted", "subscribe_confirmed", "preferences_changed", "unsubscribe", "subscribe_error"}
STORIES = {STATE: {"status": 200, "body": {"status": "ready", "lists": [{"id": "stories", "name": "New stories", "description": "", "subscribed": True},
                                                                    {"id": "weekly", "name": "Weekly roundup", "description": "", "subscribed": False}]}}}
SERVICE_DOWN = {STATE: {"status": 503, "body": {"status": "unavailable"}}}
SUMMARY = 'console.log(JSON.stringify({ calls: gtagCalls, writes }));'


def project_with_measurement_id(context, *, production: bool) -> None:
    settings = fixture_settings("sectioned")
    settings["chrome"] = {**settings.get("chrome", {}), "ga_measurement_id": MEASUREMENT_ID, "consent_mode": {}}
    environ = {"PAPYRUS_SITE_ENV": "production" if production else "staging"}
    context.site = ProjectedSite(settings=settings, content=FIXTURES / "sectioned" / "content", plugins=("notifications",), environ=environ)
    context.add_cleanup(context.site.cleanup)
    context.blocked = False


def pages(context) -> dict[str, str]:
    return {name: context.site.text(notifications_pages.site_key(name)) for name in notifications_pages.PAGE_NAMES}


def script_tag_position(html: str, path: str) -> int:
    found = re.search(rf'<script src="/{re.escape(path)}(\?v=\w+)?"></script>', html)
    return found.start() if found else -1


def run_reader_page(context, name: str, search: str, replies: dict, body: str = SUMMARY, navigation: str | None = "navigate") -> dict:
    return run_page(
        context.site.text(notifications_pages.site_key(name)),
        search,
        replies,
        body,
        preamble=analytics_preamble(navigation=navigation, gtag=not getattr(context, "blocked", False)),
        pathname=notifications_pages.site_path(name),
    )


def run_subscribe_form(context, body: str, replies: dict | None = None) -> dict:
    return run_component(
        replies or {STATE: OFFERED_TWO, SUBSCRIBE: {"status": 202, "body": {"status": "check_email"}}},
        body,
        preamble=analytics_preamble(page_type="index"),
    )


def event(outcome: dict, name: str) -> dict | None:
    found = [call for call in outcome["calls"] if call[1] == name]
    return found[0][2] if found else None


def names(outcome: dict) -> list[str]:
    return [call[1] for call in outcome["calls"]]


# ---- the pages a site with and without a measurement id projects

@given("a projected site with the notifications plugin and a measurement id")
def with_id(context) -> None:
    project_with_measurement_id(context, production=True)


@given("a projected staging site with the notifications plugin and a measurement id")
def staging(context) -> None:
    project_with_measurement_id(context, production=False)


@then("no notifications page loads the analytics event script")
def no_event_script(context) -> None:
    for name, html in pages(context).items():
        assert ANALYTICS not in html, name
        assert "googletagmanager" not in html, name


@then("every notifications page loads the analytics event script before the pages script")
def event_script_first(context) -> None:
    for name, html in pages(context).items():
        first, second = script_tag_position(html, ANALYTICS), script_tag_position(html, PAGES)
        assert 0 <= first < second, name
        assert (script_tag_position(html, notifications_pages.COMPONENT_SCRIPT_PATH) > first) or name != "index", name
    assert ANALYTICS in context.site.tree


@then("the event script comes after the Consent Mode defaults")
def after_consent(context) -> None:
    for name, html in pages(context).items():
        assert 0 <= html.index("gtag('consent','default'") < script_tag_position(html, ANALYTICS), name


@then("the notifications pages have no inline script beyond the chrome's")
def no_inline(context) -> None:
    baseline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>.*?</script>", context.site.text("404.html"), re.S)
    for name, html in pages(context).items():
        assert re.findall(r"<script(?![^>]*\bsrc=)[^>]*>.*?</script>", html, re.S) == baseline, name


# ---- consent

@given("a reader who accepted analytics")
def accepted(context) -> None:
    context.consent = "accepted"


@given("a reader who declined analytics")
def declined(context) -> None:
    context.consent = "declined"


@given("analytics is blocked in the reader's browser")
def blocked(context) -> None:
    context.blocked = True


# ---- subscribing

@when('they submit the subscribe form for the weekly list placed as "{form}"')
def submit_weekly(context, form: str) -> None:
    context.outcome = run_subscribe_form(
        context,
        f"""const el = mount({{ "form-id": {json.dumps(form)} }}); await settle();
        byClass(el, "markus-notifications-toggle")[1].click();
        byClass(el, "markus-notifications-input")[0].value = "reader@example.com";
        await el.queryAll("form")[0].listeners.submit({{ preventDefault() {{}} }}); await settle();
        {SUMMARY}""",
    )


@then('subscribe_start and subscribe_submitted are sent with kind "{kind}", form "{form}" and page_type "{page_type}"')
def start_and_submitted(context, kind: str, form: str, page_type: str) -> None:
    assert names(context.outcome) == ["subscribe_start", "subscribe_submitted"], context.outcome
    for name in ("subscribe_start", "subscribe_submitted"):
        params = event(context.outcome, name)
        assert params["form"] == form and params["page_type"] == page_type and params["kind"] == kind, params


@then("no event carries an address")
def no_address(context) -> None:
    payload = json.dumps(context.outcome["calls"])
    assert "reader@example.com" not in payload and "@" not in payload


@then("the events go only through gtag, where Consent Mode makes them cookieless pings")
def only_gtag(context) -> None:
    assert context.outcome["calls"] and all(call[0] == "event" for call in context.outcome["calls"]), context.outcome


@then("nothing is written to a cookie or to browser storage")
def nothing_written(context) -> None:
    assert context.outcome["writes"] == []


@then("no event sets a client id or a user id")
def no_identifier(context) -> None:
    for call in context.outcome["calls"]:
        assert set(call[2]) <= {"kind", "form", "page_type", "page_location"}, call
        assert not {"client_id", "user_id", "user_properties"} & set(call[2]), call


@when("a reader focuses the subscribe form twice and then submits it")
def focus_twice(context) -> None:
    context.outcome = run_subscribe_form(
        context,
        f"""const el = mount({{}}); await settle();
        const form = el.queryAll("form")[0];
        form.listeners.focusin({{}}); form.listeners.focusin({{}});
        byClass(el, "markus-notifications-input")[0].value = "reader@example.com";
        await form.listeners.submit({{ preventDefault() {{}} }}); await settle();
        {SUMMARY}""",
    )


@then("subscribe_start is sent once")
def start_once(context) -> None:
    assert names(context.outcome).count("subscribe_start") == 1, context.outcome


@when("a reader submits the subscribe form and the service asks them to slow down")
def slow_down(context) -> None:
    context.outcome = run_subscribe_form(
        context,
        f"""const el = mount({{}}); await settle();
        byClass(el, "markus-notifications-toggle")[0].click();
        byClass(el, "markus-notifications-input")[0].value = "reader@example.com";
        await el.queryAll("form")[0].listeners.submit({{ preventDefault() {{}} }}); await settle();
        {SUMMARY}""",
        {STATE: OFFERED_TWO, SUBSCRIBE: {"status": 429, "body": {"status": "slow_down"}}},
    )


@then('subscribe_error is sent with form "{form}" and page_type "{page_type}"')
def error_sent(context, form: str, page_type: str) -> None:
    params = event(context.outcome, "subscribe_error")
    assert params is not None and params["form"] == form and params["page_type"] == page_type, context.outcome


@then("subscribe_submitted is not sent")
def not_submitted(context) -> None:
    assert "subscribe_submitted" not in names(context.outcome)


# ---- the pages a reader lands on

@when("a reader lands on a confirm link that carries a token, a list and a message")
def lands_on_confirm(context) -> None:
    context.outcome = run_reader_page(context, "confirmed", f"?token={TOKEN}&lists=stories&msg=thanks", STORIES)


@then('subscribe_confirmed is sent with kind "{kind}" and page_type "{page_type}"')
def confirmed_sent(context, kind: str, page_type: str) -> None:
    params = event(context.outcome, "subscribe_confirmed")
    assert params is not None and params["kind"] == kind and params["page_type"] == page_type, context.outcome


@then("the recorded page location is the page address with no query string")
def location_without_query(context) -> None:
    assert context.outcome["calls"]
    for call in context.outcome["calls"]:
        assert call[2]["page_location"] == f"{ORIGIN}/notifications/confirmed/", call


@then("no parameter of any event contains the token")
def no_token(context) -> None:
    assert TOKEN not in json.dumps(context.outcome["calls"]) and "token" not in json.dumps(context.outcome["calls"])


@when("the confirmed page is reloaded")
def reloaded(context) -> None:
    context.outcome = run_reader_page(context, "confirmed", f"?token={TOKEN}&lists=stories", STORIES, navigation="reload")


@when("the confirmed page is reached with the back button")
def back_button(context) -> None:
    context.outcome = run_reader_page(context, "confirmed", f"?token={TOKEN}&lists=stories", STORIES, navigation="back_forward")


@then("subscribe_confirmed is not sent a second time")
def not_again(context) -> None:
    assert "subscribe_confirmed" not in names(context.outcome), context.outcome


@when("a reader saves their choices and lands on the manage page")
def saved(context) -> None:
    context.outcome = run_reader_page(context, "preferences", f"?token={TOKEN}&msg=saved", STORIES)


@then('preferences_changed is sent with kind "{kind}" and page_type "{page_type}"')
def preferences_sent(context, kind: str, page_type: str) -> None:
    params = event(context.outcome, "preferences_changed")
    assert params is not None and params["kind"] == kind and params["page_type"] == page_type, context.outcome


@when("a reader lands on the unsubscribed page")
def lands_unsubscribed(context) -> None:
    context.outcome = run_reader_page(
        context,
        "unsubscribed",
        f"?token={TOKEN}&lists=stories",
        {STATE: {"status": 200, "body": {"status": "ready", "lists": [{"id": "stories", "name": "New stories", "description": ""}]}}},
        """console.log(JSON.stringify({ calls: gtagCalls, writes, summary: visible("[data-notifications-summary]"),
          named: text("div[data-notifications-lists] li"), manage: visible("p[data-notifications-manage]") }));""",
    )


@then('unsubscribe is sent with kind "{kind}" and page_type "{page_type}"')
def unsubscribe_sent(context, kind: str, page_type: str) -> None:
    params = event(context.outcome, "unsubscribe")
    assert params is not None and params["kind"] == kind and params["page_type"] == page_type, context.outcome


@when("a reader lands on the manage page after unsubscribing from everything")
def unsubscribed_from_everything(context) -> None:
    context.outcome = run_reader_page(context, "preferences", f"?token={TOKEN}&msg=unsubscribed", STORIES)


@then("the page still names what they unsubscribed from and offers the manage link")
def page_works(context) -> None:
    assert context.outcome["summary"] is True and context.outcome["named"] == "New stories" and context.outcome["manage"] is True, context.outcome


@then("no analytics event is sent")
def none_sent(context) -> None:
    assert context.outcome["calls"] == [] and context.outcome["writes"] == []


@when("a reader opens a manage link while the service answers that notifications are not available")
def service_down(context) -> None:
    context.outcome = run_reader_page(context, "preferences", f"?token={TOKEN}", SERVICE_DOWN)


@then('subscribe_error is sent with page_type "{page_type}"')
def error_on_page(context, page_type: str) -> None:
    params = event(context.outcome, "subscribe_error")
    assert params is not None and params["page_type"] == page_type, context.outcome


# ---- what can be sent at all

@when("the page asks to send an event that is not one of the six, and one of them with an address, a token and an extra parameter")
def asks_for_too_much(context) -> None:
    context.outcome = run_reader_page(
        context,
        "unsubscribed",
        "",
        STORIES,
        f"""const a = window.papyrusNotificationsAnalytics;
        a.track("page_view", {{ kind: "stories" }});
        a.track("issue_open", {{ kind: "stories" }});
        a.track("subscribe_submitted", {{ kind: "stories", form: "footer", page_type: "subscribe", email: "reader@example.com",
          token: {json.dumps(TOKEN)}, user_id: "u1", page_location: "https://elsewhere.example/?t=1" }});
        a.track("subscribe_error", {{ kind: "reader@example.com", form: {json.dumps(TOKEN)}, page_type: "somewhere" }});
        {SUMMARY}""",
    )


@then("only the allowed event is sent and only with its allowed parameters")
def only_allowed(context) -> None:
    calls = context.outcome["calls"]
    assert [call[1] for call in calls] == ["subscribe_submitted", "subscribe_error"], calls
    assert calls[0][2] == {"kind": "stories", "form": "footer", "page_type": "subscribe", "page_location": f"{ORIGIN}/notifications/unsubscribed/"}, calls[0]
    assert calls[1][2] == {"page_location": f"{ORIGIN}/notifications/unsubscribed/"}, "an address, a token and an unknown page type are all dropped"
    assert {call[1] for call in calls} <= EVENT_NAMES


@then("the notifications scripts contain no issue_open event and no tracking pixel")
def no_issue_open(context) -> None:
    for filename in ("papyrus-notifications-analytics.js", "papyrus-notifications-pages.js", "papyrus-notifications.js"):
        source = (PLUGIN_ASSET_DIRECTORY / filename).read_text(encoding="utf-8")
        assert "issue_open" not in source and "new Image" not in source and "sendBeacon" not in source and "<img" not in source, filename
