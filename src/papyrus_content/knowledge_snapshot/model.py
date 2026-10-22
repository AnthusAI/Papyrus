"""Plain records the snapshot builder reads. No storage, no clock, no network."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .actors import Actor

DESCRIPTION_REVIEWED = "reviewed"
DESCRIPTION_AI_EDITED = "ai_edited"
DESCRIPTION_DRAFT = "draft"
DESCRIPTION_NONE = "none"
LINK_FRONT_MATTER = "front_matter"
LINK_EXTRACTOR = "extractor"
UNACCEPTED_HIDE = "hide"
UNACCEPTED_UNNAMED = "unnamed"


@dataclass(frozen=True)
class FrontMatterEntity:
    kind: str
    name: str


@dataclass(frozen=True)
class PublishedItem:
    """A published item. ``key`` is its lineage id, which links use; ``item_id`` is the id of the item row."""

    key: str
    item_id: str
    title: str | None
    url: str | None
    published_at: str | None
    tags: tuple[str, ...] = ()
    entities: tuple[FrontMatterEntity, ...] = ()


@dataclass(frozen=True)
class EntityNode:
    lineage_id: str
    node_key: str
    kind: str
    name: str
    status: str
    aliases: tuple[str, ...] = ()
    description: str | None = None
    description_state: str = DESCRIPTION_NONE
    accepted_by: Actor | None = None
    description_edited_by: Actor | None = None


@dataclass(frozen=True)
class ItemLink:
    """An item that mentions a node. Only a ``confirmed`` link is counted."""

    item_key: str
    node_lineage_id: str
    confirmed: bool
    source: str = LINK_FRONT_MATTER


@dataclass(frozen=True)
class NodeRelation:
    subject_lineage_id: str
    object_lineage_id: str
    predicate: str
    confirmed: bool


@dataclass(frozen=True)
class Cluster:
    uid: str
    accepted: bool
    name: str | None
    event: str | None
    top_terms: tuple[str, ...]
    weekly_series: dict[str, int]
    earliest_published_at: str | None
    member_item_keys: tuple[str, ...]
    member_count: int
    run_id: str | None
    run_as_of: str | None = None
    category_key: str | None = None
    accepted_by: Actor | None = None


@dataclass(frozen=True)
class Beat:
    key: str
    name: str
    href: str | None
    item_keys: frozenset[str]


@dataclass(frozen=True)
class KnowledgeData:
    items: tuple[PublishedItem, ...] = ()
    nodes: tuple[EntityNode, ...] = ()
    links: tuple[ItemLink, ...] = ()
    relations: tuple[NodeRelation, ...] = ()
    clusters: tuple[Cluster, ...] = ()
    beats: tuple[Beat, ...] = ()


@dataclass(frozen=True)
class SnapshotOptions:
    as_of: date
    entity_href_template: str | None = None
    cluster_href_template: str | None = None
    unaccepted_clusters: str = UNACCEPTED_HIDE
    maker_kind: str = "maker"
    concept_kinds: tuple[str, ...] | None = None
    neighbour_limit: int = 12
    related_limit: int = 12
