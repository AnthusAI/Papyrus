"""Context packs: the conversation, acceptance and resurfaced signals, ranking, trimming and anchor-based repeat suppression (epic PPY-2e9064, design
sections 4 and 5.1, tickets PPY-4f5cd3 and PPY-1c3cf9).

This module is a pure layer over ``SignalInputs``: it makes no client call. What the inputs do not hold (concept names and descriptions,
Reference summaries, the publication's mission, policy and sections) arrives in a ``PackLookups`` the caller builds. The one thing it may call is
``lookups.vector_provider`` (``get_vector`` and ``query_by_vector``, the S3 Vectors provider of the router, or a fake in a test), which the cluster
signal reads; without one the cluster signal is skipped and says why in the log.

* ``build_packs(inputs, lookups, now=..., config=...)`` returns every pack the signals find, already ordered by ``rank_packs``.
* Cold start (PPY-1822f2): when an entity's own history is shorter than the minimum baseline (``config.minimum_baseline_weeks``) and its own scan finds
  no significant window, ``cross_sectional_windows`` tests its event count against its expected share among the site's comparable entities (the
  share is its exposure, the buckets of its own history, over all comparable entities' exposure; binomial upper tail, Bonferroni over the entities
  tested). The pack is marked ``emerging`` in its signal, with ``comparison`` saying how it was judged. No threshold: the same ``config.significance``.
* ``hub`` signal: entity = a recently arrived accepted Reference. Degree = its current Reference edges plus its shared-concept links (each other
  Reference sharing a concept counts once, weighted 1/sqrt(number of References carrying that concept)). The p-value is the share of the site's
  accepted References whose degree is at least this one (``1 - F(degree)``, the Reference itself included so it is never zero), Bonferroni over the
  recent References with a degree. "Recent" is derived from the site's own arrivals: the latest ceil(sqrt(distinct arrival days)) arrival days.
* ``cluster`` signal: entity = a connected component of the recent accepted References over current edges plus mutual-kNN vector neighbours
  (k = ceil(sqrt(n)) of the recent References that have a vector; a mutual pair joins only when its similarity stands out from the background pairs
  of the recent set at ``config.significance``, Bonferroni over the mutual pairs, because mutual neighbours alone chain unrelated References). A component with earlier arrivals (older accepted References that are current
  neighbours or among its members' nearest neighbours) is scanned like the others (members per day against all arrivals); a component with none is
  "new": its significance is the mean pairwise similarity of its members against the pairs of the whole recent set (one-sided z over the number of
  member pairs, Bonferroni over the components tested), which grows with both its size and its similarity, and it is marked ``emerging``.
* ``conversation`` signal: entity = a Message thread; series = human Messages per day; baseline = the thread's own earlier days against all
  Messages on the site. ``acceptance`` signal: entity = a concept; series = human accepts per week of References linked to it; baseline =
  the concept's own earlier weeks against all human accepts. Both use ``scan_window`` with the bucket of the signal and report a pack only when the
  corrected p-value is within ``config.significance``; there is no fixed window, count or cap.
* Pending References appear in a pack only as context: status ``pending``, a ``P#`` handle and the note "not yet accepted". Only ``R#`` References
  (accepted) can be cited as evidence.
* ``resurfaced`` signal: entity = an accepted Reference a person recently attended to (a human accept, or human Messages in a thread anchored on it)
  whose publication-to-ingestion gap is large. Both facts are read against the site's own distributions, never against a threshold: ``pGap`` is the
  share of the site's References (with both dates) whose gap is at least this one, ``pRecent`` the share of attended References whose latest attention
  is at least as recent. The corrected p-value is ``pGap * pRecent`` times the number of attended candidates (Bonferroni), and a pack is reported only
  within ``config.significance``. The pack says what pointed attention at the Reference (the accept, which Messages). New edges are not loaded by
  ``SignalInputs`` and are not part of the attention yet.
* Date bases (design 2.3): the newsroom's own stream is on ingestion (``acceptance``), what the model may say about the world is on publication
  (``published``, ``resurfaced``, the order of References inside a pack: ``sourcePublishedAt``, falling back to the added date with ``orderedBy: "added"``
  on the row). An unknown publication date stays ``None`` in ``published`` and is never filled from the added date.
* ``rank_packs`` interleaves packs round-robin by signal, in order of surprise inside each signal.
* ``trim_pack(pack, limit)`` drops the lowest-ranked members of a pack until it fits ``synthesis.MAXIMUM_INPUT_CHARACTERS`` (the only bound).
* ``evidence_of(pack)`` is what an idea records in ``generated.evidence``; ``suppress_repeats(packs, ideas)`` offers an anchor that an idea already
  covers again only with new evidence and counts what it held back (``packsSkippedNoNewEvidence``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from statistics import NormalDist
from typing import Any

from ..knowledge_snapshot.trends import TrendConfig, binomial_upper_tail, exceeds_report, scan_window, significance_z
from . import synthesis
from .signal_inputs import AcceptedReference, HumanVote, PendingReference, ReferenceEdge, SignalInputs, SignalMessage, StoryRecord

logger = logging.getLogger(__name__)

CONVERSATION = "conversation"
ACCEPTANCE = "acceptance"
RESURFACED = "resurfaced"
HUB = "hub"
CLUSTER = "cluster"
LINKED = "linked"
CONFIRMED = "confirmed"
SUGGESTED = "suggested"
RELATED_TO = "related_to"
REFERENCE_SUMMARY_VECTOR_KIND = "reference_summary"
S3_VECTORS_MAXIMUM_TOP_K = 100
PUBLICATION_BASIS = "publication"
MESSAGE_BASIS = "message"
INGESTION_BASIS = "ingestion"
DAY = 1
WEEK = 7
NOT_YET_ACCEPTED = "not yet accepted"
REFERENCE_ANCHOR_PREFIX = "reference#"
ACCEPTED = "accepted"
PENDING = "pending"
SPIKED_STATE = "declined"


@dataclass(frozen=True)
class ConceptInfo:
    name: str
    kind: str = "concept"
    description: str = ""
    hashtag: str = ""


@dataclass(frozen=True)
class PackLookups:
    """What the pure builders are asked for beside ``SignalInputs``: concept facts and Reference summaries by lineage id, and the publication's
    mission, policy and sections."""

    concepts: Mapping[str, ConceptInfo] = field(default_factory=dict)
    summaries: Mapping[str, str] = field(default_factory=dict)
    mission: str = ""
    policy: str = ""
    allowed_sections: tuple[str, ...] = ()
    vector_provider: Any = None


@dataclass(frozen=True)
class Pack:
    """One pack in the design's JSON shape (``as_json``), plus what the code needs and the JSON does not carry: ``scan`` (the window found, with
    ``tested``) and ``accepted_lineage_ids`` (the accepted References the pack holds)."""

    pack_id: str
    signal: Mapping[str, Any]
    concepts: tuple[Mapping[str, Any], ...]
    references: tuple[Mapping[str, Any], ...]
    edges: tuple[Mapping[str, Any], ...]
    messages: tuple[Mapping[str, Any], ...]
    recent_published_stories: tuple[Mapping[str, Any], ...]
    existing_ideas: tuple[Mapping[str, Any], ...]
    mission: str
    policy: str
    allowed_sections: tuple[str, ...]
    scan: Mapping[str, Any]
    accepted_lineage_ids: tuple[str, ...]

    @property
    def anchor(self) -> str:
        return str(self.signal["anchor"])

    @property
    def signal_type(self) -> str:
        return str(self.signal["type"])

    @property
    def surprise(self) -> float:
        return float(self.signal["surprise"])

    def as_json(self) -> dict[str, Any]:
        return {
            "packId": self.pack_id, "signal": dict(self.signal), "concepts": [dict(row) for row in self.concepts],
            "references": [dict(row) for row in self.references], "edges": [dict(row) for row in self.edges],
            "messages": [dict(row) for row in self.messages], "recent_published_stories": [dict(row) for row in self.recent_published_stories],
            "existing_ideas": [dict(row) for row in self.existing_ideas], "mission": self.mission, "policy": self.policy,
            "allowed_sections": list(self.allowed_sections),
        }

    def size(self) -> int:
        return len(json.dumps(self.as_json(), ensure_ascii=False))


def pack_id_of(site: str, signal: str, anchor: str, window_days: int) -> str:
    return "pack-" + hashlib.sha256(f"{site}|{signal}|{anchor}|{window_days}".encode()).hexdigest()[:12]


def day_of(moment: str | None) -> date | None:
    if not moment:
        return None
    try:
        return datetime.fromisoformat(str(moment).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def ordering_day(published: str | None, added: str | None) -> date:
    """The day a Reference is ordered by inside a pack: its publication date, else the day it was added (the fallback is flagged on the row)."""
    return day_of(published) or day_of(added) or date.min


def iso_day(moment: str | None) -> str | None:
    found = day_of(moment)
    return found.isoformat() if found else None


@dataclass(frozen=True)
class Axis:
    """The time axis of one signal: ``history`` buckets of ``bucket_days`` days, the last one holding ``today``."""

    today: date
    first_day: date
    bucket_days: int

    @property
    def history(self) -> int:
        return (self.today - self.first_day).days // self.bucket_days + 1

    def age(self, day: date) -> int:
        return max((self.today - day).days, 0) // self.bucket_days

    def series(self, days: Iterable[date]) -> list[int]:
        counts = [0] * self.history
        for day in days:
            position = self.history - 1 - self.age(day)
            if 0 <= position < self.history:
                counts[position] += 1
        return counts

    def in_window(self, day: date, window_buckets: int) -> bool:
        return self.age(day) < window_buckets


def axis_of(days: Sequence[date], today: date, bucket_days: int) -> Axis | None:
    return Axis(today, min(days), bucket_days) if days else None


def window_for(values: list[int], volume: list[int], config: TrendConfig, bucket_days: int) -> dict[str, Any] | None:
    window = scan_window(values, [float(count) for count in volume], config, bucket_days=bucket_days)
    if window is None or window["count"] < 1 or window["correctedPValue"] > config.significance:
        return None
    return window


def signal_of(kind: str, anchor: str, window: Mapping[str, Any], basis: str) -> dict[str, Any]:
    signal = {
        "type": kind, "anchor": anchor, "windowDays": window["windowDays"], "count": window["count"], "expected": window["expected"],
        "correctedPValue": window["correctedPValue"], "surprise": window["surprise"], "dateBasis": basis,
    }
    if window.get("emerging"):
        signal["emerging"] = True
        signal["comparison"] = window.get("comparison", CROSS_SECTIONAL)
    return signal


CROSS_SECTIONAL = "cross-sectional: the entity's own history is shorter than the minimum baseline, so its count is compared with its expected share among the site's comparable entities"


def minimum_baseline_buckets(config: TrendConfig, bucket_days: int) -> int:
    return -(-config.minimum_baseline_weeks * WEEK // bucket_days)


def history_buckets(first_day: date, today: date, bucket_days: int) -> int:
    return max((today - first_day).days, 0) // bucket_days + 1


def cross_sectional_windows(entities: Mapping[Any, tuple[int, int]], bucket_days: int, config: TrendConfig, comparison: str = CROSS_SECTIONAL) -> dict[Any, dict[str, Any]]:
    """The cold-start comparison. ``entities`` maps each comparable entity to ``(event count, buckets of its own history)``. Under no difference
    between entities an entity's events fall to it in proportion to its exposure (its buckets of history), so its count is tested against the
    binomial tail of all events with that share; the p-value is multiplied by the number of entities tested (Bonferroni) and an entity is kept only
    within ``config.significance``. Each kept entity gets a window shaped like ``scan_window``'s, with ``emerging`` set."""
    total = sum(count for count, _ in entities.values())
    exposure = sum(buckets for _, buckets in entities.values())
    found: dict[Any, dict[str, Any]] = {}
    for key in sorted(entities, key=str):
        count, buckets = entities[key]
        if count < 1 or exposure < 1:
            continue
        share = buckets / exposure
        p_value = binomial_upper_tail(count, total, share)
        corrected = min(1.0, p_value * len(entities))
        if corrected > config.significance:
            continue
        found[key] = {
            "windowBuckets": buckets, "windowDays": buckets * bucket_days, "bucketDays": bucket_days, "baselineBuckets": 0, "baselineDays": 0,
            "baselineCount": 0, "count": count, "expected": round(total * share, 3), "pValue": float(f"{p_value:.3g}"), "tested": len(entities),
            "correctedPValue": float(f"{corrected:.3g}"), "surprise": significance_z(corrected), "emerging": True, "comparison": comparison,
        }
    return found


def windows_for_entities(days_by_entity: Mapping[Any, Sequence[date]], axis: Axis, volume: list[int], config: TrendConfig, bucket_days: int) -> dict[Any, dict[str, Any]]:
    """The window of every entity that has one. An entity whose own scan finds a significant window keeps it. An entity whose own history is shorter
    than the minimum baseline and whose scan found none is judged cross-sectionally against the other such entities (marked ``emerging``)."""
    found: dict[Any, dict[str, Any]] = {}
    cold: dict[Any, tuple[int, int]] = {}
    shortest = minimum_baseline_buckets(config, bucket_days)
    for key in sorted(days_by_entity, key=str):
        days = days_by_entity[key]
        window = window_for(axis.series(days), volume, config, bucket_days)
        if window is not None:
            found[key] = window
            continue
        own = history_buckets(min(days), axis.today, bucket_days)
        if own < shortest:
            cold[key] = (len(days), own)
    found.update(cross_sectional_windows(cold, bucket_days, config))
    return found


@dataclass(frozen=True)
class Context:
    inputs: SignalInputs
    lookups: PackLookups
    today: date
    config: TrendConfig
    accepted: tuple[HumanVote, ...]
    concepts_of_lineage: Mapping[str, tuple[str, ...]]
    messages_by_anchor: Mapping[str, tuple[SignalMessage, ...]]
    accepted_references: Mapping[str, AcceptedReference] = field(default_factory=dict)
    edges_by_lineage: Mapping[str, tuple[ReferenceEdge, ...]] = field(default_factory=dict)


def accepted_from_vote(vote: HumanVote) -> AcceptedReference:
    return AcceptedReference(vote.reference_id, vote.lineage_id, vote.title, vote.url, vote.created_at, vote.source_published_at, vote.voted_at, "human", vote.concept_ids)


def context_of(inputs: SignalInputs, lookups: PackLookups, now: datetime, config: TrendConfig) -> Context:
    links: dict[str, set[str]] = defaultdict(set)
    for link in inputs.concept_links:
        links[link.reference_lineage_id].add(link.concept_id)
    by_anchor: dict[str, list[SignalMessage]] = defaultdict(list)
    for message in inputs.messages:
        by_anchor[message.anchor_key].append(message)
    accepted = tuple(vote for vote in inputs.votes if vote.status == ACCEPTED and day_of(vote.voted_at))
    references = {row.lineage_id: row for row in inputs.accepted} or {vote.lineage_id: accepted_from_vote(vote) for vote in accepted}
    edges: dict[str, list[ReferenceEdge]] = defaultdict(list)
    for edge in inputs.edges:
        edges[edge.subject_lineage_id].append(edge)
        edges[edge.object_lineage_id].append(edge)
    return Context(
        inputs, lookups, now.date(), config, accepted,
        {lineage: tuple(sorted(concepts)) for lineage, concepts in links.items()}, {anchor: tuple(rows) for anchor, rows in by_anchor.items()},
        references, {lineage: tuple(rows) for lineage, rows in edges.items()},
    )


def concept_info(context: Context, concept_id: str) -> ConceptInfo:
    return context.lookups.concepts.get(concept_id) or ConceptInfo(name=concept_id, hashtag="#" + concept_id)


def concept_rows(context: Context, axis: Axis, window_buckets: int, concept_ids: Sequence[str], first: str | None) -> list[dict[str, Any]]:
    """The pack's concepts: the anchor first, the rest by how many accepts they had in the window; counts are human accepts linked to each."""
    counts: dict[str, list[int]] = {concept: [0, 0] for concept in concept_ids}
    for vote in context.accepted:
        day = day_of(vote.voted_at)
        for concept in context.concepts_of_lineage.get(vote.lineage_id, vote.concept_ids):
            if concept in counts and day:
                counts[concept][0 if axis.in_window(day, window_buckets) else 1] += 1
    ordered = sorted(concept_ids, key=lambda concept: (concept != first, -counts[concept][0], concept))
    rows = []
    for position, concept in enumerate(ordered, start=1):
        info = concept_info(context, concept)
        rows.append({
            "handle": f"C{position}", "hashtag": info.hashtag or "#" + concept, "name": info.name, "kind": info.kind, "description": info.description,
            "recentCount": counts[concept][0], "baselineCount": counts[concept][1], "_id": concept,
        })
    return rows


def reference_row(context: Context, handle: str, vote: HumanVote | AcceptedReference | None, pending: PendingReference | None, concept_handles: Mapping[str, str]) -> dict[str, Any]:
    source = vote or pending
    assert source is not None
    concepts = [concept_handles[concept] for concept in source.concept_ids if concept in concept_handles]
    row = {
        "handle": handle, "title": source.title, "url": source.url, "published": iso_day(source.source_published_at),
        "added": iso_day(source.created_at), "publishedBasis": "source" if source.source_published_at else None,
        "orderedBy": "published" if day_of(source.source_published_at) else "added",
        "summary": context.lookups.summaries.get(source.lineage_id, ""), "concepts": concepts,
    }
    if vote is not None:
        return {**row, "acceptedBy": getattr(vote, "accepted_by", "human"), "acceptedOn": iso_day(vote.voted_at), "status": ACCEPTED}
    return {**row, "acceptedBy": None, "acceptedOn": None, "status": PENDING, "note": NOT_YET_ACCEPTED}


def pending_for(context: Context, concept_ids: set[str]) -> list[PendingReference]:
    found = [row for row in context.inputs.pending_context if concept_ids & set(row.concept_ids)]
    return sorted(found, key=lambda row: (-(row.score or 0.0), row.reference_id))


def stories_since(context: Context, window: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    began = context.today - timedelta(days=window["windowDays"] + window["baselineDays"])
    published = [
        {"title": story.title, "section": story.section, "date": story.date}
        for story in context.inputs.published if (day_of(story.date) or context.today) >= began
    ]
    ideas = [{"title": idea.title, "state": "spiked" if idea.state == SPIKED_STATE else "idea"} for idea in context.inputs.ideas]
    return published, ideas


def edge_rows(context: Context, handle_of: Mapping[str, str], suggested: Sequence[tuple[str, str, float]]) -> list[dict[str, Any]]:
    """The pack's edges between its accepted References: the current ones as ``confirmed`` (with their predicate), then the vector neighbours not
    yet confirmed as ``suggested`` (with their similarity)."""
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for lineage in handle_of:
        for edge in context.edges_by_lineage.get(lineage, ()):
            if edge.subject_lineage_id in handle_of and edge.object_lineage_id in handle_of:
                rows[(edge.subject_lineage_id, edge.object_lineage_id, edge.predicate)] = {
                    "from": handle_of[edge.subject_lineage_id], "to": handle_of[edge.object_lineage_id], "type": edge.predicate, "provenance": CONFIRMED,
                }
    confirmed_pairs = {frozenset(key[:2]) for key in rows}
    for first, second, similarity in suggested:
        if first in handle_of and second in handle_of and frozenset((first, second)) not in confirmed_pairs:
            rows[(first, second, RELATED_TO)] = {"from": handle_of[first], "to": handle_of[second], "type": RELATED_TO, "provenance": SUGGESTED, "similarity": round(similarity, 3)}
    return [rows[key] for key in sorted(rows, key=lambda key: (handle_of[key[0]], handle_of[key[1]], key[2]))]


def finish_pack(context: Context, kind: str, anchor: str, window: Mapping[str, Any], basis: str, concepts: list[dict[str, Any]],
                accepted: Sequence[HumanVote | AcceptedReference], messages: Sequence[tuple[SignalMessage, str]], pending: Sequence[PendingReference],
                suggested: Sequence[tuple[str, str, float]] = ()) -> Pack:
    handles = {row["_id"]: row["handle"] for row in concepts}
    references = [reference_row(context, f"R{position}", vote, None, handles) for position, vote in enumerate(accepted, start=1)]
    handle_of = {vote.lineage_id: f"R{position}" for position, vote in enumerate(accepted, start=1)}
    references += [reference_row(context, f"P{position}", None, row, handles) for position, row in enumerate(pending, start=1)]
    message_rows = [
        {"handle": f"M{position}", "about": handle_of.get(about, about), "author": message.author_kind, "date": iso_day(message.created_at), "text": message.text}
        for position, (message, about) in enumerate(messages, start=1)
    ]
    published, ideas = stories_since(context, window)
    return Pack(
        pack_id=pack_id_of(context.inputs.site, kind, anchor, window["windowDays"]), signal=signal_of(kind, anchor, window, basis),
        concepts=tuple({key: value for key, value in row.items() if key != "_id"} for row in concepts), references=tuple(references), edges=tuple(edge_rows(context, handle_of, suggested)),
        messages=tuple(message_rows), recent_published_stories=tuple(published), existing_ideas=tuple(ideas), mission=context.lookups.mission,
        policy=context.lookups.policy, allowed_sections=context.lookups.allowed_sections, scan=dict(window),
        accepted_lineage_ids=tuple(vote.lineage_id for vote in accepted),
    )


def conversation_packs(context: Context) -> list[Pack]:
    messages = context.inputs.messages
    days = [(day, message) for message in messages if (day := day_of(message.created_at))]
    axis = axis_of([day for day, _ in days], context.today, DAY)
    if axis is None:
        return []
    volume = axis.series(day for day, _ in days)
    by_thread: dict[str, list[tuple[date, SignalMessage]]] = defaultdict(list)
    for day, message in days:
        by_thread[message.thread_id].append((day, message))
    windows = windows_for_entities({thread: [day for day, _ in rows] for thread, rows in by_thread.items()}, axis, volume, context.config, DAY)
    packs = []
    for thread_id in sorted(by_thread):
        rows = by_thread[thread_id]
        window = windows.get(thread_id)
        if window is None:
            continue
        anchor_key = rows[0][1].anchor_key or thread_id
        packs.append(conversation_pack(context, axis, window, thread_id, anchor_key, [message for _, message in rows]))
    return packs


def conversation_pack(context: Context, axis: Axis, window: Mapping[str, Any], thread_id: str, anchor_key: str, thread: list[SignalMessage]) -> Pack:
    lineage = anchor_key.removeprefix(REFERENCE_ANCHOR_PREFIX) if anchor_key.startswith(REFERENCE_ANCHOR_PREFIX) else None
    vote = next((row for row in context.inputs.votes if row.lineage_id == lineage and row.status == ACCEPTED), None) if lineage else None
    vote = vote or (context.accepted_references.get(lineage) if lineage else None)
    held_back = next((row for row in context.inputs.pending_context if row.lineage_id == lineage), None) if lineage else None
    concept_ids = set(context.concepts_of_lineage.get(lineage, ())) if lineage else set()
    concepts = concept_rows(context, axis, window["windowBuckets"], sorted(concept_ids), None)
    linked = linked_references(context, lineage)
    related = [(row, text) for row, text in related_by_concept(context, lineage, vote, concept_ids) if row.lineage_id not in {other.lineage_id for other in linked}]
    accepted = ([vote] if vote else []) + list(linked) + [row for row, _ in related]
    pending = [held_back] if held_back else []
    pending += [row for row in pending_for(context, concept_ids) if row not in pending]
    pack = finish_pack(context, CONVERSATION, thread_id, window, MESSAGE_BASIS, concepts, accepted, [(message, lineage or anchor_key) for message in thread], pending)
    why = {row.lineage_id: text for row, text in related} | {row.lineage_id: LINKED for row in linked}
    marked = tuple(
        {**row, "relation": why[pack.accepted_lineage_ids[int(row["handle"][1:]) - 1]]}
        if row["status"] == ACCEPTED and pack.accepted_lineage_ids[int(row["handle"][1:]) - 1] in why else row
        for row in pack.references
    )
    return replace(pack, references=marked)


def linked_references(context: Context, lineage: str | None) -> list[AcceptedReference]:
    """The accepted References linked to ``lineage`` by a current edge (either direction), the most recently linked first."""
    if not lineage:
        return []
    found: dict[str, str] = {}
    for edge in context.edges_by_lineage.get(lineage, ()):
        other = edge.object_lineage_id if edge.subject_lineage_id == lineage else edge.subject_lineage_id
        if other != lineage and other in context.accepted_references:
            found[other] = max(found.get(other, ""), edge.created_at or "")
    return [context.accepted_references[other] for other in sorted(found, key=lambda other: (found[other], other), reverse=True)]


def related_by_concept(context: Context, lineage: str | None, anchor: HumanVote | None, concept_ids: set[str]) -> list[tuple[HumanVote, str]]:
    """Accepted References that share a concept with the anchor, most related first: by the summed weight 1/sqrt(frequency) of the shared concepts
    (a concept few References carry says more), then the most recently accepted. There is no cap; ``trim_pack`` bounds the pack."""
    frequency: dict[str, int] = defaultdict(int)
    for vote in context.accepted:
        for concept in context.concepts_of_lineage.get(vote.lineage_id, vote.concept_ids):
            frequency[concept] += 1
    found = []
    for vote in context.accepted:
        if vote.lineage_id == lineage:
            continue
        shared = sorted(concept_ids & set(context.concepts_of_lineage.get(vote.lineage_id, vote.concept_ids)))
        if shared:
            weight = sum(1 / frequency[concept] ** 0.5 for concept in shared)
            found.append((weight, vote, "shared concept " + ", ".join(concept_info(context, concept).hashtag or concept for concept in shared)))
    found.sort(key=lambda row: (-row[0], -ordering_day(row[1].source_published_at, row[1].created_at).toordinal(), row[1].lineage_id))
    return [(vote, text) for _, vote, text in found]


def acceptance_packs(context: Context) -> list[Pack]:
    events = [(day_of(vote.voted_at), vote) for vote in context.accepted]
    axis = axis_of([day for day, _ in events if day], context.today, WEEK)
    if axis is None:
        return []
    volume = axis.series(day for day, _ in events if day)
    by_concept: dict[str, list[tuple[date, HumanVote]]] = defaultdict(list)
    for day, vote in events:
        for concept in context.concepts_of_lineage.get(vote.lineage_id, vote.concept_ids):
            by_concept[concept].append((day, vote))
    windows = windows_for_entities({concept: [day for day, _ in rows] for concept, rows in by_concept.items()}, axis, volume, context.config, WEEK)
    packs = []
    for concept in sorted(by_concept):
        rows = by_concept[concept]
        window = windows.get(concept)
        if window is None:
            continue
        packs.append(acceptance_pack(context, axis, window, concept, rows))
    return packs


def acceptance_pack(context: Context, axis: Axis, window: Mapping[str, Any], concept: str, rows: list[tuple[date, HumanVote]]) -> Pack:
    inside = sorted(
        ((day, vote) for day, vote in rows if axis.in_window(day, window["windowBuckets"])),
        key=lambda row: (ordering_day(row[1].source_published_at, row[1].created_at), row[0], row[1].lineage_id), reverse=True,
    )
    accepted = [vote for _, vote in inside]
    related = {concept}
    for vote in accepted:
        related.update(context.concepts_of_lineage.get(vote.lineage_id, vote.concept_ids))
    concepts = concept_rows(context, axis, window["windowBuckets"], sorted(related), concept)
    lineages = {vote.lineage_id for vote in accepted}
    messages = [
        (message, anchor.removeprefix(REFERENCE_ANCHOR_PREFIX))
        for lineage in sorted(lineages) for anchor in [REFERENCE_ANCHOR_PREFIX + lineage]
        for message in context.messages_by_anchor.get(anchor, ())
    ]
    messages.sort(key=lambda row: (row[0].created_at, row[0].message_id))
    return finish_pack(context, ACCEPTANCE, concept, window, INGESTION_BASIS, concepts, accepted, messages, pending_for(context, {concept}))


def gap_days(source_published_at: str | None, created_at: str | None) -> int | None:
    """Days from the source's publication to its arrival on the site (never negative); ``None`` when either date is unknown."""
    published, added = day_of(source_published_at), day_of(created_at)
    return max((added - published).days, 0) if published and added else None


def attention_of(context: Context) -> dict[str, list[tuple[date, str, SignalMessage | None]]]:
    """Human attention by Reference lineage: its human accept and the human Messages in threads anchored on it, each with its day."""
    found: dict[str, list[tuple[date, str, SignalMessage | None]]] = defaultdict(list)
    for vote in context.accepted:
        found[vote.lineage_id].append((day_of(vote.voted_at), "accept", None))
    for anchor, messages in context.messages_by_anchor.items():
        if anchor.startswith(REFERENCE_ANCHOR_PREFIX):
            for message in messages:
                if day_of(message.created_at):
                    found[anchor.removeprefix(REFERENCE_ANCHOR_PREFIX)].append((day_of(message.created_at), "message", message))
    return found


def resurfaced_packs(context: Context) -> list[Pack]:
    gaps = {row.lineage_id: gap for row in [*context.inputs.votes, *context.inputs.pending_context] if (gap := gap_days(row.source_published_at, row.created_at)) is not None}
    attention = attention_of(context)
    latest_age = {lineage: min((context.today - day).days for day, _, _ in events) for lineage, events in attention.items()}
    candidates = sorted(vote.lineage_id for vote in context.accepted if vote.lineage_id in gaps and vote.lineage_id in latest_age)
    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        return []
    first_attention = min(day for events in attention.values() for day, _, _ in events)
    packs = []
    for lineage in candidates:
        gap_share = sum(other >= gaps[lineage] for other in gaps.values()) / len(gaps)
        recent_share = sum(age <= latest_age[lineage] for age in latest_age.values()) / len(latest_age)
        corrected = min(1.0, gap_share * recent_share * len(candidates))
        if corrected > context.config.significance:
            continue
        window_days = latest_age[lineage] + 1
        count = sum((context.today - day).days < window_days for day, _, _ in attention[lineage])
        window = {
            "windowDays": window_days, "baselineDays": max((context.today - first_attention).days - window_days, 0), "count": count,
            "expected": round(len(candidates) * gap_share * recent_share, 3), "tested": len(candidates), "correctedPValue": float(f"{corrected:.3g}"),
            "surprise": significance_z(corrected),
        }
        if (context.today - first_attention).days < minimum_baseline_buckets(context.config, DAY):
            window = {**window, "emerging": True, "comparison": "the site's own distributions of publication gaps and recent attention; its attention history is shorter than the minimum baseline"}
        packs.append(resurfaced_pack(context, lineage, window, gaps[lineage], sum(other < gaps[lineage] for other in gaps.values()) / len(gaps), recent_share))
    return packs


def resurfaced_pack(context: Context, lineage: str, window: Mapping[str, Any], gap: int, gap_percentile: float, recent_share: float) -> Pack:
    vote = next(row for row in context.accepted if row.lineage_id == lineage)
    concept_ids = set(context.concepts_of_lineage.get(lineage, vote.concept_ids))
    axis = Axis(context.today, context.today - timedelta(days=window["baselineDays"] + window["windowDays"]), DAY)
    concepts = concept_rows(context, axis, window["windowDays"], sorted(concept_ids), None)
    related = related_by_concept(context, lineage, vote, concept_ids)
    thread = sorted(context.messages_by_anchor.get(REFERENCE_ANCHOR_PREFIX + lineage, ()), key=lambda message: (message.created_at, message.message_id))
    pack = finish_pack(
        context, RESURFACED, REFERENCE_ANCHOR_PREFIX + lineage, window, PUBLICATION_BASIS, concepts, [vote] + [row for row, _ in related],
        [(message, lineage) for message in thread], pending_for(context, concept_ids),
    )
    pointed = [{"kind": "human accept", "date": iso_day(vote.voted_at)}] + [{"kind": "message", "handle": row["handle"], "date": row["date"]} for row in pack.messages]
    signal = {
        **pack.signal, "publicationGapDays": gap, "gapPercentile": round(gap_percentile, 3),
        "recentAttentionShare": round(recent_share, 3), "pointedAttentionAt": pointed,
    }
    return replace(pack, signal=signal)


def arrival_day(reference: AcceptedReference) -> date | None:
    return day_of(reference.accepted_at) or day_of(reference.created_at)


def recent_references(context: Context) -> list[AcceptedReference]:
    """The accepted References that arrived recently, by the site's own arrival distribution: the References that arrived on the latest
    ceil(sqrt(D)) distinct arrival days, D being the distinct days on which anything arrived (no fixed window)."""
    arrivals = {reference.lineage_id: day for reference in context.accepted_references.values() if (day := arrival_day(reference))}
    distinct = sorted(set(arrivals.values()), reverse=True)
    if not distinct:
        return []
    cutoff = distinct[math.ceil(math.sqrt(len(distinct))) - 1]
    return sorted((context.accepted_references[lineage] for lineage, day in arrivals.items() if day >= cutoff), key=lambda reference: (arrival_day(reference), reference.lineage_id))


def arrival_axis(context: Context) -> tuple[Axis, list[int]] | None:
    days = [day for reference in context.accepted_references.values() if (day := arrival_day(reference))]
    axis = axis_of(days, context.today, DAY)
    return (axis, axis.series(days)) if axis is not None else None


def site_history_is_short(context: Context) -> bool:
    days = [day for reference in context.accepted_references.values() if (day := arrival_day(reference))]
    return bool(days) and history_buckets(min(days), context.today, DAY) < minimum_baseline_buckets(context.config, DAY)


def concept_frequency(context: Context) -> dict[str, set[str]]:
    members: dict[str, set[str]] = defaultdict(set)
    for lineage in context.accepted_references:
        for concept in concepts_of(context, lineage):
            members[concept].add(lineage)
    return members


def concepts_of(context: Context, lineage: str) -> tuple[str, ...]:
    reference = context.accepted_references.get(lineage)
    return context.concepts_of_lineage.get(lineage, reference.concept_ids if reference else ())


def degree_of(context: Context, lineage: str, members: Mapping[str, set[str]]) -> tuple[float, dict[str, float], dict[str, float]]:
    """(degree, edge neighbours, shared-concept neighbours with their weights). Degree = current Reference edges to other References (each
    neighbour once) + the weight of every other accepted Reference sharing a concept (one weighted edge per neighbour, weight 1/sqrt(the number of
    References that carry the concept), the rarest shared concept counting)."""
    edge_neighbours = {
        (edge.object_lineage_id if edge.subject_lineage_id == lineage else edge.subject_lineage_id): 1.0
        for edge in context.edges_by_lineage.get(lineage, ()) if edge.subject_lineage_id != edge.object_lineage_id
    }
    shared: dict[str, float] = {}
    for concept in concepts_of(context, lineage):
        weight = 1 / math.sqrt(len(members[concept]))
        for other in members[concept]:
            if other != lineage:
                shared[other] = max(shared.get(other, 0.0), weight)
    return len(edge_neighbours) + sum(shared.values()), edge_neighbours, shared


def hub_packs(context: Context) -> list[Pack]:
    recent = recent_references(context)
    shape = arrival_axis(context)
    if not recent or shape is None:
        return []
    axis, _ = shape
    members = concept_frequency(context)
    degrees = {lineage: degree_of(context, lineage, members) for lineage in sorted(context.accepted_references)}
    population = [degree for degree, _, _ in degrees.values()]
    candidates = [reference for reference in recent if degrees[reference.lineage_id][0] > 0]
    packs = []
    for reference in candidates:
        degree, edge_neighbours, shared = degrees[reference.lineage_id]
        at_least = sum(other >= degree for other in population) / len(population)
        corrected = min(1.0, at_least * len(candidates))
        if corrected > context.config.significance:
            continue
        span = (context.today - axis.first_day).days
        age = (context.today - (arrival_day(reference) or context.today)).days + 1
        window = {
            "windowDays": age, "baselineDays": max(span - age, 0), "windowBuckets": age, "count": len(set(edge_neighbours) | set(shared)),
            "expected": round(sum(population) / len(population), 3), "tested": len(candidates), "correctedPValue": float(f"{corrected:.3g}"),
            "surprise": significance_z(corrected),
        }
        if site_history_is_short(context):
            window = {**window, "emerging": True, "comparison": "the degree distribution of the site's accepted References, whose history is shorter than the minimum baseline"}
        packs.append(hub_pack(context, axis, window, reference, degree, at_least, edge_neighbours, shared))
    return packs


def hub_pack(context: Context, axis: Axis, window: Mapping[str, Any], hub: AcceptedReference, degree: float, at_least: float,
             edge_neighbours: Mapping[str, float], shared: Mapping[str, float]) -> Pack:
    linked = [lineage for lineage in edge_neighbours if lineage in context.accepted_references]
    sharing = sorted((lineage for lineage in shared if lineage in context.accepted_references and lineage not in linked), key=lambda lineage: (-shared[lineage], lineage))
    neighbours = [context.accepted_references[lineage] for lineage in sorted(linked, key=lambda lineage: lineage)] + [context.accepted_references[lineage] for lineage in sharing]
    accepted = [hub, *neighbours]
    concept_ids = sorted({concept for reference in accepted for concept in concepts_of(context, reference.lineage_id)})
    concepts = concept_rows(context, axis, window["windowBuckets"], concept_ids, None)
    messages = [
        (message, reference.lineage_id) for reference in accepted for message in context.messages_by_anchor.get(REFERENCE_ANCHOR_PREFIX + reference.lineage_id, ())
    ]
    messages.sort(key=lambda row: (row[0].created_at, row[0].message_id))
    pack = finish_pack(context, HUB, "hub#" + hub.lineage_id, window, INGESTION_BASIS, concepts, accepted, messages, pending_for(context, set(concept_ids)))
    signal = {**pack.signal, "degree": round(degree, 3), "degreeShare": round(at_least, 3)}
    why = {lineage: LINKED for lineage in linked} | {lineage: "shared concept" for lineage in sharing}
    marked = tuple(
        {**row, "relation": why[pack.accepted_lineage_ids[index]]} if row["status"] == ACCEPTED and index > 0 and pack.accepted_lineage_ids[index] in why else row
        for index, row in enumerate(pack.references)
    )
    return replace(pack, signal=signal, references=marked)


@dataclass(frozen=True)
class VectorGraph:
    """What the vector index says about the recent References: their unit vectors, the mutual-kNN pairs with their similarity, and for each
    recent Reference the older accepted References among its nearest neighbours."""

    vectors: Mapping[str, list[float]]
    mutual: Mapping[tuple[str, str], float]
    older: Mapping[str, tuple[tuple[str, float], ...]]
    k: int


def dot(first: Sequence[float], second: Sequence[float]) -> float:
    return math.sumprod(first, second) if hasattr(math, "sumprod") else sum(a * b for a, b in zip(first, second))


def unit(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(dot(vector, vector))
    return [value / norm for value in vector] if norm else list(vector)


def match_lineage(match: Mapping[str, Any]) -> str | None:
    metadata = match.get("metadata") or {}
    return metadata.get("referenceLineageId") or metadata.get("lineageId")


def match_similarity(match: Mapping[str, Any]) -> float | None:
    if match.get("similarity") is not None:
        return float(match["similarity"])
    return 1.0 - float(match["distance"]) if match.get("distance") is not None else None


def load_vector_graph(provider: Any, recent: Sequence[str], older: set[str]) -> VectorGraph | None:
    """The mutual-kNN graph of the recent References that have a stored ``reference_summary`` vector. k = ceil(sqrt(n)) of those. Each is queried with
    an accepted-only filter at the API's largest ``topK``; neighbours among the recent set make the kNN lists, neighbours among older accepted
    References are kept as their earlier arrivals. No embedding call is made (``get_vector`` reads the stored vector)."""
    from papyrus_knowledge_query.vector_index import reference_summary_vector_key

    vectors = {}
    for lineage in recent:
        stored = provider.get_vector(reference_summary_vector_key(lineage))
        if stored:
            vectors[lineage] = unit(stored)
    if len(vectors) < 2:
        return None
    k = math.ceil(math.sqrt(len(vectors)))
    metadata_filter = {"$and": [{"vectorKind": {"$eq": REFERENCE_SUMMARY_VECTOR_KIND}}, {"curationStatus": {"$eq": ACCEPTED}}]}
    nearest: dict[str, dict[str, float]] = {}
    older_found: dict[str, tuple[tuple[str, float], ...]] = {}
    for lineage, vector in vectors.items():
        best: dict[str, float] = {}
        for match in provider.query_by_vector(vector, S3_VECTORS_MAXIMUM_TOP_K, metadata_filter):
            other, similarity = match_lineage(match), match_similarity(match)
            if other and other != lineage and similarity is not None and similarity > best.get(other, -2.0):
                best[other] = similarity
        ranked = sorted(best.items(), key=lambda row: (-row[1], row[0]))
        nearest[lineage] = {other: similarity for other, similarity in ranked if other in vectors}
        nearest[lineage] = dict(list(nearest[lineage].items())[:k])
        older_found[lineage] = tuple([row for row in ranked if row[0] in older][:k])
    mutual = {
        (first, second): similarity for first, row in nearest.items() for second, similarity in row.items() if first < second and first in nearest.get(second, {})
    }
    return VectorGraph(vectors, mutual, older_found, k)


def pair_sample(vectors: Mapping[str, list[float]]) -> list[float]:
    """Similarities of a deterministic sample of pairs of recent References (each with the next ceil(sqrt(n)) in order): the background that a
    component's pairs are read against (by their median and median absolute deviation, so close pairs inside the sample do not inflate the spread)."""
    order = sorted(vectors)
    stride = math.ceil(math.sqrt(len(order)))
    seen: set[frozenset[str]] = set()
    sample = []
    for position, first in enumerate(order):
        for step in range(1, stride + 1):
            second = order[(position + step) % len(order)]
            if second != first and frozenset((first, second)) not in seen:
                seen.add(frozenset((first, second)))
                sample.append(dot(vectors[first], vectors[second]))
    return sample


def robust_centre_and_spread(values: Sequence[float]) -> tuple[float, float]:
    """(median, 1.4826 x the median absolute deviation) of the background pair similarities: the same centre and spread a normal sample would have,
    but a few genuinely close pairs inside the sample do not inflate them."""
    if not values:
        return 0.0, 0.0
    centre = statistics.median(values)
    return centre, 1.4826 * statistics.median(abs(value - centre) for value in values)


def similarity_p_value(similarity: float, background_mean: float, background_spread: float, pairs: int = 1) -> float:
    """One-sided normal tail of ``similarity`` (the mean of ``pairs`` pairs) against the background pairs; 1 when the background has no spread."""
    if background_spread <= 0:
        return 1.0
    return min(1.0, 0.5 * math.erfc((similarity - background_mean) / (background_spread / math.sqrt(pairs)) / math.sqrt(2)))


def typical_neighbour_pairs(mutual: Mapping[tuple[str, str], float], vectors: Mapping[str, list[float]]) -> dict[tuple[str, str], float]:
    """The mutual-kNN pairs at least as similar as the site's typical nearest neighbour (the median, over the recent References, of each one's
    similarity to its single nearest neighbour). Mutual kNN alone chains unrelated References into one component; a per-pair significance test
    over all pairs leaves a small site with none. The cut is the site's own: a pair joins when its members are as close as a typical Reference is
    to its closest one, so a real topic joins into one component and loose pairs do not. Components are then ranked by surprise, not gated."""
    nearest = [max((dot(vector, other) for name, other in vectors.items() if name != lineage), default=None) for lineage, vector in vectors.items()]
    nearest = sorted(value for value in nearest if value is not None)
    if not nearest:
        return {}
    middle = len(nearest) // 2
    typical = nearest[middle] if len(nearest) % 2 else (nearest[middle - 1] + nearest[middle]) / 2
    return {pair: similarity for pair, similarity in mutual.items() if similarity >= typical}


def distinctive_pairs(mutual: Mapping[tuple[str, str], float], background_mean: float, background_spread: float, significance: float) -> dict[tuple[str, str], float]:
    """The mutual-kNN pairs that are closer than the background pairs of the recent set at ``significance`` (Bonferroni over the mutual pairs): with
    k = ceil(sqrt(n)) mutual neighbours alone chain unrelated References into one component, so a pair joins only when its similarity stands out."""
    return {
        pair: similarity for pair, similarity in mutual.items()
        if similarity_p_value(similarity, background_mean, background_spread) * len(mutual) <= significance
    }


def components_of(nodes: Sequence[str], pairs: Iterable[tuple[str, str]]) -> list[list[str]]:
    parent = {node: node for node in nodes}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for first, second in pairs:
        if first in parent and second in parent:
            parent[find(first)] = find(second)
    groups: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        groups[find(node)].append(node)
    return sorted((sorted(group) for group in groups.values()), key=lambda group: group[0])


def fingerprint_of(members: Sequence[str]) -> str:
    return hashlib.sha256("|".join(sorted(members)).encode()).hexdigest()[:12]


def cluster_packs(context: Context) -> list[Pack]:
    provider = context.lookups.vector_provider
    if provider is None:
        logger.info("cluster signal skipped: no vector provider (the publication has no vectorIndexArn, so there are no vectors to read)")
        return []
    recent = recent_references(context)
    shape = arrival_axis(context)
    if len(recent) < 2 or shape is None:
        return []
    axis, volume = shape
    recent_lineages = [reference.lineage_id for reference in recent]
    older = set(context.accepted_references) - set(recent_lineages)
    try:
        graph = load_vector_graph(provider, recent_lineages, older)
    except Exception as error:  # noqa: BLE001 - a vector failure costs the cluster signal, not the run
        logger.warning("cluster signal skipped: reading the vector index failed (%s: %s)", type(error).__name__, str(error)[:160])
        return []
    if graph is None:
        logger.info("cluster signal skipped: fewer than two recent accepted References have a stored vector")
        return []
    confirmed = {
        (edge.subject_lineage_id, edge.object_lineage_id)
        for lineage in recent_lineages for edge in context.edges_by_lineage.get(lineage, ())
        if edge.subject_lineage_id in recent_lineages and edge.object_lineage_id in recent_lineages
    }
    background = pair_sample(graph.vectors)
    mean_background, spread = robust_centre_and_spread(background)
    older_pairs = {(member, other): similarity for member, row in graph.older.items() for other, similarity in row}
    kept_older = distinctive_pairs(older_pairs, mean_background, spread, context.config.significance)
    graph = replace(
        graph, mutual=typical_neighbour_pairs(graph.mutual, graph.vectors),
        older={member: tuple((other, similarity) for other, similarity in row if (member, other) in kept_older) for member, row in graph.older.items()},
    )
    groups = components_of(recent_lineages, [*confirmed, *graph.mutual])
    clusters = [group for group in groups if len(group) >= 2]
    shortest = minimum_baseline_buckets(context.config, DAY)
    windows: dict[str, dict[str, Any]] = {}
    scanned: dict[str, list[date]] = {}
    fresh: dict[str, list[str]] = {}
    earlier_of: dict[str, list[str]] = {}
    for group in clusters:
        key = fingerprint_of(group)
        earlier = sorted({other for member in group for other, _ in graph.older.get(member, ())} | {
            (edge.object_lineage_id if edge.subject_lineage_id == member else edge.subject_lineage_id)
            for member in group for edge in context.edges_by_lineage.get(member, ()) if (edge.object_lineage_id if edge.subject_lineage_id == member else edge.subject_lineage_id) in older
        })
        earlier_of[key] = earlier
        if earlier:
            scanned[key] = [day for lineage in [*group, *earlier] if (day := arrival_day(context.accepted_references[lineage]))]
        else:
            fresh[key] = group
    windows.update(windows_for_entities(scanned, axis, volume, context.config, DAY))
    windows.update(new_component_windows(context, fresh, graph, mean_background, spread, len(clusters)))
    packs = []
    for group in clusters:
        key = fingerprint_of(group)
        if key in windows:
            packs.append(cluster_pack(context, axis, windows[key], key, group, graph, is_new=key in fresh))
    return packs


def mean_pairwise_similarity(group: Sequence[str], vectors: Mapping[str, list[float]]) -> tuple[float, int]:
    values = [dot(vectors[first], vectors[second]) for position, first in enumerate(group) if first in vectors for second in group[position + 1:] if second in vectors]
    return (sum(values) / len(values), len(values)) if values else (0.0, 0)


def new_component_windows(context: Context, fresh: Mapping[str, list[str]], graph: VectorGraph, background_mean: float, background_spread: float,
                          total_components: int) -> dict[str, dict[str, Any]]:
    """Windows of the components with no earlier arrivals. Their members' mean pairwise similarity is read against the background pairs of the
    whole recent set (one-sided z, which grows with the number of member pairs, so with size as well as similarity), Bonferroni over the
    components tested; a component with fewer than two vectors is judged by size among all the recent References cross-sectionally instead."""
    found: dict[str, dict[str, Any]] = {}
    cold: dict[str, tuple[int, int]] = {}
    scored = {key: mean_pairwise_similarity(group, graph.vectors) for key, group in fresh.items()}
    tested = sum(1 for _, pairs in scored.values() if pairs)
    for key, group in fresh.items():
        mean, pairs = scored[key]
        days = [day for lineage in group if (day := arrival_day(context.accepted_references[lineage]))]
        if not days:
            continue
        span = (context.today - min(days)).days + 1
        if pairs and background_spread > 0:
            # Ranked, not gated: a new theme on a small site never clears a corrected test, and the design ranks new components by how much closer
            # than the background their members are. The pack says "emerging"; the citation check, the gate and the editors judge the idea.
            corrected = min(1.0, similarity_p_value(mean, background_mean, background_spread, pairs) * tested)
            if mean > background_mean:
                found[key] = {
                    "windowBuckets": span, "windowDays": span, "bucketDays": DAY, "baselineBuckets": 0, "baselineDays": 0, "baselineCount": 0, "count": len(group),
                    "expected": round(len(graph.vectors) / max(total_components, 1), 3), "tested": tested, "correctedPValue": float(f"{corrected:.3g}"),
                    "surprise": significance_z(corrected), "emerging": True, "new": True, "meanPairwiseSimilarity": round(mean, 3), "score": round(len(group) * mean, 3),
                    "comparison": "new component: its members' mean pairwise similarity against the background pairs of the recent References",
                }
        elif not pairs:
            cold[key] = (len(group), 1)
    if cold:
        singles = {"single#" + lineage: (1, 1) for lineage in graph.vectors if all(lineage not in group for group in fresh.values())}
        for key, window in cross_sectional_windows({**cold, **singles}, DAY, context.config, "new component: its size against the other recent References, which have no vectors to compare").items():
            if key in cold:
                found[key] = {**window, "new": True}
    return found


def cluster_pack(context: Context, axis: Axis, window: Mapping[str, Any], key: str, group: Sequence[str], graph: VectorGraph, *, is_new: bool) -> Pack:
    accepted = sorted((context.accepted_references[lineage] for lineage in group), key=lambda reference: (-ordering_day(reference.source_published_at, reference.created_at).toordinal(), reference.lineage_id))
    concept_ids = sorted({concept for reference in accepted for concept in concepts_of(context, reference.lineage_id)})
    concepts = concept_rows(context, axis, window["windowBuckets"], concept_ids, None)
    messages = [
        (message, reference.lineage_id) for reference in accepted for message in context.messages_by_anchor.get(REFERENCE_ANCHOR_PREFIX + reference.lineage_id, ())
    ]
    messages.sort(key=lambda row: (row[0].created_at, row[0].message_id))
    suggested = [(first, second, similarity) for (first, second), similarity in sorted(graph.mutual.items()) if first in group and second in group]
    pack = finish_pack(context, CLUSTER, "cluster#" + key, window, INGESTION_BASIS, concepts, accepted, messages, pending_for(context, set(concept_ids)), suggested)
    signal = {**pack.signal, "members": len(group), "k": graph.k}
    for name in ("meanPairwiseSimilarity", "score"):
        if name in window:
            signal[name] = window[name]
    if is_new:
        signal["new"] = True
    return replace(pack, signal=signal)


def rank_packs(packs: Iterable[Pack]) -> list[Pack]:
    """Packs from different signals interleaved round-robin by signal: inside a signal the most surprising pack is first, and in each round the
    signals take their turn in order of the surprise of the pack they offer, so one noisy signal cannot take the whole queue."""
    queues: dict[str, list[Pack]] = defaultdict(list)
    for pack in packs:
        queues[pack.signal_type].append(pack)
    for queue in queues.values():
        queue.sort(key=lambda pack: (-pack.surprise, float(pack.signal["correctedPValue"]), pack.pack_id))
    ordered: list[Pack] = []
    depth = max((len(queue) for queue in queues.values()), default=0)
    for position in range(depth):
        offered = [queue[position] for queue in queues.values() if len(queue) > position]
        ordered.extend(sorted(offered, key=lambda pack: (-pack.surprise, pack.signal_type, pack.pack_id)))
    return ordered


def build_packs(inputs: SignalInputs, lookups: PackLookups, *, now: datetime, config: TrendConfig | None = None) -> list[Pack]:
    """Every pack the conversation, acceptance, resurfaced, hub and cluster signals find in ``inputs``, ordered by ``rank_packs``."""
    context = context_of(inputs, lookups, now, config or TrendConfig())
    return rank_packs([*conversation_packs(context), *acceptance_packs(context), *resurfaced_packs(context), *hub_packs(context), *cluster_packs(context)])


TRIM_ORDER = ("pending", "recent_published_stories", "messages", "references", "concepts")


def trim_pack(pack: Pack, limit: int = synthesis.MAXIMUM_INPUT_CHARACTERS) -> Pack:
    """The pack cut to ``limit`` characters of JSON, lowest-ranked members first: pending References, then published stories, then the oldest
    Messages, then the oldest accepted References, then the least active concepts. A pack that fits is returned as it is."""
    current = pack
    while current.size() > limit:
        smaller = drop_lowest_ranked(current)
        if smaller is None:
            return current
        current = smaller
    return current


def drop_lowest_ranked(pack: Pack) -> Pack | None:
    pending = [row for row in pack.references if row["status"] == PENDING]
    if pending:
        last = pending[-1]
        return replace(pack, references=tuple(row for row in pack.references if row is not last))
    if pack.recent_published_stories:
        return replace(pack, recent_published_stories=pack.recent_published_stories[:-1])
    if pack.messages:
        return replace(pack, messages=pack.messages[1:])
    if len(pack.references) > 0:
        dropped = pack.references[-1]["handle"]
        return replace(
            pack, references=pack.references[:-1], accepted_lineage_ids=pack.accepted_lineage_ids[:-1],
            edges=tuple(row for row in pack.edges if dropped not in (row["from"], row["to"])),
        )
    if len(pack.concepts) > 1:
        return replace(pack, concepts=pack.concepts[:-1])
    return None


def evidence_of(pack: Pack) -> dict[str, Any]:
    """What an idea built from ``pack`` records in ``generated.evidence``: the anchor, the window it reported and the accepted References it held."""
    return {
        "packId": pack.pack_id, "signal": pack.signal_type, "anchor": pack.anchor,
        "window": {"windowDays": pack.scan["windowDays"], "count": pack.scan["count"], "tested": pack.scan["tested"]},
        "surprise": pack.surprise, "referenceLineageIds": list(pack.accepted_lineage_ids),
    }


@dataclass(frozen=True)
class Suppression:
    kept: tuple[Pack, ...]
    skipped: tuple[Pack, ...]

    @property
    def packsSkippedNoNewEvidence(self) -> int:
        return len(self.skipped)


def recorded_evidence(idea: StoryRecord) -> dict[str, Any]:
    try:
        parsed = json.loads(idea.evidence or "{}")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def last_idea_on(anchor: str, ideas: Sequence[StoryRecord]) -> tuple[StoryRecord, dict[str, Any]] | None:
    found = [(idea, recorded_evidence(idea)) for idea in ideas]
    found = [(idea, evidence) for idea, evidence in found if evidence.get("anchor") == anchor]
    return max(found, key=lambda row: (row[0].date or "", row[0].story_id)) if found else None


def has_new_evidence(pack: Pack, idea: StoryRecord, evidence: Mapping[str, Any], config: TrendConfig) -> bool:
    reported = evidence.get("window")
    more_activity = isinstance(reported, dict) and exceeds_report(dict(pack.scan), reported, config)[0]
    new_reference = bool(set(pack.accepted_lineage_ids) - set(evidence.get("referenceLineageIds") or ()))
    if idea.state == SPIKED_STATE:
        return more_activity and new_reference
    return more_activity or new_reference


def suppress_repeats(packs: Iterable[Pack], ideas: Sequence[StoryRecord], config: TrendConfig | None = None) -> Suppression:
    """No repeat without new evidence. A pack whose anchor an idea already covers is kept only when the activity is materially more than that
    idea reported (``exceeds_report``) or the pack holds an accepted Reference the idea's pack did not; for a spiked idea both are needed. A
    Reference may appear in several theme ideas. Order is preserved; ``packsSkippedNoNewEvidence`` is the count held back."""
    config = config or TrendConfig()
    kept, skipped = [], []
    for pack in packs:
        last = last_idea_on(pack.anchor, ideas)
        if last is None or has_new_evidence(pack, last[0], last[1], config):
            kept.append(pack)
        else:
            skipped.append(pack)
    return Suppression(tuple(kept), tuple(skipped))
