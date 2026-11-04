"""Filter the entity candidates the extractor proposes, before any node is made and before the AI review sees them (``publish-run``).

The extractor types spans of text with the site's entity kinds, and a span such as ``attachments`` or ``shows`` is only a common word. Three
rules drop a candidate that would become a **new** node. Nothing is hard-coded about a subject or a word: the first two read the site's own
files, the third is learned from the run's own extraction.

* **Stop word.** Every word of the name is on the site's ``config/stop-words.txt`` (the file the topic model reads: words and ``#`` comments,
  whitespace separated) or on the English stop list the topic model starts from (``topic_config.english_stop_words``).
* **Common word.** A one-word, letters-only name that the extractor mostly meets in lower case (a proper noun, an acronym or a model name is
  written with capitals or digits) and that turns up in more documents than is usual for the names of this extraction: more than the upper
  fence of the document counts of all the distinct names (the third quartile plus one and a half times the inter-quartile range). The fence
  is computed from the data of each run and is not a number anyone chose; a multi-word name such as ``dark patterns`` is never judged by it.
* **Undeclared kind.** The kind is not one of the ``entity_kinds`` of the site's ``config/vocabulary.yml``.

A candidate that matches a node already on the map is never filtered: an existing concept is not changed by a machine (``semantic_node_writes``).
A fourth rule applies to every candidate, new or not: a **rejected** name (a rejection by a person or by the AI review, on the map) is dropped and collects no
link, whatever its spelling (the key of ``GPT-4`` and of ``GPT 4`` is one). Every dropped candidate is kept with its reason; ``publish-run`` prints them and counts them by reason.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .keys import entity_key, kind_key, slug
from .topic_config import english_stop_words, read_extra_stop_words

REASON_STOP_WORD = "stop word"
REASON_COMMON_WORD = "common word"
REASON_UNDECLARED_KIND = "kind not in the vocabulary"
REASON_REJECTED = "rejected earlier"


@dataclass(frozen=True)
class Dropped:
    kind: str
    name: str
    reason: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "name": self.name, "reason": self.reason, "detail": self.detail}


def load_stop_words(site_file: Path | str | None) -> frozenset[str]:
    """The English stop list the topic model starts from (when scikit-learn is installed) and the site's own words."""
    try:
        words = set(english_stop_words())
    except ValueError:
        words = set()
    if site_file:
        words.update(read_extra_stop_words(Path(site_file)))
    return frozenset(words)


def vocabulary_kinds(vocabulary_text: str) -> frozenset[str]:
    document = yaml.safe_load(vocabulary_text) or {}
    return frozenset(kind_key(str(row["key"])) for row in document.get("entity_kinds") or [] if isinstance(row, dict) and row.get("key"))


def rejected_keys(node_rows: Iterable[dict]) -> frozenset[str]:
    """The entity keys of the rejected nodes: one for the name and one for each alias, so a rejection also covers the spellings it was given."""
    keys: set[str] = set()
    for row in node_rows:
        if row.get("status") != "rejected":
            continue
        keys.add(str(row.get("nodeKey") or ""))
        for name in [row.get("displayName"), *(row.get("aliases") or ())]:
            keys.add(entity_key(row.get("nodeKind") or "", str(name or "")))
    keys.discard("")
    return frozenset(keys)


def upper_fence(counts: list[int]) -> float | None:
    """The third quartile plus one and a half times the inter-quartile range; ``None`` when there are too few counts to have quartiles."""
    if len(counts) < 2:
        return None
    first, _, third = statistics.quantiles(counts, n=4, method="inclusive")
    return third + 1.5 * (third - first)


def _is_lower(text: str) -> bool:
    return text == text.casefold() and any(character.isalpha() for character in text)


@dataclass
class CandidateFilter:
    stop_words: frozenset[str] = frozenset()
    kinds: frozenset[str] | None = None
    common_words: frozenset[str] = frozenset()
    fence: float | None = None
    rejected: frozenset[str] = frozenset()  # entity keys of the rejected nodes, by their name and their aliases
    dropped: list[Dropped] = field(default_factory=list)
    _seen: set[tuple[str, str]] = field(default_factory=set, repr=False)

    @classmethod
    def learn(cls, typed: Iterable, *, stop_words: frozenset[str] = frozenset(), kinds: frozenset[str] | None = None) -> "CandidateFilter":
        """Learn the common words of this extraction from ``typed`` (the items of the typed-entities output)."""
        documents: dict[str, set[str]] = defaultdict(set)
        mentions: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # lower-case mentions, all mentions
        for item in typed:
            for entity in item.entities:
                identity = slug(entity.text)
                if not identity:
                    continue
                documents[identity].add(item.item_id)
                mentions[identity][1] += 1
                mentions[identity][0] += 1 if _is_lower(entity.text.strip()) else 0
        fence = upper_fence([len(found) for found in documents.values()])
        common = frozenset(
            identity
            for identity, found in documents.items()
            if fence is not None
            and len(found) > fence
            and identity.isalpha()
            and mentions[identity][0] * 2 > mentions[identity][1]
        )
        return cls(stop_words=stop_words, kinds=kinds, common_words=common, fence=fence)

    def reason(self, kind: str, name: str) -> Dropped | None:
        if self.kinds is not None and kind_key(kind) not in self.kinds:
            return Dropped(kind, name, REASON_UNDECLARED_KIND)
        identity = slug(name)
        words = identity.split("-") if identity else []
        if words and all(word in self.stop_words for word in words):
            return Dropped(kind, name, REASON_STOP_WORD)
        if identity in self.common_words:
            return Dropped(kind, name, REASON_COMMON_WORD, f"in more documents than the fence of {self.fence:g}, and mostly written in lower case")
        return None

    def is_rejected(self, kind: str, name: str) -> bool:
        """True when a person or the AI review rejected this name for this kind; it is recorded as dropped (``rejected earlier``)."""
        if entity_key(kind, name) not in self.rejected:
            return False
        self._record(Dropped(kind, name, REASON_REJECTED, "rejected on the map; a rejected name collects no new link"))
        return True

    def _record(self, dropped: Dropped) -> None:
        if (dropped.kind, dropped.name) not in self._seen:
            self._seen.add((dropped.kind, dropped.name))
            self.dropped.append(dropped)

    def check(self, kind: str, name: str) -> bool:
        """True when the candidate may become a node; a dropped one is recorded (once per kind and name) with its reason."""
        dropped = self.reason(kind, name)
        if dropped is None:
            return True
        self._record(dropped)
        return False
