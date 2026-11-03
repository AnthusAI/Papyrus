"""The router's research-assignments task: runs the research assignments an editor gave a Story in the newsroom, with nobody at a terminal.

An editor's research assignment is an ``Assignment`` of type ``research.multi`` with ``itemLineageId`` (the Story) and ``contextProfile: reporter`` in its
metadata attachment. It starts ``open``. This task, per publication, takes the open ones oldest first, marks each ``claimed`` (the newsroom shows that as
running) with a lease, runs ``research_multi`` on it, and marks it ``completed``, or ``failed`` with the reason. An open assignment that already has a research packet (a terminal run made one) is marked ``completed`` without running again. A claim whose lease has run out is failed with a
reason, so nothing hangs for ever; a failed assignment is never retried on its own, because a run spends search and model calls. An editor can reopen it.
"""
from __future__ import annotations

import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .assignments import assignment_metadata

MULTI_ASSIGNMENT_TYPE = "research.multi"   # multi_search_research.MULTI_ASSIGNMENT_TYPE; not imported, because that module imports the router
WORKER_LABEL = "papyrus-research-worker"
CLAIM_LEASE_SECONDS = 960       # longer than the worker's 900 second Lambda timeout
REPORTER_PROFILE = "reporter"
START_RESERVE_SECONDS = 420     # a run is not started with less time left than this: search and synthesis took about 5 minutes on real runs, and the packet still has to be written
JUDGE_RESERVE_SECONDS = 240     # the fact check's judge stops asking with less time left than this, so its claims end `unchecked` and the packet is written
POLICY_KEYS = ("enabled",)
PACKET_EVENT_TYPES = ("research.multi.completed", "research.multi.intake_failed")
CREDENTIAL_GUIDANCE_MARKERS = ("your aws session may have expired", "aws sso login", "papyrus login", "papyrus auth status")


@contextmanager
def publication_endpoint(publication: dict[str, Any]):
    """The context pack asks for the backend's address with ``env.graphql_endpoint()``, which reads ``PAPYRUS_GRAPHQL_ENDPOINT`` or the site's amplify_outputs.json; the
    router Lambda has neither, so the run sets the variable to the publication's own endpoint and puts back what was there."""
    before = os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT")
    if publication.get("appsyncEndpoint"):
        os.environ["PAPYRUS_GRAPHQL_ENDPOINT"] = publication["appsyncEndpoint"]
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("PAPYRUS_GRAPHQL_ENDPOINT", None)
        else:
            os.environ["PAPYRUS_GRAPHQL_ENDPOINT"] = before


def validate_research_assignments(publication_id: str, raw: Any) -> dict[str, Any]:
    """The normalized ``researchAssignments`` policy of a router publication. Absent means OFF: a publication opts in once its backend grants the router the fields."""
    if raw is None:
        return {"enabled": False}
    if not isinstance(raw, dict):
        raise ValueError(f"router publication {publication_id} has an invalid researchAssignments (an object is needed)")
    unknown = sorted(set(raw) - set(POLICY_KEYS))
    if unknown:
        raise ValueError(f"router publication {publication_id} researchAssignments has unknown keys: {', '.join(unknown)}")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(f"router publication {publication_id} researchAssignments.enabled must be true or false")
    return {"enabled": enabled}


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def without_credential_guidance(reason: str) -> str:
    """A failure reason an editor can read: the advice lines meant for someone at a terminal (sign in again with the CLI) are dropped and the real reason stays."""
    kept = [line for line in str(reason).splitlines() if not any(marker in line.lower() for marker in CREDENTIAL_GUIDANCE_MARKERS)]
    return "\n".join(kept).strip()


def finished_note(intake_error: Any) -> str:
    """The note of a finished run: plain when everything went in, and plain about what did not when the sources could not be taken in."""
    if not intake_error:
        return "Research finished; the packet is on the assignment."
    reason = without_credential_guidance(str(intake_error))
    if "read-only file system" in reason.lower() or "errno 30" in reason.lower():
        reason = "the server could not write a working file"
    else:
        reason = re.sub(r"^[A-Za-z_][\w.]*(?:Error|Exception): ", "", reason).strip() or "an error the log records"
    return f"Research finished and the packet is on the assignment, but its sources were not added to the newsroom, and no sources were linked to the Story: {reason}."[:500]


def assignment_has_research_packet(client: Any, assignment: dict[str, Any]) -> bool:
    """Whether a run already made this assignment's packet: it ``produces`` a research packet Message, or it has a finished-run event."""
    state_key = f"assignment#{assignment['id']}#current"
    for relation in client.list_semantic_relations_by_subject_state(state_key):
        if relation.get("relationState") != "superseded" and (relation.get("relationTypeKey") or relation.get("predicate")) == "produces" and relation.get("objectKind") == "message":
            return True
    return any(event.get("eventType") in PACKET_EVENT_TYPES for event in client.list_assignment_events_by_assignment_and_created_at(assignment["id"]))


def set_status(client: Any, assignment: dict[str, Any], status: str, *, now: datetime, note: str, event_type: str, claim: bool = False,
               actor_label: str = WORKER_LABEL) -> dict[str, Any]:
    """One status change of an assignment, with its AssignmentEvent. Returns the updated row."""
    stamp = _stamp(now)
    queue = assignment["queueKey"]
    update = {
        "id": assignment["id"], "assignmentTypeKey": assignment["assignmentTypeKey"], "queueKey": queue, "status": status,
        "queueStatusKey": f"{queue}#{status}", "sectionId": assignment.get("sectionId"), "sectionKey": assignment.get("sectionKey"),
        "sectionType": assignment.get("sectionType"), "primaryFocusCategoryKey": assignment.get("primaryFocusCategoryKey"),
        "topicScopeCategoryKeys": assignment.get("topicScopeCategoryKeys") or [], "createdAt": assignment.get("createdAt"), "updatedAt": stamp,
        "newsroomFeedKey": f"assignment#{status}", "itemLineageId": assignment.get("itemLineageId"),
        **({"priority": assignment["priority"]} if assignment.get("priority") is not None else {}),
        **({"sectionStatusKey": f"{assignment['sectionKey']}#{status}", "sectionQueueStatusKey": f"{assignment['sectionKey']}#{queue}#{status}"}
           if assignment.get("sectionKey") else {}),
    }
    if claim:
        update.update({"assigneeType": "agent", "assigneeId": WORKER_LABEL, "assigneeKey": WORKER_LABEL, "claimedAt": stamp,
                       "claimExpiresAt": _stamp(now + timedelta(seconds=CLAIM_LEASE_SECONDS))})
    if status == "completed":
        update["completedAt"] = stamp
    client.update_record("Assignment", update)
    client.create_record("AssignmentEvent", {
        "id": f"assignment-event-{assignment['id']}-{event_type}-{stamp.replace('-', '').replace(':', '').replace('.', '')}",
        "assignmentId": assignment["id"], "assignmentTypeKey": assignment["assignmentTypeKey"], "queueKey": queue, "eventType": event_type,
        "fromStatus": assignment.get("status"), "toStatus": status, "actorLabel": actor_label, "note": note[:500], "createdAt": stamp,
    })
    return {**assignment, **update}


def research_assignments_of_stories(client: Any) -> list[dict[str, Any]]:
    """Every research.multi assignment that has a Story, oldest first."""
    rows = [row for row in client.list_assignments_by_type_status_and_created_at(MULTI_ASSIGNMENT_TYPE) if row and row.get("itemLineageId")]
    return sorted(rows, key=lambda row: str(row.get("createdAt") or ""))


def run_research_assignments(client: Any, publication: dict[str, Any], *, now: datetime, out_of_time: Callable[[], bool],
                             clock: Callable[[], datetime] | None = None, time_left: Callable[[], float] | None = None, research: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """One pass for one publication. Never raises for one assignment's failure; stops, leaving the rest open, when the time is short."""
    if research is None:
        from .multi_search_research import research_multi as research
    clock = clock or (lambda: datetime.now(timezone.utc))
    judge_out_of_time = (lambda: time_left() < JUDGE_RESERVE_SECONDS) if time_left is not None else (lambda: False)
    result: dict[str, Any] = {"publicationId": publication["publicationId"], "ran": [], "failed": [], "expired": [], "alreadyDone": [], "intakeFailed": {}, "leftOpen": 0, "stoppedBy": None}
    rows = research_assignments_of_stories(client)
    for row in rows:
        if row.get("status") != "claimed":
            continue
        expires = _parse(row.get("claimExpiresAt"))
        if expires is not None and expires <= now:
            set_status(client, row, "failed", now=now, event_type="research.failed", note="The research worker stopped before finishing this assignment (its time ran out). Reopen it to run it again.")
            result["expired"].append(row["id"])
    waiting = [row for row in rows if row.get("status") == "open"]
    for index, row in enumerate(waiting):
        if out_of_time() or (time_left is not None and time_left() < START_RESERVE_SECONDS):
            result["stoppedBy"] = "time"
            result["leftOpen"] = len(waiting) - index
            break
        if assignment_metadata(client, row).get("contextProfile") != REPORTER_PROFILE:
            continue
        if assignment_has_research_packet(client, row):
            set_status(client, row, "completed", now=clock(), event_type="research.completed",
                       note="A research packet already exists for this assignment, so it was marked completed without researching again.")
            result["alreadyDone"].append(row["id"])
            continue
        running = set_status(client, row, "claimed", now=now, event_type="claim", note="The research worker started this assignment.", claim=True)
        try:
            with publication_endpoint(publication):
                outcome = research(client, {"assignment": row["id"], "corpus-key": publication.get("corpusKey"), "actor-label": WORKER_LABEL, "leave-status": True},
                                   out_of_time=judge_out_of_time)
        except Exception as error:   # noqa: BLE001 - one assignment never stops the others
            outcome = {"action": "failed", "error": f"{type(error).__name__}: {error}"}
        if outcome.get("action") == "completed":
            set_status(client, running, "completed", now=clock(), event_type="research.completed", note=finished_note(outcome.get("intakeError")))
            result["ran"].append(row["id"])
            if outcome.get("intakeError"):
                result["intakeFailed"][row["id"]] = str(outcome["intakeError"])[:300]
        else:
            set_status(client, running, "failed", now=clock(), event_type="research.failed", note=(without_credential_guidance(str(outcome.get("error") or "")) or "The research did not finish.")[:400])
            result["failed"].append(row["id"])
    result["status"] = "stopped" if result["stoppedBy"] else "complete"
    return result
