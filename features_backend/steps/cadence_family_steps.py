"""Cadence families (features_backend/cadence-family.feature): the site's notifications function on Caducus's in-memory fakes. Nothing is sent; every address is a placeholder."""
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

from caducus.notify.events import parse_timestamp  # noqa: E402

from papyrus_content.list_cadence.family import period_start  # noqa: E402
from papyrus_content.notifications.notifications_test import Site  # noqa: E402

READER = "reader@example.test"
ZONE = "America/New_York"
#: The periodic lists as the list settings describe them, for the period of an issue.
PERIODIC = {
    "daily": {"cadence": "daily", "timeZone": ZONE, "sendAt": {"time": "06:00"}},
    "weekly": {"cadence": "weekly", "timeZone": ZONE, "sendAt": {"day": "monday", "time": "04:00"}},
}


def _site(context) -> Site:
    return context.site


def _names(text: str) -> list[str]:
    return re.findall(r'"([^"]+)"', text)


def _at(context, moment: str) -> None:
    _site(context).clock.now = parse_timestamp(moment)


def _key(context) -> str:
    return _site(context).runtime.audience._keys.recipient(READER)


def _subscribed(context) -> list[str]:
    return sorted(_site(context).runtime.audience.subscribed_lists(_key(context)))


def _save(context, lists: list[str]) -> None:
    answer = _site(context).act("update_preferences", token=context.manage[READER], lists=lists)
    assert answer["body"]["status"] == "saved", answer


@given('a site with the lists "every-item" and "daily" in the family "new-stories" and the list "weekly" in its own family')
def site(context) -> None:
    lists = (
        {"id": "every-item", "name": "Every new story", "description": "", "family": "new-stories", "rule": {}, "approval": "admin"},
        {"id": "daily", "name": "Daily summary", "description": "", "family": "new-stories", "rule": {"sections": ["digest"]}, "approval": "admin"},
        {"id": "weekly", "name": "Weekly newsletter", "description": "", "rule": {"sections": ["digest"]}, "approval": "admin"},
    )
    context.site = Site("alpha", readers=0, lists=lists)
    context.manage = {}


@given('the daily list is sent at "{time}" in "{zone}"')
def daily_time(context, time: str, zone: str) -> None:
    assert (time, zone) == (PERIODIC["daily"]["sendAt"]["time"], ZONE), "these steps describe a daily list sent at 06:00 in America/New_York"


@given('the reader has confirmed "{list_id}" on "{moment}"')
def confirmed(context, list_id: str, moment: str) -> None:
    _at(context, moment)
    context.manage[READER] = _site(context).join(READER, [list_id])
    _site(context).mailer.calls.clear()


@given('the reader turns off "{list_id}" on "{moment}"')
def turns_off(context, list_id: str, moment: str) -> None:
    _at(context, moment)
    _save(context, [name for name in _subscribed(context) if name != list_id])


@step('the story "{title}" is published and sent at "{moment}"')
def published(context, title: str, moment: str) -> None:
    _at(context, moment)
    _site(context).publish(title, "news")
    _site(context).play_queue()


@when('the reader chooses "{list_id}" on the preferences page on "{moment}"')
def chooses(context, list_id: str, moment: str) -> None:
    """The preferences page keeps the reader's boxes ticked and ticks one more."""
    _at(context, moment)
    _save(context, sorted(set(_subscribed(context)) | {list_id}))


@when('the reader saves the preferences {names} on "{moment}"')
def saves(context, names: str, moment: str) -> None:
    _at(context, moment)
    _save(context, _names(names))


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


@then("nothing is mailed to the reader")
def nothing_mailed(context) -> None:
    assert not [call for call in _site(context).mailer.calls if call["to"] == READER]


@then("the reader is on {names} and not on {gone}")
def is_on(context, names: str, gone: str) -> None:
    held = _subscribed(context)
    assert held == sorted(_names(names)), held
    assert not set(_names(gone)) & set(held), held


@then('the reader\'s membership of "{list_id}" has been since "{moment}"')
def since(context, list_id: str, moment: str) -> None:
    assert _site(context).runtime.audience.since(_key(context), list_id) == parse_timestamp(moment)


@then('the weekly newsletter\'s membership of the reader is still since "{moment}"')
def weekly_since(context, moment: str) -> None:
    since(context, "weekly", moment)


@then("the reader is not suppressed")
def not_suppressed(context) -> None:
    assert _site(context).runtime.audience.suppression(_key(context)) is None


def _messages_for(context, title: str) -> int:
    return len([call for call in _site(context).mailer.calls if call["to"] == READER and title in call["subject"]])


@then('the reader has the message for "{first}" once and none for "{second}"')
def once_and_none(context, first: str, second: str) -> None:
    assert (_messages_for(context, first), _messages_for(context, second)) == (1, 0)


@then('the reader has the message for "{first}" once and for "{second}" once')
def once_each(context, first: str, second: str) -> None:
    assert (_messages_for(context, first), _messages_for(context, second)) == (1, 1)


def _reaches(context, list_id: str, scheduled: str) -> bool:
    """Whether the periodic issue scheduled at that local time goes to the reader: they must have been members at its period's start."""
    entry = PERIODIC[list_id]
    moment = datetime.fromisoformat(scheduled).replace(tzinfo=ZoneInfo(entry["timeZone"]))
    keys, _next = _site(context).runtime.audience.subscriber_page(list_id, None, as_of=period_start(entry, moment))
    return _key(context) in keys


@then('the daily summary scheduled for "{scheduled}" local time reaches the reader')
def daily_reaches(context, scheduled: str) -> None:
    assert _reaches(context, "daily", scheduled)


@then('the daily summary scheduled for "{scheduled}" local time does not reach the reader')
def daily_misses(context, scheduled: str) -> None:
    assert not _reaches(context, "daily", scheduled)


@then('the weekly issue scheduled for "{scheduled}" local time reaches the reader')
def weekly_reaches(context, scheduled: str) -> None:
    assert _reaches(context, "weekly", scheduled)
