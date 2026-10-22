"""Plan and apply the sync of accepted entities and topics into draft wiki page Items (PPY-5629f3, PPY-db2d69).

``plan_sync`` is pure over rows: it decides, for each generated page, whether to create it, update its draft in place,
open a pending revision beside a live page, or leave it alone. ``apply_plan`` performs the plan through the normal save
path. The sync never publishes and never touches a live page: a changed description on a published page becomes a new
draft version of the same lineage (the pattern of ``save_story_version``), which the publish command later stamps and
puts live.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

import yaml

from ..knowledge_snapshot.builder import _aliases, _public_keys
from ..knowledge_snapshot.keys import contains_email, slug
from ..knowledge_snapshot.model import Beat, KnowledgeData
from ..knowledge_snapshot.publish_run import json_object
from ..publishing import ItemFields, item_id_for, published_item_id_for, save_item
from ..story_reporting import save_story_version
from ..wiki_stamp import WIKI_PAGE_ITEM_TYPE
from .pages import KIND_BEAT, KIND_ENTITY, KIND_SUBTOPIC, PageSpec, comparable, entity_page, front_matter_yaml, topic_page

ACCEPTED = "accepted"
PUBLISHABLE_DESCRIPTIONS = ("reviewed", "ai_edited")
CREATE = "create"
UPDATE = "update"
REVISE = "revise"
UNCHANGED = "unchanged"
DEFAULT_MINIMUM_SUBTOPIC_ITEMS = 30
DEFAULT_ITEMS_PER_TOPIC = 20
KEY_FIELDS = {KIND_ENTITY: "entityKey", KIND_BEAT: "topicKey", KIND_SUBTOPIC: "topicKey"}


@dataclass(frozen=True)
class PagePlan:
    action: str
    section: str
    spec: PageSpec
    lineage_id: str
    item_id: str | None
    front_matter_yaml: str
    note: str = ""


@dataclass(frozen=True)
class SyncPlan:
    pages: tuple[PagePlan, ...]
    warnings: tuple[str, ...] = ()

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for page in self.pages:
            counts[f"{page.spec.kind}:{page.action}"] += 1
        return dict(sorted(counts.items()))


@dataclass(frozen=True)
class TopicOptions:
    minimum_subtopic_items: int = DEFAULT_MINIMUM_SUBTOPIC_ITEMS
    items_per_topic: int = DEFAULT_ITEMS_PER_TOPIC
    url_template: str = "/topics/{slug}/"
    sections: tuple[str, ...] = ()


def front_matter_of(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = json_object(row.get("metadata")).get("frontMatterYaml")
    loaded = yaml.safe_load(raw) if isinstance(raw, str) and raw.strip() else {}
    return loaded if isinstance(loaded, dict) else {}


def working_version(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The record being edited: the one marked current, the most recently touched if a muddled lineage has several."""
    pool = [row for row in rows if row.get("versionState") == "current"] or list(rows)
    return dict(max(pool, key=lambda row: (str(row.get("versionCreatedAt") or ""), int(row.get("versionNumber") or 0))))


def wiki_lineages(item_rows: Iterable[Mapping[str, Any]], section: str) -> dict[str, list[dict[str, Any]]]:
    """The wiki page Items of a section, grouped by lineage."""
    lineages: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in item_rows:
        if row.get("type") == WIKI_PAGE_ITEM_TYPE and row.get("section") == section:
            lineages[str(row.get("lineageId") or row["id"])].append(dict(row))
    return lineages


def _lineage_by_key(lineages: Mapping[str, list[dict[str, Any]]], kind: str) -> dict[str, str]:
    field = KEY_FIELDS[kind]
    found: dict[str, str] = {}
    for lineage_id, rows in lineages.items():
        key = front_matter_of(working_version(rows)).get(field)
        if isinstance(key, str):
            found.setdefault(key, lineage_id)
    return found


def _plan_page(
    spec: PageSpec,
    section: str,
    lineages: Mapping[str, list[dict[str, Any]]],
    lineage_for_key: Mapping[str, str],
    published_sources: Mapping[str, str],
) -> PagePlan:
    lineage_id = lineage_for_key.get(spec.key) or item_id_for(section, spec.slug)
    rows = lineages.get(lineage_id)
    text = front_matter_yaml(spec.front_matter)
    if not rows:
        return PagePlan(CREATE, section, spec, lineage_id, None, text)
    working = working_version(rows)
    same = comparable(front_matter_of(working)) == comparable(spec.front_matter) and (working.get("bodyMarkus") or "") == spec.body
    if same:
        return PagePlan(UNCHANGED, section, spec, lineage_id, working["id"], text)
    live_source = published_sources.get(lineage_id)
    if live_source is not None and live_source == working["id"]:
        return PagePlan(REVISE, section, spec, lineage_id, working["id"], text, "pending revision beside the live page")
    return PagePlan(UPDATE, section, spec, lineage_id, working["id"], text)


def _carry(lineage_for_key: Mapping[str, str], lineages: Mapping[str, list[dict[str, Any]]], key: str):
    rows = lineages.get(lineage_for_key.get(key, ""))
    return front_matter_of(working_version(rows)) if rows else None


def entity_specs(data: KnowledgeData, lineages: Mapping[str, list[dict[str, Any]]]) -> list[PageSpec]:
    """A page per accepted entity that has a public name."""
    neighbours = related_keys(data)
    eligible = [node for node in data.nodes if node.status == ACCEPTED and node.name.strip() and not contains_email(node.name)]
    keys = _public_keys(eligible)
    items_by_node: dict[str, set[str]] = defaultdict(set)
    for link in data.links:
        if link.confirmed:
            items_by_node[link.node_lineage_id].add(link.item_key)
    lineage_for_key = _lineage_by_key(lineages, KIND_ENTITY)
    specs = []
    for node in sorted(eligible, key=lambda candidate: keys.get(candidate.lineage_id, "")):
        key = keys.get(node.lineage_id)
        if not key:
            continue
        usable = node.description_state in PUBLISHABLE_DESCRIPTIONS and not contains_email(node.description)
        draft = node.description_state == "draft" and bool((node.description or "").strip())
        spec = (
            entity_page(
                key=key,
                kind=slug(node.kind) or "entity",
                name=" ".join(node.name.split()),
                aliases=_aliases(node),
                description=node.description if usable else None,
                related=sorted(neighbours.get(key, ())),
                beat=_beat_of(items_by_node.get(node.lineage_id, set()), data.beats),
                existing=_carry(lineage_for_key, lineages, key),
            )
        )
        if draft:
            spec = replace(spec, notes=(f"{key}: the description is a draft nobody has accepted; the page uses the factual line until it is reviewed",))
        specs.append(spec)
    return specs


def _beat_of(item_keys: set[str], beats: Sequence[Beat]) -> str | None:
    """The beat that holds most of the entity's items; ties go to the first key."""
    best, best_count = None, 0
    for beat in sorted(beats, key=lambda candidate: candidate.key):
        count = len(item_keys & beat.item_keys)
        if count > best_count:
            best, best_count = beat.key, count
    return best


def related_keys(data: KnowledgeData) -> dict[str, list[str]]:
    """Entity key -> keys of the accepted entities it is related to by a relation an editor confirmed."""
    eligible = [node for node in data.nodes if node.status == ACCEPTED and node.name.strip() and not contains_email(node.name)]
    keys = _public_keys(eligible)
    related: dict[str, set[str]] = defaultdict(set)
    for relation in data.relations:
        first, second = keys.get(relation.subject_lineage_id), keys.get(relation.object_lineage_id)
        if relation.confirmed and first and second and first != second:
            related[first].add(second)
            related[second].add(first)
    return {key: sorted(values) for key, values in related.items()}


def topic_specs(
    data: KnowledgeData,
    lineages: Mapping[str, list[dict[str, Any]]],
    options: TopicOptions,
    *,
    descriptions: Mapping[str, str] | None = None,
    subtopics_of: Mapping[str, Sequence[tuple[Beat, str | None]]] | None = None,
    section_slug: str = "topics",
) -> list[PageSpec]:
    """A page per beat, and a page per accepted subtopic of a beat that has enough published items.

    ``subtopics_of`` maps a beat key to its accepted children (with their descriptions)."""
    published = {item.key for item in data.items}
    lineage_for_key = _lineage_by_key(lineages, KIND_BEAT)
    lineage_for_key.update(_lineage_by_key(lineages, KIND_SUBTOPIC))
    specs: list[PageSpec] = []
    for beat in sorted(data.beats, key=lambda candidate: candidate.key):
        count = len(beat.item_keys & published)
        children = [(child, text) for child, text in (subtopics_of or {}).get(beat.key, ()) if child.item_keys & published] if count >= options.minimum_subtopic_items else []
        child_pages = [(child.name, f"{beat.key}-{child.key}", options.url_template.format(slug=f"{beat.key}-{child.key}")) for child, _text in children]
        specs.append(
            topic_page(
                kind=KIND_BEAT, key=beat.key, slug=beat.key, name=beat.name, description=(descriptions or {}).get(beat.key),
                tags=[beat.key, beat.name], count=options.items_per_topic, sections=options.sections, subtopics=child_pages,
                existing=_carry(lineage_for_key, lineages, beat.key),
            )
        )
        for child, text in children:
            child_key = f"{beat.key}-{child.key}"
            specs.append(
                topic_page(
                    kind=KIND_SUBTOPIC, key=child_key, slug=child_key, name=child.name, description=text,
                    tags=[child.key, child.name], count=options.items_per_topic, sections=options.sections, parent=beat.key,
                    existing=_carry(lineage_for_key, lineages, child_key),
                )
            )
    return specs


def plan_sync(
    specs: Sequence[PageSpec],
    section_of: Mapping[str, str],
    item_rows: Iterable[Mapping[str, Any]],
    published_sources: Mapping[str, str],
) -> SyncPlan:
    """``section_of`` maps a page kind to the section it lives in; ``published_sources`` maps a lineage to the id of the
    Item row its live PublishedItem was made from."""
    rows = list(item_rows)
    pages: list[PagePlan] = []
    warnings: list[str] = [note for spec in specs for note in spec.notes]
    seen: dict[str, set[str]] = defaultdict(set)
    for section in sorted(set(section_of.values())):
        lineages = wiki_lineages(rows, section)
        for spec in specs:
            if section_of[spec.kind] != section:
                continue
            lineage_for_key = _lineage_by_key(lineages, spec.kind)
            plan = _plan_page(spec, section, lineages, lineage_for_key, published_sources)
            pages.append(plan)
            seen[section].add(plan.lineage_id)
        wanted_fields = {KEY_FIELDS[kind] for kind, name in section_of.items() if name == section}
        for lineage_id, lineage_rows in sorted(lineages.items()):
            front = front_matter_of(working_version(lineage_rows))
            if lineage_id not in seen[section] and any(field in front for field in wanted_fields):
                warnings.append(f"{section}/{working_version(lineage_rows).get('slug')}: no longer generated; left as it is (unpublish by hand if it should go)")
    return SyncPlan(tuple(pages), tuple(warnings))


def apply_plan(client: Any, plan: SyncPlan, *, actor: str, now: str | None = None) -> dict[str, int]:
    """Write the plan. Creates and updates save drafts; a revision is a new draft version beside the live page.
    Nothing is published."""
    written: dict[str, int] = defaultdict(int)
    for page in plan.pages:
        if page.action == UNCHANGED:
            continue
        spec = page.spec
        if page.action == REVISE:
            save_story_version(
                client, page.lineage_id, front_matter_yaml=page.front_matter_yaml, body_markus=spec.body, actor=actor,
                change_reason=f"wiki-sync: {spec.kind} text changed", now=now,
            )
        else:
            existing = client.get_record("Item", page.item_id) if page.item_id else None
            save_item(
                client,
                ItemFields(
                    type=WIKI_PAGE_ITEM_TYPE, slug=(existing or {}).get("slug") or spec.slug, section=page.section,
                    front_matter_yaml=page.front_matter_yaml, body_markus=spec.body,
                    aliases=list((existing or {}).get("aliases") or []), id=page.item_id or page.lineage_id,
                ),
                actor=actor, now=now,
            )
        written[page.action] += 1
    return dict(written)


def live_sources(client: Any, lineage_ids: Iterable[str]) -> dict[str, str]:
    """Lineage -> id of the Item row its live page was made from, for the lineages that are live."""
    sources: dict[str, str] = {}
    for lineage_id in lineage_ids:
        row = client.get_record("PublishedItem", published_item_id_for(lineage_id))
        if row is not None and row.get("sourceItemId"):
            sources[lineage_id] = row["sourceItemId"]
    return sources

