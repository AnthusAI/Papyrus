"""Prove that a change of ``projection.json`` (and of stored sections) moves no public URL.

The tool projects one site's published rows twice into temporary directories, once with the site's current static
directory and once with the changed one, and diffs what a reader, a crawler or a feed reader could see move: every
generated path, the sitemap, the RSS and Atom feeds and the redirects. It reads rows from a snapshot file
(``--snapshot``: a JSON list of ``PublishedItem`` rows, saved by a read-only scan) and never talks to a backend, a
bucket or a distribution: the only writer is a local directory under ``--work``.

    python -m papyrus_content.projection.url_compare compare \\
        --snapshot anthus.PublishedItem.json --old-static old/web --new-static new/web \\
        [--plan anthus.plan.json] --work /tmp/anthus-compare

``--plan`` is a section migration plan (``papyrus_content.section_migration``): its changes are applied to the rows
for the new side only, so the comparison is "today's config on today's data" against "the new config on the migrated data".
The two projections run in separate processes (a site's hooks module is loaded once per process). Exit status 1 when a path,
a sitemap entry, a feed entry or a redirect differs; pages whose bytes differ at the same path are reported but do not fail.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

SITEMAP_NAME = re.compile(r"(^|/)sitemap[^/]*\.xml$")
LINK = re.compile(r"<link>([^<]*)</link>|<link\b[^>]*\bhref=\"([^\"]*)\"")
IDENTIFIER = re.compile(r"<(?:guid|id)\b[^>]*>([^<]*)</(?:guid|id)>")
LOC = re.compile(r"<loc>([^<]*)</loc>(?:\s*<lastmod>([^<]*)</lastmod>)?")
CATEGORY = re.compile(r"<category\b[^>]*?(?:term=\"([^\"]*)\"[^>]*/>|>([^<]*)</category>)")
FEED_START = re.compile(r"<(rss|feed)\b")


class SnapshotClient:
    """Just enough of the authoring client for ``PublishedContentSource``: the rows of a snapshot, read-only."""

    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self.rows = [dict(row) for row in rows]

    def list_records(self, model: str) -> list[dict]:
        if model != "PublishedItem":
            raise KeyError(f"a snapshot holds PublishedItem rows only, not {model}")
        return [dict(row) for row in self.rows]

    def list_published_item_summaries(self) -> list[dict]:
        return self.list_records("PublishedItem")

    def get_record(self, model: str, record_id: str) -> dict | None:
        key = "sourceItemId" if model == "Item" else "id"
        return next((dict(row) for row in self.rows if row.get(key) == record_id or row.get("id") == record_id), None)


def apply_plan(rows: Iterable[Mapping[str, Any]], plan: Mapping[str, Any]) -> list[dict]:
    """The rows with a migration plan's published-row changes applied (only in memory)."""
    changes = {change["id"]: change["to"] for change in plan.get("published", ())}
    migrated = []
    for row in rows:
        row = dict(row)
        if row["id"] in changes:
            row["section"] = changes[row["id"]]
        migrated.append(row)
    return migrated


def feed_entries(text: str) -> list[list[str]]:
    """The identifying parts of a feed in order: every link, id and category, so a moved entry shows even if its title did not change."""
    parts: list[list[str]] = []
    for match in LINK.finditer(text):
        parts.append(["link", match.group(1) or match.group(2) or ""])
    for match in IDENTIFIER.finditer(text):
        parts.append(["id", match.group(1)])
    for match in CATEGORY.finditer(text):
        parts.append(["category", match.group(1) or match.group(2) or ""])
    return parts


def inventory_of(out: Path) -> dict:
    """Every file under ``out`` with its hash, the sitemap entries and the feed entries."""
    files = {path.relative_to(out).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(out.rglob("*")) if path.is_file()}
    sitemaps: dict[str, list[list[str]]] = {}
    feeds: dict[str, list[list[str]]] = {}
    for name in files:
        if not name.endswith(".xml"):
            continue
        text = (out / name).read_text(encoding="utf-8", errors="replace")
        if SITEMAP_NAME.search(name):
            sitemaps[name] = [[loc, lastmod or ""] for loc, lastmod in LOC.findall(text)]
        elif FEED_START.search(text[:2000]):
            feeds[name] = feed_entries(text)
    return {"files": files, "sitemaps": sitemaps, "feeds": feeds}


class ReadOnlyRenditions:
    """Renditions read from a site bucket for a comparison: reads and listings only, a write is refused."""

    def __init__(self, bucket: str) -> None:
        from ..renditions import S3RenditionStore

        self._store = S3RenditionStore(bucket)

    def get(self, key: str) -> bytes | None:
        return self._store.get(key)

    def keys(self, prefix: str) -> list[str]:
        return self._store.keys(prefix)

    def put(self, key: str, body: bytes, *, cache_control: str) -> None:
        raise RuntimeError("the URL comparison never writes to a bucket")


def project_to(static_directory: Path, rows: list[dict], out: Path, renditions_bucket: str | None = None) -> dict:
    """Project ``rows`` with the site in ``static_directory`` into the empty directory ``out`` and return its inventory plus the redirects."""
    from ..projection.engine import ProjectionContext, project_all
    from ..projection.model import SiteIndex
    from ..projection.runtime import SITE_STATIC_DIRECTORY_ENV, load_projector
    from ..projection.source import PublishedContentSource
    from ..projection.writers import LocalDirectoryWriter

    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; the comparison writes only to a fresh directory")
    environment = {key: value for key, value in os.environ.items() if key.startswith(("PATH", "HOME", "LANG", "LC_"))}
    environment[SITE_STATIC_DIRECTORY_ENV] = str(static_directory)
    source = PublishedContentSource(SnapshotClient(rows))
    projector = load_projector(environment, renditions=ReadOnlyRenditions(renditions_bucket) if renditions_bucket else None)
    context = ProjectionContext(source=source, projector=projector, writer=LocalDirectoryWriter(out), keep_state=False)
    report = project_all(context)
    items = source.all_published_items()
    site = SiteIndex(items=tuple(item.summary for item in items), load_item=source.load_item)
    redirects = dict(projector.redirects(site))
    settings = getattr(projector, "standard", None)
    rules = [rule.to_edge_record() for rule in getattr(settings, "pattern_redirects", ())]
    inventory = inventory_of(out)
    inventory.update({"redirects": redirects, "redirectRules": rules, "errors": list(report.errors), "itemCount": len(items)})
    return inventory


def _delta(old: Iterable, new: Iterable) -> dict[str, list]:
    old_set, new_set = list(old), list(new)
    return {"removed": [entry for entry in old_set if entry not in new_set], "added": [entry for entry in new_set if entry not in old_set]}


def compare_inventories(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict:
    """What moved between two inventories. ``moved`` is empty exactly when no URL, sitemap entry, feed entry or redirect differs."""
    paths = _delta(sorted(old["files"]), sorted(new["files"]))
    sitemap = {name: _delta(map(tuple, old["sitemaps"].get(name, [])), map(tuple, new["sitemaps"].get(name, []))) for name in sorted({*old["sitemaps"], *new["sitemaps"]})}
    feeds = {name: _delta(map(tuple, old["feeds"].get(name, [])), map(tuple, new["feeds"].get(name, []))) for name in sorted({*old["feeds"], *new["feeds"]})}
    feed_order = [name for name in sorted(set(old["feeds"]) & set(new["feeds"])) if old["feeds"][name] != new["feeds"][name] and not feeds[name]["removed"] and not feeds[name]["added"]]
    redirects = {
        "removed": sorted(source for source in old["redirects"] if source not in new["redirects"]),
        "added": sorted(source for source in new["redirects"] if source not in old["redirects"]),
        "changed": sorted(source for source in old["redirects"] if source in new["redirects"] and old["redirects"][source] != new["redirects"][source]),
    }
    rules = _delta(map(json.dumps, old.get("redirectRules", [])), map(json.dumps, new.get("redirectRules", [])))
    changed_bytes = sorted(name for name in set(old["files"]) & set(new["files"]) if old["files"][name] != new["files"][name])
    moved = bool(
        paths["removed"] or paths["added"]
        or any(entry["removed"] or entry["added"] for entry in sitemap.values())
        or any(entry["removed"] or entry["added"] for entry in feeds.values())
        or feed_order
        or redirects["removed"] or redirects["added"] or redirects["changed"]
        or rules["removed"] or rules["added"]
    )
    return {
        "moved": moved,
        "paths": {"old": len(old["files"]), "new": len(new["files"]), **paths},
        "sitemap": {name: entry for name, entry in sitemap.items() if entry["removed"] or entry["added"]},
        "sitemapEntries": {"old": sum(len(v) for v in old["sitemaps"].values()), "new": sum(len(v) for v in new["sitemaps"].values())},
        "feeds": {name: entry for name, entry in feeds.items() if entry["removed"] or entry["added"]},
        "feedsReordered": feed_order,
        "feedEntries": {"old": sum(len(v) for v in old["feeds"].values()), "new": sum(len(v) for v in new["feeds"].values())},
        "redirects": {"old": len(old["redirects"]), "new": len(new["redirects"]), **redirects},
        "redirectRules": rules,
        "bytesChanged": {"count": len(changed_bytes), "files": changed_bytes},
        "errors": {"old": old.get("errors", []), "new": new.get("errors", [])},
        "items": {"old": old.get("itemCount"), "new": new.get("itemCount")},
    }


def _child(args: argparse.Namespace, side: str, static: Path, plan: Path | None, work: Path) -> dict:
    command = [sys.executable, "-m", "papyrus_content.projection.url_compare", "project", "--snapshot", str(args.snapshot), "--static", str(static), "--out", str(work / side), "--inventory", str(work / f"{side}.inventory.json")]
    if plan is not None:
        command += ["--plan", str(plan)]
    if args.renditions_bucket:
        command += ["--renditions-bucket", args.renditions_bucket]
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(Path(__file__).resolve().parents[2]), os.environ.get("PYTHONPATH", "")]))}
    result = subprocess.run(command, env=environment, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"projecting the {side} side failed:\n{result.stdout[-2000:]}\n{result.stderr[-4000:]}")
    return json.loads((work / f"{side}.inventory.json").read_text(encoding="utf-8"))


def render(result: Mapping[str, Any], *, limit: int = 12) -> str:
    def show(label: str, entries: list) -> list[str]:
        shown = [f"    {label} {entry!r}" for entry in entries[:limit]]
        return shown + ([f"    ... and {len(entries) - limit} more {label}"] if len(entries) > limit else [])

    lines = [
        f"items projected: old {result['items']['old']}, new {result['items']['new']}",
        f"paths: old {result['paths']['old']}, new {result['paths']['new']}, removed {len(result['paths']['removed'])}, added {len(result['paths']['added'])}",
        *show("-", result["paths"]["removed"]), *show("+", result["paths"]["added"]),
        f"sitemap entries: old {result['sitemapEntries']['old']}, new {result['sitemapEntries']['new']}",
    ]
    for name, entry in result["sitemap"].items():
        lines += [f"  {name}: removed {len(entry['removed'])}, added {len(entry['added'])}", *show("-", entry["removed"]), *show("+", entry["added"])]
    lines.append(f"feed entries (links, ids, categories): old {result['feedEntries']['old']}, new {result['feedEntries']['new']}")
    for name, entry in result["feeds"].items():
        lines += [f"  {name}: removed {len(entry['removed'])}, added {len(entry['added'])}", *show("-", entry["removed"]), *show("+", entry["added"])]
    if result["feedsReordered"]:
        lines.append(f"  feeds with the same entries in another order: {', '.join(result['feedsReordered'])}")
    redirects = result["redirects"]
    lines.append(f"redirects: old {redirects['old']}, new {redirects['new']}, removed {len(redirects['removed'])}, added {len(redirects['added'])}, changed {len(redirects['changed'])}")
    lines += [*show("-", redirects["removed"]), *show("+", redirects["added"]), *show("~", redirects["changed"])]
    if result["redirectRules"]["removed"] or result["redirectRules"]["added"]:
        lines.append(f"redirect rules: removed {len(result['redirectRules']['removed'])}, added {len(result['redirectRules']['added'])}")
    lines.append(f"pages at the same path with different bytes: {result['bytesChanged']['count']}")
    lines += show("*", result["bytesChanged"]["files"])
    if result["errors"]["old"] or result["errors"]["new"]:
        lines.append(f"projection errors: old {result['errors']['old']}, new {result['errors']['new']}")
    lines.append("RESULT: URLS MOVED" if result["moved"] else "RESULT: no URL moved (paths, sitemap, feeds and redirects are identical)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="url_compare", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    compare = commands.add_parser("compare", help="project the old and the new side and diff them")
    compare.add_argument("--snapshot", required=True, type=Path, help="JSON list of PublishedItem rows")
    compare.add_argument("--old-static", required=True, type=Path, help="the site's web directory as it is now")
    compare.add_argument("--new-static", required=True, type=Path, help="the site's web directory with the changed projection.json")
    compare.add_argument("--plan", type=Path, help="a section migration plan applied to the rows of the new side")
    compare.add_argument("--renditions-bucket", help="a site bucket to read image renditions from (reads only); needed when projection.json configures images")
    compare.add_argument("--work", type=Path, help="directory for the two projections (default: a new temporary directory)")
    compare.add_argument("--json", type=Path, help="write the full result here")
    project = commands.add_parser("project", help="one side (run by compare)")
    project.add_argument("--snapshot", required=True, type=Path)
    project.add_argument("--static", required=True, type=Path)
    project.add_argument("--out", required=True, type=Path)
    project.add_argument("--inventory", required=True, type=Path)
    project.add_argument("--plan", type=Path)
    project.add_argument("--renditions-bucket")
    args = parser.parse_args(argv)
    if args.command == "project":
        rows = json.loads(args.snapshot.read_text(encoding="utf-8"))
        if args.plan:
            rows = apply_plan(rows, json.loads(args.plan.read_text(encoding="utf-8")))
        args.out.mkdir(parents=True, exist_ok=True)
        args.inventory.write_text(json.dumps(project_to(args.static.resolve(), rows, args.out, args.renditions_bucket)), encoding="utf-8")
        return 0
    work = args.work or Path(tempfile.mkdtemp(prefix="url-compare-"))
    work.mkdir(parents=True, exist_ok=True)
    old = _child(args, "old", args.old_static.resolve(), None, work)
    new = _child(args, "new", args.new_static.resolve(), args.plan, work)
    result = compare_inventories(old, new)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(render(result))
    return 1 if result["moved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
