"""Lambda entry points of the ``notifications`` plugin. Each builds its dependencies once per container.

* ``router``     direct (asynchronous) invocations: Caducus events handed over by an email Delivery's attempt (``announcements/email_channel.py``), reader actions from the CMS routes (Caducus's public audience)
* ``email``      the site's email queue: one queued delivery, or one fan-out page of a public kind, per message
* ``flush``      every minute: groups whose window ended
* ``ses_events`` EventBridge, SES events of the site's configuration set for mail this site sent
* ``pause``      EventBridge, the bounce and complaint alarms: turns sending off (only on a site without the newsletter)
"""

from __future__ import annotations

from typing import Any, Mapping

from . import public
from .pause import handle_alarm
from .runtime import Runtime
from .sending import apply_ses_event
from .settings import Settings


def _ignored(reason: str) -> dict[str, Any]:
    return {"status": "ignored", "reason": reason}


def route(rt: Runtime, event: Mapping[str, Any]) -> dict[str, Any]:
    if event.get("action") in public.READER_ACTIONS:
        return public.handle(rt.audience, rt.keys, rt.legacy.translate(event) if rt.legacy else event)
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
