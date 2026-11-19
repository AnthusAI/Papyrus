"""The Item change feed: every change to a Story or its checklist becomes one wake per listening agent (PPY-8a374e, slice B2 of
docs/design/always-on-agents-architecture.md).

A DynamoDB stream on the Item table invokes the feed (``amplify/functions/item-change-feed``). Whoever wrote the change (the console board, the CLI, an agent,
a person's save) the record is the same, so the feed starts procedures for all of them and no writer has to call anything. For each stream record it:

1. **normalizes** the change, or finds none. Four changes are real:

   ``version_created``  a new version of an Item (not a checklist step) was inserted.
   ``stage_entered``    a Story entered a stage: a version created at a stage when it is the Story's first, or the stage field changed in place (a board move).
   ``step_changed``     a checklist step (a ``sub-task`` Item) got a new state. A note on a step repeats the previous entry and is not a change.

   ``rated``            a Story's star rating was set, changed or cleared in place (PPY-e3bb2b). Its wake key names the new stars and the time of the rating, so rating a
                        Story again is a new wake and a stream record delivered twice is the same one. A new version that only carries the rating over is no change.

   Everything else the table does (the previous version being marked superseded, a card's counts being refreshed) is no change and costs nothing.
2. **finds the agents that listen** in the site's listener index (``agent_listeners.py``), by the change's name and each listener's filter. The index is
   one small document read by its live version, never a list of the Automation table or of any table. A change nobody listens for sends nothing.
3. **puts one wake on the site's queue for each**, through ``agent_wakes.send_wake``: the key is ``<agent>|<lineage>|<version>|<what>``, so the run record made
   from it is the claim and the queue's deduplication id is its digest. The message group is the agent plus the Story's lineage, so one Story's wakes for an agent
   run one after the other. A stream record delivered twice makes the same keys, so it starts nothing twice. An agent's own change never wakes that agent.

The wake carries what the later slices need and nothing they must look up: ``trigger.paid`` and ``trigger.serialBy`` (the quiet window for paid steps,
PPY-67e3cd, decides to wait on ``paid`` and uses ``actorKind`` for the short window after a person's own action), ``trigger.actorKind``, ``trigger.actorLabel`` and
``trigger.at`` (the loop guard, PPY-4e7e8b, counts agent changes per Story since a person last acted), and ``input`` (the Story, the version, what changed). The window
and the guard are not built here: they sit between this feed and the queue, and read those fields.

Two limits of what a stream can say, kept honest: a new version created at a different stage from its predecessor is not a stage entry (the stream holds no
previous version; the stage moves that matter, the board's and ``move_story_stage``'s, change the field in place); and a stage entered again at the same
version has the same key and starts nothing again.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from . import wake_keys
from . import agent_listeners as listener_index
from .item_stars import item_stars

TABLE, KIND = "Item", "Item"
SUB_TASK = "sub-task"
VERSION_CREATED, STAGE_ENTERED, STEP_CHANGED, RATED = "version_created", "stage_entered", "step_changed", "rated"
CHANGES = (VERSION_CREATED, STAGE_ENTERED, STEP_CHANGED, RATED)
AGENT_LABEL_PREFIX = "automation:"
MAX_SUMMARY_CHARACTERS = 500
ACTOR_AGENT, ACTOR_PERSON = "agent", "person"


@dataclass(frozen=True)
class Change:
    """One normalized change: what happened to which record, and who did it."""

    change: str
    id: str                      # the record that changed
    lineage: str                 # the Story the change belongs to (a step's parent)
    version: str                 # the record's version id (the row id of the version)
    what: str                    # the change's name in a wake key: a stage entry names its stage
    actor_kind: str
    actor_label: str | None
    at: str | None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    # What the other tables' feeds (``change_feeds.py``) add to the one shape. An Item change keeps the defaults, so its wake is as it was.
    table: str = TABLE
    kind: str = KIND
    subject: Mapping[str, Any] | None = None   # what the wake is about when that is not a Story: ``{"kind", "id"}``
    only_for: str | None = None                # the one agent the change is addressed to (an answer wakes the agent that asked), else every listener

    def as_dict(self) -> dict[str, Any]:
        return {"table": self.table, "kind": self.kind, "id": self.id, "lineage": self.lineage, "version": self.version, "change": self.change, "what": self.what,
                "actorKind": self.actor_kind, "actorLabel": self.actor_label, "at": self.at, **{f"attribute.{name}": value for name, value in self.attributes.items()}}


def _metadata(row: Mapping[str, Any] | None) -> dict[str, Any]:
    value = (row or {}).get("metadata")
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else {}
        except json.JSONDecodeError:
            value = {}
    return value if isinstance(value, dict) else {}


def _actor_of_label(label: Any) -> tuple[str, str | None]:
    text = str(label).strip() if label else ""
    return (ACTOR_AGENT if text.startswith(AGENT_LABEL_PREFIX) else ACTOR_PERSON), (text or None)


def _last_move(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    moves = [move for move in _metadata(row).get("stageMoves") or [] if isinstance(move, dict)]
    return moves[-1] if moves else None


def _story_changes(old: Mapping[str, Any] | None, new: Mapping[str, Any], inserted: bool) -> list[Change]:
    lineage, row_id = new.get("lineageId") or new.get("id"), new.get("id")
    if not lineage or not row_id:
        return []
    shared = {"type": new.get("type"), "section": new.get("section"), "language": new.get("language")}
    found: list[Change] = []
    if inserted:
        kind, label = _actor_of_label(new.get("versionCreatedBy"))
        attributes = {**shared, "stage": new.get("stage"), "versionNumber": new.get("versionNumber"), "actorKind": kind}
        found.append(Change(VERSION_CREATED, row_id, lineage, row_id, VERSION_CREATED, kind, label, new.get("versionCreatedAt"), attributes))
        if int(new.get("versionNumber") or 1) == 1 and new.get("stage"):
            found.append(Change(STAGE_ENTERED, row_id, lineage, row_id, f"{STAGE_ENTERED}.{new['stage']}", kind, label, new.get("versionCreatedAt"),
                                {**shared, "stage": new["stage"], "from": None, "actorKind": kind}))
    elif old is not None and new.get("stage") and (old.get("stage") or None) != new["stage"]:
        # Every agent's move goes through ``move_story_stage``, which records it on the version. A change of the stage field with no new record of the move is
        # a person's, made in the console board, so a move that left the record of the last move as it was has no agent behind it.
        move = _last_move(new)
        recorded = move is not None and move != _last_move(old) and move.get("to") == new["stage"]
        kind, label = _actor_of_label(move.get("by")) if recorded else (ACTOR_PERSON, None)
        found.append(Change(STAGE_ENTERED, row_id, lineage, row_id, f"{STAGE_ENTERED}.{new['stage']}", kind, label,
                            (move or {}).get("at") if recorded else new.get("updatedAt"),
                            {**shared, "stage": new["stage"], "from": old.get("stage"), "actorKind": kind}))
    if not inserted and old is not None:
        before, after = item_stars(old), item_stars(new)
        if before != after:
            # A rating is made in place on the Story's record (an editor's, or the rating agent's, named ``automation:<agent>``). Clearing one is a change too: an agent
            # that re-checks what to say about the Story must hear that nobody rates it now. The key carries the stars and the moment, so a Story rated 4, 3 and 4 again
            # is three wakes, and one stream record delivered twice is one.
            kind, label = _actor_of_label(new.get("starRatedBy"))
            at = new.get("starRatedAt") or new.get("updatedAt")
            found.append(Change(RATED, row_id, lineage, row_id, f"{RATED}.{'cleared' if after is None else after}" + (f".{at}" if at else ""), kind, label, at,
                                {**shared, "stage": new.get("stage"), "stars": after, "previousStars": before, "actorKind": kind}))
    return found


def _step_changes(new: Mapping[str, Any]) -> list[Change]:
    lineage, row_id = new.get("parentLineageId"), new.get("id")
    entry = (_metadata(new).get("checklist") or {}).get("entry") or {}
    key = (_metadata(new).get("checklist") or {}).get("stepKey")
    # A version made only to add a note repeats the step's last entry, whose time is not this version's: only a state change carries the version's own time.
    if not lineage or not row_id or not key or not entry or entry.get("at") != new.get("versionCreatedAt"):
        return []
    kind = ACTOR_AGENT if entry.get("actorKind") == "agent" else ACTOR_PERSON
    label = entry.get("actorLabel") or entry.get("actorSub")
    return [Change(STEP_CHANGED, row_id, lineage, row_id, STEP_CHANGED, kind, label, entry.get("at"),
                   {"step": key, "state": new.get("status"), "actorKind": entry.get("actorKind") or kind})]


def changes_of(old: Mapping[str, Any] | None, new: Mapping[str, Any] | None, event_name: str) -> list[Change]:
    """The normalized changes one stream record makes, possibly none. A removed record is never a change."""
    if new is None or event_name not in ("INSERT", "MODIFY"):
        return []
    if new.get("type") == SUB_TASK:
        return _step_changes(new) if event_name == "INSERT" else []
    return _story_changes(old, new, event_name == "INSERT")


def is_own_change(change: Change, agent: str) -> bool:
    """An agent's own change never wakes that agent."""
    return change.actor_kind == ACTOR_AGENT and change.actor_label == f"{AGENT_LABEL_PREFIX}{agent}"


@dataclass(frozen=True)
class Site:
    """Where the site's runs go and what a runner request needs to find its policy. All of it is the feed's own configuration, set by the stack."""

    publication_id: str
    appsync_endpoint: str
    tenant_id: str | None = None
    site_bucket: str | None = None
    openai_key_parameter: str | None = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "Site":
        def value(name: str) -> str | None:
            return (environment.get(name) or "").strip() or None

        return cls(publication_id=value("PAPYRUS_AGENT_PUBLICATION_ID") or "", appsync_endpoint=value("PAPYRUS_GRAPHQL_ENDPOINT") or "",
                   tenant_id=value("PAPYRUS_TENANT_ID"), site_bucket=value("PAPYRUS_SITE_BUCKET"), openai_key_parameter=value("PAPYRUS_OPENAI_KEY_PARAMETER"))


def _reason(change: Change, agent: str) -> str:
    by = f"by {change.actor_label}" if change.actor_label else f"by a {change.actor_kind}"
    if change.kind != KIND:
        what = f"{change.kind} {change.lineage} changed: {change.change.replace('_', ' ')}"
    elif change.change == STAGE_ENTERED:
        what = f"Story {change.lineage} entered {change.attributes.get('stage')}"
    elif change.change == RATED:
        stars = change.attributes.get("stars")
        what = f"Story {change.lineage} was {f'rated {stars} stars' if stars else 'left unrated'}"
    elif change.change == STEP_CHANGED:
        what = f"step {change.attributes.get('step')} of Story {change.lineage} became {change.attributes.get('state')}"
    else:
        what = f"Story {change.lineage} got a new version ({change.version})"
    return f"Agent {agent} woke because {what}, {by}"[:MAX_SUMMARY_CHARACTERS]


def wake_request(change: Change, listener: Mapping[str, Any], site: Site) -> dict[str, Any]:
    """The runner's request for one listener of one change, with its wake key. ``agent_wakes.send_wake`` turns it into the message."""
    agent, procedure = listener["agent"], listener["procedure"]
    request: dict[str, Any] = {
        "wakeKey": wake_keys.change_key(wake_keys.owner(agent, procedure), change.lineage, change.version, change.what),
        "publicationId": site.publication_id, "appsyncEndpoint": site.appsync_endpoint, "procedureKey": procedure,
        "actorLabel": f"{AGENT_LABEL_PREFIX}{agent}",
        "input": {**({"story": change.lineage} if change.subject is None else {"subject": dict(change.subject)}), "version": change.version, "change": change.change,
                  "what": change.what, **{name: value for name, value in change.attributes.items() if value is not None}},
        "trigger": {"kind": "event", "event": f"{change.kind.lower()}.{change.change}", "automationId": agent,
                    **({"story": change.lineage} if change.subject is None else {"subject": dict(change.subject)}), "version": change.version,
                    "title": f"{procedure}: {change.change.replace('_', ' ')}"[:200], "summary": _reason(change, agent),
                    "paid": bool(listener.get("paid")), "serialBy": listener.get("serialBy"), "responsibility": listener.get("responsibility"), "actorKind": change.actor_kind,
                    "actorLabel": change.actor_label, "at": change.at},
    }
    for name, value in (("tenantId", site.tenant_id), ("siteBucket", site.site_bucket), ("openaiKeyParameter", site.openai_key_parameter)):
        if value:
            request[name] = value
    return request


def wakes_for(change: Change, index: Mapping[str, Any] | None, site: Site) -> list[dict[str, Any]]:
    """One request per agent that listens for the change, in agent order, leaving out the agent that made it."""
    attributes = {**change.attributes, "change": change.change}
    return [wake_request(change, listener, site) for listener in listener_index.listening(index, change.kind, change.change, attributes)
            if not is_own_change(change, listener["agent"]) and change.only_for in (None, listener["agent"])]


def handle(records: list[Mapping[str, Any]], *, decode: Callable[[Any], Any], listeners: Callable[[], Mapping[str, Any]], send: Callable[[dict], Any],
           site: Site, normalize: Callable[[Mapping[str, Any], Mapping[str, Any] | None, Mapping[str, Any] | None], list[Change]] | None = None,
           wakes: Callable[[Change, Mapping[str, Any] | None, Site], list[dict[str, Any]]] | None = None, feed: str = "item", gate: Any = None) -> dict[str, Any]:
    """Process one stream batch in order. The index is read once, and only if some record is a change. A record whose wakes cannot all be sent reports itself
    (and Lambda retries from it: every key is the same on the retry, so what was already sent starts nothing again). The other tables' feeds (``change_feeds.py``)
    pass their own ``normalize`` (a record and its decoded images to the changes it makes) and ``wakes``; the loop, the tenant guard and the retry are this one.

    ``gate`` (``wake_gate.WakeGate``) stands between the changes and the queue: a person's change to a Story clears the loop count, and each wake is sent, made to wait
    for quiet (a paid step) or stopped (the loop limit). With no gate every wake is sent at once, as before."""
    index: Mapping[str, Any] | None = None
    sent = 0
    for record in records:
        stream = record.get("dynamodb") or {}
        old, new = decode(stream.get("OldImage")), decode(stream.get("NewImage"))
        if site.tenant_id and (new or {}).get("tenantId") not in (None, "", site.tenant_id):
            continue   # a row of another tenant is not this site's change: nothing about it is read or sent
        found = normalize(record, old, new) if normalize else changes_of(old, new, record.get("eventName") or "")
        if not found:
            continue
        try:
            if index is None:
                index = listeners()
            if gate is not None:
                for change in found:
                    if change.kind == KIND and change.actor_kind == ACTOR_PERSON:
                        gate.person_acted(subject=change.lineage, version=change.version)
            requests = [request for change in found for request in (wakes or wakes_for)(change, index, site)]
            for request in requests:
                if gate is None:
                    send(request)
                elif gate.release(request, send)["status"] != "sent":
                    continue
                sent += 1
        except Exception as error:   # noqa: BLE001 - nothing is guessed: the record is retried whole
            print(json.dumps({"event": f"papyrus_{feed}_change_feed_failed", "error": f"{type(error).__name__}: {error}"[:500], "sequence": stream.get("SequenceNumber")}))
            return {"batchItemFailures": [{"itemIdentifier": stream["SequenceNumber"]}], "wakesSent": sent}
    return {"batchItemFailures": [], "wakesSent": sent}
