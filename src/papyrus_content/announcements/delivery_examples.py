"""What a person changed in an announcement, and how far it should reach (PPY-627bbc, slice O1; docs/announcement-learning.md).

A Delivery that went out (or has a *preferred version*, how it should have read) with a person's words in it can teach the drafter, but only when a person says how far:
``this_one`` (changes nothing later), ``channel``, ``kind`` (this kind of Announcement on this channel) or ``publication``. With no choice the edit is a **candidate**: kept, listed for
an admin, and changing nothing about any later draft. Nothing is learned silently.

The record is a few short fields on the Delivery, written once and read again later:

* ``machineVersion``: the machine's version the person worked from (the newest machine version at or before the final one);
* ``exampleScope`` and ``exampleState`` (``candidate``, ``active``, ``declined``; later ``off`` and ``absorbed``), with ``exampleAt``;
* ``exampleKey``, present only while the example is active, so the drafter reads the active examples of a scope through one sparse index (slice O3) and never scans.

The final version is the one that went out, or the preferred version when one was saved after it. **The difference between the machine's version and the final one is computed
from the two stored versions when needed, never stored again.** The person's one-line reason is a file of the Delivery in S3 (``reason``); the catalog row never holds it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..tenant_knowledge_keys import global_key
from . import delivery_text as dt
from .deliveries import Conflict, Deliveries
from .decisions import Announcements
from .records import ATTEMPT_SENT, SENT, RecordError, attempt_log, now_iso

THIS_ONE, CHANNEL, KIND, PUBLICATION = "this_one", "channel", "kind", "publication"
SCOPES = (THIS_ONE, CHANNEL, KIND, PUBLICATION)
#: The scopes that reach a later draft, narrowest first.
WIDE_SCOPES = (CHANNEL, KIND, PUBLICATION)
#: ``candidate``: kept, no scope chosen, changes nothing. ``active``: loaded by the drafter for its scope. ``declined``: a person chose "just this one", so nothing later changes.
CANDIDATE, ACTIVE, DECLINED = "candidate", "active", "declined"
REASON_FILE = "reason"


class NothingToLearn(RecordError):
    """The Delivery has no person's changes in the version in question, or has not gone out: there is nothing to record."""

    code = "constraint_conflict"


class AlreadyRecorded(Conflict):
    """The Delivery is already an example with a scope; it is turned off (a person's decision, slice O5) before it is recorded again."""

    code = "constraint_conflict"


def sent_version(row: Mapping[str, Any]) -> int | None:
    """The version that went out: the one the newest sent attempt records."""
    sent = [entry for entry in attempt_log(row) if entry.get("outcome") == ATTEMPT_SENT and entry.get("version") is not None]
    return int(sent[-1]["version"]) if sent else None


def final_version(row: Mapping[str, Any]) -> int | None:
    """The version a person's change is read from: a preferred version saved after the send when there is one, else the version that went out. None while neither exists."""
    if row.get("preferredVersion") is not None:
        return int(row["preferredVersion"])
    return sent_version(row) if row.get("state") == SENT else None


def person_changed(entry: Mapping[str, Any] | None) -> bool:
    """Whether a person's words are in the version: some block is a person's."""
    return bool(entry) and any(block.get("owner") == dt.HUMAN for block in dt.json_list(entry.get("blocks")))


def machine_version(row: Mapping[str, Any], final: int) -> int | None:
    """The newest version at or before ``final`` that no person wrote: the draft the person worked from."""
    machine = [int(entry["number"]) for entry in dt.versions_of(row) if int(entry["number"]) <= final and entry.get("owner") == dt.MACHINE]
    return max(machine) if machine else None


def scope_key(scope: str, channel: str, kind: str) -> str | None:
    """The partition an active example is read from: the publication's, the channel's, or the kind's on the channel. None for a scope that reaches nothing later."""
    if scope == PUBLICATION:
        return global_key("publication")
    if scope == CHANNEL:
        return global_key(f"channel:{channel}")
    if scope == KIND:
        return global_key(f"kind:{channel}:{kind}")
    return None


@dataclass(frozen=True)
class Recorded:
    """The answer to recording: the Delivery as it stands and what happened. ``recorded`` is False when nothing was written (no person's change, or nothing new)."""

    row: dict[str, Any]
    recorded: bool
    state: str | None
    reason: str | None = None


class Examples:
    def __init__(self, deliveries: Deliveries):
        self.deliveries = deliveries
        self.announcements = Announcements(deliveries.client, deliveries)

    def reason_of(self, row: Mapping[str, Any]) -> str | None:
        """The person's one-line reason, from S3, or None."""
        return self.deliveries.files.get(row["id"], REASON_FILE)

    def record(self, delivery_id: str, *, by: str, scope: str | None = None, reason: str | None = None, now: str | None = None) -> Recorded:
        """Record what a person changed in a Delivery that went out (or has a preferred version), and how far it reaches.

        Nothing is written when the final version has no person's words (an unedited send records nothing). With no ``scope`` the edit is kept as a candidate. A candidate, or a
        ``this_one``, is given a wider scope by recording again with it; one that is already active is not recorded again until it is turned off. Recording the same answer twice
        changes nothing."""
        if scope is not None and scope not in SCOPES:
            raise RecordError(f"A scope is one of {', '.join(SCOPES)}: {scope!r} is not.")
        reason = (reason or "").strip() or None
        if reason and "\n" in reason:
            raise RecordError("A reason is one line.")
        if reason and scope is None:
            raise RecordError("A reason goes with the choice of how far the change reaches: choose a scope with it.")
        now = now or now_iso()
        while True:
            row = self.deliveries.get(delivery_id)
            if row is None:
                raise RecordError(f"There is no Delivery {delivery_id}.")
            final = final_version(row)
            if final is None:
                raise NothingToLearn(f"{delivery_id} has not gone out and has no preferred version yet: what a person changed is recorded once it has.")
            if not person_changed(dt.entry_of(row, final)):
                return Recorded(row, False, row.get("exampleState"), f"Nothing recorded: version {final} of {delivery_id} has no words a person changed.")
            state, held = row.get("exampleState"), row.get("exampleScope")
            wanted = CANDIDATE if scope is None else DECLINED if scope == THIS_ONE else ACTIVE
            if state == ACTIVE:
                if scope in (None, held):
                    return Recorded(row, False, state, "Nothing changed: this is already recorded.")
                raise AlreadyRecorded(f"{delivery_id} already teaches the drafter for the scope {held}: turn it off before it is recorded again.")
            if state is not None and (scope is None or (state == wanted and held == scope)):
                return Recorded(row, False, state, "Nothing changed: this is already recorded.")
            changes: dict[str, Any] = {"exampleScope": scope, "exampleState": wanted, "exampleAt": now, "machineVersion": machine_version(row, final),
                                       "exampleKey": scope_key(scope, row["channel"], self._kind_of(row)) if wanted == ACTIVE else None}
            existing = self.reason_of(row) if reason else None
            if reason and existing is not None and existing != reason:
                raise AlreadyRecorded(f"{delivery_id} already has a reason; a recorded reason is not replaced.")
            try:
                written = self.deliveries._change(row, changes, by=by, note=f"example recorded: {changes['exampleState']}" + (f" for {scope}" if scope else ""), now=now)
            except Conflict:
                continue   # somebody wrote the row between the read and the write: read it again and decide again
            if reason and existing is None:
                self.deliveries.files.put(delivery_id, reason, now=now, name=REASON_FILE)
            return Recorded(written, True, written["exampleState"])

    def _kind_of(self, row: Mapping[str, Any]) -> str:
        decision = self.announcements.get(row["announcementId"])
        if decision is None:
            raise RecordError(f"{row['id']} names the Announcement {row['announcementId']}, which does not exist.")
        return str(decision["kind"])
