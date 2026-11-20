from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.home_page import incremental_test as helpers  # noqa: E402
from papyrus_content.home_page.state_store import DirtyBatch, MemoryStateStore  # noqa: E402
from papyrus_content.home_page.task import home_page_settings_of, run_home_page_snapshot  # noqa: E402

REFERENCES_KEY = helpers.REFERENCES_KEY


def start(context, size: int, *, threads: bool = False, build: bool = True) -> None:
    context.site = helpers.projected_site()
    context.add_cleanup(context.site.cleanup)
    context.client, context.store = helpers.CorpusClient(size), MemoryStateStore()
    context.threads = threads
    context.size = size
    if build:
        context.full_report = helpers.run(context.site, context.client, context.store, threads=threads)
        context.full_requests = context.client.total
        context.client.requests.clear()


def read_again(context, identifiers, **options) -> dict:
    context.client.requests.clear()
    context.before = context.site.writer.get(REFERENCES_KEY)
    context.report = helpers.run(context.site, context.client, context.store, DirtyBatch(ids=frozenset(identifiers), **options), threads=context.threads)
    return context.report


@given("a corpus of {size:d} References whose snapshot was built by a full read")
def built_corpus(context, size: int) -> None:
    start(context, size)


@given("a corpus of {size:d} References whose snapshot and threads were built by a full read")
def built_corpus_with_threads(context, size: int) -> None:
    start(context, size, threads=True)


@given("a corpus of {size:d} References with no state yet")
def corpus_without_state(context, size: int) -> None:
    start(context, size, build=False)


@when("an editor accepts and rates one Reference and the run reads it again")
def accept_and_rate_one(context) -> None:
    read_again(context, [helpers.accept(context.client, 1, stars=4)])


@when("an editor accepts {count:d} References and the run reads them again")
def accept_many(context, count: int) -> None:
    read_again(context, [helpers.accept(context.client, 1 + 3 * number) for number in range(count)])


@when("a run starts with nothing listed")
def nothing_listed(context) -> None:
    read_again(context, [])


@when("a pending Reference is retitled and the Cyclotron is only {percent:d} percent sure of it")
def retitled_and_doubted(context, percent: int) -> None:
    row = context.client.rows["reference-1-v1"]
    row["title"] = "Retitled and doubted"
    context.client.relations["reference-1"][0]["confidence"] = percent / 100
    read_again(context, [row["id"]])


@when("References are accepted, rated, retitled, rejected, archived and added, one is superseded by a new version and one has been deleted")
def many_changes(context) -> None:
    client = context.client
    ids = [helpers.accept(client, 1, stars=5), helpers.accept(client, 2), helpers.accept(client, 5, stars=1)]
    client.rows["reference-3-v1"]["title"] = "A retitled accepted Reference"
    client.rows["reference-6-v1"].update({"curationStatus": "rejected", "curationStatusKey": f"{helpers.CORPUS}#rejected"})
    client.rows["reference-8-v1"].update({"feedStateKey": None, "curationStatus": "archived"})
    client.rows["reference-9-v1"]["starRating"] = 2
    client.rows["reference-9-v1"]["curationSectionId"] = helpers.STORED_SECTION
    old = client.rows["reference-12-v1"]
    newer = {**old, "id": "reference-12-v2", "versionNumber": 2, "title": "Version two"}
    old["versionState"] = "superseded"
    client.rows[newer["id"]] = newer
    added = client.add(300)
    context.changed = [*ids, "reference-3-v1", "reference-6-v1", "reference-8-v1", "reference-9-v1", "reference-12-v1", newer["id"], added["id"], "reference-deleted-v1"]


@when("the run reads those rows again")
def run_those_rows(context) -> None:
    read_again(context, context.changed)


@when("an editor accepts one Reference with {stars:d} stars and the run reads it again")
def accept_with_stars(context, stars: int) -> None:
    context.rated = helpers.accept(context.client, 1, stars=stars)
    read_again(context, [context.rated])


@when("a Reference created after the file was built is accepted and the run reads it again")
def accept_new_reference(context) -> None:
    fresh = context.client.add(context.size)
    fresh["createdAt"] = fresh["feedArrivalAt"] = "2026-11-04T12:30:00.000Z"
    helpers.accept(context.client, context.size)
    read_again(context, [fresh["id"]])


@when("an older Reference is accepted and the run reads it again")
def accept_older_reference(context) -> None:
    read_again(context, [helpers.accept(context.client, 1)])


@when("a run starts with a Message change listed")
def message_listed(context) -> None:
    context.client.requests.clear()
    helpers.run(context.site, context.client, context.store, DirtyBatch(message_seq=1), threads=context.threads)


@when("the file in the bucket is changed by someone else and a run reads one Reference")
def file_changed_by_someone(context) -> None:
    context.site.writer.put(REFERENCES_KEY, context.site.writer.get(REFERENCES_KEY) + b" ")
    context.client.requests.clear()
    context.report = helpers.run(context.site, context.client, context.store, DirtyBatch(ids=frozenset({"reference-1-v1"})))


@when("a run starts with one Reference listed")
def one_listed(context) -> None:
    context.client.requests.clear()
    context.report = helpers.run(context.site, context.client, context.store, DirtyBatch(ids=frozenset({"reference-1-v1"})))


@when("a run starts with a full read requested")
def full_requested(context) -> None:
    context.client.requests.clear()
    context.report = helpers.run(context.site, context.client, context.store, DirtyBatch(ids=frozenset({"reference-1-v1"}), full_seq=1))


@when("the run is a dry run")
def dry_run(context) -> None:
    run_home_page_snapshot(context.site.context, context.client, home_page_settings_of(context.site.projector), now=helpers.NOW, dry_run=True, state_store=context.store, dirty=None)


def kinds(context) -> dict:
    return dict(context.client.requests)


@then("the run made exactly 4 requests: one section list, the Reference, its decision and its preview")
def four_requests(context) -> None:
    assert context.report["mode"] == "incremental", context.report
    assert kinds(context) == {"sections": 1, "getReference": 1, "relations": 1, "attachments": 1}, kinds(context)


@then("the full read had cost more than {size:d} requests")
def full_cost(context, size: int) -> None:
    assert context.full_requests > size, (context.full_requests, size)
    print(f"\n  {size} References: the full read made {context.full_requests} requests, the change made 4")  # noqa: T201


@then("the run made {count:d} requests")
def made_requests(context, count: int) -> None:
    assert context.client.total == count, kinds(context)


@then("the run made {count:d} requests: one section list, the Reference and its decision")
def made_requests_without_preview(context, count: int) -> None:
    assert kinds(context) == {"sections": 1, "getReference": 1, "relations": 1}, kinds(context)


@then("the snapshot file is unchanged")
def file_unchanged(context) -> None:
    assert helpers.without_stamp(json.loads(context.site.writer.get(REFERENCES_KEY))) == helpers.without_stamp(json.loads(context.before))


@then("the snapshot file holds exactly what a full read of the same corpus would write")
def same_as_full_read(context) -> None:
    other = helpers.projected_site()
    context.add_cleanup(other.cleanup)
    assert run_home_page_snapshot(other.context, context.client, home_page_settings_of(other.projector), now=helpers.NOW)["mode"] == "full"
    context.full_document = json.loads(other.writer.get(REFERENCES_KEY))
    assert helpers.without_stamp(helpers.document(context.site)) == helpers.without_stamp(context.full_document)


@then("the ranks are the ranks a full read would give")
def same_ranks(context) -> None:
    ranks = {record["key"]: record["rank"] for record in helpers.document(context.site)["references"]}
    assert ranks == {record["key"]: record["rank"] for record in context.full_document["references"]}
    assert sorted(ranks.values()) == list(range(1, len(ranks) + 1))


@then("no published file mentions who rated or when")
def no_rater_published(context) -> None:
    assert all(b"starRating" not in content and b"starRatedBy" not in content and b"starRatedAt" not in content for content in context.site.tree.values())


@then("the published record of that Reference shows {stars:d} stars")
def record_shows_stars(context, stars: int) -> None:
    record = next(record for record in helpers.document(context.site)["references"] if record["title"] == "Reference number 1")
    assert record["stars"] == stars, record


@when("only the stars of that Reference change and the run reads it again")
def only_stars_change(context) -> None:
    context.client.rows["reference-1-v1"].update({"starRating": 2})
    read_again(context, ["reference-1-v1"])


@then("the private state holds {stars:d} stars for that Reference")
def state_holds_stars(context, stars: int) -> None:
    key = next(record["key"] for record in helpers.document(context.site)["references"] if record["title"] == "Reference number 1")
    assert context.store.state.entries[key].stars == stars


@then("no thread was read")
def no_thread(context) -> None:
    assert "messageThreadsByKindAndUpdatedAt" not in context.client.requests, kinds(context)


@then("the threads were read")
def threads_read(context) -> None:
    assert context.client.requests["messageThreadsByKindAndUpdatedAt"] > 0, kinds(context)


@then("the threads were read and no Reference was read")
def threads_read_no_reference(context) -> None:
    assert context.client.requests["messageThreadsByKindAndUpdatedAt"] > 0 and context.client.requests["getReference"] == 0, kinds(context)


@then("the run read the whole corpus and says why")
def full_with_reason(context) -> None:
    assert context.report["mode"] == "full" and "not the one the state was built with" in context.report["fullBecause"], context.report
    assert context.client.requests["referencesByCurationStatusKey"] > 0


@then("the run read the whole corpus and says there is no state yet")
def full_no_state(context) -> None:
    assert context.report["mode"] == "full" and context.report["fullBecause"] == "there is no state yet", context.report


@then("the run read the whole corpus")
def full_read(context) -> None:
    assert context.report["mode"] == "full" and context.client.requests["referencesByCurationStatusKey"] > 0, context.report


@then("the next run reads only the listed Reference")
def next_run_incremental(context) -> None:
    read_again(context, ["reference-1-v1"])
    assert context.report["mode"] == "incremental" and context.client.requests["getReference"] == 1


@then("no state was saved and no file was written")
def nothing_saved(context) -> None:
    assert context.store.saves == 0 and context.site.writer.get(REFERENCES_KEY) is None


def unpredicted_row(context):
    return context.client.rows["reference-5-v1"]   # every tenth pending Reference of the test corpus, from the fifth, has no prediction yet


def listed_keys(context) -> set[str]:
    return {record["key"] for record in json.loads(context.site.writer.get(REFERENCES_KEY))["references"]}


@when("a pending Reference nobody has predicted is retitled and the run reads it again")
def unpredicted_retitled(context) -> None:
    unpredicted_row(context)["title"] = "Retitled while unpredicted"
    read_again(context, [unpredicted_row(context)["id"]])


@then("the run made {count:d} requests: one section list and the Reference")
def made_requests_section_and_reference(context, count: int) -> None:
    assert kinds(context) == {"sections": 1, "getReference": 1}, kinds(context)


@then("the snapshot file does not list that Reference")
def file_lacks_unpredicted(context) -> None:
    assert helpers.public_key("reference-5") not in listed_keys(context)


@when("the Cyclotron predicts {probability:f} for it, the picture of its video is stored, and the run reads it again")
def predicted_with_picture(context, probability: float) -> None:
    row = unpredicted_row(context)
    row.update({"medium": "video", "thumbnailPath": "assets/reference-thumbnails/a4645fd6b3de98f4-bb02a57c6adf.jpg", "predictedAcceptProbability": probability})
    context.client.relations["reference-5"][0]["confidence"] = probability
    read_again(context, [row["id"]])


@then("the snapshot file lists that Reference as recommended with confidence {probability:f} and its stored picture")
def file_lists_predicted(context, probability: float) -> None:
    record = next(item for item in json.loads(context.site.writer.get(REFERENCES_KEY))["references"] if item["key"] == helpers.public_key("reference-5"))
    assert (record["status"], record["confidence"]) == ("recommended", probability), record
    assert record["image"] == "/assets/reference-thumbnails/a4645fd6b3de98f4-bb02a57c6adf.jpg", record


@given("a corpus of {size:d} References whose snapshot was built under the old rule, which published Reference rows nobody had predicted")
def built_under_old_rule(context, size: int) -> None:
    from unittest import mock

    from papyrus_content.home_page import incremental

    context.site = helpers.projected_site()
    context.add_cleanup(context.site.cleanup)
    context.client, context.store, context.threads, context.size = helpers.CorpusClient(size), MemoryStateStore(), False, size
    with mock.patch.object(incremental, "STATE_FORMAT", 1), mock.patch("papyrus_content.home_page.export.has_prediction", lambda row: True):
        helpers.run(context.site, context.client, context.store)
    assert helpers.public_key("reference-5") in listed_keys(context), "the old rule published it"


@then("the run read the whole corpus because the build of the fields changed")
def full_because_build_changed(context) -> None:
    assert context.report["mode"] == "full" and "build of the fields" in context.report["fullBecause"], context.report


@then("the snapshot file no longer lists the Reference nobody had predicted")
def file_lacks_after_full_read(context) -> None:
    assert helpers.public_key("reference-5") not in listed_keys(context)


def published_sections(context) -> dict:
    return {record["title"]: record.get("section") for record in json.loads(context.site.writer.get(REFERENCES_KEY))["references"]}


@then('the full read published the title "{title}" for the Reference tagged with the stored section id "publication#slug"')
def full_read_names_section(context, title: str) -> None:
    published = published_sections(context)
    assert published["Reference number 3"] == title, published["Reference number 3"]
    assert published["Reference number 6"] is None


@when("an editor tags one Reference with that stored section id and another with an id that names no section, and the run reads them again")
def tag_two(context) -> None:
    context.client.rows["reference-9-v1"]["curationSectionId"] = helpers.STORED_SECTION
    context.client.rows["reference-12-v1"]["curationSectionId"] = "example-publication#no-such-section"
    read_again(context, ["reference-9-v1", "reference-12-v1"])


@then('the tagged Reference publishes the title "{title}" and the other publishes no section')
def tagged_publishes_title(context, title: str) -> None:
    published = published_sections(context)
    assert published["Reference number 9"] == title, published["Reference number 9"]
    assert published["Reference number 12"] is None
