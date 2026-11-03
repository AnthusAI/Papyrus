"""Connections: what the newsroom already knows about a Reference, and the deterministic rules that make an idea more than a summary of it (tickets
PPY-3ccdcb and its sub-tasks; design docs/idea-context-packs.md, "More than a summary").

An idea that only restates its source is not filed. The single-item writer is therefore given the newsroom's own knowledge of the Reference, as
handles it must cite beside the source (``I1``):

* ``E1``, kind ``acceptReason``: the words an editor wrote when they accepted the Reference (``curationStatusReason``, only when a person voted).
  It is direction for the writer: it says what to look for, it is never reported in the story and it grounds no fact.
* ``M1..``, kind ``message``: human Messages in threads anchored on the Reference.
* ``R1..``, kind ``neighbour``: another accepted Reference linked to it: a confirmed link (a person or a rule made it), or a suggested one whose
  similarity is at least the site's median nearest-neighbour similarity (the cut the cluster signal uses: ``context_packs.typical_neighbour_pairs``).
  A neighbour must have a summary (or an editors' explanation) beyond its title, so the writer never leans on a title alone.
* ``X1..``, kind ``editorsExplanation``: the words an editor wrote on the link to a neighbour (``ReferenceEdge.explanation``, PR #1034; read with ``getattr``, so a
  build whose edges have no such field works the same without them). Also direction, not content.

``Connections.clears_the_bar`` decides before any model call whether there is anything to add: some connection, and for a Reference whose page could not
be read (no page text and no real summary) a Message or a neighbour, because an accept reason alone is no reason to describe what cannot be read.
``standard_problems`` is the check after the call: the dek rests on a connection, at least one body sentence does, the connecting sentence shares a content
word with what it cites, no sentence talks about how the story came to be, no "trend" is claimed without counts. Nothing here asks a model; whether the draft says
anything is ``point_check``'s question.

There is one standard, "more than a summary". A site's old ``monitorStories.minimumStandard`` setting is retired (``RETIRED_POLICY_FIELDS`` in
``monitoring_stories.py``): a stored config that still carries it loads, and the value is ignored.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..reference_links import REFERENCE_LINK_FEED_KEY
from ..reference_vote import HUMAN
from . import dedupe

MORE_THAN_SUMMARY = "more-than-summary"   # the one standard; recorded on each idea's evidence

SOURCE_HANDLE = "I1"
ACCEPT_REASON, MESSAGE, NEIGHBOUR, EDITORS_EXPLANATION = "acceptReason", "message", "neighbour", "editorsExplanation"
#: Only a variation writer is shown these two (``with_options``, ideas/variations.py): another Story and a concept the Reference carries. The single-item writer never is.
STORY_OPTION, CONCEPT_OPTION = "story", "concept"
KINDS = (ACCEPT_REASON, MESSAGE, NEIGHBOUR, EDITORS_EXPLANATION, STORY_OPTION, CONCEPT_OPTION)
PREFIX = {ACCEPT_REASON: "E", MESSAGE: "M", NEIGHBOUR: "R", EDITORS_EXPLANATION: "X", STORY_OPTION: "S", CONCEPT_OPTION: "C"}
KIND_OF_PREFIX = {prefix: kind for kind, prefix in PREFIX.items()}
HANDLE = re.compile(r"^([EMRXSC])(\d+)$")
#: How the story came to be, not what it is about. Phrases, not single words: "similarity", "monitor" and "knowledge base" are also subjects the sites cover.
INTERNAL_WORDING = re.compile(
    r"\b(the editors\b|editors'|editors? (accepted|chose|picked|said|noted|see|saw)|accepted (it|this|the item|the reference)|why (it|this) was accepted|by similarity|similarity score|"
    r"(suggested|confirmed) (link|reference)|related reference|this reference\b|the newsroom|newsroom's|the monitor\b|monitor (found|marked|flagged))",
    re.IGNORECASE,
)
TREND_CLAIM = re.compile(r"\b(trends?|trending|rising|surging|on the rise)\b")   # lower case only: "Trend Micro" is a name, not a claim
EMAIL = re.compile(r"[^@\s:]+@[^@\s:]+\.[^@\s:]+")
CONFIRMED, SUGGESTED = "confirmed", "suggested"

NOTHING_TO_ADD = "nothing_to_add"
ONLY_THE_SOURCE_CITED = "only_the_source_cited"
DEK_WITHOUT_CONNECTION = "dek_without_connection"
CONNECTION_UNGROUNDED = "connection_ungrounded"
INTERNAL_WORDING_USED = "internal_wording"
MESSAGE_WITHOUT_REFERENCE = "message_cited_without_reference"
TREND_WITHOUT_SIGNAL = "trend_claim_without_signal"
DESCRIBES_UNREAD_PAGE = "describes_unread_page"


def scrubbed(text: Any) -> str:
    """Editor words on one line with any address replaced (the same rule as ``priming_export.scrubbed``, which the router zip does not carry)."""
    return " ".join(EMAIL.sub("[address removed]", str(text or "")).split())


def readable(view: Mapping[str, Any]) -> bool:
    """The page could be read, or there is a real summary beyond the title. Stored facts alone (likes, downloads) describe nothing."""
    return "page_text" in view or "summary" in view


def content_tokens(text: str) -> set[str]:
    """The words of ``text`` that carry meaning: lower-cased, plural endings folded, common words and bare numbers left out."""
    return {term for term in dedupe.terms(text) if " " not in term and not term.isdigit()}


# --- the connections of one Reference ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Neighbour:
    lineage_id: str
    title: str
    url: str
    published: str | None
    summary: str
    provenance: str   # confirmed | suggested
    similarity: float | None = None
    explanation: str | None = None


@dataclass(frozen=True)
class StoryOption:
    """Another Story (a current Item that is not an idea or spiked) the Reference could be connected to: it rests on a related Reference, or carries a concept the Reference has."""

    lineage_id: str
    title: str
    deck: str
    stage: str | None
    via: str   # how it is connected, in plain words, for the editor


@dataclass(frozen=True)
class ConceptOption:
    """A concept the Reference carries: tagged with it by an editor or by a rule."""

    lineage_id: str
    name: str
    hashtag: str
    description: str
    by_editor: bool = False
    explanation: str | None = None


@dataclass(frozen=True)
class Connection:
    handle: str
    kind: str
    row: Mapping[str, Any]   # what the writer sees; the handle is its first key
    grounding: str           # the words a sentence resting on this handle shares at least one content word with
    reference: Neighbour | None = None
    about: str | None = None   # for an editors' explanation, the neighbour handle it explains
    story: StoryOption | None = None
    concept: ConceptOption | None = None

    @property
    def label(self) -> str:
        """What the idea records in ``generated.evidence.connections``."""
        if self.kind == ACCEPT_REASON:
            return ACCEPT_REASON
        return f"{self.kind}:{self.about if self.kind == EDITORS_EXPLANATION else self.handle}"


@dataclass(frozen=True)
class Connections:
    entries: tuple[Connection, ...] = ()
    found: Mapping[str, Any] = field(default_factory=dict)   # what exists, for the run record and the curation flag
    rating: int | None = None   # the editors' stars for the source: direction for the writer (``editor_rating``), no handle, grounds nothing, not a connection that clears the bar

    def kinds(self) -> set[str]:
        return {entry.kind for entry in self.entries}

    def by_handle(self) -> dict[str, Connection]:
        return {entry.handle: entry for entry in self.entries}

    def view(self) -> list[dict[str, Any]]:
        return [dict(entry.row) for entry in self.entries]

    def clears_the_bar(self, page_readable: bool) -> bool:
        """Something to add: any connection; and when the page could not be read, a Message or a neighbour (an accept reason alone is not enough)."""
        if page_readable:
            return bool(self.entries)
        return bool(self.kinds() & {MESSAGE, NEIGHBOUR})

    def labels_of(self, handles: Iterable[str]) -> list[str]:
        """The evidence labels of the cited connections, in the order the connections are numbered (E, M, R, X)."""
        cited = set(handles)
        return [entry.label for entry in self.entries if entry.handle in cited]


def build_connections(
    accept_reason: str | None, messages: Sequence[Mapping[str, Any]], neighbours: Sequence[Neighbour], *, suggested_links: int = 0, stars: int | None = None,
) -> Connections:
    """The handles for one Reference: ``E1``, then ``M1..`` (oldest first), ``R1..`` (confirmed before suggested, closest first) and ``X1..`` for the
    neighbours an editor explained."""
    entries: list[Connection] = []
    reason = scrubbed(accept_reason)
    if reason:
        entries.append(Connection("E1", ACCEPT_REASON, {
            "handle": "E1", "kind": ACCEPT_REASON, "writtenBy": "editor", "text": reason,
            "note": "The editors' reason for accepting this Reference. It tells you what to look for: it is not a fact, and it is not to be reported.",
        }, reason))
    for message in messages:
        text = scrubbed(message.get("text"))
        if text:
            handle = f"M{sum(entry.kind == MESSAGE for entry in entries) + 1}"
            entries.append(Connection(handle, MESSAGE, {
                "handle": handle, "kind": MESSAGE, "author": message.get("author"), "date": message.get("date"), "text": text,
            }, text))
    ordered = sorted(neighbours, key=lambda row: (row.provenance != CONFIRMED, -(row.similarity or 0.0), row.lineage_id))
    explained: list[tuple[str, Neighbour]] = []
    for number, neighbour in enumerate(ordered, start=1):
        handle = f"R{number}"
        row = {
            "handle": handle, "kind": NEIGHBOUR, "title": neighbour.title, "url": neighbour.url, "published": neighbour.published, "summary": neighbour.summary,
            "link": neighbour.provenance, **({"similarity": round(neighbour.similarity, 3)} if neighbour.similarity is not None else {}),
        }
        entries.append(Connection(handle, NEIGHBOUR, {key: value for key, value in row.items() if value not in (None, "")}, f"{neighbour.title} {neighbour.summary}", reference=neighbour))
        if neighbour.explanation:
            explained.append((handle, neighbour))
    for number, (about, neighbour) in enumerate(explained, start=1):
        handle = f"X{number}"
        entries.append(Connection(handle, EDITORS_EXPLANATION, {
            "handle": handle, "kind": EDITORS_EXPLANATION, "about": about, "editorsExplanation": {"writtenBy": "editor", "text": neighbour.explanation},
            "note": "What an editor wrote on the link between the source and the related Reference. It tells you what to look for: it is not a fact, and it is not to be reported.",
        }, str(neighbour.explanation), about=about))
    found = {
        "acceptReason": bool(reason), "messages": sum(entry.kind == MESSAGE for entry in entries), "neighbours": len(ordered),
        "editorsExplanations": len(explained), "suggestedLinks": suggested_links, **({"stars": stars} if stars is not None else {}),
    }
    return Connections(tuple(entries), found, stars)


def with_options(connections: Connections, stories: Sequence[StoryOption] = (), concepts: Sequence[ConceptOption] = ()) -> Connections:
    """The same connections plus the other Stories (``S1..``) and concepts (``C1..``) the Reference could be connected to, for the variation writer only. A
    Story or a concept grounds no number or date: a figure must come from a source. An editor's explanation of a concept tag is direction, like ``X``."""
    entries = list(connections.entries)
    for number, option in enumerate(stories, start=1):
        handle = f"S{number}"
        entries.append(Connection(handle, STORY_OPTION, {
            key: value for key, value in {"handle": handle, "kind": STORY_OPTION, "title": option.title, "deck": option.deck, "stage": option.stage, "link": option.via}.items() if value
        }, f"{option.title} {option.deck}", story=option))
    for number, option in enumerate(concepts, start=1):
        handle = f"C{number}"
        row = {"handle": handle, "kind": CONCEPT_OPTION, "name": option.name, "hashtag": option.hashtag, "description": option.description,
               "editorsExplanation": {"writtenBy": "editor", "text": option.explanation} if option.explanation else None}
        entries.append(Connection(handle, CONCEPT_OPTION, {key: value for key, value in row.items() if value}, f"{option.name} {option.description} {option.explanation or ''}", concept=option))
    return Connections(tuple(entries), connections.found, connections.rating)


def citation_views(connections: Connections) -> tuple[dict[str, str], dict[str, tuple[set[str], set[str]]]]:
    """(handle to the id the citation check records, the numbers and dates each handle may ground). The editors' words and Messages ground none: a
    number must come from a source, never from an opinion."""
    from . import trends

    ids: dict[str, str] = {}
    views: dict[str, tuple[set[str], set[str]]] = {}
    for entry in connections.entries:
        identifier = f"{entry.kind}:{entry.handle}"
        ids[entry.handle] = identifier
        views[identifier] = trends.facts_in({key: value for key, value in entry.row.items() if key != "handle"}) if entry.kind == NEIGHBOUR else (set(), set())
    return ids, views


# --- the rules after the model's answer ----------------------------------------------------------------------------------------


def is_connection(handle: str) -> bool:
    return bool(HANDLE.match(handle))


def standard_problems(sentences: Sequence[Mapping[str, Any]], connections: Connections, *, page_readable: bool) -> list[dict[str, str]]:
    """Why a checked draft is only a summary, as problems in the shape of ``trends._problem``. ``sentences`` are ``{"where", "role", "text", "handles"}``
    with role ``headline``, ``dek`` or ``body`` and the raw handles each cites."""
    from . import trends

    known = connections.by_handle()
    problems: list[dict[str, str]] = []
    connecting, grounded_any = [], False
    for sentence in sentences:
        where, role, text = sentence["where"], sentence["role"], sentence["text"]
        cited = [handle for handle in sentence["handles"] if handle in known]
        kinds = {known[handle].kind for handle in cited}
        if INTERNAL_WORDING.search(text):
            problems.append(trends._problem(where, text, INTERNAL_WORDING_USED))
        if MESSAGE in kinds and not ({SOURCE_HANDLE} & set(sentence["handles"]) or NEIGHBOUR in kinds):
            problems.append(trends._problem(where, text, MESSAGE_WITHOUT_REFERENCE))
        if TREND_CLAIM.search(text):
            problems.append(trends._problem(where, text, TREND_WITHOUT_SIGNAL))
        if role == "dek" and not cited:
            problems.append(trends._problem(where, text, DEK_WITHOUT_CONNECTION))
        if role == "body":
            if cited:
                connecting.append(sentence)
                words = content_tokens(text)
                grounded_any = grounded_any or any(words & content_tokens(known[handle].grounding) for handle in cited)
            elif not page_readable:
                problems.append(trends._problem(where, text, DESCRIBES_UNREAD_PAGE))
    if not connecting:
        problems.append(trends._problem("body", "", ONLY_THE_SOURCE_CITED))
    elif not grounded_any:
        problems.append(trends._problem("body", connecting[0]["text"], CONNECTION_UNGROUNDED))
    return problems


# --- reading the newsroom --------------------------------------------------------------------------------------------------


def median(values: Iterable[float]) -> float | None:
    ordered = sorted(values)
    return statistics.median(ordered) if ordered else None


class Knowledge:
    """What a run knows about the Reference it is writing on: the editors' Messages, the links between References and the summaries. Everything is read
    once and lazily; a read that fails is recorded in ``errors`` and treated as empty, so a role without a grant never stops a run.

    ``summary_of(lineage)`` is ``signal_queue.ReferenceSummaries``; ``reference_of(lineage)`` the current Reference row (or None); both are injected so this
    module reads nothing itself except the link feed and the Messages."""

    def __init__(self, client: Any, *, summary_of: Callable[[str], str], reference_of: Callable[[str], Mapping[str, Any] | None], inputs: Any = None) -> None:
        self.client = client
        self.summary_of = summary_of
        self.reference_of = reference_of
        self.inputs = inputs
        self.errors: dict[str, str] = {}
        self._messages: dict[str, list[dict[str, Any]]] | None = None
        self._confirmed: dict[str, list[tuple[str, str | None]]] | None = None
        self._suggested: dict[str, list[tuple[str, float]]] | None = None
        self.neighbour_cut: float | None = None
        self._catalogue: dict[str, Any] | None = None

    def concept_catalogue_by_lineage(self) -> dict[str, Any]:
        """The accepted concepts by lineage id and id (``signal_queue.concept_catalogue``), read once; a read that fails is recorded and means no concepts."""
        if self._catalogue is None:
            try:
                from .signal_queue import concept_catalogue

                self._catalogue = concept_catalogue(self.client)[0]
            except Exception as error:  # noqa: BLE001 - a role that cannot list concepts must not stop the run
                self.errors["concepts"] = type(error).__name__
                self._catalogue = {}
        return self._catalogue

    # Messages

    def messages_of(self, lineage_id: str) -> list[dict[str, Any]]:
        if self._messages is None:
            self._messages = {}
            try:
                if self.inputs is not None:
                    rows = self.inputs.messages
                else:
                    from .signal_inputs import load_messages

                    rows = load_messages(self.client)[0]
                for message in rows:
                    if message.anchor_key.startswith("reference#"):
                        self._messages.setdefault(message.anchor_key.removeprefix("reference#"), []).append(
                            {"author": message.author_kind, "date": (message.created_at or "")[:10] or None, "text": message.text})
            except Exception as error:  # noqa: BLE001 - a role that cannot list threads must not stop the run
                self.errors["messages"] = type(error).__name__
        return self._messages.get(lineage_id, [])

    # Links

    def load_links(self) -> None:
        if self._confirmed is not None:
            return
        self._confirmed, self._suggested = {}, {}
        try:
            rows = list(self.client.list_by_index("semanticRelationsByNewsroomFeedAndCreatedAt", REFERENCE_LINK_FEED_KEY))
        except Exception as error:  # noqa: BLE001
            self.errors["links"] = type(error).__name__
            return
        from .signal_inputs import edges_of

        for edge in edges_of([row for row in rows if row.get("relationState", "current") == "current"]):
            explanation = getattr(edge, "explanation", None)   # PR #1034 puts it on the edge; a build without it has none
            self._confirmed.setdefault(edge.subject_lineage_id, []).append((edge.object_lineage_id, explanation))
            self._confirmed.setdefault(edge.object_lineage_id, []).append((edge.subject_lineage_id, explanation))
        for row in rows:
            if row.get("relationState") != SUGGESTED or row.get("predicate") != "related_to" or row.get("subjectKind") != "reference" or row.get("objectKind") != "reference":
                continue
            first, second, score = row.get("subjectLineageId"), row.get("objectLineageId"), row.get("score")
            if first and second and score is not None:
                self._suggested.setdefault(str(first), []).append((str(second), float(score)))
                self._suggested.setdefault(str(second), []).append((str(first), float(score)))
        # The site's typical nearest neighbour: the median, over the References that have a suggestion, of the similarity to the closest one.
        self.neighbour_cut = median(max(similarity for _, similarity in row) for row in self._suggested.values())

    def neighbours_of(self, lineage_id: str) -> tuple[list[Neighbour], int]:
        """(the usable neighbours, how many suggestions touch the Reference at all)."""
        self.load_links()
        found: dict[str, Neighbour] = {}
        for other, explanation in self._confirmed.get(lineage_id, []):
            row = self.neighbour(other, CONFIRMED, None, explanation)
            if row is not None and (other not in found or (explanation and not found[other].explanation)):
                found[other] = row
        suggestions = self._suggested.get(lineage_id, [])
        for other, similarity in suggestions:
            if other in found or (self.neighbour_cut is not None and similarity < self.neighbour_cut):
                continue
            row = self.neighbour(other, SUGGESTED, similarity, None)
            if row is not None:
                found[other] = row
        return list(found.values()), len(suggestions)

    def neighbour(self, lineage_id: str, provenance: str, similarity: float | None, explanation: str | None) -> Neighbour | None:
        row = self.reference_of(lineage_id)
        if not row or row.get("curationStatus") != "accepted":
            return None
        summary = " ".join(str(self.summary_of(lineage_id) or "").split())
        explanation = scrubbed(explanation) or None
        if not summary and not explanation:
            return None   # a title alone is nothing to write from
        return Neighbour(
            lineage_id, str(row.get("title") or row.get("sourceUri") or lineage_id).strip(), str(row.get("sourceUri") or ""),
            (str(row.get("sourcePublishedAt") or "")[:10] or None), summary, provenance, similarity, explanation,
        )

    def connections_for(self, item: Any) -> Connections:
        """The connections of a ``MonitoredItem``."""
        reason = item.accept_reason if getattr(item, "accepted_by_human", False) else None
        neighbours, suggested = self.neighbours_of(item.lineage_id)
        return build_connections(reason, self.messages_of(item.lineage_id), neighbours, suggested_links=suggested, stars=getattr(item, "stars", None))


# --- the other ways to connect a Reference (variations: ideas/variations.py) -----------------------------------------------------------

#: A Story that is still an idea, or was declined, is not something to connect another to.
NOT_A_STORY_STAGES = frozenset({"idea", "spiked"})
CONCEPT_PREDICATES = ("mentions", "related_to")


def _metadata_of(relation: Mapping[str, Any]) -> dict[str, Any]:
    import json

    raw = relation.get("metadata")
    try:
        found = json.loads(raw or "{}") if isinstance(raw, str) else dict(raw or {})
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def concept_options(client: Any, lineage_id: str, catalogue: Mapping[str, Any]) -> list[ConceptOption]:
    """The concepts a Reference carries (a current ``mentions`` or ``related_to`` link to an accepted concept the catalogue knows), editors' tags first. A concept the
    catalogue does not know has no name to show and is left out. ``catalogue`` is ``signal_queue.concept_catalogue``'s first result."""
    from .signal_inputs import explanation_of

    found: dict[str, ConceptOption] = {}
    for relation in client.list_semantic_relations_by_subject_state(f"reference#{lineage_id}#current"):
        concept = str(relation.get("objectLineageId") or relation.get("objectId") or "")
        info = catalogue.get(concept)
        if (relation.get("relationState", "current") != "current" or relation.get("predicate") not in CONCEPT_PREDICATES or relation.get("objectKind") != "semanticNode"
                or info is None):
            continue
        by_editor = relation.get("predicate") == "related_to" and _metadata_of(relation).get("provenance") == "human"
        explanation = explanation_of(relation) if relation.get("predicate") == "related_to" else None
        earlier = found.get(concept)
        if earlier is None or (by_editor and not earlier.by_editor):
            found[concept] = ConceptOption(concept, info.name, info.hashtag, info.description, by_editor, explanation or (earlier.explanation if earlier else None))
    return sorted(found.values(), key=lambda option: (not option.by_editor, option.hashtag))


def story_options(
    client: Any, *, neighbours: Sequence[Neighbour], concepts: Sequence[ConceptOption], exclude: Iterable[str] = (), read_concept_stories: bool = True,
) -> list[StoryOption]:
    """The other Stories this Reference could be connected to: a Story that rests on a related Reference (a ``uses_evidence`` link), and a Story tagged with a
    concept the Reference carries. A Story still at the idea stage or spiked is not one. Each Story is found once, by the first way that reaches it. A read that
    fails leaves that way out. ``read_concept_stories`` False (the run is out of time) skips the concept reads, which page through everything tagged with the concept."""
    from ..story_reporting import current_story_version

    skip = set(exclude)
    found: dict[str, StoryOption] = {}

    def add(lineage: str, via: str) -> None:
        if lineage in skip or lineage in found:
            return
        try:
            row = current_story_version(client, lineage)
        except Exception:  # noqa: BLE001 - a Story that cannot be read is not an option
            return
        title = str(row.get("headline") or row.get("title") or "").strip()
        if not title or row.get("stage") in NOT_A_STORY_STAGES:
            return
        found[lineage] = StoryOption(lineage, title, " ".join(str(row.get("deck") or "").split()), row.get("stage"), via)

    ways = [(f"reference#{neighbour.lineage_id}#current", "uses_evidence", f"Rests on {neighbour.title}") for neighbour in neighbours]
    if read_concept_stories:
        ways += [(f"semanticNode#{concept.lineage_id}#current", "related_to", f"Tagged {concept.hashtag}") for concept in concepts]
    for key, predicate, via in ways:
        try:
            relations = client.list_semantic_relations_by_object_state(key)
        except Exception:  # noqa: BLE001
            continue
        for relation in relations:
            if relation.get("predicate") == predicate and relation.get("subjectKind") == "item" and relation.get("relationState", "current") == "current":
                add(str(relation.get("subjectLineageId") or relation.get("subjectId") or ""), via)
    return list(found.values())


def human_voted(row: Mapping[str, Any]) -> bool:
    return row.get("curationActorKind") == HUMAN
