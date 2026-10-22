"""SES event notifications (through the SNS topic) and the CloudWatch alarms that pause sending.

A Lambda subscribed to an SNS topic receives ``{"Records": [{"EventSource": "aws:sns", "Sns": {"Message": "<json>"}}]}``.
The message is either an SES event (``eventType``) or a CloudWatch alarm state change (``AlarmName``).
Events map back to a subscriber through the message tags ``sub`` (subscriber id), ``issue`` and ``list``; an event without
a valid ``sub`` tag, or for another site, is ignored.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from . import records
from .manage import apply_unsubscribe
from .pause import pause_site
from .rate import log_metric
from .store import Conflict

HID = re.compile(r"[0-9a-f]{32}")
TAG_VALUE = re.compile(r"[A-Za-z0-9_.-]{1,64}")

# event type -> (ledger status, statuses that must not be overwritten, issue counter)
LEDGER_EFFECTS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "Delivery": ("delivered", ("delivered", "bounced", "complained"), "delivered"),
    "Complaint": ("complained", ("complained",), "complained"),
    "Reject": ("failed", ("failed", "bounced", "complained"), "failed"),
    "Rendering Failure": ("failed", ("failed", "bounced", "complained"), "failed"),
}
LOGGED_TYPES = ("Delivery", "Bounce", "Complaint", "Reject", "Rendering Failure", "DeliveryDelay")


def _tag(mail: Mapping[str, Any], name: str) -> str:
    values = (mail.get("tags") or {}).get(name) or []
    value = values[0] if isinstance(values, list) and values else values
    return value if isinstance(value, str) and TAG_VALUE.fullmatch(value) else ""


def _event_type(message: Mapping[str, Any]) -> str:
    kind = str(message.get("eventType") or message.get("notificationType") or "")
    return "Rendering Failure" if kind.replace(" ", "") == "RenderingFailure" else kind


def alarm_names(site_id: str) -> tuple[str, str]:
    return (f"papyrus-newsletter-{site_id}-bounce-rate", f"papyrus-newsletter-{site_id}-complaint-rate")


def handle_ses_event(svc: Any, message: Mapping[str, Any]) -> str:
    """Apply one SES event. Returns what happened (``ignored`` for an event that is not ours)."""
    mail = message.get("mail") or {}
    hid, issue, list_id = _tag(mail, "sub"), _tag(mail, "issue"), _tag(mail, "list")
    site = _tag(mail, "site")
    event_type = _event_type(message)
    if not HID.fullmatch(hid) or (site and site != svc.settings.site_id) or event_type not in LOGGED_TYPES:
        return "ignored"
    now = svc.clock()
    store = svc.store
    detail = ""
    counter = ""
    if event_type == "Bounce":
        bounce_type = str((message.get("bounce") or {}).get("bounceType", ""))
        detail = bounce_type
        if bounce_type == "Permanent":
            _suppress(svc, hid, "bounce", issue, now)
            if issue and records.update_ledger(store, issue, hid, "bounced", ("bounced", "complained"), now):
                counter = "bounced"
        else:
            counter = "softBounced"  # only counted: no suppression, no ledger change
    elif event_type == "Complaint":
        _suppress(svc, hid, "complaint", issue, now)
        if issue and records.update_ledger(store, issue, hid, "complained", ("complained",), now):
            counter = "complained"
    elif event_type in LEDGER_EFFECTS:
        status, unless, name = LEDGER_EFFECTS[event_type]
        if issue and records.update_ledger(store, issue, hid, status, unless, now):
            counter = name
    if issue and counter:
        records.add_issue_counter(store, issue, counter)
    message_id = _tag_free_id(mail.get("messageId"))
    records.put_event(store, message_id=message_id, event_type=event_type.replace(" ", ""), hid=hid, issue=issue, list_id=list_id, detail=detail, now=now)
    return event_type.lower().replace(" ", "_")


def _tag_free_id(value: Any) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.@=+-]{1,128}", value) else "unknown"


def _suppress(svc: Any, hid: str, reason: str, issue: str, now: float) -> None:
    """A permanent bounce or a complaint: never mail this address again, and leave every list."""
    records.put_suppression(svc.store, hid, reason, now, issue)
    for _attempt in range(3):
        try:
            apply_unsubscribe(svc, hid, None, f"suppressed:{reason}")  # no profile (erased): the suppression row still protects
            return
        except Conflict:
            continue


def handle_alarm(svc: Any, message: Mapping[str, Any]) -> str:
    name = str(message.get("AlarmName", ""))
    if name not in (svc.settings.alarm_names or alarm_names(svc.settings.site_id)) or message.get("NewStateValue") != "ALARM":
        return "ignored"
    reason = f"{name}: {message.get('NewStateReason', '')}"
    paused = pause_site(svc.store, svc.mailer, reason, svc.clock())
    log_metric(svc.settings.site_id, "SendingPaused", Alarm=name)
    return "paused" if paused else "already_paused"


def handle_sns(svc: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    results: list[str] = []
    for record in event.get("Records") or []:
        sns = record.get("Sns") if isinstance(record, dict) else None
        if not isinstance(sns, dict):
            continue
        try:
            message = json.loads(sns.get("Message", ""))
        except (TypeError, ValueError):
            results.append("unparseable")
            continue
        if not isinstance(message, dict):
            results.append("unparseable")
        elif "AlarmName" in message:
            results.append(handle_alarm(svc, message))
        else:
            results.append(handle_ses_event(svc, message))
    return {"statusCode": 200, "body": {"status": "ok", "results": results}}
