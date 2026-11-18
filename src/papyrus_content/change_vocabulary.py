"""The changes an agent definition may listen for (``wakes.changes``): one list, read by the definition check and by the feeds (PPY-8a374e, PPY-9b9e64).

Each record kind has a feed that turns a change to a row of its table into a normalized change (``item_change_feed.py`` for Item, ``change_feeds.py`` for
the rest). A definition names a kind and one of that kind's changes, so a definition that listens for a change no feed can produce is refused when it is read,
not found missing when it never wakes. The list is the feeds' own: a feed names its changes from here, and a test holds the two together.

* Item           version_created, stage_entered, step_changed
* Reference      created, accepted, rated, recaptured
* ReviewRequest  answered                (wakes the agent that asked, and only if it listens)
* Message        posted                  (a comment on a subject; the wake is for that subject's listeners)
* LocalizationRequest  wanted
* Delivery       state_changed
"""
from __future__ import annotations

CHANGES: dict[str, tuple[str, ...]] = {
    "Item": ("version_created", "stage_entered", "step_changed"),
    "Reference": ("created", "accepted", "rated", "recaptured"),
    "ReviewRequest": ("answered",),
    "Message": ("posted",),
    "LocalizationRequest": ("wanted",),
    "Delivery": ("state_changed",),
}

#: The tables whose feed is ``change_feeds.py`` (the Item table has its own function, ``item_change_feed.py``).
FEED_TABLES = tuple(kind for kind in CHANGES if kind != "Item")


def known(kind: str, change: str) -> bool:
    return change in CHANGES.get(kind, ())


def describe() -> str:
    """The vocabulary as one line for an error message."""
    return "; ".join(f"{kind}: {', '.join(changes)}" for kind, changes in CHANGES.items())
