"""The one table of page-refresh operations (PPY-105508), the way ``images/operations.py`` is for pictures.

An ``Operation`` is an MCP tool name, a CLI form, an input schema and a sentence. The CLI (``cli.py``), the MCP tools (``mcp.py``) and the
content-actions Lambda all read this table and run ``run_operation`` over ``service.RefreshService``, so none of them can drift from another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .service import RERENDER_SCOPES, RefreshError, RefreshService

_DRY_RUN = {"type": "boolean", "description": "Only show the paths (and, for a re-render, the pages it would write). Nothing is written or invalidated."}


@dataclass(frozen=True)
class Operation:
    name: str                 # the MCP tool name
    cli: str                  # the form of the command after `papyrus ops content`
    summary: str              # one plain sentence: MCP description, CLI help, docs, skill
    input: dict               # JSON Schema (closed object)
    run: Callable[[RefreshService, dict], dict]
    audience: str = "staff"


def _closed(properties: dict, required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


OPERATIONS: tuple[Operation, ...] = (
    Operation(
        "site_refresh_pages",
        "refresh --path PATH [--path PATH ...] [--dry-run] [--json]",
        "Make an edit visible now on the pages named: purge each under every URL form it is cached under (/dir/ and /dir/index.html) and its Markdown twin.",
        _closed(
            {"paths": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1, "description": "Site paths such as /articles/my-story/ or /."}, "dryRun": _DRY_RUN},
            ("paths",),
        ),
        lambda service, args: service.refresh_pages(args["paths"], dry_run=bool(args.get("dryRun"))),
    ),
    Operation(
        "site_refresh_story",
        "refresh --story LINEAGE [--dry-run] [--json]",
        "Make a Story's edit visible now: purge its page and Markdown twin and every index page that lists it (home, its list and section pages, paging).",
        _closed({"storyLineageId": {"type": "string", "minLength": 1, "description": "The Story's lineage id."}, "dryRun": _DRY_RUN}, ("storyLineageId",)),
        lambda service, args: service.refresh_story(args["storyLineageId"], dry_run=bool(args.get("dryRun"))),
    ),
    Operation(
        "site_refresh_indexes",
        "refresh --indexes [--dry-run] [--json]",
        "Purge the home page, every list page and every section page (with paging and Markdown twins). Never the whole site.",
        _closed({"dryRun": _DRY_RUN}),
        lambda service, args: service.refresh_indexes(dry_run=bool(args.get("dryRun"))),
    ),
    Operation(
        "site_rerender_pages",
        "rerender (--story LINEAGE | --indexes | --all) [--no-invalidate] [--dry-run] [--json]",
        "Rebuild pages from the hooks and templates the site has deployed now, without a content change, then purge the pages it wrote.",
        _closed(
            {
                "scope": {"type": "string", "enum": list(RERENDER_SCOPES), "description": "story: one Story's pages; indexes: every list page; all: every page of the site."},
                "storyLineageId": {"type": "string", "minLength": 1, "description": "The Story's lineage id; only with scope story."},
                "invalidate": {"type": "boolean", "description": "Purge the pages written (default true)."},
                "dryRun": _DRY_RUN,
            },
            ("scope",),
        ),
        lambda service, args: service.rerender(args["scope"], lineage=args.get("storyLineageId"), invalidate=args.get("invalidate", True) is not False, dry_run=bool(args.get("dryRun"))),
    ),
)
BY_NAME = {operation.name: operation for operation in OPERATIONS}


def validate(operation: Operation, arguments: Any) -> dict:
    """The small subset of JSON Schema the inputs use. Raises ``RefreshError('invalid_input')`` naming the field."""
    if not isinstance(arguments, dict):
        raise RefreshError("invalid_input", "The input must be an object.")
    schema = operation.input
    properties = schema["properties"]
    for name in arguments:
        if name not in properties:
            raise RefreshError("invalid_input", f"{name}: not an input of {operation.name}.")
    for name in schema["required"]:
        if arguments.get(name) in (None, "", []):
            raise RefreshError("invalid_input", f"{name}: required by {operation.name}.")
    for name, value in arguments.items():
        spec = properties[name]
        kind = spec["type"]
        good = (
            (kind == "boolean" and isinstance(value, bool))
            or (kind == "string" and isinstance(value, str) and bool(value.strip()) and ("enum" not in spec or value in spec["enum"]))
            or (kind == "array" and isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value))
        )
        if not good:
            raise RefreshError("invalid_input", f"{name}: expected {kind}" + (f" (one of {', '.join(spec['enum'])})" if "enum" in spec else "") + ".")
    return arguments


def run_operation(name: str, arguments: Any, service: RefreshService) -> dict:
    """Run one operation and return its result: the same JSON the CLI prints. A request that cannot run returns ``{"ok": false, "error": {...}}``."""
    operation = BY_NAME.get(name)
    if operation is None:
        return {"ok": False, "operation": name, "error": {"code": "unknown_operation", "message": f"There is no page-refresh operation {name!r}."}}
    try:
        return operation.run(service, validate(operation, arguments))
    except RefreshError as error:
        return {"ok": False, "operation": name, "error": {"code": error.code, "message": error.message}}
