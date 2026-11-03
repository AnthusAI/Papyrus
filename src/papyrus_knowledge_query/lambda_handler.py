from __future__ import annotations

import json
from typing import Any

from .engine import run_knowledge_query
from .services import build_environment_services


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """One Lambda, two AppSync queries: ``searchReferences`` (the References page search box) and, for anything else, ``knowledgeQuery``."""
    input_payload = _extract_input(event)
    services = build_environment_services(event)
    if _field_name(event) == "searchReferences":
        return _search_references(event, input_payload, services)
    return run_knowledge_query(input_payload, services)


def _field_name(event: dict[str, Any]) -> str:
    """Amplify's Lambda resolvers send ``fieldName`` at the top of the event; a direct AppSync resolver sends it under ``info``."""
    if not isinstance(event, dict):
        return ""
    info = event.get("info")
    return str((info.get("fieldName") if isinstance(info, dict) else None) or event.get("fieldName") or "")


def _search_references(event: dict[str, Any], input_payload: dict[str, Any], services: Any) -> dict[str, Any]:
    from . import reference_search

    reference_search.require_editor(event)
    graph = getattr(services, "graph", None)
    return reference_search.search_references(
        input_payload,
        graphql=graph.graphql if graph is not None else None,
        vectors=services.semantic if hasattr(services.semantic, "query_by_vector") and hasattr(services.semantic, "embed_text") else None,
    )


def _extract_input(event: dict[str, Any]) -> dict[str, Any]:
    arguments = event.get("arguments") if isinstance(event, dict) else None
    raw_input = arguments.get("input") if isinstance(arguments, dict) and "input" in arguments else event
    if isinstance(raw_input, str):
        try:
            raw_input = json.loads(raw_input)
        except json.JSONDecodeError as exc:
            raise ValueError(f"knowledgeQuery input must be valid JSON: {exc}") from exc
    if not isinstance(raw_input, dict):
        raise TypeError("knowledgeQuery input must be a JSON object")
    return raw_input
