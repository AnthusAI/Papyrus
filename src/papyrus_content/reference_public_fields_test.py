"""The card copies on a Reference row and the one-time backfill (docs/plans/public-blocks-from-indexes.md, PPY-7f1e54). Offline: counting fakes, no network."""
from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from .link_exploration import Exploration, PageMetadata
from .reference_images import attach_preview, enrich_reference_previews, preview_attachment
from .reference_public_fields import backfill_public_fields, card_fields, chosen_preview, planned_public_fields
from .reference_thumbnails import Refused, record_thumbnail

C = "knowledge-corpus-demo"
ARRIVED = "2026-11-02T12:00:00.000Z"
THUMBNAIL = "assets/reference-thumbnails/0123456789abcdef-0123456789ab.jpg"
VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
A_UUID = "-".join(["123e4567", "e89b", "12d3", "a456", "426614174000"])   # built, not written out: a bare identifier in a test file is flagged


def attachment(image: str | None = "https://img.example.org/a.jpg", *, description: Any = "A description.", site: Any = "Example News", via: str | None = None, at: str = "2026-11-02T00:00:00Z",
               title: Any = "The page title") -> dict[str, Any]:
    metadata = {"description": description, "siteName": site, "title": title, **({"via": via} if via else {})}
    return {"role": "preview", "sourceUri": image, "importedAt": at, "metadata": json.dumps(metadata)}


# --- what a card shows -------------------------------------------------------------------------------------------------------------------------


def test_a_card_copies_the_preview_picture_description_and_site_name():
    row = {"id": "r", "sourceUri": "https://example.org/a"}
    assert card_fields(row, attachment()) == {"cardImage": "https://img.example.org/a.jpg", "cardSummary": "A description.", "cardSiteName": "Example News", "cardPageTitle": "The page title"}
    assert card_fields(row, None) == {"cardImage": None, "cardSummary": None, "cardSiteName": None, "cardPageTitle": None}


def test_the_title_the_page_declared_is_carried_so_a_card_can_show_it_when_the_row_is_titled_with_its_address():
    row = {"id": "r", "title": "https://example.org/a", "sourceUri": "https://example.org/a"}
    assert card_fields(row, attachment(title="  A real title  "))["cardPageTitle"] == "A real title"
    assert card_fields(row, attachment(title=None))["cardPageTitle"] is None
    assert card_fields(row, attachment(title="Reach me at editor@example.org"))["cardPageTitle"] == "Reach me at"


def test_the_summary_is_stored_whole_so_a_site_can_change_its_length_without_touching_the_table():
    long = "A sentence. " * 80
    assert card_fields({"id": "r"}, attachment(description=long))["cardSummary"] == long.strip()


def test_nothing_private_reaches_a_card_copy():
    private = {"description": "Write to editor@example.org about " + A_UUID + " and ss1_abcdefghijkl.", "site": "Desk editor@example.org"}
    fields = card_fields({"id": "r"}, attachment(description=private["description"], site=private["site"], image="https://img.example.org/a.jpg?user=editor@example.org"))
    assert fields["cardSummary"] == "Write to about and ."
    for value in fields.values():
        assert value is not None and "@" not in value and "123e4567" not in value and "ss1_" not in value, value
    assert fields["cardImage"] == "https://img.example.org/a.jpg", "a query that carries identity is dropped from the picture address"
    withheld = card_fields({"id": "r"}, attachment(image="https://img.example.org/editor@example.org/a.jpg"))
    assert withheld["cardImage"] is None, "a picture address whose path carries identity is withheld"


def test_a_video_card_shows_our_own_thumbnail_never_the_platforms_picture():
    video = {"id": "r", "sourceUri": VIDEO, "thumbnailPath": THUMBNAIL}
    fields = card_fields(video, attachment(image="https://i.ytimg.com/vi/x/hqdefault.jpg"))
    assert fields["cardImage"] == f"/{THUMBNAIL}"
    assert card_fields({**video, "thumbnailPath": None}, attachment(image="https://i.ytimg.com/vi/x/hqdefault.jpg"))["cardImage"] is None, "no copy yet means no picture"
    assert card_fields({**video, "thumbnailPath": "none"}, attachment())["cardImage"] is None
    assert card_fields(video, None)["cardImage"] == f"/{THUMBNAIL}", "a video with no preview attachment still shows its thumbnail"


def test_a_picture_an_editor_chose_wins_over_the_thumbnail():
    video = {"id": "r", "sourceUri": VIDEO, "thumbnailPath": THUMBNAIL}
    assert card_fields(video, attachment(image="https://img.example.org/chosen.jpg", via="editor"))["cardImage"] == "https://img.example.org/chosen.jpg"


def test_the_preview_a_card_is_drawn_from_is_the_latest_one_that_has_a_picture():
    older, newer, bare = attachment("https://img.example.org/old.jpg", at="2026-11-01T00:00:00Z"), attachment("https://img.example.org/new.jpg", at="2026-11-02T00:00:00Z"), attachment(None, at="2026-11-03T00:00:00Z")
    assert chosen_preview([older, newer, bare, {"role": "curation"}, None])["sourceUri"] == "https://img.example.org/new.jpg"
    assert chosen_preview([bare])["sourceUri"] is None
    assert chosen_preview([{"role": "curation"}]) is None


# --- the writers ------------------------------------------------------------------------------------------------------------------------------


class Writes:
    """A client that records every call a writer makes, by kind."""

    def __init__(self, rows: dict[str, dict[str, Any]] | None = None):
        self.rows = rows or {}
        self.calls: list[tuple[str, str]] = []
        self.attachments: dict[str, dict[str, Any]] = {}

    def get_record(self, model: str, record_id: str):
        self.calls.append(("get", model))
        return copy.deepcopy(self.attachments.get(record_id) if model == "ReferenceAttachment" else self.rows.get(record_id))

    def upsert(self, model: str, row: dict[str, Any]):
        self.calls.append(("upsert", model))
        self.attachments[row["id"]] = copy.deepcopy(row)

    def update_record(self, model: str, row: dict[str, Any]):
        self.calls.append(("update", model))
        self.rows.setdefault(row["id"], {}).update(copy.deepcopy(row))


def an_exploration(image: str | None = "https://img.example.org/a.jpg") -> Exploration:
    return Exploration(True, "https://example.org/a", via="direct", metadata=PageMetadata(image_url=image, description="A description.", site_name="Example News", title="T"))


def test_capturing_a_preview_writes_the_card_copies_in_one_more_mutation_and_only_once():
    reference = {"id": "r-v1", "lineageId": "r", "title": "A title", "sourceUri": "https://example.org/a"}
    client = Writes({"r-v1": dict(reference)})
    assert attach_preview(client, reference, exploration=an_exploration(), log=lambda line: None) == "written"
    assert client.calls == [("get", "ReferenceAttachment"), ("upsert", "ReferenceAttachment"), ("update", "Reference")], "one read, the attachment, and one mutation for the card"
    assert {key: client.rows["r-v1"].get(key) for key in ("cardImage", "cardSummary", "cardSiteName", "cardPageTitle")} == {
        "cardImage": "https://img.example.org/a.jpg", "cardSummary": "A description.", "cardSiteName": "Example News", "cardPageTitle": "T"}
    assert attach_preview(client, reference, exploration=an_exploration(), log=lambda line: None) == "exists"
    assert [call for call in client.calls if call == ("update", "Reference")] == [("update", "Reference")], "a repeat writes nothing"


def test_a_row_that_already_holds_the_same_card_copies_costs_no_mutation():
    reference = {"id": "r-v1", "lineageId": "r", "title": "A title", "sourceUri": "https://example.org/a", "cardImage": "https://img.example.org/a.jpg", "cardSummary": "A description.", "cardSiteName": "Example News", "cardPageTitle": "T"}
    client = Writes({"r-v1": dict(reference)})
    attach_preview(client, reference, exploration=an_exploration(), log=lambda line: None)
    assert ("update", "Reference") not in client.calls


def test_a_card_copy_that_fails_does_not_fail_the_preview():
    reference = {"id": "r-v1", "lineageId": "r", "title": "A title", "sourceUri": "https://example.org/a"}
    client = Writes({"r-v1": dict(reference)})
    logged: list[str] = []

    def refuse(model: str, row: dict[str, Any]):
        raise RuntimeError("Not Authorized")

    client.update_record = refuse   # type: ignore[method-assign]
    assert attach_preview(client, reference, exploration=an_exploration(), log=logged.append) == "written"
    assert any("referenceCardFields" in line for line in logged) and ("upsert", "ReferenceAttachment") in client.calls


def test_a_video_captured_before_its_thumbnail_has_no_card_picture_until_the_thumbnail_is_recorded():
    reference = {"id": "v-v1", "lineageId": "v", "sourceUri": VIDEO}
    client = Writes({"v-v1": dict(reference)})
    attach_preview(client, reference, exploration=an_exploration("https://i.ytimg.com/vi/x/hqdefault.jpg"), log=lambda line: None)
    assert client.rows["v-v1"].get("cardImage") is None, "the platform's own picture is never the card's"
    assert client.rows["v-v1"]["cardSummary"] == "A description."


def test_recording_a_thumbnail_puts_it_in_the_card_picture_with_the_path_in_one_update():
    reference = {"id": "v-v1", "lineageId": "v", "sourceUri": VIDEO}
    client = Writes({"v-v1": dict(reference)})
    result = record_thumbnail(client, reference, {"state": "stored", "path": THUMBNAIL, "sha256": "a" * 64})
    assert result["changed"] is True
    assert client.calls == [("get", "ReferenceAttachment"), ("update", "Reference")]
    assert client.rows["v-v1"]["thumbnailPath"] == THUMBNAIL and client.rows["v-v1"]["cardImage"] == f"/{THUMBNAIL}"
    again = record_thumbnail(client, reference, {"state": "stored", "path": THUMBNAIL, "sha256": "a" * 64})
    assert again["changed"] is False and client.calls.count(("update", "Reference")) == 1
    none = record_thumbnail(client, reference, {"state": "none", "reason": "no picture"})
    assert none["changed"] is True and client.rows["v-v1"]["thumbnailPath"] == "none" and client.rows["v-v1"]["cardImage"] is None


def test_a_row_with_a_thumbnail_but_no_card_picture_is_repaired_by_the_next_record():
    reference = {"id": "v-v1", "lineageId": "v", "sourceUri": VIDEO, "thumbnailPath": THUMBNAIL}
    client = Writes({"v-v1": dict(reference)})
    assert record_thumbnail(client, reference, {"state": "stored", "path": THUMBNAIL, "sha256": "a" * 64})["changed"] is True
    assert client.rows["v-v1"]["cardImage"] == f"/{THUMBNAIL}" and client.rows["v-v1"]["thumbnailPath"] == THUMBNAIL


def test_a_thumbnail_is_not_recorded_over_a_picture_an_editor_chose():
    reference = {"id": "v-v1", "lineageId": "v", "sourceUri": VIDEO}
    client = Writes({"v-v1": dict(reference)})
    exploration = an_exploration("https://img.example.org/chosen.jpg")
    attach_preview(client, reference, exploration=exploration, log=lambda line: None)
    from .reference_images import preview_attachment_id
    client.attachments[preview_attachment_id(reference)]["metadata"] = json.dumps({"via": "editor"})
    with pytest.raises(Refused):
        record_thumbnail(client, reference, {"state": "stored", "path": THUMBNAIL, "sha256": "a" * 64})


def test_the_enrich_images_command_writes_the_card_copies_with_each_preview(monkeypatch):
    class Listing(Writes):
        def list_records(self, model: str):
            return [{"id": "r-v1", "lineageId": "r", "versionState": "current", "sourceUri": "https://example.org/a"}] if model == "Reference" else []

    client = Listing({"r-v1": {"id": "r-v1", "lineageId": "r", "sourceUri": "https://example.org/a"}})
    counts = enrich_reference_previews(client, explorer=lambda *args, **kwargs: an_exploration())
    assert counts["written"] == 1 and client.rows["r-v1"]["cardSiteName"] == "Example News"
    dry = Listing({"r-v1": {"id": "r-v1", "lineageId": "r", "sourceUri": "https://example.org/a"}})
    enrich_reference_previews(dry, dry_run=True, explorer=lambda *args, **kwargs: an_exploration())
    assert not dry.calls


# --- the backfill ------------------------------------------------------------------------------------------------------------------------------


class Backend:
    """A corpus as the backfill reads it, counting every request by kind. Pending rows are served highest prediction first, as the index serves them."""

    def __init__(self, accepted: list[dict[str, Any]], pending: list[dict[str, Any]], previews: dict[str, list[dict[str, Any]]]):
        self.rows = {row["id"]: copy.deepcopy(row) for row in [*accepted, *pending]}
        self.accepted = [row["id"] for row in accepted]
        self.pending = sorted((row["id"] for row in pending), key=lambda identifier: str(self.rows[identifier].get("predictionSortKey") or ""), reverse=True)
        self.previews = previews
        self.reads = {"listAccepted": 0, "pendingRowsPulled": 0, "attachments": 0}
        self.writes: list[tuple[str, dict[str, Any]]] = []

    def list_by_index(self, index_name: str, key: str):
        assert index_name == "referencesByCurationStatusKey" and key == f"{C}#accepted", (index_name, key)
        self.reads["listAccepted"] += 1
        return [copy.deepcopy(self.rows[identifier]) for identifier in self.accepted]

    def iterate_newest_first(self, index_name: str, key: str):
        assert index_name == "referencesByFeedStateAndPrediction" and key == f"{C}#unrated", (index_name, key)
        for identifier in self.pending:
            self.reads["pendingRowsPulled"] += 1
            yield copy.deepcopy(self.rows[identifier])

    def list_reference_attachments_by_lineage(self, lineage: str):
        self.reads["attachments"] += 1
        return self.previews.get(lineage, [])

    def update_record(self, model: str, row: dict[str, Any]):
        assert model == "Reference"
        self.writes.append((row["id"], copy.deepcopy(row)))
        self.rows[row["id"]].update(copy.deepcopy(row))


def reference(identifier: str, status: str, probability: float | None, **extra: Any) -> dict[str, Any]:
    row = {"id": identifier, "lineageId": f"{identifier}-lineage", "corpusId": C, "versionState": "current", "curationStatus": status, "sourceUri": f"https://example.org/{identifier}",
           "createdAt": "2026-11-02T12:00:00Z", "feedArrivalAt": ARRIVED}
    if probability is not None:
        row["predictedAcceptProbability"] = probability
    row["predictionSortKey"] = f"{0.5 if probability is None else probability:.6f}#{ARRIVED}#{identifier}"
    return {**row, **extra}


def a_corpus() -> Backend:   # each preview also declares a title: "Title of <id>"
    accepted = [reference("a1", "accepted", 0.9), reference("a2", "accepted", None), reference("a3", "accepted", 0.2)]
    pending = [reference("p1", "pending", 0.95), reference("p2", "pending", 0.7), reference("p3", "pending", None), reference("p4", "pending", 0.3),
               reference("p5", "pending", 0.2), reference("p6", "pending", 0.1)]
    previews = {f"{identifier}-lineage": [attachment(f"https://img.example.org/{identifier}.jpg", description=f"About {identifier}.", site="Example", title=f"Title of {identifier}")]
                for identifier in ("a1", "a2", "a3", "p1", "p2", "p3", "p4")}
    return Backend(accepted, pending, previews)


def test_the_backfill_previews_by_default_and_reads_only_what_can_be_public():
    backend = a_corpus()
    counts = backfill_public_fields(backend, corpus_id=C)
    assert backend.writes == [], "a preview writes nothing"
    assert counts["dryRun"] is True and counts["public"] == 5 and counts["accepted"] == 3 and counts["recommended"] == 2 and counts["changed"] == 5 and counts["written"] == 0
    # one list of the accepted rows; the pending partition read down to the first row under one half (p1, p2, the unpredicted p3, then p4 ends the read)
    assert backend.reads == {"listAccepted": 1, "pendingRowsPulled": 4, "attachments": 5}, "preview attachments are read for the five public rows only"
    assert counts["keysSet"] == 5 and counts["cardImagesSet"] == 5 and counts["cardSummariesSet"] == 5 and counts["cardSiteNamesSet"] == 5 and counts["cardPageTitlesSet"] == 5


def test_the_backfill_writes_the_keys_and_card_copies_and_a_second_run_writes_nothing():
    backend = a_corpus()
    counts = backfill_public_fields(backend, corpus_id=C, dry_run=False)
    assert counts["written"] == 5 and len(backend.writes) == 5
    written = {identifier: row for identifier, row in backend.writes}
    assert written["a1"] == {"id": "a1", "publicFeedKey": f"{C}#accepted", "publicOrderKey": f"p0.900000#{ARRIVED}#a1", "cardImage": "https://img.example.org/a1.jpg",
                             "cardSummary": "About a1.", "cardSiteName": "Example", "cardPageTitle": "Title of a1"}
    assert written["a2"]["publicOrderKey"] == f"n#{ARRIVED}#a2", "an accepted row nobody scored sorts last"
    assert written["p1"]["publicFeedKey"] == f"{C}#recommended#2026-11-02" and written["p2"]["publicOrderKey"] == f"p0.700000#{ARRIVED}#p2"
    assert set(written) == {"a1", "a2", "a3", "p1", "p2"}, "an unpredicted row and a row under one half are never touched"
    assert not any("curation" in key for _, row in backend.writes for key in row), "no vote is changed"
    again = backfill_public_fields(backend, corpus_id=C, dry_run=False)
    assert again["written"] == 0 and again["changed"] == 0 and again["alreadyRight"] == 6 and len(backend.writes) == 5   # the sixth is the unpredicted row, read and left alone


def test_the_backfill_clears_keys_a_row_holds_but_no_longer_qualifies_for():
    backend = a_corpus()
    backend.rows["p2"].update(predictedAcceptProbability=0.3, publicFeedKey=f"{C}#recommended#2026-11-02", publicOrderKey="stale")
    backend.rows["p2"]["predictionSortKey"] = f"0.700000#{ARRIVED}#p2"   # still read: the index sorts by the key it was written with
    counts = backfill_public_fields(backend, corpus_id=C, dry_run=False)
    cleared = dict(backend.writes)["p2"]
    assert cleared["publicFeedKey"] is None and cleared["publicOrderKey"] is None and "cardImage" not in cleared
    assert counts["keysCleared"] == 1


def test_a_video_without_a_thumbnail_is_reported_and_has_no_card_picture():
    video = reference("v1", "accepted", 0.8, sourceUri=VIDEO)
    backend = Backend([video], [], {"v1-lineage": [attachment("https://i.ytimg.com/vi/x/hqdefault.jpg")]})
    counts = backfill_public_fields(backend, corpus_id=C, dry_run=False)
    assert counts["videosWithoutImage"] == 1
    assert dict(backend.writes)["v1"].get("cardImage") is None
    withcopy = Backend([{**video, "thumbnailPath": THUMBNAIL}], [], {"v1-lineage": [attachment("https://i.ytimg.com/vi/x/hqdefault.jpg")]})
    backfill_public_fields(withcopy, corpus_id=C, dry_run=False)
    assert dict(withcopy.writes)["v1"]["cardImage"] == f"/{THUMBNAIL}", "video thumbnails end up in cardImage"


def test_a_superseded_or_rejected_row_is_not_touched_and_the_longest_summary_is_reported():
    accepted = [reference("a1", "accepted", 0.9), reference("a9", "accepted", 0.9, versionState="superseded")]
    backend = Backend(accepted, [], {"a1-lineage": [attachment(description="x" * 321)]})
    counts = backfill_public_fields(backend, corpus_id=C)
    assert counts["scanned"] == 1 and counts["longestSummary"] == 321


def test_planned_fields_read_the_attachments_only_for_a_row_that_can_be_public():
    reads: list[int] = []

    def attachments():
        reads.append(1)
        return [attachment()]

    assert planned_public_fields(reference("x", "pending", 0.2), attachments) == {}
    assert planned_public_fields(reference("x", "rejected", 0.9), attachments) == {}
    assert reads == []
    assert planned_public_fields(reference("x", "pending", 0.9), attachments)["publicFeedKey"] == f"{C}#recommended#2026-11-02"
    assert reads == [1]


def test_the_preview_attachment_row_carries_what_the_card_copy_reads():
    row = preview_attachment({"id": "r-v1", "lineageId": "r", "sourceUri": "https://example.org/a"}, an_exploration(), __import__("datetime").datetime(2026, 11, 2, tzinfo=__import__("datetime").timezone.utc))
    assert card_fields({"id": "r-v1", "sourceUri": "https://example.org/a"}, row)["cardSummary"] == "A description."
