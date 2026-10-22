"""The knowledge snapshot as a site hook sees it: find an accepted entity by name and draw its chip.

A hook reaches it as ``site.knowledge`` (``site`` is the :class:`~papyrus_content.projection.standard.hooks.HookSite` that
``item_decorator``, ``source``, ``page_inputs`` and ``redirects`` are given, and ``page.site`` in the page hooks). It reads
``index.json`` only, so it holds exactly what the public snapshot holds: accepted entities, never proposed ones.
"""

from __future__ import annotations

from collections.abc import Mapping

from papyrus_content.knowledge_snapshot.keys import normalize_name

from . import knowledge_components as parts
from .knowledge import KnowledgeSource

STATE_ACCEPTED = "accepted"


class KnowledgeLookup:
    def __init__(self, source: KnowledgeSource | None = None) -> None:
        self._source = source or KnowledgeSource()
        self._built: tuple[object, dict[str, list[dict]]] | None = None

    def _names(self, index: Mapping) -> dict[str, list[dict]]:
        """Normalised name or alias -> the entities that answer to it, in the snapshot's order."""
        if self._built is None or self._built[0] is not index:
            names: dict[str, list[dict]] = {}
            for entity in index.get("entities") or []:
                for label in (entity.get("name"), *(entity.get("aliases") or [])):
                    normal = normalize_name(label)
                    if normal and entity not in names.setdefault(normal, []):
                        names[normal].append(entity)
            self._built = (index, names)
        return self._built[1]

    def entity_for(self, kind: str | None, name: str) -> dict | None:
        """The accepted entity of this ``kind`` named ``name`` (or having it as an alias), or ``None``.

        Names and kinds match without regard to case or white space, exactly as the snapshot matches them. ``kind`` is the
        entity kind key (``"maker"``) or its label (``"Maker"``); ``None`` or ``""`` searches every kind, and a name
        that two kinds share then resolves to nothing rather than to a guess. Returns
        ``{"key", "name", "kind", "href", "state"}``: ``href`` is the entity's page (``None`` when the snapshot has no
        page for it) and ``state`` is always ``"accepted"``, because the snapshot holds nothing else."""
        index = self._source.index()
        if not index:
            return None
        wanted = normalize_name(kind) if kind else ""
        labels = {str(row.get("key")): normalize_name(row.get("label")) for row in index.get("kinds") or []}
        found = [
            entity
            for entity in self._names(index).get(normalize_name(name), [])
            if not wanted or wanted in (normalize_name(entity.get("kind")), labels.get(str(entity.get("kind"))))
        ]
        if len(found) != 1:
            return None
        entity = found[0]
        return {
            "key": str(entity.get("key")),
            "name": str(entity.get("name")),
            "kind": str(entity.get("kind")),
            "href": parts.safe_href(entity.get("href")) or None,
            "state": STATE_ACCEPTED,
        }

    def chip_html(self, entity: Mapping) -> str:
        """The standard ``papyrus-knowledge-chip`` markup (kind label and name, a link when the entity has a page) for what
        :meth:`entity_for` returned. An empty string for ``None``."""
        if not entity:
            return ""
        kind = str(entity.get("kind") or "")
        labels = {str(row.get("key")): str(row.get("label") or row.get("key")) for row in (self._source.index() or {}).get("kinds") or []}
        return parts.entity_chip(labels.get(kind, kind), entity.get("name"), kind=kind, href=entity.get("href"), proposed=entity.get("state") == "proposed")
