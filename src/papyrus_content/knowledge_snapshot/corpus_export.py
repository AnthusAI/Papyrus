"""Published items of a site as Markdown files a Biblicus corpus can ingest (``papyrus knowledge corpus export``).

One file per published item, ``<out>/<item id>.md``. Point ``--out`` at a folder inside the Biblicus corpus
(``<corpus>/raw/papyrus``) and run ``biblicus reindex``: Biblicus ingests a file that lives in its corpus root through the
catalog rebuild, which keeps the ``biblicus.id`` below (``biblicus ingest`` of a file gives it a new random id). The
front matter is what Biblicus reads from a Markdown file:

``biblicus.id``
    A UUID. Biblicus keeps an id only when it is a UUID, and Papyrus item ids are not, so the id is
    ``deterministic_uuid(<item id>)``. ``publish-run`` turns it back into the item id.
``dates.published_at``
    The field Biblicus reads for publication dates (topic trends, topic identity).
``tags``
    Biblicus tags, from the item's front matter.

The rest (``papyrus_item_id``, ``slug``, ``url``, ``title``, ``section``, ``entities``) is ordinary metadata that
Biblicus carries with the item. The body is the title, the deck and the Markus source, so the topic model and the
entity extractor read the words a reader reads.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..ids import deterministic_uuid
from ..projection.source import is_projectable, summary_from_row
from .loaders import UrlResolver, front_matter_entities, front_matter_tags

ITEM_MARKER = "papyrus_item_id:"
DEFAULT_TYPES = ("article", "page")


@dataclass(frozen=True)
class ExportedItem:
    item_id: str
    biblicus_id: str
    file: str
    slug: str
    url: str | None
    title: str
    published_at: str | None
    text: str


def biblicus_item_id(item_id: str) -> str:
    """The Biblicus id of a Papyrus item: the same UUID on every export."""
    return deterministic_uuid(f"papyrus-item:{item_id}")


def _body(title: str, deck: str, markus: str) -> str:
    parts = [f"# {title}"] if title else []
    if deck:
        parts.append(deck)
    if markus:
        parts.append(markus)
    return "\n\n".join(parts) + "\n"


def render_item(row: Mapping[str, Any], url_for: UrlResolver) -> ExportedItem:
    summary = summary_from_row(dict(row))
    title = (summary.page_title or summary.title or "").strip()
    deck = str(row.get("deck") or "").strip()
    markus = str(row.get("bodyMarkus") or "").strip()
    url = url_for(summary)
    meta: dict[str, Any] = {
        "title": title,
        "biblicus": {"id": biblicus_item_id(summary.item_id)},
        "papyrus_item_id": summary.item_id,
        "slug": summary.slug,
        "section": summary.section,
        "url": url,
    }
    if summary.published_at:
        meta["dates"] = {"published_at": summary.published_at}
        meta["date_provenance"] = {"published_at": "papyrus-published-at"}
    tags = list(front_matter_tags(summary.front_matter))
    if tags:
        meta["tags"] = tags
    entities = [{"kind": entity.kind, "name": entity.name} for entity in front_matter_entities(summary.front_matter)]
    if entities:
        meta["entities"] = entities
    meta = {key: value for key, value in meta.items() if value not in (None, "")}
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1000).strip()
    return ExportedItem(
        item_id=summary.item_id,
        biblicus_id=meta["biblicus"]["id"],
        file=f"{summary.item_id}.md",
        slug=summary.slug,
        url=url,
        title=title,
        published_at=summary.published_at,
        text=f"---\n{front}\n---\n{_body(title, deck, markus)}",
    )


def export_items(rows: Iterable[Mapping[str, Any]], url_for: UrlResolver, types: tuple[str, ...] = DEFAULT_TYPES) -> list[ExportedItem]:
    """Every published item of the given types, ordered by item id."""
    selected = [row for row in rows if is_projectable(dict(row), types) and row.get("type") in types]
    return sorted((render_item(row, url_for) for row in selected), key=lambda item: item.item_id)


def _is_exported_file(path: Path) -> bool:
    with path.open(encoding="utf-8") as handle:
        return any(line.startswith(ITEM_MARKER) for _, line in zip(range(20), handle))


def write_export(items: list[ExportedItem], out: Path) -> dict[str, int]:
    """Write the files; remove files of an earlier export (they carry ``papyrus_item_id``) that are no longer published."""
    out.mkdir(parents=True, exist_ok=True)
    wanted = {item.file for item in items}
    removed = 0
    for stale in sorted(out.glob("*.md")):
        if stale.name not in wanted and _is_exported_file(stale):
            stale.unlink()
            removed += 1
    for item in items:
        (out / item.file).write_text(item.text, encoding="utf-8")
    return {"items": len(items), "removed": removed, "undated": sum(1 for item in items if not item.published_at)}
