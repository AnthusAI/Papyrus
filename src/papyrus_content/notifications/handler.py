"""Lambda entry points of the ``notifications`` plugin. Each builds its dependencies once per container.

* ``router``     direct (asynchronous) invocations: ``story-published`` from a publish, reader actions from the CMS routes (Caducus's public audience)
* ``email``      the site's email queue: one queued delivery, or one fan-out page of a public kind, per message
* ``flush``      every minute: groups whose window ended
* ``ses_events`` EventBridge, SES events of the site's configuration set for mail this site sent
* ``pause``      EventBridge, the bounce and complaint alarms: turns sending off (only on a site without the newsletter)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from . import public
from .events import EVENT_ID, story_published_detail
from .pause import handle_alarm
from .runtime import Runtime
from .sending import apply_ses_event
from .settings import Settings

PUBLISHED_ID_PREFIX = "published-"


def _ignored(reason: str) -> dict[str, Any]:
    return {"status": "ignored", "reason": reason}


def story_published(rt: Runtime, event: Mapping[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """The ``story-published`` task. Raises when Caducus fails, so Lambda's retry finishes (its own dedupe makes that safe)."""
    event_id, lineage_id = event.get("eventId"), event.get("lineageId")
    if not isinstance(event_id, str) or not EVENT_ID.fullmatch(event_id) or not isinstance(lineage_id, str):
        return _ignored("bad_event")
    if event_id != "story.published:" + lineage_id:
        return _ignored("bad_event")
    published_id = event.get("publishedItemId")
    if not isinstance(published_id, str) or not published_id:
        published_id = PUBLISHED_ID_PREFIX + lineage_id
    row = rt.read_item(published_id)
    if row is None or row.get("status") not in (None, "published"):
        return _ignored("not_published")
    occurred_at = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    detail = story_published_detail(row, event_id=event_id, settings=rt.settings, occurred_at=occurred_at)
    if detail is None:
        return _ignored("no_matching_list")
    result = rt.router.handle_detail(detail)
    return {"status": result.outcome, "reason": result.reason, "deliveries": len(result.deliveries)}


def route(rt: Runtime, event: Mapping[str, Any]) -> dict[str, Any]:
    if event.get("task") == "story-published":
        return story_published(rt, event)
    if event.get("action") in public.READER_ACTIONS:
        return public.handle(rt.audience, event)
    return _ignored("unknown_event")


def router(event: Mapping[str, Any], context: Any = None) -> dict[str, Any]:
    from .runtime import runtime

    return route(runtime(), event)


def email_with(rt: Runtime, event: Mapping[str, Any]) -> dict[str, Any]:
    from caducus.notify.handlers.email_sender import handle_batch

    return handle_batch(rt.store, rt.email, event, fan_out=rt.router.fan_out_page)


def email(event: Mapping[str, Any], context: Any = None) -> dict[str, Any]:
    from .runtime import runtime

    return email_with(runtime(), event)


def flush(event: Any = None, context: Any = None) -> dict[str, int]:
    from .runtime import runtime

    return {"sent": runtime().router.tick()}


def ses_events_with(rt: Runtime, event: Mapping[str, Any]) -> str:
    return apply_ses_event(rt.store, rt.log, rt.settings, event, rt.audience)


def ses_events(event: Mapping[str, Any], context: Any = None) -> Mapping[str, Any]:
    from .runtime import runtime

    return {"result": ses_events_with(runtime(), event)}


def pause(event: Mapping[str, Any], context: Any = None) -> Mapping[str, Any]:
    import boto3

    return {"result": handle_alarm(Settings.from_environment(), boto3.client("sesv2"), event)}
