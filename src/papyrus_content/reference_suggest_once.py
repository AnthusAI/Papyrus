"""One related-items check per Reference, started by the event that makes it possible (docs/monitoring-cloud.md#vector-index-and-suggestions).

A check needs the Reference's own summary vector, so the trigger is the moment that vector is stored: new, or rewritten because the text it was made from changed
(``vector_index`` calls ``on_summary_written`` with the Reference and the hash of that text). The router's vector pass puts one message per such vector on the
suggestion queue; this module's ``handle_queue`` takes them off and calls ``reference_suggestions.suggest_for`` for that one Reference. Nothing else asks: no
schedule, no plan, no backlog, no walk of the corpus. A vote, a star, a metadata edit and an accept or reject start no check (they do not store a summary vector).

The record that a Reference was checked is one row in the router's own table: ``pk=MONITOR#<id> sk=STATE#suggested#<publicationId>#<lineageId>`` holding the hash of
the text that was checked, when, and what was written. A message whose hash equals the record's is dropped (a repeated message, a repeated run), so a Reference is
checked once per version of its text. No index on the Reference table is involved.

A failure is retried by the queue: SQS redelivers a message that was not deleted, up to the queue's ``maxReceiveCount``, and then moves it to the dead-letter queue,
which an alarm watches (infra/monitoring/papyrus-monitoring.yaml). Every outcome is one JSON log line, ``{"suggestOnce": "checked"|"already"|"failed"|"noVector"}``.
``unchecked_references`` and ``queue_unchecked`` are the by-hand command that finds the References with no record and queues them (docs/monitoring-cloud.md)."""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

CHECK_SORT_KEY_PREFIX = "STATE#suggested#"
MESSAGE_VERSION = 1
CALIBRATION_SECONDS = 6 * 3600   # how long a warm container keeps the site's calibration; it is read only when a check is about to run
SQS_BATCH = 10
WRITTEN_OUTCOMES = ("created", "updated")


def check_prefix(publication_id: str) -> str:
    return f"{CHECK_SORT_KEY_PREFIX}{publication_id}#"


def check_sort_key(publication_id: str, lineage_id: str) -> str:
    return f"{check_prefix(publication_id)}{lineage_id}"


def suggestion_message(monitor_id: str, publication_id: str, lineage_id: str, content_hash: str, *, audit: bool = False) -> dict[str, Any]:
    """The queue message for one Reference. ``contentHash`` is the hash of the text its summary vector was made from; ``audit`` marks one queued by the by-hand
    command, for which a Reference with no vector yet is not a failure."""
    return {"v": MESSAGE_VERSION, "monitorId": monitor_id, "publicationId": publication_id, "referenceLineageId": lineage_id, "contentHash": content_hash, **({"audit": True} if audit else {})}


def send_messages(sqs: Any, queue_url: str, messages: Iterable[dict[str, Any]]) -> int:
    """Sends the messages ten to a request; raises if the queue refuses any (the caller reports it, and the by-hand command finds those References). Returns how many were sent."""
    batch: list[dict[str, Any]] = []
    sent = 0
    for message in messages:
        batch.append(message)
        if len(batch) == SQS_BATCH:
            sent += _send_batch(sqs, queue_url, batch)
            batch = []
    if batch:
        sent += _send_batch(sqs, queue_url, batch)
    return sent


def _send_batch(sqs: Any, queue_url: str, batch: list[dict[str, Any]]) -> int:
    response = sqs.send_message_batch(QueueUrl=queue_url, Entries=[{"Id": str(number), "MessageBody": json.dumps(message, separators=(",", ":"))} for number, message in enumerate(batch)])
    failed = response.get("Failed") or []
    if failed:
        raise RuntimeError(f"the suggestion queue refused {len(failed)} of {len(batch)} messages ({failed[0].get('Code')})")
    return len(batch)


def queue_sender(monitor_id: str, publication_id: str, sqs: Any, queue_url: str) -> Callable[[list[dict[str, Any]]], None]:
    """The ``on_summary_written`` hook of the vector pass for one publication: one message per stored summary vector."""
    def send(entries: list[dict[str, Any]]) -> None:
        send_messages(sqs, queue_url, [suggestion_message(monitor_id, publication_id, entry["referenceLineageId"], entry["contentHash"]) for entry in entries if entry.get("referenceLineageId")])

    return send


class Calibrations:
    """A warm container's calibration per site, read when a check is about to run and kept ``CALIBRATION_SECONDS`` (the cut changes with editors' decisions, slowly)."""

    def __init__(self, loader: Callable[[Any], Any], clock: Callable[[], float] = time.monotonic) -> None:
        self.loader, self.clock, self.kept = loader, clock, {}

    def get(self, endpoint: str, client: Any) -> Any:
        held = self.kept.get(endpoint)
        if held is None or self.clock() - held[0] > CALIBRATION_SECONDS:
            held = (self.clock(), self.loader(client))
            self.kept[endpoint] = held
        return held[1]


def check_once(store: Any, monitor_id: str, publication: dict[str, Any], message: dict[str, Any], *, client: Any, provider: Any, calibration: Callable[[], Any],
               suggester: Callable[..., dict], now: datetime) -> str:
    """The one check for one message: ``already`` (a record says this text was checked), ``noVector`` (an audit message, and the Reference has no summary vector yet:
    nothing recorded, nothing wrong), or ``checked`` (suggestions written and the record stored). Raises when the check cannot be made, so the queue tries again."""
    from .monitoring_cloud import pk

    publication_id, lineage = publication["publicationId"], str(message["referenceLineageId"])
    content_hash = str(message.get("contentHash") or "")
    sort_key = check_sort_key(publication_id, lineage)
    record = store.get_any(monitor_id, sort_key)
    if record and (not content_hash or record.get("contentHash") == content_hash):
        return "already"
    outcome = suggester(client, provider, lineage, corpus_id=publication["corpusId"], calibration=calibration(), now=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    if outcome.get("skipped"):
        if message.get("audit"):
            return "noVector"
        raise RuntimeError(f"no reference_summary vector for {lineage} right after it was stored")
    written = sum(1 for entry in (*outcome.get("references", []), *outcome.get("concepts", [])) if entry.get("outcome") in WRITTEN_OUTCOMES)
    store.put_any(monitor_id, {"pk": pk(monitor_id), "sk": sort_key, "publicationId": publication_id, "referenceLineageId": lineage, "contentHash": content_hash,
                               "checkedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "written": written})
    return "checked"


def handle_queue(store: Any, event: dict[str, Any], *, config_for: Callable[[str], dict[str, Any] | None], appsync: Callable[..., Any],
                 provider_for: Callable[[dict[str, Any]], Any], calibrations: Calibrations, suggester: Callable[..., dict], now: datetime | None = None,
                 emit: Callable[[str], None] = print) -> dict[str, Any]:
    """An SQS batch: one check per message. Returns the Lambda's partial-batch response: the messages that failed stay on the queue and are delivered again, up to
    the queue's receive limit, then go to its dead-letter queue."""
    moment = now or datetime.now(timezone.utc)
    failures: list[dict[str, str]] = []
    for record in event.get("Records") or []:
        message_id, line = record.get("messageId"), {}
        try:
            message = json.loads(record["body"])
            monitor_id, publication_id = str(message["monitorId"]), str(message["publicationId"])
            line = {"monitorId": monitor_id, "publicationId": publication_id, "referenceLineageId": message.get("referenceLineageId")}
            config = config_for(monitor_id)
            publication = next((entry for entry in (config or {}).get("publications", []) if entry["publicationId"] == publication_id), None)
            if publication is None:
                raise ValueError(f"unknown publication {publication_id!r} for monitor {monitor_id}")
            client = appsync(publication["appsyncEndpoint"], publication["tenantId"]) if publication.get("tenantId") else appsync(publication["appsyncEndpoint"])
            policy_provider = provider_for(publication)
            if policy_provider is None:
                raise RuntimeError("the publication has no usable vector index")
            status = check_once(store, monitor_id, publication, message, client=client, provider=policy_provider,
                                calibration=lambda: calibrations.get(publication["appsyncEndpoint"], client), suggester=suggester, now=moment)
            emit(json.dumps({"suggestOnce": status, **line}))
        except Exception as error:  # noqa: BLE001 - the queue redelivers it, and the dead-letter queue keeps it after the last try
            failures.append({"itemIdentifier": str(message_id)})
            emit(json.dumps({"suggestOnce": "failed", "reason": f"{type(error).__name__}: {str(error)[:300]}", **line}))
    return {"batchItemFailures": failures}


# --- the by-hand command for References that were never checked ----------------------------------------------------------------------------------

def unchecked_references(client: Any, store: Any, monitor_id: str, publication: dict[str, Any]) -> list[str]:
    """Lineage ids of the accepted and pending References with no check recorded. THIS READS THE WHOLE REFERENCE LIST of the publication (the status index, a page of 100
    at a time) and the record rows of the router's table (one prefix query): it is a scan, run by hand once, and nothing schedules it."""
    prefix = check_prefix(publication["publicationId"])
    checked = {str(row["sk"]).removeprefix(prefix) for row in store.query_prefix(monitor_id, prefix)}
    missing: list[str] = []
    for status in ("accepted", "pending"):
        for row in client.list_by_index("referencesByCurationStatusKey", f"{publication['corpusId']}#{status}"):
            lineage = str(row.get("lineageId") or row.get("id") or "")
            if lineage and row.get("versionState", "current") == "current" and lineage not in checked:
                missing.append(lineage)
    return sorted(set(missing))


def queue_unchecked(client: Any, store: Any, monitor_id: str, publication: dict[str, Any], *, write: bool, sqs: Any = None, queue_url: str | None = None) -> dict[str, Any]:
    """The by-hand command: the References with no check recorded, and with ``write`` True (never by default) one audit message each on the suggestion queue. A Reference
    with no summary vector yet is answered ``noVector`` and left unrecorded, so a later run finds it again."""
    lineages = unchecked_references(client, store, monitor_id, publication)
    result: dict[str, Any] = {"publicationId": publication["publicationId"], "unchecked": len(lineages), "write": bool(write), "queued": 0, "scanned": "all accepted and pending References"}
    if write and lineages:
        if sqs is None or not queue_url:
            raise RuntimeError("no suggestion queue is configured (SUGGEST_QUEUE_URL)")
        result["queued"] = send_messages(sqs, queue_url, [suggestion_message(monitor_id, publication["publicationId"], lineage, "", audit=True) for lineage in lineages])
    return result
