"""Retired Stories: the addresses a retired Story was served at, and where each one now redirects.

``papyrus stories retire --story X --redirect-to Y`` takes X's page down and records, on X, the lineage of the Story Y that
replaces it (``metadata.retiredInto``). The projection turns that into redirects: one register object in the site store
(``_papyrus/retired.json``) remembers, for each retired Story, every page key it was ever served at (its current address and
Markdown twin, the addresses of its earlier published versions, the tombstone's former addresses) and the aliases it kept. The
redirect store gets one permanent entry per request path, pointing at Y's address *as it is now*.

The register keeps the Story it points to as a lineage, never as an address, so every projection (a publish, a rename of Y, a
full render, a reconcile) computes the redirects from the site as it stands: when Y changes address the redirects follow, and
they never form a chain. A target that is itself retired is followed to its own target (with a loop guard); a target that is not
published has no redirect, so its sources answer 404 until it is published again.

Nothing here reads a published row or the CMS: the register is what the projection itself wrote when it removed the Story.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .model import ItemSummary, SiteIndex
from .writers import STATE_PREFIX, PageWriter, request_paths_for_key

RETIRED_KEY = STATE_PREFIX + "retired.json"
FOLLOW_LIMIT = 10


@dataclass(frozen=True)
class RetiredEntry:
    item_id: str
    lineage_id: str
    to_lineage: str
    keys: tuple[str, ...]
    aliases: tuple[str, ...] = ()

    def to_json(self) -> dict:
        return {
            "itemId": self.item_id,
            "lineageId": self.lineage_id,
            "toLineageId": self.to_lineage,
            "keys": list(self.keys),
            "aliases": list(self.aliases),
        }

    @classmethod
    def from_json(cls, raw: dict) -> "RetiredEntry":
        return cls(
            item_id=raw["itemId"],
            lineage_id=raw["lineageId"],
            to_lineage=raw["toLineageId"],
            keys=tuple(raw.get("keys") or ()),
            aliases=tuple(raw.get("aliases") or ()),
        )


#: ``{retired Story's lineage id: entry}``
Registry = dict[str, RetiredEntry]


def read_registry(store: PageWriter) -> Registry:
    body = store.get(RETIRED_KEY)
    if body is None:
        return {}
    raw = json.loads(body.decode("utf-8"))
    return {entry["lineageId"]: RetiredEntry.from_json(entry) for entry in raw.get("entries", [])}


def write_registry(store: PageWriter, registry: Registry) -> None:
    entries = [registry[lineage_id].to_json() for lineage_id in sorted(registry)]
    store.put(RETIRED_KEY, json.dumps({"entries": entries}, sort_keys=True).encode("utf-8"))


def _canonical_path(projector, key: str) -> str:
    canonical = getattr(projector, "canonical_path", None)
    return canonical(key) if canonical is not None else request_paths_for_key(key)[0]


def _request_paths(projector, key: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys((_canonical_path(projector, key), *request_paths_for_key(key))))


def _normalized(alias: str) -> str:
    return alias if alias.startswith("/") else "/" + alias


def final_target(site: SiteIndex, registry: Registry, to_lineage: str) -> ItemSummary | None:
    """The published Story a redirect to ``to_lineage`` lands on: that Story, or, when it is retired too, the one it points to."""
    by_lineage = {summary.lineage_id: summary for summary in site.items if summary.lineage_id}
    retired_to = {entry.lineage_id: entry.to_lineage for entry in registry.values()}
    lineage, seen = to_lineage, set()
    for _ in range(FOLLOW_LIMIT):
        if lineage in by_lineage:
            return by_lineage[lineage]
        if lineage in seen or lineage not in retired_to:
            return None
        seen.add(lineage)
        lineage = retired_to[lineage]
    return None


def registry_redirects(projector, site: SiteIndex, registry: Registry) -> dict[str, str]:
    """``{request path: target path}`` for every address of every retired Story whose target is published.

    A ``.md`` twin goes to the target's twin when it has one, else to its page. A path that is a live page (an address another
    Story took over) is left out, as is a path that would redirect to itself.
    """
    if not registry:
        return {}
    live = {path for summary in site.items for key in projector.item_page_paths(summary) for path in _request_paths(projector, key)}
    found: dict[str, str] = {}
    for entry in registry.values():
        target = final_target(site, registry, entry.to_lineage)
        if target is None:
            continue
        keys = projector.item_page_paths(target)
        if not keys:
            continue
        page = _canonical_path(projector, keys[0])
        twin = next((_canonical_path(projector, key) for key in keys[1:] if key.endswith(".md")), page)
        for key in entry.keys:
            destination = twin if key.endswith(".md") else page
            for source in _request_paths(projector, key):
                found[source] = destination
        for alias in entry.aliases:
            found[_normalized(alias)] = page
    return {source: destination for source, destination in found.items() if source not in live and source != destination}


def entry_for(projector, item_id: str, lineage_id: str, to_lineage: str, summaries, page_keys) -> RetiredEntry:
    """The register entry for a Story: ``page_keys`` (what the projection state remembers) plus the keys and aliases of every version in ``summaries``."""
    keys = list(page_keys)
    aliases: list[str] = []
    for summary in summaries:
        keys.extend(projector.item_page_paths(summary))
        aliases.extend(summary.aliases)
    return RetiredEntry(
        item_id=item_id,
        lineage_id=lineage_id,
        to_lineage=to_lineage,
        keys=tuple(sorted(dict.fromkeys(keys))),
        aliases=tuple(sorted(dict.fromkeys(aliases))),
    )
