"""The words of a Delivery as versions, blocks and candidates: the pure part (docs/announcement-records.md, "Editing window", PPY-e8ec54).

Every edit of a Delivery is a new version of its text and no version is overwritten. A version is one file in S3 (a ModelAttachment of the Delivery named ``v<number>``);
the row holds the log of versions (``versions``: the file, its key and hash, who saved it and when, which version it replaced) and the key and hash of the newest one. A candidate
is a text or a picture a person or the machine put beside the draft (``candidates``): it is kept whether or not it is chosen, and choosing one saves a new version.

**Blocks.** A text is blocks, separated by blank lines. Every version records, for each block, who owns it and whether it is pinned: ``owner: human, pinned`` is a block a person
changed, and a later machine redraft never overwrites it (the rule the Story translations follow). The block flags are in the version's log entry, in the order of the text's blocks, so
nothing about ownership is in the words themselves.

This module reads no backend: ``deliveries.py`` writes the log and ``delivery_versions.py`` is the one that changes it.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .records import json_list

HUMAN, MACHINE = "human", "machine"
OWNERS = (HUMAN, MACHINE)

OPEN, CHOSEN, KEPT = "open", "chosen", "kept"   # a candidate: not chosen yet, the one chosen, or one left behind when another was chosen
KEEP: Any = object()   # "leave this as it is" for an optional value that may itself be None (a picture a version does not have)

_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def content_hash(text_sha256: str, image_key: str | None) -> str:
    """One hash for the words and the picture that go out together."""
    return hashlib.sha256(f"{text_sha256}\n{image_key or ''}".encode("utf-8")).hexdigest()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def version_file(number: int) -> str:
    return f"v{int(number)}"


def candidate_file(number: int) -> str:
    return f"c{int(number)}"


# --- blocks -------------------------------------------------------------------------------------------------------------------------------------


def split_blocks(text: str) -> list[str]:
    """The blocks of a text: the paragraphs between blank lines, each without the whitespace around it. A text with no words has none."""
    return [block.strip() for block in _BLANK_LINE.split(text.strip()) if block.strip()] if text else []


def join_blocks(blocks: Sequence[str]) -> str:
    return "\n\n".join(blocks)


@dataclass(frozen=True)
class Flags:
    """Who owns one block and whether it is pinned. A pinned block is a person's: only a person changes or unpins it."""

    owner: str
    pinned: bool

    def as_record(self, text: str) -> dict[str, Any]:
        return {"sha256": sha256(text), "owner": self.owner, "pinned": self.pinned}


MACHINE_FLAGS = Flags(MACHINE, False)
HUMAN_FLAGS = Flags(HUMAN, True)


def flags_of(entry: Mapping[str, Any] | None, texts: Sequence[str]) -> list[Flags]:
    """The flags of each block of the text an entry names, in order. A block the log has no flags for (a version made before blocks were recorded) is the machine's, unpinned."""
    recorded = json_list(entry.get("blocks")) if entry else []
    return [Flags(str(recorded[i]["owner"]), bool(recorded[i]["pinned"])) if i < len(recorded) else MACHINE_FLAGS for i in range(len(texts))]


def person_flags(previous: Sequence[tuple[str, Flags]], texts: Sequence[str]) -> list[Flags]:
    """The flags after a person saved ``texts``: a block that is in the version it replaces word for word keeps its flags (wherever it moved to), and every other block is the
    person's and pinned. ``previous`` is that version's blocks with their flags."""
    unused = list(previous)
    flags: list[Flags] = []
    for text in texts:
        match = next((i for i, (old, _) in enumerate(unused) if old == text), None)
        flags.append(unused.pop(match)[1] if match is not None else HUMAN_FLAGS)
    return flags


def merge_redraft(current: Sequence[tuple[str, Flags]], redraft: Sequence[str]) -> tuple[list[str], list[Flags]]:
    """A machine redraft laid over the current version: every pinned block of the current version is in the result, word for word, and the redraft fills the rest.

    A pinned block the redraft reproduced exactly is left where the redraft put it. One it did not is put back where it stood: in place of the redraft's block at its position
    when that block is not itself a pinned one, and otherwise inserted at its position (or at the end when the redraft is shorter). Nothing of a pinned block is the machine's to change."""
    texts = list(redraft)
    flags: list[Flags] = [MACHINE_FLAGS] * len(texts)
    claimed: set[int] = set()
    for position, (text, flag) in enumerate(current):
        if not flag.pinned:
            continue
        same = next((i for i, other in enumerate(texts) if other == text and i not in claimed), None)
        if same is not None:
            flags[same] = flag
            claimed.add(same)
        elif position < len(texts) and position not in claimed:
            texts[position], flags[position] = text, flag
            claimed.add(position)
        else:
            at = min(position, len(texts))
            texts.insert(at, text)
            flags.insert(at, flag)
            claimed = {i + 1 if i >= at else i for i in claimed} | {at}
    return texts, flags


# --- the version log ----------------------------------------------------------------------------------------------------------------------------


def block_records(texts: Sequence[str], flags: Sequence[Flags]) -> list[dict[str, Any]]:
    return [flag.as_record(text) for text, flag in zip(texts, flags)]


def version_entry(number: int, file: str, described: Mapping[str, str], *, image_key: str | None, by: str, owner: str, at: str, replaces: int | None,
                  texts: Sequence[str], flags: Sequence[Flags], **extra: Any) -> dict[str, Any]:
    """One line of a Delivery's version log. ``file`` names the S3 file (a carried version shares its predecessor's); ``key`` and ``sha256`` are that file's."""
    return {"number": int(number), "file": file, "key": described["key"], "sha256": described["sha256"], "imageKey": image_key,
            "contentHash": content_hash(described["sha256"], image_key), "by": by, "owner": owner, "at": at, "replaces": replaces,
            "blocks": block_records(texts, flags), **{name: value for name, value in extra.items() if value is not None}}


def versions_of(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The Delivery's version log, oldest first."""
    return json_list(row.get("versions"))


def candidates_of(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    return json_list(row.get("candidates"))


def entry_of(row: Mapping[str, Any], number: int) -> dict[str, Any] | None:
    return next((entry for entry in versions_of(row) if int(entry["number"]) == int(number)), None)


def head_entry(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """The log line of the Delivery's newest version: none for a draft that has no words yet."""
    return entry_of(row, int(row["version"]))


def sendable_number(row: Mapping[str, Any]) -> int:
    """The version that goes out: the locked one once the Delivery is locked (a later version is a preferred version that never goes in this attempt), otherwise the newest."""
    return int(row["lockedVersion"]) if row.get("lockedVersion") is not None else int(row["version"])


def sendable_entry(row: Mapping[str, Any]) -> dict[str, Any] | None:
    return entry_of(row, sendable_number(row))


def replacing(row: Mapping[str, Any], number: int) -> dict[str, Any] | None:
    """The version that replaced version ``number``: the first line of the log that names it."""
    return next((entry for entry in versions_of(row) if entry.get("replaces") is not None and int(entry["replaces"]) == int(number)), None)
