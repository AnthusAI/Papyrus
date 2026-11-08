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
    if caller.kind == "agent" and not item.agent_allowed:
        return error_envelope(name, "human_required", f"{name} needs a person; an agent may not call it.")
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
