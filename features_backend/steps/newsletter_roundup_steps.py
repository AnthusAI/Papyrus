from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.newsletter.issues_test import ADMIN, EDITOR, rig_context  # noqa: E402
from papyrus_content.newsletter.store import iso  # noqa: E402

DAY = 24 * 60 * 60


def close_rig(context) -> None:
    manager = getattr(context, "rig_manager", None)
    if manager is not None:
        manager.__exit__(None, None, None)
        context.rig_manager = None


@given("a site with a weekly roundup and {count:d} confirmed subscribers")
def site_with_roundup(context, count: int) -> None:
    context.rig_manager = rig_context()
    context.rig = context.rig_manager.__enter__()
    context.add_cleanup(close_rig, context)
    for number in range(count):
        context.rig.add_member(f"reader{number}@example.com")
    context.refused = None


@given("the week's published items have been drafted into an issue")
def drafted(context) -> None:
    created = context.rig.draft()
    context.issue_id = created["issueId"]
    context.rig.last_issue = context.issue_id


def approve(context) -> dict:
    rig = context.rig
    return rig.call("issue_approve", ADMIN, issueId=context.issue_id, sendAt=iso(rig.now + 3600))


@given("an admin approves the issue for an hour from now")
@when("an admin approves the issue for an hour from now")
def admin_approves(context) -> None:
    assert approve(context)["ok"]


@when("an editor tries to approve the issue")
def editor_approves(context) -> None:
    rig = context.rig
    context.refused = rig.call("issue_approve", EDITOR, issueId=context.issue_id, sendAt=iso(rig.now + 3600)).get("error") == "forbidden"


@given("the postal address is not configured")
def no_postal_address(context) -> None:
    context.rig.postal.value = None


@when("an editor changes the issue body")
def edit_body(context) -> None:
    item_id = context.rig.issue(context.issue_id)["itemId"]
    context.rig.content.items[item_id]["bodyMarkus"] += "\nA correction added after approval.\n"


@when("the schedule fires the send for the issue")
def fire(context) -> None:
    context.rig.now += 3600
    context.rig.fire(context.issue_id)


@when("the worker handles the queued messages")
def drain(context) -> None:
    context.delivered = list(context.rig.queue.batches)
    context.rig.drain()


@when("the queue delivers the same messages again")
def redeliver(context) -> None:
    for batch in context.delivered:
        context.rig.sender.process({"issueId": context.issue_id, "hids": batch})


@then("the answer is refused")
def refused(context) -> None:
    assert context.refused is True


@then("no email is sent")
def nothing_sent(context) -> None:
    assert context.rig.ses.sent == [], context.rig.ses.sent


@then('the issue is "{status}"')
def issue_status(context, status: str) -> None:
    assert context.rig.issue(context.issue_id)["status"] == status


@then('the issue note says "{note}"')
def issue_note(context, note: str) -> None:
    assert context.rig.issue(context.issue_id)["note"] == note


@then("a one-time schedule is set for the issue")
def schedule_set(context) -> None:
    names = [entry[0] for entry in context.rig.scheduler.created]
    assert names == [f"papyrus-nl-example-{context.issue_id[:8]}"], names


@then("{count:d} emails are sent, each to a different subscriber")
def mails_sent(context, count: int) -> None:
    recipients = [message["Destination"]["ToAddresses"][0] for message in context.rig.ses.sent]
    assert len(recipients) == count and len(set(recipients)) == count, recipients


@then("every email carries a one-click unsubscribe header")
def one_click(context) -> None:
    for message in context.rig.ses.sent:
        headers = {entry["Name"]: entry["Value"] for entry in message["Content"]["Simple"]["Headers"]}
        assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
        assert headers["List-Unsubscribe"].startswith("<https://")


@then("the issue is published to the archive")
def archived(context) -> None:
    assert context.rig.published_items == [context.rig.issue(context.issue_id)["itemId"]]


@then("the issue is published to the archive once")
def archived_once(context) -> None:
    archived(context)
