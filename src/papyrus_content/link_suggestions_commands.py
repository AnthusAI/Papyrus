"""`papyrus knowledge concepts related` and `papyrus stories suggest-links` (read only; docs/story-reporting.md, "Suggesting related content")."""

from __future__ import annotations

import json

from .graphql_authoring import create_authoring_client
from .link_suggestions import KIND_LABELS, related_concepts, suggest_links
from .options import normalize_string, parse_options

KINDS = tuple(KIND_LABELS)


def _limit(options: dict, name: str, default: int) -> int:
    value = normalize_string(options.get(name))
    if value is None:
        return default
    if value is True or not str(value).isdigit() or int(value) < 1:
        raise ValueError(f"--{name} must be a whole number of at least 1.")
    return int(value)


def relations_related(flags: list[str]) -> None:
    """papyrus knowledge concepts related --concept NAME|#HASHTAG|NODEKEY [--limit N] [--json]

    Read only. Lists the concepts near a concept, with the reason: editor-confirmed concept links (with the explanation a person wrote), aliases and same_as, and
    concepts that appear together with it on published stories and accepted References (newest 60 carriers; count, lift and strength, so hubs do not dominate).
    The concept is found with the exact resolver of `stories link-concept`; it is never created and never matched fuzzily."""
    options = parse_options(flags)
    concept = normalize_string(options.get("concept"))
    if not concept or concept is True:
        raise ValueError("--concept is required (a name, #hashtag or node key).")
    client, _ = create_authoring_client()
    result = related_concepts(client, concept, limit=_limit(options, "limit", 15))
    if options.get("json"):
        print(json.dumps({"ok": True, **result}, indent=2))
        return
    head = result["concept"]
    print(f"concepts\trelated\t{head['name']}\t{head['nodeKey']}\tcarried by {result['carriers']['stories']} stories and {result['carriers']['references']} References")
    for entry in result["related"]:
        if entry["reason"] == "cooccurrence":
            detail = f"together on {entry['count']} of {entry['sampled']}\tlift {entry['lift']}\tstrength {entry['strength']}"
        else:
            detail = f"{entry['predicate']}\t{entry.get('explanation') or ''}"
        print("\t".join(["concepts", "related", entry["name"], str(entry["nodeKey"]), entry["reason"], detail]))
    print(f"concepts\trelated\t{len(result['related'])} related concept(s); {result['requests']} request(s)")


def stories_suggest_links(flags: list[str]) -> None:
    """papyrus stories suggest-links --story LINEAGE|SLUG [--kinds articles,posts,references] [--limit N] [--min-score S] [--json]

    Read only; writes nothing. Starts from the story's concepts (curated tags, then accepted mentions), expands them to related concepts, and scans those for the
    published articles and posts and accepted References that carry them. Scores are rarity-weighted (rare shared concepts count most). Already linked stories (either
    direction), References already linked as evidence or see_also, unpublished stories and non-accepted References are left out. Each candidate shows the shared
    concepts, the path ('direct' or 'via A, then B') and the exact command that links it; a person or model only judges the list."""
    options = parse_options(flags)
    story = normalize_string(options.get("story"))
    if not story or story is True:
        raise ValueError("--story is required (a lineage id or slug).")
    raw_kinds = normalize_string(options.get("kinds"))
    kinds = tuple(dict.fromkeys(part.strip() for part in str(raw_kinds).split(",") if part.strip())) if raw_kinds and raw_kinds is not True else KINDS
    for kind in kinds:
        if kind not in KINDS:
            raise ValueError(f"--kinds takes {', '.join(KINDS)}; {kind!r} is not one.")
    minimum = normalize_string(options.get("min-score"))
    try:
        min_score = float(minimum) if minimum and minimum is not True else 0.0
    except ValueError as error:
        raise ValueError("--min-score must be a number.") from error
    client, _ = create_authoring_client()
    result = suggest_links(client, story, kinds=kinds, limit=_limit(options, "limit", 5), min_score=min_score)
    if options.get("json"):
        print(json.dumps({"ok": True, **result}, indent=2))
        return
    print(f"stories\tsuggest-links\t{result['story']['lineageId']}\t{result['story']['title']}\t{len(result['concepts'])} concept(s) scanned; "
          f"{result['linkedStories']} story link(s) and {result['linkedReferences']} Reference link(s) already exist")
    if result.get("note"):
        print(f"stories\tsuggest-links\t{result['note']}")
    for kind in kinds:
        items = result["candidates"].get(kind) or []
        print(f"\n{KIND_LABELS[kind]} ({kind}): {len(items)}")
        for index, item in enumerate(items, 1):
            print(f"  {index}. {item['score']:.2f}\t{item['title']}\t{item['type']}\t{item['date'] or '-'}\tshared: {', '.join(item['shared'])}\tpath: {item['path']}")
            print(f"     {item['command']}")
    print(f"\nstories\tsuggest-links\t{result['requests']} request(s)")
