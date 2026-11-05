"""A synthetic site with long Reference lists, for the tests of paged lists and for the screenshots: no network, no AWS, no real Reference."""

from __future__ import annotations

import copy
import json

from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite

SITE_DIRECTORY = FIXTURES / "home-page"
SNAPSHOT_KEY = "_data/home-page/references.json"
PAGE = '''::band{size="bare"}

::include{kind="references" select="recent" count="%(first)d" paged="true" heading="Accepted" empty="Nothing has been accepted yet."}

::include{kind="references" select="recommended" count="%(first)d" paged="true" heading="Waiting for an editor" empty="Nothing is waiting."}
'''


def record(number: int, status: str, *, rank: int | None = None, image: str | None = None) -> dict:
    """A public Reference record in the shape the snapshot holds. Higher numbers are newer."""
    day = 1 + number % 28
    month = 1 + (number // 28) % 10
    stamp = f"2026-{month:02d}-{day:02d}T{number % 24:02d}:00:00.000Z"
    found = {
        "key": f"{number:012x}", "status": status, "title": f"Reference number {number}", "authors": ["Ada Author"], "url": f"https://www.example.org/posts/{number}",
        "host": "example.org", "mediaType": "text/html", "sourceDate": stamp[:10], "arrivedAt": stamp, "acceptedAt": stamp if status == "accepted" else None,
        "decidedAt": stamp if status == "accepted" else None, "section": "Tools", "actor": "human" if status == "accepted" else None,
        "confidence": round(0.4 + (number % 55) / 100, 2), "versionNumber": 1, "summary": f"A short summary of number {number}.", "siteName": "Example",
        "rank": rank if rank is not None else number,
    }
    if image:
        found["image"] = image
    return found


def snapshot(accepted: int, recommended: int, *, image: str | None = None) -> dict:
    records = [record(number, "accepted", image=image) for number in range(1, accepted + 1)] + [record(10_000 + number, "recommended", image=image) for number in range(1, recommended + 1)]
    ordered = sorted(records, key=lambda found: (found["status"] != "accepted", -int(found["key"], 16)))
    for position, found in enumerate(ordered, start=1):
        found["rank"] = position
    return {"generatedAt": "2026-11-04T12:00:00.000Z", "corpus": "knowledge-corpus-example", "fields": [], "references": ordered}


def snapshot_bytes(document: dict) -> bytes:
    return (json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def settings(*, page_size: int = 12, paging: bool = True, hooks: str | None = None) -> dict:
    found = copy.deepcopy(json.loads((SITE_DIRECTORY / "projection.json").read_text(encoding="utf-8")))
    found["pages"] = [{"id": "wire", "path": "wire", "title": "The wire", "description": "Long Reference lists.", "dependsOn": [], "source": "pages/wire.md"}]
    if paging:
        found["homePage"]["references"]["paging"] = {"pageSize": page_size}
    if hooks:
        found["hooks"] = hooks
    return found


def project(document: dict, *, first: int = 6, page_size: int = 12, paging: bool = True, extra_files: dict | None = None, hooks: str | None = None) -> ProjectedSite:
    files = {"pages/wire.md": (PAGE % {"first": first}).encode("utf-8"), **(extra_files or {})}
    return ProjectedSite(settings=settings(page_size=page_size, paging=paging, hooks=hooks), content=SITE_DIRECTORY / "content", extra_files=files, seed={SNAPSHOT_KEY: snapshot_bytes(document)})


def list_files(site: ProjectedSite) -> dict[str, bytes]:
    return {key: body for key, body in site.tree.items() if key.startswith("reference-lists/")}
