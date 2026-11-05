"""Which blocks a changed row can touch, decided from the change alone (docs/plans/public-blocks-from-indexes.md, "How a change reaches the pages").

The stream trigger records, for each change, a small *coordinate*: the row's id, its public keys before and after, its accepted time and star count before and
after, its medium, and a hash of what its card shows. Nothing is read to decide: a block remembers the ids of the rows it pulled, the coordinates of the last
one (its frontier) and whether it came up short (``indexed.Block.state``), and a change touches a block when

* the row is one the block pulled (its card or its place changed), or
* the row can be public in the block's partition and sorts ahead of the block's frontier (it enters), or
* the block came up short and the row can be public in its partition (it fills the gap).

A row that touches no block is dropped without a request: a new recommended Reference at 0.62 does not reach a block that shows the top six, and an unpredicted
one never reaches a block at all. A state that is missing, from another build or for another day is not repaired: its block is simply treated as touched.
Where the order is not known from the coordinate (a ``section`` filter), the router errs towards touching.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from .ordering import _primary, bucket_moment, rolling_age, valid_stars

STATE_FORMAT = 1
CARD_HASH_FIELDS = ("title", "cardImage", "cardSummary", "cardSiteName", "cardPageTitle", "medium", "curationSectionId", "thumbnailPath", "curationActorKind", "sourceUri")


def card_hash(values: Mapping[str, Any]) -> str:
    """A short hash of what a card shows besides its place; the trigger computes the same from the typed image (``handler.py``), a test holds the two together."""
    material = json.dumps([values.get(name) for name in CARD_HASH_FIELDS], separators=(",", ":"), default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class Coordinate:
    """One change as the trigger recorded it: ``0`` is before, ``1`` after (missing when the row was created or removed)."""

    identifier: str
    feed0: str | None = None
    feed1: str | None = None
    order0: str | None = None
    order1: str | None = None
    stars0: int | None = None
    stars1: int | None = None
    accepted0: str | None = None
    accepted1: str | None = None
    medium0: str | None = None
    medium1: str | None = None
    hash0: str | None = None
    hash1: str | None = None
    section0: str | None = None
    section1: str | None = None

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "Coordinate":
        return cls(str(value["i"]), value.get("f0"), value.get("f1"), value.get("o0"), value.get("o1"), value.get("s0"), value.get("s1"), value.get("a0"), value.get("a1"),
                   value.get("m0"), value.get("m1"), value.get("h0"), value.get("h1"), value.get("x0"), value.get("x1"))

    def to_json(self) -> dict[str, Any]:
        full = {"i": self.identifier, "f0": self.feed0, "f1": self.feed1, "o0": self.order0, "o1": self.order1, "s0": self.stars0, "s1": self.stars1, "a0": self.accepted0,
                "a1": self.accepted1, "m0": self.medium0, "m1": self.medium1, "h0": self.hash0, "h1": self.hash1, "x0": self.section0, "x1": self.section1}
        return {name: value for name, value in full.items() if value is not None}


def parse_order(order: str | None) -> tuple[float | None, str]:
    """``(stored prediction or None, arrival)`` from a ``publicOrderKey`` (``p<P>#<arrival>#<id>`` or ``n#<arrival>#<id>``)."""
    if not order:
        return None, ""
    head, _, rest = order.partition("#")
    arrival = rest.split("#", 1)[0]
    if head.startswith("p"):
        try:
            return float(head[1:]), arrival
        except ValueError:
            return None, arrival
    return None, arrival


def _accepts(feed: str | None) -> bool:
    return bool(feed) and feed.endswith("#accepted")


def _recommends(feed: str | None) -> bool:
    return bool(feed) and "#recommended#" in feed


def _ahead(selection: str, bucket: str | None, as_of: date | None, state: Mapping[str, Any], stars: int | None, accepted: str | None, order: str | None) -> bool:
    """True when a row with these coordinates sorts at or ahead of the block's last pulled row (a tie counts: touching is the safe answer)."""
    frontier = state.get("frontier")
    if not frontier:
        return True
    probability, arrival = parse_order(order)
    if bucket and as_of is not None:
        row_moment = accepted if selection != "recommended" and accepted else arrival
        edge = bucket_moment({"acceptedAt": frontier.get("acceptedAt") or None, "arrivedAt": frontier.get("arrivedAt")})
        mine, theirs = rolling_age(row_moment, bucket, as_of), rolling_age(edge, bucket, as_of)
        if mine != theirs:
            return mine < theirs
        # inside one window the shared order applies, whatever the selection
        first, second = _primary(valid_stars(stars), probability), _primary(valid_stars(frontier.get("stars")), frontier.get("probability"))
        return first < second or (first == second and arrival >= (frontier.get("arrivedAt") or ""))
    if selection == "recent":
        return (accepted or "", arrival) >= (frontier.get("acceptedAt") or "", frontier.get("arrivedAt") or "")
    mine, theirs = _primary(valid_stars(stars), probability), _primary(valid_stars(frontier.get("stars")), frontier.get("probability"))
    return mine < theirs or (mine == theirs and arrival >= (frontier.get("arrivedAt") or ""))


def block_touched(state: Mapping[str, Any] | None, coordinate: Coordinate, *, as_of: date) -> bool:
    """Whether one change can alter one block. ``state`` is what the block remembered (``None``: it never ran, so it is touched)."""
    if state is None:
        return True
    attributes = state.get("attributes") or {}
    if coordinate.identifier in set(state.get("ids") or ()):
        return True
    selection, bucket, medium = str(attributes.get("select")), attributes.get("bucket"), attributes.get("medium")
    wants_accepted = selection != "recommended"
    partition = _accepts if wants_accepted else _recommends
    if state.get("whole"):   # a paged list: a row that is, or was, in the block's partition changes the list
        relevant = partition(coordinate.feed1) or partition(coordinate.feed0)
        if not relevant or (medium and coordinate.medium1 != medium and coordinate.medium0 != medium):
            return False
        return not attributes.get("section") or bool({coordinate.section0, coordinate.section1} & set(state.get("sectionIds") or ()))
    relevant = partition(coordinate.feed1)
    if not relevant or (medium and coordinate.medium1 != medium):
        return False
    if attributes.get("section") and coordinate.section1 not in set(state.get("sectionIds") or ()):
        return False   # a row in another section cannot enter a block of this one (a section's rename is not a Reference change: the next full run draws the new label)
    if state.get("short"):
        return True
    state_day = state.get("asOf")
    block_day = date.fromisoformat(state_day) if state_day else as_of
    return _ahead(selection, bucket, block_day if bucket else None, state, coordinate.stars1, coordinate.accepted1, coordinate.order1)


def touched_blocks(states: Mapping[str, Mapping[str, Any]], wanted: Iterable[str], coordinates: Iterable[Coordinate], *, as_of: date) -> set[str]:
    """The keys among ``wanted`` that at least one change can alter; a key with no remembered state is touched."""
    changes = list(coordinates)
    return {key for key in wanted if key not in states or any(block_touched(states[key], change, as_of=as_of) for change in changes)}
