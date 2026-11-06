"""A video Reference's own thumbnail: the address, the checks, the worker, the record and the published image. No network, no AWS, no real platform."""
from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from papyrus_content import reference_thumbnails as thumbnails
from papyrus_content import references_thumbnails as worker
from papyrus_content.home_page.export import public_reference
from papyrus_content.home_page.settings import HomePageSettings, home_page_settings_from_mapping
from papyrus_content.projection.standard import home_page_blocks
from papyrus_content.projection.standard.page_ledger import PageLedger
from papyrus_content.reference_curation_store import CurationError, correct_reference_capture
from papyrus_content.reference_thumbnails import NoThumbnail, Response, Unreachable

CORPUS = "knowledge-corpus-demo"
WATCH = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture(autouse=True)
def _undo_the_signed_in_lane_switch(monkeypatch):
    """The worker command selects the signed-in lane in the environment; give it back after each test."""
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")


def picture(width: int, height: int, kind: str = "JPEG", colour=(40, 90, 160)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, kind)
    return buffer.getvalue()


def answers(table: dict[str, Response | Exception]):
    asked: list[str] = []

    def http(address: str) -> Response:
        asked.append(address)
        found = table[address]
        if isinstance(found, Exception):
            raise found
        return found
    http.asked = asked
    return http


def ok(body: bytes, kind="image/jpeg") -> Response:
    return Response(200, kind, body)


# --- the address -----------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("address", [WATCH, "https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/shorts/dQw4w9WgXcQ"])
def test_a_youtube_address_is_built_from_the_video_id_with_no_request(address):
    http = answers({})
    assert thumbnails.thumbnail_address(address, http) == ("youtube", "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg")
    assert http.asked == []


def test_an_oembed_platform_is_asked_once_for_its_thumbnail_url():
    ask = "https://vimeo.com/api/oembed.json?url=https%3A%2F%2Fvimeo.com%2F76979871"
    http = answers({ask: ok(json.dumps({"thumbnail_url": "https://i.vimeocdn.com/video/1_295x166"}).encode(), "application/json")})
    assert thumbnails.thumbnail_address("https://vimeo.com/76979871", http) == ("vimeo", "https://i.vimeocdn.com/video/1_295x166")
    assert http.asked == [ask]


def test_twitch_has_no_oembed_endpoint_so_it_has_no_thumbnail():
    with pytest.raises(NoThumbnail):
        thumbnails.thumbnail_address("https://www.twitch.tv/videos/123456", answers({}))


def test_an_address_that_is_not_a_video_has_no_thumbnail():
    with pytest.raises(NoThumbnail):
        thumbnails.thumbnail_address("https://example.org/article", answers({}))


@pytest.mark.parametrize("status,error", [(404, NoThumbnail), (403, NoThumbnail), (500, Unreachable), (429, Unreachable)])
def test_an_oembed_refusal_is_settled_only_when_the_platform_says_the_video_is_missing_or_private(status, error):
    http = answers({"https://vimeo.com/api/oembed.json?url=https%3A%2F%2Fvimeo.com%2F1": Response(status, "", b"")})
    with pytest.raises(error):
        thumbnails.thumbnail_address("https://vimeo.com/1", http)


@pytest.mark.parametrize("named", ["http://i.vimeocdn.com/a.jpg", "https://localhost/a.jpg", "https://127.0.0.1/a.jpg", "https://printer.local/a.jpg", "file:///etc/passwd"])
def test_an_oembed_answer_that_names_a_private_or_insecure_address_is_not_followed(named):
    http = answers({"https://vimeo.com/api/oembed.json?url=https%3A%2F%2Fvimeo.com%2F1": ok(json.dumps({"thumbnail_url": named}).encode())})
    with pytest.raises(NoThumbnail):
        thumbnails.thumbnail_address("https://vimeo.com/1", http)


# --- the picture -----------------------------------------------------------------------------------------------------------------------------


def test_a_real_youtube_thumbnail_is_taken_and_described():
    http = answers({"https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg": ok(picture(480, 360))})
    found = thumbnails.fetch_thumbnail(WATCH, http)
    assert (found.platform, found.width, found.height, found.extension, found.media_type) == ("youtube", 480, 360, "jpg", "image/jpeg")
    assert len(found.sha256) == 64


def test_youtubes_grey_stand_in_for_a_missing_video_is_not_a_thumbnail():
    """A missing video answers 404 with a grey 120 x 90 picture; even a 200 with that picture is refused."""
    http = answers({"https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg": Response(404, "image/jpeg", picture(120, 90))})
    with pytest.raises(NoThumbnail):
        thumbnails.fetch_thumbnail(WATCH, http)
    narrow = answers({"https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg": ok(picture(120, 90))})
    with pytest.raises(NoThumbnail, match="120 px wide"):
        thumbnails.fetch_thumbnail(WATCH, narrow)


def test_a_refusal_of_this_connection_is_not_recorded_as_no_thumbnail():
    for status in (403, 429, 503):
        http = answers({"https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg": Response(status, "text/html", b"")})
        with pytest.raises(Unreachable):
            thumbnails.fetch_thumbnail(WATCH, http)
    broken = answers({"https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg": Unreachable("timed out")})
    with pytest.raises(Unreachable):
        thumbnails.fetch_thumbnail(WATCH, broken)


@pytest.mark.parametrize("body", [b"", b"<html>consent</html>", b"GIF89a" + b"\x00" * 20])
def test_something_that_is_not_a_usable_picture_is_refused(body):
    http = answers({"https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg": ok(body)})
    with pytest.raises(NoThumbnail):
        thumbnails.fetch_thumbnail(WATCH, http)


def test_a_small_oembed_thumbnail_is_enough_for_a_platform_that_only_gives_small_ones():
    assert thumbnails.read_picture(picture(295, 166), "vimeo", "https://i.vimeocdn.com/x").width == 295


def test_the_copy_is_named_for_the_reference_and_the_picture_so_a_new_picture_is_a_new_address():
    video = {"id": "reference-a-v1", "lineageId": "reference-a"}
    first = thumbnails.read_picture(picture(480, 360), "youtube", "u")
    second = thumbnails.read_picture(picture(480, 360, colour=(1, 2, 3)), "youtube", "u")
    one, two = thumbnails.source_path(video, first), thumbnails.source_path(video, second)
    assert one != two and one == thumbnails.source_path({"id": "reference-a-v2", "lineageId": "reference-a"}, first)
    assert thumbnails.SOURCE_PATH.match(one) and thumbnails.media_key(one) == "media/" + one


# --- recording -------------------------------------------------------------------------------------------------------------------------------


class Site:
    """Reference rows, preview attachments and the capture action, in memory."""

    def __init__(self, rows, attachments=None, refuse=None):
        self.rows = {row["id"]: row for row in rows}
        self.attachments = attachments or {}
        self.updates: list[dict] = []
        self.actions: list[dict] = []
        self.refuse = refuse or {}
        self.asked: list[str] = []
        self.listings = 0

    def get_record(self, model, record_id):
        return (self.rows if model == "Reference" else self.attachments).get(record_id)

    def update_record(self, model, payload):
        assert model == "Reference"
        self.updates.append(payload)
        self.rows[payload["id"]].update(payload)

    def list_records(self, model):
        return [{"id": CORPUS}]

    def iterate_newest_first(self, index, partition):
        assert index == "referencesByMediumFeedAndArrival"
        self.asked.append(partition)
        rows = [row for row in self.rows.values() if row.get("mediumFeedKey") == partition]
        yield from sorted((dict(row) for row in rows), key=lambda row: row["feedArrivalAt"], reverse=True)

    def graphql(self, query, variables):
        assert "correctReferenceCapture" in query
        payload = json.loads(variables["input"])
        self.actions.append(payload)
        if payload["referenceId"] in self.refuse:
            return {"correctReferenceCapture": json.dumps({"ok": False, "errors": [{"message": self.refuse[payload["referenceId"]]}]})}
        try:
            answer = correct_reference_capture(self, payload, {"username": "editor"})
        except CurationError as error:
            return {"correctReferenceCapture": json.dumps({"ok": False, "errors": [{"message": str(error)}]})}
        return {"correctReferenceCapture": json.dumps(answer)}


def video(identifier: str, arrival: str, status="accepted", **extra) -> dict:
    return {"id": f"reference-{identifier}-v1", "lineageId": f"reference-{identifier}", "title": f"Talk {identifier}", "feedArrivalAt": arrival,
            "sourceUri": f"https://www.youtube.com/watch?v={identifier}", "medium": "video", "mediumFeedKey": f"{CORPUS}#video#{status}", **extra}


def test_a_stored_thumbnail_is_recorded_on_the_video_and_an_unchanged_one_writes_nothing():
    row = video("aaaaaaaaaaa", "2026-01-01")
    site = Site([row])
    found = thumbnails.read_picture(picture(480, 360), "youtube", "u")
    request = thumbnails.stored_request(row, found)
    assert thumbnails.record_thumbnail(site, row, request)["changed"] is True
    assert site.updates == [{"id": row["id"], "thumbnailPath": request["path"], "cardImage": f"/{request['path']}"}], "the card picture is written with the path, in one update"
    assert thumbnails.record_thumbnail(site, row, request)["changed"] is False and len(site.updates) == 1


def test_no_thumbnail_is_recorded_as_none_so_nobody_asks_again():
    row = video("aaaaaaaaaaa", "2026-01-01")
    site = Site([row])
    thumbnails.record_thumbnail(site, row, thumbnails.none_request("YouTube answered 404"))
    assert row["thumbnailPath"] == "none"
    assert thumbnails.public_image(row) is None


@pytest.mark.parametrize("request_body", [
    {"state": "stored", "path": "assets/other/x.jpg", "sha256": "0" * 64},
    {"state": "stored", "path": "assets/reference-thumbnails/../x.jpg", "sha256": "0" * 64},
    {"state": "stored", "path": "assets/reference-thumbnails/" + "a" * 16 + "-" + "b" * 12 + ".jpg", "sha256": "short"},
    {"state": "maybe"},
])
def test_a_thumbnail_request_outside_the_rules_is_refused(request_body):
    row = video("aaaaaaaaaaa", "2026-01-01")
    with pytest.raises(thumbnails.Refused):
        thumbnails.record_thumbnail(Site([row]), row, request_body)


def test_only_a_video_can_hold_a_thumbnail():
    row = {"id": "reference-x-v1", "lineageId": "reference-x", "sourceUri": "https://example.org/article"}
    with pytest.raises(thumbnails.Refused, match="video"):
        thumbnails.record_thumbnail(Site([row]), row, thumbnails.none_request("x"))


def test_an_image_an_editor_set_is_never_replaced():
    from papyrus_content.reference_images import preview_attachment_id

    row = video("aaaaaaaaaaa", "2026-01-01")
    site = Site([row], {preview_attachment_id(row): {"metadata": json.dumps({"via": "editor"})}})
    with pytest.raises(thumbnails.Refused, match="editor"):
        thumbnails.record_thumbnail(site, row, thumbnails.none_request("x"))
    assert site.updates == []


def test_the_capture_action_takes_a_thumbnail_alone():
    row = video("aaaaaaaaaaa", "2026-01-01")
    site = Site([row])
    answer = correct_reference_capture(site, {"referenceId": row["id"], "thumbnail": thumbnails.none_request("x")}, {"username": "editor"})
    assert answer["ok"] is True and answer["thumbnailPath"] == "none"
    with pytest.raises(CurationError, match="alone"):
        correct_reference_capture(site, {"referenceId": row["id"], "thumbnail": thumbnails.none_request("x"), "note": "n"}, {"username": "editor"})
    with pytest.raises(CurationError, match="video"):
        article = {"id": "reference-y-v1", "sourceUri": "https://example.org/a"}
        correct_reference_capture(Site([article]), {"referenceId": article["id"], "thumbnail": thumbnails.none_request("x")}, {"username": "editor"})


# --- the worker ------------------------------------------------------------------------------------------------------------------------------


def run(site, *flags, fetch=None, stored=None):
    out = io.StringIO()
    code = worker.command(["--corpus-key", "demo", *flags], client=site, out=out, fetch=fetch, upload=lambda path, found: (stored if stored is not None else []).append((path, found.sha256)),
                          sleep=lambda seconds: None)
    return code, out.getvalue()


def fetches(text):
    return [line for line in text.splitlines() if line.split("\t")[2:3] == ["would_fetch"]]


def good(address):
    return thumbnails.read_picture(picture(480, 360), "youtube", "https://img.youtube.com/vi/x/hqdefault.jpg")


def test_the_worker_previews_by_default_and_touches_nothing():
    site = Site([video("aaaaaaaaaaa", "2026-01-02"), video("bbbbbbbbbbb", "2026-01-01")])
    calls: list[str] = []
    code, text = run(site, fetch=lambda address: calls.append(address))
    assert code == 0 and calls == [] and site.actions == [] and site.updates == []
    assert len(fetches(text)) == 2 and "preview" in text and "--write" in text


def test_the_worker_reads_accepted_and_pending_videos_newest_first_and_never_scans():
    site = Site([video("aaaaaaaaaaa", "2026-01-01"), video("bbbbbbbbbbb", "2026-01-03", "pending"), video("ccccccccccc", "2026-01-02", "rejected")])
    code, text = run(site)
    assert sorted(site.asked) == [f"{CORPUS}#video#accepted", f"{CORPUS}#video#pending"]
    assert [line.split("\t")[3] for line in fetches(text)] == ["reference-bbbbbbbbbbb-v1", "reference-aaaaaaaaaaa-v1"]


def test_with_write_each_video_is_fetched_stored_and_recorded_once():
    site = Site([video("aaaaaaaaaaa", "2026-01-02"), video("bbbbbbbbbbb", "2026-01-01")])
    stored: list = []
    fetched: list[str] = []

    def fetch(address):
        fetched.append(address)
        return good(address)
    code, text = run(site, "--write", fetch=fetch, stored=stored)
    assert code == 0 and len(fetched) == 2 and len(stored) == 2
    assert all(row["thumbnailPath"].startswith("assets/reference-thumbnails/") for row in site.rows.values())
    assert [action["thumbnail"]["state"] for action in site.actions] == ["stored", "stored"]
    again = run(site, "--write", fetch=fetch, stored=stored)
    assert len(fetched) == 2 and "already_have 2" in again[1]


def test_a_video_the_platform_has_no_thumbnail_for_is_recorded_and_not_asked_again():
    site = Site([video("aaaaaaaaaaa", "2026-01-01")])
    attempts: list[str] = []

    def fetch(address):
        attempts.append(address)
        raise NoThumbnail("YouTube answered 404 for the picture")
    run(site, "--write", fetch=fetch)
    assert site.rows["reference-aaaaaaaaaaa-v1"]["thumbnailPath"] == "none"
    run(site, "--write", fetch=fetch)
    assert len(attempts) == 1


def test_a_video_whose_platform_could_not_be_asked_records_nothing_and_goes_on():
    site = Site([video("aaaaaaaaaaa", "2026-01-03"), video("bbbbbbbbbbb", "2026-01-02")])

    def fetch(address):
        if "aaaaaaaaaaa" in address:
            raise Unreachable("timed out")
        return good(address)
    code, text = run(site, "--write", fetch=fetch)
    assert code == 0 and "failed" in text and "reference-aaaaaaaaaaa-v1" not in {key for key, row in site.rows.items() if row.get("thumbnailPath")}
    assert site.rows["reference-bbbbbbbbbbb-v1"]["thumbnailPath"].endswith(".jpg")


def test_the_worker_stops_when_the_platforms_keep_refusing_this_connection():
    site = Site([video(f"{n:011d}", f"2026-01-{10 - n:02d}") for n in range(6)])
    attempts: list[str] = []

    def fetch(address):
        attempts.append(address)
        raise Unreachable("refused")
    code, text = run(site, "--write", fetch=fetch)
    assert code == worker.EXIT_BLOCKED and len(attempts) == worker.STOP_AFTER_UNREACHABLE and "stopped: blocked" in text
    assert site.updates == [] and site.actions == []


def test_the_limit_is_the_only_cap_and_counts_videos_that_needed_work():
    rows = [video(f"{n:011d}", f"2026-01-{10 - n:02d}") for n in range(4)]
    rows[0]["thumbnailPath"] = "none"
    site = Site(rows)
    code, text = run(site, "--limit", "2")
    assert len(fetches(text)) == 2 and "already_have 1" in text


def test_a_site_that_refuses_one_video_does_not_stop_the_run():
    site = Site([video("aaaaaaaaaaa", "2026-01-02"), video("bbbbbbbbbbb", "2026-01-01")], refuse={"reference-aaaaaaaaaaa-v1": "An editor set this Reference's image"})
    code, text = run(site, "--write", fetch=good)
    assert code == 0 and "An editor set" in text and site.rows["reference-bbbbbbbbbbb-v1"].get("thumbnailPath")


def test_a_storage_fault_stops_the_run_with_a_plain_message(capsys):
    site = Site([video("aaaaaaaaaaa", "2026-01-02")])
    out = io.StringIO()

    def broken(path, found):
        raise PermissionError("Access Denied")
    code = worker.command(["--corpus-key", "demo", "--write"], client=site, out=out, fetch=good, upload=broken, sleep=lambda seconds: None)
    assert code == 2 and "media bucket" in capsys.readouterr().err and site.actions == []


# --- the published image ---------------------------------------------------------------------------------------------------------------------


SETTINGS = home_page_settings_from_mapping({"references": {"corpus": CORPUS}})
PATH = "assets/reference-thumbnails/" + "a" * 16 + "-" + "b" * 12 + ".jpg"
PREVIEW = {"sourceUri": "https://i.ytimg.com/vi/x/maxresdefault.jpg", "metadata": json.dumps({"description": "About feeds", "siteName": "YouTube"})}


def published(row, preview=PREVIEW):
    base = {"lineageId": row["id"], "title": "T", "curationStatus": "accepted", "curationActorKind": "human"}
    return public_reference({**base, **row}, None, preview, {}, SETTINGS)


def test_a_video_card_publishes_the_copy_in_our_storage_and_never_the_platforms_address():
    record = published({"id": "v", "sourceUri": WATCH, "medium": "video", "thumbnailPath": PATH})
    assert record["image"] == "/" + PATH


def test_a_video_with_no_copy_yet_publishes_no_image_even_when_the_page_declared_one():
    for value in (None, "none"):
        assert published({"id": "v", "sourceUri": WATCH, "medium": "video", "thumbnailPath": value})["image"] is None


def test_an_ordinary_page_keeps_its_preview_image_and_an_editors_image_on_a_video_is_kept():
    assert published({"id": "p", "sourceUri": "https://example.org/a"})["image"] == PREVIEW["sourceUri"]
    editors = {"sourceUri": "https://example.org/chosen.jpg", "metadata": json.dumps({"via": "editor"})}
    assert published({"id": "v", "sourceUri": WATCH, "medium": "video", "thumbnailPath": PATH}, editors)["image"] == "https://example.org/chosen.jpg"


def test_a_video_whose_medium_is_only_in_its_address_still_gets_the_copy():
    assert published({"id": "v", "sourceUri": WATCH, "thumbnailPath": PATH})["image"] == "/" + PATH


def render(image, **options):
    snapshot = {"references": [{"key": "k1", "status": "accepted", "title": "Talk", "url": WATCH, "medium": "video", "image": image, "acceptedAt": "2026-01-01T00:00:00Z"}]}
    return home_page_blocks.render({"kind": "references", "select": "recent", "medium": "video"}, snapshot, PageLedger(), HomePageSettings(), **options)


def test_the_card_draws_the_copy_from_the_site_and_moves_it_under_a_base_path():
    assert 'src="/' + PATH + '"' in render("/" + PATH)
    assert 'src="/posts/' + PATH + '"' in render("/" + PATH, asset_href=lambda path: "/posts" + path)
    assert 'src="https://example.org/x.jpg"' in render("https://example.org/x.jpg", asset_href=lambda path: "/posts" + path)


def test_a_video_card_without_an_image_draws_none():
    assert "<img" not in render(None)
