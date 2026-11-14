"""Tell the site's ``newsletter`` function (PPY-d415c0) and its ``notifications`` function (PPY-38be08) that an item was
published, so alert lists can raise an alert and Caducus can announce the story.

Both publish paths end here: the newsroom's ``publishItem`` action and the projection task the CLI schedules on the same
function. The caller decides *whether* this is a real publish (``PublishResult.changed``); this module only delivers the
messages and never lets a problem reach the publish.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Mapping

from .publishing import PUBLISHED_ID_PREFIX

NEWSLETTER_FUNCTION_ENV = "PAPYRUS_NEWSLETTER_FUNCTION"
NOTIFICATIONS_FUNCTION_ENV = "PAPYRUS_NOTIFICATIONS_FUNCTION"
TASK_NAME = "item-published"
NOTIFICATIONS_TASK_NAME = "story-published"
#: The Caducus event id of a published story: the lineage, so a republish of the same story dedupes in the site's table.
STORY_EVENT_PREFIX = "story.published:"
#: The key a projection task carries when its item was just published (``{"publishedItemId": ...}``).
PUBLISHED_TASK_KEY = "published"
CONNECT_TIMEOUT_SECONDS = 2
READ_TIMEOUT_SECONDS = 3


def newsletter_function(environment: Mapping[str, str] = os.environ) -> str:
    return (environment.get(NEWSLETTER_FUNCTION_ENV) or "").strip()


def notifications_function(environment: Mapping[str, str] = os.environ) -> str:
    return (environment.get(NOTIFICATIONS_FUNCTION_ENV) or "").strip()


def story_event_id(lineage_id: str) -> str:
    return STORY_EVENT_PREFIX + lineage_id


def lineage_of(item_id: str, published_item_id: str | None) -> str:
    """The lineage id: ``published-<lineage>`` names it; an unexpected shape falls back to the item id."""
    if published_item_id and published_item_id.startswith(PUBLISHED_ID_PREFIX) and len(published_item_id) > len(PUBLISHED_ID_PREFIX):
        return published_item_id[len(PUBLISHED_ID_PREFIX) :]
    return item_id


def _invoke(function_name: str, payload: dict[str, Any]) -> None:
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "lambda",
        config=Config(connect_timeout=CONNECT_TIMEOUT_SECONDS, read_timeout=READ_TIMEOUT_SECONDS, retries={"max_attempts": 1}),
    )
    client.invoke(FunctionName=function_name, InvocationType="Event", Payload=json.dumps(payload).encode("utf-8"))


def announce_published(
    item_id: str,
    published_item_id: str | None = None,
    *,
    environment: Mapping[str, str] = os.environ,
    invoke: Callable[[str, dict[str, Any]], None] = _invoke,
) -> dict[str, Any]:
    """Asynchronously invoke the newsletter function (``item-published``) and the notifications function
    (``story-published``). Never raises; each function is tried even if the other failed.

    A plugin that is off (its environment variable unset) is a no-op.
    """
    targets: list[tuple[str, str]] = []
    if newsletter_function(environment):
        targets.append((newsletter_function(environment), TASK_NAME))
    if notifications_function(environment):
        targets.append((notifications_function(environment), NOTIFICATIONS_TASK_NAME))
    if not targets:
        return {"ok": True, "skipped": "not-configured"}
    failure: str | None = None
    for function_name, task in targets:
        try:
            lineage = lineage_of(item_id, published_item_id)
            payload: dict[str, Any] = {"task": task, "itemId": item_id, "lineageId": lineage}
            if task == NOTIFICATIONS_TASK_NAME:
                payload["eventId"] = story_event_id(lineage)
            if published_item_id:
                payload["publishedItemId"] = published_item_id
            invoke(function_name, payload)
        except Exception as error:  # noqa: BLE001 - an alert problem never fails or slows the publish
            print(json.dumps({"event": "item_published_announce_failed", "itemId": item_id, "task": task, "error": type(error).__name__}))
            failure = failure or type(error).__name__
    return {"ok": False, "error": failure} if failure else {"ok": True, "announced": item_id}
