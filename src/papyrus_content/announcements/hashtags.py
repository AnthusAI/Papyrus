"""Hashtags for an X announcement: the accepted concepts tagged to the Story (PPY-d40025).

The concepts a Story is tagged with are the hashtags worth using when it is announced (Ryan, 2026-11-09). This reads them and nothing else: the name part of each tagged
concept's node key, in CamelCase so it reads as a hashtag, most-used concept first. It writes nothing. The drafting step may pick from this list and only from it
(``drafting.py``); a hashtag the list does not hold is refused as invented, like any other markup the Story does not have.
"""
from __future__ import annotations

import re
from typing import Any

ACCEPTED = "accepted"
#: The predicate of a concept tag (``reference_links.TAGGED_WITH``, repeated here for the same reason: that module pulls in PyYAML).
TAGGED_WITH = "tagged_with"
#: A node key is ``<kind>--<name>``. Read here, not through ``knowledge_snapshot.keys``: the image service function that serves the door carries no PyYAML, which that package pulls in.
KEY_SEPARATOR = "--"
#: X reads a hashtag as letters, digits and underscores that are not all digits.
VALID = re.compile(r"^(?=.*[A-Za-z_])[A-Za-z0-9_]{2,40}$")


def camel_case(name: str) -> str:
    """``voice-cloning`` gives ``VoiceCloning``; a part that is already capitalised or an acronym (``AI``) keeps its letters."""
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", name) if part]
    return "".join(part if part[:1].isupper() else part[:1].upper() + part[1:] for part in parts)


def concept_name_part(node_key: str) -> str:
    kind_part, separator, name_part = str(node_key or "").partition(KEY_SEPARATOR)
    return name_part if kind_part and separator else ""


def hashtag_for(node_key: str) -> str:
    """``#VoiceCloning`` for ``concept--voice-cloning``, or ``""`` when the name cannot be a hashtag."""
    word = camel_case(concept_name_part(node_key))
    return f"#{word}" if VALID.match(word) else ""


def _uses(client: Any, node_lineage: str) -> int:
    """How many Stories carry this concept as a current tag."""
    rows = client.list_by_index("semanticRelationsByObjectState", f"semanticNode#{node_lineage}#current")
    return len({row.get("subjectLineageId") for row in rows if row.get("predicate") == TAGGED_WITH and row.get("subjectKind") == "item"})


def story_hashtags(client: Any, lineage_id: str) -> list[str]:
    """The Story's hashtags, most-used concept first, each once. Empty when it carries no accepted concept."""
    rows = [row for row in client.list_by_index("semanticRelationsBySubjectState", f"item#{lineage_id}#current")
            if row.get("predicate") == TAGGED_WITH and row.get("objectKind") == "semanticNode" and row.get("objectId")]
    nodes = client.get_records_by_id("SemanticNode", [str(row["objectId"]) for row in rows]) if rows else {}
    found: dict[str, tuple[int, str]] = {}
    for row in rows:
        node = nodes.get(str(row["objectId"])) or {}
        if node.get("status") != ACCEPTED:
            continue
        tag = hashtag_for(str(node.get("nodeKey") or ""))
        if tag and tag.lower() not in {key.lower() for key in found}:
            found[tag] = (_uses(client, str(node.get("lineageId") or row.get("objectLineageId") or "")), tag)
    return [tag for _count, tag in sorted(found.values(), key=lambda pair: (-pair[0], pair[1].lower()))]
