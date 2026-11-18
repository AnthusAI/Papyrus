"""Announcement and Delivery notes of a pod, loaded as the newsroom's own records, as history (docs/announcement-records.md, "In a pod").

A pod keeps what was said and where as notes: an Announcement note, and a Delivery note for each channel whose body is the words exactly as posted. A load
turns them into the same two records the newsroom writes, so a Story's drawer shows a pod Delivery beside any other. They are history: every Delivery loads in the
final state its note says (``sent``, ``failed``, ``withdrawn`` or ``superseded``), in manual mode, with its attempts as the person wrote them. So:

- **A load sends nothing.** It has no channel, no Caducus and no worker. A loaded Delivery is in no state that waits for a time, so the sparse due index never holds it,
  and the attempt guard refuses a Delivery that is not live. Nothing in this module can open an attempt.
- **A pod's approval is a claim.** The Delivery records ``approval: hard`` with no approved version and a policy that says it was recorded in a pod, so nothing
  reads it as a newsroom approval or releases it.
- **Loaded once.** The Announcement's once-only key is ``pod:<the note's id>``, so loading the same note again finds the first load, writes nothing new, and
  completes only what a crash left undone. A record the newsroom has edited since is the newsroom's, and a later load never overwrites it.
- **Corrections.** A Delivery note that ``supersedes`` another is the next generation of that channel and account, as ``Deliveries.supersede`` would have made it.

``papyrus.pod.announcement_notes`` reads the notes into the plain records below; this module holds no pod code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import links
from .deliveries import Deliveries, DeliveryFiles, content_hash
from .links import StoryRef
from .records import (
    ANNOUNCEMENT_STATES, ANNOUNCES, SUPERSEDES, ATTEMPT_REFUSED, ATTEMPT_SENT, DECISION_MODEL, DELIVERY_MODEL, DELIVERY_STATES, HARD, MANUAL, RecordError, account_key, announcement_id,
    delivery_id, history_with, now_iso, require_catalog_only, stored, stored_dedupe_key, utc, with_due,
)

TRIGGER = "pod load"
APPROVAL_POLICY = "recorded in a pod; a claim, not a newsroom approval"
POD_ATTEMPT_OUTCOMES = (ATTEMPT_SENT, ATTEMPT_REFUSED)
#: The Delivery states a pod may carry: what happened, never something still waiting to go.
POD_DELIVERY_STATES = tuple(state for state in DELIVERY_STATES if state in ("sent", "failed", "withdrawn", "superseded"))
POD_ANNOUNCEMENT_STATES = tuple(state for state in ANNOUNCEMENT_STATES if state in ("released", "cancelled", "withdrawn"))


@dataclass(frozen=True)
class HistoricAttempt:
    number: int
    at: str
    outcome: str
    by: str | None = None
    code: str | None = None


@dataclass(frozen=True)
class HistoricDelivery:
    """One Delivery note. ``note_id`` is the note's permanent id; ``supersedes`` is the permanent id of the Delivery note it corrects."""

    note_id: str
    channel: str
    account: str
    state: str
    text: str
    attempts: Sequence[HistoricAttempt] = ()
    result_url: str | None = None
    supersedes: str | None = None


@dataclass(frozen=True)
class HistoricAnnouncement:
    """One Announcement note, the Stories it is about (as the newsroom knows them) and its Delivery notes."""

    note_id: str
    kind: str
    state: str
    stories: Sequence[StoryRef]
    deliveries: Sequence[HistoricDelivery]
    release_at: str | None = None


@dataclass(frozen=True)
class Loaded:
    announcement: dict[str, Any]
    deliveries: list[dict[str, Any]]
    created: bool


def dedupe_key(note_id: str) -> str:
    return f"pod:{note_id}"


class PodHistory:
    def __init__(self, client: Any, files: DeliveryFiles | None = None):
        self.client = client
        self.deliveries = Deliveries(client, files)

    def load(self, historic: HistoricAnnouncement, *, by: str, now: str | None = None) -> Loaded:
        """Write one Announcement note and its Delivery notes as records. Calling it again finds what was written and completes what a crash left undone."""
        now = now or now_iso()
        self._check(historic)
        row_id = announcement_id(dedupe_key(historic.note_id))
        release = utc(historic.release_at) or now
        announcement, created = self._announcement(row_id, historic, release, by, now)
        ids = self._ids(row_id, historic.deliveries)
        corrected_by = {delivery.supersedes: delivery.note_id for delivery in historic.deliveries if delivery.supersedes}
        written = [self._delivery(row_id, delivery, ids, corrected_by, announcement["releaseAt"], by, now) for delivery in self._in_generation_order(historic.deliveries, ids)]
        for story in historic.stories:
            if not self._linked(links.link_id(ANNOUNCES, row_id, story.lineage_id)):
                links.announces(self.client, row_id, story, now=now)
        for delivery in historic.deliveries:
            if delivery.supersedes and not self._linked(links.link_id(SUPERSEDES, ids[delivery.note_id][0], ids[delivery.supersedes][0])):
                links.supersedes(self.client, ids[delivery.note_id][0], ids[delivery.supersedes][0], now=now)
        return Loaded(announcement, written, created)

    def _linked(self, link_id: str) -> bool:
        """A link that is there is left as it is: the newsroom may have moved the version an Announcement looks at since the pod was loaded."""
        return self.client.get_record(links.MODEL, link_id) is not None

    # --- the rules a note must meet, said in the record's words ----------------------------------------------------------------------------------------

    def _check(self, historic: HistoricAnnouncement) -> None:
        if historic.state not in POD_ANNOUNCEMENT_STATES:
            raise RecordError(f"A pod records what happened: an Announcement note is {', '.join(POD_ANNOUNCEMENT_STATES)}; not {historic.state!r}.")
        if not historic.stories:
            raise RecordError("An Announcement is about at least one Story.")
        if not historic.deliveries:
            raise RecordError("A decision with no Delivery leaves no record: an Announcement note has a Delivery note.")
        known = {delivery.note_id for delivery in historic.deliveries}
        corrected: set[str] = set()
        for delivery in historic.deliveries:
            if delivery.state not in POD_DELIVERY_STATES:
                raise RecordError(f"A pod records what happened: a Delivery note is {', '.join(POD_DELIVERY_STATES)}; not {delivery.state!r}.")
            if not delivery.text.strip():
                raise RecordError(f"{delivery.note_id} has no words; the words are the body of the note.")
            for attempt in delivery.attempts:
                if attempt.outcome not in POD_ATTEMPT_OUTCOMES:
                    raise RecordError(f"{delivery.note_id}: an attempt in a pod ended {' or '.join(POD_ATTEMPT_OUTCOMES)}; not {attempt.outcome!r}.")
            if delivery.supersedes:
                if delivery.supersedes not in known or delivery.supersedes == delivery.note_id:
                    raise RecordError(f"{delivery.note_id} corrects {delivery.supersedes}, which is not another Delivery of this Announcement.")
                if delivery.supersedes in corrected:
                    raise RecordError(f"{delivery.supersedes} has two corrections; the live Delivery of a channel and account is the last of one chain.")
                corrected.add(delivery.supersedes)
        by_note = {delivery.note_id: delivery for delivery in historic.deliveries}
        for delivery in historic.deliveries:
            older = by_note.get(delivery.supersedes or "")
            if older and (older.channel, older.account) != (delivery.channel, delivery.account):
                raise RecordError(f"{delivery.note_id} corrects {older.note_id}, which is for another channel or account.")
            if (delivery.note_id in corrected) != (delivery.state == "superseded"):
                raise RecordError(f"{delivery.note_id} is {delivery.state}; a Delivery is superseded when, and only when, a later Delivery corrects it.")
        live = [d for d in historic.deliveries if d.note_id not in corrected]
        if len({(d.channel, d.account) for d in live}) != len(live):
            raise RecordError("One live Delivery for each Announcement, channel and account: a second one is a correction, so it supersedes the first.")

    # --- ids and generations ----------------------------------------------------------------------------------------------------------------------

    def _ids(self, announcement: str, deliveries: Sequence[HistoricDelivery]) -> dict[str, tuple[str, int]]:
        """Each Delivery note's record id and generation. A Delivery that corrects none is generation 1; the one that corrects it is the next."""
        by_note = {delivery.note_id: delivery for delivery in deliveries}
        generations: dict[str, int] = {}

        def generation(note_id: str, trail: tuple[str, ...] = ()) -> int:
            if note_id in trail:
                raise RecordError("A ring of corrections: each Delivery in it corrects another.")
            if note_id not in generations:
                older = by_note[note_id].supersedes
                generations[note_id] = 1 if not older else generation(older, (*trail, note_id)) + 1
            return generations[note_id]

        return {note_id: (delivery_id(announcement, by_note[note_id].channel, by_note[note_id].account, generation(note_id)), generation(note_id)) for note_id in by_note}

    @staticmethod
    def _in_generation_order(deliveries: Sequence[HistoricDelivery], ids: Mapping[str, tuple[str, int]]) -> list[HistoricDelivery]:
        return sorted(deliveries, key=lambda delivery: (ids[delivery.note_id][1], delivery.channel, delivery.account))

    # --- the rows -----------------------------------------------------------------------------------------------------------------------------------

    def _announcement(self, row_id: str, historic: HistoricAnnouncement, release: str, by: str, now: str) -> tuple[dict[str, Any], bool]:
        found = self.client.get_record(DECISION_MODEL, row_id)
        if found:
            return dict(found), False
        key = dedupe_key(historic.note_id)
        row = {
            "id": row_id, "dedupeKey": stored_dedupe_key(key), "kind": historic.kind, "state": historic.state, "releaseAt": release, "createdBy": by, "trigger": TRIGGER,
            "history": history_with({}, at=now, by=by, state=historic.state, note=f"loaded from the pod note {historic.note_id}: {historic.kind}"),
            "revision": 1, "createdAt": now, "updatedAt": now,
        }
        try:
            self.client.create_record(DECISION_MODEL, stored(row))
        except RuntimeError as error:
            if "conditional" in str(error).lower():
                return dict(self.client.get_record(DECISION_MODEL, row_id) or row), False
            raise
        return row, True

    def _delivery(self, announcement: str, delivery: HistoricDelivery, ids: Mapping[str, tuple[str, int]], corrected_by: Mapping[str, str], release: str, by: str, now: str) -> dict[str, Any]:
        row_id, generation = ids[delivery.note_id]
        existing = self.deliveries.get(row_id)
        if existing:
            self.deliveries.ensure_text(existing, delivery.text, now=now)
            return existing
        file = self.deliveries.files.describe(row_id, delivery.text)
        successor = ids[corrected_by[delivery.note_id]][0] if delivery.note_id in corrected_by else None
        row: dict[str, Any] = {
            "id": row_id, "announcementId": announcement, "channel": delivery.channel, "accountId": delivery.account, "accountKey": account_key(delivery.channel, delivery.account),
            "mode": MANUAL, "state": delivery.state, "generation": generation, "version": 1,
            "textKey": file["key"], "contentHash": content_hash(file["sha256"], None), "draftedBy": "pod",
            "approval": HARD, "approvalPolicy": APPROVAL_POLICY,
            "releaseAt": release, "lockAt": release,
            "attempts": [_entry(attempt) for attempt in delivery.attempts] or None, "resultUrl": delivery.result_url,
            "supersedes": ids[delivery.supersedes][0] if delivery.supersedes else None, "supersededBy": successor,
            "history": history_with({}, at=now, by=by, state=delivery.state, note=f"loaded from the pod note {delivery.note_id}"),
            "revision": 1, "createdAt": now, "updatedAt": now,
        }
        require_catalog_only(row)
        row = with_due(row)
        try:
            self.client.create_record(DELIVERY_MODEL, stored(row))
        except RuntimeError as error:
            if "conditional" in str(error).lower():
                found = self.deliveries.get(row_id) or row
                self.deliveries.ensure_text(found, delivery.text, now=now)
                return found
            raise
        self.deliveries.files.put(row_id, delivery.text, now=now)
        return row


def _entry(attempt: HistoricAttempt) -> dict[str, Any]:
    entry: dict[str, Any] = {"number": attempt.number, "at": attempt.at, "outcome": attempt.outcome, "closedAt": attempt.at}
    if attempt.by:
        entry["by"] = attempt.by
    if attempt.code:
        entry["code"] = attempt.code
    return entry
