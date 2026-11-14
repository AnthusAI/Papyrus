from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path
from typing import Any

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.publish_alerts_test import Backend  # noqa: E402

SAVE = {"type": "article", "slug": "hello", "section": "news", "frontMatterYaml": "title: Hello\n", "bodyMarkus": "Hello.\n"}


def save(context, number: int = 0, body: str = "Hello.\n", title: str = "Hello") -> str:
    item_id = "item-news-hello" if number == 0 else f"item-news-import-{number}"
    context.backend.action(
        "saveItemDraft",
        {**SAVE, "id": item_id, "slug": "hello" if number == 0 else f"import-{number}", "bodyMarkus": body, "frontMatterYaml": f"title: {title}\n"},
    )
    return item_id


@given("a site whose notifications plugin is on")
def plugin_on(context) -> None:
    context.backend = Backend(projection=True, notifications=True)
    context.result = None


@given("a site whose notifications plugin is off")
def plugin_off(context) -> None:
    context.backend = Backend(projection=True, notifications=False)


@given("the site cannot write its pages")
def cannot_write(context) -> None:
    context.backend = Backend(projection=True, notifications=True, rejects_writes=True)


@given("the editor publishes an article")
@when("the editor publishes an article")
def publishes(context) -> None:
    context.item_id = save(context)
    with contextlib.redirect_stdout(io.StringIO()) as output:
        context.result = context.backend.action("publishItem", {"id": context.item_id})
    context.output = output.getvalue()


@when("the editor publishes the same article again without changes")
def publishes_again(context) -> None:
    assert context.backend.action("publishItem", {"id": context.item_id})["changed"] is False


@when("the editor unpublishes the article and publishes it again")
def unpublishes_and_publishes(context) -> None:
    assert context.backend.action("unpublishItem", {"id": context.item_id})["changed"] is True
    result = context.backend.action("publishItem", {"id": context.item_id})
    assert result.get("ok") and result.get("changed"), result


@when("the site can write its pages again and the scheduled retry runs")
def retry_succeeds(context) -> None:
    (context.retry,) = context.backend.retries()
    context.backend.s3.rejects_writes = False
    assert context.backend.run({"projectionTask": context.retry})["ok"] is True


@when("the scheduled retry runs and fails")
def retry_fails(context) -> None:
    (context.retry,) = context.backend.retries()
    try:
        context.backend.run({"projectionTask": context.retry})
    except Exception:  # noqa: BLE001 - the task raises so Lambda retries it
        pass


@given("invoking the notifications function is refused")
def invoking_refused(context) -> None:
    context.backend = Backend(projection=True, notifications=True)
    original = context.backend.lam.invoke

    def refuse(**arguments: Any) -> None:
        if arguments["FunctionName"].startswith("papyrus-notifications"):
            raise RuntimeError("secret-looking detail")
        original(**arguments)

    context.backend.lam.invoke = refuse


@when("{count:d} articles are imported as drafts and the whole site is reprojected")
def bulk_import(context, count: int) -> None:
    for number in range(1, count + 1):
        save(context, number)
    context.backend.run({"projectionTask": {"task": "all"}})
    context.backend.run({"projectionTask": {"task": "deploy-render"}})


@when("the editor edits the live article and then unpublishes it")
def edit_then_unpublish(context) -> None:
    save(context, body="A new body.\n")
    assert context.backend.action("unpublishItem", {"id": context.item_id})["changed"] is True


@then("the notifications function was told about {count:d} publish")
@then("the notifications function was told about {count:d} publishes")
def told(context, count: int) -> None:
    assert len(context.backend.notification_announcements()) == count, context.backend.notification_announcements()


@then("the newsletter was still told about {count:d} publish")
def newsletter_told(context, count: int) -> None:
    assert len(context.backend.announcements()) == count


@then('the announcement carries the event id "story.published:" followed by the article\'s lineage')
def event_id(context) -> None:
    (payload,) = context.backend.notification_announcements()
    assert payload["task"] == "story-published"
    assert payload["eventId"] == "story.published:" + payload["lineageId"], payload
    assert payload["lineageId"] == context.item_id


@then("both announcements carry the same event id")
def same_event_id(context) -> None:
    first, second = context.backend.notification_announcements()
    assert first["eventId"] == second["eventId"]


@then("the publish is recorded but not live")
def recorded_not_live(context) -> None:
    assert context.result["ok"] is True and context.result["live"] is False, context.result


@then("the publish succeeds")
def succeeds(context) -> None:
    assert context.result["ok"] is True, context.result


@then("the publish succeeds and the page is live")
def succeeds_live(context) -> None:
    assert context.result["ok"] is True and context.result["live"] is True, context.result


@then("the problem is logged without its detail")
def logged(context) -> None:
    assert "item_published_announce_failed" in context.output, context.output
    assert "secret-looking detail" not in context.output
