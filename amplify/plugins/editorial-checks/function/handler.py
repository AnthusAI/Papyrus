"""The editorial-checks plugin's function: routes its GraphQL fields to papyrus_content.editorial_checks."""

from __future__ import annotations

from typing import Any

from papyrus_content.editorial_checks import GraphQLEditorialStore, Services, handle


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    return handle(event["info"]["fieldName"], event.get("arguments") or {}, Services(store=GraphQLEditorialStore()))
