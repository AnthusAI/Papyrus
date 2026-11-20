"""The roundup issue as a living Story: blocks with one owner each, and the rules for writing them (PPY-4108ef). Pure: no I/O, no clock, no ids made here.

The issue document has a fixed set of blocks. **Machine-owned:** the entries in each section slot (a reference to a Story by id, with who added it, when and why).
**Human-owned:** subject, preheader, intro, outro, section headings, an entry's copy override, and entry order pins. Every write is a new version carrying its actor
and the blocks it touched, and names the version it started from, so two writers on disjoint blocks both land (a rebase, not a text merge) and two writers on the
same block never overwrite each other silently: the second is told and sees the newer text.

* A human edit to a machine entry (copy, position, or keep) PINS it: the machine never changes, moves or removes it for ordinary reasons.
* Once a human has touched a human-owned field only humans change it; an agent that wants to change it posts a suggestion instead (:class:`NeedsSuggestion`).
* A person removing an entry writes an exclusion with a required reason; the inserter never re-adds it for this issue until a person restores it.
* The quality floor outranks pins: an entry under the floor is removed even if pinned, recorded as ``below floor`` (not an exclusion). If it is rated up again the
  inserter may add it back with the person's copy intact, unless a person excluded it.
* An admin approves a version (its fingerprint) for a time. The inserter is paused while approved. Any edit afterwards, by a person or by a below-floor removal,
  returns the issue to draft ("edited after approval; approve again"). An issue with no entries cannot be approved.

Nothing here knows where the document is stored; the caller loads it at a version, applies one operation and saves the result conditionally on that version.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

HUMAN_FIELDS = ("subject", "preheader", "intro", "outro")
EDITED_AFTER_APPROVAL = "edited after approval; approve again"
BELOW_FLOOR = "below floor"


class IssueError(Exception):
    """A write the rules refuse."""


class Conflict(IssueError):
    """Someone else wrote the same block since the writer's base version. ``current`` is the newer text, for the writer to decide on."""

    def __init__(self, block: str, current: Any) -> None:
        super().__init__(f"{block} changed since your version")
        self.block, self.current = block, current


class NeedsSuggestion(IssueError):
    """An agent tried to write a block a person has touched: it posts a suggestion in the Story's Conversation instead."""


class NotAllowed(IssueError):
    pass


@dataclass(frozen=True)
class Entry:
    """A machine entry: a Story by id in a section slot. ``copy`` is a person's override of its blurb; ``position`` a person's order pin inside the slot."""

    id: str
    section: str | None
    added_by: str
    added_at: str
    reason: str
    copy: str | None = None
    position: int | None = None
    keep: bool = False

    @property
    def pinned(self) -> bool:
        return self.copy is not None or self.position is not None or self.keep


@dataclass(frozen=True)
class Exclusion:
    id: str
    by: str
    at: str
    reason: str
    restored_by: str | None = None
    restored_at: str | None = None

    @property
    def active(self) -> bool:
        return self.restored_at is None


@dataclass(frozen=True)
class Version:
    number: int
    actor: str
    human: bool
    blocks: tuple[str, ...]


@dataclass(frozen=True)
class Approval:
    by: str
    send_at: str
    fingerprint: str


@dataclass(frozen=True)
class Issue:
    """One issue of one list and period. ``fields`` holds the human-owned text, ``touched`` the fields a person has ever written, ``removed`` the machine
    removals (below floor) with the entry kept so a re-rating can bring it back intact."""

    list_id: str
    period: str
    version: int = 1
    fields: Mapping[str, str] = field(default_factory=dict)
    headings: Mapping[str, str] = field(default_factory=dict)
    entries: tuple[Entry, ...] = ()
    exclusions: tuple[Exclusion, ...] = ()
    removed: tuple[tuple[Entry, str], ...] = ()
    touched: frozenset[str] = frozenset()
    approval: Approval | None = None
    note: str = ""
    log: tuple[Version, ...] = (Version(1, "scheduler", False, ("created",)),)

    @property
    def status(self) -> str:
        return "approved" if self.approval else "draft"

    def entry(self, item_id: str) -> Entry | None:
        return next((entry for entry in self.entries if entry.id == item_id), None)

    def excluded(self, item_id: str) -> bool:
        return any(record.id == item_id and record.active for record in self.exclusions)


def fingerprint(issue: Issue) -> str:
    """What an approval approves: the human text and the entries, in slot order, with their copy. Who added what and when is not part of it."""
    material = {
        "fields": {name: issue.fields.get(name, "") for name in HUMAN_FIELDS},
        "headings": dict(sorted(issue.headings.items())),
        "entries": [[entry.section, entry.id, entry.copy] for entry in ordered(issue)],
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()


def ordered(issue: Issue) -> list[Entry]:
    """Entries by section slot (alphabetical, unsectioned last), each slot by the entries' order: pinned positions first where given, the rest as added."""
    slots: dict[str | None, list[Entry]] = {}
    for entry in issue.entries:
        slots.setdefault(entry.section, []).append(entry)
    out: list[Entry] = []
    for section in sorted(slots, key=lambda name: (name is None, name or "")):
        slot = [entry for entry in slots[section] if entry.position is None]
        for entry in sorted((entry for entry in slots[section] if entry.position is not None), key=lambda entry: entry.position):  # type: ignore[arg-type,return-value]
            slot.insert(min(entry.position, len(slot)), entry)  # type: ignore[arg-type]
        out += slot
    return out


def _since(issue: Issue, base: int) -> list[Version]:
    return [version for version in issue.log if version.number > base]


def _commit(issue: Issue, actor: str, human: bool, blocks: tuple[str, ...], **changes: Any) -> Issue:
    """The next version. A write by a person after approval returns the issue to draft; the machine's own writes cannot happen while approved (the inserter is paused)."""
    version = issue.version + 1
    returned = issue.approval is not None and "approval" not in changes
    note = EDITED_AFTER_APPROVAL if returned else changes.pop("note", issue.note)
    return replace(issue, version=version, log=issue.log + (Version(version, actor, human, blocks),), **({"approval": None, "note": note} if returned else {"note": note}), **changes)


def _check_base(issue: Issue, base: int, block: str, current: Any) -> None:
    if base > issue.version:
        raise IssueError(f"version {base} does not exist")
    if any(block in version.blocks for version in _since(issue, base)):
        raise Conflict(block, current)


# -- people ------------------------------------------------------------------------------------------------------------


def edit_field(issue: Issue, *, base: int, actor: str, human: bool, name: str, value: str) -> Issue:
    """Write subject, preheader, intro or outro. An agent may write it only while no person has ever touched it; a second writer of the same field is told."""
    if name not in HUMAN_FIELDS:
        raise NotAllowed(f"{name} is not a human-owned field")
    if not human and name in issue.touched:
        raise NeedsSuggestion(name)
    _check_base(issue, base, name, issue.fields.get(name, ""))
    return _commit(issue, actor, human, (name,), fields={**issue.fields, name: value}, touched=issue.touched | ({name} if human else set()))


def edit_heading(issue: Issue, *, base: int, actor: str, section: str, text: str) -> Issue:
    block = f"heading:{section}"
    _check_base(issue, base, block, issue.headings.get(section, ""))
    return _commit(issue, actor, True, (block,), headings={**issue.headings, section: text})


def edit_entry(issue: Issue, *, base: int, actor: str, item_id: str, copy: str | None = None, position: int | None = None, keep: bool | None = None) -> Issue:
    """A person rewrites an entry's blurb, moves it, or marks it keep. The entry is pinned from then on."""
    entry = issue.entry(item_id)
    if entry is None:
        raise NotAllowed(f"{item_id} is not in this issue")
    block = f"entry:{item_id}"
    _check_base(issue, base, block, entry)
    changed = replace(entry, copy=entry.copy if copy is None else copy, position=entry.position if position is None else position, keep=entry.keep if keep is None else keep)
    if not changed.pinned:
        changed = replace(changed, keep=True)
    return _commit(issue, actor, True, (block,), entries=tuple(changed if candidate.id == item_id else candidate for candidate in issue.entries))


def remove_entry(issue: Issue, *, base: int, actor: str, item_id: str, reason: str, at: str) -> Issue:
    """A person removes an entry, with a required one-line reason. The exclusion stays in the history; the inserter never adds the Story back to this issue."""
    if not " ".join(reason.split()):
        raise NotAllowed("a reason is required to remove an entry")
    entry = issue.entry(item_id)
    if entry is None:
        raise NotAllowed(f"{item_id} is not in this issue")
    _check_base(issue, base, f"entry:{item_id}", entry)
    return _commit(
        issue, actor, True, (f"entry:{item_id}", "exclusions"),
        entries=tuple(candidate for candidate in issue.entries if candidate.id != item_id),
        exclusions=issue.exclusions + (Exclusion(item_id, actor, at, " ".join(reason.split())),),
    )


def restore_entry(issue: Issue, *, base: int, actor: str, item_id: str, at: str) -> Issue:
    """A person undoes an exclusion: a new record marks it restored (nothing is deleted); the inserter may add the Story again."""
    if not issue.excluded(item_id):
        raise NotAllowed(f"{item_id} is not excluded")
    _check_base(issue, base, "exclusions", issue.exclusions)
    return _commit(issue, actor, True, ("exclusions",), exclusions=tuple(replace(record, restored_by=actor, restored_at=at) if record.id == item_id and record.active else record for record in issue.exclusions))


# -- the machine -------------------------------------------------------------------------------------------------------


def insert(issue: Issue, *, base: int, actor: str, found: list[tuple[str, str | None, str]], at: str) -> Issue:
    """The inserter adds machine entries: ``found`` is ``(item id, section, reason)`` for each Story the selection chose. It writes only the entries block, skips Stories
    already in the issue or excluded by a person, brings back an entry the floor removed with its person's copy intact, and does nothing while the issue is approved."""
    if issue.approval is not None:
        return issue
    _check_base(issue, base, "entries", issue.entries)
    removed = {entry.id: entry for entry, _reason in issue.removed}
    added = []
    for item_id, section, reason in found:
        if issue.entry(item_id) is not None or issue.excluded(item_id):
            continue
        previous = removed.get(item_id)
        added.append(replace(previous, section=section) if previous else Entry(item_id, section, actor, at, reason))
    if not added:
        return issue
    return _commit(issue, actor, False, ("entries",), entries=issue.entries + tuple(added), removed=tuple(pair for pair in issue.removed if pair[0].id not in {entry.id for entry in added}))


def drop_below_floor(issue: Issue, *, actor: str, stars: Mapping[str, int], floor: int) -> Issue:
    """The floor outranks pins: every entry whose rating fell under ``floor`` is removed, even a pinned one, and recorded as ``below floor``. An approved issue returns
    to draft (nothing is sent)."""
    low = [entry for entry in issue.entries if stars.get(entry.id, 0) < floor]
    if not low:
        return issue
    ids = {entry.id for entry in low}
    return _commit(
        issue, actor, False, ("entries",),
        entries=tuple(entry for entry in issue.entries if entry.id not in ids),
        removed=issue.removed + tuple((entry, BELOW_FLOOR) for entry in low),
    )


# -- approval ----------------------------------------------------------------------------------------------------------


def approve(issue: Issue, *, actor: str, admin: bool, send_at: str) -> Issue:
    """An admin approves exactly this version for a time. Editors cannot; an issue with no entries cannot be approved."""
    if not admin:
        raise NotAllowed("only an admin approves an issue")
    if not issue.entries:
        raise NotAllowed("an issue with no entries cannot be approved")
    return _commit(issue, actor, True, ("approval",), approval=Approval(actor, send_at, fingerprint(issue)), note="")


def ready_to_send(issue: Issue) -> bool:
    """At fire time: still approved, and the content is what was approved."""
    return issue.approval is not None and issue.approval.fingerprint == fingerprint(issue) and bool(issue.entries)
