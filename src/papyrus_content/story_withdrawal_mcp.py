"""``stories_withdraw`` and ``stories_restore`` as MCP tools, in the shape of ``story_signals_mcp.py``: ``TOOLS.update(story_withdrawal_tools())`` and
``DESCRIPTIONS.update(story_withdrawal_descriptions())``, then ``call_story_withdrawal_tool``. The inputs use the CLI's flag names in camelCase
(``--force-paths`` is ``forcePaths``), and the result is the JSON the operation returns (``status``, ``plan``, ``purge``). The MCP server is not in this
repository and has no registry to add these to, so they follow the same standalone pattern as the page-refresh and Story-signal tools."""

from __future__ import annotations

from typing import Any

from .story_withdrawal import WithdrawalError, restore_story, withdraw_story

_STR = {"type": "string"}
_COMMON = {
    "storyLineageId": _STR,
    "authorLabel": {"type": "string", "description": "Who is acting; recorded on the Story."},
    "dryRun": {"type": "boolean", "description": "Only return the plan. Nothing is written or purged."},
    "run": {"type": "boolean", "description": "Do it. More than 5 paths are a dry run until this is set."},
    "forcePaths": {"type": "integer", "minimum": 1, "description": "Allow this one call above the per-call cap of 25 paths."},
}


def _closed(properties: dict, required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


TOOLS_TABLE: dict[str, tuple[str, dict, str]] = {
    "stories_withdraw": (
        "staff",
        _closed({**_COMMON, "reason": _STR}, ("storyLineageId",)),
        "Takes a published Story down: returns the exact plan (pages, purge paths, count, cost) first, then unpublishes it, projects the pages away, moves the board stage to spiked, "
        "records the withdrawal on the Story and purges exactly the planned paths. The old address shows the site's 404 page. Refuses an unpublished Story and a plan over the path cap.",
    ),
    "stories_restore": (
        "staff",
        _closed(_COMMON, ("storyLineageId",)),
        "Republishes the version stories_withdraw took down, puts the stage back to published, clears the withdrawal record and purges the same pages. Refuses when nothing was withdrawn.",
    ),
}


def story_withdrawal_tools() -> dict[str, tuple[str, dict]]:
    return {name: (audience, schema) for name, (audience, schema, _) in TOOLS_TABLE.items()}


def story_withdrawal_descriptions() -> dict[str, str]:
    return {name: text for name, (_, _, text) in TOOLS_TABLE.items()}


def call_story_withdrawal_tool(name: str, arguments: dict[str, Any], client, **hooks: Any) -> dict:
    """``hooks`` (``lane``, ``trigger``, ``now``) are for tests."""
    args = arguments or {}
    if name not in TOOLS_TABLE:
        raise ValueError(f"Unknown story tool {name}.")
    common = dict(actor=args.get("authorLabel") or "mcp", dry_run=bool(args.get("dryRun")), run=bool(args.get("run")), force_paths=args.get("forcePaths"), **hooks)
    try:
        if name == "stories_withdraw":
            return withdraw_story(client, args["storyLineageId"], reason=args.get("reason"), **common)
        return restore_story(client, args["storyLineageId"], **common)
    except WithdrawalError as error:
        return {"ok": False, "operation": name, "error": {"code": error.code, "message": error.message}}
