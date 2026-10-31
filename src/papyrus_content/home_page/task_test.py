"""The snapshot rewrites only the pages that read it, and refuses to write with a projector that cannot say which those are."""

import json
from pathlib import Path

import pytest

from features_backend.steps.home_page_snapshot_steps import NOW, FixtureClient
from papyrus_content.home_page.commands import home_page_snapshot, require_standard_site
from papyrus_content.home_page.task import ProjectorRefused, home_page_settings_of, reader_pages_of, run_home_page_snapshot
from papyrus_content.projection.engine import ProjectionContext, UnsafeRewrite, project_stale_listings
from papyrus_content.projection.projector import MarkusSiteProjector
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite

SITE = FIXTURES / "home-page"
STALE = "digest-of-another-build"


@pytest.fixture
def site():
    directory = FIXTURES / "home-page"
    extra = {f"pages/{path.name}": path.read_bytes() for path in sorted((directory / "pages").glob("*.md"))}
    projected = ProjectedSite(settings=json.loads((directory / "projection.json").read_text(encoding="utf-8")), content=directory / "content", extra_files=extra)
    yield projected
    projected.cleanup()


def accept_a_reference(client):
    for row in client.rows():
        if row["title"] == "Pending high":
            row["curationStatus"] = "accepted"
            row["curationStatusKey"] = f"{client.corpus_id}#accepted"
            row["feedStateKey"] = None


def mark_stale(site, key):
    """Store ``key`` as a page whose recorded inputs digest is not the one the projector computes: the state the production home page was in."""
    site.writer.put(key, site.writer.get(key), inputs=STALE)


def run(site, client, **options):
    return run_home_page_snapshot(site.context, client, home_page_settings_of(site.projector), now=NOW, **options)


def test_a_stale_page_without_a_home_page_include_is_not_rewritten(site):
    """Reproduces the 2026-10-31 incident: index.html looked stale, so the snapshot rewrote the site's home page."""
    client = FixtureClient()
    run(site, client)
    mark_stale(site, "index.html")
    original = site.writer.get("index.html")
    accept_a_reference(client)
    site.writer.operations.clear()
    report = run(site, client)
    puts = {key for operation, key in site.writer.operations if operation == "put"}
    assert "index.html" not in puts, puts
    assert site.writer.get("index.html") == original
    assert "front/index.html" in puts
    assert set(report["rewritten"]) == {key for key in puts if key != "_data/home-page/references.json"}


def test_every_rewritten_page_has_a_home_page_include(site):
    client = FixtureClient()
    run(site, client)
    for key in site.projector.home_page_reader_keys():
        mark_stale(site, key)
    mark_stale(site, "quiet/index.html")
    accept_a_reference(client)
    report = run(site, client)
    assert report["rewritten"] and "quiet/index.html" not in report["rewritten"]
    assert set(report["rewritten"]) <= set(site.projector.home_page_reader_keys())


def test_reader_pages_are_the_pages_that_place_a_references_or_threads_include(site):
    keys = reader_pages_of(site.projector)
    assert {"front/index.html", "ranked/index.html", "threads-list/index.html", "mixed/index.html"} <= keys
    assert "quiet/index.html" not in keys and "index.html" not in keys


def test_the_dry_run_lists_the_keys_a_real_run_would_write_and_rewrite(site):
    client = FixtureClient()
    report = run(site, client, dry_run=True)
    assert report["wouldWrite"] == ["_data/home-page/references.json"]
    assert "front/index.html" in report["wouldRewrite"] and "index.html" not in report["wouldRewrite"]
    assert site.writer.get("_data/home-page/references.json") is None


def test_the_task_refuses_a_projector_that_cannot_name_the_reader_pages(site):
    plain = MarkusSiteProjector.from_static_directory(None)
    context = ProjectionContext(source=site.context.source, projector=plain, writer=site.writer)
    before = dict(site.tree)
    with pytest.raises(ProjectorRefused, match="Refusing to write"):
        run_home_page_snapshot(context, FixtureClient(), home_page_settings_of(site.projector), now=NOW)
    assert site.tree == before


def test_the_guard_aborts_before_writing_when_a_projector_renders_an_unselected_page(site):
    class Overeager:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def listing_pages(self, site_index, keys=None):
            pages = self.inner.listing_pages(site_index, keys)
            pages["index.html"] = b"<html>another page</html>"
            return pages

    context = ProjectionContext(source=site.context.source, projector=Overeager(site.projector), writer=site.writer)
    before = dict(site.tree)
    with pytest.raises(UnsafeRewrite, match="index.html"):
        run_home_page_snapshot(context, FixtureClient(), home_page_settings_of(site.projector), now=NOW)
    assert site.tree == before, "the guard must abort before the snapshot file is written"


def test_project_stale_listings_with_a_selection_never_touches_other_pages(site):
    mark_stale(site, "index.html")
    mark_stale(site, "front/index.html")
    site.writer.operations.clear()
    report = project_stale_listings(site.context, {"front/index.html"})
    assert report.written == ["front/index.html"]


def test_a_missing_projection_json_is_refused_naming_the_path(tmp_path):
    with pytest.raises(ValueError, match="projection.json does not exist"):
        require_standard_site({"static-dir": str(tmp_path)}, {})


def test_no_static_directory_is_refused_naming_the_option():
    with pytest.raises(ValueError, match="--static-dir"):
        require_standard_site({}, {})


def test_a_projection_json_without_a_site_object_is_refused(tmp_path):
    (tmp_path / "projection.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="no 'site' object"):
        require_standard_site({"static-dir": str(tmp_path)}, {})


def test_the_standard_site_is_accepted():
    require_standard_site({"static-dir": str(SITE)}, {})


def test_the_cli_refuses_to_write_without_the_sites_settings(tmp_path):
    with pytest.raises(ValueError, match="Refusing to write"):
        home_page_snapshot(["--site", "example", "--out", str(tmp_path / "out"), "--static-dir", str(tmp_path / "missing")])
    assert not (tmp_path / "out").exists()
