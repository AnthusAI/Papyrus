"""Build the public knowledge files from plain records.

``build_files`` is a pure function: the same records and options give the same dictionaries, with no clock and no
timestamps in them. It is the one place that decides what is public. Only accepted entities, only published and dated
items, only desk-confirmed links and relations come out, and no text of a reference, private note or message is read.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .keys import contains_email, entity_key, is_public_key, kind_label, normalize_name, slug
from .model import (
    DESCRIPTION_REVIEWED,
    UNACCEPTED_UNNAMED,
    Beat,
    Cluster,
    EntityNode,
    KnowledgeData,
    PublishedItem,
    SnapshotOptions,
)
from .trends import (
    SERIES_LONG,
    SERIES_SHORT,
    Change,
    change_of,
    is_new,
    series,
    weekly_counts,
    weeks_of_history,
)
from .weeks import iso_timestamp, parse_day, week_label, week_number

SCHEMA_VERSION = 1
DATA_DIRECTORY = "_data/knowledge"
INDEX_FILE = f"{DATA_DIRECTORY}/index.json"
CLUSTERS_FILE = f"{DATA_DIRECTORY}/clusters.json"
ENTITY_DIRECTORY = f"{DATA_DIRECTORY}/entities"
CO_MENTION = "mentioned_with"
CLUSTER_NEW = "new"
CLUSTER_GROWING = "growing"
CLUSTER_COOLING = "cooling"
CLUSTER_STATE_PERCENT = 20
CLUSTER_MINIMUM_WEEKS = 4
ACCEPTED = "accepted"


def entity_file(key: str) -> str:
    return f"{ENTITY_DIRECTORY}/{key}.json"


@dataclass(frozen=True)
class _Entity:
    node: EntityNode
    key: str
    kind: str
    name: str
    aliases: tuple[str, ...]
    item_keys: frozenset[str]
    history: int
    values8: list[int]
    values26: list[int]
    change: Change
    new: bool
    href: str | None


def _dated_items(items: tuple[PublishedItem, ...], as_of_week: int) -> dict[str, tuple[int, PublishedItem]]:
    dated: dict[str, tuple[int, PublishedItem]] = {}
    for item in items:
        if not item.published_at:
            continue
        week = week_number(parse_day(item.published_at))
        if week <= as_of_week:
            dated[item.key] = (week, item)
    return dated


def _public_keys(nodes: list[EntityNode]) -> dict[str, str]:
    """A public key per node lineage: the stored key when it has the public shape, else the slug of kind and name."""
    taken: set[str] = set()
    keys: dict[str, str] = {}
    for node in sorted(nodes, key=lambda candidate: candidate.lineage_id):
        base = node.node_key if is_public_key(node.node_key) else entity_key(node.kind or "entity", node.name)
        if not base:
            continue
        key, suffix = base, 1
        while key in taken:
            suffix += 1
            key = f"{base}-{suffix}"
        taken.add(key)
        keys[node.lineage_id] = key
    return keys


def _aliases(node: EntityNode) -> tuple[str, ...]:
    seen = {normalize_name(node.name)}
    kept: list[str] = []
    for alias in node.aliases:
        normal = normalize_name(alias)
        if not normal or normal in seen or contains_email(alias):
            continue
        seen.add(normal)
        kept.append(" ".join(alias.split()))
    return tuple(sorted(kept, key=lambda value: (normalize_name(value), value)))


def _entities(data: KnowledgeData, options: SnapshotOptions, dated: dict[str, tuple[int, PublishedItem]], as_of_week: int):
    eligible = [
        node
        for node in data.nodes
        if node.status == ACCEPTED and node.name.strip() and not contains_email(node.name)
    ]
    keys = _public_keys(eligible)
    items_by_node: dict[str, set[str]] = defaultdict(set)
    for link in data.links:
        if link.confirmed and link.item_key in dated:
            items_by_node[link.node_lineage_id].add(link.item_key)
    entities: list[_Entity] = []
    for node in eligible:
        key = keys.get(node.lineage_id)
        item_keys = items_by_node.get(node.lineage_id)
        if not key or not item_keys:
            continue
        counts = weekly_counts(dated[item][0] for item in item_keys)
        values8, values26 = series(counts, as_of_week, SERIES_SHORT), series(counts, as_of_week, SERIES_LONG)
        history = weeks_of_history(min(counts), as_of_week)
        entities.append(
            _Entity(
                node=node,
                key=key,
                kind=slug(node.kind) or "entity",
                name=" ".join(node.name.split()),
                aliases=_aliases(node),
                item_keys=frozenset(item_keys),
                history=history,
                values8=values8,
                values26=values26,
                change=change_of(values8),
                new=is_new(history),
                href=options.entity_href_template.format(key=key) if options.entity_href_template else None,
            )
        )
    return sorted(entities, key=lambda entity: (-len(entity.item_keys), entity.key))


def _trending_order(entities: list[_Entity]) -> list[str]:
    candidates = [entity for entity in entities if not entity.new and entity.change.last4 > 0]

    def order(entity: _Entity):
        change = entity.change
        if change.percent is not None:
            return (0, -change.percent, entity.key)
        return (1, -(change.last4 - change.prior4), entity.key)

    return [entity.key for entity in sorted(candidates, key=order)]


def _neighbours(entities: list[_Entity], data: KnowledgeData, options: SnapshotOptions) -> dict[str, list[dict]]:
    by_lineage = {entity.node.lineage_id: entity for entity in entities}
    entities_by_item: dict[str, list[_Entity]] = defaultdict(list)
    for entity in entities:
        for item in entity.item_keys:
            entities_by_item[item].append(entity)
    shared: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for members in entities_by_item.values():
        for first in members:
            for second in members:
                if first.key != second.key:
                    shared[first.key][second.key] += 1

    explicit: dict[str, dict[tuple[str, str], dict]] = defaultdict(dict)
    for relation in data.relations:
        subject, target = by_lineage.get(relation.subject_lineage_id), by_lineage.get(relation.object_lineage_id)
        if not relation.confirmed or subject is None or target is None or subject.key == target.key:
            continue
        for owner, other in ((subject, target), (target, subject)):
            explicit[owner.key][(relation.predicate, other.key)] = _neighbour(
                relation.predicate, other, shared[owner.key].get(other.key, 0)
            )

    by_key = {entity.key: entity for entity in entities}
    result: dict[str, list[dict]] = {}
    for entity in entities:
        mentioned = [_neighbour(CO_MENTION, by_key[other], count) for other, count in shared.get(entity.key, {}).items()]
        mentioned.sort(key=lambda row: (-row["weight"], row["key"]))
        rows = list(explicit.get(entity.key, {}).values()) + mentioned[: options.neighbour_limit]
        rows.sort(key=lambda row: (-row["weight"], row["relation"], row["key"]))
        result[entity.key] = rows
    return result


def _neighbour(relation: str, other: _Entity, weight: int) -> dict:
    return {"relation": relation, "key": other.key, "name": other.name, "kind": other.kind, "weight": weight}


def _related_items(entity: _Entity, dated: dict[str, tuple[int, PublishedItem]], limit: int) -> list[dict]:
    rows = []
    for item_key in entity.item_keys:
        _week, item = dated[item_key]
        if not item.url or not item.title or contains_email(item.title):
            continue
        rows.append(
            {
                "title": " ".join(item.title.split()),
                "url": item.url,
                "publishedAt": iso_timestamp(item.published_at),
                "reason": entity.key,
            }
        )
    rows.sort(key=lambda row: (row["publishedAt"], row["url"]), reverse=True)
    return rows[:limit]


def _description(node: EntityNode) -> dict:
    return {"state": node.description_state, "reviewedOn": node.reviewed_on if node.description_state == DESCRIPTION_REVIEWED else None}


def _index_entity(entity: _Entity) -> dict:
    return {
        "key": entity.key,
        "kind": entity.kind,
        "name": entity.name,
        "href": entity.href,
        "itemCount": len(entity.item_keys),
        "weeksOfHistory": entity.history,
        "series8": entity.values8,
        "change": entity.change.to_dict(),
        "isNew": entity.new,
    }


def _entity_file(entity: _Entity, neighbours: list[dict], related: list[dict]) -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "key": entity.key,
        "kind": entity.kind,
        "name": entity.name,
        "aliases": list(entity.aliases),
        "description": _description(entity.node),
        "href": entity.href,
        "itemCount": len(entity.item_keys),
        "weeksOfHistory": entity.history,
        "series8": entity.values8,
        "series26": entity.values26,
        "change": entity.change.to_dict(),
        "neighbours": neighbours,
        "relatedItems": related,
    }


def _concept_of_the_week(entities: list[_Entity], data: KnowledgeData, options: SnapshotOptions) -> dict | None:
    makers_by_item: dict[str, set[str]] = defaultdict(set)
    for entity in entities:
        if entity.kind == slug(options.maker_kind):
            for item in entity.item_keys:
                makers_by_item[item].add(entity.key)
    candidates = [
        entity
        for entity in entities
        if entity.node.description_state == DESCRIPTION_REVIEWED
        and (entity.node.description or "").strip()
        and not contains_email(entity.node.description)
        and entity.change.last4 > 0
    ]
    if not candidates:
        return None
    chosen = sorted(candidates, key=lambda entity: (-entity.change.last4, entity.key))[0]
    makers = {maker for item in chosen.item_keys for maker in makers_by_item.get(item, ())} - {chosen.key}
    return {
        "key": chosen.key,
        "name": chosen.name,
        "href": chosen.href,
        "lede": " ".join((chosen.node.description or "").split()),
        "itemCount": len(chosen.item_keys),
        "makerCount": len(makers),
    }


def _beat_row(beat: Beat, dated: dict[str, tuple[int, PublishedItem]], as_of_week: int) -> dict:
    members = [item for item in beat.item_keys if item in dated]
    return {
        "key": beat.key,
        "name": beat.name,
        "href": beat.href,
        "itemCount": len(members),
        "series8": series(weekly_counts(dated[item][0] for item in members), as_of_week, SERIES_SHORT),
    }


def _cluster_row(cluster: Cluster, published: set[str], options: SnapshotOptions, as_of_week: int, named: bool) -> dict | None:
    members = [key for key in cluster.member_item_keys if key in published]
    count = len(members) if cluster.member_item_keys else cluster.member_count
    if count <= 0:
        return None
    labels = {week_label(as_of_week - offset): offset for offset in range(SERIES_SHORT)}
    values = [0] * SERIES_SHORT
    for label, amount in cluster.weekly_series.items():
        if label in labels:
            values[SERIES_SHORT - 1 - labels[label]] = int(amount)
    first_week = _first_week(cluster, as_of_week)
    weeks_of_data = weeks_of_history(first_week, as_of_week) if first_week is not None else 0
    change = change_of(values)
    return {
        "uid": cluster.uid,
        "name": cluster.name if named else None,
        "state": _cluster_state(cluster, change, weeks_of_data, first_week, as_of_week),
        "itemCount": count,
        "topTerms": list(cluster.top_terms),
        "series8": values,
        "weeksOfData": weeks_of_data,
        "href": options.cluster_href_template.format(uid=cluster.uid, slug=slug(cluster.name or cluster.uid))
        if options.cluster_href_template and named
        else None,
    }


def _first_week(cluster: Cluster, as_of_week: int) -> int | None:
    if cluster.first_seen:
        return week_number(parse_day(cluster.first_seen))
    labelled = [as_of_week - offset for offset in range(SERIES_LONG) if cluster.weekly_series.get(week_label(as_of_week - offset), 0) > 0]
    return min(labelled) if labelled else None


def _cluster_state(cluster: Cluster, change: Change, weeks_of_data: int, first_week: int | None, as_of_week: int) -> str | None:
    if cluster.event == "new" and first_week is not None and as_of_week - first_week < CLUSTER_MINIMUM_WEEKS:
        return CLUSTER_NEW
    if weeks_of_data < CLUSTER_MINIMUM_WEEKS or change.percent is None:
        return None
    if change.percent >= CLUSTER_STATE_PERCENT:
        return CLUSTER_GROWING
    if change.percent <= -CLUSTER_STATE_PERCENT:
        return CLUSTER_COOLING
    return None


def _clusters_file(data: KnowledgeData, options: SnapshotOptions, published: set[str], as_of_week: int) -> dict:
    rows: list[tuple[int, dict]] = []
    runs = sorted((cluster.run_as_of or "", cluster.run_id) for cluster in data.clusters if cluster.run_id)
    latest = runs[-1][1] if runs else None
    for cluster in data.clusters:
        if cluster.run_id != latest:
            continue
        named = cluster.accepted and bool(cluster.name)
        if not named and options.unaccepted_clusters != UNACCEPTED_UNNAMED:
            continue
        row = _cluster_row(cluster, published, options, as_of_week, named)
        if row is None:
            continue
        rows.append((sum(row["series8"][-4:]), row))
    rows.sort(key=lambda pair: (-pair[0], -pair[1]["itemCount"], pair[1]["uid"]))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "asOf": options.as_of.isoformat(),
        "runId": latest if rows else None,
        "unacceptedClusters": options.unaccepted_clusters,
        "clusters": [row for _count, row in rows],
    }


def build_files(data: KnowledgeData, options: SnapshotOptions) -> dict[str, dict]:
    """Every file of ``_data/knowledge/`` as ``{site key: payload}``."""
    as_of_week = week_number(options.as_of)
    dated = _dated_items(data.items, as_of_week)
    entities = _entities(data, options, dated, as_of_week)
    neighbours = _neighbours(entities, data, options)
    kinds: dict[str, int] = defaultdict(int)
    for entity in entities:
        kinds[entity.kind] += 1
    beats = sorted(
        (_beat_row(beat, dated, as_of_week) for beat in data.beats), key=lambda row: (-row["itemCount"], row["key"])
    )
    files: dict[str, dict] = {
        INDEX_FILE: {
            "schemaVersion": SCHEMA_VERSION,
            "asOf": options.as_of.isoformat(),
            "entityCount": len(entities),
            "topicCount": len(beats),
            "kinds": [{"key": kind, "label": kind_label(kind), "count": kinds[kind]} for kind in sorted(kinds)],
            "beats": beats,
            "entities": [_index_entity(entity) for entity in entities],
            "trending": _trending_order(entities),
            "conceptOfTheWeek": _concept_of_the_week(entities, data, options),
        },
        CLUSTERS_FILE: _clusters_file(data, options, set(dated), as_of_week),
    }
    for entity in entities:
        files[entity_file(entity.key)] = _entity_file(
            entity, neighbours[entity.key], _related_items(entity, dated, options.related_limit)
        )
    return files
