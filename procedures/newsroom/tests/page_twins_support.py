"""A projected site whose pages read the home-page snapshot (References and conversations), for the page twin tests and scenarios."""

from __future__ import annotations

import copy
import json

from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite

HOME_PAGE = FIXTURES / "home-page"
THREADS = {
    "generatedAt": "2026-10-31T12:00:00.000Z",
    "threads": [
        {"key": "aaaaaaaaaaaa", "title": "Is this worth adopting?", "messages": 2, "lastAt": "2026-10-31T10:00:00Z", "anchor": {"kind": "reference", "key": "b94890d5bbae"}, "latest": {"text": "Agreed.", "author": {"label": "Editor"}}},
        {"key": "bbbbbbbbbbbb", "title": "Fungi follow-up", "messages": 1, "lastAt": "2026-10-29T08:00:00Z", "anchor": {"kind": "story"}, "latest": {"text": "Spores.", "author": {"label": "AI"}}},
    ],
}


def page_entry(page_id: str, path: str, title: str, description: str = "") -> dict:
    return {"id": page_id, "path": path, "title": title, "description": description, "dependsOn": [], "source": f"pages/{page_id}.md"}


def snapshot_site(pages: dict[str, str], page_entries: list[dict], *, forum: bool = False, references: dict | None = None) -> ProjectedSite:
    """The home-page fixture's content and References (or ``references``), two conversations, and these page files and entries."""
    config = copy.deepcopy(json.loads((HOME_PAGE / "projection.json").read_text(encoding="utf-8")))
    config["pages"] = page_entries
    config["homePage"]["threads"] = {"enabled": True}
    if forum:
        config["homePage"]["forum"] = {}
    seed = {"_data/home-page/references.json": json.dumps(references).encode() if references is not None else (HOME_PAGE / "_data" / "home-page" / "references.json").read_bytes()}
    seed["_data/home-page/threads.json"] = json.dumps(THREADS).encode()
    return ProjectedSite(settings=config, content=HOME_PAGE / "content", extra_files=pages, seed=seed)
