from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.newsletter.issues_test import ADMIN, LISTS, rig_context  # noqa: E402
from papyrus_content.newsletter.store import iso  # noqa: E402
from papyrus_content.projection_trigger import item_task  # noqa: E402
from papyrus_content.publish_alerts_test import NEWSLETTER, Backend  # noqa: E402
from papyrus_content.publishing import publish_item  # noqa: E402

ITEM = "item-{section}-hello"


def close_rig(context) -> None:
    manager = getattr(context, "rig_manager", None)
    if manager is not None:
        manager.__exit__(None, None, None)
        context.rig_manager = None


def save(context, section: str, body: str = "Hello.\n") -> str:
    item_id = ITEM.format(section=section)
    context.backend.action(
        "saveItemDraft",
        {"id": item_id, "type": "article", "slug": "hello", "section": section, "frontMatterYaml": "title: Hello\n", "bodyMarkus": body},
    )
    return item_id


def deliver(context) -> None:
    """Hand the newsletter function what the content-actions function asked it to be invoked with."""
    for payload in context.backend.announcements():
        context.rig.task(payload["task"], **{key: value for key, value in payload.items() if key != "task"})
        context.delivered.append(payload)
    context.backend.lam.invocations.clear()


def alerts(context) -> list[dict]:
    return [row for row in context.rig.service.issues.list_all() if row["kind"] == "alert"]


@given('a site with an alert list for the "{section}" section and {count:d} confirmed subscribers')
def site_with_alert_list(context, section: str, count: int) -> None:
    context.rig_manager = rig_context()
    context.rig = context.rig_manager.__enter__()
    context.add_cleanup(close_rig, context)
    alert = {"id": "rulings", "name": "Rulings", "description": "", "kind": "alert", "approval": "admin", "rule": {"sections": [section]}}
    object.__setattr__(context.rig.settings, "lists", (LISTS[0], alert))
    for number in range(count):
        context.rig.add_member(f"reader{number}@example.com", list_id="rulings")
    context.backend = Backend(projection=True)
    context.rig.service._content = context.backend.client  # the newsletter reads the published item the publish just wrote
    context.delivered = []


@given('the editor publishes an article in the "{section}" section')
@when('the editor publishes an article in the "{section}" section')
def editor_publishes(context, section: str) -> None:
    context.item_id = save(context, section)
    context.backend.action("publishItem", {"id": context.item_id})
    deliver(context)


@when("the editor changes the article and publishes it again")
def editor_republishes(context) -> None:
    context.backend.action(
        "saveItemDraft",
        {"id": context.item_id, "type": "article", "slug": "hello", "section": "rulings", "frontMatterYaml": "title: Hello again\n", "bodyMarkus": "Changed.\n"},
    )
    context.backend.action("publishItem", {"id": context.item_id})
    deliver(context)


@when("the same announcement is delivered again")
def announce_again(context) -> None:
    payload = context.delivered[0]
    context.rig.task(payload["task"], **{key: value for key, value in payload.items() if key != "task"})


@when('the command line publishes an article in the "{section}" section')
def cli_publishes(context, section: str) -> None:
    context.item_id = save(context, section)
    result = publish_item(context.backend.client, context.item_id, actor="papyrus-cli")
    assert result.changed
    context.backend.run({"projectionTask": item_task(context.item_id, unpublished=False, published_item_id=result.published_item_id)})
    deliver(context)


@when("the editor publishes the same article in the newsroom")
def newsroom_publishes_again(context) -> None:
    context.backend.action("publishItem", {"id": context.item_id})
    deliver(context)


@when("the editor unpublishes the alert's article")
def unpublish(context) -> None:
    context.backend.action("unpublishItem", {"id": context.item_id})
    deliver(context)


@when("the whole site is reprojected")
def reproject(context) -> None:
    context.backend.run({"projectionTask": {"task": "all"}})
    context.backend.run({"projectionTask": {"task": "deploy-render"}})
    deliver(context)


@when("an admin approves the alert for an hour from now")
def approve(context) -> None:
    (issue,) = alerts(context)
    context.alert_id = issue["issueId"]
    context.rig.last_issue = context.alert_id
    answer = context.rig.call("issue_approve", ADMIN, issueId=context.alert_id, sendAt=iso(context.rig.now + 3600))
    assert answer["ok"], answer


@when("the schedule fires the send for the alert")
def fire(context) -> None:
    context.rig.now += 3600
    context.rig.fire(context.alert_id)


@when("the worker handles the alert's queued messages")
def drain(context) -> None:
    context.rig.drain()


@then("{count:d} alert is awaiting approval")
@then("{count:d} alerts are awaiting approval")
def awaiting(context, count: int) -> None:
    rows = [row for row in alerts(context) if row["status"] == "awaiting_approval"]
    assert len(rows) == count == len(alerts(context)), alerts(context)


@then("no alert exists")
def none(context) -> None:
    assert alerts(context) == []


@then('the alert subject is "{subject}"')
def subject(context, subject: str) -> None:
    assert alerts(context)[0]["subject"] == subject


@then("no alert email is sent")
def nothing_sent(context) -> None:
    assert context.rig.ses.sent == []


@then("the alert is mailed to {count:d} subscribers")
def sent(context, count: int) -> None:
    assert len(context.rig.ses.sent) == count, context.rig.ses.sent


@then('the alert is "{status}"')
def status(context, status: str) -> None:
    assert context.rig.issue(context.alert_id)["status"] == status


@then("no Item is published for the alert")
def no_item(context) -> None:
    assert context.rig.published_items == []


@then("the newsletter was told about {count:d} publish")
def told(context, count: int) -> None:
    assert len(context.delivered) == count, context.delivered
