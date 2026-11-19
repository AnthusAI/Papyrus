"""Subscription preferences (features_backend/subscription-preferences.feature): the site's notifications function on Caducus's in-memory fakes. Nothing is sent; every address is a placeholder.

The background, the signup, the cadence choice, the story and summary sends and the one-click unsubscribe reuse the steps of cadence-family.feature. What these steps add is the consent
side of the preferences page: a list added to the site's settings, a choice that joins a family, the consent wording the page shows, the confirmation, and the evidence stored per family."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from caducus.notify.directory import StaticDirectory  # noqa: E402
from caducus.notify.events import parse_timestamp  # noqa: E402

from papyrus_content.announcements.email_channel import CaducusEmail  # noqa: E402
from papyrus_content.notifications.notifications_test import CONSENT, Site  # noqa: E402
from papyrus_content.notifications.preferences import consent_by_family  # noqa: E402
from papyrus_content.notifications.runtime import assemble  # noqa: E402

READER = "reader@example.test"
ZONE = "America/New_York"
FORM = "notifications-preferences"
BASE = {"description": "", "approval": "admin"}
EVERY_ITEM = {**BASE, "id": "every-item", "name": "Every new story", "family": "new-stories", "cadence": "each", "rule": {}}
WEEKLY = {**BASE, "id": "weekly", "name": "Weekly newsletter", "cadence": "weekly", "sendAt": {"day": "monday", "time": "04:00"}, "timeZone": ZONE, "rule": {"sections": ["digest"]}}
DAILY = {**BASE, "id": "daily", "name": "Daily summary", "family": "new-stories", "cadence": "daily", "sendAt": {"time": "06:00"}, "timeZone": ZONE, "rule": {"sections": ["digest"]}}


def _site(context) -> Site:
    return context.site


def _at(context, moment: str) -> None:
    _site(context).clock.now = parse_timestamp(moment)


def _chosen(context) -> list[str]:
    body = _site(context).runtime.audience.preferences_state(context.manage[READER])["body"]
    return sorted(view["id"] for view in body["lists"] if view["subscribed"])


def _start(context, lists: tuple[dict, ...]) -> None:
    context.site = Site("alpha", readers=0, lists=lists)
    context.manage = {}
    context.summaries = {}
    _channel(context, lists)


def _channel(context, lists: tuple[dict, ...]) -> None:
    site = _site(context)
    context.channel = CaducusEmail(
        site.runtime.router, site.runtime.log, "alpha", lambda row, text: {"title": text.splitlines()[0], "url": f"https://alpha.example.test/{row['id']}.html"},
        clock=site.clock, lists={entry["id"]: entry for entry in lists},
    )


def _page_save(context, lists: list[str], *, consent: str | None) -> dict:
    """What the route sends for the page's Save: the ticked lists and, with them, the consent wording the page showed, the form and the page as evidence."""
    site = _site(context)
    fields = {"formId": FORM, "page": site.settings.site_origin + "/notifications/preferences/", "origin": site.settings.site_origin, "ip": "203.0.113.9", "userAgent": "Reader/1.0"}
    if consent is not None:
        fields["consent"] = consent
    answer = site.act("update_preferences", token=context.manage[READER], lists=lists, **fields)
    site.play_queue()
    return answer


@given('a site with the lists "every-item" and "weekly" and no daily list yet')
def without_daily(context) -> None:
    _start(context, (EVERY_ITEM, WEEKLY))


@when('the site adds the daily list to the family "new-stories"')
def adds_daily(context) -> None:
    """The site's settings change, as a deploy of the plugin's lists would: the same table, queue and mailer, one more list. Nothing else runs."""
    site = _site(context)
    lists = (*site.settings.lists, DAILY)
    site.settings = dataclasses.replace(site.settings, lists=lists)
    site.runtime = assemble(
        site.settings, store=site.store, queues=site.queues, directory=StaticDirectory([], "recipient-key-alpha"), mailer=site.mailer, clock=site.clock,
        postal_address=lambda: "1 Example Way\nExample City, EX 00000", key_secret="recipient-key-alpha", domains=site.domains, unsuppress=site.unsuppressed.append,
    )
    _channel(context, lists)


@then('the list "{list_id}" has no members')
def no_members(context, list_id: str) -> None:
    audience = _site(context).runtime.audience
    members, cursor = [], None
    while True:
        page, cursor = audience.subscriber_page(list_id, cursor)
        members += page
        if cursor is None:
            break
    assert members == [], f"{list_id} has {len(members)} members"


@when('the reader chooses "{list_id}" on the preferences page and agrees to the consent wording on "{moment}"')
def chooses_with_consent(context, list_id: str, moment: str) -> None:
    _at(context, moment)
    context.answer = _page_save(context, sorted(set(_chosen(context)) | {list_id}), consent=CONSENT)


@when('the reader agrees to the consent wording and saves the preferences {lists} on "{moment}"')
def saves_with_consent(context, lists: str, moment: str) -> None:
    import re

    _at(context, moment)
    context.answer = _page_save(context, re.findall(r'"([^"]+)"', lists), consent=CONSENT)


@when('the reader chooses "{list_id}" on the preferences page without the consent wording on "{moment}"')
def chooses_without_consent(context, list_id: str, moment: str) -> None:
    _at(context, moment)
    context.answer = _page_save(context, sorted(set(_chosen(context)) | {list_id}), consent=None)


@when('the reader chooses "{list_id}" on the preferences page with other words than the consent wording on "{moment}"')
def chooses_with_other_words(context, list_id: str, moment: str) -> None:
    _at(context, moment)
    context.answer = _page_save(context, sorted(set(_chosen(context)) | {list_id}), consent="Sign me up for anything.")


@given('the reader unsubscribes from everything on the preferences page on "{moment}"')
@when('the reader unsubscribes from everything on the preferences page on "{moment}"')
def unsubscribes_everything(context, moment: str) -> None:
    _at(context, moment)
    context.answer = _site(context).act("unsubscribe", token=context.manage[READER])
    assert context.answer["body"]["status"] == "unsubscribed", context.answer


@when('the reader presses the confirmation link on "{moment}"')
def presses_link(context, moment: str) -> None:
    _at(context, moment)
    site = _site(context)
    answer = site.act("confirm", token=site.confirm_link(READER).split("token=", 1)[1], userAgent="Reader/1.0")
    assert answer["body"]["status"] == "confirmed", answer
    context.manage[READER] = answer["body"]["manageToken"]


@then('the page answers "{status}"')
def answers_status(context, status: str) -> None:
    assert context.answer["body"]["status"] == status, context.answer


@then('the function answers {code:d} "{status}" to the choice')
def answers_code(context, code: int, status: str) -> None:
    assert (context.answer["statusCode"], context.answer["body"]["status"]) == (code, status), context.answer


@then('the page says a confirmation is on its way for "{list_id}"')
def says_confirming(context, list_id: str) -> None:
    assert context.answer["body"]["status"] == "check_email" and context.answer["body"]["confirming"] == [list_id], context.answer


def _confirmations(context) -> list[dict]:
    return [call for call in _site(context).mailer.calls if call["to"] == READER and "Confirm" in call["subject"]]


@then('one confirmation is mailed to the reader naming "{name}"')
def confirmation_named(context, name: str) -> None:
    (mail,) = _confirmations(context)
    assert name in mail["text"], mail["text"]


@then("no confirmation is mailed to the reader")
def no_confirmation(context) -> None:
    assert _confirmations(context) == [], _confirmations(context)


@then('the family "{family}" holds the confirmation of "{moment}" with the site\'s consent wording and the form "{form}"')
def holds_confirmation(context, family: str, moment: str, form: str) -> None:
    records = consent_by_family(_site(context).runtime.audience, READER).get(family, [])
    matching = [record for record in records if record.get("confirmedAt") and parse_timestamp(record["confirmedAt"]) == parse_timestamp(moment)]
    assert matching, f"no confirmation of {moment} for {family}: {records}"
    record = matching[0]
    assert record["wording"] == CONSENT and record["formId"] == form, record


@then('the family "{family}" holds no confirmation')
def holds_none(context, family: str) -> None:
    assert consent_by_family(_site(context).runtime.audience, READER).get(family, []) == []


@then('the family "{family}" has {count:d} confirmation records')
def holds_count(context, family: str, count: int) -> None:
    assert len(consent_by_family(_site(context).runtime.audience, READER).get(family, [])) == count


@then('the reader is on nothing')
def on_nothing(context) -> None:
    assert _chosen(context) == [], _chosen(context)


@then('the reader is suppressed as "{reason}"')
def suppressed_as(context, reason: str) -> None:
    runtime = _site(context).runtime
    assert runtime.audience.suppression(runtime.keys.recipient(READER)) == reason


@then('the reader has no message for "{title}"')
def no_message(context, title: str) -> None:
    assert not [call for call in _site(context).mailer.calls if call["to"] == READER and title in call["subject"]], _site(context).mailer.calls
