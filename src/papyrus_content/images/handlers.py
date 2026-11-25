"""Running an operation: check the caller and the input, call the handler, wrap the answer in the shared envelope.

Every front end (the CLI, the MCP tools, the newsroom's server code) comes through ``execute``, so the same checks and the same JSON happen whichever
one asked. ``HANDLERS`` holds what each operation does; every handler answers ``not_implemented`` until its build step fills it in
(project/wiki/image-toolchain.md section 9). A test or a later front end passes its own handlers to ``execute``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from .operations import ERROR_BY_CODE, OPERATIONS, operation


@dataclass(frozen=True)
class Caller:
    """Who is asking. An agent is anything that is not a person choosing: procedures, automations and agent shells (design section 3.6)."""
    kind: Literal["person", "agent"] = "person"
    subject: str = ""
    delegated_by: str | None = None
    is_admin: bool = False   # an admin of this site; only a person who is one may change a binding constraint
    request_id: str | None = None   # the door's requestId: a write repeated with the same id gives the first answer
    gate_run: Any = field(default=None, compare=False)   # an agent's run (agent_gate.GateRun): every call it makes is answered by the one gate


@dataclass(frozen=True)
class Outcome:
    """What a handler returns on success."""
    result: dict
    publication: str
    warnings: tuple[dict, ...] = field(default_factory=tuple)


class ImageOperationError(Exception):
    def __init__(self, code: str, message: str | None = None, *, retryable: bool | None = None, details: dict | None = None):
        known = ERROR_BY_CODE[code]
        super().__init__(message or known.message)
        self.code, self.message = code, message or known.message
        self.retryable = known.retryable if retryable is None else retryable
        self.details = details or {}


Handler = Callable[[dict, Caller], Outcome]


def _not_implemented(name: str) -> Handler:
    def handler(arguments: dict, caller: Caller) -> Outcome:
        raise ImageOperationError("not_implemented", f"{name} is described but not built yet.", details={"operation": name})
    handler.not_implemented = True
    return handler


HANDLERS: dict[str, Handler] = {item.name: _not_implemented(item.name) for item in OPERATIONS}


def ok_envelope(name: str, outcome: Outcome) -> dict:
    return {"ok": True, "op": name, "publication": outcome.publication, "result": outcome.result, "warnings": list(outcome.warnings)}


def error_envelope(name: str, code: str, message: str | None = None, *, retryable: bool | None = None, details: dict | None = None) -> dict:
    error = ImageOperationError(code, message, retryable=retryable, details=details)
    return {"ok": False, "op": name, "error": {"code": error.code, "message": error.message, "retryable": error.retryable, "details": error.details}}


# --- input checking: the small part of JSON Schema the table uses -----------------------------------------------------------------------------------

_TYPES = {"string": lambda v: isinstance(v, str), "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
          "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool), "boolean": lambda v: isinstance(v, bool),
          "object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list), "null": lambda v: v is None}


def check(schema: dict, value: Any, path: str = "") -> tuple[str, str] | None:
    """The first problem with ``value`` against ``schema`` as (path, plain message), or None when it fits."""
    where = path or "input"
    if "type" in schema:
        kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[kind](value) for kind in kinds):
            return path, f"{where} must be {' or '.join(kinds)}."
    if "enum" in schema and value not in schema["enum"]:
        return path, f"{where} must be one of: {', '.join(map(str, schema['enum']))}."
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        return path, f"{where} must not be empty."
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return path, f"{where} must be at least {schema['minimum']}."
        if "maximum" in schema and value > schema["maximum"]:
            return path, f"{where} must be at most {schema['maximum']}."
    if isinstance(value, dict):
        for name in schema.get("required", ()):
            if name not in value:
                return f"{path}.{name}".lstrip("."), f"{name} is required."
        properties = schema.get("properties", {})
        for name, item in value.items():
            child = f"{path}.{name}".lstrip(".")
            if name not in properties:
                if schema.get("additionalProperties") is False:
                    return child, f"{name} is not an input of this operation."
                continue
            problem = check(properties[name], item, child)
            if problem:
                return problem
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            problem = check(schema["items"], item, f"{path}[{index}]")
            if problem:
                return problem
    if "oneOf" in schema:
        fits = [option for option in schema["oneOf"] if check(option, value, path) is None]
        if len(fits) != 1:
            names = " or ".join(option["required"][0] for option in schema["oneOf"] if option.get("required"))
            return path, f"Give exactly one of: {names}."
    return None


def execute(name: str, arguments: Any, caller: Caller | None = None, handlers: dict[str, Handler] | None = None) -> dict:
    """Run one operation and return its envelope (a success or an error). Never raises for a bad request."""
    caller = caller or Caller()
    item = operation(name) if isinstance(name, str) else None
    if item is None:
        return error_envelope(str(name), "unknown_operation", f"There is no image operation named {name}.", details={"operation": str(name)})
    if caller.kind == "agent" and caller.gate_run is not None:
        answer = caller.gate_run.ask(name)
        if not answer.allowed:
            return error_envelope(name, answer.answer, answer.reason, details={"gate": answer.as_record()})
    elif caller.kind == "agent" and not item.agent_allowed and not item.delegable:
        return error_envelope(name, item.agent_refusal, f"{name} needs a person; an agent may not call it.")
    problem = check(item.input, arguments if arguments is not None else {})
    if problem:
        return error_envelope(name, "invalid_input", problem[1], details={"path": problem[0]})
    handler = (handlers if handlers is not None else HANDLERS).get(name)
    if handler is None:
        return error_envelope(name, "not_implemented", f"{name} is described but not built yet.", details={"operation": name})
    try:
        return ok_envelope(name, handler(arguments or {}, caller))
    except ImageOperationError as error:
        return error_envelope(name, error.code, error.message, retryable=error.retryable, details=error.details)


# The style profile operations are built (project/wiki/image-toolchain.md section 9, step 2). On this lane each call opens the signed-in person's own
# authoring client; the image-service function binds the same handlers to the caller's identity instead.
from .profile_handlers import signed_in_handlers  # noqa: E402  (after the names above, which profile_handlers imports)

HANDLERS.update(signed_in_handlers())


# Generation is built too (project/wiki/image-toolchain.md section 9, step 5). Nothing spends from here unless the site's image guidelines configure a model and a person
# has approved spending; the check is made before a provider or the store is touched.
from .generation_binding import signed_in_generation_handlers  # noqa: E402

HANDLERS.update(signed_in_generation_handlers())


# The announcement operations (PPY-09ee86) run on the same lane: the person's own authoring client.
from papyrus_content.announcements.handlers import signed_in_handlers as _announcement_handlers  # noqa: E402

HANDLERS.update(_announcement_handlers())

# Announcement review (PPY-97c0f2): the announce rung and its overrides, and one Delivery's review. They read the site's agent policy and the Delivery records, which the
# monitoring router and the image service never do, so the module is imported by the call and not by this file (infra/monitoring/build.py leaves it out of the router zip).
REVIEW_OPERATIONS = ("announcements_release", "announcements_review_show", "announcements_review_set", "announcements_delivery_review_set", "announcements_record_manual", "announcements_correct", "announcements_withdraw")


def _review_handler(name: str) -> Handler:
    def handler(arguments: dict, caller: Caller) -> Outcome:
        from papyrus_content.announcements.review_handlers import signed_in_handlers

        return signed_in_handlers()[name](arguments, caller)
    return handler


HANDLERS.update({name: _review_handler(name) for name in REVIEW_OPERATIONS})

# The editing window (PPY-e8ec54): versions, candidates, pinned blocks and unlock of a Delivery, imported by the call for the same reason.
EDIT_OPERATIONS = ("announcements_draft", "announcements_candidate_choose", "announcements_pinned_change", "announcements_versions", "announcements_unlock", "announcements_example", "announcements_preferred")


def _edit_handler(name: str) -> Handler:
    def handler(arguments: dict, caller: Caller) -> Outcome:
        from papyrus_content.announcements.edit_handlers import signed_in_handlers

        return signed_in_handlers()[name](arguments, caller)
    return handler


HANDLERS.update({name: _edit_handler(name) for name in EDIT_OPERATIONS})

# The Announcements list, a Story's lines and "why was this not announced" (PPY-e4ae3a) read the same records and are imported by the call for the same reason.
LIST_OPERATIONS = ("announcements_where", "announcements_recent", "announcements_explain")


def _list_handler(name: str) -> Handler:
    def handler(arguments: dict, caller: Caller) -> Outcome:
        from papyrus_content.announcements.list_handlers import signed_in_handlers

        return signed_in_handlers()[name](arguments, caller)
    return handler


HANDLERS.update({name: _list_handler(name) for name in LIST_OPERATIONS})


# The rating operation (PPY-d85860) runs on the same lane: whoever runs it, a person's session or the procedure runner's role, opens its own authoring client.
from papyrus_content.rating_handlers import signed_in_handlers as _rating_handlers  # noqa: E402

HANDLERS.update(_rating_handlers())


# The handoff request (PPY-51f96f) runs on the same lane: a person's session, or the procedure runner's role inside an agent's run.
from papyrus_content.handoff_handlers import signed_in_handlers as _handoff_handlers  # noqa: E402

HANDLERS.update(_handoff_handlers())


# The poke-in operations (PPY-e6f31e): pause, resume, the pauses, wake now and wake now on an Overdue record (PPY-97180c). They read the agent policy, the run index and the wake queue, which the image service and
# the monitoring router never do, so the module is imported by the call.
AGENT_OPERATIONS = ("agents_pause", "agents_resume", "agents_pauses", "agents_wake", "agents_wake_overdue")


def _agent_handler(name: str) -> Handler:
    def handler(arguments: dict, caller: Caller) -> Outcome:
        from papyrus_content.agent_poke_in_handlers import signed_in_handlers

        return signed_in_handlers()[name](arguments, caller)
    return handler


HANDLERS.update({name: _agent_handler(name) for name in AGENT_OPERATIONS})


# The guideline operations (PPY-8d41d7) are in the same table, so an agent reads the site's guidelines through this door and its gate (the rating agent's
# guidelines_resolve). The guideline modules read guideline files the monitoring router never does, so they are imported by the call.
GUIDELINE_OPERATIONS = tuple(item.name for item in OPERATIONS if item.group == "guidelines")


def _guideline_handler(name: str) -> Handler:
    def handler(arguments: dict, caller: Caller) -> Outcome:
        from papyrus_content.guidelines.handlers import signed_in_handlers

        return signed_in_handlers()[name](arguments, caller)
    return handler


HANDLERS.update({name: _guideline_handler(name) for name in GUIDELINE_OPERATIONS})
