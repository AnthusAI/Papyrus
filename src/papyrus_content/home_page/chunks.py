"""Where a long, ranked list of References is cut into data files, so that a change near the top rewrites a few files and not all of them.

A list that is cut every N items is stable only until something is inserted: one new Reference at the top moves every cut after it, and every file after
it changes. Here the cut comes from the Reference itself (content-defined chunking): a chunk ends after a Reference whose key hashes to a cut, once it
has at least ``minimum`` items, and always after ``maximum``. A cut depends on the key and on how far the chunk has run, not on the position in the
whole list, so after an insertion or a removal the cuts find their old places again within a chunk or two and every later chunk is byte for byte what it
was. A chunk is named by the key of its first Reference, so an unchanged chunk keeps its name and its address.

The cuts are public and need no private data: keys are already in the public snapshot.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    name: str
    keys: tuple[str, ...]
    next: str | None   # the name of the chunk after this one; None for the last


def chunk_name(first_key: str) -> str:
    """``c`` and ten hex digits of the key of the chunk's first Reference: stable while that Reference starts the chunk."""
    return "c" + hashlib.sha256(first_key.encode("utf-8")).hexdigest()[:10]


def _is_cut(key: str, window: int) -> bool:
    return int.from_bytes(hashlib.sha256(b"cut:" + key.encode("utf-8")).digest()[:4], "big") % window == 0


def bounds(target: int) -> tuple[int, int, int]:
    """``(minimum, maximum, window)`` for a typical chunk of ``target`` items: chunks run from a quarter of it to twice it, about ``target`` on average."""
    minimum = max(1, target // 4)
    return minimum, target * 2, max(1, target - minimum)


def split(keys: Sequence[str], target: int) -> list[Chunk]:
    """``keys`` (a list in its display order) cut into chunks of about ``target``; each chunk names the one after it."""
    minimum, maximum, window = bounds(target)
    groups: list[list[str]] = []
    run: list[str] = []
    for key in keys:
        run.append(key)
        if len(run) >= maximum or (len(run) >= minimum and _is_cut(key, window)):
            groups.append(run)
            run = []
    if run:
        groups.append(run)
    names = [chunk_name(group[0]) for group in groups]
    return [Chunk(name, tuple(group), names[index + 1] if index + 1 < len(names) else None) for index, (name, group) in enumerate(zip(names, groups))]
