"""Running a topic operation: check the caller and the input, call the handler, wrap the answer in the same envelope the image operations use.

The CLI, the MCP tool and the newsroom's server code all come through ``execute``. ``topics_model`` takes the backend's client, so the same code runs
on the signed-in command line (``signed_in_handlers``: the client is the person's own session, so the backend applies their own rights) and in the
tests (``with_client``, with a fake engine and a store in memory).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable

from papyrus_content.images.handlers import Caller, Handler, Outcome, check, ok_envelope

from .engine import BiblicusTopicEngine, TopicEngine, TopicEngineError
from .model import DEFAULT_REPRESENTATIVES, TopicParams, run_topics
from .operations import ERROR_BY_CODE, operation
from .select import DEFAULT_STATES
from .store import FileTopicStore, TopicStore


class TopicOperationError(Exception):
    def __init__(self, code: str, message: str | None = None, *, details: dict | None = None):
        known = ERROR_BY_CODE[code]
        super().__init__(message or known.message)
        self.code, self.message, self.retryable, self.details = code, message or known.message, known.retryable, details or {}


def error_envelope(name: str, code: str, message: str | None = None, *, details: dict | None = None) -> dict:
    error = TopicOperationError(code, message, details=details)
    return {"ok": False, "op": name, "error": {"code": error.code, "message": error.message, "retryable": error.retryable, "details": error.details}}


def execute(name: str, arguments: Any, caller: Caller | None = None, handlers: dict[str, Handler] | None = None) -> dict:
    """Run one operation and return its envelope (a success or an error). Never raises for a bad request."""
    caller = caller or Caller()
    item = operation(name) if isinstance(name, str) else None
    if item is None:
        return error_envelope(str(name), "unknown_operation", f"There is no topic operation named {name}.", details={"operation": str(name)})
    problem = check(item.input, arguments if arguments is not None else {})
    if problem:
        return error_envelope(name, "invalid_input", problem[1], details={"path": problem[0]})
    handler = (handlers if handlers is not None else {}).get(name)
    if handler is None:
        return error_envelope(name, "not_implemented", f"{name} is described but not built yet.", details={"operation": name})
    try:
        return ok_envelope(name, handler(arguments or {}, caller))
    except TopicOperationError as error:
        return error_envelope(name, error.code, error.message, details=error.details)


def params_from(client: Any, arguments: dict, corpus_id: str) -> TopicParams:
    from papyrus_content.editorial_context import find_section

    section_id = None
    if arguments.get("section"):
        found = find_section(client, arguments["section"])
        if not found:
            raise TopicOperationError("not_found", f"No section {arguments['section']!r} in this publication.", details={"section": arguments["section"]})
        section_id = found["id"]
    try:
        as_of = date.fromisoformat(arguments["asOf"]) if arguments.get("asOf") else None
    except ValueError as error:
        raise TopicOperationError("invalid_input", f"asOf must be a day, YYYY-MM-DD, not {arguments['asOf']!r}.", details={"path": "asOf"}) from error
    return TopicParams(
        corpus_id=corpus_id, window=arguments.get("window") or "14d", as_of=as_of, section_id=section_id, monitor=arguments.get("monitor"),
        states=tuple(arguments.get("states") or DEFAULT_STATES), min_cluster_size=arguments.get("minClusterSize"),
        compare=arguments.get("compareTo", "previous") == "previous", max_references=arguments.get("maxReferences"),
        representatives=arguments.get("representatives") or DEFAULT_REPRESENTATIVES, refresh=bool(arguments.get("refresh")))


def topics_model(client: Any, arguments: dict, caller: Caller, *, engine: TopicEngine, store: TopicStore, today: date | None = None) -> Outcome:
    from papyrus_content.editorial_context import hosted_publication

    try:
        publication = hosted_publication(client)
    except ValueError as error:
        raise TopicOperationError("service_unavailable", str(error)) from error
    params = params_from(client, arguments, publication["corpusId"])
    try:
        outcome = run_topics(client, params, engine=engine, store=store, today=today)
    except TopicEngineError as error:
        raise TopicOperationError("engine_failed", str(error)) from error
    return Outcome(outcome.result, publication["key"], outcome.warnings)


def with_client(client: Any, *, engine: TopicEngine, store: TopicStore, today: date | None = None) -> dict[str, Handler]:
    """The handlers bound to one client, one engine and one store (the tests, and any front end that owns them)."""
    return {"topics_model": lambda arguments, caller: topics_model(client, arguments, caller, engine=engine, store=store, today=today)}


def signed_in_handlers(client_factory: Callable[[], Any] | None = None, *, engine: TopicEngine | None = None, store: TopicStore | None = None) -> dict[str, Handler]:
    """The handlers on the signed-in lane: each call opens the person's own authoring client."""
    def handler(arguments: dict, caller: Caller) -> Outcome:
        if client_factory is not None:
            client = client_factory()
        else:
            from papyrus_content.graphql_authoring import create_authoring_client

            client = create_authoring_client()[0]
        return topics_model(client, arguments, caller, engine=engine or BiblicusTopicEngine(), store=store or FileTopicStore())

    return {"topics_model": handler}
