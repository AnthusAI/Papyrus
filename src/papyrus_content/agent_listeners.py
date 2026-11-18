"""The site's listener index: which agents listen for which change (PPY-8a374e, slice B2).

A change feed turns each record change into one wake per agent that listens for it. Finding those agents must never read a table: today every delivery lists the
Automation table. The registered definitions are the source, so the deploy that registers them (``papyrus agents apply``) also writes ONE small derived document,
the listener index, to the site store (kind ``listeners``; its body is an S3 object at ``tenants/<tenant>/site/listeners/<version>.json``, text never goes in
DynamoDB). It is keyed by what changed, so a feed reads the one entry for a change and nothing else::

    {"schemaVersion": 1, "changes": {"Item/stage_entered": [{"agent": "copy-edit", "procedure": "story.copy_edit", "paid": true, "serialBy": "subject",
                                                           "filter": {"stage": "copywriting"}}], ...}}

* It holds the agents in Git, none retired (``release.load`` returns the definitions that are in Git, so an agent removed from Git leaves the index at the next apply).
* It holds no rung, pause or budget: those are the agent policy, which the runner checks for every wake (a deploy still cannot change them).
* The same definitions always give the same document, so an apply that changes no definition writes no new version.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Mapping

if TYPE_CHECKING:   # the feed's function bundle carries no YAML reader, so the definition file form is not imported at run time
    from .agent_definitions.definition import Definition

KIND = "listeners"
SCHEMA_VERSION = 1


def change_name(kind: str, change: str) -> str:
    return f"{kind}/{change}"


def build(definitions: Iterable[Definition]) -> dict[str, Any]:
    """The listener index for these definitions: one entry per ``kind/change``, agents in id order."""
    changes: dict[str, list[dict[str, Any]]] = {}
    for item in sorted(definitions, key=lambda definition: definition.id):
        for listened in item.data["wakes"].get("changes") or []:
            changes.setdefault(change_name(listened["kind"], listened["change"]), []).append({
                "agent": item.id, "procedure": item.data["procedure"], "paid": bool(item.data["paid"]), "serialBy": item.data["serialBy"],
                "filter": dict(listened.get("filter") or {}),
            })
    return {"schemaVersion": SCHEMA_VERSION, "changes": changes}


def listeners_of(document: Mapping[str, Any] | None, kind: str, change: str) -> list[dict[str, Any]]:
    """Every agent that listens for this change, whatever its filter: the one entry of the index for ``kind/change``. Nothing is read to find it."""
    return list(((document or {}).get("changes") or {}).get(change_name(kind, change)) or [])


def listening(document: Mapping[str, Any] | None, kind: str, change: str, attributes: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The listeners of one change whose filter every field of matches ``attributes`` (a filter names fields of the normalized change; values compare as text)."""
    entries = listeners_of(document, kind, change)

    def matches(entry: Mapping[str, Any]) -> bool:
        return all(attributes.get(field) is not None and str(attributes[field]) == str(value) for field, value in (entry.get("filter") or {}).items())

    return [entry for entry in entries if matches(entry)]


def publish(store, tenant_id: str, definitions: Iterable[Definition], *, actor: str, apply: bool) -> dict[str, Any]:
    """Make the site's listener index agree with the definitions. ``apply`` False reads and says what would change; an unchanged index writes nothing."""
    wanted = build(definitions)
    version = store.current_version(tenant_id, KIND)
    current = store.read_current(tenant_id, KIND) if version else None
    if current == wanted:
        return {"action": "unchanged", "version": version, "applied": False}
    action = "created" if not version else "updated"
    if not apply:
        return {"action": action, "version": version + 1, "applied": False}
    saved = store.save(tenant_id, KIND, wanted, actor, note="the agents that listen for changes, from the registered definitions", expected_version=version)
    return {"action": action, "version": saved, "applied": True}


class ListenerIndex:
    """What a change feed reads: the live index of one site, held in memory for as long as it is the live version.

    Each ``document()`` is one point read of the site's ``SiteDocument`` row (the live version number). The body is fetched from S3 only when that number is
    not the one held, so a deploy that registers a changed definition reaches the next change with no timer and no list. A site whose deploy has never
    written an index has no listeners: ``document()`` is empty and every change sends nothing."""

    def __init__(self, store, tenant_id: str):
        self._store, self._tenant_id = store, tenant_id
        self._held: tuple[int, dict[str, Any]] | None = None

    def document(self) -> dict[str, Any]:
        version = self._store.current_version(self._tenant_id, KIND)
        if version == 0:
            return {}
        if self._held is None or self._held[0] != version:
            body = self._store.read_current(self._tenant_id, KIND)
            self._held = (version, body or {})
        return self._held[1]
