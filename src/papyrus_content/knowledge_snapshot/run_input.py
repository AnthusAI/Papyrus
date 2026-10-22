"""The input of ``papyrus knowledge publish-run``: one workstation run, read from a directory of Biblicus JSON files.

The pydantic models below are Papyrus's own contract for what it needs; the Biblicus outputs are mapped onto them by
``load_run_directory``, which is deliberately thin. Files of the run directory:

``topic-identity.json``
    ``{"run_id", "as_of", "clusters": [{"uid", "event", "predecessor_uids", "member_count", "member_item_ids",
    "top_terms", "first_seen", "topic_id"}]}``. The output of ``biblicus analyze topic-identity``.
``topic-trends.json``
    The output of ``biblicus analyze topic-trends --bin weekly``; only ``weekly_bins`` is read:
    ``{"weekly_bins": {"iso_weeks": ["2026-W42", ...], "discovered_topics": [{"topic_id", "topic_uid", "counts": [...]}]}}``.
    A cluster takes the series whose ``topic_uid`` is its ``uid``, else whose ``topic_id`` is its ``topic_id``.
``typed-entities.json`` (optional)
    ``{"entities": [{"item_id", "name", "kind", "state": "resolved"|"proposed", "start", "end"}]}``. The output of
    ``biblicus extract typed-entities``.

Item ids are the ids of Papyrus items (the corpus export writes them to the front matter).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IDENTITY_FILE = "topic-identity.json"
TRENDS_FILE = "topic-trends.json"
ENTITIES_FILE = "typed-entities.json"


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore")


class IdentityCluster(_Input):
    uid: str = Field(min_length=1)
    event: str = "continued"
    predecessor_uids: list[str] = Field(default_factory=list)
    member_count: int = Field(default=0, ge=0)
    member_item_ids: list[str] = Field(default_factory=list)
    top_terms: list[str] = Field(default_factory=list)
    first_seen: date | None = None
    topic_id: int | None = None


class IdentityFile(_Input):
    run_id: str | None = None
    as_of: date | None = None
    clusters: list[IdentityCluster] = Field(default_factory=list)


class TrendSeries(_Input):
    topic_id: int | None = None
    topic_uid: str | None = None
    counts: list[int] = Field(default_factory=list)


class WeeklyBins(_Input):
    iso_weeks: list[str] = Field(default_factory=list)
    discovered_topics: list[TrendSeries] = Field(default_factory=list)
    canonical_topics: list[TrendSeries] = Field(default_factory=list)


class TrendsFile(_Input):
    weekly_bins: WeeklyBins | None = None


class TypedEntity(_Input):
    item_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    state: Literal["resolved", "proposed"] = "proposed"
    start: int | None = None
    end: int | None = None


class EntitiesFile(_Input):
    entities: list[TypedEntity] = Field(default_factory=list)


class ClusterEntry(_Input):
    """One cluster with its weekly series keyed by ISO week label."""

    uid: str
    event: str
    predecessor_uids: list[str]
    member_count: int
    member_item_ids: list[str]
    top_terms: list[str]
    first_seen: date | None
    weekly_series: dict[str, int]


class ClusterRun(_Input):
    run_id: str
    as_of: date | None
    clusters: list[ClusterEntry]
    entities: list[TypedEntity]
    warnings: list[str] = Field(default_factory=list)


def _series_of(cluster: IdentityCluster, bins: WeeklyBins | None) -> dict[str, int]:
    if bins is None:
        return {}
    rows = [*bins.discovered_topics, *bins.canonical_topics]
    match = next((row for row in rows if row.topic_uid == cluster.uid), None)
    if match is None and cluster.topic_id is not None:
        match = next((row for row in rows if row.topic_uid is None and row.topic_id == cluster.topic_id), None)
    if match is None:
        return {}
    return {week: int(count) for week, count in zip(bins.iso_weeks, match.counts)}


def load_run_directory(directory: Path) -> ClusterRun:
    directory = Path(directory)
    identity_path = directory / IDENTITY_FILE
    if not identity_path.is_file() and not (directory / ENTITIES_FILE).is_file():
        raise ValueError(f"{directory} holds neither {IDENTITY_FILE} nor {ENTITIES_FILE}.")
    warnings: list[str] = []
    identity = IdentityFile.model_validate(json.loads(identity_path.read_text(encoding="utf-8"))) if identity_path.is_file() else IdentityFile()
    trends_path = directory / TRENDS_FILE
    trends = TrendsFile.model_validate(json.loads(trends_path.read_text(encoding="utf-8"))) if trends_path.is_file() else TrendsFile()
    if identity.clusters and trends.weekly_bins is None:
        warnings.append(f"{TRENDS_FILE} has no weekly_bins; cluster series are empty.")
    entities_path = directory / ENTITIES_FILE
    entities = EntitiesFile.model_validate(json.loads(entities_path.read_text(encoding="utf-8"))).entities if entities_path.is_file() else []
    clusters = [
        ClusterEntry(
            uid=cluster.uid,
            event=cluster.event,
            predecessor_uids=cluster.predecessor_uids,
            member_count=cluster.member_count,
            member_item_ids=cluster.member_item_ids,
            top_terms=cluster.top_terms,
            first_seen=cluster.first_seen,
            weekly_series=_series_of(cluster, trends.weekly_bins),
        )
        for cluster in identity.clusters
    ]
    return ClusterRun(run_id=identity.run_id or directory.resolve().name, as_of=identity.as_of, clusters=clusters, entities=entities, warnings=warnings)
