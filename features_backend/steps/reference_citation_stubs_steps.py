"""Steps for features_backend/reference-citation-stubs.feature. Everything is in memory: no network, no AWS, no model."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import test_monitoring_intake as intake_tests  # noqa: E402
from papyrus_content.monitoring import Monitor, SourceItem  # noqa: E402
from papyrus_content.monitoring_intake import ReferenceIntake  # noqa: E402
from papyrus_content.monitoring_router import record_original_prediction  # noqa: E402
from papyrus_content.reference_citation_stubs import (RETIRED_BY, STUB_CHANGE_REASON, STUB_CREATED_BY, STUB_STATUS_REASON,  # noqa: E402
                                                      retire_citation_stubs)
from papyrus_content.reference_feed_keys import feed_keys  # noqa: E402

CORPUS = "knowledge-corpus-publication"
NOW = "2026-11-03T12:00:00.000Z"
PAPER = "https://example.org/paper"


class Backend:
    """A corpus's Reference table, recording every write."""

    def __init__(self):
        self.rows, self.written = {}, []

    def list_by_index(self, index, key):
        assert index == "referencesByCurationStatusKey", index
        return [copy.deepcopy(row) for row in self.rows.values() if f"{row['corpusId']}#{row['curationStatus']}" == key]

    def update_record(self, model, payload):
        assert model == "Reference", model
        self.written.append(copy.deepcopy(payload))
        self.rows[payload["id"]].update(payload)

    def add(self, name, **extra):
        row = {"id": f"{name}-v1", "lineageId": name, "versionNumber": 1, "versionState": "current", "corpusId": CORPUS,
               "changeReason": STUB_CHANGE_REASON, "curationStatus": "pending", "curationStatusKey": f"{CORPUS}#pending",
               "curationStatusUpdatedBy": STUB_CREATED_BY, "curationStatusReason": STUB_STATUS_REASON,
               "createdAt": "2026-10-01T00:00:00Z", "sourceUri": f"https://example.org/{name}", "inboundCitationCount": 0,
               "newsroomFeedKey": "references", "reviewedFeedKey": None, **extra}
        row.update({key: extra.get(key, value) for key, value in feed_keys(row).items()})
        self.rows[row["id"]] = row
        return row


def _backend(context):
    context.backend = Backend()
    context.second = None
    return context.backend


@given("a corpus with {plain:d} untouched citation stubs, {starred:d} starred citation stub, {reopened:d} citation stub a person reopened "
       "and {found:d} paper a monitor found")
def mixed_corpus(context, plain, starred, reopened, found):
    backend = _backend(context)
    for index in range(plain):
        backend.add(f"plain-{index}")
    for index in range(starred):
        backend.add(f"starred-{index}", starRating=4, starRatedBy="an editor", starFeedKey=f"{CORPUS}#stars#4")
    for index in range(reopened):
        backend.add(f"reopened-{index}", curationStatusUpdatedBy="an editor")   # reopened with no note: only the actor differs
    for index in range(found):
        backend.add(f"found-{index}", changeReason="monitor-discovery", curationStatusUpdatedBy="papyrus-monitoring-worker",
                    curationStatusReason="Discovered through a monitor")


@given("a corpus with {count:d} untouched citation stub that has a prediction")
def predicted_stub(context, count):
    backend = _backend(context)
    for index in range(count):
        backend.add(f"predicted-{index}", predictedAcceptProbability=0.2, predictionDecidedAt="2026-10-02T00:00:00.000Z")


@given("a corpus with {count:d} starred citation stub")
def starred_stub(context, count):
    backend = _backend(context)
    for index in range(count):
        backend.add(f"starred-{index}", starRating=5, starRatedBy="an editor", starFeedKey=f"{CORPUS}#stars#5")


@given("a corpus with {count:d} citation stub a person reopened")
def reopened_stub(context, count):
    backend = _backend(context)
    for index in range(count):
        backend.add(f"reopened-{index}", curationStatusUpdatedBy="an editor")   # reopened with no note: only the actor differs


@given("a corpus with citation stubs: {plain:d} with a link and no citations, {cited:d} with a link and {inbound:d} citations, {bare:d} without a link")
def link_corpus(context, plain, cited, inbound, bare):
    backend = _backend(context)
    for index in range(plain):
        backend.add(f"linked-{index}")
    for index in range(cited):
        backend.add(f"cited-{index}", inboundCitationCount=inbound)
    for index in range(bare):
        backend.add(f"bare-{index}", sourceUri=None)


@when("the citation stubs are retired")
def retire(context):
    context.before = copy.deepcopy(context.backend.rows)
    context.counts = retire_citation_stubs(context.backend, corpus_id=CORPUS, now=NOW)


@when("the citation stubs are retired as a dry run")
def retire_dry(context):
    context.before = copy.deepcopy(context.backend.rows)
    context.counts = retire_citation_stubs(context.backend, corpus_id=CORPUS, dry_run=True, now=NOW)


@when("the citation stubs are retired again")
def retire_again(context):
    context.backend.written.clear()
    context.second = retire_citation_stubs(context.backend, corpus_id=CORPUS, now=NOW)


@then("{count:d} References are archived")
@then("{count:d} Reference is archived")
def archived(context, count):
    rows = [row for row in context.backend.rows.values() if row["curationStatus"] == "archived"]
    assert len(rows) == count, (len(rows), count)


@then("the retirement counts say {scanned:d} scanned, {eligible:d} eligible and {skipped:d} skipped")
def counts_skipped(context, scanned, eligible, skipped):
    counts = context.counts
    assert (counts["scanned"], counts["eligible"], counts["skipped"]) == (scanned, eligible, skipped), counts


@then("the retirement counts say {scanned:d} scanned, {eligible:d} eligible and {written:d} written")
def counts_written(context, scanned, eligible, written):
    counts = context.counts
    assert (counts["scanned"], counts["eligible"], counts["written"]) == (scanned, eligible, written), counts


@then("the retirement counts say {linked:d} with a link, {bare:d} without a link and {cited:d} cited")
def counts_links(context, linked, bare, cited):
    counts = context.counts
    assert (counts["withUrl"], counts["withoutUrl"], counts["withInboundCitations"]) == (linked, bare, cited), counts


@then("the retirement counts say {count:d} skipped because it is starred")
def counts_starred(context, count):
    assert context.counts["skipped.starred"] == count and context.counts["eligible"] == 0, context.counts


@then("the retirement counts say {count:d} skipped because its actor is not the system actor")
def counts_actor(context, count):
    assert context.counts["skipped.notSystemActor"] == count and context.counts["eligible"] == 0, context.counts


@then("the starred stub, the reopened stub and the monitor's paper are still pending")
def untouched(context):
    for prefix in ("starred-", "reopened-", "found-"):
        [row] = [row for row in context.backend.rows.values() if row["lineageId"].startswith(prefix)]
        assert row["curationStatus"] == "pending" and row == context.before[row["id"]], row["id"]


@then("no stub was written or changed")
def nothing(context):
    assert context.backend.written == [] and context.backend.rows == context.before


@then("the archived stub still records its prediction")
def keeps_prediction(context):
    [row] = context.backend.rows.values()
    assert row["predictedAcceptProbability"] == 0.2 and row["predictionDecidedAt"] == "2026-10-02T00:00:00.000Z"


@then("the archived stub is in no feed")
def no_feed(context):
    [row] = context.backend.rows.values()
    assert row["curationStatus"] == "archived" and row["curationStatusKey"] == f"{CORPUS}#archived" and row["feedStateKey"] is None


@then("the archived stub is still in the corpus with its link")
def still_there(context):
    [row] = context.backend.rows.values()
    assert row["sourceUri"] == "https://example.org/predicted-0" and row["versionState"] == "current"


@then("the archived stub is signed by the machine and records no vote")
def signed(context):
    [row] = context.backend.rows.values()
    assert row["curationStatusUpdatedBy"] == RETIRED_BY and not row.get("curationActorKind")


@then("the second run scanned {count:d} and wrote nothing")
def second_run(context, count):
    assert context.second["scanned"] == count and context.second["written"] == 0 and context.backend.written == [], context.second


# --- the monitor restores a machine-archived match ---------------------------------------------------

def _monitor_setup(context, *, status, by):
    client = intake_tests.Client()
    monitor = Monitor("hn", "publication", CORPUS, client.endpoint, Path("/tmp/monitor-state-unused"))
    context.client = client
    context.sink = ReferenceIntake(client, monitor, auth_mode="iam", persist=lambda rows: None)
    context.item = SourceItem("123", "A paper", PAPER, "https://news.ycombinator.com/item?id=123", None)
    context.provenance = {**monitor.binding, "sourceId": "123", "sourceItemUrl": context.item.source_item_url,
                          "fingerprint": context.item.fingerprint, "observedAt": "2026-11-04T00:00:00Z", "revision": 1}
    stub = Backend().add("stub", sourceUri=PAPER, curationStatus=status, curationStatusKey=f"{CORPUS}#{status}", curationStatusUpdatedBy=by,
                         curationStatusReason="Archived", reviewedFeedKey="references#reviewed", feedStateKey=None)
    client.references.append(stub)
    context.left = copy.deepcopy(stub)


@given("a citation stub the machine archived")
def machine_archived(context):
    _monitor_setup(context, status="archived", by=RETIRED_BY)


@given("a citation stub an editor rejected")
def editor_rejected(context):
    _monitor_setup(context, status="rejected", by="an editor")


@given("a citation stub a person archived")
def person_archived(context):
    _monitor_setup(context, status="archived", by="an editor")


@when("a monitor finds that paper")
def monitor_finds(context):
    context.receipt = context.sink(context.item, context.provenance)


@when("a monitor finds that paper and the Cyclotron predicts it")
def monitor_finds_and_predicts(context):
    context.receipt = context.sink(context.item, context.provenance)
    publication = {"positiveLabel": "include"}
    decision = {"label": "include", "confidence": 0.83, "decidedAt": "2026-11-04T00:00:01Z"}
    record_original_prediction(context.client, publication, decision, context.receipt["referenceId"], {"observedAt": "2026-11-04T00:00:00Z"})


@then("the stub is pending again and in the unrated feed")
def restored(context):
    [row] = context.client.references
    assert row["curationStatus"] == "pending" and row["curationStatusKey"] == f"{CORPUS}#pending", row
    assert row["feedStateKey"] == f"{CORPUS}#unrated" and row["reviewedFeedKey"] is None


@then("the stub has the prediction of the Cyclotron")
def predicted(context):
    [row] = context.client.references
    assert row["predictedAcceptProbability"] == 0.83 and row["predictionSortKey"].startswith("0.830000#"), row


@then("no second Reference was created")
def no_second(context):
    assert len(context.client.references) == 1 and context.client.writes == [] and context.receipt["referenceId"] == "stub-v1"


@then("the Reference is exactly as the editor left it")
@then("the Reference is exactly as the person left it")
def as_left(context):
    [row] = context.client.references
    assert {key: row[key] for key in context.left} == context.left, row
    assert "referenceRestored" not in context.receipt
