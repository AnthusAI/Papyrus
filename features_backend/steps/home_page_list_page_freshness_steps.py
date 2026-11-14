"""Steps for features_backend/home-page-list-page-freshness.feature. Synthetic data in local directories only: no network, no AWS."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.home_page import incremental_test as corpus  # noqa: E402
from procedures.newsroom.tests.test_reference_list_page_dependencies import (  # noqa: E402
    FRONTS_SNAPSHOT, LIST_PAGES, VideoSite, fronts_site, full_rebuild, reader_keys, rewrite_snapshot, rewritten_list_pages,
)


@given("a site whose list pages show accepted videos, videos filed under Music, videos filed under Art and accepted findings")
def _(context):
    context.video_site = VideoSite()
    context.add_cleanup(context.video_site.cleanup)


@given("the snapshot was built by a full read")
def _(context):
    assert context.video_site.first["mode"] == "full"


def picture_for(context, row_id: str) -> None:
    context.changed = row_id
    context.video_site.client.give_thumbnail(row_id)
    context.report = context.video_site.change(row_id)


@when("the newest Music video gets its stored thumbnail and the snapshot run reads it again")
def _(context):
    picture_for(context, context.video_site.music_video)


@when("the newest Art video gets its stored thumbnail and the snapshot run reads it again")
def _(context):
    picture_for(context, context.video_site.art_video)


@when("an older Art video gets its stored thumbnail and the snapshot run reads it again")
def _(context):
    picture_for(context, context.video_site.oldest_video)


@when("a recommended Reference is retitled and the snapshot run reads it again")
def _(context):
    context.video_site.client.rows[context.video_site.pending]["title"] = "A pending Reference, retitled"
    context.report = context.video_site.change(context.video_site.pending)


@then("the snapshot file carries the video's picture")
def _(context):
    assert context.report["written"] == [corpus.REFERENCES_KEY], context.report
    context.picture = context.video_site.record(context.changed)["image"]
    assert context.picture and context.picture.startswith("/assets/reference-thumbnails/"), context.picture


@then("the Videos page and the Music videos page are re-projected, with their Markdown twins, and show the picture")
def _(context):
    assert {"videos", "music-videos"} <= rewritten_list_pages(context.report), context.report["rewritten"]
    assert {"videos/index.md", "music-videos/index.md"} <= set(context.report["rewritten"]), context.report["rewritten"]
    for name in ("videos", "music-videos"):
        assert context.picture in context.video_site.site.text(LIST_PAGES[name]), name


@then("the Art videos page and the Findings page are not re-projected")
def _(context):
    assert not rewritten_list_pages(context.report) & {"art-videos", "findings"}, context.report["rewritten"]


@then("no chunk file of a paged list is re-projected")
def _(context):
    assert not [key for key in context.report["rewritten"] if key.startswith("reference-lists/")], context.report["rewritten"]


@then("only chunk files of the Videos list are re-projected among the paged lists")
def _(context):
    chunks = [key for key in context.report["rewritten"] if key.startswith("reference-lists/")]
    assert chunks and all(key.startswith("reference-lists/videos/all/") for key in chunks), context.report["rewritten"]


@then("the Art videos page is re-projected and the Videos page is not")
def _(context):
    assert rewritten_list_pages(context.report) == {"art-videos"}, context.report["rewritten"]


@then("the snapshot file carries the new title")
def _(context):
    assert context.report["written"] == [corpus.REFERENCES_KEY], context.report
    assert context.video_site.record(context.video_site.pending)["title"] == "A pending Reference, retitled"


@then("no page is re-projected")
def _(context):
    assert context.report["rewritten"] == [] and context.report["pagesRewritten"] == 0, context.report["rewritten"]


@then("every list page is what a full projection from the new snapshot draws")
def _(context):
    rebuilt = full_rebuild(context.video_site)
    try:
        for key in LIST_PAGES.values():
            assert rebuilt.text(key) == context.video_site.site.text(key), key
    finally:
        rebuilt.cleanup()


@given("a site whose Essays section front shows the two newest accepted Essays References")
def _(context):
    context.fronts = fronts_site()
    context.add_cleanup(context.fronts.cleanup)
    context.fronts_document = json.loads(FRONTS_SNAPSHOT.read_text(encoding="utf-8"))
    assert "essays/index.html" in reader_keys(context.fronts)


def retitle_front_reference(context, title: str, new_title: str) -> None:
    next(found for found in context.fronts_document["references"] if found["title"] == title)["title"] = new_title
    context.fronts_written = rewrite_snapshot(context.fronts, context.fronts_document)


@when("a Reference on that grid is retitled and the snapshot file is written")
def _(context):
    assert "Walls atlas" in context.fronts.text("essays/index.html")
    retitle_front_reference(context, "Walls atlas", "Walls atlas, second edition")


@when("a Reference filed under Notes is retitled and the snapshot file is written")
def _(context):
    retitle_front_reference(context, "Tide notes", "Tide notes, retitled")


@then("the Essays front is re-projected and shows the new title")
def _(context):
    assert "essays/index.html" in context.fronts_written, context.fronts_written
    assert "Walls atlas, second edition" in context.fronts.text("essays/index.html")


@then("the Essays front is not re-projected")
def _(context):
    assert "essays/index.html" not in context.fronts_written, context.fronts_written
