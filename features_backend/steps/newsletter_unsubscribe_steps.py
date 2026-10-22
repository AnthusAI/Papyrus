from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.newsletter import records  # noqa: E402
from papyrus_content.newsletter.events import alarm_names  # noqa: E402
from papyrus_content.newsletter.manage_test import add_ledger, ses_event, sns  # noqa: E402
from papyrus_content.newsletter.pause import is_paused  # noqa: E402
from papyrus_content.newsletter.suppression import is_suppressed  # noqa: E402

ADDRESS = "reader@example.com"


def token(context) -> str:
    from papyrus_content.newsletter import links

    return links.make_manage_token(context.harness.hid(ADDRESS), context.harness.keys)


def call(context, action: str, **fields):
    return context.harness.service.dispatch({"action": action, **fields})


@given('"{email}" is subscribed to "{first}" and "{second}"')
def subscribed(context, email: str, first: str, second: str) -> None:
    context.harness.subscribe(email, lists=[first, second])
    context.harness.confirm()
    context.harness.now += 4000
    context.mails_before = len(context.harness.ses.sent)


@when("the subscriber unsubscribes from everything {count:d} times")
def unsubscribe_times(context, count: int) -> None:
    context.answers = [call(context, "unsubscribe", token=token(context))["body"]["status"] for _ in range(count)]


@given("the subscriber unsubscribes from everything")
def unsubscribe_once(context) -> None:
    call(context, "unsubscribe", token=token(context))


@when('the subscriber unsubscribes from "{list_id}"')
def unsubscribe_list(context, list_id: str) -> None:
    call(context, "unsubscribe", token=token(context), list=list_id)


@when('the subscriber saves preferences choosing "{list_id}"')
@given('the subscriber saves preferences choosing "{list_id}"')
def save_preferences(context, list_id: str) -> None:
    context.saved = call(context, "update_preferences", token=token(context), lists=[list_id])


@when("the subscriber opens preferences")
def open_preferences(context) -> None:
    context.state = call(context, "preferences_state", token=token(context))["body"]


@then('every answer is "{status}"')
def every_answer(context, status: str) -> None:
    assert context.answers and all(answer == status for answer in context.answers), context.answers


@then('the subscriber is "{status}" and holds no list')
def holds_nothing(context, status: str) -> None:
    profile = context.harness.profile(ADDRESS)
    assert profile["status"] == status, profile["status"]
    assert not [row for row in context.harness.store.memberships(context.harness.hid(ADDRESS)).values() if row["status"] == "subscribed"]


@then('the subscriber is "{status}" and holds only "{lists}"')
def holds_only(context, status: str, lists: str) -> None:
    assert context.harness.profile(ADDRESS)["status"] == status
    rows = context.harness.store.memberships(context.harness.hid(ADDRESS))
    held = sorted(list_id for list_id, row in rows.items() if row["status"] == "subscribed")
    assert held == sorted(lists.split(",")), held


@then("no new email was sent to the subscriber")
def no_new_email(context) -> None:
    assert len(context.harness.ses.sent) == context.mails_before, len(context.harness.ses.sent)


@then('the address shows as "{masked}"')
def masked(context, masked: str) -> None:
    assert context.state["email"] == masked and ADDRESS not in str(context.state)


@then('"{first}" and "{second}" are ticked and "{third}" is not')
def ticked(context, first: str, second: str, third: str) -> None:
    flags = {entry["id"]: entry["subscribed"] for entry in context.state["lists"]}
    assert flags == {first: True, second: True, third: False}, flags


def hid(context) -> str:
    return context.harness.hid(ADDRESS)


@when('SES reports a "{kind}" bounce for the subscriber')
@given('SES reports a "{kind}" bounce for the subscriber')
def bounce(context, kind: str) -> None:
    context.harness.service.dispatch(sns(ses_event("Bounce", hid(context), issue="", list_id="", bounce={"bounceType": kind})))
    context.harness.ses.on_suppression_list.add(ADDRESS)


@when('SES reports a "{kind}" bounce with no subscriber tag')
def untagged_bounce(context, kind: str) -> None:
    context.harness.service.dispatch(sns(ses_event("Bounce", "", bounce={"bounceType": kind})))


@when("SES reports a complaint for the subscriber")
def complaint(context) -> None:
    context.harness.service.dispatch(sns(ses_event("Complaint", hid(context), issue="", list_id="")))


@then('the address is suppressed because of "{reason}"')
def suppressed_because(context, reason: str) -> None:
    row = records.get_suppression(context.harness.store, hid(context))
    assert row and row["reason"] == reason, row


@then("the address is not suppressed")
def not_suppressed(context) -> None:
    assert not is_suppressed(hid(context), context.harness.store)


@then("SES was told to forget the address")
def forgotten(context) -> None:
    assert context.harness.ses.unsuppressed == [ADDRESS]


@given('the subscriber was sent issue "{issue}"')
def was_sent(context, issue: str) -> None:
    add_ledger(context.harness, hid(context), issue)


@when("the subscriber deletes their data")
def delete_data(context) -> None:
    assert call(context, "delete_subscriber", token=token(context))["body"]["status"] == "deleted"


@then("nothing is stored about the subscriber")
def nothing_about(context) -> None:
    import json

    leftovers = [
        item for item in context.harness.items()
        if hid(context) in json.dumps(item) and not item["pk"]["S"].startswith(("RATE#", "EVENTS"))
    ]
    assert leftovers == [], leftovers


@when("the bounce rate alarm goes off")
def alarm_goes_off(context) -> None:
    message = {"AlarmName": alarm_names("example")[0], "NewStateValue": "ALARM", "NewStateReason": "too many bounces"}
    context.harness.service.dispatch(sns(message))


@when("an admin resumes sending")
def resume(context) -> None:
    call(context, "resume_sending")


@then("sending is paused and SES sending is turned off")
def paused(context) -> None:
    assert is_paused(context.harness.store) and context.harness.ses.sending == [False]


@then("sending is not paused and SES sending is turned on")
def not_paused(context) -> None:
    assert not is_paused(context.harness.store) and context.harness.ses.sending == [False, True]
