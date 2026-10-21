"""Published content read from a directory of Markdown files instead of the CMS.

A site whose content lives in its repository (and is built by CI, not edited in the CMS) can still use the standard
front end: ``papyrus ops content project --all --from-dir content --static-dir web --out dist`` reads ``content/``
through this source and runs the same projection as a CMS-backed site would.

Every ``.md`` file is one published item. The first directory is its section (``guides/start.md`` is the ``start``
item of the ``guides`` section; a file at the top is a root page). Front matter keys ``type`` (``article`` or
``page``; default ``article``), ``aliases`` and ``title`` become item fields; the
rest of the front matter stays front matter. Directories below the section nest the slug:
``guides/intro/first.md`` is the ``intro/first`` item of ``guides`` (``/guides/intro/first/``). There is no publish time, so ``updated`` falls back to the front
matter ``updated`` / ``date`` only.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..markus_export import EXPORTED_TYPES
from .model import ProjectedItem, SiteIndex
from .source import ProjectionSourceError, projected_item_from_row, summary_from_row

_FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.S)


def _split(text: str) -> tuple[dict, str | None, str]:
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, None, text
    loaded = yaml.safe_load(match.group(1) + "\n")
    return (loaded if isinstance(loaded, dict) else {}), match.group(1) + "\n", match.group(2)


class DirectoryContentSource:
    """The projection source for a content directory; same interface as ``PublishedContentSource``."""

    def __init__(self, content_directory: Path) -> None:
        self.directory = Path(content_directory)
        if not self.directory.is_dir():
            raise ProjectionSourceError(f"{self.directory} is not a directory")
        self._rows: dict[str, dict] | None = None

    def _load(self) -> dict[str, dict]:
        if self._rows is not None:
            return self._rows
        rows: dict[str, dict] = {}
        for path in sorted(self.directory.rglob("*.md")):
            relative = path.relative_to(self.directory)
            if any(part.startswith(".") for part in relative.parts):
                continue
            data, _raw, body = _split(path.read_text(encoding="utf-8"))
            section = relative.parts[0] if len(relative.parts) > 1 else None
            kind = str(data.pop("type", "article"))
            if kind not in EXPORTED_TYPES:
                raise ProjectionSourceError(f"{relative.as_posix()}: type {kind!r} is not one of {', '.join(EXPORTED_TYPES)}")
            aliases = [str(alias) for alias in data.pop("aliases", None) or []]
            front_matter = yaml.safe_dump(data, sort_keys=False, allow_unicode=True) if data else None
            item_id = f"file:{relative.as_posix()}"
            rows[item_id] = {
                "id": item_id,
                "sourceItemId": item_id,
                "type": kind,
                "status": "published",
                "section": section,
                "slug": path.stem,
                "nestedSlug": True,
                "title": data.get("title"),
                "versionNumber": 1,
                "publishedAt": None,
                "aliases": aliases,
                "bodyMarkus": body,
                "metadata": {"frontMatterYaml": front_matter, "source": {"path": relative.as_posix()}},
            }
        self._rows = rows
        return rows

    def all_published_items(self) -> list[ProjectedItem]:
        items = [projected_item_from_row(row) for row in self._load().values()]
        return sorted(items, key=lambda item: item.summary.output_path)

    def load_item(self, item_id: str) -> ProjectedItem:
        row = self._load().get(item_id)
        if row is None:
            raise ProjectionSourceError(f"Item {item_id} is not published")
        return projected_item_from_row(row)

    def published_item(self, item_id: str) -> ProjectedItem | None:
        row = self._load().get(item_id)
        return projected_item_from_row(row) if row is not None else None

    def site_index(self) -> SiteIndex:
        summaries = [summary_from_row(row) for row in self._load().values()]
        return SiteIndex(items=tuple(sorted(summaries, key=lambda summary: summary.output_path)), load_item=self.load_item)
