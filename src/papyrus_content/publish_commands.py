"""CLI entries for ``papyrus content publish`` and ``unpublish`` (PPY-b3a10e)."""

from __future__ import annotations

import json
from typing import Any, Callable

from .graphql_authoring import create_authoring_client
from .options import normalize_string, parse_options, resolve_mutation_apply
from .publishing import DryRunClient, PublishError, publish_item, unpublish_item

DEFAULT_ACTOR = "papyrus-cli"


def resolve_item_id(client, options: dict[str, Any]) -> str:
    item_id = normalize_string(options.get("id"))
    slug = normalize_string(options.get("slug"))
    if bool(item_id) == bool(slug):
        raise ValueError("Pass exactly one of --id <item-id> or --slug <slug>.")
    if item_id:
        return item_id
    section = normalize_string(options.get("section"))
    matches = client.list_by_index("itemBySlug", slug)
    if section:
        matches = [match for match in matches if match.get("section") == section]
    if not matches:
        raise ValueError(f"No item with slug {slug!r}.")
    if len(matches) > 1:
        ids = ", ".join(sorted(match["id"] for match in matches))
        raise ValueError(f"Slug {slug!r} matches more than one item ({ids}); pass --id.")
    return matches[0]["id"]


def _run(flags: list[str], label: str, action: Callable[..., Any]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, label)
    client, claims = create_authoring_client()
    actor = normalize_string((claims or {}).get("sub")) or DEFAULT_ACTOR
    item_id = resolve_item_id(client, options)
    target = client if apply else DryRunClient(client)
    try:
        result = action(target, item_id, actor=actor)
    except PublishError as error:
        payload = {
            "ok": False,
            "code": error.code,
            "message": error.message,
            "errors": [entry.to_dict() for entry in error.errors],
        }
        print(json.dumps(payload, indent=2) if options.get("json") else f"{label} failed [{error.code}]: {error.message}")
        raise SystemExit(1)
    planned = [] if apply else target.planned
    payload = {
        "ok": True,
        "dryRun": not apply,
        "changed": result.changed,
        "itemId": result.item_id,
        "publishedItemId": result.published_item_id,
        "versionNumber": result.version_number,
        "planned": planned,
    }
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return
    state = "changed" if result.changed else "unchanged"
    print(f"{label}: {result.item_id} {state} (published version {result.version_number})")
    for entry in planned:
        print(f"  would {entry['operation']} {entry['model']} {entry['id']}")


def content_publish(flags: list[str]) -> None:
    _run(flags, "content publish", publish_item)


def content_unpublish(flags: list[str]) -> None:
    _run(flags, "content unpublish", unpublish_item)
