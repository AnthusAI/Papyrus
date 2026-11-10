"""Page refresh (PPY-105508): path expansion, the story and index fan-out of a real standard projector, and the operations over a fake CloudFront."""

from __future__ import annotations

import json

import pytest

from papyrus_content.edge_invalidation import invalidate_exact_paths, invalidation_cost_note
from papyrus_content.page_refresh.mcp import call_page_refresh_tool, page_refresh_descriptions, page_refresh_tools
from papyrus_content.page_refresh.operations import OPERATIONS, run_operation
from papyrus_content.page_refresh.paths import InvalidPagePath, expand_site_paths, forms_of_path, keys_under, normalize_prefixes, paths_for_page_keys
from papyrus_content.page_refresh.service import RefreshService
from papyrus_content.projection.directory_source import DirectoryContentSource
from papyrus_content.projection.engine import ProjectionContext
from papyrus_content.projection.standard.projector import StandardMarkusProjector
from papyrus_content.projection.writers import LocalDirectoryWriter
from procedures.newsroom.tests.standard_frontend_content_support import DirectorySite, item, settings


# ------------------------------------------------------------------ path expansion


def test_a_directory_page_is_purged_under_both_url_forms_and_its_twin():
    assert forms_of_path("/articles/my-story/") == ["/articles/my-story/", "/articles/my-story/index.html", "/articles/my-story/index.md"]
    assert forms_of_path("/articles/my-story/index.html") == forms_of_path("/articles/my-story/")
    assert forms_of_path("https://example.org/articles/my-story/?utm=1#top") == forms_of_path("/articles/my-story/")


def test_the_home_page_has_all_three_forms():
    assert forms_of_path("/") == ["/", "/index.html", "/index.md"]
    assert forms_of_path("index.html") == forms_of_path("/")


def test_a_page_file_is_also_its_clean_url_and_its_twin():
    assert forms_of_path("/posts/a.html") == ["/posts/a.html", "/posts/a", "/posts/a.md"]
    assert forms_of_path("/posts/a.md") == ["/posts/a.md", "/posts/a.html", "/posts/a"]


def test_a_bare_path_covers_the_clean_page_and_the_directory_page():
    assert forms_of_path("/about") == ["/about", "/about.html", "/about.md", "/about/", "/about/index.html", "/about/index.md"]


def test_many_pages_are_expanded_without_duplicates_in_order():
    assert expand_site_paths(["/a/", "/a/index.html", "/b/"]) == ["/a/", "/a/index.html", "/a/index.md", "/b/", "/b/index.html", "/b/index.md"]


@pytest.mark.parametrize("bad", ["", "   ", "/*", "/articles/*", "*"])
def test_a_wildcard_or_empty_path_is_refused(bad):
    with pytest.raises(InvalidPagePath):
        expand_site_paths([bad])


def test_page_keys_become_every_form_a_page_is_cached_under():
    assert paths_for_page_keys(["index.html", "articles/a/index.html", "articles/a/index.md", "articles/b.html"]) == [
        "/index.html", "/", "/articles/a/index.html", "/articles/a/", "/articles/a/index.md", "/articles/b.html",
    ]
    assert paths_for_page_keys(["posts/b.html", "posts/b.md"], "clean") == ["/posts/b.html", "/posts/b", "/posts/b.md"]


def test_no_expansion_ever_makes_a_wildcard():
    everything = expand_site_paths(["/", "/a/", "/b.html", "/c.md", "/d"]) + paths_for_page_keys([f"p/{n}/index.html" for n in range(2000)])
    assert not any("*" in path for path in everything)


# ------------------------------------------------------------------ the purge itself


class FakeCloudFront:
    def __init__(self, fail_after: int | None = None):
        self.calls: list[dict] = []
        self.fail_after = fail_after

    def create_invalidation(self, **arguments):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise RuntimeError("AccessDenied: not allowed to create invalidations")
        self.calls.append(arguments)
        return {"Invalidation": {"Id": f"I{len(self.calls)}", "Status": "InProgress"}}


def test_an_explicit_purge_never_collapses_to_a_wildcard_however_many_paths():
    cloudfront = FakeCloudFront()
    paths = [f"/p/{n}/" for n in range(3500)]
    made = invalidate_exact_paths("EDIST", paths, cloudfront)
    assert [call["InvalidationBatch"]["Paths"]["Quantity"] for call in cloudfront.calls] == [3000, 500]
    assert all("/*" not in call["InvalidationBatch"]["Paths"]["Items"] for call in cloudfront.calls)
    assert made == [{"id": "I1", "status": "InProgress", "paths": 3000}, {"id": "I2", "status": "InProgress", "paths": 500}]


def test_the_cost_note_is_the_published_price():
    assert invalidation_cost_note(10) == {"paths": 10, "freePathsPerMonth": 1000, "usdPerPathAfterFree": 0.005, "usdAtMost": 0.05}


# ------------------------------------------------------------------ a real standard projector: which pages list a story


SETTINGS = settings(
    urls={"style": "directory", "sections": {"articles": {"pageSize": 2}, "videos": {}}},
    listings={"pageSize": 2, "featuredCount": 0, "tags": False},
    agents={"markdown": True},
)
ITEMS = [
    item("a1", section="articles", date="2026-01-05"),
    item("a2", section="articles", date="2026-01-04"),
    item("a3", section="articles", date="2026-01-03"),
    item("a4", section="articles", date="2026-01-02"),
    item("v1", section="videos", date="2026-01-01"),
]


@pytest.fixture()
def site():
    built = DirectorySite(SETTINGS, ITEMS)
    projector = StandardMarkusProjector.from_static_directory(built.static, environ=built.environ)
    source = DirectoryContentSource(built.content)
    context = ProjectionContext(source=source, projector=projector, writer=LocalDirectoryWriter(built.out), keep_state=False)
    yield built, context
    built.cleanup()


def service_for(context, cloudfront=None, distribution="EDIST"):
    return RefreshService(distribution_id=distribution, context=lambda: context, cloudfront=cloudfront if cloudfront is not None else FakeCloudFront(), sleep=lambda _s: None)


def test_a_story_fans_out_to_the_pages_that_list_it_and_only_those(site):
    _built, context = site
    result = service_for(context).refresh_story("file:articles/a1.md", dry_run=True)
    indexes = result["pages"]["indexes"]
    assert "index.html" in indexes and "articles/index.html" in indexes and "articles/index.md" in indexes
    assert "articles/page/2/index.html" not in indexes      # a1 is the newest: it is on page 1 only
    assert not any(key.startswith("videos/") for key in indexes)
    assert result["pages"]["story"] == ["articles/a1/index.html", "articles/a1/index.md"]
    paths = result["invalidation"]["paths"]
    for form in ("/articles/a1/", "/articles/a1/index.html", "/articles/a1/index.md", "/", "/index.html", "/articles/", "/articles/index.html"):
        assert form in paths, form
    assert not any("*" in path for path in paths)
    assert result["dryRun"] and result["invalidation"]["status"] == "dry-run"


def test_an_older_story_fans_out_to_its_own_page_of_the_paging(site):
    _built, context = site
    result = service_for(context).refresh_story("file:articles/a4.md", dry_run=True)
    indexes = result["pages"]["indexes"]
    assert "articles/page/2/index.html" in indexes and "articles/page/2/index.md" in indexes
    assert "articles/index.html" not in indexes


def test_a_video_story_reaches_its_own_section_and_not_the_articles_pages(site):
    _built, context = site
    indexes = service_for(context).refresh_story("file:videos/v1.md", dry_run=True)["pages"]["indexes"]
    assert "videos/index.html" in indexes
    assert not any(key.startswith("articles/") for key in indexes)


def test_the_index_refresh_is_home_every_list_page_and_every_section_page(site):
    _built, context = site
    result = service_for(context).refresh_indexes(dry_run=True)
    indexes = set(result["pages"]["indexes"])
    assert {"index.html", "index.md", "articles/index.html", "articles/page/2/index.html", "videos/index.html"} <= indexes
    assert not any("/a1/" in key for key in indexes)       # no story pages
    assert not any("*" in path for path in result["invalidation"]["paths"])
    assert result["invalidation"]["count"] == len(result["invalidation"]["paths"])


def test_an_unknown_story_is_refused_and_nothing_is_purged(site):
    _built, context = site
    cloudfront = FakeCloudFront()
    result = run_operation("site_refresh_story", {"storyLineageId": "nope"}, service_for(context, cloudfront))
    assert result["ok"] is False and result["error"]["code"] == "not_found"
    assert cloudfront.calls == []


# ------------------------------------------------------------------ outcomes


def test_a_refresh_reports_the_cloudfront_invalidation_id_and_status():
    cloudfront = FakeCloudFront()
    result = RefreshService("EDIST", cloudfront=cloudfront).refresh_pages(["/articles/x/"])
    assert result["ok"] and result["invalidation"]["status"] == "invalidated"
    assert result["invalidation"]["requests"] == [{"id": "I1", "status": "InProgress", "paths": 3}]
    assert cloudfront.calls[0]["DistributionId"] == "EDIST"


def test_a_dry_run_invalidates_nothing_and_needs_no_distribution():
    cloudfront = FakeCloudFront()
    result = RefreshService(None, cloudfront=cloudfront).refresh_pages(["/articles/x/"], dry_run=True)
    assert result["ok"] and cloudfront.calls == [] and result["invalidation"]["count"] == 3


def test_a_failed_invalidation_is_not_ok_and_says_why():
    result = RefreshService("EDIST", cloudfront=FakeCloudFront(fail_after=0)).refresh_pages(["/a/"])
    assert result["ok"] is False
    assert result["invalidation"]["status"] == "failed" and "AccessDenied" in result["invalidation"]["error"]


def test_no_distribution_is_a_failed_invalidation_not_a_silent_skip():
    result = RefreshService(None).refresh_pages(["/a/"])
    assert result["ok"] is False and "PAPYRUS_EDGE_DISTRIBUTION_ID" in result["invalidation"]["error"]


# ------------------------------------------------------------------ URL prefix filter

PREFIX_KEYS = ["index.html", "index.md", "posts/index.html", "posts/index.md", "posts/page/2/index.html", "postscript/index.html", "tags/index.html", "about.html"]


def test_a_prefix_selects_the_pages_whose_url_path_starts_with_it():
    assert keys_under(PREFIX_KEYS, ["/posts/"]) == ["posts/index.html", "posts/index.md", "posts/page/2/index.html"]


def test_repeated_prefixes_select_the_union_in_key_order():
    assert keys_under(PREFIX_KEYS, ["/tags/", "/posts/page/"]) == ["posts/page/2/index.html", "tags/index.html"]


def test_a_prefix_without_a_slash_stops_at_a_path_segment():
    assert keys_under(PREFIX_KEYS, ["/posts"]) == ["posts/index.html", "posts/index.md", "posts/page/2/index.html"]   # not /postscript/


def test_the_root_prefix_selects_every_page():
    assert keys_under(PREFIX_KEYS, ["/"]) == sorted(PREFIX_KEYS)


def test_a_prefix_can_be_a_full_url_or_lack_the_leading_slash():
    assert normalize_prefixes(["https://example.org/posts/?x=1", "tags/"]) == ["/posts/", "/tags/"]


def test_a_prefix_is_a_url_path_only_never_a_wildcard_or_empty():
    for bad in ("", "  ", "/posts/*"):
        with pytest.raises(InvalidPagePath):
            normalize_prefixes([bad])


def test_a_clean_url_style_page_matches_by_its_extensionless_path():
    assert keys_under(["posts/archive.html"], ["/posts/archive"], "clean") == ["posts/archive.html"]


# ------------------------------------------------------------------ re-render


def test_a_rerender_reports_what_it_wrote_separately_from_the_purge(site):
    built, context = site
    cloudfront = FakeCloudFront()
    result = service_for(context, cloudfront).rerender("indexes", confirm=True)
    assert result["rendered"]["ok"] and result["rendered"]["count"] > 0
    assert "articles/index.html" in result["rendered"]["written"]
    assert (built.out / "articles" / "index.html").exists()
    assert "/articles/" in result["invalidation"]["paths"] and "/articles/index.html" in result["invalidation"]["paths"]
    assert not any("*" in path for path in result["invalidation"]["paths"])
    assert result["ok"] and result["invalidation"]["status"] == "invalidated"


def test_a_rerender_purges_exactly_the_pages_even_when_the_engine_would_have_gone_wildcard(site):
    _built, context = site
    cloudfront = FakeCloudFront()
    context.invalidate = lambda keys: ["/*"]          # what a big engine run does; the operation must not use it
    result = service_for(context, cloudfront).rerender("all", confirm=True, force_paths=500)
    assert result["invalidation"]["count"] > 10
    assert all("/*" not in call["InvalidationBatch"]["Paths"]["Items"] for call in cloudfront.calls)


def test_a_story_rerender_writes_that_storys_pages(site):
    built, context = site
    result = service_for(context).rerender("story", lineage="file:articles/a2.md", confirm=True)
    assert "articles/a2/index.html" in result["rendered"]["written"]
    assert "/articles/a2/" in result["invalidation"]["paths"] and "/articles/a2/index.html" in result["invalidation"]["paths"]


def test_rerender_dry_run_writes_nothing_and_lists_the_pages(site):
    built, context = site
    cloudfront = FakeCloudFront()
    result = service_for(context, cloudfront).rerender("all", dry_run=True, force_paths=500)
    assert result["rendered"]["dryRun"] and "articles/a1/index.html" in result["rendered"]["wouldWrite"]
    assert cloudfront.calls == [] and not (built.out / "index.html").exists()


def test_rerender_without_invalidation_still_reports_the_write(site):
    _built, context = site
    cloudfront = FakeCloudFront()
    result = service_for(context, cloudfront).rerender("indexes", invalidate=False, confirm=True)
    assert result["rendered"]["ok"] and result["invalidation"]["status"] == "not-requested" and cloudfront.calls == []


def test_a_failed_purge_after_a_good_render_is_reported_apart(site):
    _built, context = site
    result = service_for(context, FakeCloudFront(fail_after=0)).rerender("indexes", confirm=True)
    assert result["rendered"]["ok"] is True and result["invalidation"]["ok"] is False and result["ok"] is False


# ------------------------------------------------------------------ one table behind the CLI and the MCP tools


def test_the_mcp_tools_are_the_operation_table():
    assert set(page_refresh_tools()) == {operation.name for operation in OPERATIONS} == {
        "site_refresh_pages", "site_refresh_story", "site_refresh_indexes", "site_rerender_pages", "site_update_live", "site_inspect",
    }
    assert set(page_refresh_descriptions()) == set(page_refresh_tools())
    assert all(audience == "staff" for audience, _schema in page_refresh_tools().values())
    json.dumps(page_refresh_tools())


def test_a_tool_call_validates_its_input_and_returns_the_same_json_as_the_command():
    service = RefreshService("EDIST", cloudfront=FakeCloudFront())
    ok = call_page_refresh_tool("site_refresh_pages", {"paths": ["/a/"], "dryRun": True}, service)
    assert ok["ok"] and ok["operation"] == "site_refresh_pages"
    for bad in ({}, {"paths": []}, {"paths": ["/a/"], "extra": 1}, {"paths": "/a/"}):
        refused = call_page_refresh_tool("site_refresh_pages", bad, service)
        assert refused["ok"] is False and refused["error"]["code"] == "invalid_input", bad
    assert call_page_refresh_tool("site_rerender_pages", {"scope": "story"}, service)["error"]["code"] == "invalid_input"
    assert call_page_refresh_tool("site_rerender_pages", {"scope": "everything"}, service)["error"]["code"] == "invalid_input"
    assert call_page_refresh_tool("nope", {}, service)["error"]["code"] == "unknown_operation"


# ------------------------------------------------------------------ the guard: cap and dry-run-first


from papyrus_content.page_refresh.budget import Budget  # noqa: E402


def many_pages(count):
    return [f"/articles/story-{n}/" for n in range(count)]


def test_a_call_over_the_cap_is_refused_naming_the_override():
    cloudfront = FakeCloudFront()
    result = RefreshService("EDIST", cloudfront=cloudfront).refresh_pages(many_pages(10), confirm=True)   # 30 paths, cap 25
    assert result["ok"] is False and result["error"]["code"] == "over_path_cap"
    assert "--force-paths 30" in result["error"]["message"] and "maxInvalidationPaths" in result["error"]["message"]
    assert result["invalidation"]["status"] == "refused" and cloudfront.calls == []


def test_the_override_is_explicit_and_must_cover_the_count():
    cloudfront = FakeCloudFront()
    service = RefreshService("EDIST", cloudfront=cloudfront)
    assert service.refresh_pages(many_pages(10), confirm=True, force_paths=29)["error"]["code"] == "over_path_cap"
    assert service.refresh_pages(many_pages(10), confirm=True, force_paths=30)["ok"] is True
    assert len(cloudfront.calls) == 1


def test_the_cap_is_a_site_setting():
    service = RefreshService("EDIST", cloudfront=FakeCloudFront(), budget=Budget(path_cap=6))
    assert service.refresh_pages(many_pages(3), confirm=True)["error"]["code"] == "over_path_cap"


def test_more_than_five_paths_is_a_dry_run_until_confirmed():
    cloudfront = FakeCloudFront()
    service = RefreshService("EDIST", cloudfront=cloudfront)
    first = service.refresh_pages(many_pages(3))          # 9 paths
    assert first["ok"] and first["dryRun"] and first["needsRun"] and cloudfront.calls == [] and "--run" in first["hint"]
    assert len(first["invalidation"]["paths"]) == 9
    second = service.refresh_pages(many_pages(3), confirm=True)
    assert second["invalidation"]["status"] == "invalidated" and len(cloudfront.calls) == 1


def test_five_paths_or_fewer_runs_at_once():
    cloudfront = FakeCloudFront()
    assert RefreshService("EDIST", cloudfront=cloudfront).refresh_pages(["/a/"])["invalidation"]["status"] == "invalidated"


# ------------------------------------------------------------------ update-live: the whole loop


class FakeEdge:
    """What the public site serves: a page that ends with the source-version marker of the version the edge holds."""

    def __init__(self, version):
        self.version, self.fetched = version, []

    def __call__(self, url):
        self.fetched.append(url)
        return 200, {"age": "12", "x-cache": "Hit from cloudfront"}, f"<html>page</html>\n<!-- papyrus-source-version: {self.version} -->\n".encode()


def live_service(context, edge, cloudfront=None):
    service = service_for(context, cloudfront)
    service.public_url, service.fetch = "https://site.example", edge
    return service


def test_update_live_is_a_dry_run_first_because_a_story_touches_more_than_five_paths(site):
    _built, context = site
    cloudfront = FakeCloudFront()
    result = live_service(context, FakeEdge(1), cloudfront).update_live("file:articles/a1.md")
    assert result["dryRun"] and result["needsRun"] and cloudfront.calls == []
    assert "/articles/a1/" in result["invalidation"]["paths"] and "/" in result["invalidation"]["paths"]


def test_update_live_projects_purges_exactly_and_verifies_the_live_version(site):
    built, context = site
    cloudfront, edge = FakeCloudFront(), FakeEdge(1)
    result = live_service(context, edge, cloudfront).update_live("file:articles/a1.md", confirm=True, verify_seconds=0)
    assert (built.out / "articles" / "a1" / "index.html").exists()
    assert result["rendered"]["ok"] and result["invalidation"]["status"] == "invalidated"
    assert not any("*" in path for path in result["invalidation"]["paths"])
    assert {"/articles/a1/", "/articles/a1/index.html", "/articles/a1/index.md", "/", "/articles/"} <= set(result["invalidation"]["paths"])
    assert result["verification"]["current"] is True and result["verdict"].startswith("LIVE")
    assert result["ok"] and set(edge.fetched) == {"https://site.example/articles/a1/index.html", "https://site.example/articles/a1/"}


def test_update_live_says_the_edge_is_stale_when_the_public_page_is_an_old_version(site):
    _built, context = site
    result = live_service(context, FakeEdge(0), FakeCloudFront()).update_live("file:articles/a1.md", confirm=True, verify_seconds=0)
    assert result["verification"]["current"] is False and "STALE" in result["verdict"] and result["ok"] is False


def test_update_live_over_the_cap_writes_nothing(site):
    built, context = site
    service = live_service(context, FakeEdge(1), FakeCloudFront())
    service.budget = Budget(path_cap=4)
    result = service.update_live("file:articles/a1.md", confirm=True)
    assert result["error"]["code"] == "over_path_cap" and not (built.out / "articles").exists()


def test_the_source_version_marker_round_trips():
    from papyrus_content.page_refresh.marker import source_version_of, with_source_version

    marked = with_source_version("a/index.html", b"<html></html>\n", 7)
    assert source_version_of(marked) == 7 and with_source_version("a/index.html", marked, 8).count(b"papyrus-source-version") == 1
    assert with_source_version("a.css", b"x", 7) == b"x" and source_version_of(b"<html></html>") is None


# ------------------------------------------------------------------ inspect: the verdict, stage by stage


import datetime as dt  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from papyrus_content.projection.model import ItemSummary, SiteIndex  # noqa: E402
from papyrus_content.projection.writers import StoredObject  # noqa: E402

LINEAGE = "lineage-containment"
KEYS = ("articles/containment/index.html", "articles/containment/index.md")


class InspectClient:
    def __init__(self, published=7, versions=7):
        self.rows = [{"versionNumber": n, "versionState": "current" if n == versions else "superseded", "stage": "published" if n == versions else "copywriting", "authorLabel": "AI", "versionCreatedAt": f"2026-11-08T1{n % 10}:00:00Z"} for n in range(1, versions + 1)]
        self.published = published

    def list_by_index(self, name, key, **_):
        return self.rows

    def get_record(self, model, ident):
        return {"versionNumber": self.published, "publishedAt": "2026-11-08T17:06:41Z"} if self.published else None


class InspectWriter:
    def __init__(self, version=7, modified="2026-11-08T17:07:42+00:00"):
        self.version, self.modified = version, modified

    def head(self, key):
        return StoredObject(key=key, version=self.version, last_modified=self.modified)

    def get(self, key):
        return f"<html></html>\n<!-- papyrus-source-version: {self.version} -->\n".encode()


class StubProjector:
    def item_page_paths(self, summary):
        return KEYS


def inspect_service(client=None, writer=None, edge=None):
    summary = ItemSummary("item-1", "article", "articles", "containment", "articles/containment.md", 7, "T", None, {}, (), None, lineage_id=LINEAGE)
    context = SimpleNamespace(source=SimpleNamespace(site_index=lambda: SiteIndex(items=(summary,), load_item=None), _client=client or InspectClient()), projector=StubProjector(), writer=writer or InspectWriter())
    service = RefreshService("EDIST", context=lambda: context, cloudfront=FakeCloudFront(), sleep=lambda _s: None, emit_metric=False, public_url="https://site.example")
    service.fetch = edge or (lambda url: (200, {"age": "3169", "last-modified": "Sun, 08 Nov 2026 16:11:36 GMT", "etag": '"abc"', "x-cache": "Hit from cloudfront", "cache-control": "public, max-age=0, s-maxage=3600"}, b"<html></html>"))
    return service, context


NOW = dt.datetime(2026, 11, 8, 18, 4, 25, tzinfo=dt.timezone.utc)


def test_inspect_the_real_case_published_v7_stored_from_v7_edge_cached_before_that():
    service, _ = inspect_service()
    report = service.inspect(lineage=LINEAGE, now=NOW)
    assert report["verdictCode"] == "edge-stale" and report["ok"] is False
    assert "version 7" in report["verdict"] and "3169" in report["verdict"] and "16:11:36" in report["verdict"] and "refresh --path" in report["verdict"]
    assert [v["version"] for v in report["record"]["versions"]] == [1, 2, 3, 4, 5, 6, 7]
    assert report["record"]["published"] == {"version": 7, "publishedAt": "2026-11-08T17:06:41Z"}
    assert report["projected"]["pages"]["articles/containment/index.html"]["sourceVersion"] == 7
    seen = report["edge"]["urls"]["/articles/containment/"]
    assert (seen["status"], seen["age"], seen["etag"], seen["xCache"], seen["sMaxAge"]) == (200, "3169", '"abc"', "Hit from cloudfront", "3600")


def test_inspect_finds_the_edge_serving_an_older_version_by_its_marker():
    service, _ = inspect_service(edge=lambda url: (200, {"age": "5"}, b"<!-- papyrus-source-version: 6 -->\n"))
    report = service.inspect(path="/articles/containment/", now=NOW)
    assert report["verdictCode"] == "edge-stale" and "serves version 6" in report["verdict"]


def test_inspect_says_everything_is_current_when_the_edge_serves_the_published_version():
    service, _ = inspect_service(edge=lambda url: (200, {"age": "2"}, b"<!-- papyrus-source-version: 7 -->\n"))
    report = service.inspect(lineage=LINEAGE, now=NOW)
    assert report["verdictCode"] == "current" and report["ok"] is True


def test_inspect_finds_a_published_page_that_was_never_re_projected():
    service, _ = inspect_service(writer=InspectWriter(version=6))
    report = service.inspect(lineage=LINEAGE, now=NOW)
    assert report["verdictCode"] == "never-reprojected" and "rendered from 6" in report["verdict"] and "update-live" in report["verdict"]


def test_inspect_says_not_published_when_there_is_no_published_pointer():
    service, _ = inspect_service(client=InspectClient(published=None))
    report = service.inspect(lineage=LINEAGE, now=NOW)
    assert report["verdictCode"] == "not-published" and report["record"]["published"] is None


def test_inspect_fix_purges_the_exact_stale_paths_then_looks_again():
    calls = []
    service, _ = inspect_service()
    original = service.cloudfront.create_invalidation

    def create(**arguments):
        calls.append(arguments)
        service.fetch = lambda url: (200, {"age": "1"}, b"<!-- papyrus-source-version: 7 -->\n")
        return original(**arguments)

    service.cloudfront.create_invalidation = create
    report = service.inspect(lineage=LINEAGE, fix=True, now=NOW)
    assert calls and set(calls[0]["InvalidationBatch"]["Paths"]["Items"]) == {"/articles/containment/index.html", "/articles/containment/", "/articles/containment/index.md"}
    assert report["verdictCode"] == "current" and report["fix"]["ran"] is True


def test_inspect_without_fix_changes_nothing():
    service, _ = inspect_service()
    service.inspect(lineage=LINEAGE, now=NOW)
    assert service.cloudfront.calls == []


# ------------------------------------------------------------------ re-render under a URL prefix


def test_a_rerender_under_a_prefix_writes_and_purges_only_those_pages(site):
    built, context = site
    cloudfront = FakeCloudFront()
    result = service_for(context, cloudfront).rerender("indexes", under=["/videos/"], confirm=True)
    written = result["rendered"]["written"]
    assert "videos/index.html" in written and written and all(key.startswith("videos/") for key in written)
    assert not (built.out / "index.html").exists() and not (built.out / "articles" / "index.html").exists()
    assert result["invalidation"]["paths"] and all(path.startswith("/videos/") for path in result["invalidation"]["paths"])
    assert result["target"]["under"] == ["/videos/"] and result["ok"]


def test_repeated_prefixes_rerender_the_union(site):
    _built, context = site
    result = service_for(context).rerender("indexes", under=["/videos/", "/articles/page/"], confirm=True)
    written = result["rendered"]["written"]
    assert "videos/index.html" in written and "articles/page/2/index.html" in written and "articles/index.html" not in written


def test_a_prefix_that_matches_no_index_page_is_an_error_that_says_so(site):
    built, context = site
    with pytest.raises(Exception) as caught:
        service_for(context).rerender("indexes", under=["/nowhere/"], confirm=True)
    assert getattr(caught.value, "code", None) == "no_pages_match" and "/nowhere/" in caught.value.message
    assert not (built.out / "index.html").exists()
    result = run_operation("site_rerender_pages", {"scope": "indexes", "under": ["/nowhere/"]}, service_for(context))
    assert result["ok"] is False and result["error"]["code"] == "no_pages_match"


def test_under_only_goes_with_the_index_pages(site):
    _built, context = site
    for scope, extra in (("all", {}), ("story", {"storyLineageId": "file:articles/a1.md"})):
        result = run_operation("site_rerender_pages", {"scope": scope, "under": ["/articles/"], **extra}, service_for(context))
        assert result["ok"] is False and result["error"]["code"] == "invalid_input" and "--indexes" in result["error"]["message"]


def test_a_dry_run_under_a_prefix_lists_exactly_the_pages_and_their_count(site):
    built, context = site
    cloudfront = FakeCloudFront()
    result = service_for(context, cloudfront).rerender("indexes", under=["/videos/"], dry_run=True)
    rendered = result["rendered"]
    assert rendered["dryRun"] and rendered["wouldWrite"] == ["videos/index.html", "videos/index.md"] and rendered["count"] == 2
    assert cloudfront.calls == [] and not (built.out / "videos").exists()


def test_the_prefix_filter_knows_no_site_specific_type_names():
    import inspect

    from papyrus_content.page_refresh import paths

    source = inspect.getsource(paths.keys_under) + inspect.getsource(paths.normalize_prefixes)
    for name in ("article", "post", "video", "edition"):
        assert name not in source.lower()


def test_the_cli_text_lists_the_pages_a_dry_run_would_write_and_never_says_wrote():
    from papyrus_content.page_refresh.cli import render_text

    text = render_text({"ok": True, "operation": "site_rerender_pages", "dryRun": True, "rendered": {"ok": True, "dryRun": True, "wouldWrite": ["videos/index.html", "videos/index.md"], "count": 2, "errors": []},
                        "invalidation": {"ok": True, "status": "dry-run", "paths": ["/videos/"], "count": 1, "cost": {}}})
    assert "would write 2 pages" in text and "/videos/index.html" in text and "/videos/index.md" in text and "wrote" not in text.replace("would write", "")


def test_the_cli_text_says_how_many_pages_a_scheduled_rerender_was_asked_to_rebuild():
    from papyrus_content.page_refresh.cli import render_text

    text = render_text({"ok": True, "operation": "site_rerender_pages", "dryRun": False, "scheduled": True, "rendered": {"ok": None, "scheduled": True, "requested": 7, "count": 0, "errors": []},
                        "invalidation": {"ok": True, "status": "scheduled", "paths": [], "count": 0, "cost": {}}})
    assert "scheduled" in text and "7 pages" in text and "wrote" not in text


def test_the_cli_reads_a_repeated_under_flag():
    from papyrus_content.page_refresh.cli import operation_for, split_flags

    paths, options = split_flags(["--indexes", "--under", "/posts/", "--under", "/tags/", "--dry-run"])
    name, arguments = operation_for(paths, options, rerender=True)
    assert name == "site_rerender_pages" and arguments["scope"] == "indexes" and arguments["under"] == ["/posts/", "/tags/"]
    with pytest.raises(ValueError):
        split_flags(["--indexes", "--under"])
