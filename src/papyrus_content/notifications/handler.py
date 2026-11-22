"""Lambda entry points of the ``notifications`` plugin. Each builds its dependencies once per container.

* ``router``     direct (asynchronous) invocations: Caducus events handed over by an email Delivery's attempt (``announcements/email_channel.py``), reader actions from the CMS routes (Caducus's public audience)
* ``email``      the site's email queue: one queued delivery, or one fan-out page of a public kind, per message
* ``x``         the site's x queue: one queued announcement post per message (``x_sender.py``); only where the site is wired for X
* ``broadcast``  direct (synchronous) invocations by the shared procedure runner: submit, read or withdraw one X announcement through this site's Caducus wiring
                 (``announcements/remote_broadcaster.py``); only where the site is wired for X
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


def x_with(rt: Runtime, event: Mapping[str, Any]) -> dict[str, Any]:
    from .x_sender import handle_batch

    if rt.x is None:
        raise RuntimeError("This function is not wired for X (X_QUEUE_URL is not set), so it cannot post.")
    return handle_batch(rt.store, rt.x, event, posted=delivery_settler(rt))


def delivery_settler(rt: Runtime, deliveries: Any = None) -> Any:
    """Closes the site's Delivery for a posted event from Caducus's record, read through this site's broadcaster. The Deliveries are the site's own records, read and
    written with this function's role (``PAPYRUS_GRAPHQL_ENDPOINT``, the operator lane). A function without the site's API settles nothing."""
    import os

    from papyrus_content.announcements.settle_after_post import settle_after_post
    from papyrus_content.announcements.x_channel import XChannel

    if rt.broadcaster is None or (deliveries is None and not os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT")):
        return None
    made: dict[str, Any] = {}

    def site_deliveries() -> Any:
        if deliveries is not None:
            return deliveries
        if "deliveries" not in made:
            from papyrus_content.announcements.deliveries import Deliveries
            from papyrus_content.graphql_authoring import create_authoring_client

            made["deliveries"] = Deliveries(create_authoring_client()[0])
        return made["deliveries"]

    return lambda event_id: settle_after_post(site_deliveries(), XChannel(rt.broadcaster), event_id)


def x(event: Mapping[str, Any], context: Any = None) -> dict[str, Any]:
    from .runtime import runtime

    return x_with(runtime(), event)


def broadcast_with(rt: Runtime, event: Mapping[str, Any]) -> dict[str, Any]:
    """One Broadcaster call for the runner. A refusal is an answer (``ok`` false, with its kind), so the runner raises the same error the in-process Broadcaster would."""
    from papyrus_content.announcements.caducus_errors import error_code
    from papyrus_content.announcements.records import RecordError
    from papyrus_content.announcements.remote_broadcaster import view_payload

    if rt.broadcaster is None:
        return {"ok": False, "error": "record", "message": "This site is not wired for X (X_QUEUE_URL is not set), so nothing can be posted."}
    operation = event.get("operation")
    try:
        if operation == "submit":
            rt.broadcaster.submit(account_id=str(event["accountId"]), event_id=str(event["eventId"]), text=str(event["text"]), url=str(event["url"]))
            return {"ok": True}
        if operation == "delivery":
            return {"ok": True, "delivery": view_payload(rt.broadcaster.delivery(str(event["eventId"])))}
        if operation == "withdraw":
            return {"ok": True, "delivery": view_payload(rt.broadcaster.withdraw(str(event["eventId"]), by=str(event.get("by") or "the procedure runner")))}
    except KeyError as missing:
        return {"ok": False, "error": "record", "message": f"The request is missing {missing.args[0]}."}
    except RecordError as error:
        return {"ok": False, "error": error_code(error), "message": str(error)}
    return {"ok": False, "error": "record", "message": f"Unknown broadcast operation {operation!r}."}


def broadcast(event: Mapping[str, Any], context: Any = None) -> dict[str, Any]:
    from .runtime import runtime

    return broadcast_with(runtime(), event)


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
