"""Signal inputs: one read pass per publication that loads everything the idea signals need (epic PPY-2e9064, design sections 1.3, 2.2, 4 and 5.1).

``load_signal_inputs(client, site=..., now=...)`` reads through the existing GraphQL client, adds no field to any model, pages every query to
the end and applies no cap and no day window: the signals decide time ranges later. It returns one frozen ``SignalInputs``.

Fields of ``SignalInputs``:

* ``site``, ``loaded_at``: the publication key and the time of the read (ISO, from ``now``).
* ``messages``: ``SignalMessage`` tuple, oldest first. Only Messages written by people (role ``human``/``user``, active, not deleted, with text)
  count as human signal (role is the test: ``human`` or ``user``; assistant, system and tool Messages are machines); each has ``message_id``, ``thread_id``, ``thread_kind``, ``anchor_key`` (the thread's ``primaryAnchorKey``),
  ``created_at``, ``author_kind`` (staff, reader, ...) and ``text``.
* ``votes``: ``HumanVote`` tuple for every Reference whose latest vote was cast by a person (``curationActorKind == "human"``, the only kind that
  trains), in every curation status. Each has ``reference_id``, ``lineage_id``, ``title``, ``url``, ``status``, ``voted_at``
  (``curationStatusUpdatedAt``), ``voted_by``, ``reason`` (``curationStatusReason``), ``reason_code``, ``section_id``, ``created_at`` (when the
  Reference arrived) and ``source_published_at`` (the two dates), and ``concept_ids``.
* Relations are read only for References that can matter: those with a human vote, pending ones (the verdict is a relation, so a pending
  Reference must be read to be judged) and those a Message thread is anchored on (``reference#<lineage>``). An accepted or rejected Reference with
  no human vote and no thread triggers no query. The reads run concurrently (``DEFAULT_WORKERS``, one client copy per thread).
* ``concept_links``: ``ConceptLink`` tuple, one per current SemanticRelation from a Reference to a semanticNode with predicate ``mentions`` or
  ``related_to`` (``related_to`` is the human "relates to this concept" link): ``reference_lineage_id``, ``concept_id``, ``predicate``.
  Links of every Reference the pass read, so a signal can use them for votes, for pending context and for Messages anchored on a Reference.
* ``edges``: ``ReferenceEdge`` tuple, one per current SemanticRelation between two References (predicate ``related_to``, ``cites``, ``supports`` or
  ``contradicts``) that touches a Reference the pass read: the relations are read by subject state key and by object state key (the concurrent reads
  of the other relations), so an edge is found from whichever end was read. Each has ``subject_lineage_id``, ``object_lineage_id``, ``predicate`` and
  ``created_at``. Suggested and rejected edges are not read (their state key is not ``current``).
* ``accepted``: ``AcceptedReference`` tuple, every accepted Reference of the publication whoever accepted it (a person or a machine rule), with the
  day it was accepted (``accepted_at``, falling back to the time it arrived), so the hub and cluster signals can compare recent arrivals with the
  site's own history. Their concept ids are those of the pass's concept links (a Reference the pass did not read has none).
* ``pending_context``: ``PendingReference`` tuple, pending References whose relevance verdict (``relevance_decision_is``) is positive, context
  only (never a vote). Each has ``reference_id``, ``lineage_id``, ``title``, ``url``, ``created_at``, ``source_published_at``, ``score`` and
  ``concept_ids``.
* ``published``: ``StoryRecord`` tuple of the published Items, for repeat suppression.
* ``ideas``: ``StoryRecord`` tuple of every existing generated idea, spiked ones included (``state`` is ``declined`` when spiked), with ``targets`` and ``evidence`` (the ``generated.evidence`` the idea recorded).
  ``StoryRecord`` fields: ``story_id``, ``title``, ``summary``, ``section``, ``state``, ``date``, ``targets`` and ``evidence`` (JSON text).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..reference_vote import ACTION_FOR_STATUS, HUMAN
from ..knowledge_snapshot.parallel import DEFAULT_WORKERS, map_with_clients
from .context import list_stories, story_entry
from .digest import CORPUS_PREFIX, collect_references, iso, relations_of, relevance_of
from .items import idea_rows
from .monitor_stories import POSITIVE_LABEL

CONCEPT_PREDICATES = ("mentions", "related_to")
EDGE_PREDICATES = ("related_to", "cites", "supports", "contradicts")
REFERENCE_KIND = "reference"
REFERENCE_ANCHOR_PREFIX = "reference#"
HUMAN_ROLES = ("human", "user")
MESSAGE_FIELDS = "id threadId sequenceNumber messageKind status role authorKind authorLabel content createdAt editedAt deletedAt"
MESSAGES_QUERY = f"""
query ListMessagesByThreadAndCreatedAt($threadId: ID!, $limit: Int, $nextToken: String) {{
  listMessagesByThreadAndCreatedAt(threadId: $threadId, sortDirection: ASC, limit: $limit, nextToken: $nextToken) {{
    items {{ {MESSAGE_FIELDS} }}
    nextToken
  }}
}}
"""


@dataclass(frozen=True)
class SignalMessage:
    message_id: str
    thread_id: str
    thread_kind: str
    anchor_key: str
    created_at: str
    author_kind: str
    text: str


@dataclass(frozen=True)
class ConceptLink:
    reference_lineage_id: str
    concept_id: str
    predicate: str


@dataclass(frozen=True)
class ReferenceEdge:
    subject_lineage_id: str
    object_lineage_id: str
    predicate: str
    created_at: str | None


@dataclass(frozen=True)
class AcceptedReference:
    reference_id: str
    lineage_id: str
    title: str
    url: str
    created_at: str | None
    source_published_at: str | None
    accepted_at: str | None
    accepted_by: str
    concept_ids: tuple[str, ...]

    @property
    def voted_at(self) -> str | None:
        return self.accepted_at or self.created_at


@dataclass(frozen=True)
class HumanVote:
    reference_id: str
    lineage_id: str
    title: str
    url: str
    status: str
    voted_at: str | None
    voted_by: str | None
    reason: str | None
    reason_code: str | None
    section_id: str | None
    created_at: str | None
    source_published_at: str | None
    concept_ids: tuple[str, ...]


@dataclass(frozen=True)
class PendingReference:
    reference_id: str
    lineage_id: str
    title: str
    url: str
    created_at: str | None
    source_published_at: str | None
    score: float | None
    concept_ids: tuple[str, ...]


@dataclass(frozen=True)
class StoryRecord:
    story_id: str
    title: str
    summary: str
    section: str | None
    state: str
    date: str | None
    targets: str
    evidence: str = "{}"


@dataclass(frozen=True)
class SignalInputs:
    site: str
    loaded_at: str
    messages: tuple[SignalMessage, ...]
    votes: tuple[HumanVote, ...]
    concept_links: tuple[ConceptLink, ...]
    pending_context: tuple[PendingReference, ...]
    published: tuple[StoryRecord, ...]
    ideas: tuple[StoryRecord, ...]
    edges: tuple[ReferenceEdge, ...] = ()
    accepted: tuple[AcceptedReference, ...] = ()


def independent_copy(client: Any) -> Any:
    """A copy of the client with a connection of its own, for a worker thread (the pattern of monitor_stories.collect_monitored_items)."""
    duplicate = copy.copy(client)
    if hasattr(duplicate, "_connection"):
        duplicate._connection = None
    return duplicate


def is_human_message(row: dict[str, Any]) -> bool:
    return (
        row.get("status") == "active"
        and not row.get("deletedAt")
        and str(row.get("role") or "") in HUMAN_ROLES
        and bool(str(row.get("content") or "").strip())
    )


def list_thread_messages(client: Any, thread_id: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    token = None
    while True:
        page = client.graphql(MESSAGES_QUERY, {"threadId": thread_id, "limit": 100, "nextToken": token}).get("listMessagesByThreadAndCreatedAt") or {}
        found.extend(row for row in page.get("items") or [] if row)
        token = page.get("nextToken")
        if not token:
            return found


def load_messages(client: Any) -> tuple[tuple[SignalMessage, ...], set[str]]:
    """(the human Messages, the lineage ids of the References any thread is anchored on)."""
    messages: list[SignalMessage] = []
    anchored: set[str] = set()
    for thread in client.list_records("MessageThread"):
        if not thread or not thread.get("id"):
            continue
        anchor = str(thread.get("primaryAnchorKey") or "")
        if anchor.startswith(REFERENCE_ANCHOR_PREFIX):
            anchored.add(anchor.removeprefix(REFERENCE_ANCHOR_PREFIX))
        for row in list_thread_messages(client, str(thread["id"])):
            if is_human_message(row):
                messages.append(SignalMessage(
                    message_id=str(row["id"]), thread_id=str(thread["id"]), thread_kind=str(thread.get("threadKind") or ""),
                    anchor_key=str(thread.get("primaryAnchorKey") or ""), created_at=str(row.get("createdAt") or ""),
                    author_kind=str(row.get("authorKind") or "staff"), text=str(row["content"]).strip(),
                ))
    return tuple(sorted(messages, key=lambda message: (message.created_at, message.message_id))), anchored


def concept_links_of(lineage: str, relations: list[dict[str, Any]]) -> list[ConceptLink]:
    found = {}
    for relation in relations:
        concept = str(relation.get("objectLineageId") or relation.get("objectId") or "")
        if (
            relation.get("relationState", "current") == "current"
            and relation.get("predicate") in CONCEPT_PREDICATES
            and relation.get("objectKind") == "semanticNode"
            and concept
        ):
            found[(concept, relation["predicate"])] = ConceptLink(lineage, concept, relation["predicate"])
    return [found[key] for key in sorted(found)]


def edges_of(relations: list[dict[str, Any]]) -> list[ReferenceEdge]:
    """The current Reference-to-Reference edges among ``relations`` (read from either end of the edge)."""
    return [
        ReferenceEdge(str(relation["subjectLineageId"]), str(relation["objectLineageId"]), str(relation["predicate"]), relation.get("createdAt"))
        for relation in relations
        if relation.get("relationState", "current") == "current" and relation.get("predicate") in EDGE_PREDICATES
        and relation.get("subjectKind") == REFERENCE_KIND and relation.get("objectKind") == REFERENCE_KIND
        and relation.get("subjectLineageId") and relation.get("objectLineageId")
    ]


def objects_of(reader: Any, row: dict[str, Any]) -> list[dict[str, Any]]:
    lineage = row.get("lineageId")
    return list(reader.list_semantic_relations_by_object_state(f"{REFERENCE_ANCHOR_PREFIX}{lineage}#current")) if lineage else []


def story_record(entry: dict[str, Any], targets: str = "[]", evidence: str = "{}") -> StoryRecord:
    return StoryRecord(str(entry["id"]), entry["title"], entry.get("summary") or "", entry.get("section"), entry["state"], entry.get("date"), targets, evidence)


def pending_of(row: dict[str, Any], relations: list[dict[str, Any]], common: dict[str, Any]) -> PendingReference | None:
    """A pending Reference with a positive verdict, as context: the row's prediction when it has one (at or above even odds), else the verdict
    relation when its relations were read."""
    probability = predicted_probability(row)
    if probability is not None:
        return PendingReference(score=probability, **common) if probability >= 0.5 else None
    verdict = relevance_of(relations)
    if verdict is not None and verdict["label"] == (verdict.get("positiveLabel") or POSITIVE_LABEL):
        return PendingReference(score=verdict.get("score"), **common)
    return None


def predicted_probability(row: dict[str, Any]) -> float | None:
    """The relevance Cyclotron's original verdict as the Reference row stores it (``predictedAcceptProbability``), or None."""
    value = row.get("predictedAcceptProbability")
    return float(value) if isinstance(value, (int, float)) else None


def load_signal_inputs(
    client: Any, *, site: str, now: datetime, workers: int = DEFAULT_WORKERS, client_factory: Callable[[], Any] | None = None,
    out_of_time: Callable[[], bool] = lambda: False,
) -> SignalInputs:
    """One read pass for the publication ``site``: Messages, human votes, concept links, pending verdicts, published Items and ideas.

    Relations are read for every Reference a person voted on or a thread is anchored on. A pending Reference's verdict is the prediction on its
    row, so a large backlog needs no read for it; its relations (concept links, edges) are read highest prediction first, a chunk at a time, while
    ``out_of_time`` allows: a site with thousands of pending References spends its time share on the most likely ones, not on all of them."""
    references = sorted(collect_references(client, [f"{CORPUS_PREFIX}{site}"], list(ACTION_FOR_STATUS), None), key=lambda entry: str(entry["id"]))
    messages, anchored = load_messages(client)
    is_pending = lambda row: str(row.get("curationStatus") or "pending") == "pending"  # noqa: E731
    core = [row for row in references if row.get("curationActorKind") == HUMAN or str(row.get("lineageId") or row["id"]) in anchored]
    core_ids = {row["id"] for row in core}
    backlog = sorted((row for row in references if is_pending(row) and row["id"] not in core_ids),
                     key=lambda row: (-(predicted_probability(row) or 0.0), str(row["id"])))
    factory = client_factory or (lambda: independent_copy(client))

    def read_both(rows: list[dict[str, Any]]) -> tuple[list, list]:
        return (map_with_clients(rows, lambda reader, row: relations_of(reader, row), client=client, client_factory=factory, workers=workers),
                map_with_clients(rows, lambda reader, row: objects_of(reader, row), client=client, client_factory=factory, workers=workers))

    needed = list(core)
    read, incoming = read_both(core)
    chunk = max(1, workers) * 4
    for start in range(0, len(backlog), chunk):
        if out_of_time():
            break
        rows = backlog[start:start + chunk]
        more_read, more_incoming = read_both(rows)
        needed.extend(rows)
        read.extend(more_read)
        incoming.extend(more_incoming)
    unread_pending = backlog[len(needed) - len(core):]
    relations_by_id = {row["id"]: relations for row, relations in zip(needed, read)}
    found_edges: dict[tuple[str, str, str], ReferenceEdge] = {}
    for row, objects in zip(needed, incoming):
        for edge in [*edges_of(relations_by_id[row["id"]]), *edges_of(objects)]:
            found_edges.setdefault((edge.subject_lineage_id, edge.object_lineage_id, edge.predicate), edge)
    links: list[ConceptLink] = []
    votes: list[HumanVote] = []
    pending: list[PendingReference] = []
    for row in needed:
        lineage = str(row.get("lineageId") or row["id"])
        relations = relations_by_id[row["id"]]
        reference_links = concept_links_of(lineage, relations)
        links.extend(reference_links)
        concepts = tuple(sorted({link.concept_id for link in reference_links}))
        status = str(row.get("curationStatus") or "pending")
        common = {
            "reference_id": str(row["id"]), "lineage_id": lineage, "title": str(row.get("title") or row.get("sourceUri") or "").strip(),
            "url": str(row.get("sourceUri") or ""), "created_at": row.get("createdAt"), "source_published_at": row.get("sourcePublishedAt") or None,
            "concept_ids": concepts,
        }
        if row.get("curationActorKind") == HUMAN:
            votes.append(HumanVote(
                status=status, voted_at=row.get("curationStatusUpdatedAt"), voted_by=row.get("curationStatusUpdatedBy"),
                reason=(row.get("curationStatusReason") or "").strip() or None, reason_code=row.get("curationReasonCode") or None,
                section_id=row.get("curationSectionId") or None, **common,
            ))
        elif status == "pending":
            pending_reference = pending_of(row, relations, common)
            if pending_reference is not None:
                pending.append(pending_reference)
    for row in unread_pending:
        pending_reference = pending_of(row, [], {
            "reference_id": str(row["id"]), "lineage_id": str(row.get("lineageId") or row["id"]), "title": str(row.get("title") or row.get("sourceUri") or "").strip(),
            "url": str(row.get("sourceUri") or ""), "created_at": row.get("createdAt"), "source_published_at": row.get("sourcePublishedAt") or None, "concept_ids": (),
        })
        if pending_reference is not None:
            pending.append(pending_reference)
    concepts_by_lineage: dict[str, set[str]] = {}
    for link in links:
        concepts_by_lineage.setdefault(link.reference_lineage_id, set()).add(link.concept_id)
    accepted = [
        AcceptedReference(
            reference_id=str(row["id"]), lineage_id=str(row.get("lineageId") or row["id"]), title=str(row.get("title") or row.get("sourceUri") or "").strip(),
            url=str(row.get("sourceUri") or ""), created_at=row.get("createdAt"), source_published_at=row.get("sourcePublishedAt") or None,
            accepted_at=row.get("curationStatusUpdatedAt") or row.get("createdAt"), accepted_by="human" if row.get("curationActorKind") == HUMAN else "machine",
            concept_ids=tuple(sorted(concepts_by_lineage.get(str(row.get("lineageId") or row["id"]), ()))),
        )
        for row in references if str(row.get("curationStatus") or "pending") == "accepted"
    ]
    stories = [story_entry(row) for row in list_stories(client) if row.get("versionState") == "current" and row.get("status") == "published"]
    ideas = [
        story_record({"id": row["id"], "title": row["title"], "summary": row["summary"], "state": row["state"], "date": (row.get("createdAt") or "")[:10] or None}, row["targets"], row.get("evidence") or "{}")
        for row in idea_rows(client)
    ]
    return SignalInputs(
        site=site, loaded_at=iso(now), messages=messages, votes=tuple(votes), concept_links=tuple(links),
        pending_context=tuple(pending), published=tuple(story_record(entry) for entry in stories), ideas=tuple(ideas),
        edges=tuple(sorted(found_edges.values(), key=lambda edge: (edge.subject_lineage_id, edge.object_lineage_id, edge.predicate))), accepted=tuple(accepted),
    )

