"""Wait until the live GraphQL API serves every field the content tools select.

A backend deploy that adds attributes to a model updates the AppSync schema and the Lambda code in the same stack update.
CloudFormation reports the schema resource complete before every AppSync endpoint validates queries against it, so
code that already selects a new field can be told the field is undefined (the first deploy of Papyrus 5.107.2 on Machines on
Machines failed this way). The post-deploy render therefore asks the live schema first, by introspection, and waits until it has
the fields the tools select. If it never does, the failure names the missing fields."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .graphql_authoring import GET_DEFINITIONS

SCHEMA_WAIT_SECONDS = 300
SCHEMA_POLL_SECONDS = 10
# A listing of a model's rows that leaves out the body is a selection on the same GraphQL type.
TYPE_OF_MODEL = {"PublishedItemSummary": "PublishedItem"}


class LiveSchemaIncomplete(RuntimeError):
    """The live API schema lacks fields that the deployed code selects."""


def selected_fields() -> dict[str, set[str]]:
    """The fields the tools select, by GraphQL type name."""
    selected: dict[str, set[str]] = {}
    for model, definition in GET_DEFINITIONS.items():
        selected.setdefault(TYPE_OF_MODEL.get(model, model), set()).update(definition["fields"].split())
    return selected


def missing_fields(client: Any, selected: dict[str, set[str]] | None = None) -> list[str]:
    """`Type.field` for every selected field the live schema does not have. A model the backend does not include is not checked."""
    selected = selected if selected is not None else selected_fields()
    types = sorted(selected)
    query = "query LiveSchema {\n" + "\n".join(
        f'  t{index}: __type(name: "{name}") {{ fields {{ name }} }}' for index, name in enumerate(types)
    ) + "\n}"
    data = client.graphql(query)
    missing: list[str] = []
    for index, name in enumerate(types):
        live = data.get(f"t{index}")
        if live is None:
            continue
        served = {field["name"] for field in live["fields"]}
        missing.extend(f"{name}.{field}" for field in sorted(selected[name] - served))
    return missing


def wait_for_live_schema(
    client: Any,
    *,
    timeout_seconds: float = SCHEMA_WAIT_SECONDS,
    poll_seconds: float = SCHEMA_POLL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    deadline = clock() + timeout_seconds
    while True:
        missing = missing_fields(client)
        if not missing:
            return
        if clock() >= deadline:
            raise LiveSchemaIncomplete(
                f"The live GraphQL schema still lacks {', '.join(missing)} after {timeout_seconds:g} seconds. "
                "The deployed code selects these fields, so the schema in this deploy does not match the code."
            )
        sleep(poll_seconds)
