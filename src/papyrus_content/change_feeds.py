"""The change feeds of the other tables agents react to (PPY-9b9e64, slice B3 of docs/design/always-on-agents-architecture.md).

``item_change_feed.py`` turns a change to a Story or its checklist into a wake for each agent that listens. This module does the same for five more tables, with
the same normalized change (``table, kind, id, lineage, version, change, actorKind, at``), the same listener index, the same wake and the same loop, so nothing
here is a second way to wake an agent: it is five normalizers and the lookup of a Message's subject.

==========================  ==========  ===========================================================================================================
table                       change      what it is
==========================  ==========  ===========================================================================================================
Reference                   created     the first version of a Reference was inserted
                            accepted    its curation status became ``accepted`` (a Reference may also arrive accepted)
                            rated       its star rating was set or changed
                            recaptured  its content was captured again (a new retrieval time or content hash on a Reference that had one)
ReviewRequest               answered    an open request was answered. The change is addressed to the agent that asked, and to no other
Message                     posted      a comment was posted. The wake is for the listeners of the subject the comment is on (the anchor of its thread)
LocalizationRequest         wanted      a translation was asked for (a request inserted ``wanted``, or put back to ``wanted``)
Delivery                    state_changed  a Delivery was drafted or its state changed (the state is in the wake key)
                            approved    a version of a Delivery was approved (the version is in the wake key); the announce agent sends on it (PPY-1de948)
Assignment                  created     a request for a responsibility's work was filed (``agent_assignments.py``); only ``responsibility.*`` Assignments are changes
                            reopened    a closed (completed, canceled or failed) request was put back to ``open``; the key names the reopening
                            completed   the responsible agent finished the work. The change is addressed to the agent that asked, and to no other
==========================  ==========  ===========================================================================================================

A feed never reads a table. The listener index is read first (one point read of its live version) and a change nobody listens for sends nothing, so the one
lookup a feed makes, a Message's thread (a point read by id, to find what the comment is on), happens only when some agent listens for a posted Message.

The wake key is ``<agent>|<lineage>|<version>|<what>``. ``what`` carries what made the change different from the last one at that version (a star rating, the
state a Delivery entered, the time a translation was asked for), so asking again is a new wake and a stream record delivered twice is the same one.
An agent's own change never wakes that agent (``item_change_feed.is_own_change``: the label ``automation:<agent>`` on the change).

Which table a stream record belongs to comes from the stream ARN it carries (``Streams``), set by the stack that reads the streams: a record from a stream the
feed was not given is an error, never a guess. The same records arrive from a table's own mapping or, where the table already has two stream readers, from the
existing reader that relays the batch to this function (``change_feed_relay.py``): the feed cannot tell and does not need to.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from . import agent_listeners as listener_index
from . import item_change_feed
from .change_vocabulary import FEED_TABLES
from .item_change_feed import ACTOR_AGENT, ACTOR_PERSON, AGENT_LABEL_PREFIX, Change, Site
from .wake_keys import UNVERSIONED

STREAMS_ENVIRONMENT = "PAPYRUS_CHANGE_FEED_STREAMS"
REFERENCE, REVIEW_REQUEST, MESSAGE, LOCALIZATION_REQUEST, DELIVERY, ASSIGNMENT = "Reference", "ReviewRequest", "Message", "LocalizationRequest", "Delivery", "Assignment"
ACCEPTED_STATUS = "accepted"
ANSWERED, WANTED = "answered", "wanted"
COMMENT = "comment"
AGENT_PREFIXES = (AGENT_LABEL_PREFIX, "agent:")
#: A thread's anchor kind as the stored thread names it, and what the subject is called in a wake.
SUBJECT_KINDS = {"item": "Story", "reference": "Reference", "delivery": "Delivery"}
THREAD_KIND = "thread"


class UnknownStream(ValueError):
    """A stream record from a stream this feed was not given. Nothing is guessed about which table it is."""


@dataclass(frozen=True)
class Streams:
    """Which stream is which table: the stack gives the feed each stream ARN it reads or is relayed, with the table's name."""

    tables: Mapping[str, str]

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "Streams":
        text = (environment.get(STREAMS_ENVIRONMENT) or "").strip()
        if not text:
            raise ValueError(f"the change feed needs the streams it reads ({STREAMS_ENVIRONMENT}: a JSON list of stream ARNs and table names)")
        pairs = json.loads(text)
        tables = {pair["stream"]: pair["table"] for pair in pairs}
        unknown = sorted(set(tables.values()) - set(FEED_TABLES))
        if unknown:
            raise ValueError(f"{STREAMS_ENVIRONMENT} names tables the feeds do not cover: {', '.join(unknown)}")
        return cls(tables)

    def table_of(self, record: Mapping[str, Any]) -> str:
        arn = record.get("eventSourceARN")
        if arn not in self.tables:
            raise UnknownStream(f"a stream record from {arn!r}, which this feed does not read")
        return self.tables[arn]


# --- who made a change ---------------------------------------------------------------------------------------------------------------------------


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _actor(label: Any, agent_kind: bool = False) -> tuple[str, str | None]:
    """An agent when the label says so (``automation:<agent>`` or ``agent:<agent>``) or the row says the actor is a machine; else a person."""
    text = _text(label)
    is_agent = agent_kind or bool(text and text.startswith(AGENT_PREFIXES))
    if text and text.startswith("agent:"):
        text = f"{AGENT_LABEL_PREFIX}{text[len('agent:'):]}"   # one spelling, so an agent's own change is found whichever prefix its writer used
    return (ACTOR_AGENT if is_agent else ACTOR_PERSON), text


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else default
        except json.JSONDecodeError:
            return default
    return default if value is None else value


# --- Reference -----------------------------------------------------------------------------------------------------------------------------------


def _reference_changes(old: Mapping[str, Any] | None, new: Mapping[str, Any], inserted: bool) -> list[Change]:
    lineage, row_id = new.get("lineageId") or new.get("id"), new.get("id")
    if not lineage or not row_id:
        return []
    old = old or {}
    shared = {"corpusId": new.get("corpusId"), "medium": new.get("medium"), "section": new.get("curationSectionId")}
    subject = {"kind": REFERENCE, "id": lineage}

    def change(name: str, what: str, kind: str, label: Any, at: Any, **extra: Any) -> Change:
        who, text = _actor(label, kind in ("agent", "cyclotron"))
        return Change(name, row_id, lineage, row_id, what, who, text, _text(at), {**shared, **extra, "actorKind": who}, REFERENCE, REFERENCE, subject)

    found: list[Change] = []
    if inserted and int(new.get("versionNumber") or 1) == 1:
        found.append(change("created", "created", "", new.get("versionCreatedBy"), new.get("versionCreatedAt") or new.get("createdAt"), versionNumber=new.get("versionNumber")))
    status = _text(new.get("curationStatus"))
    if status == ACCEPTED_STATUS and _text(old.get("curationStatus")) != ACCEPTED_STATUS:
        found.append(change("accepted", "accepted", str(new.get("curationActorKind") or ""), new.get("curationStatusUpdatedBy"), new.get("curationStatusUpdatedAt"),
                            curationStatus=status, reason=new.get("curationReasonCode")))
    stars = new.get("starRating")
    if stars is not None and stars != old.get("starRating"):
        found.append(change("rated", f"rated.{int(stars)}", "", new.get("starRatedBy"), new.get("starRatedAt"), stars=int(stars), previousStars=old.get("starRating")))
    if not inserted and old:
        retrieved, changed_hash = _text(new.get("retrievedAt")), _text(new.get("contentHash"))
        recaptured = (retrieved is not None and _text(old.get("retrievedAt")) not in (None, retrieved)) or \
                     (changed_hash is not None and _text(old.get("contentHash")) not in (None, changed_hash))
        if recaptured:
            found.append(change("recaptured", f"recaptured.{retrieved or (changed_hash or '')[:16]}", "", new.get("versionCreatedBy"), retrieved or new.get("updatedAt"),
                                captureState=new.get("captureState")))
    return found


# --- ReviewRequest -------------------------------------------------------------------------------------------------------------------------------


def _asker(raised_by: Any) -> str | None:
    """The agent a request was raised by, as the definition names it: ``agent:<id>`` and ``automation:<id>`` lose their prefix, a bare name is the id."""
    text = _text(raised_by)
    if not text:
        return None
    for prefix in AGENT_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):] or None
    return text


def _review_changes(old: Mapping[str, Any] | None, new: Mapping[str, Any]) -> list[Change]:
    if new.get("state") != ANSWERED or (old or {}).get("state") == ANSWERED:
        return []
    row_id, asker = new.get("id"), _asker(new.get("raisedBy"))
    subject = _json(new.get("subject"), {})
    subject_id = _text(subject.get("id")) if isinstance(subject, dict) else None
    if not row_id or not asker or not subject_id:
        return []   # a request nobody raised, or about nothing: nobody asked, so nobody is waiting for the answer
    answer = _json(new.get("answer"), {})
    answer = answer if isinstance(answer, dict) else {}
    who, label = _actor(answer.get("by"))
    decision = _text(answer.get("decision"))
    return [Change("answered", row_id, subject_id, row_id, "answered", who, label, _text(answer.get("at")) or _text(new.get("updatedAt")),
                   {"decision": decision, "mode": new.get("mode"), "reason": new.get("reason"), "subjectType": subject.get("type"), "steer": answer.get("steer"),
                    "raisedBy": new.get("raisedBy"), "actorKind": who},
                   REVIEW_REQUEST, REVIEW_REQUEST, {"kind": str(subject.get("type") or ""), "id": subject_id}, asker)]


# --- LocalizationRequest -------------------------------------------------------------------------------------------------------------------------


def _localization_changes(old: Mapping[str, Any] | None, new: Mapping[str, Any]) -> list[Change]:
    if new.get("state") != WANTED:
        return []
    old = old or {}
    asked_at = _text(new.get("requestedAt"))
    if old.get("state") == WANTED and _text(old.get("requestedAt")) == asked_at:
        return []   # a row rewritten as it was is not a new ask
    group, language, version, row_id = new.get("languageGroupId"), new.get("language"), new.get("sourceVersionId"), new.get("id")
    if not (group and language and version and row_id and asked_at):
        return []
    who, label = _actor(new.get("requestedBy"))
    return [Change("wanted", row_id, group, version, f"wanted.{language}.{asked_at}", who, label, asked_at,
                   {"language": language, "sourceVersionNumber": new.get("sourceVersionNumber"), "automationId": new.get("automationId"), "publish": new.get("publish"),
                    "actorKind": who},
                   LOCALIZATION_REQUEST, LOCALIZATION_REQUEST, {"kind": "Story", "id": group})]


# --- Delivery ------------------------------------------------------------------------------------------------------------------------------------


def _delivery_changes(old: Mapping[str, Any] | None, new: Mapping[str, Any], inserted: bool) -> list[Change]:
    state, row_id = _text(new.get("state")), new.get("id")
    before = _text((old or {}).get("state"))
    approved, approved_before = new.get("approvedVersion"), (old or {}).get("approvedVersion")
    newly_approved = approved is not None and approved != approved_before
    if not state or not row_id or (not inserted and state == before and not newly_approved):
        return []
    history = [line for line in _json(new.get("history"), []) if isinstance(line, dict)]
    last = history[-1] if history else {}
    who, label = _actor(last.get("by") or new.get("draftedBy"))
    version = str(new.get("revision") if new.get("revision") is not None else "unversioned")
    at = _text(last.get("at")) or _text(new.get("updatedAt"))
    attributes = {"state": state, "from": before, "channel": new.get("channel"), "accountId": new.get("accountId"), "announcementId": new.get("announcementId"),
                  "mode": new.get("mode"), "approval": new.get("approval"), "actorKind": who}
    subject = {"kind": DELIVERY, "id": row_id}
    changes = []
    if inserted or state != before:
        changes.append(Change("state_changed", row_id, row_id, version, f"state_changed.{state}", who, label, at, attributes, DELIVERY, DELIVERY, subject))
    if newly_approved:
        # A person let a version go (PPY-1de948): its own change, so the agent that sends can wake for it rather than wait for an unrelated Story change.
        changes.append(Change("approved", row_id, row_id, version, f"approved.{approved}", who, label, at, {**attributes, "approvedVersion": approved}, DELIVERY, DELIVERY, subject))
    return changes


# --- Assignment ----------------------------------------------------------------------------------------------------------------------------------


def _assignment_changes(old: Mapping[str, Any] | None, new: Mapping[str, Any], inserted: bool) -> list[Change]:
    from .handoff_records import CLAIMED, COMPLETED, FINAL, OPEN, responsibility_of

    responsibility, row_id, status = responsibility_of(new), new.get("id"), _text(new.get("status"))
    if not responsibility or not row_id:
        return []   # any other kind of Assignment is run by its own executor, not woken for
    before = _text((old or {}).get("status"))
    asker = _text(new.get("createdBy"))
    shared = {"responsibility": responsibility, "story": new.get("itemLineageId"), "askedBy": asker, "why": new.get("summary"), "assignmentStatus": status}
    subject = {"kind": ASSIGNMENT, "id": row_id}

    def change(name: str, what: str, label: Any, at: Any, only_for: str | None = None) -> Change:
        who, text = _actor(label)
        return Change(name, row_id, row_id, UNVERSIONED, what, who, text, _text(at), {**shared, "actorKind": who}, ASSIGNMENT, ASSIGNMENT, subject, only_for)

    if inserted:
        return [change("created", "created", asker, new.get("createdAt"))] if status == OPEN else []
    if status == OPEN and before in FINAL:
        at = _text(new.get("updatedAt"))
        return [change("reopened", f"reopened.{at}", asker, at)] if at else []
    if status == COMPLETED and before == CLAIMED:
        agent = _asker(asker)
        if not agent or not (asker or "").startswith(AGENT_PREFIXES):
            return []   # a person asked: nobody is waiting to be woken, the Story shows the result
        at = _text(new.get("completedAt")) or _text(new.get("updatedAt"))
        return [change("completed", f"completed.{at}" if at else "completed", new.get("assigneeKey"), at, only_for=agent)]
    return []


# --- Message -------------------------------------------------------------------------------------------------------------------------------------


def _message_changes(new: Mapping[str, Any]) -> list[Change]:
    row_id = new.get("id")
    if not row_id or _text(new.get("messageKind")) != COMMENT or (_text(new.get("status")) or "active") != "active" or not _text(new.get("threadId")):
        return []
    machine = str(new.get("role") or "").lower() in ("assistant", "agent", "system")
    who, label = _actor(new.get("authorLabel"), machine)
    return [Change("posted", row_id, str(new["threadId"]), row_id, "posted", who, label, _text(new.get("createdAt")),
                   {"threadId": new["threadId"], "parentMessageId": new.get("parentMessageId"), "actorKind": who}, MESSAGE, MESSAGE, {"kind": THREAD_KIND, "id": str(new["threadId"])})]


def _resolved(change: Change, thread: Mapping[str, Any] | None) -> Change:
    """The posted Message's subject: what its thread is anchored on. A thread with no anchor is its own subject."""
    anchor = _text((thread or {}).get("primaryAnchorLineageId")) or _text((thread or {}).get("primaryAnchorId"))
    if not anchor:
        return change
    kind = SUBJECT_KINDS.get(str((thread or {}).get("primaryAnchorKind") or "").lower(), str((thread or {}).get("primaryAnchorKind") or THREAD_KIND))
    return replace(change, lineage=anchor, subject={"kind": kind, "id": anchor},
                   attributes={**change.attributes, "subjectKind": kind, "subjectId": anchor, "threadKind": (thread or {}).get("threadKind")})


# --- the feed ------------------------------------------------------------------------------------------------------------------------------------


def changes_of(table: str, old: Mapping[str, Any] | None, new: Mapping[str, Any] | None, event_name: str) -> list[Change]:
    """The normalized changes one stream record of ``table`` makes, possibly none. A removed record is never a change."""
    if new is None or event_name not in ("INSERT", "MODIFY"):
        return []
    inserted = event_name == "INSERT"
    if table == REFERENCE:
        return _reference_changes(old, new, inserted)
    if table == REVIEW_REQUEST:
        return _review_changes(old, new)
    if table == LOCALIZATION_REQUEST:
        return _localization_changes(old, new)
    if table == DELIVERY:
        return _delivery_changes(old, new, inserted)
    if table == ASSIGNMENT:
        return _assignment_changes(old, new, inserted)
    if table == MESSAGE:
        return _message_changes(new) if inserted else []
    raise ValueError(f"no change feed for the table {table!r}")


def wakes_for(change: Change, index: Mapping[str, Any] | None, site: Site, *, thread_of: Callable[[str], Mapping[str, Any] | None]) -> list[dict[str, Any]]:
    """One request per agent that listens for the change. A posted Message is first placed on its subject, and only when some agent listens for it at all."""
    if not listener_index.listeners_of(index, change.kind, change.change):
        return []
    if change.kind == MESSAGE:
        change = _resolved(change, thread_of(change.lineage))
    return item_change_feed.wakes_for(change, index, site)


def handle(records: list[Mapping[str, Any]], *, streams: Streams, decode: Callable[[Any], Any], listeners: Callable[[], Mapping[str, Any]],
           send: Callable[[dict], Any], site: Site, thread_of: Callable[[str], Mapping[str, Any] | None]) -> dict[str, Any]:
    """Process one batch of stream records of any of the feed's tables, in order, with the Item feed's own loop (tenant guard, one read of the index, retry of a
    failed record from itself). A record from a stream the feed was not given raises: that is a wiring error, not a change."""
    return item_change_feed.handle(
        records, decode=decode, listeners=listeners, send=send, site=site, feed="change",
        normalize=lambda record, old, new: changes_of(streams.table_of(record), old, new, record.get("eventName") or ""),
        wakes=lambda change, index, which: wakes_for(change, index, which, thread_of=thread_of))
