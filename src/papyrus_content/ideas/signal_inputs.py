"""Signal inputs: one read pass per publication that loads everything the idea signals need (epic PPY-2e9064, design sections 1.3, 2.2, 4 and 5.1).

``load_signal_inputs(client, site=..., now=...)`` reads through the existing GraphQL client, adds no field to any model, pages every query to
the end and applies no cap and no day window: the signals decide time ranges later. It returns one frozen ``SignalInputs``.

Fields of ``SignalInputs``:

* ``site``, ``loaded_at``: the publication key and the time of the read (ISO, from ``now``).
* ``messages``: ``SignalMessage`` tuple, oldest first. Only Messages written by people (role ``human``/``user``, active, not deleted, with text)
  count as human signal; each has ``message_id``, ``thread_id``, ``thread_kind``, ``anchor_key`` (the thread's ``primaryAnchorKey``),
  ``created_at``, ``author_kind`` (staff, reader, ...) and ``text``.
* ``votes``: ``HumanVote`` tuple for every Reference whose latest vote was cast by a person (``curationActorKind == "human"``, the only kind that
  trains), in every curation status. Each has ``reference_id``, ``lineage_id``, ``title``, ``url``, ``status``, ``voted_at``
  (``curationStatusUpdatedAt``), ``voted_by``, ``reason`` (``curationStatusReason``), ``reason_code``, ``section_id``, ``created_at`` (when the
  Reference arrived) and ``source_published_at`` (the two dates), and ``concept_ids``.
* ``concept_links``: ``ConceptLink`` tuple, one per current SemanticRelation from a Reference to a semanticNode with predicate ``mentions`` or
  ``related_to`` (``related_to`` is the human "relates to this concept" link): ``reference_lineage_id``, ``concept_id``, ``predicate``.
  Links of every Reference the pass read, so a signal can use them for votes, for pending context and for Messages anchored on a Reference.
* ``pending_context``: ``PendingReference`` tuple, pending References whose relevance verdict (``relevance_decision_is``) is positive, context
  only (never a vote). Each has ``reference_id``, ``lineage_id``, ``title``, ``url``, ``created_at``, ``source_published_at``, ``score`` and
  ``concept_ids``.
* ``published``: ``StoryRecord`` tuple of the published Items, for repeat suppression.
* ``ideas``: ``StoryRecord`` tuple of every existing generated idea, spiked ones included (``state`` is ``declined`` when spiked), with ``targets``.
  ``StoryRecord`` fields: ``story_id``, ``title``, ``summary``, ``section``, ``state``, ``date``, ``targets`` (JSON text).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..reference_vote import ACTION_FOR_STATUS, HUMAN
from .context import list_stories, story_entry
from .digest import CORPUS_PREFIX, collect_references, iso, relations_of, relevance_of
from .items import idea_rows
from .monitor_stories import POSITIVE_LABEL

CONCEPT_PREDICATES = ("mentions", "related_to")
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


def load_messages(client: Any) -> tuple[SignalMessage, ...]:
    messages: list[SignalMessage] = []
    for thread in client.list_records("MessageThread"):
        if not thread or not thread.get("id"):
            continue
        for row in list_thread_messages(client, str(thread["id"])):
            if is_human_message(row):
                messages.append(SignalMessage(
                    message_id=str(row["id"]), thread_id=str(thread["id"]), thread_kind=str(thread.get("threadKind") or ""),
                    anchor_key=str(thread.get("primaryAnchorKey") or ""), created_at=str(row.get("createdAt") or ""),
                    author_kind=str(row.get("authorKind") or "staff"), text=str(row["content"]).strip(),
                ))
    return tuple(sorted(messages, key=lambda message: (message.created_at, message.message_id)))


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


def story_record(entry: dict[str, Any], targets: str = "[]") -> StoryRecord:
    return StoryRecord(str(entry["id"]), entry["title"], entry.get("summary") or "", entry.get("section"), entry["state"], entry.get("date"), targets)


def load_signal_inputs(client: Any, *, site: str, now: datetime) -> SignalInputs:
    """One read pass for the publication ``site``: Messages, human votes, concept links, pending verdicts, published Items and ideas."""
    references = collect_references(client, [f"{CORPUS_PREFIX}{site}"], list(ACTION_FOR_STATUS), None)
    links: list[ConceptLink] = []
    votes: list[HumanVote] = []
    pending: list[PendingReference] = []
    for row in sorted(references, key=lambda entry: str(entry["id"])):
        lineage = str(row.get("lineageId") or row["id"])
        relations = relations_of(client, row)
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
            verdict = relevance_of(relations)
            if verdict is not None and verdict["label"] == (verdict.get("positiveLabel") or POSITIVE_LABEL):
                pending.append(PendingReference(score=verdict.get("score"), **common))
    stories = [story_entry(row) for row in list_stories(client) if row.get("versionState") == "current" and row.get("status") == "published"]
    ideas = [
        story_record({"id": row["id"], "title": row["title"], "summary": row["summary"], "state": row["state"], "date": (row.get("createdAt") or "")[:10] or None}, row["targets"])
        for row in idea_rows(client)
    ]
    return SignalInputs(
        site=site, loaded_at=iso(now), messages=load_messages(client), votes=tuple(votes), concept_links=tuple(links),
        pending_context=tuple(pending), published=tuple(story_record(entry) for entry in stories), ideas=tuple(ideas),
    )

