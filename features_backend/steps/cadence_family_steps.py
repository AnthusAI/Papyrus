"""Cadence families (features_backend/cadence-family.feature): the site's notifications function on Caducus's in-memory fakes. Nothing is sent; every address is a placeholder.

The rule is Caducus's (the stock public audience); what these steps prove is Papyrus's part of it: the list settings that name a family, the hook that makes a switch
wait for the next period start, and the ``audienceAsOf`` a periodic Delivery carries (``announcements/email_channel.py``)."""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from behave import given, step, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from caducus.notify.audience.service import rcpt  # noqa: E402
from caducus.notify.events import parse_timestamp  # noqa: E402

from papyrus_content.announcements import records  # noqa: E402
from papyrus_content.announcements.email_channel import CaducusEmail  # noqa: E402
from papyrus_content.list_cadence.list_cadence_test import entry as list_entry  # noqa: E402
from papyrus_content.list_cadence.settings import ListSettingsError, validate_document  # noqa: E402
from papyrus_content.notifications.notifications_test import Site  # noqa: E402

READER = "reader@example.test"
ZONE = "America/New_York"
SEND_AT = {"daily": {"time": "06:00"}, "weekly": {"day": "monday", "time": "04:00"}}


def _site(context) -> Site:
    return context.site


def _names(text: str) -> list[str]:
    return re.findall(r'"([^"]+)"', text)


def _at(context, moment: str) -> None:
    _site(context).clock.now = parse_timestamp(moment)


def _key(context) -> str:
    return _site(context).runtime.audience._keys.recipient(READER)


def _chosen(context) -> list[str]:
    """What the reader's preferences page shows ticked: their choice, which runs ahead of the membership while a switch waits."""
    body = _site(context).runtime.audience.preferences_state(context.manage[READER])["body"]
    return sorted(view["id"] for view in body["lists"] if view["subscribed"])


def _row(context, list_id: str) -> dict:
    row = _site(context).store.get(rcpt(_key(context)), "SUB#" + list_id)
    assert row is not None, f"the reader has no membership row for {list_id}"
    return row


def _save(context, lists: list[str]) -> dict:
    return _site(context).act("update_preferences", token=context.manage[READER], lists=lists)


def _lists(*extra) -> tuple[dict, ...]:
    return extra


def _start(context, lists: tuple[dict, ...]) -> None:
    context.site = Site("alpha", readers=0, lists=lists)
    context.manage = {}
    context.channel = CaducusEmail(
        context.site.runtime.router, context.site.runtime.log, "alpha", _facts, clock=context.site.clock,
        lists={entry["id"]: entry for entry in lists},
    )
    context.summaries = {}


def _facts(row, text):
    return {"title": text.splitlines()[0], "url": f"https://alpha.example.test/{row['id']}.html"}


@given('a site with the lists "every-item" and "daily" in the family "new-stories" and the list "weekly" in its own family')
def site(context) -> None:
    base = {"description": "", "approval": "admin"}
    _start(context, (
        {**base, "id": "every-item", "name": "Every new story", "family": "new-stories", "cadence": "each", "rule": {}},
        {**base, "id": "daily", "name": "Daily summary", "family": "new-stories", "cadence": "daily", "sendAt": SEND_AT["daily"], "timeZone": ZONE, "rule": {"sections": ["digest"]}},
        {**base, "id": "weekly", "name": "Weekly newsletter", "cadence": "weekly", "sendAt": SEND_AT["weekly"], "timeZone": ZONE, "rule": {"sections": ["digest"]}},
    ))


@given('a site whose lists "first" and "second" form a family with no periodic list')
def plain_family(context) -> None:
    base = {"description": "", "approval": "admin", "family": "pair", "cadence": "each", "rule": {}}
    _start(context, ({**base, "id": "first", "name": "First"}, {**base, "id": "second", "name": "Second"}))


@given('the daily list is sent at "{time}" in "{zone}"')
def daily_time(context, time: str, zone: str) -> None:
    assert (time, zone) == (SEND_AT["daily"]["time"], ZONE), "these steps describe a daily list sent at 06:00 in America/New_York"


@given('the reader has confirmed "{list_id}" on "{moment}"')
@when('the reader confirms "{list_id}" on "{moment}"')
def confirmed(context, list_id: str, moment: str) -> None:
    """A signup and the link in its confirmation: a list of a family the reader does not hold needs one (subscription-preferences.feature)."""
    _at(context, moment)
    context.manage[READER] = _site(context).join(READER, [list_id])
    _site(context).mailer.calls.clear()


@given('the reader turns off "{list_id}" on "{moment}"')
def turns_off(context, list_id: str, moment: str) -> None:
    _at(context, moment)
    assert _save(context, [name for name in _chosen(context) if name != list_id])["body"]["status"] == "saved"


@given('the reader chooses "{list_id}" on the preferences page on "{moment}"')
@when('the reader chooses "{list_id}" on the preferences page on "{moment}"')
def chooses(context, list_id: str, moment: str) -> None:
    """The preferences page keeps the reader's other boxes ticked and ticks one more."""
    _at(context, moment)
    context.answer = _save(context, sorted(set(_chosen(context)) | {list_id}))
    assert context.answer["body"]["status"] == "saved", context.answer


@step('the time is "{moment}"')
def the_time(context, moment: str) -> None:
    _at(context, moment)


@step('the story "{title}" is published and sent at "{moment}"')
def published(context, title: str, moment: str) -> None:
    _at(context, moment)
    _site(context).publish(title, "news")
    _site(context).play_queue()


@when('the reader saves the preferences {names} on "{moment}"')
def saves(context, names: str, moment: str) -> None:
    _at(context, moment)
    context.answer = _save(context, _names(names))


@when('the reader subscribes to "{first}" and "{second}" together')
def subscribes_together(context, first: str, second: str) -> None:
    context.answer = _site(context).subscribe(READER, [first, second])


@step('the mail provider posts the one-click unsubscribe from the message for "{title}"')
def one_click(context, title: str) -> None:
    (mail,) = [call for call in _site(context).mailer.calls if call["to"] == READER and title in call["subject"]]
    url = mail["headers"]["List-Unsubscribe"].strip("<>")
    query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
    answer = _site(context).act("unsubscribe", token=query["t"], list=query.get("l"))
    assert answer["body"]["status"] == "unsubscribed", answer


def _summary(context, label: str, list_id: str, scheduled: str) -> None:
    """A periodic list's Delivery, as Papyrus hands it to Caducus: its release time is the scheduled local time, and the event names the period's start."""
    moment = datetime.fromisoformat(scheduled).replace(tzinfo=ZoneInfo(ZONE))
    site = _site(context)
    if site.clock.now < moment:
        site.clock.now = moment
    title = f"{label} {scheduled}"
    row = {"id": f"delivery-{list_id}-{scheduled}", "channel": "email", "audience": [list_id], "releaseAt": records.utc(moment)}
    context.channel.submit(row, title, f"delivery:{row['id']}:a1")
    site.play_queue()
    context.summaries[(list_id, scheduled)] = title


@when('the daily summary scheduled for "{scheduled}" local time is sent')
def daily_sent(context, scheduled: str) -> None:
    _summary(context, "Daily summary", "daily", scheduled)


@when('the weekly issue scheduled for "{scheduled}" local time is sent')
def weekly_sent(context, scheduled: str) -> None:
    _summary(context, "Weekly issue", "weekly", scheduled)


@when('a list settings document names a daily and a weekly list of the family "{family}"')
def two_periodic(context, family: str) -> None:
    context.document = {"schemaVersion": 1, "lists": {"first": list_entry("daily", family=family), "second": list_entry("weekly", family=family, sendAt={"day": "monday", "time": "06:05"})}}


@when('a list settings document names two daily lists of the family "{family}"')
def two_daily(context, family: str) -> None:
    context.document = {"schemaVersion": 1, "lists": {"first": list_entry("daily", family=family), "second": list_entry("daily", family=family)}}


def _refused(context) -> str:
    try:
        validate_document(context.document)
    except ListSettingsError as refusal:
        return refusal.message
    raise AssertionError("the settings were accepted")


@then("the settings are refused saying a family has one periodic list")
def refused_periodic(context) -> None:
    assert "periodic lists of the family" in _refused(context)


@then("the settings are refused saying a family has one list for each cadence")
def refused_cadence(context) -> None:
    assert "a family has one list for each cadence" in _refused(context)


@then("nothing is mailed to the reader")
def nothing_mailed(context) -> None:
    assert not [call for call in _site(context).mailer.calls if call["to"] == READER]


@then('the preferences page shows {names} on and {gone} off')
def page_shows(context, names: str, gone: str) -> None:
    chosen = _chosen(context)
    assert chosen == sorted(_names(names)), chosen
    assert not set(_names(gone)) & set(chosen), chosen


@then('the reader is {still} on {names} and nothing else')
@then("the reader is on {names} and nothing else")
def only_on(context, names: str, still: str = "") -> None:
    assert _chosen(context) == sorted(_names(names)), _chosen(context)


@then('the reader\'s membership of "{list_id}" ends at "{moment}"')
def ends(context, list_id: str, moment: str) -> None:
    assert parse_timestamp(_row(context, list_id)["until"]) == parse_timestamp(moment), _row(context, list_id)


@then('the reader\'s membership of "{list_id}" begins at "{moment}"')
def begins(context, list_id: str, moment: str) -> None:
    assert parse_timestamp(_row(context, list_id)["since"]) == parse_timestamp(moment), _row(context, list_id)


@then('the reader\'s membership of "{list_id}" began at "{moment}" and has no end')
def began(context, list_id: str, moment: str) -> None:
    begins(context, list_id, moment)
    assert "until" not in _row(context, list_id)


@then("the reader is not suppressed")
def not_suppressed(context) -> None:
    assert _site(context).runtime.audience.suppression(_key(context)) is None


def _messages_for(context, title: str) -> int:
    return len([call for call in _site(context).mailer.calls if call["to"] == READER and title in call["subject"]])


@then('the reader has the message for "{title}" once')
def once(context, title: str) -> None:
    assert _messages_for(context, title) == 1, _site(context).mailer.calls


@then('the reader has no message for "{title}" as it happened')
def none_for(context, title: str) -> None:
    assert _messages_for(context, title) == 0, _site(context).mailer.calls


def _has_summary(context, list_id: str, scheduled: str) -> bool:
    return _messages_for(context, context.summaries[(list_id, scheduled)]) == 1


@then('the reader has the daily summary scheduled for "{scheduled}" local time')
def has_daily(context, scheduled: str) -> None:
    assert _has_summary(context, "daily", scheduled), _site(context).mailer.calls


@then('the reader has the weekly issue scheduled for "{scheduled}" local time')
def has_weekly(context, scheduled: str) -> None:
    assert _has_summary(context, "weekly", scheduled), _site(context).mailer.calls


@then('the reader has only the daily summary scheduled for "{kept}" local time and not the one scheduled for "{missed}" local time')
def has_one_daily(context, kept: str, missed: str) -> None:
    assert _has_summary(context, "daily", kept) and not _messages_for(context, context.summaries[("daily", missed)]), _site(context).mailer.calls


@then("the reader has no daily summary")
def no_daily(context) -> None:
    assert not [call for call in _site(context).mailer.calls if call["to"] == READER and call["subject"].startswith("Daily summary")], _site(context).mailer.calls
