"""Link routed monitor records to the entities already on the map (``monitor_import.py``), deterministically and locally.

A routed record (a Hacker News story, later an RSS or arXiv item) has a title and no structured fields. Its title (and summary or excerpt,
when the source stored one) is matched, case-insensitively and on word boundaries, against the display names and aliases of the entities
that are **accepted** on the site's map. Nothing is created: a name the map does not have stays unlinked, and a generated or rejected
entity never matches. There is no model call; an entity name is found only if it is written out in the text.

Words are the runs of letters and digits (``GPT-4`` is ``gpt`` ``4``). A name of one word needs at least ``MINIMUM_WORD`` characters, so
short names like ``Go`` or ``AI`` never match by accident.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from .publish_run import STATUS_ACCEPTED

MINIMUM_WORD = 3
_WORDS = re.compile(r"\w+")


def words(text: str) -> tuple[str, ...]:
    return tuple(_WORDS.findall(text.casefold()))


class EntityMatcher:
    """Finds the accepted entities of a map that a text names."""

    def __init__(self, nodes: Iterable[Mapping[str, Any]]) -> None:
        self._names: dict[tuple[str, ...], dict[str, dict]] = {}
        self._longest = 0
        for node in nodes:
            if node.get("status") != STATUS_ACCEPTED or node.get("versionState", "current") != "current":
                continue
            for name in [node.get("displayName"), *(node.get("aliases") or ())]:
                tokens = words(str(name or ""))
                if not tokens or (len(tokens) == 1 and len(tokens[0]) < MINIMUM_WORD):
                    continue
                self._names.setdefault(tokens, {})[str(node["lineageId"])] = dict(node)
                self._longest = max(self._longest, len(tokens))

    def find(self, text: str) -> list[dict]:
        """The accepted entities ``text`` names, in lineage id order."""
        tokens = words(text)
        found: dict[str, dict] = {}
        for start in range(len(tokens)):
            for length in range(1, min(self._longest, len(tokens) - start) + 1):
                found.update(self._names.get(tokens[start : start + length], {}))
        return [found[key] for key in sorted(found)]


def match_records(records: Iterable[Any], index_rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict]]:
    """Reference id to the accepted entities a routed record's text names; records with no match, and Hub records, are left out."""
    matcher = EntityMatcher(index_rows)
    matches = {record.reference_id: matcher.find(record.text) for record in records if record.routed}
    return {key: nodes for key, nodes in matches.items() if nodes}
