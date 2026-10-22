"""The input of ``papyrus knowledge publish-run``: the JSON files Biblicus writes on the workstation.

Each file is passed by name (``--identity``, ``--trends``, ``--entities``); none is found by walking a directory. The
pydantic models below hold only what Papyrus reads; every other field is ignored.

``--identity FILE``
    ``<corpus>/analysis/topic-identity/<run_id>/output.json`` of ``biblicus analyze topic-identity``
    (``analyze-topic-identity.response.schema.json``): ``run_id``, ``generated_at``, ``series_iso_weeks`` and
    ``clusters[{uid, topic_id, event, predecessor_uids, label, top_terms, member_item_count, member_item_ids,
    first_seen, earliest_published_at, weekly_series}]``.
``--trends FILE``
    ``<corpus>/analysis/topic-governance/<snapshot_id>/output.json`` of ``biblicus analyze topic-trends --bin weekly``
    (``analyze-topic-trends.response.schema.json``); only ``snapshot_id`` and ``weekly_bins`` are read:
    ``{as_of, iso_weeks, discovered_topics, canonical_topics}`` where a series is ``{topic_id, topic_uid, counts}``.
    A cluster takes the series whose ``topic_uid`` is its ``uid``, else whose ``topic_id`` is its ``topic_id``. Without
    this file a cluster keeps the eight weekly counts of the identity file.
``--entities FILE``
    The output of ``biblicus extract typed-entities``: ``items[{item_id, entities[{id, kind, text, state, entity_key,
    span, score}], relations[{id, type, subject, object, state, span, score}]}]``. ``subject`` and ``object`` are ids
    of entities of the same item.

Item ids are the ids of Papyrus items (the corpus export writes them to the front matter).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .weeks import parse_day


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore")


class IdentityCluster(_Input):
    uid: str = Field(min_length=1)
    topic_id: int | None = None
    event: str = "continued"
    predecessor_uids: list[str] = Field(default_factory=list)
    label: str | None = None
    top_terms: list[str] = Field(default_factory=list)
    member_item_count: int = Field(default=0, ge=0)
    member_item_ids: list[str] = Field(default_factory=list)
    first_seen: str | None = None
    earliest_published_at: str | None = None
    weekly_series: list[int] | None = None


class IdentityFile(_Input):
    run_id: str = Field(min_length=1)
    generated_at: str | None = None
    trends_snapshot_id: str | None = None
    series_iso_weeks: list[str] | None = None
    clusters: list[IdentityCluster] = Field(default_factory=list)


class TrendSeries(_Input):
    topic_id: int | None = None
    topic_uid: str | None = None
    counts: list[int] = Field(default_factory=list)


class WeeklyBins(_Input):
    as_of: str | None = None
    iso_weeks: list[str] = Field(default_factory=list)
    discovered_topics: list[TrendSeries] = Field(default_factory=list)
    canonical_topics: list[TrendSeries] = Field(default_factory=list)


class TrendsFile(_Input):
    snapshot_id: str | None = None
    weekly_bins: WeeklyBins | None = None


class Span(_Input):
    start: int | None = None
    end: int | None = None


class TypedMention(_Input):
    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    text: str = Field(min_length=1)
    state: Literal["resolved", "proposed"] = "proposed"
    entity_key: str | None = None
    span: Span | None = None
    score: float | None = None


class TypedRelation(_Input):
    id: str | None = None
    type: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    object: str = Field(min_length=1)
    state: str = "proposed"
    score: float | None = None

    @field_validator("subject", "object", mode="before")
    @classmethod
    def _endpoint(cls, value: Any) -> Any:
        return value.get("id") if isinstance(value, dict) else value


class TypedItem(_Input):
    item_id: str = Field(min_length=1)
    entities: list[TypedMention] = Field(default_factory=list)
    relations: list[TypedRelation] = Field(default_factory=list)


class Backend(_Input):
    id: str | None = None
    model: str | None = None
    revision: str | None = None


class EntitiesFile(_Input):
    schema_version: int = 1
    backend: Backend | None = None
    items: list[TypedItem] = Field(default_factory=list)


class ClusterEntry(_Input):
    """One cluster with its weekly series keyed by ISO week label."""

    uid: str
    event: str
    predecessor_uids: list[str]
    member_count: int
    member_item_ids: list[str]
    top_terms: list[str]
    first_seen: str | None
    earliest_published_at: str | None
    weekly_series: dict[str, int]


class ClusterRun(_Input):
    run_id: str
    as_of: date | None
    clusters: list[ClusterEntry]
    entities: list[TypedItem]
    backend: Backend | None = None
    warnings: list[str] = Field(default_factory=list)


def _read(path: Path, model):
    try:
        return model.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except OSError as error:
        raise ValueError(f"Cannot read {path}: {error.strerror or error}") from error
    except ValueError as error:
        raise ValueError(f"{path} is not the expected Biblicus output: {error}") from error


def _trend_series(cluster: IdentityCluster, bins: WeeklyBins) -> dict[str, int]:
    rows = [*bins.discovered_topics, *bins.canonical_topics]
    match = next((row for row in rows if row.topic_uid == cluster.uid), None)
    if match is None and cluster.topic_id is not None:
        match = next((row for row in rows if row.topic_uid is None and row.topic_id == cluster.topic_id), None)
    return {week: int(count) for week, count in zip(bins.iso_weeks, match.counts)} if match is not None else {}


def _identity_series(cluster: IdentityCluster, weeks: list[str] | None) -> dict[str, int]:
    return {week: int(count) for week, count in zip(weeks or [], cluster.weekly_series or [])}


def load_run(identity: Path | None, trends: Path | None, entities: Path | None) -> ClusterRun | None:
    """The run the files describe, or ``None`` when no file is given. Trends and entities alone need the identity
    file only for clusters; entities can be imported without it."""
    if identity is None and trends is None and entities is None:
        return None
    if identity is None and trends is not None:
        raise ValueError("--trends needs --identity: the cluster identity says which topic is which cluster.")
    warnings: list[str] = []
    found = _read(identity, IdentityFile) if identity is not None else None
    series = _read(trends, TrendsFile) if trends is not None else None
    bins = series.weekly_bins if series is not None else None
    use_bins = bins is not None
    if found is not None and series is not None:
        if bins is None:
            warnings.append("The trends file has no weekly_bins; cluster series come from the identity file.")
        elif found.trends_snapshot_id and series.snapshot_id and found.trends_snapshot_id != series.snapshot_id:
            warnings.append(
                f"The identity run used trends snapshot {found.trends_snapshot_id}, not {series.snapshot_id}; "
                "cluster series come from the identity file."
            )
            use_bins = False
    typed = _read(entities, EntitiesFile) if entities is not None else None
    clusters = []
    for cluster in found.clusters if found is not None else []:
        weekly = _trend_series(cluster, bins) if use_bins and bins is not None else {}
        clusters.append(
            ClusterEntry(
                uid=cluster.uid,
                event=cluster.event,
                predecessor_uids=cluster.predecessor_uids,
                member_count=cluster.member_item_count,
                member_item_ids=cluster.member_item_ids,
                top_terms=cluster.top_terms or ([cluster.label] if cluster.label else []),
                first_seen=cluster.first_seen,
                earliest_published_at=cluster.earliest_published_at,
                weekly_series=weekly or _identity_series(cluster, found.series_iso_weeks),
            )
        )
    as_of = None
    if bins is not None and bins.as_of:
        as_of = parse_day(bins.as_of)
    elif found is not None and found.generated_at:
        as_of = parse_day(found.generated_at)
    run_id = found.run_id if found is not None else f"typed-entities-{hashlib.sha256(Path(entities).read_bytes()).hexdigest()[:12]}"
    return ClusterRun(
        run_id=run_id,
        as_of=as_of,
        clusters=clusters,
        entities=typed.items if typed is not None else [],
        backend=typed.backend if typed is not None else None,
        warnings=warnings,
    )
