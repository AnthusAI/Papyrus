"""Steps for features_backend/reference-medium.feature. Everything is in memory: no network, no AWS, no model."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from features_backend.steps.home_page_snapshot_steps import FixtureClient, run_snapshot  # noqa: E402
from papyrus_content import reference_creation_paths_test as paths  # noqa: E402
from papyrus_content.reference_medium import classify_address  # noqa: E402
from papyrus_content.reference_medium_backfill import backfill_medium  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite, fixture_settings  # noqa: E402

PLAYLIST = "PLJkNSeYcYBlCaamscxip0l2LGYCZ2TIom"
CORPUS = "knowledge-corpus-example"
STAR_SENTINELS = ("starRating", "starRatedAt", "starRatedBy", "star-rater@example.test")
MEDIUM_FIELDS = {"medium", "mediumFeedKey", "contentNeededKey", "evidenceLevel", "playlistUrl"}


# --- the rule -----------------------------------------------------------------------------------------------------------------------------

@when('the medium of "{address}" is read')
def read_medium(context, address: str) -> None:
    context.found = classify_address(address)


@then('its medium is "{medium}"')
def medium_is(context, medium: str) -> None:
    assert context.found.medium == medium, context.found


@then("it has no medium")
def no_medium(context) -> None:
    assert context.found.medium is None, context.found


@then("its evidence level is empty")
def evidence_empty(context) -> None:
    assert context.found.evidence_level is None, context.found


@then('its evidence level is "{level}"')
def evidence_is(context, level: str) -> None:
    assert context.found.evidence_level == level, context.found


@then('its playlist address is "{address}"')
def playlist_is(context, address: str) -> None:
    assert context.found.playlist_url == address, context.found


# --- the intake paths ---------------------------------------------------------------------------------------------------------------------

@when('a Reference is created through "{path}" at the address "{address}" in the "{key}" corpus')
def create_through(context, path: str, address: str, key: str) -> None:
    context.reference = paths.PATHS[path](key, address)


@then('the Reference\'s medium list is "{key}"')
def medium_list_is(context, key: str) -> None:
    assert context.reference["mediumFeedKey"] == key, context.reference.get("mediumFeedKey")
    assert context.reference["medium"] == "video"


@then("the Reference names no medium field")
def no_medium_field(context) -> None:
    assert not MEDIUM_FIELDS & set(context.reference), {key: context.reference[key] for key in MEDIUM_FIELDS & set(context.reference)}


@then('the Reference\'s evidence level is "{level}"')
def reference_evidence(context, level: str) -> None:
    assert context.reference["evidenceLevel"] == level


@then("the Reference is in no medium list")
def in_no_list(context) -> None:
    assert not context.reference.get("mediumFeedKey"), context.reference.get("mediumFeedKey")


# --- votes and corpora --------------------------------------------------------------------------------------------------------------------

@given('a pending video in the "{key}" corpus')
def pending_video(context, key: str) -> None:
    corpus_id = f"knowledge-corpus-{key}"
    context.client = paths.VoteClient(corpus_id, paths.a_video(corpus_id))
    context.corpus_id = corpus_id
    context.lists = getattr(context, "lists", []) + [context.client.get_record("Reference", "reference-v-v1")["mediumFeedKey"]]
    context.reference = context.client.get_record("Reference", "reference-v-v1")


@when('the Reference is voted "{action}"')
def vote(context, action: str) -> None:
    from papyrus_newsroom.reference_actions import review_reference_curation

    row = context.client.get_record("Reference", "reference-v-v1")

    def graphql(query: str, variables: dict) -> dict:
        if "getReference" in query:
            return {"getReference": {"id": row["id"], "lineageId": row["lineageId"], "corpusId": row["corpusId"], "versionState": "current",
                                     "curationStatus": row["curationStatus"], "newsroomFeedKey": "references", "sourceUri": row["sourceUri"]}}
        context.client.update_record("Reference", variables["input"])
        return {"updateReference": {"id": row["id"]}}

    review_reference_curation(graphql, reference_id=row["id"], action=action, reason_code="out_of_scope" if action == "reject" else "")
    context.reference = context.client.get_record("Reference", row["id"])


@then('the two medium lists are "{first}" and "{second}"')
def two_lists(context, first: str, second: str) -> None:
    assert context.lists == [first, second] and first != second, context.lists


# --- the backfill -------------------------------------------------------------------------------------------------------------------------

class BackfillClient:
    def __init__(self, rows):
        self.rows = {row["id"]: copy.deepcopy(row) for row in rows}
        self.updates: list[dict] = []

    def list_by_index(self, index, key):
        return [copy.deepcopy(row) for row in self.rows.values() if row["curationStatus"] == key.rsplit("#", 1)[1]]

    def update_record(self, model, row):
        self.updates.append(row)
        self.rows[row["id"]].update(row)


@given("a corpus of existing References with a video, a video with a playlist, a playlist and an article, none tagged yet")
def untagged_corpus(context) -> None:
    def row(identifier, address):
        return {"id": identifier, "corpusId": "knowledge-corpus-demo", "versionState": "current", "curationStatus": "accepted", "sourceUri": address,
                "curationStatusUpdatedBy": "someone", "curationReasonCode": "on_topic"}
    context.client = BackfillClient([
        row("video", "https://youtu.be/dQw4w9WgXcQ"),
        row("listed-video", f"https://www.youtube.com/watch?v=JDAPDpbXRXw&list={PLAYLIST}"),
        row("playlist", f"https://www.youtube.com/playlist?list={PLAYLIST}"),
        row("article", "https://example.org/an-article"),
    ])
    context.before = copy.deepcopy(context.client.rows)


@when("the medium backfill runs without the write flag")
def backfill_preview(context) -> None:
    context.lines = []
    context.result = backfill_medium(context.client, corpus_id="knowledge-corpus-demo", progress=context.lines.append)


@when("the medium backfill runs with the write flag")
def backfill_write(context) -> None:
    context.client.updates.clear()
    context.result = backfill_medium(context.client, corpus_id="knowledge-corpus-demo", dry_run=False)


@then("the medium backfill wrote nothing")
def nothing_written(context) -> None:
    assert context.client.updates == [] and context.result["written"] == 0, context.client.updates


@then("it reports {videos:d} videos, {aggregations:d} aggregation and {playlists:d} playlist address to record")
def reported(context, videos: int, aggregations: int, playlists: int) -> None:
    assert (context.result["videos"], context.result["aggregations"], context.result["playlistsRecorded"]) == (videos, aggregations, playlists), context.result
    assert context.lines and all(line.startswith("would write") for line in context.lines)


@then('the video is tagged "video" and listed in "{key}"')
def video_tagged(context, key: str) -> None:
    assert context.client.rows["video"]["medium"] == "video" and context.client.rows["video"]["mediumFeedKey"] == key


@then('both videos wait in the content-needed list "{key}", because nothing is captured yet')
def videos_need_content(context, key: str) -> None:
    for identifier in ("video", "listed-video"):
        assert context.client.rows[identifier]["contentNeededKey"] == key, identifier
    assert "contentNeededKey" not in context.client.rows["playlist"] and "contentNeededKey" not in context.client.rows["article"]


@then('the video with a playlist records "{address}"')
def playlist_recorded(context, address: str) -> None:
    assert context.client.rows["listed-video"]["playlistUrl"] == address


@then('the playlist has the evidence level "{level}" and no medium')
def playlist_level(context, level: str) -> None:
    row = context.client.rows["playlist"]
    assert row["evidenceLevel"] == level and "medium" not in row and "mediumFeedKey" not in row


@then("the article is not written")
def article_untouched(context) -> None:
    assert not any(update["id"] == "article" for update in context.client.updates) and "medium" not in context.client.rows["article"]


@then("no vote or curation field was changed")
def no_vote_changed(context) -> None:
    for identifier, before in context.before.items():
        after = context.client.rows[identifier]
        assert {key: value for key, value in after.items() if key not in MEDIUM_FIELDS} == before, identifier


# --- the public videos page ---------------------------------------------------------------------------------------------------------------

VIDEOS_PAGE = '::band{size="bare"}\n::include{kind="references" select="recent" medium="video" count="12" heading="Videos" empty="No videos yet."}\n'


def entry(title: str, address: str, status: str, accepted_at: str, *, image: str | None = None, medium: str | None = "video", stars: int | None = None, actor: str = "human") -> dict:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    row = {"id": f"record-{slug}", "lineageId": f"lineage-{slug}", "versionNumber": 1, "versionState": "current", "corpusId": CORPUS, "externalItemId": slug,
           "title": title, "authors": [], "sourceUri": address, "mediaType": "text/html", "curationStatus": status, "curationStatusKey": f"{CORPUS}#{status}",
           "curationStatusUpdatedAt": accepted_at, "feedArrivalAt": accepted_at, "createdAt": accepted_at, "importedAt": accepted_at,
           "feedStateKey": f"{CORPUS}#unrated" if status == "pending" else f"{CORPUS}#rated", "curationActorKind": actor,
           "curationStatusUpdatedBy": "editor@example.test", "predictedAcceptProbability": 0.9}
    if medium:
        row["medium"] = medium
    if image and re.search(r"youtube|youtu\.be|vimeo|loom", address):
        digest = hashlib.sha256(slug.encode()).hexdigest()   # the copy the thumbnail worker made; the preview below is the page's own picture on another host
        row["thumbnailPath"] = f"assets/reference-thumbnails/{digest[:16]}-{digest[16:28]}.jpg"
    if stars:
        row.update(starRating=stars, starRatedAt=accepted_at, starRatedBy="star-rater@example.test")
    attachments = [] if not image else [{"id": f"att-{slug}", "role": "preview", "sortKey": "002-preview", "referenceLineageId": row["lineageId"], "sourceUri": image,
                                         "importedAt": accepted_at, "metadata": json.dumps({"imageUrl": image, "description": f"About {title}.", "siteName": "Example"})}]
    return {"row": row, "relations": [], "attachments": attachments}


def corpus_entries(*, stored_medium: bool = True) -> list[dict]:
    medium = "video" if stored_medium else None
    return [
        entry("Newest video", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "accepted", "2026-11-03T09:00:00.000Z", image="https://img.example.org/newest.jpg", medium=medium),
        entry("Older video", "https://vimeo.com/123456789", "accepted", "2026-11-01T09:00:00.000Z", image="https://img.example.org/older.jpg", medium=medium),
        entry("Loom walkthrough", "https://www.loom.com/share/0123456789abcdef0123456789abcdef", "accepted", "2026-10-30T09:00:00.000Z", image="https://img.example.org/loom.jpg", medium=medium),
        entry("Pending video", "https://youtu.be/aaaaaaaaaaa", "pending", "2026-11-03T10:00:00.000Z", medium=medium),
        entry("Rejected video", "https://youtu.be/bbbbbbbbbbb", "rejected", "2026-11-03T11:00:00.000Z", medium=medium),
        entry("A playlist", f"https://www.youtube.com/playlist?list={PLAYLIST}", "accepted", "2026-11-02T09:00:00.000Z", medium=None),
        entry("An article", "https://example.org/an-article", "accepted", "2026-11-02T10:00:00.000Z", medium=None),
    ]


def videos_site(context, page: str, entries: list[dict] | None = None) -> None:
    settings = fixture_settings("flat")
    settings["homePage"] = {"references": {"corpus": CORPUS, "defaultCount": 12}}
    settings["pages"] = [{"id": "videos", "path": "videos", "title": "Videos", "description": "Videos.", "dependsOn": [], "source": "pages/videos.md"}]
    context.client = FixtureClient({"corpusId": CORPUS, "references": entries if entries is not None else corpus_entries(), "sections": []})
    context.build_error = None
    context.reports = []
    context.base_path = ""
    try:
        context.site = ProjectedSite(settings=settings, content=FIXTURES / "flat" / "content", extra_files={"pages/videos.md": page})
    except (AssertionError, ValueError) as error:
        context.build_error = str(error)
        return
    context.add_cleanup(context.site.cleanup)


@given('a site whose videos page places a references include with the medium "video", and a corpus with accepted, pending and rejected videos, a playlist and an article')
def videos_site_given(context) -> None:
    videos_site(context, VIDEOS_PAGE)
    assert context.build_error is None, context.build_error


@given('a site whose videos page places a references include with the medium "video", and a corpus whose accepted videos have no stored medium')
def videos_site_unstored(context) -> None:
    videos_site(context, VIDEOS_PAGE, corpus_entries(stored_medium=False))
    assert context.build_error is None, context.build_error


@given('a site whose videos page places a references include with the medium "{medium}"')
def videos_site_bad_medium(context, medium: str) -> None:
    videos_site(context, VIDEOS_PAGE.replace('medium="video"', f'medium="{medium}"'))


@given("a site with a home page setting whose pages place no medium include, and a corpus with accepted videos")
def site_without_the_block(context) -> None:
    videos_site(context, '::band{size="bare"}\n::include{kind="references" select="recent" count="12"}\n')
    assert context.build_error is None, context.build_error


@given('an editor rated "{title}" {stars:d} stars')
def rated(context, title: str, stars: int) -> None:
    (row,) = [entry_["row"] for entry_ in context.client.fixture["references"] if entry_["row"]["title"] == title]
    row.update(starRating=stars, starRatedAt="2026-11-03T12:00:00.000Z", starRatedBy="star-rater@example.test")


GRID_CARD = re.compile(r'<li>(<article class="home-page-tile".*?</article>)</li>', re.S)
TITLE = re.compile(r'class="home-page-title">(?:<a [^>]*>)?([^<]*)')


def video_cards(context) -> list[str]:
    page = context.site.text("videos/index.html")
    section = re.search(r'<section class="home-page-references"[^>]*data-medium="video".*?</section>', page, re.S)
    assert section, "the page has no videos block"
    return GRID_CARD.findall(section.group(0))


@then("the videos page lists {titles} in that order")
def page_lists(context, titles: str) -> None:
    wanted = re.findall(r'"([^"]*)"', titles)
    found = [TITLE.search(card).group(1) for card in video_cards(context)]
    assert found == wanted, found


@then('the videos page does not list {titles}')
def page_omits(context, titles: str) -> None:
    text = context.site.text("videos/index.html")
    for title in re.findall(r'"([^"]*)"', titles):
        assert f">{title}<" not in text, title


@then('no video card repeats a "Video" label, because every card in the block is a video')
def cards_without_label(context) -> None:
    cards = video_cards(context)
    assert cards
    for card in cards:
        assert 'data-kind="medium"' not in card and ">Video<" not in card, card


MIXED_PAGE = '::band{size="bare"}\n::include{kind="references" select="recent" count="12" heading="Everything"}\n'


@given("a site whose home page places one block of every accepted Reference, and a corpus with an editor-accepted video, a Cyclotron-accepted video and an editor-accepted article")
def mixed_site(context) -> None:
    entries = [
        entry("Newest video", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "accepted", "2026-11-03T09:00:00.000Z", image="https://img.example.org/newest.jpg"),
        entry("Auto video", "https://vimeo.com/123456789", "accepted", "2026-11-02T09:00:00.000Z", image="https://img.example.org/older.jpg", actor="cyclotron"),
        entry("An article", "https://example.org/an-article", "accepted", "2026-11-01T09:00:00.000Z", medium=None),
    ]
    videos_site(context, MIXED_PAGE, entries)
    assert context.build_error is None, context.build_error


def mixed_card(context, title: str) -> str:
    page = context.site.text("videos/index.html")
    for card in GRID_CARD.findall(page):
        if TITLE.search(card).group(1) == title:
            return card
    raise AssertionError(f"no card titled {title!r}")


VIDEO_LABEL = re.compile(r'data-kind="medium"><svg class="home-page-icon" data-icon="video".*?</svg><span>Video</span>', re.S)


@then('the card for "{title}" says "Video" next to a "video" icon and shows no confidence')
def card_video_no_confidence(context, title: str) -> None:
    card = mixed_card(context, title)
    assert VIDEO_LABEL.search(card) and "home-page-confidence" not in card, card


@then('the card for "{title}" says "Video" next to a "video" icon and shows a confidence')
def card_video_confidence(context, title: str) -> None:
    card = mixed_card(context, title)
    assert VIDEO_LABEL.search(card) and "home-page-confidence" in card and "Accepted automatically" in card, card


@then('the card for "{title}" has no Video label and shows no confidence')
def card_plain(context, title: str) -> None:
    card = mixed_card(context, title)
    assert 'data-kind="medium"' not in card and "home-page-confidence" not in card, card


@then("every video card shows the video's own thumbnail from the site's storage, loads no picture from another host, and links out to its source")
def cards_image_and_link(context) -> None:
    for card in video_cards(context):
        assert re.search(r'<img class="home-page-image" src="/assets/reference-thumbnails/[0-9a-f]{16}-[0-9a-f]{12}\.jpg"', card), card
        assert "img.example.org" not in card, card
        assert re.search(r'<a href="https://(?:www\.youtube\.com/watch\?v=|vimeo\.com/|www\.loom\.com/share/)[^"]+" rel="noopener">', card), card


@then("the videos page embeds nothing and loads no third-party script")
def embeds_nothing(context) -> None:
    page = context.site.text("videos/index.html")
    main = re.search(r"<main.*?</main>", page, re.S).group(0)
    assert "<iframe" not in main and "<video" not in main and "<embed" not in main and "<script" not in main
    scripts = re.findall(r'<script[^>]*src="([^"]+)"', page)
    assert all(not re.match(r"https?://", src) or "example.org" in src for src in scripts), scripts
    assert "youtube.com/embed" not in page


@then("no file the site wrote mentions a star field or who rated")
def no_star_leak(context) -> None:
    leaked = [(name, sentinel) for name, body in context.site.tree.items() for sentinel in STAR_SENTINELS if sentinel.encode() in body]
    assert not leaked, leaked


@then("no page has a videos block")
def no_block(context) -> None:
    assert 'data-medium="video"' not in context.site.text("videos/index.html")


@then('the videos build failed saying "{first}" and "{second}"')
def build_failed(context, first: str, second: str) -> None:
    assert context.build_error and first in context.build_error and second in context.build_error, context.build_error
