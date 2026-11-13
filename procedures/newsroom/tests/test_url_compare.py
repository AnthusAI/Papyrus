"""The URL comparison tool: what it counts as a moved URL, and that it projects from a snapshot into a temporary directory only."""

from __future__ import annotations

import json
from pathlib import Path

from papyrus_content.projection import url_compare


def inventory(files=None, sitemaps=None, feeds=None, redirects=None, rules=None):
    return {"files": files or {}, "sitemaps": sitemaps or {}, "feeds": feeds or {}, "redirects": redirects or {}, "redirectRules": rules or [], "errors": [], "itemCount": 1}


def test_identical_inventories_moved_nothing():
    same = inventory({"a/index.html": "1"}, {"sitemap.xml": [["https://x/a/", "2026-01-01"]]}, {"feed.xml": [["link", "https://x/a/"]]}, {"/old": "/a/"})
    result = url_compare.compare_inventories(same, same)
    assert result["moved"] is False and result["bytesChanged"]["count"] == 0


def test_a_removed_or_added_path_a_sitemap_entry_a_feed_entry_or_a_redirect_is_a_move():
    base = inventory({"a/index.html": "1"}, {"sitemap.xml": [["https://x/a/", ""]]}, {"feed.xml": [["link", "https://x/a/"]]}, {"/old": "/a/"})
    moved_path = url_compare.compare_inventories(base, inventory({"b/index.html": "1"}, base["sitemaps"], base["feeds"], base["redirects"]))
    assert moved_path["moved"] and moved_path["paths"]["removed"] == ["a/index.html"] and moved_path["paths"]["added"] == ["b/index.html"]
    assert url_compare.compare_inventories(base, {**base, "sitemaps": {"sitemap.xml": [["https://x/b/", ""]]}})["moved"]
    assert url_compare.compare_inventories(base, {**base, "feeds": {"feed.xml": [["link", "https://x/b/"]]}})["moved"]
    assert url_compare.compare_inventories(base, {**base, "redirects": {"/old": "/b/"}})["redirects"]["changed"] == ["/old"]
    assert url_compare.compare_inventories(base, {**base, "redirects": {}})["redirects"]["removed"] == ["/old"]
    assert url_compare.compare_inventories(base, {**base, "redirectRules": ['{"p": "^/x$"}']})["moved"]


def test_the_same_entries_in_another_order_are_reported_and_a_changed_page_alone_is_not_a_move():
    first = inventory({"a/index.html": "1"}, feeds={"feed.xml": [["link", "a"], ["link", "b"]]})
    second = inventory({"a/index.html": "2"}, feeds={"feed.xml": [["link", "b"], ["link", "a"]]})
    result = url_compare.compare_inventories(first, second)
    assert result["moved"] and result["feedsReordered"] == ["feed.xml"]
    assert url_compare.compare_inventories(first, inventory({"a/index.html": "2"}, feeds=first["feeds"]))["bytesChanged"] == {"count": 1, "files": ["a/index.html"]}
    assert url_compare.compare_inventories(first, inventory({"a/index.html": "2"}, feeds=first["feeds"]))["moved"] is False


def test_a_plan_changes_only_the_rows_it_names_and_only_in_memory():
    rows = [{"id": "p1", "section": "articles"}, {"id": "p2", "section": "platform"}]
    migrated = url_compare.apply_plan(rows, {"published": [{"id": "p1", "from": "articles", "to": None}]})
    assert [row["section"] for row in migrated] == [None, "platform"] and rows[0]["section"] == "articles"


def test_the_comparison_projects_a_snapshot_into_the_work_directory_and_finds_a_moved_base(tmp_path: Path):
    def site(name, urls):
        web = tmp_path / name
        web.mkdir()
        (web / "projection.json").write_text(json.dumps({"site": {"name": "Example", "productionUrl": "https://example.org"}, "urls": {"style": "directory", **urls}}))
        return web

    rows = [{
        "id": "published-item-one", "sourceItemId": "item-one", "itemLineageId": "item-one", "versionNumber": 1, "type": "article", "status": "published", "language": "en", "languageGroupId": "item-one",
        "slug": "one", "section": "articles", "title": "One", "bodyMarkus": "Body.\n", "aliases": [], "publishedAt": "2026-03-01T00:00:00Z",
        "metadata": {"frontMatterYaml": "title: One\ndate: 2026-03-01\n"},
    }]
    snapshot = tmp_path / "rows.json"
    snapshot.write_text(json.dumps(rows))
    old = site("old", {"sections": {"articles": {"base": "articles"}}})
    same = site("same", {"types": {"article": {"base": "articles"}}})
    moved = site("moved", {"types": {"article": {"base": "stories"}}})
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"published": [{"id": "published-item-one", "from": "articles", "to": None}]}))
    work = tmp_path / "work"
    assert url_compare.main(["compare", "--snapshot", str(snapshot), "--old-static", str(old), "--new-static", str(same), "--plan", str(plan), "--work", str(work / "same")]) == 0
    assert (work / "same" / "new" / "articles" / "one" / "index.html").is_file()
    assert url_compare.main(["compare", "--snapshot", str(snapshot), "--old-static", str(old), "--new-static", str(moved), "--plan", str(plan), "--work", str(work / "moved"), "--json", str(tmp_path / "result.json")]) == 1
    result = json.loads((tmp_path / "result.json").read_text())
    assert "articles/one/index.html" in result["paths"]["removed"] and "stories/one/index.html" in result["paths"]["added"]
