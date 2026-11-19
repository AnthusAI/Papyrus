"""The handoff operation on the signed-in lane (``handoffs_request``, PPY-51f96f, slice F1): an agent or a person asks a responsibility for work on a Story.

The gate has already answered an agent (``images.handlers.execute``); this writes the Assignment (``agent_assignments.py`` has what happens to it afterwards). It is
its own module, as the rating handler is, because the operation table's handlers import it when the table loads."""
from __future__ import annotations

from typing import Any, Callable

from .agent_assignments import DEFAULT_PRIORITY, FEED_KEY, MAX_WHY_CHARACTERS, QUEUE_KEY, RESPONSIBILITY, assignment_id, record_event, utc_now
from .handoff_records import OPEN, type_key
from .images.handlers import Caller, Handler, ImageOperationError, Outcome

CREATED_EVENT = "created"


def _asker_label(caller: Caller) -> str:
    if caller.kind == "agent":
        if not caller.subject:
            raise ImageOperationError("invalid_input", "An agent's request names the agent that asked.", details={"path": "caller"})
        return f"agent:{caller.subject}"
    return caller.subject or "an editor"


def _publication(client: Any) -> str:
    from papyrus_content.editorial_context import hosted_publication

    try:
        return hosted_publication(client)["key"]
    except ValueError as error:
        raise ImageOperationError("service_unavailable", str(error)) from error


# --- the request ---------------------------------------------------------------------------------------------------------------------------------


def request_work(client: Any, arguments: dict, caller: Caller, *, now: str | None = None) -> Outcome:
    """Ask a responsibility for one piece of work on a Story. The gate has already answered an agent (``images.handlers.execute``)."""
    from papyrus_content.story_reporting import current_story_version

    story, responsibility, why = arguments["story"], arguments["responsibility"], arguments["why"].strip()
    if not RESPONSIBILITY.match(responsibility):
        raise ImageOperationError("invalid_input", "A responsibility is lower-case words joined by underscores, as the agent catalogue names it.", details={"path": "responsibility"})
    if not why or len(why) > MAX_WHY_CHARACTERS:
        raise ImageOperationError("invalid_input", f"Say why in 1 to {MAX_WHY_CHARACTERS} characters.", details={"path": "why"})
    asker = _asker_label(caller)
    if caller.kind == "agent" and caller.subject == responsibility:
        raise ImageOperationError("constraint_conflict", f"{responsibility} cannot ask itself for work: it does the work.", details={"constraint": "no_self_request"})
    try:
        current_story_version(client, story)
    except ValueError as error:
        raise ImageOperationError("not_found", str(error)) from error
    moment = now or utc_now()
    wanted = assignment_id(asker, responsibility, story, why, "" if caller.kind == "agent" else (caller.request_id or moment))
    existing = client.get_record("Assignment", wanted)
    if existing:
        return Outcome({"assignmentId": wanted, "responsibility": responsibility, "story": story, "status": existing.get("status") or OPEN, "askedBy": existing.get("createdBy") or asker,
                        "created": False}, _publication(client))
    row = {"id": wanted, "assignmentTypeKey": type_key(responsibility), "queueKey": QUEUE_KEY, "queueStatusKey": f"{QUEUE_KEY}#{OPEN}", "status": OPEN, "priority": DEFAULT_PRIORITY,
           "title": f"Work for {responsibility.replace('_', ' ')}", "summary": why, "createdBy": asker, "createdAt": moment, "updatedAt": moment, "newsroomFeedKey": FEED_KEY, "itemLineageId": story}
    client.create_record("Assignment", row)   # the insert is the change the feed wakes the responsible agent for
    record_event(client, row, CREATED_EVENT, OPEN, actor=asker, note=why, now=moment, payload={"askedBy": asker, "responsibility": responsibility, "story": story, "why": why})
    from .newsroom_summary import update_newsroom_summary_after_assignment_creates

    update_newsroom_summary_after_assignment_creates(client, [{"modelName": "Assignment", "action": "create", "expected": row}], actor_label=asker, reason=f"handoffs request {wanted}")
    return Outcome({"assignmentId": wanted, "responsibility": responsibility, "story": story, "status": OPEN, "askedBy": asker, "created": True}, _publication(client))


HANDOFF_HANDLERS: dict[str, Callable[..., Outcome]] = {"handoffs_request": request_work}


def signed_in_handlers(client_factory: Callable[[], Any] | None = None) -> dict[str, Handler]:
    """Each call opens the authoring client of whoever runs it: a person's own session, or the procedure runner's role inside a run."""
    def factory():
        if client_factory is not None:
            return client_factory()
        from papyrus_content.graphql_authoring import create_authoring_client

        return create_authoring_client()[0]

    def wrap(function):
        def handler(arguments: dict, caller: Caller) -> Outcome:
            return function(factory(), arguments, caller)
        return handler

    return {name: wrap(function) for name, function in HANDOFF_HANDLERS.items()}


