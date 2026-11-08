"""Page refresh (PPY-105508): path expansion, the story and index fan-out of a real standard projector, and the operations over a fake CloudFront."""

from __future__ import annotations

import json

import pytest

from papyrus_content.edge_invalidation import invalidate_exact_paths, invalidation_cost_note
from papyrus_content.page_refresh.mcp import call_page_refresh_tool, page_refresh_descriptions, page_refresh_tools
from papyrus_content.page_refresh.operations import OPERATIONS, run_operation
from papyrus_content.page_refresh.paths import InvalidPagePath, expand_site_paths, forms_of_path, paths_for_page_keys
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


# ------------------------------------------------------------------ re-render


def test_a_rerender_reports_what_it_wrote_separately_from_the_purge(site):
    built, context = site
    cloudfront = FakeCloudFront()
    result = service_for(context, cloudfront).rerender("indexes")
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
    result = service_for(context, cloudfront).rerender("all")
    assert result["invalidation"]["count"] > 10
    assert all("/*" not in call["InvalidationBatch"]["Paths"]["Items"] for call in cloudfront.calls)


def test_a_story_rerender_writes_that_storys_pages(site):
    built, context = site
    result = service_for(context).rerender("story", lineage="file:articles/a2.md")
    assert "articles/a2/index.html" in result["rendered"]["written"]
    assert "/articles/a2/" in result["invalidation"]["paths"] and "/articles/a2/index.html" in result["invalidation"]["paths"]


def test_rerender_dry_run_writes_nothing_and_lists_the_pages(site):
    built, context = site
    cloudfront = FakeCloudFront()
    result = service_for(context, cloudfront).rerender("all", dry_run=True)
    assert result["rendered"]["dryRun"] and "articles/a1/index.html" in result["rendered"]["wouldWrite"]
    assert cloudfront.calls == [] and not (built.out / "index.html").exists()


def test_rerender_without_invalidation_still_reports_the_write(site):
    _built, context = site
    cloudfront = FakeCloudFront()
    result = service_for(context, cloudfront).rerender("indexes", invalidate=False)
    assert result["rendered"]["ok"] and result["invalidation"]["status"] == "not-requested" and cloudfront.calls == []


def test_a_failed_purge_after_a_good_render_is_reported_apart(site):
    _built, context = site
    result = service_for(context, FakeCloudFront(fail_after=0)).rerender("indexes")
    assert result["rendered"]["ok"] is True and result["invalidation"]["ok"] is False and result["ok"] is False


# ------------------------------------------------------------------ one table behind the CLI and the MCP tools


def test_the_mcp_tools_are_the_operation_table():
    assert set(page_refresh_tools()) == {operation.name for operation in OPERATIONS} == {
        "site_refresh_pages", "site_refresh_story", "site_refresh_indexes", "site_rerender_pages",
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
