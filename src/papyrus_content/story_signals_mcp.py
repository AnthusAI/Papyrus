"""The Story signal operations as MCP tools, in the shape of ``page_refresh/mcp.py``: ``TOOLS.update(story_signal_tools())`` and
``DESCRIPTIONS.update(story_signal_descriptions())``, then ``call_story_signal_tool``. The inputs use the CLI's flag names in camelCase
(``--min-stars`` is ``minStars``), and the results carry the CLI's columns by name. There is no stories tool in the MCP server today; this adds the three."""

from __future__ import annotations

from typing import Any

from .story_signals import SORTS, list_stories, set_story_stars, signals, validated_stars

_STR = {"type": "string"}
_INT = {"type": "integer", "minimum": 0, "maximum": 5}


def _closed(properties: dict, required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


TOOLS_TABLE: dict[str, tuple[str, dict, str]] = {
    "stories_list": ("staff", _closed({
        "stage": _STR, "section": _STR, "type": {"type": "string", "description": "article or post"}, "stars": _INT, "minStars": _INT, "maxStars": _INT,
        "sort": {"type": "string", "enum": list(SORTS), "description": "rank = the order the Articles and Posts page shows first"},
        "bucket": {"type": "string", "enum": ["day", "week", "none"]}, "limit": {"type": "integer", "minimum": 1}}),
        "Lists Stories with their layout signals: stars (the effective quality rating, 0 unrated), source, votes, bucket, type, section, words, published. Private; staff only."),
    "stories_show": ("staff", _closed({"storyLineageId": _STR, "bucket": {"type": "string", "enum": ["day", "week", "none"]}}, ("storyLineageId",)),
                     "Shows one Story's layout signals and who rated it and when."),
    "stories_set_stars": ("staff", _closed({"storyLineageId": _STR, "stars": _INT, "dryRun": {"type": "boolean"}}, ("storyLineageId", "stars")),
                          "Sets the editor's rating of a Story, 1 to 5 (0 clears it), through the newsroom's setItemStars, which re-renders the listings whose order changed."),
}


def story_signal_tools() -> dict[str, tuple[str, dict]]:
    return {name: (audience, schema) for name, (audience, schema, _) in TOOLS_TABLE.items()}


def story_signal_descriptions() -> dict[str, str]:
    return {name: text for name, (_, _, text) in TOOLS_TABLE.items()}


def call_story_signal_tool(name: str, arguments: dict[str, Any], client) -> dict:
    args = arguments or {}
    if name == "stories_list":
        rows, total = list_stories(client, stage=args.get("stage"), section=args.get("section"), story_type=args.get("type"), stars=args.get("stars"),
                                   min_stars=args.get("minStars"), max_stars=args.get("maxStars"), sort=args.get("sort", "updated"), bucket=args.get("bucket"),
                                   limit=args.get("limit", 50))
        return {"stories": rows, "total": total}
    if name == "stories_show":
        from .home_page.ordering import utc_today
        from .projection.standard.config import DEFAULT_STORY_BUCKET
        from .story_reporting import current_story_version

        return signals(current_story_version(client, args["storyLineageId"]), args.get("bucket") or DEFAULT_STORY_BUCKET, utc_today())
    if name == "stories_set_stars":
        return set_story_stars(client, args["storyLineageId"], validated_stars(args["stars"], "stars"), apply=not args.get("dryRun"))
    raise ValueError(f"Unknown story tool {name}.")
