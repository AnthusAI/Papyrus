"""Single-item signals and the one idea queue (epic PPY-2e9064, ticket PPY-2e72e3; design docs/idea-context-packs.md).

A single-item idea is one accepted Reference worth a post of its own. It is chosen by the same kind of evidence as a pack, not by being accepted and
undrafted. ``score_items`` gives each candidate (a ``MonitoredItem``) an *item signal* from the publication's ``SignalInputs``:

* ``acceptReason``: a person accepted this Reference and said why (1 or 0).
* ``messages``: the human Messages in threads anchored on it.
* ``links``: the concepts it is linked to (``mentions`` or ``related_to``).
* ``conceptAcceptance``: for each of those concepts, how many accepted human votes carry it, summed. Concept links are read only for References a
  person voted on, a thread is anchored on, or that are pending, so a Reference with none of those has no concept links yet.
* ``cyclotron``: the relevance Cyclotron's probability for the positive label, when it judged the Reference.

Each component is turned into a p-value against the site's own distribution: the share of the site's accepted References (the candidates and every
Reference a person accepted) whose value is at least this one. A component of zero says nothing and has p-value one. There is no threshold and no
weight: the item's p-value is the smallest component p-value times the number of components (Bonferroni, as the pack scan does), and its
``surprise`` is ``trends.significance_z`` of that, the same scale as a pack. An item whose corrected p-value is one (no evidence, or nothing the site's other References do not match) is not
scored, so a quiet site yields no single-item candidate rather than all of them.

``ordered_queue`` merges ranked packs and scored items into one list. Single items are one more signal type (``item``) beside ``conversation`` and
``acceptance``: inside a signal the most surprising comes first, and in each round the signals take their turn in order of the surprise they offer,
so neither packs nor single items starve. ``ordered_lineage_ids`` is the item part of that queue, ready for ``draft_monitor_stories(ordered_candidates=...)``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..knowledge_snapshot.trends import significance_z
from .context_packs import Pack
from .monitor_stories import MonitoredItem
from .signal_inputs import SignalInputs

ITEM = "item"
REFERENCE_ANCHOR_PREFIX = "reference#"
COMPONENTS = ("acceptReason", "messages", "links", "conceptAcceptance", "cyclotron")


@dataclass(frozen=True)
class ScoredItem:
    item: MonitoredItem
    signal: Mapping[str, Any]

    @property
    def surprise(self) -> float:
        return float(self.signal["surprise"])

    @property
    def signal_type(self) -> str:
        return ITEM

    @property
    def entry_id(self) -> str:
        return self.item.lineage_id


@dataclass(frozen=True)
class QueueEntry:
    kind: str
    surprise: float
    signal_type: str
    entry_id: str
    corrected_p_value: float
    pack: Pack | None = None
    scored_item: ScoredItem | None = None


def component_values(inputs: SignalInputs, candidates: Sequence[MonitoredItem]) -> dict[str, dict[str, float]]:
    """For each component, the value of every accepted Reference of the site (by lineage id); a Reference absent from a component has value zero."""
    accepted_votes = [vote for vote in inputs.votes if vote.status == "accepted"]
    lineages = {vote.lineage_id for vote in accepted_votes} | {item.lineage_id for item in candidates}
    concepts_of: dict[str, set[str]] = defaultdict(set)
    for link in inputs.concept_links:
        concepts_of[link.reference_lineage_id].add(link.concept_id)
    for vote in accepted_votes:
        concepts_of[vote.lineage_id] |= set(vote.concept_ids)
    accepted_per_concept: dict[str, int] = defaultdict(int)
    for lineage in {vote.lineage_id for vote in accepted_votes}:
        for concept in concepts_of[lineage]:
            accepted_per_concept[concept] += 1
    messages_per_lineage: dict[str, int] = defaultdict(int)
    for message in inputs.messages:
        if message.anchor_key.startswith(REFERENCE_ANCHOR_PREFIX):
            messages_per_lineage[message.anchor_key.removeprefix(REFERENCE_ANCHOR_PREFIX)] += 1
    reasoned = {vote.lineage_id for vote in accepted_votes if vote.reason}
    values: dict[str, dict[str, float]] = {name: {} for name in COMPONENTS}
    for lineage in lineages:
        values["acceptReason"][lineage] = 1.0 if lineage in reasoned else 0.0
        values["messages"][lineage] = float(messages_per_lineage.get(lineage, 0))
        values["links"][lineage] = float(len(concepts_of.get(lineage, ())))
        values["conceptAcceptance"][lineage] = float(sum(accepted_per_concept.get(concept, 0) for concept in concepts_of.get(lineage, ())))
    for item in candidates:
        if item.verdict and item.verdict.get("score") is not None:
            values["cyclotron"][item.lineage_id] = float(item.verdict["score"])
    return values


def upper_tail_p_value(value: float, distribution: Iterable[float]) -> float:
    """The share of the distribution at or above ``value``; one when the value is zero (no evidence)."""
    if value <= 0:
        return 1.0
    population = list(distribution)
    return sum(other >= value for other in population) / len(population)


def score_items(inputs: SignalInputs, candidates: Sequence[MonitoredItem]) -> list[ScoredItem]:
    """The candidates that have any evidence, each with its item signal (``type``, ``anchor``, ``surprise``, ``correctedPValue``, ``components``)."""
    values = component_values(inputs, candidates)
    scored = []
    for item in candidates:
        components = {}
        for name in COMPONENTS:
            value = values[name].get(item.lineage_id, 0.0)
            components[name] = {"value": value, "pValue": upper_tail_p_value(value, values[name].values())}
        smallest = min(row["pValue"] for row in components.values())
        corrected = min(1.0, smallest * len(COMPONENTS))
        if corrected >= 1.0:
            continue
        signal = {"type": ITEM, "anchor": item.lineage_id, "correctedPValue": corrected, "surprise": significance_z(corrected), "components": components}
        scored.append(ScoredItem(item, signal))
    return sorted(scored, key=lambda row: (-row.surprise, row.signal["correctedPValue"], row.item.lineage_id))


def ordered_queue(packs: Iterable[Pack], scored_items: Iterable[ScoredItem]) -> list[QueueEntry]:
    """Packs and scored single items in one queue: round-robin by signal type, the most surprising first inside a signal, and in each round the
    signals take their turn in order of the surprise they offer."""
    queues: dict[str, list[QueueEntry]] = defaultdict(list)
    for pack in packs:
        queues[pack.signal_type].append(QueueEntry("pack", pack.surprise, pack.signal_type, pack.pack_id, float(pack.signal["correctedPValue"]), pack=pack))
    for row in scored_items:
        queues[ITEM].append(QueueEntry("item", row.surprise, ITEM, row.entry_id, float(row.signal["correctedPValue"]), scored_item=row))
    for queue in queues.values():
        queue.sort(key=lambda entry: (-entry.surprise, entry.corrected_p_value, entry.entry_id))
    ordered: list[QueueEntry] = []
    for position in range(max((len(queue) for queue in queues.values()), default=0)):
        offered = [queue[position] for queue in queues.values() if len(queue) > position]
        ordered.extend(sorted(offered, key=lambda entry: (-entry.surprise, entry.signal_type, entry.entry_id)))
    return ordered


def ordered_lineage_ids(queue: Iterable[QueueEntry]) -> list[str]:
    return [entry.entry_id for entry in queue if entry.kind == "item"]
