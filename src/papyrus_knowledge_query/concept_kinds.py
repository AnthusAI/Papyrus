"""Which semantic nodes are concepts an editor could link a Reference to, and which are the graph's own bookkeeping.

A site's graph holds, besides its vocabulary (models, tasks, topics, products and the like), nodes that are not subjects: the paper authors, the editorial
concepts a comment is filed under, quality ratings, relevance decisions, coverage questions, editorial forms, and the bulk-extracted entities and identifiers.
The public wiki already leaves these out (``papyrus_content.knowledge_wiki.kinds``, commit 82670d24); concept cards and concept suggestions leave them out
too, by kind and, where a node's kind is missing, by the prefix of its key.

This module has no dependencies so the vector index (and so the monitoring router's zip) can use it; ``test_concept_kinds`` keeps its list equal to the wiki's.
A caller that wants only some kinds passes them as ``allowed`` (an allowlist); with none, every kind but these is a concept.
"""
from __future__ import annotations

import re
from collections.abc import Iterable


def kind_token(kind: str | None) -> str:
    """``commentConcept``, ``comment_concept`` and ``comment-concept`` are one kind."""
    return re.sub(r"[^a-z0-9]", "", str(kind or "").lower())


#: The wiki's bookkeeping kinds and the authors, plus the kinds a bulk extraction produces (named entities, identifiers such as arXiv ids).
NON_CONCEPT_KINDS = frozenset(kind_token(kind) for kind in (
    "commentConcept", "qualityRating", "relevanceDecision", "coverageQuestion", "editorialForm", "personAuthor", "entity", "identifier"))
#: What the keys of those nodes begin with, for a node whose kind is not known (``coverage.ai``, ``author.name.x``, ``quality.rating.4_star``).
NON_CONCEPT_KEY_PREFIXES = ("author.", "author-", "coverage.", "coverage-", "comment.", "comment-", "quality.", "quality-", "relevance.", "relevance-", "editorial.", "editorial-")


def is_concept(kind: str | None, node_key: str | None = None, allowed: Iterable[str] | None = None) -> bool:
    """Whether a node of this kind (and key) may have a concept card and be suggested to an editor. ``allowed`` is the publication's own allowlist of kinds."""
    token = kind_token(kind)
    key = str(node_key or "").lower()
    if allowed is not None:
        return bool(token) and token in {kind_token(entry) for entry in allowed}
    if token in NON_CONCEPT_KINDS:
        return False
    return not (not token and key.startswith(NON_CONCEPT_KEY_PREFIXES))
