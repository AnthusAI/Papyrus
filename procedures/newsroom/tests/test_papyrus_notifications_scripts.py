"""The notifications plugin's page script and <papyrus-notifications> component, run in Node against the real projected markup."""

from __future__ import annotations

import json
import unittest

import pytest

from procedures.newsroom.tests.notifications_js_support import CONSENT, HAS_NODE, OFFERED_ONE, OFFERED_TWO, run_component, run_page
from procedures.newsroom.tests.standard_frontend_support import ProjectedSite

pytestmark = pytest.mark.skipif(not HAS_NODE, reason="node is not installed")

TOKEN = "tok.en_1-2"
STATE = "/api/notifications/state"
PREFERENCES = {
    "status": 200,
    "body": {
        "status": "ready",
        "email": "reader@example.com",
        "lists": [
            {"id": "stories", "name": "New stories", "description": "Each new story as it is published.", "subscribed": True},
            {"id": "weekly", "name": "Weekly roundup", "description": "", "subscribed": False},
        ],
    },
}


@pytest.fixture(scope="module")
def site():
    projected = ProjectedSite("sectioned", plugins=("notifications",))
    yield projected
    projected.cleanup()


def page(site, name):
    return site.text("notifications/index.html" if name == "index" else f"notifications/{name}/index.html")


def test_preferences_show_each_list_as_a_button_that_says_on_or_off(site):
    result = run_page(
        page(site, "preferences"), f"?token={TOKEN}", {STATE: PREFERENCES},
        """console.log(JSON.stringify({
          manage: visible("[data-notifications-section=manage]"), form: visible("form"), token: $("form").elements.t.value,
          intro: text("[data-notifications-email]"),
          rows: $("form").queryAll("button.markus-notifications-toggle").map((b) => [b.queryAll(".markus-notifications-name")[0].textContent, b.queryAll(".markus-notifications-state")[0].textContent, b.getAttribute("aria-pressed")]),
          icons: $("form").queryAll("button.markus-notifications-toggle").map((b) => /data-icon="([a-z-]+)"/.exec(b.queryAll(".markus-notifications-mark")[0].innerHTML)[1]),
          request: requests[0].url,
        }));""",
    )
    assert result["manage"] and result["form"] and result["token"] == TOKEN
    assert "reader@example.com" in result["intro"]
    assert result["rows"] == [["New stories", "On", "true"], ["Weekly roundup", "Off", "false"]]
    assert result["icons"] == ["bell", "bell-off"], "state is a mark as well as a word"
    assert result["request"] == f"{STATE}?kind=preferences&t={TOKEN}"


def test_turning_a_list_off_changes_the_word_the_mark_and_what_the_form_sends(site):
    result = run_page(
        page(site, "preferences"), f"?token={TOKEN}", {STATE: PREFERENCES},
        """const toggle = $("form").queryAll("button.markus-notifications-toggle")[0];
        toggle.click();
        const fields = $("form").queryAll("input").filter((i) => i.name === "l");
        console.log(JSON.stringify({ word: toggle.queryAll(".markus-notifications-state")[0].textContent, pressed: toggle.getAttribute("aria-pressed"),
          icon: /data-icon="([a-z-]+)"/.exec(toggle.queryAll(".markus-notifications-mark")[0].innerHTML)[1], sent: fields.filter((f) => !f.disabled).map((f) => f.value) }));""",
    )
    assert result == {"word": "Off", "pressed": "false", "icon": "bell-off", "sent": []}


def test_after_saving_the_page_confirms_in_words_what_the_reader_gets(site):
    off = json.loads(json.dumps(PREFERENCES))
    off["body"]["lists"][0]["subscribed"] = False
    result = run_page(
        page(site, "preferences"), f"?token={TOKEN}&msg=saved", {STATE: off},
        """console.log(JSON.stringify({ shown: visible("[data-notifications-notice]"), notice: text("[data-notifications-notice] span") }));""",
    )
    assert result["shown"]
    assert result["notice"] == "Your choices are saved. You get nothing."
    with_one = run_page(
        page(site, "preferences"), f"?token={TOKEN}&msg=saved", {STATE: PREFERENCES},
        """console.log(JSON.stringify({ notice: text("[data-notifications-notice] span") }));""",
    )
    assert with_one["notice"] == "Your choices are saved. You get: New stories. You do not get: Weekly roundup."


def test_the_delete_step_shows_the_confirmation_not_the_form(site):
    result = run_page(
        page(site, "preferences"), f"?token={TOKEN}&step=delete", {STATE: PREFERENCES},
        """console.log(JSON.stringify({ confirm: visible("[data-notifications-section=delete]"), manage: visible("[data-notifications-section=manage]"),
          back: $("[data-notifications-back]").href, token: $("[data-notifications-section=delete] form").elements.t.value }));""",
    )
    assert result["confirm"] and not result["manage"]
    assert result["back"] == f"/notifications/preferences/?token={TOKEN}" and result["token"] == TOKEN


def test_a_no_good_link_goes_to_the_expired_page_never_to_an_api_address(site):
    for name, search, reply in [
        ("preferences", "", PREFERENCES),
        ("preferences", "?token=bad%20token", PREFERENCES),
        ("preferences", f"?token={TOKEN}", {"status": 400, "body": {"status": "invalid"}}),
        ("confirm", f"?token={TOKEN}", {"status": 400, "body": {"status": "invalid"}}),
        ("unsubscribe", "", PREFERENCES),
    ]:
        result = run_page(page(site, name), search, {STATE: reply}, "console.log(JSON.stringify({ replaced }));")
        assert result["replaced"] == "/notifications/expired/", (name, search)


def test_a_service_that_cannot_be_reached_is_said_in_words_not_called_expired(site):
    for reply in [{"status": 503, "body": {"status": "unavailable"}}, {"status": 502, "body": {"status": "unavailable"}}, {"reject": True}]:
        result = run_page(
            page(site, "preferences"), f"?token={TOKEN}", {STATE: reply},
            """console.log(JSON.stringify({ replaced, words: visible("[data-notifications-unavailable]"), form: visible("form") }));""",
        )
        assert result == {"replaced": None, "words": True, "form": False}, reply


def test_the_confirm_page_names_the_lists_and_unhides_its_form(site):
    reply = {"status": 200, "body": {"status": "ready", "lists": [{"name": "New stories"}]}}
    result = run_page(
        page(site, "confirm"), f"?token={TOKEN}", {STATE: reply},
        """console.log(JSON.stringify({ form: visible("form"), token: $("form").elements.t.value, lists: $("div[data-notifications-lists] ul").children.map((li) => li.textContent) }));""",
    )
    assert result == {"form": True, "token": TOKEN, "lists": ["New stories"]}


def test_the_confirmed_page_links_to_manage_and_reports_one_sign_up(site):
    reply = {"status": 200, "body": {"status": "ready", "lists": [{"id": "stories", "name": "New stories"}]}}
    result = run_page(
        page(site, "confirmed"), f"?token={TOKEN}&lists=stories", {STATE: reply},
        """console.log(JSON.stringify({ manage: visible("p[data-notifications-manage]"), href: $("p[data-notifications-manage] a").href,
          lists: $("div[data-notifications-lists] ul").children.map((li) => li.textContent), tracked }));""",
    )
    assert result["manage"] and result["href"] == f"/notifications/preferences/?token={TOKEN}"
    assert result["lists"] == ["New stories"]
    assert result["tracked"] == [["sign_up", {"method": "notifications"}]]


def test_the_unsubscribe_page_can_name_one_list(site):
    reply = {"status": 200, "body": {"status": "ready", "lists": [{"id": "stories", "name": "New stories"}]}}
    result = run_page(
        page(site, "unsubscribe"), f"?token={TOKEN}&list=stories", {STATE: reply},
        """console.log(JSON.stringify({ prompt: text("[data-notifications-prompt]"), label: $("form button span").textContent, list: $("form").elements.l.value, form: visible("form") }));""",
    )
    assert result["prompt"].startswith("Stop getting “New stories” from ")
    assert result["label"] == "Unsubscribe from this one" and result["list"] == "stories" and result["form"]


def submit(attributes, replies, email="reader@example.com", before=""):
    return run_component(
        replies,
        f"""const el = mount({json.dumps(attributes)});
        await settle();
        const input = byClass(el, "markus-notifications-input")[0];
        input.value = {json.dumps(email)};
        {before}
        await el.queryAll("form")[0].listeners.submit({{ preventDefault() {{}} }});
        await settle();
        const status = byClass(el, "markus-notifications-status")[0];
        console.log(JSON.stringify({{ posts: requests.filter((r) => r.method === "POST").map((r) => [r.url, r.body]), reads: requests.filter((r) => r.method === "GET").map((r) => r.url),
          status: status.textContent, state: status.attrs["data-state"] || null, icon: (/data-icon="([a-z-]+)"/.exec(status.innerHTML) || [])[1] || null, events: el.events }}));""",
    )


ACCEPTED = {"status": 202, "body": {"status": "check_email"}}


def test_subscribing_with_one_list_says_to_check_email_and_posts_the_sites_consent_and_page():
    result = submit({"consent": "An attribute is ignored."}, {STATE: OFFERED_ONE, "/api/notifications/subscribe": ACCEPTED})
    assert result["reads"] == [f"{STATE}?kind=offered"]
    url, body = result["posts"][0]
    assert url == "/api/notifications/subscribe"
    assert body["lists"] == ["stories"] and body["email"] == "reader@example.com" and body["consent"] == CONSENT
    assert body["page"] == "https://news.example.com/notifications/" and body["website"] == "" and body["formId"] == "notifications"
    assert "renderedAt" not in body
    assert result["status"] == "Check your email to confirm your subscription."
    assert result["state"] == "check_email" and result["icon"] == "circle-check"
    assert result["events"] == [{"status": "check_email"}]


def test_several_lists_start_off_need_a_choice_and_post_the_chosen_ones():
    replies = {STATE: OFFERED_TWO, "/api/notifications/subscribe": ACCEPTED}
    none = submit({}, replies)
    assert none["posts"] == [] and none["status"] == "Choose at least one thing to get."
    chosen = submit({}, replies, before='byClass(el, "markus-notifications-toggle")[1].click();')
    assert chosen["posts"][0][1]["lists"] == ["weekly"]
    start = run_component(
        replies,
        """const el = mount({}); await settle();
        console.log(JSON.stringify(byClass(el, "markus-notifications-toggle").map((b) => [b.queryAll(".markus-notifications-state")[0].textContent, b.getAttribute("aria-pressed")])));""",
    )
    assert start == [["Off", "false"], ["Off", "false"]], "nothing is pre-chosen"


def test_a_bad_address_is_refused_without_a_request():
    result = submit({}, {STATE: OFFERED_ONE}, email="nope")
    assert result["posts"] == [] and result["status"] == "Please enter a valid email address." and result["icon"] == "triangle-alert"


def test_an_unreachable_service_is_said_in_words():
    for reply in [{"status": 503, "body": {"status": "unavailable"}}, {"status": 502, "body": {"error": "x"}}]:
        result = submit({}, {STATE: OFFERED_ONE, "/api/notifications/subscribe": reply})
        assert result["status"] == "Notifications are not available right now. Please try again later.", reply
    odd = submit({}, {STATE: OFFERED_ONE, "/api/notifications/subscribe": {"status": 200, "broken": True}})
    assert odd["status"] == "Something went wrong. Please try again later."


def test_the_form_shows_exactly_the_sites_consent_wording():
    shown = run_component(
        {STATE: OFFERED_ONE},
        'const el = mount({}); await settle(); console.log(JSON.stringify(byClass(el, "markus-notifications-consent")[0].textContent));',
    )
    assert shown == CONSENT


def test_a_site_without_consent_wording_says_the_form_is_not_set_up():
    no_consent = {"status": 200, "body": {"status": "ready", "lists": OFFERED_ONE["body"]["lists"]}}
    result = submit({}, {STATE: no_consent})
    assert result["posts"] == [] and result["status"] == "This form is not set up."


def test_a_network_limit_and_an_outdated_form_are_said_in_words():
    slow = submit({}, {STATE: OFFERED_ONE, "/api/notifications/subscribe": {"status": 429, "body": {"status": "slow_down"}}})
    assert slow["status"] == "Too many signups from your network just now. Please try again later." and slow["icon"] == "triangle-alert"
    stale = submit({}, {STATE: OFFERED_ONE, "/api/notifications/subscribe": {"status": 400, "body": {"status": "invalid_consent"}}})
    assert stale["status"] == "This form is out of date. Please reload the page and try again."


def test_a_site_that_offers_no_lists_says_the_form_is_not_set_up():
    result = submit({}, {STATE: {"status": 200, "body": {"status": "ready", "lists": []}}})
    assert result["posts"] == [] and result["status"] == "This form is not set up."


def test_the_honeypot_is_hidden_with_the_style_object_not_an_attribute():
    result = run_component(
        {STATE: OFFERED_ONE},
        'const el = mount({}); const trap = byClass(el, "markus-notifications-trap")[0]; console.log(JSON.stringify({ attribute: trap.attrs.style || null, style: trap.style }));',
    )
    assert result["attribute"] is None and result["style"]["left"] == "-10000px"
