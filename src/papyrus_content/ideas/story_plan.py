"""The monitor-stories queue: one plan a day, one queued step per candidate, one review for the plan (docs/monitoring-cloud.md#monitor-stories-daily).

The daily task used to read the publication, build the context packs and then draft as many ideas as the Lambda's ten minutes allowed; whatever the time
stopped was read again, in full, the next day. Now the day's task is only the PLAN, and the drafting is a queue:

1. ``QueuePlanner`` is the ``plan_sink`` of ``monitor_stories.draft_monitor_stories``. Given the ordered steps (packs and single items, best first) it stores each
   step with everything the draft needs, ONE ROW EACH in the router's table (``STORYPLAN#<publication>#<plan>#E#<n>``: the pack, or the item with its
   connections), stores what the steps share in a head row (the context the single-item writer is shown, the ideas that already exist, the plan's size), and sends
   one message per step to the story queue, a FIFO queue with the publication as the message group, so a publication's steps run one at a time, in order.
2. ``run_step`` is the queue's worker, one step per invocation, well inside the Lambda limit. It reads its row and the head (the existing ideas are in the head, and
   the step's ``ItemStore`` is handed them, so it never lists the site's Items), drafts through the same
   ``draft_monitor_stories`` (``prepared=``) with the retry memory, the point check, the dedupe and the Humanus gate as before, files what it keeps at once, records
   the outcome in a DONE row (``STORYDONE#<publication>#<plan>#<n>``) and adds the ideas to the plan's one review request. A failure that says nothing about the
   Reference (a model error, a filing error) is raised, so SQS tries the step again and, after the last try, parks it in the dead-letter queue, whose alarm tells a
   person; the DONE row of that last try says it failed, so the plan still finishes.
3. The step that completes the plan (``finish_if_complete``) writes the plan's one log line and settles the curation flag, once (a conditional write).

Nothing a step did is lost when another step fails or the day ends: the next plan reads what is filed and what was rejected (the retry memory) and plans only
what remains. A plan that is still running when the next day's task starts is left alone: the task skips it, says so, and plans again when it has finished.

Rows expire (``ttl``) with the queue's own message retention, the real limit on how long a step can wait.
"""
from __future__ import annotations

import base64
import dataclasses
import json
import zlib
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from . import connections as connection_rules, point_check, retry_memory as retry_rules
from .rules import rules_of, validate_idea_rules
from .context_packs import Pack
from .item_signals import ITEM, QueueEntry
from .monitor_stories import MonitoredItem, Prepared, PlanInput, draft_monitor_stories, stored_summary

MESSAGE_KIND = "story-step"
MESSAGE_VERSION = 1
PLAN_TTL_SECONDS = 15 * 24 * 3600   # the story queue keeps a message 14 days; a row outlives it by a day
MAXIMUM_RECEIVES = 3   # the queue's maxReceiveCount (infra/monitoring/papyrus-monitoring.yaml): the third try that fails is the last
MAXIMUM_STEP_COST_USD = 0.50   # one step's guard against one oversized request; a plan is bounded by its number of steps, so there is no cost stop for the plan
TRANSIENT_REASONS = ("model_error", point_check.POINT_CHECK_ERROR)   # invalid reasons that say nothing about the Reference: the step is tried again
SQS_BATCH = 10
INVALID_KEYS = ("referenceId", "packId", "title", "reason", "failures", "message")


# --- the rows ---------------------------------------------------------------------------------------------------------------


def pointer_key(publication_id: str) -> str:
    return f"STATE#storyPlan#{publication_id}"


def plan_prefix(publication_id: str, plan_id: str) -> str:
    return f"STORYPLAN#{publication_id}#{plan_id}#"


def head_key(publication_id: str, plan_id: str) -> str:
    return f"{plan_prefix(publication_id, plan_id)}HEAD"


def final_key(publication_id: str, plan_id: str) -> str:
    return f"{plan_prefix(publication_id, plan_id)}FINAL"


def entry_key(publication_id: str, plan_id: str, number: int) -> str:
    return f"{plan_prefix(publication_id, plan_id)}E#{number:05d}"


def done_prefix(publication_id: str, plan_id: str) -> str:
    return f"STORYDONE#{publication_id}#{plan_id}#"


def done_key(publication_id: str, plan_id: str, number: int) -> str:
    return f"{done_prefix(publication_id, plan_id)}{number:05d}"


def flag_key(publication_id: str) -> str:
    """The row that remembers the publication's curation flag, so the step that finishes a plan reads it by id and does not list the review requests."""
    return f"STATE#storyCuration#{publication_id}"


def encode(value: Any) -> str:
    """A JSON value as compressed text, so a row stays far below DynamoDB's 400 KB and holds only text."""
    return base64.b64encode(zlib.compress(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))).decode("ascii")


def decode(text: str) -> Any:
    return json.loads(zlib.decompress(base64.b64decode(text)).decode("utf-8"))


# --- what a step carries ------------------------------------------------------------------------------------------------------


def item_to_json(item: MonitoredItem) -> dict[str, Any]:
    return dataclasses.asdict(item)


def item_from_json(data: Mapping[str, Any]) -> MonitoredItem:
    return MonitoredItem(**dict(data))


def connections_to_json(connections: connection_rules.Connections) -> dict[str, Any]:
    return {
        "entries": [
            {"handle": entry.handle, "kind": entry.kind, "row": dict(entry.row), "grounding": entry.grounding, "about": entry.about,
             "reference": dataclasses.asdict(entry.reference) if entry.reference is not None else None}
            for entry in connections.entries
        ],
        "found": dict(connections.found), "rating": connections.rating,
    }


def connections_from_json(data: Mapping[str, Any]) -> connection_rules.Connections:
    entries = tuple(
        connection_rules.Connection(
            entry["handle"], entry["kind"], dict(entry["row"]), entry["grounding"],
            connection_rules.Neighbour(**entry["reference"]) if entry.get("reference") else None, entry.get("about"),
        )
        for entry in data.get("entries") or []
    )
    return connection_rules.Connections(entries, dict(data.get("found") or {}), data.get("rating"))


def pack_to_json(pack: Pack) -> dict[str, Any]:
    return dataclasses.asdict(pack)


def pack_from_json(data: Mapping[str, Any]) -> Pack:
    rows = lambda name: tuple(dict(row) for row in data[name])   # noqa: E731
    return Pack(
        pack_id=data["pack_id"], signal=dict(data["signal"]), concepts=rows("concepts"), references=rows("references"), edges=rows("edges"), messages=rows("messages"),
        recent_published_stories=rows("recent_published_stories"), existing_ideas=rows("existing_ideas"), mission=data["mission"], policy=data["policy"],
        allowed_sections=tuple(data["allowed_sections"]), scan=dict(data["scan"]), accepted_lineage_ids=tuple(data["accepted_lineage_ids"]),
        editor_keys={lineage: tuple(key) for lineage, key in (data.get("editor_keys") or {}).items()}, editor=tuple(data["editor"]),
    )


class StoredKnowledge:
    """What the plan already worked out about one item, in the place of ``connections.Knowledge``: its connections and the summary the writer falls back to. It reads
    nothing, which is the point: ``Knowledge`` would list the site's Messages and its whole link feed again for every step."""

    def __init__(self, connections: connection_rules.Connections, summary: str | None) -> None:
        self.stored, self.summary = connections, summary or ""
        self.errors: dict[str, str] = {}

    def connections_for(self, item: Any) -> connection_rules.Connections:
        return self.stored

    def summary_of(self, lineage_id: str) -> str:
        return self.summary


def stub_signal_run(kind: str, subject: Any, *, gate: Any, concept_nodes: Mapping[str, Mapping[str, Any]]) -> SimpleNamespace:
    """The part of a ``signal_queue.SignalRun`` that ``draft_monitor_stories`` uses, for a plan of one step."""
    def queue(candidates: list[MonitoredItem]) -> list[QueueEntry]:
        if kind == "pack":
            return [QueueEntry("pack", subject.surprise, subject.signal_type, subject.pack_id, float(subject.signal["correctedPValue"]), pack=subject)]
        # An item an idea filed earlier today already covers (a pack idea cites it) is no longer a candidate: the step has nothing to do.
        return [QueueEntry(ITEM, 0.0, ITEM, subject.lineage_id, 1.0)] if any(candidate.lineage_id == subject.lineage_id for candidate in candidates) else []

    def pack_records() -> list[dict[str, Any]]:
        if kind != "pack":
            return []
        return [{"packId": subject.pack_id, "signal": subject.signal_type, "anchor": subject.anchor, "correctedPValue": subject.signal["correctedPValue"],
                 "surprise": subject.surprise, "dateBasis": subject.signal.get("dateBasis"), "acceptedReferences": len(subject.accepted_lineage_ids),
                 "attempted": False, "ideas": 0}]

    return SimpleNamespace(queue=queue, pack_records=pack_records, packs_skipped_no_new_evidence=0, gate=gate, concept_nodes=dict(concept_nodes),
                           inputs=SimpleNamespace(ratings=(), votes=(), messages=()), summaries=None)


# --- the plan -----------------------------------------------------------------------------------------------------------------


def step_message(monitor_id: str, publication_id: str, plan_id: str, number: int) -> dict[str, Any]:
    return {"v": MESSAGE_VERSION, "kind": MESSAGE_KIND, "monitorId": monitor_id, "publicationId": publication_id, "planId": plan_id, "step": number}


def is_story_message(body: Any) -> bool:
    return isinstance(body, dict) and body.get("kind") == MESSAGE_KIND


def send_steps(sqs: Any, queue_url: str, messages: Iterable[dict[str, Any]]) -> int:
    """Sends the steps to the FIFO queue ten to a request, in order. The message group is the publication (its steps run one at a time, in order) and the
    deduplication id is the step, so a repeated send of one plan is one message. Raises if the queue refuses any."""
    pending, sent = list(messages), 0
    for start in range(0, len(pending), SQS_BATCH):
        batch = pending[start:start + SQS_BATCH]
        response = sqs.send_message_batch(QueueUrl=queue_url, Entries=[
            {"Id": str(number), "MessageBody": json.dumps(message, separators=(",", ":")), "MessageGroupId": message["publicationId"],
             "MessageDeduplicationId": f"{message['planId']}-{message['step']}"[:128]}
            for number, message in enumerate(batch)])
        failed = response.get("Failed") or []
        if failed:
            raise RuntimeError(f"the story queue refused {len(failed)} of {len(batch)} steps ({failed[0].get('Code')})")
        sent += len(batch)
    return sent


class QueuePlanner:
    """The ``plan_sink``: stores the steps and queues them. ``store`` is the router's table (``put_any``, ``get_any``)."""

    def __init__(self, store: Any, monitor_id: str, publication_id: str, plan_id: str, *, sqs: Any, queue_url: str, now: float, suggestions_waiting: bool = False) -> None:
        self.store, self.monitor_id, self.publication_id, self.plan_id = store, monitor_id, publication_id, plan_id
        self.sqs, self.queue_url, self.now, self.suggestions_waiting = sqs, queue_url, now, suggestions_waiting

    def row(self, sort_key: str, **fields: Any) -> dict[str, Any]:
        from .monitor_stories import iso

        return {"pk": f"MONITOR#{self.monitor_id}", "sk": sort_key, "publicationId": self.publication_id, "planId": self.plan_id, "ttl": int(self.now + PLAN_TTL_SECONDS),
                "createdAt": iso(datetime.fromtimestamp(self.now, timezone.utc)), **fields}

    def __call__(self, plan: PlanInput) -> dict[str, Any]:
        steps = plan.steps
        nodes = plan.signal_run.concept_nodes if plan.signal_run is not None else {}
        messages = []
        for number, (kind, subject) in enumerate(steps, start=1):
            if kind == "pack":
                payload = {"kind": "pack", "subject": retry_rules.pack_subject(subject.signal_type, subject.anchor), "title": subject.anchor, "pack": pack_to_json(subject),
                           "nodes": {row["hashtag"]: dict(nodes[row["hashtag"]]) for row in subject.concepts if row.get("hashtag") in nodes}}
            else:
                connections = plan.knowledge.connections_for(subject)
                payload = {"kind": "item", "subject": retry_rules.single_subject(subject.lineage_id), "title": subject.title, "item": item_to_json(subject),
                           "connections": connections_to_json(connections),
                           "summary": None if stored_summary(subject.details) else (plan.knowledge.summary_of(subject.lineage_id) or None)}
            self.store.put_any(self.monitor_id, self.row(entry_key(self.publication_id, self.plan_id, number), kind=kind, payload=encode(payload)))
            messages.append(step_message(self.monitor_id, self.publication_id, self.plan_id, number))
        proposals = [{"id": row.get("id"), "title": row.get("title") or "", "summary": row.get("summary") or "", "state": row.get("state"), "targets": row.get("targets")}
                     for row in plan.proposals]
        ratings = [{"referenceId": rating.reference_id, "lineageId": rating.lineage_id, "title": rating.title, "stars": rating.stars, "status": rating.status}
                   for rating in (getattr(getattr(plan.signal_run, "inputs", None), "ratings", None) or ())]
        head = {"total": len(steps), "publication": self.publication_id, "inputs": {key: value for key, value in plan.run["inputs"].items() if isinstance(value, int)},
                "suggestionsWaiting": self.suggestions_waiting, "kinds": {"pack": sum(kind == "pack" for kind, _ in steps), "item": sum(kind == "item" for kind, _ in steps)},
                "candidateLineages": [item.lineage_id for item in plan.candidates], "ratings": ratings,
                "context": encode(plan.context), "proposals": encode(proposals), "covered": len(plan.covered),
                "duplicateThreshold": plan.run["duplicateCut"]["threshold"]}   # learned once from the editors' decisions (duplicate_cut.py); a step does not read them again
        self.store.put_any(self.monitor_id, self.row(head_key(self.publication_id, self.plan_id), **head))
        self.store.put_any(self.monitor_id, self.row(pointer_key(self.publication_id), total=len(steps), finalized=not steps))
        sent = send_steps(self.sqs, self.queue_url, messages) if messages else 0
        return {"planId": self.plan_id, "steps": len(steps), "queued": sent, **{f"{kind}s": count for kind, count in head["kinds"].items()}}


def open_plan(store: Any, monitor_id: str, publication_id: str) -> dict[str, Any] | None:
    """The publication's latest plan when it has not finished (its pointer row says so), else None."""
    pointer = store.get_any(monitor_id, pointer_key(publication_id))
    if not pointer or pointer.get("finalized"):
        return None
    done = len(store.query_prefix(monitor_id, done_prefix(publication_id, pointer["planId"])))
    return {"planId": pointer["planId"], "total": int(pointer.get("total") or 0), "done": done} if done < int(pointer.get("total") or 0) else None


# --- one step -----------------------------------------------------------------------------------------------------------------


class StepFailed(RuntimeError):
    """A step that must be tried again."""


def router_retry_memory(store: Any, monitor_id: str, publication_id: str) -> retry_rules.CallbackMemory:
    """The rejected-draft memory in the router's own table, one row per Reference or pack."""
    def recall(subject: str) -> Any:
        return store.get_any(monitor_id, retry_rules.sort_key(publication_id, subject))

    def remember(subject: str, record: Mapping[str, Any]) -> None:
        store.put_any(monitor_id, {"pk": f"MONITOR#{monitor_id}", "sk": retry_rules.sort_key(publication_id, subject), **record})

    return retry_rules.CallbackMemory(recall, remember)


def extend_batch_review(client: Any, run: Mapping[str, Any], drafts: list[dict[str, Any]], review_requests: Any) -> dict[str, Any]:
    """Adds the step's ideas to the plan's one soft review request (``rr-batch-<plan>``), creating it with the first. Never raises."""
    if not drafts:
        return {"status": "none", "requested": False, "ideas": 0}
    try:
        request = review_requests.raise_batch_review(
            client, raised_by="idea-pipeline", batch_id=run["runId"], idea_ids=[draft.get("itemLineageId") or draft["ideaId"] for draft in drafts], noun="monitor story draft",
            link_type="story", extend=True)
    except Exception as error:  # noqa: BLE001 - the ideas are filed; a site without review requests must not fail the step
        return {"status": "not_raised", "requested": False, "ideas": len(drafts), "error": f"{type(error).__name__}: {error}"[:300]}
    return {"status": "requested", "requested": True, "ideas": len(drafts), "requestId": request["id"]}


def outcome_of(run: Mapping[str, Any]) -> dict[str, Any]:
    """The step's record in a DONE row: what was filed, and the skipped and invalid rows the curation flag reads, trimmed to what it reads."""
    return {
        "drafted": [{"id": draft.get("itemLineageId") or draft["ideaId"], "title": draft["title"], "summary": draft.get("angle") or "", "origin": draft.get("origin"),
                     "referenceLineageId": draft.get("referenceLineageId"), "targets": draft.get("targets")} for draft in run["drafts"]],
        "skipped": [dict(row) for row in run["skipped"]], "invalid": [{key: row[key] for key in INVALID_KEYS if key in row} for row in run["invalid"]],
        "duplicates": len(run["duplicates"]), "attempted": run["attempted"], "costUsd": (run.get("usage") or {}).get("costUsd") or 0.0,
        "fileErrors": [row.get("error") for row in run.get("fileErrors") or []], "stoppedBy": run.get("stoppedBy"),
        "retriedWithNewConnections": len(run.get("retriedWithNewConnections") or []), "packRecords": run.get("packs") or [],
    }


def run_step(
    store: Any, monitor_id: str, publication: Mapping[str, Any], message: Mapping[str, Any], *, client: Any, transport: Callable, gate: Any, now: datetime,
    fetch: Any = None, explorer: Any = None, review_requests: Any = None, receive_count: int = 1, emit: Callable[[str], None] = print,
) -> dict[str, Any]:
    """One queued step. Returns its outcome word and numbers; raises ``StepFailed`` when the queue should try it again."""
    from . import monitor_stories
    from .items import ItemStore   # imported here so a test can stand a double in its place

    publication_id, plan_id, number = publication["publicationId"], str(message["planId"]), int(message["step"])
    head_row = store.get_any(monitor_id, head_key(publication_id, plan_id))
    entry_row = store.get_any(monitor_id, entry_key(publication_id, plan_id, number))
    if head_row is None or entry_row is None:
        return {"step": number, "status": "gone", "reason": "the plan's rows have expired"}
    if store.get_any(monitor_id, done_key(publication_id, plan_id, number)):
        return {"step": number, "status": "already"}   # a redelivered message: the step finished
    payload = decode(entry_row["payload"])
    context = decode(head_row["context"])
    earlier = [row for row in store.query_prefix(monitor_id, done_prefix(publication_id, plan_id))]
    proposals = decode(head_row["proposals"]) + [{"state": "draft", **idea} for row in earlier for idea in row.get("drafted") or []]
    if payload["kind"] == "pack":
        subject = pack_from_json(payload["pack"])
        prepared = Prepared(items=[], proposals=proposals)
        knowledge = StoredKnowledge(connection_rules.Connections(), None)
        stub = stub_signal_run("pack", subject, gate=gate, concept_nodes=payload.get("nodes") or {})
    else:
        subject = item_from_json(payload["item"])
        prepared = Prepared(items=[subject], proposals=proposals)
        knowledge = StoredKnowledge(connections_from_json(payload["connections"]), payload.get("summary"))
        stub = stub_signal_run("item", subject, gate=gate, concept_nodes={})
    moment = now
    try:
        run = draft_monitor_stories(
            client=client, site=publication_id, corpus_key=publication["corpusKey"], context=context, json_store=None,
            idea_store=ItemStore(client, gate=gate, drafts=proposals, checklist=False), review_client=None, transport=transport, limit=None, dry_run=False, now=moment,
            fetch=fetch or monitor_stories.fetch_source, explorer=explorer, out_of_time=None, maximum_cost_usd=MAXIMUM_STEP_COST_USD, read_workers=1,
            signal_run=stub, knowledge=knowledge, retry_memory=router_retry_memory(store, monitor_id, publication_id), suggestions_waiting=bool(head_row.get("suggestionsWaiting")),
            count_pending=False, run_id=plan_id, prepared=prepared, threshold=float(head_row["duplicateThreshold"]) if head_row.get("duplicateThreshold") is not None else None,
            rules=rules_of(validate_idea_rules(publication_id, (publication.get("monitorStories") or {}).get("ideaRules"))))
        transient = [row for row in run["invalid"] if row.get("reason") in TRANSIENT_REASONS]
        trouble = run.get("fileError") or (transient[0].get("message") or transient[0]["reason"] if transient else None)
        if trouble and not run["drafts"]:
            raise StepFailed(str(trouble)[:300])
    except Exception as error:  # noqa: BLE001 - the queue tries again; the last try leaves a DONE row so the plan still finishes
        if receive_count >= MAXIMUM_RECEIVES:
            record_done(store, monitor_id, publication_id, plan_id, number, payload, {"status": "failed", "reason": f"{type(error).__name__}: {str(error)[:300]}", "drafted": [], "skipped": [], "invalid": [], "attempted": 0, "costUsd": 0.0},
                        float(entry_row.get("ttl") or 0))
            finish_if_complete(store, monitor_id, publication, plan_id, client=client, now=now, emit=emit)
        raise
    outcome = outcome_of(run)
    if run["drafts"] and review_requests is not None:
        outcome["review"] = extend_batch_review(client, run, run["drafts"], review_requests)
    status = "drafted" if run["drafts"] else ("skipped" if run["skipped"] and not run["invalid"] else "rejected" if run["invalid"] else "nothing")
    record_done(store, monitor_id, publication_id, plan_id, number, payload, {"status": status, **outcome}, float(entry_row.get("ttl") or 0))
    emit(json.dumps({"monitorStoriesStep": status, "monitorId": monitor_id, "publicationId": publication_id, "planId": plan_id, "step": number, "kind": payload["kind"],
                     "drafted": len(outcome["drafted"]), "costUsd": outcome["costUsd"], "skipped": [row.get("reason") for row in outcome["skipped"]],
                     "invalid": [row.get("reason") for row in outcome["invalid"]]}))
    finished = finish_if_complete(store, monitor_id, publication, plan_id, client=client, now=now, emit=emit)
    return {"step": number, "status": status, "drafted": len(outcome["drafted"]), "finished": bool(finished)}


def record_done(store: Any, monitor_id: str, publication_id: str, plan_id: str, number: int, payload: Mapping[str, Any], outcome: Mapping[str, Any], ttl: float) -> None:
    store.put_any(monitor_id, {"pk": f"MONITOR#{monitor_id}", "sk": done_key(publication_id, plan_id, number), "publicationId": publication_id, "planId": plan_id, "step": number,
                               "kind": payload["kind"], "subject": payload["subject"], "title": payload.get("title"), "ttl": int(ttl), **outcome})


# --- the end of a plan --------------------------------------------------------------------------------------------------------


def known_open_flags(store: Any, monitor_id: str, publication_id: str, client: Any) -> list[dict[str, Any]]:
    """The publication's open curation flag, read by the id the last plan stored (none when no plan raised one, or when it has been answered)."""
    from .. import review_requests

    remembered = store.get_any(monitor_id, flag_key(publication_id))
    row = client.get_record("ReviewRequest", remembered["requestId"]) if remembered and remembered.get("requestId") else None
    request = review_requests.read_review(row) if row else None
    return [request] if request and request["state"] == "open" else []


def finish_if_complete(store: Any, monitor_id: str, publication: Mapping[str, Any], plan_id: str, *, client: Any, now: datetime, emit: Callable[[str], None] = print) -> dict[str, Any] | None:
    """When every step has a DONE row: the plan's one log line and its curation flag, once. Returns the summary, or None (not complete, or another step finished it)."""
    from .monitor_stories import iso
    from .review import settle_curation_flag

    publication_id = publication["publicationId"]
    head = store.get_any(monitor_id, head_key(publication_id, plan_id))
    if head is None:
        return None
    rows = store.query_prefix(monitor_id, done_prefix(publication_id, plan_id))
    if len(rows) < int(head["total"]):
        return None
    if not store.put_new(monitor_id, {"pk": f"MONITOR#{monitor_id}", "sk": final_key(publication_id, plan_id), "finishedAt": iso(now), "ttl": int(now.timestamp() + PLAN_TTL_SECONDS)}):
        return None
    drafted = [idea for row in rows for idea in row.get("drafted") or []]
    skipped = [skip for row in rows for skip in row.get("skipped") or []]
    invalid = [bad for row in rows for bad in row.get("invalid") or []]
    failed = [row for row in rows if row.get("status") == "failed"]
    inputs = dict(head.get("inputs") or {})
    inputs["candidates"] = len(head.get("candidateLineages") or [])
    covered_run = {"drafts": [{"referenceLineageId": idea.get("referenceLineageId"), "itemLineageId": idea["id"]} for idea in drafted], "invalid": invalid, "skipped": skipped}
    from .rated_outcomes import rated_without_ideas

    rated = rated_without_ideas(covered_run, head.get("ratings") or [], candidate_lineages=head.get("candidateLineages") or [])
    flag_run = {"runId": plan_id, "drafts": drafted, "skipped": skipped, "invalid": invalid, "inputs": inputs, "ratedNoIdea": rated,
                "stoppedBy": "file_error" if any(row.get("fileErrors") for row in rows) and not drafted else None, "suggestionsWaiting": bool(head.get("suggestionsWaiting"))}
    flag = settle_curation_flag(client, flag_run, publication_id, open_flags=known_open_flags(store, monitor_id, publication_id, client))
    if flag.get("status") == "raised" and flag.get("requestId"):
        store.put_any(monitor_id, {"pk": f"MONITOR#{monitor_id}", "sk": flag_key(publication_id), "requestId": flag["requestId"]})
    summary = {
        "publicationId": publication_id, "planId": plan_id, "status": "complete" if not failed else "complete_with_failures", "steps": int(head["total"]), "drafted": len(drafted),
        "failedSteps": len(failed), "skipped": len(skipped), "failedTheCheck": len(invalid), "nothingToAdd": sum(row.get("reason") == connection_rules.NOTHING_TO_ADD for row in skipped),
        "alreadyRejected": sum(row.get("reason") == retry_rules.ALREADY_REJECTED for row in skipped), "attempted": sum(int(row.get("attempted") or 0) for row in rows),
        "costUsd": round(sum(float(row.get("costUsd") or 0) for row in rows), 6), "candidates": inputs["candidates"], "curationFlag": flag.get("status"),
    }
    store.put_any(monitor_id, {"pk": f"MONITOR#{monitor_id}", "sk": pointer_key(publication_id), "planId": plan_id, "total": int(head["total"]), "finalized": True,
                               "ttl": int(now.timestamp() + PLAN_TTL_SECONDS)})
    emit(json.dumps({"monitorStories": "finished", "monitorId": monitor_id, **summary}))
    return summary
