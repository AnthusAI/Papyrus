"""What the drafter learned from people's edits, read for one draft (PPY-d99bd0, slice O3; docs/announcement-learning.md).

Before a draft the drafter loads the **active examples** that apply to the channel and kind it is writing for: the publication's, the channel's and the kind's on the channel, merged
newest first, each read from the sparse ``deliveriesByExample`` index (``exampleKey`` is present only while an example is active, so an off or absorbed one is not read, and nothing is scanned).
An example is the machine's draft beside the words a person made of it and, when they gave one, why. The examples go into the prompt within a character budget (the context pack's
default): the newest come first and reading stops when the budget is spent. The answer names the Delivery of every example it used (``ids``), and the Delivery being drafted records them
with the guideline layers it read (``recorded``), so "why did it write this?" always has an answer (``papyrus announcements explain --delivery``).
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from papyrus_content.newsroom_context_pack import DEFAULT_MAX_CHARACTERS

from . import delivery_text as dt
from .deliveries import Deliveries
from .delivery_examples import CHANNEL, INDEX_BY_EXAMPLE, KIND, PUBLICATION, REASON_FILE, final_version, scope_key

HEADING = "Earlier drafts a person rewrote, newest first. Follow what they changed where it applies to this Story, and copy none of their words as they stand:"


@dataclass(frozen=True)
class Example:
    delivery: str
    scope: str
    before: str
    after: str
    reason: str | None = None


@dataclass
class Read:
    """The examples one draft read, newest first, and the words that go into its prompt. ``dropped`` counts the ones the budget left out."""

    examples: list[Example] = field(default_factory=list)
    dropped: int = 0

    @property
    def ids(self) -> list[str]:
        return [example.delivery for example in self.examples]

    @property
    def prompt(self) -> str:
        if not self.examples:
            return ""
        lines = [HEADING]
        for number, example in enumerate(self.examples, 1):
            lines.append(f"Example {number} (applies to the {example.scope}):\nDraft: {example.before}\nPerson's version: {example.after}" + (f"\nWhy: {example.reason}" if example.reason else ""))
        return "\n\n".join(lines)


def partitions(channel: str, kind: str) -> list[str]:
    return [key for key in (scope_key(PUBLICATION, channel, kind), scope_key(CHANNEL, channel, kind), scope_key(KIND, channel, kind)) if key]


def load(deliveries: Deliveries, *, channel: str, kind: str, budget: int = DEFAULT_MAX_CHARACTERS, words_of: Callable[[str], str] = str.strip) -> Read:
    """The active examples for the channel and kind, newest first, as many as the character ``budget`` holds. ``words_of`` takes what is not the writing out of a Delivery's words (the link
    an X post ends with); a Delivery whose words are missing is left out, since an example is nothing without them."""
    streams = [deliveries.client.iterate_newest_first(INDEX_BY_EXAMPLE, key) for key in partitions(channel, kind)]
    read, spent = Read(), 0
    for row in heapq.merge(*streams, key=lambda row: str(row.get("exampleAt") or ""), reverse=True):
        example = _example(deliveries, row, words_of)
        if example is None:
            continue
        cost = len(example.before) + len(example.after) + len(example.reason or "")
        if spent + cost > budget:
            read.dropped += 1
            break   # newest first: what is older is left out too, and no further page is fetched
        read.examples.append(example)
        spent += cost
    return read


def _example(deliveries: Deliveries, row: Mapping[str, Any], words_of: Callable[[str], str]) -> Example | None:
    final = final_version(row)
    if final is None or row.get("machineVersion") is None:
        return None
    before = deliveries.files.get(row["id"], dt.version_file(int(row["machineVersion"])))
    after = deliveries.files.get(row["id"], dt.version_file(final))
    if before is None or after is None:
        return None
    return Example(delivery=row["id"], scope=str(row.get("exampleScope")), before=words_of(before), after=words_of(after), reason=deliveries.files.get(row["id"], REASON_FILE))


def recorded(read: Read) -> dict[str, Any]:
    """The part of the inputs line a draft records for the examples it read: the Delivery of each, in the order they were given."""
    return {"examples": read.ids}
