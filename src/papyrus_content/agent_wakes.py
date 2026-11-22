"""Wakes on the per-site queue: how a wake is put on it, and how the runner reads one (PPY-567bf9, slice B1).

Every site has one FIFO queue, `papyrus-<site>-agent-wakes.fifo` (amplify/agents/wake-queue.ts). A wake is one message:

    {"wake": {"key", "agent", "subject", "why", "scope"}, "request": {...the runner's request, without its wake key...}}

* `key` is the wake key (wake_keys.py): what the wake is about, so the same wake can never run twice.
* `agent` is the key's owner: the automation, or `procedure:<key>` when no automation governs the start.
* `subject` is what the wake is about: the record in a change key, `schedule` for a timer, the request id for a person's request.
* `why` is the trigger's own one-line summary, so a person reading the queue or the run record sees the reason in words.
* The **message group** is the agent plus its serial scope (slice B4, PPY-a200ec). The scope comes from the definition's `serialBy`, which the wake's trigger
  carries: `subject` (the default for a wake no definition governs) makes the subject the scope, so wakes about one subject run one after the other and wakes
  about different subjects run at the same time; `agent` makes one scope for the whole agent, so its wakes run one at a time whatever they are about;
  `key:<name>` makes the scope the value the trigger names in `serialKey` (a channel account, say), and a trigger without one is not a wake.
* The **deduplication id** is the wake key. SQS limits an id to 128 characters from a fixed set and a key may be 1000, so both ids are the
  SHA-256 digest of their text: the same text is always the same id, and two texts never share one.

A wake that cannot be put on the queue raises: the caller records the start as failed. Nothing starts the runner another way.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

from . import wake_keys

QUEUE_NAME_PREFIX, QUEUE_NAME_SUFFIX = "papyrus-", "-agent-wakes.fifo"
SITE_ID_CHARACTERS = 40          # what amplify/agents/wake-queue.ts keeps of a brand id: a FIFO queue name is at most 80 characters
MAX_WHY_CHARACTERS = 500
SERIAL_SUBJECT, SERIAL_AGENT, SERIAL_KEY_PREFIX = "subject", "agent", "key:"
AGENT_SCOPE = "*"                # the scope of a whole agent: no subject id is this
WAKE_FIELDS = ("key", "agent", "subject", "why", "scope")
SQS_SOURCE = "aws:sqs"


class WakeError(ValueError):
    """A wake that cannot be sent, or a queue message that is not a wake."""


def site_id(identifier: object) -> str:
    """The site's id as the queue name keeps it: what `sanitizeAwsName(brandId, 40)` makes of the brand id (the publication id is the brand id)."""
    text = re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]", "-", str(identifier or "").lower())).strip("-")[:SITE_ID_CHARACTERS]
    if not text:
        raise WakeError(f"a wake queue is named after the site, which must contain a letter or digit (got {identifier!r})")
    return text


def queue_name(identifier: object) -> str:
    return f"{QUEUE_NAME_PREFIX}{site_id(identifier)}{QUEUE_NAME_SUFFIX}"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scope_of(trigger: dict, subject: str) -> str:
    """The serial scope of a wake: what, with the agent, makes its message group (`serialBy` in the trigger; no `serialBy` means `subject`)."""
    serial = trigger.get("serialBy") or SERIAL_SUBJECT
    if serial == SERIAL_SUBJECT:
        return subject
    if serial == SERIAL_AGENT:
        return AGENT_SCOPE
    if isinstance(serial, str) and serial.startswith(SERIAL_KEY_PREFIX) and len(serial) > len(SERIAL_KEY_PREFIX):
        value = str(trigger.get("serialKey") or "").strip()
        if not value:
            raise WakeError(f"a wake serial by {serial!r} needs its trigger to name the {serial[len(SERIAL_KEY_PREFIX):]} (serialKey) it runs one at a time for")
        return f"{serial[len(SERIAL_KEY_PREFIX):]}={value}"
    raise WakeError(f"serialBy must be subject, agent or key:<name> (got {serial!r})")


def wake_of(request: dict) -> dict[str, str]:
    """`{key, agent, subject, why, scope}` for a runner request, from its wake key, its trigger's summary and its trigger's serial scope."""
    try:
        key = wake_keys.checked(request.get("wakeKey"))
    except wake_keys.InvalidWakeKey as invalid:
        raise WakeError(str(invalid)) from invalid
    parts = key.split(wake_keys.SEPARATOR)
    subject = parts[1] if len(parts) == 4 else (wake_keys.SCHEDULE if parts[1] == wake_keys.SCHEDULE else parts[2])
    trigger = request.get("trigger") if isinstance(request.get("trigger"), dict) else {}
    why = str(trigger.get("summary") or "").strip()
    if not why:
        raise WakeError(f"wake {key!r} has no reason: its trigger needs a summary that says why it started")
    return {"key": key, "agent": parts[0], "subject": subject, "why": why[:MAX_WHY_CHARACTERS], "scope": scope_of(trigger, subject)}


def group_id(wake: dict) -> str:
    return digest(f"{wake['agent']}{wake_keys.SEPARATOR}{wake['scope']}")


def deduplication_id(wake: dict) -> str:
    return digest(wake["key"])


def message_body(request: dict) -> str:
    wake = wake_of(request)
    return json.dumps({"wake": wake, "request": {name: value for name, value in request.items() if name != "wakeKey"}}, sort_keys=True, default=str)


def send_wake(sqs, queue_url: str, request: dict, *, deduplication: str | None = None) -> dict[str, str]:
    """Puts one wake on the queue and returns it. A wake whose key is already on the queue inside SQS's five-minute window is dropped by the queue;
    after that the run record's own condition drops it (the runner answers `duplicate`). ``deduplication`` names a sending of a wake that already has its run
    record, such as releasing a wake that waited for the budget (spend_stop.py): that sending is its own message, and the record still makes it one run."""
    wake = wake_of(request)
    sqs.send_message(QueueUrl=queue_url, MessageBody=message_body(request), MessageGroupId=group_id(wake),
                     MessageDeduplicationId=digest(deduplication) if deduplication else deduplication_id(wake))
    return wake


def wake_sender(sqs: Any = None) -> Callable[[dict], None]:
    """The one way a caller starts a procedure: `send(request)` puts the request's wake on its site's queue. The queue is found by name
    from the request's publication id and looked up once. A site whose queue does not exist yet raises, and the caller records the start as failed."""
    urls: dict[str, str] = {}

    def send(request: dict, deduplication: str | None = None) -> None:
        client = sqs
        if client is None:
            import boto3  # provided by the Lambda runtime and the operator's environment
            client = boto3.client("sqs")
        name = queue_name(request.get("publicationId"))
        if name not in urls:
            urls[name] = client.get_queue_url(QueueName=name)["QueueUrl"]
        send_wake(client, urls[name], request, deduplication=deduplication)
    return send


def request_from_event(event: Any) -> dict:
    """The runner's request from the queue's event: exactly one message, a well-formed wake whose request agrees with it.
    Anything else raises, so the message stays on the queue and reaches the dead-letter queue after its second delivery."""
    records = event.get("Records") if isinstance(event, dict) else None
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict) or records[0].get("eventSource") != SQS_SOURCE:
        raise WakeError("the procedure runner is started by its wake queue, one message at a time; this event is not one")
    try:
        body = json.loads(records[0].get("body") or "")
    except (TypeError, ValueError) as invalid:
        raise WakeError(f"the wake message is not JSON: {invalid}") from invalid
    wake, request = (body.get("wake"), body.get("request")) if isinstance(body, dict) else (None, None)
    if not isinstance(wake, dict) or not isinstance(request, dict):
        raise WakeError("the wake message needs a wake and a request")
    request = {**request, "wakeKey": wake.get("key")}
    if wake_of(request) != {name: wake.get(name) for name in WAKE_FIELDS} or set(wake) != set(WAKE_FIELDS):
        raise WakeError("the wake message's agent, subject, reason or scope does not match its wake key and trigger")
    return request


def receive_count(event: Any) -> int:
    """Which delivery of its message this is, as the queue reports it (`ApproximateReceiveCount`): 1 for the first, 2 for the one that settles."""
    attributes = event["Records"][0].get("attributes") or {}
    return int(attributes.get("ApproximateReceiveCount") or 1)
