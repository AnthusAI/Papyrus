"""Build the public knowledge files from plain records.

``build_files`` is a pure function: the same records and options give the same dictionaries, with no clock and no
timestamps in them. It is the one place that decides what is public. Only accepted entities, only published and dated
items, only confirmed links and relations come out, and no text of a reference, private note or message is read. Who
accepted an entity or a cluster, and who edited a description, is public: ``{"actor": "ai" | "human", "name", "on"}``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .cluster_history import history_file, identity_of, valid_weeks, week_entry
from .monitor_records import provenance_of
from .keys import contains_email, entity_key, is_public_key, kind_label, kind_key, normalize_name, slug
from .model import (
    DESCRIPTION_AI_EDITED,
    DESCRIPTION_REVIEWED,
    UNACCEPTED_UNNAMED,
    Beat,
    Cluster,
    EntityNode,
    KnowledgeData,
    NodeRelation,
    PublishedItem,
    SnapshotOptions,
)
from .trends import (
    SERIES_LONG,
    SERIES_SHORT,
    Change,
    change_of,
    is_new,
    rank_trending,
    series,
    weekly_counts,
    weeks_of_history,
)
from .weeks import iso_timestamp, parse_day, week_label, week_monday, week_number

SCHEMA_VERSION = 1
DATA_DIRECTORY = "_data/knowledge"
INDEX_FILE = f"{DATA_DIRECTORY}/index.json"
CLUSTERS_FILE = f"{DATA_DIRECTORY}/clusters.json"
CLUSTERS_HISTORY_FILE = f"{DATA_DIRECTORY}/clusters-history.json"
ENTITY_DIRECTORY = f"{DATA_DIRECTORY}/entities"
CO_MENTION = "mentioned_with"
CLUSTER_NEW = "new"
CLUSTER_GROWING = "growing"
CLUSTER_COOLING = "cooling"
CLUSTER_STATE_PERCENT = 20
CLUSTER_MINIMUM_WEEKS = 4
ACCEPTED = "accepted"
BEAT_ENTITY_LIMIT = 12
DATA_ONLY_MINIMUM = 2  # an entity that only monitor records mention needs this many of them, or a confirmed relation


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
    record_keys: frozenset[str]
    history: int
    values8: list[int]
    values26: list[int]
    weekly_start: str  # the Monday of weekly[0]
    weekly: list[int]  # every week from the first item to the as-of week, oldest first: the full history
    change: Change
    new: bool
    href: str | None


DATE_BASIS = "publication"  # items count in the week of their publication date (a published story's date, a record's sourcePublishedAt); an undated one is left out, never dated by ingestion


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
    related = {lineage for relation in data.relations if relation.confirmed for lineage in (relation.subject_lineage_id, relation.object_lineage_id)}
    entities: list[_Entity] = []
    for node in eligible:
        key = keys.get(node.lineage_id)
        item_keys = items_by_node.get(node.lineage_id)
        if not key or not item_keys:
            continue
        record_keys = frozenset(item for item in item_keys if dated[item][1].is_record)
        has_page = len(record_keys) < len(item_keys)  # a site item mentions it; an entity only records mention is data, with no page
        if not has_page and len(item_keys) < DATA_ONLY_MINIMUM and node.lineage_id not in related:
            continue
        counts = weekly_counts(dated[item][0] for item in item_keys)
        values8, values26 = series(counts, as_of_week, SERIES_SHORT), series(counts, as_of_week, SERIES_LONG)
        history = weeks_of_history(min(counts), as_of_week)
        weekly = series(counts, as_of_week, history)
        entities.append(
            _Entity(
                node=node,
                key=key,
                kind=kind_key(node.kind) or "entity",
                name=" ".join(node.name.split()),
                aliases=_aliases(node),
                item_keys=frozenset(item_keys),
                record_keys=record_keys,
                history=history,
                values8=values8,
                values26=values26,
                weekly=weekly,
                weekly_start=week_monday(min(counts)).isoformat(),
                change=change_of(values8, history),
                new=is_new(history),
                href=options.entity_href_template.format(key=key, slug=slug(key)) if options.entity_href_template and has_page else None,
            )
        )
    return sorted(entities, key=lambda entity: (-len(entity.item_keys), entity.key))


def _trending_order(entities: list[_Entity]) -> list[str]:
    """Entities that gained mentions beyond what the corpus's own growth explains, most surprising first; broad kinds (licence, task,
    platform) are demoted by weight, so what everything mentions does not lead. New entities are listed through ``isNew``, not here."""
    ranked = rank_trending((entity.key, entity.kind, entity.values8) for entity in entities if not entity.new)
    return [str(row["key"]) for row in ranked]


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
                relation.predicate, other, shared[owner.key].get(other.key, 0), relation
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


def _neighbour(relation: str, other: _Entity, weight: int, source: NodeRelation | None = None) -> dict:
    row = {"relation": relation, "key": other.key, "name": other.name, "kind": other.kind, "weight": weight}
    if source is not None:  # what a relation imported from a source fact says of itself
        row.update({name: value for name, value in (("subtype", source.subtype), ("evidence", source.evidence), ("provenance", source.provenance)) if value})
    return row


def _related_items(entity: _Entity, dated: dict[str, tuple[int, PublishedItem]], limit: int) -> list[dict]:
    rows = []
    for item_key in entity.item_keys - entity.record_keys:
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


def _related_records(entity: _Entity, dated: dict[str, tuple[int, PublishedItem]], limit: int) -> list[dict]:
    """The newest monitor records behind an entity: data with a source address, not pages of the site."""
    rows = []
    for item_key in entity.record_keys:
        _week, record = dated[item_key]
        if not record.url or not record.title or contains_email(record.title):
            continue
        rows.append(
            {
                "title": " ".join(record.title.split()),
                "url": record.url,
                "publishedAt": iso_timestamp(record.published_at),
                "summary": record.summary,
                "source": record.source,
                "provenance": provenance_of(record.source) if record.source else None,
                "reason": entity.key,
            }
        )
    rows.sort(key=lambda row: (row["publishedAt"], row["url"]), reverse=True)
    return [{name: value for name, value in row.items() if value} for row in rows[:limit]]


EDITED_STATES = (DESCRIPTION_REVIEWED, DESCRIPTION_AI_EDITED)


def _actor(actor) -> dict | None:
    return actor.to_dict() if actor is not None else None


def _description(node: EntityNode) -> dict:
    edited = node.description_state in EDITED_STATES
    return {"state": node.description_state, "editedBy": _actor(node.description_edited_by) if edited else None}


def _index_entity(entity: _Entity) -> dict:
    row = {
        "key": entity.key,
        "kind": entity.kind,
        "name": entity.name,
        "aliases": list(entity.aliases),
        "href": entity.href,
        "acceptedBy": _actor(entity.node.accepted_by),
        "itemCount": len(entity.item_keys),
        "weeksOfHistory": entity.history,
        "series8": entity.values8,
        "series26": entity.values26,
        "dateBasis": DATE_BASIS,
        "change": entity.change.to_dict(),
        "isNew": entity.new,
    }
    if entity.weekly:  # additive: the full weekly history (series8 and series26 stay, as windows of it), from the entity's first week
        row["seriesWeekly"] = entity.weekly
        row["seriesWeeklyStart"] = entity.weekly_start
    if entity.record_keys:
        row["recordCount"] = len(entity.record_keys)
    return row


def _entity_file(entity: _Entity, neighbours: list[dict], related: list[dict], records: list[dict]) -> dict:
    file = {
        "schemaVersion": SCHEMA_VERSION,
        "key": entity.key,
        "kind": entity.kind,
        "name": entity.name,
        "aliases": list(entity.aliases),
        "acceptedBy": _actor(entity.node.accepted_by),
        "description": _description(entity.node),
        "href": entity.href,
        "itemCount": len(entity.item_keys),
        "weeksOfHistory": entity.history,
        "series8": entity.values8,
        "series26": entity.values26,
        "dateBasis": DATE_BASIS,
        "change": entity.change.to_dict(),
        "neighbours": neighbours,
        "relatedItems": related,
    }
    if entity.record_keys:  # present only for an entity monitor records count in
        file["recordCount"] = len(entity.record_keys)
        file["relatedRecords"] = records
    return file


def _concept_of_the_week(entities: list[_Entity], data: KnowledgeData, options: SnapshotOptions) -> dict | None:
    makers_by_item: dict[str, set[str]] = defaultdict(set)
    for entity in entities:
        if entity.kind == kind_key(options.maker_kind):
            for item in entity.item_keys:
                makers_by_item[item].add(entity.key)
    allowed = {kind_key(kind) for kind in options.concept_kinds} if options.concept_kinds else None
    candidates = [
        entity
        for entity in entities
        if (allowed is None or entity.kind in allowed)
        and entity.node.description_state in EDITED_STATES
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
        "editedBy": _actor(chosen.node.description_edited_by),
        "itemCount": len(chosen.item_keys),
        "makerCount": len(makers),
    }


def _beat_row(beat: Beat, dated: dict[str, tuple[int, PublishedItem]], as_of_week: int, entities: list[_Entity]) -> dict:
    members = [item for item in beat.item_keys if item in dated]
    shared = ((len(entity.item_keys.intersection(members)), entity.key) for entity in entities)
    top = sorted((pair for pair in shared if pair[0] > 0), key=lambda pair: (-pair[0], pair[1]))
    return {
        "key": beat.key,
        "name": beat.name,
        "href": beat.href,
        "itemCount": len(members),
        "series8": series(weekly_counts(dated[item][0] for item in members), as_of_week, SERIES_SHORT),
        "topEntities": [key for _count, key in top[:BEAT_ENTITY_LIMIT]],
    }


def _cluster_row(
    cluster: Cluster, published: set[str], options: SnapshotOptions, as_of_week: int, named: bool, beat_members: dict[str, set[str]], record_keys: set[str]
) -> dict | None:
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
    row = {
        "uid": cluster.uid,
        "beats": sorted(key for key, beat_items in beat_members.items() if beat_items.intersection(members)),
        "name": cluster.name if named else None,
        "acceptedBy": _actor(cluster.accepted_by) if named else None,
        "state": _cluster_state(cluster, change, weeks_of_data, first_week, as_of_week),
        "itemCount": count,
        "topTerms": list(cluster.top_terms),
        "series8": values,
        "weeksOfData": weeks_of_data,
        "href": options.cluster_href_template.format(uid=cluster.uid, slug=slug(cluster.name or cluster.uid))
        if options.cluster_href_template and named
        else None,
    }
    records = sum(1 for key in members if key in record_keys)
    if records:
        row["recordCount"] = records
    return row


def _first_week(cluster: Cluster, as_of_week: int) -> int | None:
    """The week of the earliest published member item (not the date of the run); the first week with a count if the run
    has no such date."""
    if cluster.earliest_published_at:
        return week_number(parse_day(cluster.earliest_published_at))
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


def _clusters_file(
    data: KnowledgeData, options: SnapshotOptions, published: set[str], as_of_week: int, beat_members: dict[str, set[str]], record_keys: set[str]
) -> dict:
    rows: list[tuple[int, dict]] = []
    runs = sorted((cluster.run_as_of or "", cluster.run_id) for cluster in data.clusters if cluster.run_id)
    latest = runs[-1][1] if runs else None
    for cluster in data.clusters:
        if cluster.run_id != latest:
            continue
        named = cluster.accepted and bool(cluster.name)
        if not named and options.unaccepted_clusters != UNACCEPTED_UNNAMED:
            continue
        row = _cluster_row(cluster, published, options, as_of_week, named, beat_members, record_keys)
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


def _clusters_history_file(data: KnowledgeData, options: SnapshotOptions, clusters_file: dict, previous: dict | None) -> dict:
    """``clusters-history.json``: the weeks of ``previous`` carried forward and this week's entry from the latest run, which is the
    same set of clusters ``clusters.json`` lists. A run dated in an earlier week is not filed under this one."""
    weeks = valid_weeks(previous, SCHEMA_VERSION) or []
    runs = sorted((cluster.run_as_of or "", cluster.run_id) for cluster in data.clusters if cluster.run_id)
    entry = None
    if runs:
        run_as_of, run_id = runs[-1]
        if not run_as_of or week_number(parse_day(run_as_of)) == week_number(options.as_of):
            by_uid = {cluster.uid: cluster for cluster in data.clusters if cluster.run_id == run_id}
            rows = [
                {"uid": row["uid"], "label": row["name"], "itemCount": row["itemCount"], "identity": identity_of(by_uid[row["uid"]])}
                for row in clusters_file["clusters"]
            ]
            entry = week_entry(options.as_of, run_id, rows)
    return history_file(SCHEMA_VERSION, options.as_of, weeks, entry)


def build_files(data: KnowledgeData, options: SnapshotOptions, previous_history: dict | None = None) -> dict[str, dict]:
    """Every file of ``_data/knowledge/`` as ``{site key: payload}``.

    ``previous_history`` is the stored ``clusters-history.json`` (or weeks rebuilt from the weekly archive); its weeks are carried
    into the new file, which adds this week."""
    as_of_week = week_number(options.as_of)
    dated = _dated_items(data.items, as_of_week)
    entities = _entities(data, options, dated, as_of_week)
    neighbours = _neighbours(entities, data, options)
    kinds: dict[str, int] = defaultdict(int)
    for entity in entities:
        kinds[entity.kind] += 1
    beat_members = {beat.key: set(beat.item_keys).intersection(dated) for beat in data.beats}
    beats = sorted(
        (_beat_row(beat, dated, as_of_week, entities) for beat in data.beats), key=lambda row: (-row["itemCount"], row["key"])
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
        CLUSTERS_FILE: _clusters_file(data, options, set(dated), as_of_week, beat_members, {key for key, (_week, item) in dated.items() if item.is_record}),
    }
    files[CLUSTERS_HISTORY_FILE] = _clusters_history_file(data, options, files[CLUSTERS_FILE], previous_history)
    for entity in entities:
        files[entity_file(entity.key)] = _entity_file(
            entity, neighbours[entity.key], _related_items(entity, dated, options.related_limit), _related_records(entity, dated, options.related_limit)
        )
    return files
