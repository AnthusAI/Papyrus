"""What an editor's own hand says about a Reference, and the one ordering that follows from it (epic PPY-2e9064; docs/idea-context-packs.md, "Editor interest").

Three things an editor does to a Reference are the strongest human signals the pipeline has, and they are independent of each other:

* **stars**: a 1-5 rating (``reference_stars``). Above the midpoint (4, 5) it is interest; below it (1, 2) it is interest *against*; 3 says nothing.
* **a message**: a person wrote a Message in a thread anchored on the Reference.
* **an accept reason**: the words a person wrote when they accepted it.

``interest_key`` is the whole rule, used by every consumer (the single-item queue, the pack members and the packs' order, ``monitor_stories.rank``). It is a
count, not a weight table: each signal that is *for* the Reference counts once, stars that are *against* it take one away, and ties go to the
Reference with more stars, then more messages. So a 5-star accepted Reference with a message from an editor (net 2, 5 stars) is drafted before anything
without both, an accepted Reference with a message and a reason (net 2, no stars) comes right after it, and a Reference rated 1 or 2 stars (net -1 or less
without other signal) waits behind everything neutral: it is still in the queue, only later. Nothing is excluded and nothing is capped.

Stars are not a statistical signal (no p-value): an editor decided. A Reference with no other evidence but good stars therefore still enters the queue.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..reference_stars import MIDPOINT_STARS

if TYPE_CHECKING:
    from .signal_inputs import SignalInputs

#: The sort key of "no editor signal at all". Larger keys are drafted first.
NEUTRAL: tuple[int, int, int] = (0, 0, 0)


@dataclass(frozen=True)
class EditorInterest:
    """What editors did to one Reference: ``stars`` (or None), the human ``messages`` anchored on it and whether an accepting editor gave a ``reason``."""

    stars: int | None = None
    messages: int = 0
    reason: bool = False

    @property
    def for_it(self) -> int:
        """How many independent signals are for the Reference: good stars, a message, an accept reason."""
        return int(self.stars is not None and self.stars > MIDPOINT_STARS) + int(self.messages > 0) + int(self.reason)

    @property
    def against_it(self) -> int:
        return int(self.stars is not None and self.stars < MIDPOINT_STARS)

    @property
    def net(self) -> int:
        return self.for_it - self.against_it

    @property
    def key(self) -> tuple[int, int, int]:
        """Sorts larger first: net signals, then stars, then messages."""
        return (self.net, self.stars or 0, self.messages)

    @property
    def rated_high(self) -> bool:
        return self.stars is not None and self.stars > MIDPOINT_STARS


def interest_key(stars: int | None = None, messages: int = 0, reason: bool = False) -> tuple[int, int, int]:
    return EditorInterest(stars, messages, reason).key


def tier(key: tuple[int, int, int]) -> int:
    """1: editors want it first; 0: no editor decision on it; -1: editors lean against it (still drafted, after the rest).

    Only a rating moves a Reference between tiers. Messages and accept reasons are already counted by the statistical signals (a thread's activity, an accepted
    Reference's reason), so on their own they keep the order those signals give; they matter here when they come *with* stars, where they add to the key."""
    if not key[1]:
        return 0
    return (key[0] > 0) - (key[0] < 0)


def order_key(key: tuple[int, int, int]) -> tuple[int, int, int]:
    """The key to sort by, larger first: the real key for a Reference in a tier, ``NEUTRAL`` for the rest, so unrated Reference keep their order."""
    return key if tier(key) else NEUTRAL


def best_key(keys: "list[tuple[int, int, int]]") -> tuple[int, int, int]:
    return max(keys, default=NEUTRAL)


def interest_from_inputs(inputs: "SignalInputs") -> dict[str, EditorInterest]:
    """The interest of every Reference an editor rated, wrote a Message on, or accepted with a reason, from one read pass (``SignalInputs``)."""
    messages: dict[str, int] = {}
    for message in inputs.messages:
        if message.anchor_key.startswith("reference#"):
            lineage = message.anchor_key.removeprefix("reference#")
            messages[lineage] = messages.get(lineage, 0) + 1
    reasoned = {vote.lineage_id for vote in inputs.votes if vote.status == "accepted" and vote.reason}
    return interest_by_lineage({rating.lineage_id: rating.stars for rating in inputs.ratings}, messages, reasoned)


def interest_by_lineage(
    ratings: Mapping[str, int], messages: Mapping[str, int], reasoned: "set[str] | frozenset[str]",
) -> dict[str, EditorInterest]:
    """An ``EditorInterest`` for every Reference an editor touched in any of the three ways."""
    lineages = set(ratings) | {lineage for lineage, count in messages.items() if count} | set(reasoned)
    return {lineage: EditorInterest(ratings.get(lineage), int(messages.get(lineage, 0)), lineage in reasoned) for lineage in lineages}
