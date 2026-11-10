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
    # No field names a relation: the one official type (story_links.STORY_LINK_RELATION) is written by the code, and additionalProperties is false.
    "papyrus_link_stories": ("staff", _closed({
        "story": {"type": "string", "description": "lineage id or slug of the story that gets the See also block"},
        "see_also_stories": {"type": "array", "items": _STR, "description": "lineage ids or slugs of the stories it goes with"},
        "see_also_references": {"type": "array", "items": _STR, "description": "ids of accepted References to read too (the page shows accepted References only; a Reference that is not accepted refuses the whole call)"},
        "note": _STR, "dryRun": {"type": "boolean"}}, ("story",)),
        "Links a story to other stories for its See also block. Every one must be an existing story and none the story itself; a link that exists in either direction is left alone. "
        "Returns each target's title, type, stage, outcome (write, exists or dry run) and a warning when it is not published yet (the public block shows published stories only). "
        "Give at least one story or Reference; see_also_references links the story to accepted References (directional, story to Reference). "
        "After a real write that created a link, the published stories whose page changed are re-rendered at once with no purge; `rerendered` lists them (lineageId, status ok or failed, purged false) and a failure is in `rerenderWarnings`, never an error. The change shows on the site within about five minutes."),
    "papyrus_suggest_links": ("staff", _closed({
        "story": {"type": "string", "description": "lineage id or slug of the story"},
        "kinds": {"type": "array", "items": {"type": "string", "enum": ["articles", "posts", "references"]}},
        "limit": {"type": "integer", "minimum": 1}}, ("story",)),
        "Read only. Ranked related articles, posts and accepted References for a story, computed from its concepts and the concepts related to them (no model call). Each candidate has a score, "
        "the shared concepts, the path ('direct' or 'via A, then B') and the exact link command. Already linked content is left out. You judge the short list, then link the good ones."),
    "papyrus_related_concepts": ("staff", _closed({
        "concept": {"type": "string", "description": "exact node key, hashtag, name or alias of an accepted concept"},
        "limit": {"type": "integer", "minimum": 1}}, ("concept",)),
        "Read only. The concepts near a concept: editor-confirmed links with their explanation, aliases, and concepts that co-occur on the same stories and References (count, lift, strength)."),
    "papyrus_search_concepts": ("staff", _closed({
        "query": {"type": "string", "description": "free text to find concepts for; leave out with list=true"},
        "list": {"type": "boolean", "description": "list every accepted concept alphabetically instead of searching"},
        "limit": {"type": "integer", "minimum": 1}}, ()),
        "Read only. Finds accepted concepts by meaning (one embedding, concept vectors only); an exact or prefix name match comes first. Order is relevance, never popularity. Each result has the node key, reason, "
        "similarity, whether it has a public wiki page, counts of stories and References that carry it (information only) and a duplicate flag. Reports an empty or stale concept index with the command that rebuilds it."),
    "papyrus_link_concepts": ("staff", _closed({
        "target_kind": {"type": "string", "enum": ["story", "reference"]},
        "target": {"type": "string", "description": "a story's lineage id or slug, or a Reference id"},
        "concepts": {"type": "array", "items": _STR, "minItems": 1, "description": "exact node keys, hashtags, names or aliases of EXISTING accepted concepts"},
        "note": _STR, "dryRun": {"type": "boolean"}}, ("target_kind", "target", "concepts")),
        "Tags a story or a Reference with existing accepted concepts. Matching is exact (node key, hashtag, name or alias, case-insensitive); a concept is never created; an unknown name "
        "returns the closest accepted concepts, an ambiguous one its node keys. Existing tags (also the older related_to, or mentions) are left alone and a rejected tag stays rejected. "
        "Returns each concept's outcome and whether it has a public wiki page (a warning says when it does not). No field chooses a relation or a state. "
        "A story whose tag was newly written is re-rendered at once with no purge (`rerendered`; a failure is in `rerenderWarnings`, never an error); a Reference has no public page, so nothing is re-rendered."),
}


def story_signal_tools() -> dict[str, tuple[str, dict]]:
    return {name: (audience, schema) for name, (audience, schema, _) in TOOLS_TABLE.items()}


def story_signal_descriptions() -> dict[str, str]:
    return {name: text for name, (_, _, text) in TOOLS_TABLE.items()}


def call_story_signal_tool(name: str, arguments: dict[str, Any], client, actor: str | None = None) -> dict:
    """``actor`` is the signed-in person the server names for a write (papyrus_link_stories); an argument can never supply it."""
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
    if name == "papyrus_link_stories":
        from .story_links import link_reference_set, link_story_set, resolve_link_references, resolve_link_targets, resolve_story

        unknown = set(args) - {"story", "see_also_stories", "see_also_references", "note", "dryRun"}
        if unknown:
            raise ValueError(f"Unknown argument(s) for papyrus_link_stories: {', '.join(sorted(unknown))}. There is no relation to choose.")
        targets, reference_ids = list(args.get("see_also_stories") or []), list(args.get("see_also_references") or [])
        if not targets and not reference_ids:
            raise ValueError("Give see_also_stories or see_also_references.")
        story, others = resolve_link_targets(client, args["story"], targets) if targets else (resolve_story(client, args["story"]), [])
        references = resolve_link_references(client, reference_ids)
        rows = link_story_set(client, story, others, actor=actor, provenance="derived", note=args.get("note") or None, apply=not args.get("dryRun"))
        reference_rows = link_reference_set(client, story, references, actor=actor, provenance="derived", note=args.get("note") or None, apply=not args.get("dryRun"))
        from .story_rerender import rerender_after_write, signed_in_request, tool_result

        lineage = story.get("lineageId") or story["id"]
        wrote = [row for row in rows if row["outcome"] == "write"]
        changed = [lineage, *(row["lineageId"] for row in wrote)] if wrote or any(row["outcome"] == "write" for row in reference_rows) else []
        done = rerender_after_write(client, changed, enabled=not args.get("dryRun"), request=signed_in_request)
        return {"story": lineage, "dryRun": bool(args.get("dryRun")), "links": rows, "referenceLinks": reference_rows, **tool_result(done)}
    if name == "papyrus_suggest_links":
        from .link_suggestions import suggest_links

        unknown = set(args) - {"story", "kinds", "limit"}
        if unknown:
            raise ValueError(f"Unknown argument(s) for papyrus_suggest_links: {', '.join(sorted(unknown))}.")
        return suggest_links(client, args["story"], kinds=tuple(args.get("kinds") or ("articles", "posts", "references")), limit=int(args.get("limit") or 5))
    if name == "papyrus_related_concepts":
        from .link_suggestions import related_concepts

        unknown = set(args) - {"concept", "limit"}
        if unknown:
            raise ValueError(f"Unknown argument(s) for papyrus_related_concepts: {', '.join(sorted(unknown))}.")
        return related_concepts(client, args["concept"], limit=int(args.get("limit") or 15))
    if name == "papyrus_search_concepts":
        from .concept_search import default_provider, search_concepts

        unknown = set(args) - {"query", "list", "limit"}
        if unknown:
            raise ValueError(f"Unknown argument(s) for papyrus_search_concepts: {', '.join(sorted(unknown))}.")
        return search_concepts(client, None if args.get("list") else default_provider(), args.get("query"), limit=int(args.get("limit") or 10), list_all=bool(args.get("list")))
    if name == "papyrus_link_concepts":
        from .concept_tags import tag_with_concepts

        unknown = set(args) - {"target_kind", "target", "concepts", "note", "dryRun"}
        if unknown:
            raise ValueError(f"Unknown argument(s) for papyrus_link_concepts: {', '.join(sorted(unknown))}. There is no relation or state to choose.")
        result = tag_with_concepts(client, args["target_kind"], args["target"], list(args["concepts"]), actor=actor, provenance="derived", note=args.get("note") or None,
                                   apply=not args.get("dryRun"))
        if args["target_kind"] != "story":   # a Reference has no public page: nothing to re-render
            return result
        from .story_rerender import rerender_after_write, signed_in_request, tool_result

        wrote = any(row["outcome"] == "write" for row in result["concepts"])
        return {**result, **tool_result(rerender_after_write(client, [result["target"]] if wrote else [], enabled=not args.get("dryRun"), request=signed_in_request))}
    raise ValueError(f"Unknown story tool {name}.")
