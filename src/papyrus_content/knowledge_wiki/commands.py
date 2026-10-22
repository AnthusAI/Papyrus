"""CLI entries: ``papyrus knowledge wiki sync | publish``."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from ..graphql_authoring import create_authoring_client
from ..knowledge_snapshot.commands import announce_backend, load_knowledge_data, select_backend
from ..knowledge_snapshot.keys import slug
from ..knowledge_snapshot.loaders import CURRENT, beats_from_categories
from ..options import normalize_string, parse_comma_list, parse_options
from ..publish_commands import DEFAULT_ACTOR, run_site_triggers
from ..publishing import ItemFields, PublishError, _parse_json_object, publish_item, published_item_id_for, save_item
from ..wiki_stamp import ACTORS, REVIEW_KEY, UPDATED_KEY, WIKI_PAGE_ITEM_TYPE, review_mapping, stamp_problems
from .pages import KIND_BEAT, KIND_ENTITY, KIND_SUBTOPIC, front_matter_yaml
from .sync import (
    DEFAULT_ITEMS_PER_TOPIC,
    DEFAULT_MINIMUM_SUBTOPIC_ITEMS,
    UNCHANGED,
    TopicOptions,
    apply_plan,
    entity_specs,
    front_matter_of,
    live_sources,
    plan_sync,
    topic_specs,
    wiki_lineages,
    working_version,
)

DEFAULT_WIKI_SECTION = "wiki"
DEFAULT_TOPICS_SECTION = "topics"
SYNC_ACTOR = "papyrus-wiki-sync"


class _NoPages:
    """Item URLs are not needed to sync: entity pages never read them."""

    policy = None

    def item_page_paths(self, _summary):
        return ()


def _whole(options: dict[str, Any], name: str, default: int, minimum: int = 0) -> int:
    value = normalize_string(options.get(name))
    if value is None:
        return default
    try:
        number = int(value)
    except ValueError:
        number = minimum - 1
    if number < minimum:
        raise ValueError(f"--{name} must be a whole number of at least {minimum}.")
    return number


def _category_context(client: Any, options: dict[str, Any], data) -> tuple[list[dict], dict[str, str], dict[str, list]]:
    """Category rows of the beat source, the beats' descriptions and each beat's accepted subtopics (with descriptions)."""
    set_id = normalize_string(options.get("beats-category-set"))
    if not set_id:
        return [], {}, {}
    rows = [row for row in client.list_records("Category") if row.get("versionState", CURRENT) == CURRENT and row.get("status") == "accepted"]
    descriptions = {slug(row["categoryKey"]) or row["categoryKey"]: str(row.get("description") or "") for row in rows if row.get("categorySetId") == set_id}
    roots = {
        (slug(row["categoryKey"]) or row["categoryKey"]): row["categoryKey"]
        for row in rows
        if row.get("categorySetId") == set_id and not row.get("parentCategoryKey")
    }
    children: dict[str, list] = {}
    for beat in data.beats:
        raw = roots.get(beat.key)
        if raw is None:
            continue
        found = beats_from_categories(rows, set_id, list(data.clusters), list(data.items), None, parent_key=raw)
        children[beat.key] = [(child, descriptions.get(child.key) or None) for child in found]
    return rows, {key: text for key, text in descriptions.items() if text}, children


def _print_plan(plan, apply: bool, as_json: bool, written: dict[str, int]) -> None:
    if as_json:
        print(
            json.dumps(
                {
                    "mode": "apply" if apply else "dry-run",
                    "counts": plan.counts,
                    "pages": [
                        {"action": page.action, "section": page.section, "slug": page.spec.slug, "kind": page.spec.kind, "note": page.note}
                        for page in plan.pages
                    ],
                    "warnings": list(plan.warnings),
                    "written": written,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    print(f"knowledge\twiki-sync\tmode\t{'apply' if apply else 'dry-run'}")
    for page in plan.pages:
        if page.action != UNCHANGED:
            note = f"\t{page.note}" if page.note else ""
            print(f"knowledge\twiki-sync\t{page.action}\t{page.spec.kind}\t{page.section}/{page.spec.slug}{note}")
    for name, count in plan.counts.items():
        print(f"knowledge\twiki-sync\tplan\t{name}\t{count}")
    for warning in plan.warnings:
        print(f"knowledge\twiki-sync\twarning\t{warning}")
    print("knowledge\twiki-sync\tpublish\tnever: pages stay drafts until `papyrus knowledge wiki publish`")
    if not apply:
        print("knowledge\twiki-sync\tapply\tskipped\tpass --apply to write")


def knowledge_wiki_sync(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = options.get("apply") is True
    section = normalize_string(options.get("section")) or DEFAULT_WIKI_SECTION
    topics_section = normalize_string(options.get("topics-section")) or DEFAULT_TOPICS_SECTION
    with_topics = bool(options.get("beats-config") or options.get("beats-category-set")) and not options.get("no-topics")
    topic_options = TopicOptions(
        minimum_subtopic_items=_whole(options, "subtopic-min-items", DEFAULT_MINIMUM_SUBTOPIC_ITEMS, 1),
        items_per_topic=_whole(options, "items-per-topic", DEFAULT_ITEMS_PER_TOPIC, 1),
        url_template=normalize_string(options.get("topics-url")) or f"/{topics_section}/{{slug}}/",
        sections=tuple(parse_comma_list(options.get("topic-sections")) or ()),
    )
    select_backend(options)
    client, claims = create_authoring_client()
    announce_backend()
    data = load_knowledge_data(client, _NoPages(), options)
    rows = client.list_records("Item")
    specs = entity_specs(data, wiki_lineages(rows, section))
    section_of = {KIND_ENTITY: section}
    if with_topics:
        _rows, descriptions, children = _category_context(client, options, data)
        specs += topic_specs(data, wiki_lineages(rows, topics_section), topic_options, descriptions=descriptions, subtopics_of=children)
        section_of |= {KIND_BEAT: topics_section, KIND_SUBTOPIC: topics_section}
    lineages = {lineage for name in set(section_of.values()) for lineage in wiki_lineages(rows, name)}
    plan = plan_sync(specs, section_of, rows, live_sources(client, lineages))
    written: dict[str, int] = {}
    if apply:
        written = apply_plan(client, plan, actor=normalize_string((claims or {}).get("sub")) or SYNC_ACTOR)
    _print_plan(plan, apply, bool(options.get("json")), written)


def _split_positional(flags: list[str]) -> tuple[str | None, list[str]]:
    if flags and not flags[0].startswith("--"):
        return flags[0], flags[1:]
    return None, flags


def _find_target(rows: list[dict], identifier: str, section: str | None) -> dict:
    wiki = [row for row in rows if row.get("type") == WIKI_PAGE_ITEM_TYPE and (not section or row.get("section") == section)]
    matches = {str(row.get("lineageId") or row["id"]) for row in wiki if identifier in (row["id"], row.get("lineageId"))}
    if not matches:
        matches = {str(row.get("lineageId") or row["id"]) for row in wiki if row.get("slug") == identifier}
    if not matches:
        raise ValueError(f"No wiki page {identifier!r} (give an item id or a slug).")
    if len(matches) > 1:
        raise ValueError(f"{identifier!r} names {len(matches)} wiki pages; pass --section or an item id.")
    lineage = matches.pop()
    return working_version([row for row in wiki if str(row.get("lineageId") or row["id"]) == lineage])


def _needs_publishing(client: Any, working: dict) -> bool:
    live = client.get_record("PublishedItem", published_item_id_for(str(working.get("lineageId") or working["id"])))
    if live is None or live.get("sourceItemId") != working["id"]:
        return True
    return _parse_json_object(live.get("metadata")).get("sourceContentHash") != working.get("contentHash")


def knowledge_wiki_publish(flags: list[str]) -> None:
    identifier, rest = _split_positional(flags)
    options = parse_options(rest)
    apply = options.get("apply") is True
    all_drafts = options.get("all-drafts") is True
    if bool(identifier) == all_drafts:
        raise ValueError("Pass one wiki page (an item id or slug) or --all-drafts.")
    actor = normalize_string(options.get("actor"))
    if actor not in ACTORS:
        raise ValueError(f"--actor must be one of {', '.join(ACTORS)}: ai when an AI agent edited the page, human when a person reviewed it.")
    name = normalize_string(options.get("actor-name"))
    on = normalize_string(options.get("on")) or datetime.now(timezone.utc).date().isoformat()
    review = review_mapping(actor, name, on)
    section = normalize_string(options.get("section"))
    select_backend(options)
    client, claims = create_authoring_client()
    announce_backend()
    who = normalize_string((claims or {}).get("sub")) or DEFAULT_ACTOR
    rows = client.list_records("Item")
    if identifier:
        targets = [_find_target(rows, identifier, section)]
    else:
        wiki = [row for row in rows if row.get("type") == WIKI_PAGE_ITEM_TYPE and (not section or row.get("section") == section)]
        lineages: dict[str, list[dict]] = {}
        for row in wiki:
            lineages.setdefault(str(row.get("lineageId") or row["id"]), []).append(row)
        targets = [working for working in (working_version(group) for _lineage, group in sorted(lineages.items())) if _needs_publishing(client, working)]
    outcomes: Counter = Counter()
    report: list[dict[str, Any]] = []
    failed = False
    for working in targets:
        front = front_matter_of(working)
        stamped = {**front, REVIEW_KEY: review, UPDATED_KEY: on}
        label = f"{working.get('section')}/{working.get('slug')}"
        problems = stamp_problems(stamped)
        if problems:
            print(f"knowledge\twiki-publish\tfailed\t{label}\t{'; '.join(problems)}")
            failed = True
            continue
        if not apply:
            outcomes["would-publish"] += 1
            report.append({"item": working["id"], "page": label, "result": "would-publish"})
            print(f"knowledge\twiki-publish\twould publish\t{label}\t{review['actor']}\t{on}")
            continue
        text = front_matter_yaml(stamped)
        if stamped != front:
            save_item(
                client,
                ItemFields(
                    type=WIKI_PAGE_ITEM_TYPE, slug=working["slug"], section=working.get("section"), front_matter_yaml=text,
                    body_markus=working.get("bodyMarkus") or "", aliases=list(working.get("aliases") or []), id=working["id"],
                ),
                actor=who,
            )
        try:
            result = publish_item(client, working["id"], actor=who)
        except PublishError as error:
            print(f"knowledge\twiki-publish\tfailed\t{label}\t[{error.code}] {error.message}")
            failed = True
            continue
        triggers = run_site_triggers(client, options, result) if result.changed and not options.get("no-trigger") else {}
        state = "published" if result.changed else "unchanged"
        outcomes[state] += 1
        report.append({"item": working["id"], "page": label, "result": state, "version": result.version_number, **({"triggers": triggers} if triggers else {})})
        print(f"knowledge\twiki-publish\t{state}\t{label}\tversion {result.version_number}")
    if options.get("json"):
        print(json.dumps({"mode": "apply" if apply else "dry-run", "review": review, "pages": report, "counts": dict(outcomes)}, indent=2, sort_keys=True))
    else:
        for state, count in sorted(outcomes.items()):
            print(f"knowledge\twiki-publish\tsummary\t{state}\t{count}")
        if not targets:
            print("knowledge\twiki-publish\tnothing to publish")
        if not apply and targets:
            print("knowledge\twiki-publish\tapply\tskipped\tpass --apply to publish")
    if failed:
        raise SystemExit(1)


WIKI_COMMANDS = {
    "wiki-sync": knowledge_wiki_sync,
    "wiki-publish": knowledge_wiki_publish,
}
