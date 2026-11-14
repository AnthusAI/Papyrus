"""Near-duplicate detection for story ideas, by title-and-text similarity (no network, no model).

Each document is a bag of lower-cased words and word pairs with common words removed and plural endings folded. Similarity is
the cosine of the two vectors weighted by how rare each term is among all the documents being compared, so shared boilerplate
counts for little. An idea is a near-duplicate when it is at least ``threshold`` similar to any story, draft, rejected idea or
earlier idea in the same run. A model-embedding comparison can replace ``similarity`` later without changing the callers.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

FALLBACK_THRESHOLD = 0.5   # used only while a site has too few duplicate decisions to learn its own cut (see duplicate_cut.py)
DEFAULT_THRESHOLD = FALLBACK_THRESHOLD
STOPWORDS = frozenset(
    "a an and are as at be been but by can could did do does for from had has have how if in into is it its more most new no not "
    "of on one or our out over so than that the their them then there these they this to up us was we were what when which who "
    "why will with would you your about after also all any because before between both each few get got just like make many may "
    "much now other only same should some such through under use used using very way well while".split()
)


def terms(text: str) -> list[str]:
    words = [fold(word) for word in re.findall(r"[a-z0-9][a-z0-9'-]*", text.lower())]
    words = [word for word in words if word and word not in STOPWORDS and len(word) > 1]
    return words + [f"{first} {second}" for first, second in zip(words, words[1:])]


def fold(word: str) -> str:
    word = word.strip("'-")
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


@dataclass(frozen=True)
class Document:
    kind: str
    identifier: str
    title: str
    text: str


@dataclass(frozen=True)
class Match:
    kind: str
    identifier: str
    title: str
    score: float

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "id": self.identifier, "title": self.title, "score": self.score}


class WordScorer:
    """Cosine similarity of two texts, with terms weighted by rarity across ``corpus``. The rarity is counted once, so many pairs are cheap."""

    def __init__(self, corpus: list[str]) -> None:
        self.count = len(corpus)
        self.frequency: Counter[str] = Counter()
        for document in corpus:
            self.frequency.update(set(terms(document)))

    def vector(self, text: str) -> dict[str, float]:
        counts = Counter(terms(text))
        return {term: n * (math.log((1 + self.count) / (1 + self.frequency.get(term, 0))) + 1.0) for term, n in counts.items()}

    def __call__(self, left: str, right: str) -> float:
        first, second = self.vector(left), self.vector(right)
        dot = sum(weight * second.get(term, 0.0) for term, weight in first.items())
        norms = math.sqrt(sum(w * w for w in first.values())) * math.sqrt(sum(w * w for w in second.values()))
        return round(dot / norms, 3) if norms else 0.0


Scorer = Callable[[str, str], float]
ScorerFactory = Callable[[list[str]], Scorer]   # the seam: a model-embedding scorer can replace WordScorer without changing the callers


def similarity(left: str, right: str, documents: list[str] | None = None) -> float:
    """Cosine similarity of two texts, with terms weighted by rarity across ``documents`` (the two texts if none are given)."""
    return WordScorer(documents or [left, right])(left, right)


def idea_text(title: str, angle: str) -> str:
    return f"{title}. {title}. {angle}"


def best_match(title: str, angle: str, documents: list[Document], scorer_factory: ScorerFactory = WordScorer) -> Match | None:
    if not documents:
        return None
    candidate = idea_text(title, angle)
    corpus = [candidate] + [idea_text(document.title, document.text) for document in documents]
    score = scorer_factory(corpus)
    scored = [
        Match(document.kind, document.identifier, document.title, score(candidate, text))
        for document, text in zip(documents, corpus[1:])
    ]
    return max(scored, key=lambda match: (match.score, match.identifier))


def split_duplicates(
    ideas: list[dict[str, Any]], documents: list[Document], threshold: float = DEFAULT_THRESHOLD, scorer_factory: ScorerFactory = WordScorer
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keeps the ideas that are new; reports the others with what they resemble. Kept ideas also count against later ones."""
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    known = list(documents)
    for idea in ideas:
        match = best_match(idea["title"], idea["angle"], known, scorer_factory)
        if match is not None and match.score >= threshold:
            dropped.append({"title": idea["title"], "reason": "near_duplicate", "similarTo": match.as_dict(), "threshold": threshold})
            continue
        kept.append(idea)
        known.append(Document("idea", idea.get("ideaId") or idea["title"], idea["title"], idea["angle"]))
    return kept, dropped
