"""Which Stories a roundup issue holds: the inserter's standing rules (PPY-849bf1), as one pure function with no I/O.

The caller gathers the facts (the published rows, each one's rating and when it was rated, the groups, what earlier issues sent, what a person excluded or pinned) and
:func:`select` decides. It returns what goes in, in order, and what was left out, each with its reason, so an editor can steer by restoring or removing.

The rules, in the order they are applied:

1. **Window.** An item belongs to the window by when it became eligible: the later of its publication and the moment it reached the floor, so a late-rated older article
   counts as new when it gets its third star. An item under the floor has no eligibility yet and is looked at by its publication. Nothing is a number of days: the window
   runs from the end of the list's last sent issue (``since``) to now (``until``).
2. **Type.** Only the Story types the list declares. A retired Story never.
3. **Quality.** The site's floor. Unrated and AI-only never qualify.
4. **Sent and excluded.** Never an item an earlier issue sent, never one a person excluded from this issue.
5. **Non-duplication.** One entry per group (same document or same story) in the issue and across issues: the first eligible wins, later ones are left out as duplicates.
6. **Placement.** Into the item's section slot, in the shared quality order (``quality_ranking.rank``), except where a person pinned a position.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from papyrus_content.quality_floor import meets_floor
from papyrus_content.quality_ranking import rank

WRONG_TYPE = "not a type this list carries"
RETIRED = "retired"
BELOW_FLOOR = "below the floor"
ALREADY_SENT = "already sent in an earlier issue"
EXCLUDED = "removed by a person"
DUPLICATE = "duplicate of {title}"


@dataclass(frozen=True)
class Candidate:
    """A published row and the facts the rules need. ``stars`` is the effective human rating (0: unrated); ``eligible_at`` is epoch seconds; ``group`` is the
    same-document or same-story group key, or None when the item is in no group."""

    row: Mapping[str, Any]
    stars: int
    published_at: float
    eligible_at: float
    group: str | None = None

    @property
    def id(self) -> str:
        return str(self.row.get("itemLineageId") or self.row.get("id"))


@dataclass(frozen=True)
class LeftOut:
    candidate: Candidate
    reason: str


@dataclass(frozen=True)
class Selection:
    """``included``: sections in alphabetical order (unsectioned last), each slot in order. ``left_out``: every candidate in the window the rules refused, with why."""

    included: dict[str | None, list[Candidate]]
    left_out: list[LeftOut]

    @property
    def count(self) -> int:
        return sum(len(slot) for slot in self.included.values())


def eligible_at(published_at: float, rated_at: float | None, stars: int, floor: int | None) -> float:
    """When the item became eligible: its publication, or the later moment it reached the floor."""
    if floor is not None and meets_floor(stars, floor) and rated_at is not None:
        return max(published_at, rated_at)
    return published_at


def _place(slot: list[Candidate], pinned: Mapping[str, int], newest_of: Callable[[Candidate], float]) -> list[Candidate]:
    ordered = rank(slot, stars=lambda c: c.stars, newest=newest_of, key=lambda c: str(c.row.get("slug")))
    for item_id, position in sorted(((c.id, pinned[c.id]) for c in ordered if c.id in pinned), key=lambda pair: pair[1]):
        entry = next(c for c in ordered if c.id == item_id)
        ordered.remove(entry)
        ordered.insert(min(max(position, 0), len(ordered)), entry)
    return ordered


def select(
    candidates: Iterable[Candidate],
    *,
    types: Collection[str],
    floor: int | None,
    since: float,
    until: float,
    sent_ids: Collection[str] = (),
    sent_groups: Collection[str] = (),
    excluded: Collection[str] = (),
    pinned: Mapping[str, int] = {},
) -> Selection:
    """Apply the rules to ``candidates``. ``pinned`` maps an item id to the position a person gave it inside its slot."""
    chosen: list[Candidate] = []
    left_out: list[LeftOut] = []
    taken_groups: dict[str, Candidate] = {}
    ordered = sorted(candidates, key=lambda c: (c.eligible_at, str(c.row.get("slug"))))
    for candidate in ordered:
        moment = candidate.eligible_at if meets_floor(candidate.stars, floor) else candidate.published_at
        if not since < moment <= until:
            continue
        if candidate.row.get("status") not in (None, "published"):
            left_out.append(LeftOut(candidate, RETIRED))
        elif candidate.row.get("type") not in types:
            left_out.append(LeftOut(candidate, WRONG_TYPE))
        elif not meets_floor(candidate.stars, floor):
            left_out.append(LeftOut(candidate, BELOW_FLOOR))
        elif candidate.id in sent_ids:
            left_out.append(LeftOut(candidate, ALREADY_SENT))
        elif candidate.id in excluded:
            left_out.append(LeftOut(candidate, EXCLUDED))
        elif candidate.group is not None and (candidate.group in sent_groups or candidate.group in taken_groups):
            first = taken_groups.get(candidate.group)
            title = str(first.row.get("title") or first.row.get("slug")) if first else "an item an earlier issue sent"
            left_out.append(LeftOut(candidate, DUPLICATE.format(title=title)))
        else:
            chosen.append(candidate)
            if candidate.group is not None:
                taken_groups[candidate.group] = candidate
    slots: dict[str | None, list[Candidate]] = {}
    for candidate in chosen:
        slots.setdefault(candidate.row.get("section") or None, []).append(candidate)
    newest = lambda c: c.eligible_at  # noqa: E731
    included = {section: _place(slots[section], pinned, newest) for section in sorted(slots, key=lambda name: (name is None, name or ""))}
    return Selection(included, left_out)
