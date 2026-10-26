"""Read the plain records of ``model.py`` from authoring-client rows (or from an offline records file)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from ..categories_steering import semantic_state_key
from ..projection.model import ItemSummary
from ..projection.source import is_projectable, summary_from_row
from .cluster_records import cluster_from_proposal
from .actors import Actor, decode_review
from .keys import normalize_name, slug
from .model import (
    DESCRIPTION_AI_EDITED,
    DESCRIPTION_DRAFT,
    DESCRIPTION_NONE,
    DESCRIPTION_REVIEWED,
    LINK_EXTRACTOR,
    LINK_MONITOR,
    Beat,
    Cluster,
    EntityNode,
    FrontMatterEntity,
    ItemLink,
    KnowledgeData,
    NodeRelation,
    PublishedItem,
)
from .monitor_import import is_record_mention
from .publish_run import NODE_KIND, is_item_mention, json_object

CURRENT = "current"

UrlResolver = Callable[[ItemSummary], str | None]


def front_matter_entities(front_matter: Mapping[str, Any]) -> tuple[FrontMatterEntity, ...]:
    """Entities of a front matter: ``[{kind, name}]`` or ``{kind: [name, ...]}``; anything else is ignored."""
    value = front_matter.get("entities")
    pairs: list[tuple[Any, Any]] = []
    if isinstance(value, list):
        pairs = [(entry.get("kind"), entry.get("name")) for entry in value if isinstance(entry, dict)]
    elif isinstance(value, dict):
        for kind, names in value.items():
            for name in names if isinstance(names, list) else [names]:
                pairs.append((kind, name.get("name") if isinstance(name, dict) else name))
    return tuple(
        FrontMatterEntity(kind=str(kind).strip(), name=str(name).strip())
        for kind, name in pairs
        if isinstance(kind, str) and isinstance(name, str) and kind.strip() and name.strip()
    )


def front_matter_tags(front_matter: Mapping[str, Any]) -> tuple[str, ...]:
    value = front_matter.get("tags")
    values = value if isinstance(value, list) else [value]
    return tuple(str(tag).strip() for tag in values if isinstance(tag, str) and tag.strip())


def published_items(rows: Iterable[Mapping[str, Any]], url_for: UrlResolver) -> list[PublishedItem]:
    items: list[PublishedItem] = []
    for row in rows:
        if not is_projectable(dict(row)):
            continue
        summary = summary_from_row(dict(row))
        items.append(
            PublishedItem(
                key=str(row.get("itemLineageId") or summary.item_id),
                item_id=str(row.get("sourceItemId") or summary.item_id),
                title=summary.page_title or summary.title,
                url=url_for(summary),
                published_at=summary.published_at,
                tags=front_matter_tags(summary.front_matter),
                entities=front_matter_entities(summary.front_matter),
            )
        )
    return sorted(items, key=lambda item: item.key)


def description_state(row: Mapping[str, Any]) -> tuple[str, Actor | None]:
    """``reviewed`` when a person edited the description, ``ai_edited`` when an AI agent did, else ``draft`` or ``none``."""
    if not str(row.get("description") or "").strip():
        return DESCRIPTION_NONE, None
    editor = decode_review(row.get("changeReason")).description_edited_by
    if editor is None:
        return DESCRIPTION_DRAFT, None
    return (DESCRIPTION_REVIEWED if editor.is_human else DESCRIPTION_AI_EDITED), editor


def entity_node(row: Mapping[str, Any]) -> EntityNode:
    state, editor = description_state(row)
    return EntityNode(
        lineage_id=str(row.get("lineageId") or row["id"]),
        node_key=str(row.get("nodeKey") or ""),
        kind=str(row.get("nodeKind") or ""),
        name=str(row.get("displayName") or ""),
        status=str(row.get("status") or ""),
        aliases=tuple(str(alias) for alias in row.get("aliases") or ()),
        description=row.get("description"),
        description_state=state,
        accepted_by=decode_review(row.get("changeReason")).accepted_by,
        description_edited_by=editor,
    )


def current_nodes(rows: Iterable[Mapping[str, Any]]) -> list[dict]:
    return [dict(row) for row in rows if row.get("versionState", CURRENT) == CURRENT]


def relations_of_nodes(client: Any, node_rows: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Every current relation that touches one of the nodes, through the state indexes (no scan of the table)."""
    seen: dict[str, dict] = {}
    for node in node_rows:
        state = semantic_state_key(NODE_KIND, str(node.get("lineageId") or node["id"]))
        for lookup in (client.list_semantic_relations_by_object_state, client.list_semantic_relations_by_subject_state):
            for row in lookup(state):
                seen[row["id"]] = row
    return sorted(seen.values(), key=lambda row: row["id"])


def links_and_relations(relation_rows: Iterable[Mapping[str, Any]]) -> tuple[list[ItemLink], list[NodeRelation]]:
    links: list[ItemLink] = []
    relations: list[NodeRelation] = []
    for row in relation_rows:
        if row.get("relationState", CURRENT) != CURRENT:
            continue
        metadata = json_object(row.get("metadata"))
        confirmed = metadata.get("confirmed") is True
        if is_item_mention(row):
            links.append(
                ItemLink(
                    item_key=str(row["subjectLineageId"]),
                    node_lineage_id=str(row["objectLineageId"]),
                    confirmed=confirmed,
                    source=str(metadata.get("linkSource") or LINK_EXTRACTOR),
                )
            )
        elif is_record_mention(row):
            links.append(ItemLink(item_key=str(row["subjectLineageId"]), node_lineage_id=str(row["objectLineageId"]), confirmed=confirmed, source=LINK_MONITOR))
        elif row.get("subjectKind") == NODE_KIND and row.get("objectKind") == NODE_KIND:
            relations.append(
                NodeRelation(
                    subject_lineage_id=str(row["subjectLineageId"]),
                    object_lineage_id=str(row["objectLineageId"]),
                    predicate=str(row.get("predicate") or ""),
                    confirmed=confirmed,
                    subtype=_text(metadata.get("subtype")),
                    evidence=_text(metadata.get("evidence")),
                    provenance=_text(metadata.get("provenance")),
                )
            )
    return links, relations


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def category_names(category_rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], str]:
    return {
        (str(row.get("categorySetId") or ""), str(row.get("categoryKey") or "")): str(row["displayName"])
        for row in category_rows
        if row.get("versionState", CURRENT) == CURRENT and row.get("status") == "accepted" and row.get("displayName")
    }


def clusters_of(proposal_rows: Iterable[Mapping[str, Any]], names: Mapping[tuple[str, str], str], items: list[PublishedItem]) -> list[Cluster]:
    """Clusters with member item ids turned into item keys; ids of items that are not published stay as they are."""
    key_by_id = {item.item_id: item.key for item in items}
    clusters: list[Cluster] = []
    for row in proposal_rows:
        cluster = cluster_from_proposal(row, names)
        if cluster is None:
            continue
        clusters.append(
            Cluster(**{**cluster.__dict__, "member_item_keys": tuple(key_by_id.get(member, member) for member in cluster.member_item_keys)})
        )
    return sorted(clusters, key=lambda cluster: cluster.uid)


def beats_from_config(config: Mapping[str, Any], items: list[PublishedItem]) -> list[Beat]:
    """Beats from a ``topics`` mapping (``{key: {label, path}}``, the shape of a site's ``scoring.json``); items belong
    to the beat whose key is one of their front-matter tags."""
    topics = config.get("topics") if isinstance(config.get("topics"), dict) else {}
    beats = []
    for key in sorted(topics):
        entry = topics[key] if isinstance(topics[key], dict) else {}
        members = frozenset(item.key for item in items if any(normalize_name(tag) == normalize_name(key) for tag in item.tags))
        beats.append(Beat(key=str(key), name=str(entry.get("label") or key), href=entry.get("path"), item_keys=members))
    return beats


def beats_from_categories(
    category_rows: Iterable[Mapping[str, Any]],
    category_set_id: str,
    clusters: list[Cluster],
    items: list[PublishedItem],
    href_template: str | None,
    parent_key: str | None = None,
) -> list[Beat]:
    """Beats from the accepted root categories of one category set (the accepted children of ``parent_key`` when it is
    given). An item belongs to a beat when it is a member of the accepted cluster the category was made from, or carries
    the category key or name as a front-matter tag."""
    beats = []
    for row in category_rows:
        if (
            row.get("categorySetId") != category_set_id
            or row.get("versionState", CURRENT) != CURRENT
            or row.get("status") != "accepted"
            or (row.get("parentCategoryKey") or None) != parent_key
        ):
            continue
        key, name = str(row["categoryKey"]), str(row.get("displayName") or row["categoryKey"])
        wanted = {normalize_name(key), normalize_name(name)}
        members = {item.key for item in items if any(normalize_name(tag) in wanted for tag in item.tags)}
        for cluster in clusters:
            if cluster.accepted and cluster.category_key == key:
                members.update(cluster.member_item_keys)
        beats.append(Beat(key=slug(key) or key, name=name, href=href_template.format(key=slug(key) or key) if href_template else None, item_keys=frozenset(members)))
    return sorted(beats, key=lambda beat: beat.key)


def knowledge_data_from_mapping(raw: Mapping[str, Any]) -> KnowledgeData:
    """Records of an offline records file (``snapshot --records FILE``): published ``items``, SemanticNode ``nodes``,
    SemanticRelation ``relations``, SteeringProposal ``proposals``, Category ``categories`` and plain ``beats``."""
    items = [
        PublishedItem(
            key=entry["key"],
            item_id=entry.get("itemId") or entry["key"],
            title=entry.get("title"),
            url=entry.get("url"),
            published_at=entry.get("publishedAt"),
            tags=tuple(entry.get("tags") or ()),
            entities=tuple(FrontMatterEntity(kind=e["kind"], name=e["name"]) for e in entry.get("entities") or ()),
        )
        for entry in raw.get("items") or ()
    ]
    links, relations = links_and_relations(raw.get("relations") or ())
    return KnowledgeData(
        items=tuple(items),
        nodes=tuple(entity_node(row) for row in current_nodes(raw.get("nodes") or ())),
        links=tuple(links),
        relations=tuple(relations),
        clusters=tuple(clusters_of(raw.get("proposals") or (), category_names(raw.get("categories") or ()), items)),
        beats=tuple(
            Beat(key=entry["key"], name=entry["name"], href=entry.get("href"), item_keys=frozenset(entry.get("itemKeys") or ()))
            for entry in raw.get("beats") or ()
        ),
    )


def load_records_file(path: str) -> KnowledgeData:
    with open(path, encoding="utf-8") as handle:
        return knowledge_data_from_mapping(json.load(handle))
