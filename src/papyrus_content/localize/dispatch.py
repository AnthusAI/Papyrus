"""The dispatcher of translate-on-publish: it reacts to changes of the desired-state records (``desired_state.py``) on the site's own runner.

A DynamoDB stream on ``LocalizationRequest`` invokes it (``amplify/functions/localization-dispatch``). Each batch does two things, once per change:

* **start** the runs still waiting. ``wanted`` records are read through the ``localizationRequestsByState`` index, oldest first, and each is started through
  the Automation it names, by the same code as "Run now" (``automations.run_now``): the automation's limits, the router's publication and model key all
  apply. A record is claimed with a conditional write (``wanted`` to ``started``) before its run is invoked, so two overlapping batches never start one
  run twice. When the automation is at its limit of runs at a time the rest stay ``wanted``: the next record to change (a run that ends is one) starts them.
  A record naming no automation (a person's ``papyrus stories localize`` run in process) is not the dispatcher's and is left alone.
* **publish** what a run saved cleanly. A record that just became ``saved`` with ``publish`` set asks the content-actions function to publish its
  translation (task ``publish-localization``), which publishes through the ordinary path and builds the page when the language is public.

It never calls a model and never publishes by itself: the publish is the content-actions function's, under ``publish.publishable``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from ..automations import AutomationDeferred, AutomationError, read_record, run_now
from . import desired_state

ACTOR = "translation on publish"
PUBLISH_TASK = "publish-localization"
#: States a run ends in (or that free its place): the stream event for any of them is a reason to start what is waiting.
ENDED = ("saved", "held", "failed", "stopped", "unchanged", "waiting", "published")


def decode_image(image: dict[str, Any] | None) -> dict[str, Any] | None:
    """A DynamoDB stream image (attribute values) as a plain row: whole numbers as ints, the rest as the stored types."""
    if not image:
        return None
    from boto3.dynamodb.types import TypeDeserializer

    deserializer = TypeDeserializer()
    row = {name: deserializer.deserialize(value) for name, value in image.items()}
    return {name: int(value) if hasattr(value, "as_integer_ratio") and not isinstance(value, bool) and value == int(value) else value for name, value in row.items()}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_input(row: dict[str, Any]) -> dict[str, Any]:
    return {"story": row["languageGroupId"], "language": row["language"], "ceiling_usd": 0, "source_version": int(row.get("sourceVersionNumber") or 0),
            "automation_id": row["automationId"]}


def drain(client, *, reader, writer, invoke, site_endpoint: str | None, now: str | None = None) -> list[dict[str, Any]]:
    """Start the waiting runs, oldest first, until the automation has no room. One outcome per record looked at."""
    outcomes: list[dict[str, Any]] = []
    automations: dict[str, dict[str, Any] | None] = {}
    for row in desired_state.wanted(client):
        automation_id = row.get("automationId")
        if not automation_id:
            continue   # a person's run in process: not ours to start
        outcome = {"id": row["id"], "automationId": automation_id}
        outcomes.append(outcome)
        if automation_id not in automations:
            found = client.get_record("Automation", automation_id)
            automations[automation_id] = read_record(found) if found else None
        automation = automations[automation_id]
        stamp = now or _now()
        if automation is None:
            desired_state.record_outcome(client, row, state="failed", reason=f"The automation {automation_id} does not exist. Create it (docs/automations.md) and run `papyrus stories localize --all`.")
            outcome["status"] = "failed"
            continue
        claimed = client.update_record_if(desired_state.MODEL, {"id": row["id"], "state": "started", "reason": None, "updatedAt": stamp},
                                          {"state": {"eq": "wanted"}, "sourceContentHash": {"eq": row["sourceContentHash"]}})
        if not claimed:
            outcome["status"] = "claimed elsewhere"
            continue
        try:
            started = run_now(automation, reader=reader, writer=writer, invoke=invoke, actor=ACTOR, supplied_input=_row_input(row),
                              site_endpoint=site_endpoint, now=stamp)
        except AutomationDeferred as error:   # no room: put it back, and leave the rest waiting too
            client.update_record_if(desired_state.MODEL, {"id": row["id"], "state": "wanted", "reason": str(error)[:1000], "updatedAt": stamp},
                                    {"state": {"eq": "started"}, "sourceContentHash": {"eq": row["sourceContentHash"]}})
            outcome.update(status="deferred", reason=str(error))
            break
        except AutomationError as error:
            client.update_record_if(desired_state.MODEL, {"id": row["id"], "state": "failed", "reason": str(error)[:1000], "updatedAt": stamp},
                                    {"state": {"eq": "started"}, "sourceContentHash": {"eq": row["sourceContentHash"]}})
            outcome.update(status="failed", reason=str(error))
            continue
        outcome.update(status="started", key=started["key"])
    return outcomes


def _wants_a_start(image: dict[str, Any]) -> bool:
    """A fresh request (a ``wanted`` row whose ``requestedAt`` is new: the dispatcher's own put-back of a start that found no room keeps it, so it never
    wakes itself) or a run that ended (its place is free)."""
    new, old = image["new"], image.get("old") or {}
    if new.get("state") == "wanted":
        return new.get("requestedAt") != old.get("requestedAt") or old.get("state") is None
    return new.get("state") in ENDED and old.get("state") != new.get("state")


def handle_changes(images: list[dict[str, Any]], client, *, reader, writer, invoke, invoke_publish: Callable[[dict[str, Any]], None],
                   site_endpoint: str | None, now: str | None = None) -> dict[str, Any]:
    """One stream batch. ``images`` are ``{"old": row or None, "new": row or None}`` (a deleted row has no new image and changes nothing)."""
    published = []
    for image in images:
        new, old = image.get("new"), image.get("old") or {}
        if not new:
            continue
        if new.get("state") == "saved" and new.get("publish") is True and old.get("state") != "saved":
            invoke_publish({"task": PUBLISH_TASK, "requestId": new["id"]})
            published.append(new["id"])
    wants_start = any(_wants_a_start(image) for image in images if image.get("new"))
    started = drain(client, reader=reader, writer=writer, invoke=invoke, site_endpoint=site_endpoint, now=now) if wants_start else []
    return {"publishRequested": published, "started": started}
