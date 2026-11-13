from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

from behave import given, then, when

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "src", ROOT / "procedures" / "newsroom" / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from papyrus_content.markus_renderer.consent import ConsentModeSettings  # noqa: E402
from papyrus_content.markus_renderer.shell import NavItem, SiteChrome, render_page  # noqa: E402
from test_markus_renderer_consent_region_lookup import (  # noqa: E402
    MEASUREMENT_ID,
    consent_updates,
    render,
    visit,
)

DENIED = {"ad_storage": "denied", "ad_user_data": "denied", "ad_personalization": "denied", "analytics_storage": "denied"}


@given("a page built with region-aware consent")
def region_aware_page(context) -> None:
    context.page = render(region_lookup=True)
    context.state = {"fetch": "hang"}


@given("a guarded page built with region-aware consent")
def guarded_page(context) -> None:
    chrome = SiteChrome(site_name="S", ga_measurement_id=MEASUREMENT_ID, consent_mode=ConsentModeSettings(region_lookup=True))
    guarded = dataclasses.replace(chrome, ga_measurement_id=None, ga_owner_opt_out=False, consent_mode=None)
    context.page = render_page(
        title="S", fragment="<p>x</p>", active_href="index.html", nav_items=[NavItem("Home", "index.html")], chrome=guarded
    )


def _result(context) -> dict:
    if not hasattr(context, "result"):
        context.result = visit(context.page, **context.state)
    return context.result


@then("the page never asks where the visitor is")
def never_asks(context) -> None:
    for fragment in ("fetch(", "_papyrus/consent", "needsNotice"):
        assert fragment not in context.page, fragment


@then("the notice shows to a new visitor")
def notice_shows(context) -> None:
    assert "if(!c.read())b.hidden=false" in context.page and "c.lookup" not in context.page


@when('the edge answers country "{country}" with notice required')
def answers_notice(context, country: str) -> None:
    context.state = {"answer": {"country": country, "notice": True}}


@when('the edge answers country "{country}" with no notice required')
def answers_no_notice(context, country: str) -> None:
    context.state = {"answer": {"country": country, "notice": False}}


@when("the edge answers an unknown country")
def answers_unknown(context) -> None:
    context.state = {"answer": {"country": "", "notice": False}}


@when("the edge does not answer within the time limit")
def times_out(context) -> None:
    context.state = {"fetch": "hang"}


@when("the edge answers with something malformed")
def answers_malformed(context) -> None:
    context.state = {"fetch": "malformed"}


@when("the request to the edge fails")
def request_fails(context) -> None:
    context.state = {"fetch": "fail"}


@when("the edge has not answered yet")
def not_answered(context) -> None:
    context.state = {"fetch": "hang"}


@when("a visitor who rejected cookies earlier returns")
def returns_after_reject(context) -> None:
    now = 1_700_000_000_000
    stored = json.dumps({"version": 1, "savedAt": now, "granted": False})
    context.state = {"storage": {"anthus-consent": stored}, "now": now + 1000, "answer": {"country": "US", "notice": False}}


@then("the banner is shown")
def banner_shown(context) -> None:
    assert _result(context)["bannerShownAfter"] is True


@then("the banner is not shown")
def banner_not_shown(context) -> None:
    assert _result(context)["bannerShownAfter"] is False


@then("the banner is not shown yet")
def banner_not_shown_yet(context) -> None:
    assert _result(context)["bannerShownBefore"] is False


@then("analytics stay denied until the visitor chooses")
def analytics_denied(context) -> None:
    result = _result(context)
    assert consent_updates(result["commandsAfter"]) == []
    assert result["commandsBefore"][0][2]["analytics_storage"] == "denied"


@then("analytics storage is granted")
def analytics_granted(context) -> None:
    assert {"analytics_storage": "granted"} in consent_updates(_result(context)["commandsAfter"])


@then("advertising storage stays denied until the visitor accepts")
def ads_denied(context) -> None:
    result = _result(context)
    default = result["commandsBefore"][0][2]
    assert {default[k] for k in ("ad_storage", "ad_user_data", "ad_personalization")} == {"denied"}
    for update in consent_updates(result["commandsAfter"]):
        assert not any(key.startswith("ad_") for key in update), update


@then("the page does not ask the edge anything")
def asks_nothing(context) -> None:
    assert _result(context)["fetchCalls"] == []


@then("the stored rejection is applied")
def rejection_applied(context) -> None:
    assert consent_updates(_result(context)["commandsAfter"]) == [DENIED]


@then("every consent signal is denied")
def all_denied(context) -> None:
    default = _result(context)["commandsBefore"][0]
    assert default[:2] == ["consent", "default"] and set(default[2].values()) >= {"denied"}
    assert {default[2][k] for k in DENIED} == {"denied"}


@then("the analytics configuration has already been issued")
def config_issued(context) -> None:
    assert _result(context)["commandsBefore"][-1][0] == "config"


@then("the country is not stored")
def country_not_stored(context) -> None:
    assert "US" not in json.dumps(_result(context)["storage"])


@then("the country is not in any analytics command")
def country_not_in_commands(context) -> None:
    assert "US" not in json.dumps(_result(context)["commandsAfter"])


@then("the only request is to the site's own consent address")
def only_own_address(context) -> None:
    calls = _result(context)["fetchCalls"]
    assert [c["url"] for c in calls] == ["/_papyrus/consent"], calls
