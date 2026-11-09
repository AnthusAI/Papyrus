"""A deterministic stand-in for the topic engine, for tests and for trying the command without a model.

It groups documents by shared words: the commonest word first, then the next, each group taking the documents it has not taken yet, and a group
counts only when it reaches the cluster size. The same documents always give the same topics.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Sequence

from .engine import FoundTopic, TopicDocument

STOP = frozenset("a an and are as at be by for from in is it its of on or that the this to was with".split())
WORD = re.compile(r"[a-z][a-z0-9]{2,}")


def words(text: str) -> set[str]:
    return {word for word in WORD.findall(text.casefold()) if word not in STOP}


class FakeTopicEngine:
    name = "fake"
    version = "1"

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], int]] = []

    def model(self, documents: Sequence[TopicDocument], *, min_cluster_size: int) -> list[FoundTopic]:
        self.calls.append((tuple(document.id for document in documents), min_cluster_size))
        by_id = {document.id: words(document.text) for document in documents}
        frequency = Counter(word for found in by_id.values() for word in found)
        taken: set[str] = set()
        topics = []
        for word, _ in sorted(frequency.items(), key=lambda item: (-item[1], item[0])):
            members = [identifier for identifier, found in by_id.items() if word in found and identifier not in taken]
            if len(members) < min_cluster_size:
                continue
            inside = Counter(other for identifier in members for other in by_id[identifier])
            terms = tuple(term for term, _ in sorted(inside.items(), key=lambda item: (-item[1], item[0]))[:6])
            topics.append(FoundTopic(terms=terms, member_ids=tuple(members)))
            taken.update(members)
        return topics
