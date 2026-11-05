"""Steps for features_backend/reference-video-thumbnails.feature. In memory: no site, no AWS, no platform, no sleeping."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from test_reference_thumbnails import CORPUS, Site, ok, picture, video  # noqa: E402
from papyrus_content import reference_thumbnails as thumbnails  # noqa: E402
from papyrus_content import references_thumbnails as worker  # noqa: E402
from papyrus_content.home_page.export import public_reference  # noqa: E402
from papyrus_content.home_page.settings import HomePageSettings, home_page_settings_from_mapping  # noqa: E402
from papyrus_content.projection.standard import home_page_blocks  # noqa: E402
from papyrus_content.projection.standard.page_ledger import PageLedger  # noqa: E402
from papyrus_content.reference_images import preview_attachment_id  # noqa: E402

NEWEST, SECOND = "aaaaaaaaaaa", "bbbbbbbbbbb"
NEWEST_ID, SECOND_ID, ARTICLE_ID = f"reference-{NEWEST}-v1", f"reference-{SECOND}-v1", "reference-article-v1"
PLATFORM_PICTURE = f"https://i.ytimg.com/vi/{NEWEST}/maxresdefault.jpg"
SETTINGS = home_page_settings_from_mapping({"references": {"corpus": CORPUS}})
GREY = picture(120, 90, colour=(128, 128, 128))


class Platforms:
    """YouTube, Vimeo and the rest, scripted per address; counts every request."""

    def __init__(self):
        self.table: dict[str, object] = {}
        self.asked: list[str] = []
        self.refuse_everything = False

    def __call__(self, address):
        self.asked.append(address)
        if self.refuse_everything or isinstance(self.table.get(address), Exception):
            raise thumbnails.Unreachable("refused")
        if address in self.table:
            return self.table[address]
        if address.startswith("https://img.youtube.com/"):
            return ok(picture(480, 360))
        raise AssertionError(f"unscripted request {address}")


def youtube_picture(identifier):
    return f"https://img.youtube.com/vi/{identifier}/hqdefault.jpg"


@given("a site with accepted and pending videos and an ordinary article")
def _(context):
    article = {"id": ARTICLE_ID, "lineageId": "reference-article", "title": "An article", "sourceUri": "https://example.org/a", "feedArrivalAt": "2026-11-01T00:00:00.000Z"}
    context.site = Site([video(NEWEST, "2026-11-04T00:00:00.000Z", "accepted"), video(SECOND, "2026-11-03T00:00:00.000Z", "pending"), article])
    context.platforms, context.copies, context.output, context.code, context.errors = Platforms(), [], "", None, ""
    context.fetches = lambda address: thumbnails.fetch_thumbnail(address, context.platforms)
    context.record, context.preview = None, None
    environment = mock.patch.dict("os.environ", {}, clear=False)   # the command selects the signed-in lane in the environment; undo that after the scenario
    environment.start()
    context.add_cleanup(environment.stop)


@given("a Vimeo video that oEmbed gives a thumbnail for")
def _(context):
    context.site.rows["reference-vimeo-v1"] = {**video("vvvvvvvvvvv", "2026-11-05T00:00:00.000Z"), "id": "reference-vimeo-v1", "lineageId": "reference-vimeo",
                                              "sourceUri": "https://vimeo.com/76979871"}
    ask = "https://vimeo.com/api/oembed.json?url=https%3A%2F%2Fvimeo.com%2F76979871"
    context.platforms.table[ask] = ok(json.dumps({"thumbnail_url": "https://i.vimeocdn.com/video/1_295x166"}).encode(), "application/json")
    context.platforms.table["https://i.vimeocdn.com/video/1_295x166"] = ok(picture(295, 166))
    context.vimeo_ask = ask


@given("a Twitch video")
def _(context):
    context.site.rows["reference-twitch-v1"] = {**video("ttttttttttt", "2026-11-05T00:00:00.000Z"), "id": "reference-twitch-v1", "lineageId": "reference-twitch",
                                               "sourceUri": "https://www.twitch.tv/videos/123456"}


@given('YouTube answers "not found" with its grey 120 pixel picture for the newest video')
def _(context):
    context.platforms.table[youtube_picture(NEWEST)] = thumbnails.Response(404, "image/jpeg", GREY)


@given("YouTube refuses this connection for the newest video")
def _(context):
    context.platforms.table[youtube_picture(NEWEST)] = thumbnails.Unreachable("refused")


@given("YouTube refuses this connection for every video")
def _(context):
    for n in range(4):
        context.site.rows[f"reference-extra{n}-v1"] = {**video(f"{n:011d}", f"2026-10-{10 + n:02d}T00:00:00.000Z"), "id": f"reference-extra{n}-v1", "lineageId": f"reference-extra{n}"}
    context.platforms.refuse_everything = True


@given("the page declared a platform picture for the newest video")
def _(context):
    context.preview = {"sourceUri": PLATFORM_PICTURE, "metadata": json.dumps({"siteName": "YouTube"})}


@given("the page declared a preview image for the article")
def _(context):
    context.preview = {"sourceUri": "https://example.org/preview.jpg", "metadata": json.dumps({"siteName": "Example"})}


@given("an editor chose an image for the newest video")
def _(context):
    context.preview = {"sourceUri": "https://example.org/chosen.jpg", "metadata": json.dumps({"via": "editor"})}
    context.site.attachments[preview_attachment_id(context.site.rows[NEWEST_ID])] = context.preview


def run(context, *flags):
    out, errors = io.StringIO(), io.StringIO()
    real = sys.stderr
    sys.stderr = errors
    try:
        context.code = worker.command(["--corpus-key", "demo", *flags], client=context.site, out=out, fetch=context.fetches,
                                      upload=lambda path, found: context.copies.append(path), sleep=lambda seconds: None)
    finally:
        sys.stderr = real
    context.output, context.errors = out.getvalue(), errors.getvalue()


@when("the thumbnail worker runs")
def _(context):
    run(context)


@when("the thumbnail worker runs with write")
@given("the thumbnail worker has run with write")
def _(context):
    run(context, "--write")


def record_of(context, identifier, preview=None):
    row = {**context.site.rows[identifier], "curationStatus": "accepted", "curationActorKind": "human"}
    return public_reference(row, None, preview if preview is not None else context.preview, {}, SETTINGS)


@when("the home page snapshot record of the newest video is built")
def _(context):
    context.record = record_of(context, NEWEST_ID)


@when("the home page snapshot record of the article is built")
def _(context):
    context.record = record_of(context, ARTICLE_ID)


@when('a videos block is drawn for a site under the base path "{base}"')
def _(context, base):
    record = {"key": "k1", "status": "accepted", "title": "Talk", "url": "https://www.youtube.com/watch?v=" + NEWEST, "medium": "video",
              "image": record_of(context, NEWEST_ID, {})["image"], "acceptedAt": "2026-11-04T00:00:00Z"}
    context.markup = home_page_blocks.render({"kind": "references", "select": "recent", "medium": "video"}, {"references": [record]}, PageLedger(), HomePageSettings(),
                                             asset_href=lambda path: base + path)


def held(context, identifier):
    return context.site.rows[identifier].get("thumbnailPath")


@then('the picture was asked for at "{address}" without opening the video page')
def _(context, address):
    assert address in context.platforms.asked, context.platforms.asked
    assert not any("watch?v=" in asked or "youtube.com/oembed" in asked for asked in context.platforms.asked), context.platforms.asked


@then('the picture was copied into the site\'s media storage under "{prefix}"')
def _(context, prefix):
    assert context.copies and all(path.startswith(prefix) for path in context.copies), context.copies


@then("the video holds the site path of its copy")
def _(context):
    assert thumbnails.SOURCE_PATH.match(held(context, NEWEST_ID)), held(context, NEWEST_ID)


@then("the Vimeo video was asked about once through its oEmbed address")
def _(context):
    assert context.platforms.asked.count(context.vimeo_ask) == 1


@then("the Vimeo video holds the site path of its copy")
def _(context):
    assert thumbnails.SOURCE_PATH.match(held(context, "reference-vimeo-v1"))


@then('the Twitch video holds "none"')
def _(context):
    assert held(context, "reference-twitch-v1") == "none"


@then("no platform was asked about the Twitch video")
def _(context):
    assert not any("123456" in asked for asked in context.platforms.asked), context.platforms.asked


@then('the newest video holds "none"')
def _(context):
    assert held(context, NEWEST_ID) == "none"


@then("nothing was copied for the newest video")
def _(context):
    assert not any(path for path in context.copies if thumbnails.hash_short("reference-" + NEWEST) in path), context.copies


@then("running the thumbnail worker again does not ask YouTube about it")
def _(context):
    before = context.platforms.asked.count(youtube_picture(NEWEST))
    run(context, "--write")
    assert context.platforms.asked.count(youtube_picture(NEWEST)) == before


@then("the newest video holds nothing")
def _(context):
    assert not held(context, NEWEST_ID)


@then("running the thumbnail worker again asks YouTube about it again")
def _(context):
    before = context.platforms.asked.count(youtube_picture(NEWEST))
    run(context, "--write")
    assert context.platforms.asked.count(youtube_picture(NEWEST)) == before + 1


@then("the worker stopped after three refusals with a message to run it elsewhere")
def _(context):
    assert context.code == worker.EXIT_BLOCKED and len(context.platforms.asked) == 3, (context.code, context.platforms.asked)
    assert "Run this where" in context.errors


@then("no video holds anything")
def _(context):
    assert not any(row.get("thumbnailPath") for row in context.site.rows.values())


@then("every video that needs a thumbnail was listed as one it would fetch")
def _(context):
    wanted = [line for line in context.output.splitlines() if line.split("\t")[2:3] == ["would_fetch"]]
    assert len(wanted) == 2, context.output


@then("no platform was asked and nothing was copied or recorded")
def _(context):
    assert context.platforms.asked == [] and context.copies == [] and context.site.actions == [] and context.site.updates == []


@then("each video was fetched exactly once")
def _(context):
    pictures = sorted(asked for asked in context.platforms.asked if asked.startswith("https://img.youtube.com/"))
    assert pictures == sorted([youtube_picture(NEWEST), youtube_picture(SECOND)]), pictures


@then("its image is the site path of the copy")
def _(context):
    assert context.record["image"] == "/" + held(context, NEWEST_ID), context.record["image"]


@then("its image is not an address on a video platform")
def _(context):
    assert not context.record["image"].startswith("http"), context.record["image"]
    assert "ytimg" not in context.record["image"] and "youtube" not in context.record["image"]


@then("it has no image")
def _(context):
    assert context.record["image"] is None


@then("the site refused to record a thumbnail for the newest video")
def _(context):
    assert not held(context, NEWEST_ID) and "An editor set" in context.output, context.output


@then("the home page snapshot record of the newest video has the editor's image")
def _(context):
    assert record_of(context, NEWEST_ID)["image"] == "https://example.org/chosen.jpg"


@then("its image is the page's preview image")
def _(context):
    assert context.record["image"] == "https://example.org/preview.jpg"


@then('the card for the newest video shows the copy at "{prefix}"')
def _(context, prefix):
    assert f'src="{prefix}' in context.markup, context.markup
