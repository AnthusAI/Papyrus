"""The signal queue of one publication's run: the one read pass, the lookups the packs need, the packs, and the single items, in one ordered queue (epic
PPY-2e9064, tickets PPY-787361 and PPY-022025; design docs/idea-context-packs.md sections 4 and 5).

``prepare_signal_run`` reads the publication once (``load_signal_inputs``), loads what the pure pack builders are asked for (``load_pack_lookups``),
builds the packs, keeps only the signals the publication asked for, holds back every pack whose anchor an idea already covers without new evidence
(``suppress_repeats``) and ranks the rest. ``SignalRun.queue(candidates)`` then scores the single-item candidates (``score_items``) and merges both into
the one queue ``ordered_queue`` defines; ``monitor_stories.draft_monitor_stories`` walks that queue, sending a pack to ``draft_pack_ideas`` and an item to
the single-item path.

The lookups:

* ``concepts``: every accepted, current SemanticNode, keyed by its lineage id and its id, with the name, kind, description and hashtag
  (``knowledge_snapshot.keys.concept_hashtag``); ``concept_nodes`` maps a hashtag to its row, so ``draft_pack_ideas`` can link a cited concept.
* ``summaries``: a Reference's summary, read only for the References a pack shows. It is the text of the ``reference_summary_<N>_tokens`` Message
  linked to the Reference (the highest token budget, the newest), else ``attachment_summary(lineage)`` when the caller can read the metadata
  attachment (the router has no storage grant, so it passes none and a Reference without a summary Message has an empty summary).
* ``vector_provider``: the vector index provider the router run holds when the publication has a ``vectorIndexArn`` (``monitoring_vectors.vector_provider_for``);
  without one the hub signal still runs on edges and concepts and the cluster signal is skipped with a logged reason.
* ``mission``, ``policy`` and ``allowed_sections``: from the same context ``load_context`` gives the single-item path.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..knowledge_snapshot.keys import concept_hashtag
from .context_packs import ConceptInfo, Pack, PackLookups, build_packs, rank_packs, suppress_repeats
from .item_signals import QueueEntry, ordered_queue, score_items
from .monitor_stories import MonitoredItem
from .signal_inputs import SignalInputs, load_signal_inputs

SUMMARY_PREDICATE = re.compile(r"^reference_summary_(\d+)_tokens$")
SUMMARY_MESSAGE_KINDS = (None, "", "reference_summary")
ACCEPTED_NODE = "accepted"
CURRENT = "current"   # the loaders of the knowledge snapshot name it too; they are not imported here because they pull in pydantic, which the router zip does not carry
AttachmentSummary = Callable[[str], str]


class ReferenceSummaries(Mapping):
    """Summaries by Reference lineage id, each read the first time a pack asks for it (a Reference no pack shows is never read)."""

    def __init__(self, client: Any, attachment_summary: AttachmentSummary | None = None) -> None:
        self.client = client
        self.attachment_summary = attachment_summary
        self.found: dict[str, str] = {}

    def __getitem__(self, lineage_id: str) -> str:
        if lineage_id not in self.found:
            self.found[lineage_id] = self.read(lineage_id)
        return self.found[lineage_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self.found)

    def __len__(self) -> int:
        return len(self.found)

    def get(self, lineage_id: str, default: Any = "") -> Any:
        return self[lineage_id] or default

    def read(self, lineage_id: str) -> str:
        return self.from_message(lineage_id) or (self.attachment_summary(lineage_id) if self.attachment_summary else "")

    def from_message(self, lineage_id: str) -> str:
        relations = self.client.list_semantic_relations_by_object_state(f"reference#{lineage_id}#current")
        candidates = []
        for relation in relations:
            match = SUMMARY_PREDICATE.match(str(relation.get("relationTypeKey") or relation.get("predicate") or ""))
            if match and relation.get("subjectKind") == "message" and relation.get("subjectId") and relation.get("relationState", "current") == "current":
                candidates.append((int(match.group(1)), str(relation.get("createdAt") or ""), str(relation["subjectId"])))
        for _, _, message_id in sorted(candidates, reverse=True):
            message = self.client.get_record("Message", message_id) or {}
            summary = " ".join(str(message.get("summary") or "").split())
            if summary and message.get("messageKind") in SUMMARY_MESSAGE_KINDS and message.get("status") in (None, "", "active"):
                return summary
        return ""


def concept_catalogue(client: Any) -> tuple[dict[str, ConceptInfo], dict[str, dict[str, Any]]]:
    """(concept facts by lineage id and by id, SemanticNode row by hashtag) for the accepted, current SemanticNodes. When two kinds share a name the
    first node key in order owns the hashtag."""
    concepts: dict[str, ConceptInfo] = {}
    by_hashtag: dict[str, dict[str, Any]] = {}
    nodes = [row for row in client.list_records("SemanticNode") if row.get("versionState", CURRENT) == CURRENT and row.get("status") == ACCEPTED_NODE]
    for node in sorted(nodes, key=lambda row: str(row.get("nodeKey") or "")):
        hashtag = concept_hashtag(str(node.get("nodeKey") or ""))
        if not hashtag or hashtag in by_hashtag:
            continue
        info = ConceptInfo(
            name=str(node.get("displayName") or hashtag.removeprefix("#")), kind=str(node.get("nodeKind") or "concept"),
            description=str(node.get("description") or ""), hashtag=hashtag,
        )
        by_hashtag[hashtag] = node
        for key in (node.get("lineageId"), node.get("id")):
            if key:
                concepts[str(key)] = info
    return concepts, by_hashtag


def load_pack_lookups(client: Any, context: Mapping[str, Any], *, attachment_summary: AttachmentSummary | None = None,
                      vector_provider: Any = None) -> tuple[PackLookups, dict[str, dict[str, Any]]]:
    """(the lookups the pack builders are given, the concept nodes by hashtag). ``context`` is ``ideas.context.load_context``'s result.
    ``vector_provider`` (``get_vector`` / ``query_by_vector``) is what the cluster signal reads; None skips that signal."""
    concepts, concept_nodes = concept_catalogue(client)
    lookups = PackLookups(
        concepts=concepts, summaries=ReferenceSummaries(client, attachment_summary), mission=str(context.get("mission") or ""),
        policy=str(context.get("policy") or ""), allowed_sections=tuple(str(section["title"]) for section in context.get("sections") or ()),
        vector_provider=vector_provider,
    )
    return lookups, concept_nodes


@dataclass(frozen=True)
class SignalRun:
    """What one publication's run walks: the packs it offers (ranked, repeats held back), and whether single items are drafted."""

    inputs: SignalInputs
    packs: tuple[Pack, ...]
    packs_skipped_no_new_evidence: int
    single_items: bool
    concept_nodes: Mapping[str, Mapping[str, Any]]
    gate: Any = None

    def queue(self, candidates: list[MonitoredItem]) -> list[QueueEntry]:
        """The packs and the scored single-item candidates in one ordered queue. A candidate with no evidence is not in it."""
        return ordered_queue(self.packs, score_items(self.inputs, candidates) if self.single_items else [])

    def pack_records(self) -> list[dict[str, Any]]:
        return [
            {"packId": pack.pack_id, "signal": pack.signal_type, "anchor": pack.anchor, "correctedPValue": pack.signal["correctedPValue"],
             "surprise": pack.surprise, "dateBasis": pack.signal.get("dateBasis"), "acceptedReferences": len(pack.accepted_lineage_ids),
             "attempted": False, "ideas": 0}
            for pack in self.packs
        ]


def prepare_signal_run(
    client: Any, *, site: str, context: Mapping[str, Any], now: datetime, signals: tuple[str, ...] | None, single_items: bool, gate: Any = None,
    attachment_summary: AttachmentSummary | None = None, vector_provider: Any = None,
) -> SignalRun:
    """The one read pass and the packs of ``site``. ``signals`` is the closed set the publication asked for (None: every signal that has data)."""
    inputs = load_signal_inputs(client, site=site, now=now)
    lookups, concept_nodes = load_pack_lookups(client, context, attachment_summary=attachment_summary, vector_provider=vector_provider)
    built = [pack for pack in build_packs(inputs, lookups, now=now) if signals is None or pack.signal_type in signals]
    suppression = suppress_repeats(rank_packs(built), inputs.ideas)
    return SignalRun(
        inputs=inputs, packs=suppression.kept, packs_skipped_no_new_evidence=suppression.packsSkippedNoNewEvidence, single_items=single_items,
        concept_nodes=concept_nodes, gate=gate,
    )
