"""Steps for features_backend/reference-public-fields.feature. Everything is in memory: no network, no AWS, no model."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src",):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.link_exploration import Exploration, PageMetadata  # noqa: E402
from papyrus_content.monitoring_router import record_original_prediction  # noqa: E402
from papyrus_content.reference_feed_keys import PUBLIC_KEY_FIELDS, feed_keys, public_feed_keys  # noqa: E402
from papyrus_content.reference_images import attach_preview  # noqa: E402
from papyrus_content.reference_public_fields import backfill_public_fields  # noqa: E402
from papyrus_content.reference_thumbnails import record_thumbnail  # noqa: E402

CORPUS = "knowledge-corpus-example-site"
VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
PAGE = "https://example.org/a-page"
A_UUID = "-".join(["123e4567", "e89b", "12d3", "a456", "426614174000"])   # built, not written out: a bare identifier in a test file is flagged
THUMBNAIL = "assets/reference-thumbnails/0123456789abcdef-0123456789ab.jpg"
CARD_FIELDS = ("cardImage", "cardSummary", "cardSiteName", "cardPageTitle")


class Backend:
    """A publication's Reference rows and attachments, counting what is read and recording what is written."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.attachments: dict[str, dict] = {}
        self.previews: dict[str, list[dict]] = {}
        self.written: list[dict] = []
        self.pulled = 0

    def get_record(self, model, record_id):
        source = self.attachments if model == "ReferenceAttachment" else self.rows
        return copy.deepcopy(source.get(record_id))

    def upsert(self, model, payload):
        assert model == "ReferenceAttachment", model
        self.attachments[payload["id"]] = copy.deepcopy(payload)
        return "created"

    def update_record(self, model, payload):
        assert model == "Reference", model
        self.written.append(copy.deepcopy(payload))
        self.rows[payload["id"]].update(copy.deepcopy(payload))

    def list_by_index(self, index, key):
        assert index == "referencesByCurationStatusKey" and key == f"{CORPUS}#accepted", (index, key)
        return [copy.deepcopy(row) for row in self.rows.values() if row["curationStatus"] == "accepted"]

    def iterate_newest_first(self, index, key):
        assert index == "referencesByFeedStateAndPrediction" and key == f"{CORPUS}#unrated", (index, key)
        pending = [row for row in self.rows.values() if row["curationStatus"] == "pending"]
        for row in sorted(pending, key=lambda item: item["predictionSortKey"], reverse=True):
            self.pulled += 1
            yield copy.deepcopy(row)

    def list_reference_attachments_by_lineage(self, lineage):
        return self.previews.get(lineage, [])


def world(context):
    if getattr(context, "pub", None) is None:
        context.pub = SimpleNamespace(backend=Backend(), refs={}, row=None, update=None, backfill=None, writes_before=0)
    return context.pub


def a_row(identifier, status, arrival, probability=None, **extra):
    row = {"id": identifier, "lineageId": f"{identifier}-lineage", "corpusId": CORPUS, "versionState": "current", "curationStatus": status,
           "sourceUri": PAGE, "createdAt": arrival, **extra}
    if probability is not None:
        row["predictedAcceptProbability"] = probability
    row.update(feed_keys(row))   # the keys a writer gives a row when it creates it
    return row


def keep(context, row):
    state = world(context)
    state.row = row
    state.backend.rows[row["id"]] = copy.deepcopy(row)
    state.backend.previews.setdefault(row["lineageId"], [])
    return row


@given('two accepted References that arrived at "{arrival}", one scored {probability:g} and one nobody scored')
def two_accepted(context, arrival, probability):
    state = world(context)
    state.refs["scored"] = keep(context, a_row("scored-v1", "accepted", arrival, probability))
    state.refs["unscored"] = keep(context, a_row("unscored-v1", "accepted", arrival))


@given('a Reference that is "{status}", arrived at "{arrival}" and has a stored prediction of {probability:g}')
def with_prediction(context, status, arrival, probability):
    keep(context, a_row("reference-v1", status, arrival, probability))


@given('a Reference that is "{status}", arrived at "{arrival}" and has no prediction')
def without_prediction(context, status, arrival):
    keep(context, a_row("reference-v1", status, arrival))


@given('a video Reference that is "{status}", arrived at "{arrival}" and has a stored prediction of {probability:g}')
def a_video(context, status, arrival, probability):
    keep(context, a_row("video-v1", status, arrival, probability, sourceUri=VIDEO))


def stored_keys(row):
    return row.get("publicFeedKey"), row.get("publicOrderKey")


@then('the scored one is in the accepted public partition sorted by "{prefix}"')
def scored_is_accepted(context, prefix):
    feed, order = stored_keys(world(context).refs["scored"])
    assert feed == f"{CORPUS}#accepted" and order.startswith(prefix), (feed, order)


@then('the unscored one is in the accepted public partition sorted by "{prefix}"')
def unscored_is_accepted(context, prefix):
    feed, order = stored_keys(world(context).refs["unscored"])
    assert feed == f"{CORPUS}#accepted" and order.startswith(prefix), (feed, order)


@then("the scored one sorts above the unscored one")
def scored_above_unscored(context):
    refs = world(context).refs
    assert refs["scored"]["publicOrderKey"] > refs["unscored"]["publicOrderKey"], (refs["scored"]["publicOrderKey"], refs["unscored"]["publicOrderKey"])


@then('it is in the recommended public partition of "{day}"')
def recommended_on(context, day):
    feed, order = stored_keys(world(context).row)
    assert feed == f"{CORPUS}#recommended#{day}" and order.startswith("p"), (feed, order)


@then('it is in the accepted public partition sorted by "{prefix}"')
def accepted_sorted(context, prefix):
    feed, order = stored_keys(world(context).row)
    assert feed == f"{CORPUS}#accepted" and order.startswith(prefix), (feed, order)


@then("it is in no public partition")
def in_none(context):
    state = world(context)
    assert stored_keys(state.row) == (None, None), stored_keys(state.row)
    assert public_feed_keys(state.row) == {"publicFeedKey": None, "publicOrderKey": None}


@then("writing it names no public attribute at all")
def names_nothing(context):
    row = world(context).row
    assert not set(PUBLIC_KEY_FIELDS) & set(row), "an explicit null on an index key of a new row is not a missing attribute"
    assert not set(PUBLIC_KEY_FIELDS) & set(feed_keys(row))


def vote(context, action):
    from papyrus_newsroom.reference_actions import review_reference_curation

    state = world(context)
    row = state.row
    calls = []

    def graphql(query, variables):
        calls.append((query, variables))
        if "getReference" in query:
            return {"getReference": {**{key: row[key] for key in row if key in ("id", "lineageId", "corpusId", "versionState", "curationStatus", "sourceUri", "createdAt",
                                                                                 "predictedAcceptProbability", "feedArrivalAt", "publicFeedKey", "publicOrderKey")},
                                     "newsroomFeedKey": "references"}}
        return {"updateReference": {"id": row["id"]}}

    review_reference_curation(graphql, reference_id=row["id"], action=action, reason_code="out_of_scope" if action == "reject" else "")
    (update,) = [variables["input"] for query, variables in calls if "updateReference" in query]
    state.update = update
    row.update(update)


@when("an editor accepts it")
def editor_accepts(context):
    vote(context, "accept")


@when("an editor rejects it")
def editor_rejects(context):
    vote(context, "reject")


@then("clearing it names both public attributes")
def clearing_names_both(context):
    update = world(context).update
    assert "publicFeedKey" in update and "publicOrderKey" in update and update["publicFeedKey"] is None and update["publicOrderKey"] is None, update


@when('the Cyclotron decides "{label}" with {confidence:d}% confidence')
def cyclotron_decides(context, label, confidence):
    state = world(context)
    row = state.row
    record_original_prediction(state.backend, {"positiveLabel": "include"}, {"label": label, "confidence": confidence / 100, "decidedAt": row["createdAt"]},
                               row["id"], {"observedAt": row["createdAt"]})
    state.row = state.backend.get_record("Reference", row["id"])


def exploration(image, description, site="Example News"):
    return Exploration(True, PAGE, via="direct", metadata=PageMetadata(image_url=image, description=description, site_name=site, title="A page"))


def capture(context, image, description):
    state = world(context)
    row = state.backend.rows[state.row["id"]]
    state.preview = (image, description)
    attach_preview(state.backend, row, exploration=exploration(image, description), log=lambda line: None)
    state.row = state.backend.get_record("Reference", row["id"])
    state.backend.attachments_by_id = state.backend.attachments


@when("its page preview is captured with a picture, a long description and a site name")
def capture_plain(context):
    state = world(context)
    state.description = "A long description of the page. " * 30
    capture(context, "https://img.example.org/a.jpg", state.description)


@then("the row holds the picture address, the whole description and the site name")
def row_holds_card(context):
    state = world(context)
    assert state.row["cardImage"] == "https://img.example.org/a.jpg"
    assert state.row["cardSummary"] == state.description.strip(), "the description is stored whole: the clip happens when a card is drawn"
    assert state.row["cardSiteName"] == "Example News"
    assert state.row["cardPageTitle"] == "A page", "the title the page declared travels with the card, for a Reference titled with its own address"


@then("capturing the same preview again writes nothing more to the row")
def capturing_again(context):
    state = world(context)
    before = len(state.backend.written)
    capture(context, "https://img.example.org/a.jpg", state.description)
    assert len(state.backend.written) == before


@when("its page preview is captured with an email address and an identifier in the description")
def capture_private(context):
    capture(context, "https://img.example.org/a.jpg?who=editor@example.org", "Write to editor@example.org about " + A_UUID + " or ss1_abcdefghijkl.")


@then("no card attribute holds an email address or an identifier")
def nothing_private(context):
    row = world(context).row
    for name in CARD_FIELDS:
        value = row.get(name) or ""
        assert "@" not in value and "123e4567" not in value and "ss1_" not in value, (name, value)
    assert row["cardImage"] == "https://img.example.org/a.jpg"


@when("its page preview is captured with the platform's own picture")
def capture_platform_picture(context):
    capture(context, "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg", "A video.")


@then("the row's card picture is empty")
def card_picture_empty(context):
    assert not world(context).row.get("cardImage")


@when("its thumbnail copy is recorded")
def thumbnail_recorded(context):
    state = world(context)
    row = state.backend.rows[state.row["id"]]
    record_thumbnail(state.backend, row, {"state": "stored", "path": THUMBNAIL, "sha256": "a" * 64})
    state.row = state.backend.get_record("Reference", row["id"])


@then("the row's card picture is the thumbnail copy")
def card_picture_is_thumbnail(context):
    assert world(context).row["cardImage"] == f"/{THUMBNAIL}"


@given("a corpus with 3 accepted References and pending ones predicted 0.9, 0.7, none, 0.3, 0.2 and 0.1")
def a_corpus(context):
    state = world(context)
    arrival = "2026-11-02T12:00:00Z"
    for identifier, status, probability in (("a1", "accepted", 0.9), ("a2", "accepted", None), ("a3", "accepted", 0.2), ("p1", "pending", 0.9), ("p2", "pending", 0.7),
                                            ("p3", "pending", None), ("p4", "pending", 0.3), ("p5", "pending", 0.2), ("p6", "pending", 0.1)):
        row = a_row(identifier, status, arrival, probability)
        for name in PUBLIC_KEY_FIELDS:
            row.pop(name, None)   # as they were stored before the attributes existed
        row["predictionSortKey"] = f"{0.5 if probability is None else probability:.6f}#{arrival}#{identifier}"
        keep(context, row)
        state.backend.previews[f"{identifier}-lineage"] = [{"role": "preview", "sourceUri": f"https://img.example.org/{identifier}.jpg", "importedAt": arrival,
                                                              "metadata": json.dumps({"description": f"About {identifier}.", "siteName": "Example"})}]


def run_backfill(context, write):
    state = world(context)
    state.writes_before = len(state.backend.written)
    state.backend.pulled = 0
    state.backfill = backfill_public_fields(state.backend, corpus_id=CORPUS, dry_run=not write)


@when("the public-fields backfill runs as a preview")
def backfill_preview(context):
    run_backfill(context, write=False)


@when("the public-fields backfill runs with writing on")
def backfill_write(context):
    run_backfill(context, write=True)


@then("it writes nothing")
def writes_nothing(context):
    assert world(context).backend.written == []


@then("it reports {count:d} public rows")
def reports_public(context, count):
    assert world(context).backfill["public"] == count, world(context).backfill


@then("it read the pending index down to the first row under one half and no further")
def read_down_to_half(context):
    assert world(context).backend.pulled == 4, "p1, p2, the unpredicted row, then the first row under one half ends the read"


@then("it wrote {count:d} rows")
def wrote_rows(context, count):
    state = world(context)
    assert state.backfill["written"] == count and len(state.backend.written) - state.writes_before == count, state.backfill


@then("no vote was changed")
def no_vote_changed(context):
    assert not any("curation" in key for payload in world(context).backend.written for key in payload)


@then("it wrote nothing more")
def wrote_nothing_more(context):
    state = world(context)
    assert state.backfill["written"] == 0 and len(state.backend.written) == state.writes_before, state.backfill
