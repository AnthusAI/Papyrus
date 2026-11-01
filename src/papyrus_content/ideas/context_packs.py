"""Context packs: the conversation and acceptance signals, ranking, trimming and anchor-based repeat suppression (epic PPY-2e9064, design
sections 4 and 5.1, tickets PPY-4f5cd3 and PPY-1c3cf9).

This module is a pure layer over ``SignalInputs``: it makes no client call. What the inputs do not hold (concept names and descriptions,
Reference summaries, the publication's mission, policy and sections) arrives in a ``PackLookups`` the caller builds.

* ``build_packs(inputs, lookups, now=..., config=...)`` returns every pack both signals find, already ordered by ``rank_packs``.
* ``conversation`` signal: entity = a Message thread; series = human Messages per day; baseline = the thread's own earlier days against all
  Messages on the site. ``acceptance`` signal: entity = a concept; series = human accepts per week of References linked to it; baseline =
  the concept's own earlier weeks against all human accepts. Both use ``scan_window`` with the bucket of the signal and report a pack only when the
  corrected p-value is within ``config.significance``; there is no fixed window, count or cap.
* Pending References appear in a pack only as context: status ``pending``, a ``P#`` handle and the note "not yet accepted". Only ``R#`` References
  (accepted) can be cited as evidence.
* ``rank_packs`` interleaves packs round-robin by signal, in order of surprise inside each signal.
* ``trim_pack(pack, limit)`` drops the lowest-ranked members of a pack until it fits ``synthesis.MAXIMUM_INPUT_CHARACTERS`` (the only bound).
* ``evidence_of(pack)`` is what an idea records in ``generated.evidence``; ``suppress_repeats(packs, ideas)`` offers an anchor that an idea already
  covers again only with new evidence and counts what it held back (``packsSkippedNoNewEvidence``).
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any

from ..knowledge_snapshot.trends import TrendConfig, exceeds_report, scan_window
from . import synthesis
from .signal_inputs import HumanVote, PendingReference, SignalInputs, SignalMessage, StoryRecord

CONVERSATION = "conversation"
ACCEPTANCE = "acceptance"
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
    return {
        "type": kind, "anchor": anchor, "windowDays": window["windowDays"], "count": window["count"], "expected": window["expected"],
        "correctedPValue": window["correctedPValue"], "surprise": window["surprise"], "dateBasis": basis,
    }


@dataclass(frozen=True)
class Context:
    inputs: SignalInputs
    lookups: PackLookups
    today: date
    config: TrendConfig
    accepted: tuple[HumanVote, ...]
    concepts_of_lineage: Mapping[str, tuple[str, ...]]
    messages_by_anchor: Mapping[str, tuple[SignalMessage, ...]]


def context_of(inputs: SignalInputs, lookups: PackLookups, now: datetime, config: TrendConfig) -> Context:
    links: dict[str, set[str]] = defaultdict(set)
    for link in inputs.concept_links:
        links[link.reference_lineage_id].add(link.concept_id)
    by_anchor: dict[str, list[SignalMessage]] = defaultdict(list)
    for message in inputs.messages:
        by_anchor[message.anchor_key].append(message)
    accepted = tuple(vote for vote in inputs.votes if vote.status == ACCEPTED and day_of(vote.voted_at))
    return Context(
        inputs, lookups, now.date(), config, accepted,
        {lineage: tuple(sorted(concepts)) for lineage, concepts in links.items()}, {anchor: tuple(rows) for anchor, rows in by_anchor.items()},
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


def reference_row(context: Context, handle: str, vote: HumanVote | None, pending: PendingReference | None, concept_handles: Mapping[str, str]) -> dict[str, Any]:
    source = vote or pending
    assert source is not None
    concepts = [concept_handles[concept] for concept in source.concept_ids if concept in concept_handles]
    row = {
        "handle": handle, "title": source.title, "url": source.url, "published": iso_day(source.source_published_at),
        "added": iso_day(source.created_at), "publishedBasis": "source" if source.source_published_at else None,
        "summary": context.lookups.summaries.get(source.lineage_id, ""), "concepts": concepts,
    }
    if vote is not None:
        return {**row, "acceptedBy": "human", "acceptedOn": iso_day(vote.voted_at), "status": ACCEPTED}
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


def finish_pack(context: Context, kind: str, anchor: str, window: Mapping[str, Any], basis: str, concepts: list[dict[str, Any]],
                accepted: Sequence[HumanVote], messages: Sequence[tuple[SignalMessage, str]], pending: Sequence[PendingReference]) -> Pack:
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
        concepts=tuple({key: value for key, value in row.items() if key != "_id"} for row in concepts), references=tuple(references), edges=(),
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
    packs = []
    for thread_id in sorted(by_thread):
        rows = by_thread[thread_id]
        window = window_for(axis.series(day for day, _ in rows), volume, context.config, DAY)
        if window is None:
            continue
        anchor_key = rows[0][1].anchor_key or thread_id
        packs.append(conversation_pack(context, axis, window, thread_id, anchor_key, [message for _, message in rows]))
    return packs


def conversation_pack(context: Context, axis: Axis, window: Mapping[str, Any], thread_id: str, anchor_key: str, thread: list[SignalMessage]) -> Pack:
    lineage = anchor_key.removeprefix(REFERENCE_ANCHOR_PREFIX) if anchor_key.startswith(REFERENCE_ANCHOR_PREFIX) else None
    vote = next((row for row in context.inputs.votes if row.lineage_id == lineage and row.status == ACCEPTED), None) if lineage else None
    held_back = next((row for row in context.inputs.pending_context if row.lineage_id == lineage), None) if lineage else None
    concept_ids = set(context.concepts_of_lineage.get(lineage, ())) if lineage else set()
    concepts = concept_rows(context, axis, window["windowBuckets"], sorted(concept_ids), None)
    accepted = [vote] if vote else []
    pending = [held_back] if held_back else []
    pending += [row for row in pending_for(context, concept_ids) if row not in pending]
    return finish_pack(context, CONVERSATION, thread_id, window, MESSAGE_BASIS, concepts, accepted, [(message, lineage or anchor_key) for message in thread], pending)


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
    packs = []
    for concept in sorted(by_concept):
        rows = by_concept[concept]
        window = window_for(axis.series(day for day, _ in rows), volume, context.config, WEEK)
        if window is None:
            continue
        packs.append(acceptance_pack(context, axis, window, concept, rows))
    return packs


def acceptance_pack(context: Context, axis: Axis, window: Mapping[str, Any], concept: str, rows: list[tuple[date, HumanVote]]) -> Pack:
    inside = sorted(
        ((day, vote) for day, vote in rows if axis.in_window(day, window["windowBuckets"])),
        key=lambda row: (row[0], row[1].lineage_id), reverse=True,
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
    """Every pack the conversation and acceptance signals find in ``inputs``, ordered by ``rank_packs``."""
    context = context_of(inputs, lookups, now, config or TrendConfig())
    return rank_packs([*conversation_packs(context), *acceptance_packs(context)])


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
        return replace(pack, references=pack.references[:-1], accepted_lineage_ids=pack.accepted_lineage_ids[:-1])
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
