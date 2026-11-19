"""Saving a Delivery's words: versions, pinned human edits and candidates (docs/announcement-records.md, "Editing window", PPY-e8ec54).

**Every save names the version it replaces.** A save of version ``n + 1`` says it read version ``n``; when the Delivery has moved on it is refused with ``StaleVersion``, whose
message names the version that replaced the one the caller read, who saved it and when (the same answer guidelines and image profiles give). Two saves against one version
therefore leave one winner. A machine redraft is never refused: ``redraft`` drops it and the person's version stays, since theirs is newer.

**A save is a new version, and none is overwritten.** The row is written first, conditional on its ``revision`` (the writer that wins is the only one that then writes the words' file,
so two writers never write one file), and the words second. A crash between them leaves a version whose file is missing; the same call made again finds it and finishes it.

**Pinned blocks.** A block a person changed is ``owner: human, pinned`` (``delivery_text.person_flags``). A machine redraft is laid over the current version
(``delivery_text.merge_redraft``) so every pinned block comes out word for word. Only a person changes or unpins one (``change_pinned``).

**An edit while an attempt is open does not change that attempt, and a person's words after the send are a preferred version too.** The attempt sends the locked version; the
person's edit is saved as the next version, flagged ``preferred`` and named in ``preferredVersion`` (``delivery_examples`` teaches from it; nothing here sends it). **A late edit after the lock is refused** until a person unlocks the Delivery
(``delivery_lock.unlock``).

**Candidates** are texts or pictures kept beside the draft. Adding one changes nothing that goes out, so it is allowed after the lock; choosing one is a save (a new version) and
follows every rule above. The ones not chosen are kept.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from . import delivery_text as dt
from .deliveries import Conflict, Deliveries
from .records import (
    BLOCKED, DELIVERY_WITHDRAWN, DRAFTED, DRY_RUN, LIVE_STATES, NONE, READY, SENT, SUPERSEDED, SYSTEM, RecordError, now_iso, open_attempt_of,
)

SAVED, PREFERRED, UNCHANGED, DROPPED = "saved", "preferred", "unchanged", "dropped"
EDITABLE_STATES = (DRAFTED, READY, BLOCKED)


class StaleVersion(Conflict):
    """The Delivery is no longer at the version the caller read. ``replaced_by`` is the line of the log of the version that replaced it (who, when, which), ``head`` is the newest."""

    code = "stale_version"

    def __init__(self, delivery: str, named: int, head: int, replaced_by: Mapping[str, Any] | None):
        self.named, self.head, self.replaced_by = named, head, dict(replaced_by) if replaced_by else None
        if replaced_by:
            who = f"saved by {replaced_by['by']} at {replaced_by['at']}"
            super().__init__(f"{delivery} is at version {head}: version {replaced_by['number']}, {who}, replaced version {named}, the one you read. "
                             f"Read it again and apply your change to version {head}.")
        else:
            super().__init__(f"{delivery} is at version {head}, not {named}. Read it again and apply your change to version {head}.")


class Locked(RecordError):
    """The Delivery is locked for sending, so a late edit is refused: a person unlocks it first."""

    code = "locked"


class NotEditable(RecordError):
    """The Delivery is not in a state whose words are edited: it is withdrawn, superseded or sent, or it is going out and the editor is a machine."""

    code = "not_editable"


class NoSuchBlock(RecordError):
    code = "not_found"


class NotPinned(RecordError):
    code = "constraint_conflict"


class NoSuchCandidate(RecordError):
    code = "not_found"


@dataclass(frozen=True)
class Composed:
    """What a save is to write, worked out from the Delivery as it is read (so a retry after a conflict composes again from the newer row)."""

    texts: Sequence[str]
    flags: Sequence[dt.Flags]
    image_key: str | None
    text: str | None = None                   # the words as given (a person's text is stored as written); the blocks joined when None
    row_changes: Mapping[str, Any] = field(default_factory=dict)
    entry_extra: Mapping[str, Any] = field(default_factory=dict)
    force: bool = False                       # a save that is a version even when nothing about the words changed (choosing a candidate)


@dataclass(frozen=True)
class Saved:
    """The answer to a save: the Delivery as written (or as it stands), the log line of the new version (None when nothing was saved), and what happened."""

    row: dict[str, Any]
    entry: dict[str, Any] | None
    status: str
    reason: str | None = None

    @property
    def saved(self) -> bool:
        return self.status in (SAVED, PREFERRED)

    @property
    def dropped(self) -> bool:
        return self.status == DROPPED


Compose = Callable[[dict[str, Any], "dict[str, Any] | None", str, int], Composed]


class Versions:
    def __init__(self, deliveries: Deliveries):
        self.deliveries = deliveries

    # --- reads --------------------------------------------------------------------------------------------------------------------------------

    def row(self, delivery_id: str) -> dict[str, Any]:
        found = self.deliveries.get(delivery_id)
        if found is None:
            raise RecordError(f"There is no Delivery {delivery_id}.")
        return found

    def listing(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """The Delivery's versions and candidates as a person reads them: who saved each, when, what it replaced and which blocks are pinned. No words and no keys."""
        versions = [{"number": int(e["number"]), "by": e["by"], "owner": e["owner"], "at": e["at"], "replaces": e.get("replaces"), "preferred": bool(e.get("preferred")),
                     "carried": bool(e.get("carried")), "chosenFrom": e.get("chosenFrom"), "contentHash": e["contentHash"], "imageKey": e.get("imageKey"),
                     "blocks": [{"owner": b["owner"], "pinned": bool(b["pinned"])} for b in dt.json_list(e.get("blocks"))]} for e in dt.versions_of(row)]
        candidates = [{"id": c["id"], "state": c["state"], "by": c["by"], "owner": c["owner"], "at": c["at"], "forVersion": c.get("forVersion"), "chosenAs": c.get("chosenAs"),
                       "imageKey": c.get("imageKey"), "hasText": bool(c.get("key"))} for c in dt.candidates_of(row)]
        return {"id": row["id"], "version": int(row["version"]), "approvedVersion": row.get("approvedVersion"), "lockedVersion": row.get("lockedVersion"),
                "lockedAt": row.get("lockedAt"), "preferredVersion": row.get("preferredVersion"), "versions": versions, "candidates": candidates}

    def text_of_version(self, row: Mapping[str, Any], number: int) -> str:
        entry = dt.entry_of(row, number)
        if entry is None:
            raise NoSuchBlock(f"{row['id']} has no version {number}.")
        text = self.deliveries.text_of(row, entry)
        if text is None:
            raise RecordError(f"The words of version {number} of {row['id']} are missing from S3.")
        return text

    def text_of_candidate(self, row: Mapping[str, Any], candidate_id: str) -> str | None:
        found = self._candidate(row, candidate_id)
        return self.deliveries.files.get(row["id"], found["file"]) if found.get("key") else None

    # --- saving -------------------------------------------------------------------------------------------------------------------------------

    def _mode(self, row: Mapping[str, Any], replaces: int, owner: str, preferred_only: bool = False) -> str:
        """Whether an edit may be made now, and as what: a new version (``saved``) or, while an attempt is open, a preferred version. Otherwise the refusal in plain words."""
        state = row.get("state")
        if state in (SUPERSEDED, DELIVERY_WITHDRAWN, DRY_RUN) or row.get("supersededBy"):
            raise NotEditable(f"{row['id']} is {state}; the words of a Delivery that is {state} are not edited.")
        attempt = open_attempt_of(row)
        if attempt:
            if owner == dt.MACHINE:
                raise NotEditable(f"{row['id']} is going out (attempt {attempt['number']} is open); a machine's redraft is not saved against it.")
            mode = PREFERRED
        elif state == SENT:
            if owner == dt.MACHINE:
                raise NotEditable(f"{row['id']} was sent; a machine's redraft is not saved against it. A person saves how it should have read as a preferred version.")
            mode = PREFERRED   # a person saves how it should have read: never sent, no public text changes (a change to what went out is a correction, a new Delivery)
        elif state not in EDITABLE_STATES:
            raise NotEditable(f"{row['id']} is {state}; only a draft, a ready or a blocked Delivery's words are edited.")
        elif row.get("lockedAt"):
            raise Locked(f"{row['id']} was locked at {row['lockedAt']} with version {row['lockedVersion']} for sending; a late edit needs an explicit unlock by a person first.")
        else:
            mode = SAVED
        if preferred_only and mode != PREFERRED:
            raise NotEditable(f"{row['id']} has not gone out and has no attempt open, so there is no preferred version to save: edit its words with an ordinary save.")
        head = int(row["version"])
        if int(replaces) != head:
            if int(replaces) > head:
                raise RecordError(f"{row['id']} is at version {head}; there is no version {replaces} to replace.")
            raise StaleVersion(row["id"], int(replaces), head, dt.replacing(row, int(replaces)))
        return mode

    def _write(self, delivery_id: str, *, replaces: int, by: str, owner: str, compose: Compose, note: str, checks: Sequence[Mapping[str, Any]] = (),
               retry_of: str | None = None, now: str | None = None, preferred_only: bool = False) -> Saved:
        now = now or now_iso()
        while True:
            row = self.row(delivery_id)
            try:
                mode = self._mode(row, replaces, owner, preferred_only)
            except StaleVersion as stale:
                finished = self._finish_earlier(row, stale, by=by, owner=owner, text=retry_of, now=now)
                if finished is not None:
                    return finished
                raise
            head = dt.head_entry(row)
            head_text = self.deliveries.text(row) if head else ""
            number = int(row["version"]) + (1 if head else 0)   # a draft with no words yet is at version 1 and its first words are that version
            made = compose(row, head, head_text or "", number)
            text = made.text if made.text is not None else dt.join_blocks(made.texts)
            if not text.strip():
                raise RecordError("A version has words: a Delivery's words are not saved empty.")
            blocks = dt.split_blocks(text)
            flags = list(made.flags)
            if (not made.force and head and blocks == dt.split_blocks(head_text or "") and made.image_key == head.get("imageKey")
                    and flags == dt.flags_of(head, blocks)):
                return Saved(row, None, UNCHANGED, "Nothing changed: these are the words of the version you read.")
            name = dt.version_file(number)
            described = self.deliveries.files.describe(row["id"], text, name)
            entry = dt.version_entry(number, name, described, image_key=made.image_key, by=by, owner=owner, at=now, replaces=int(row["version"]) if head else None, texts=blocks, flags=flags,
                                     preferred=True if mode == PREFERRED else None, **dict(made.entry_extra))
            changes: dict[str, Any] = {"version": number, "textKey": described["key"], "contentHash": entry["contentHash"], "imageKey": made.image_key,
                                       "versions": [*dt.versions_of(row), entry], "checks": [dict(check) for check in checks] or None, **dict(made.row_changes)}
            if mode == PREFERRED:
                changes["preferredVersion"] = number
            elif row.get("approval") == NONE:   # fully automatic: the policy approves the new version at once, as it does a Story's next version
                changes.update(approvedVersion=number, approvedBy=SYSTEM, approvedAt=now)
            try:
                written = self.deliveries._change(row, changes, by=by, note=f"{note}: version {number}" + (" (preferred, an attempt is open)" if mode == PREFERRED else ""), now=now)
            except Conflict:
                continue   # somebody wrote the row between the read and the write: read it again and decide again (a stale or a locked answer, or compose on the newer version)
            self.deliveries.files.put(row["id"], text, now=now, name=name)
            return Saved(written, entry, mode)

    def _finish_earlier(self, row: Mapping[str, Any], stale: StaleVersion, *, by: str, owner: str, text: str | None, now: str) -> Saved | None:
        """A save that crashed after its row was written and before its file was: the same call, made again, finds its own version and writes the file."""
        entry = stale.replaced_by
        if not entry or text is None or entry.get("by") != by or entry.get("owner") != owner or entry.get("preferred"):
            return None
        if entry["sha256"] != dt.sha256(text):
            return None
        if self.deliveries.files.get(row["id"], entry["file"]) is None:
            self.deliveries.files.put(row["id"], text, now=now, name=entry["file"])
        return Saved(dict(row), dict(entry), UNCHANGED, f"This save was already made as version {entry['number']}.")

    def save(self, delivery_id: str, *, replaces: int, text: str | None = None, image_key: Any = dt.KEEP, by: str, owner: str = dt.HUMAN,
             checks: Sequence[Mapping[str, Any]] = (), now: str | None = None, preferred_only: bool = False) -> Saved:
        """Save the words (and the picture) as the next version, naming the version read. ``text`` None keeps the words (a change of picture only).

        A person's save marks the blocks it changed as theirs and pinned; a block that is in the version it replaces word for word keeps its flags wherever it moved. A machine's
        (``owner`` machine) is laid over the pinned blocks, which come out unchanged. Refused as ``StaleVersion`` when the Delivery is not at ``replaces``, as ``Locked`` after the
        lock, and (for a machine) as ``NotEditable`` while an attempt is open; for a person an open attempt makes it a preferred version."""
        def compose(row: dict[str, Any], head: dict[str, Any] | None, head_text: str, number: int) -> Composed:
            image = (head.get("imageKey") if head else row.get("imageKey")) if image_key is dt.KEEP else image_key
            given = head_text if text is None else text
            texts = dt.split_blocks(given)
            current_texts = dt.split_blocks(head_text)
            current = list(zip(current_texts, dt.flags_of(head, current_texts)))
            if owner == dt.HUMAN:
                return Composed(texts, dt.person_flags(current, texts), image, text=given)
            merged, flags = dt.merge_redraft(current, texts)
            return Composed(merged, flags, image)

        return self._write(delivery_id, replaces=replaces, by=by, owner=owner, compose=compose, note="saved" if owner == dt.HUMAN else "redrafted", checks=checks,
                           retry_of=text if owner == dt.HUMAN else None, now=now, preferred_only=preferred_only)

    def redraft(self, delivery_id: str, *, replaces: int, text: str, by: str, checks: Sequence[Mapping[str, Any]] = (), now: str | None = None) -> Saved:
        """A machine redraft. When the Delivery has moved on (a person saved a version, it locked, it is going out) the redraft is dropped, never saved over theirs: the person's
        version is newer, and nothing is written."""
        try:
            return self.save(delivery_id, replaces=replaces, text=text, by=by, owner=dt.MACHINE, checks=checks, now=now)
        except (StaleVersion, Locked, NotEditable) as refused:
            return Saved(self.row(delivery_id), None, DROPPED, f"Dropped: {refused}")

    def change_pinned(self, delivery_id: str, *, replaces: int, block: int, by: str, text: str | None = None, unpin: bool = False, now: str | None = None) -> Saved:
        """A person changes the words of a pinned block, or unpins it, as the next version. A block that is not pinned is edited with an ordinary save."""
        if text is None and not unpin:
            raise RecordError("Name what to change in the pinned block: its new words, or to unpin it.")
        if text is not None and dt.split_blocks(text) != [text.strip()]:
            raise RecordError("A block is one paragraph: the new words of a block have no blank line in them.")

        def compose(row: dict[str, Any], head: dict[str, Any] | None, head_text: str, number: int) -> Composed:
            texts = dt.split_blocks(head_text)
            flags = dt.flags_of(head, texts)
            if not 1 <= block <= len(texts):
                raise NoSuchBlock(f"{row['id']} version {row['version']} has {len(texts)} block{'s' if len(texts) != 1 else ''}; there is no block {block}.")
            if not flags[block - 1].pinned:
                raise NotPinned(f"Block {block} of {row['id']} is not pinned, so it is edited with an ordinary save.")
            if text is not None:
                texts[block - 1] = text.strip()
            flags[block - 1] = dt.Flags(dt.HUMAN, not unpin)
            return Composed(texts, flags, head.get("imageKey") if head else None)

        return self._write(delivery_id, replaces=replaces, by=by, owner=dt.HUMAN, compose=compose, note="unpinned a block" if unpin and text is None else "changed a pinned block", now=now)

    # --- candidates ---------------------------------------------------------------------------------------------------------------------------

    @staticmethod
    def _candidate(row: Mapping[str, Any], candidate_id: str) -> dict[str, Any]:
        found = next((c for c in dt.candidates_of(row) if c["id"] == candidate_id), None)
        if found is None:
            raise NoSuchCandidate(f"{row['id']} has no candidate {candidate_id}.")
        return found

    def add_candidate(self, delivery_id: str, *, text: str | None = None, image_key: str | None = None, by: str, owner: str, now: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        """Keep another text or picture beside the draft. It changes nothing that goes out, so the lock does not refuse it; a Delivery that has not gone is all it needs."""
        if not (text and text.strip()) and not image_key:
            raise RecordError("A candidate is a text or a picture.")
        now = now or now_iso()
        while True:
            row = self.row(delivery_id)
            if row.get("state") not in LIVE_STATES or row.get("supersededBy"):
                raise NotEditable(f"{row['id']} is {row.get('state')}; a candidate is kept beside a Delivery that has not gone.")
            existing = dt.candidates_of(row)
            number = max((int(c["number"]) for c in existing), default=0) + 1
            name = dt.candidate_file(number)
            texts = dt.split_blocks(text or "")
            flags = [dt.HUMAN_FLAGS if owner == dt.HUMAN else dt.MACHINE_FLAGS] * len(texts)
            described = self.deliveries.files.describe(row["id"], text, name) if text and text.strip() else None
            candidate = {"id": name, "number": number, "file": name, "key": described["key"] if described else None, "sha256": described["sha256"] if described else None,
                         "imageKey": image_key, "by": by, "owner": owner, "at": now, "forVersion": int(row["version"]), "state": dt.OPEN, "blocks": dt.block_records(texts, flags)}
            try:
                written = self.deliveries._change(row, {"candidates": [*existing, candidate]}, by=by, note=f"candidate {name} added", now=now)
            except Conflict:
                continue
            if described:
                self.deliveries.files.put(row["id"], text, now=now, name=name)
            return written, candidate

    def choose_candidate(self, delivery_id: str, candidate_id: str, *, replaces: int, by: str, owner: str = dt.HUMAN, now: str | None = None) -> Saved:
        """Choose one candidate: a new version with its words and its picture (the current ones where it has none). The others are kept. A machine's choice is laid over the
        pinned blocks like any machine save."""
        def compose(row: dict[str, Any], head: dict[str, Any] | None, head_text: str, number: int) -> Composed:
            found = self._candidate(row, candidate_id)
            words = self.deliveries.files.get(row["id"], found["file"]) if found.get("key") else None
            if found.get("key") and words is None:
                raise RecordError(f"The words of candidate {candidate_id} of {row['id']} are missing from S3.")
            given = words if words is not None else head_text
            texts = dt.split_blocks(given)
            flags = dt.flags_of(found, texts) if words is not None else dt.flags_of(head, texts)
            image = found["imageKey"] if found.get("imageKey") else (head.get("imageKey") if head else None)
            if owner == dt.MACHINE:
                current_texts = dt.split_blocks(head_text)
                texts, flags = dt.merge_redraft(list(zip(current_texts, dt.flags_of(head, current_texts))), texts)
                given = None
            states = [{**c, "state": dt.CHOSEN, "chosenAs": number} if c["id"] == candidate_id else {**c, "state": dt.KEPT} for c in dt.candidates_of(row)]
            return Composed(texts, flags, image, text=given, row_changes={"candidates": states}, entry_extra={"chosenFrom": candidate_id}, force=True)

        return self._write(delivery_id, replaces=replaces, by=by, owner=owner, compose=compose, note=f"chose candidate {candidate_id}", now=now)
