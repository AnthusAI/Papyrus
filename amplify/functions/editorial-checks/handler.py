"""The editorial-checks function: routes its GraphQL fields to papyrus_content.editorial_checks."""

from __future__ import annotations

from typing import Any

from papyrus_content.editorial_checks import GraphQLEditorialStore, Services, event_field_name, handle, load_provider_keys

# Amplify passes secrets to Python functions as placeholders; resolve them once per cold start.
load_provider_keys()


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    return handle(event_field_name(event), event.get("arguments") or {}, Services(store=GraphQLEditorialStore()))
