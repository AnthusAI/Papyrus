"""A Reference created by the CLI, the Add dialog or any other creating route is enriched before it is predicted
(src/papyrus_content/reference_prediction_queue.py, monitoring_router.Router.enrich_created_reference).

Offline: an in-memory monitoring table, the scripted machine API of the router tests, in-memory AppSync and attachment storage, and a scripted capture and
summary model. No AWS, no network, no model.
"""
import copy
import json

import pytest

from curation_support import MemoryStore, Summarizer
from papyrus_content import monitoring_enrichment as me
from papyrus_content import monitoring_router as mr
from papyrus_content import reference_prediction_queue as queue
from papyrus_content.monitoring_view import TableViewStore
from procedures.newsroom.tests.test_monitoring_enrichment import ARTICLE, SUMMARY, Capturer, failed, good
from procedures.newsroom.tests.test_monitoring_router import ENDPOINT, FakeTable, LabAppSync, go, router_config, setup_router

ENDPOINT_ANTH = ENDPOINT.replace("abc123", "api0")
CORPUS = "knowledge-corpus-anth-us"
PAGE = "https://example.org/pasted"
VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


class EnrichedLab(LabAppSync):
    """LabAppSync plus the attachment tables curation writes."""

    def __init__(self, *args):
        super().__init__(*args)
        self.tables = {"ReferenceAttachment": {}, "ModelAttachment": {}}

    def upsert(self, model, row):
        self.tables.setdefault(model, {})[row["id"]] = copy.deepcopy(row)
        return "created"

    def get_record(self, model, record_id):
        if model in self.tables:
            row = self.tables[model].get(record_id)
            return copy.deepcopy(row) if row else None
        return super().get_record(model, record_id)

    def list_by_index(self, index, key, **kwargs):
        if index == "referenceAttachmentsByReferenceLineageAndSortKey":
            return [copy.deepcopy(r) for r in self.tables["ReferenceAttachment"].values() if r.get("referenceLineageId") == key]
        if index == "modelAttachmentsByOwnerRoleAndSortKey":
            return [copy.deepcopy(r) for r in self.tables["ModelAttachment"].values() if r.get("ownerId") == key]
        return super().list_by_index(index, key)

    def card(self, reference_id):
        for row in self.tables["ReferenceAttachment"].values():
            if row.get("role") == "curation" and row.get("referenceId") == reference_id:
                return json.loads(row["metadata"])
        return None


def reference_row(identifier="reference-user-intake-aaa-v1", address=PAGE, **more):
    return {"id": identifier, "lineageId": identifier.removesuffix("-v1"), "versionNumber": 1, "versionState": "current", "corpusId": CORPUS,
            "sourceUri": address, "title": "A pasted page", "curationStatus": "pending", "createdAt": "2026-11-05T10:00:00Z",
            "feedStateKey": f"{CORPUS}#unrated", "feedArrivalAt": "2026-11-05T10:00:00.000Z",
            "predictionSortKey": f"0.500000#2026-11-05T10:00:00.000Z#{identifier}", **more}


def request_of(row):
    return {"referenceId": row["id"], "sourceUri": row["sourceUri"], "title": row["title"]}


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr("papyrus_content.records.upload_attachment_body", lambda client, expected, body: None)
    table = FakeTable()
    store, cyclotron = setup_router(table)
    client = EnrichedLab(ENDPOINT_ANTH, CORPUS)
    monkeypatch.setattr(me, "AttachmentStore", lambda c: MemoryStore(c))
    queue_store = TableViewStore(table, "hn")
    order = []
    original_post = cyclotron.http

    def add(row):
        client.rows[("Reference", row["id"])] = row
        return row

    def ask(*rows):
        return queue.queue_reference_predictions(queue_store, endpoint=ENDPOINT_ANTH, references=[request_of(r) for r in rows], subject="user-intake")

    def drain(now=2000, capture=None, summarizer="default", **kwargs):
        enrich = me.Enricher(texts=me.MemoryTexts(), summarizer=Summarizer(SUMMARY) if summarizer == "default" else summarizer,
                             capture=capture or Capturer(good()))
        kwargs.setdefault("enricher", enrich)
        return go(table, store, cyclotron, now=now, task="email-references", appsync=lambda endpoint: client, **kwargs)

    return type("World", (), {"table": table, "cyclotron": cyclotron, "client": client, "add": staticmethod(add), "ask": staticmethod(ask),
                              "drain": staticmethod(drain), "queue_store": queue_store, "order": order})


def lane_rows(table):
    return [row for row in table.by_prefix("DISC#") if row.get("gsi1pk") == f"ROUTING#hn#{queue.LANE}"]


def stored(world, identifier="reference-user-intake-aaa-v1"):
    return world.client.rows[("Reference", identifier)]


# --- the queue key ---------------------------------------------------------------------------------------------------------------


def test_the_enrichment_key_is_stable_per_reference_and_never_the_prediction_key():
    one = queue.enrichment_source_id(ENDPOINT_ANTH, CORPUS, "reference-a-v1")
    assert one == queue.enrichment_source_id(ENDPOINT_ANTH, CORPUS, "reference-a-v1") and len(one) == 64
    assert one != queue.enrichment_source_id(ENDPOINT_ANTH, CORPUS, "reference-b-v1")
    assert one != queue.enrichment_source_id(ENDPOINT_ANTH, "knowledge-corpus-other", "reference-a-v1")
    assert one != queue.prediction_source_id(ENDPOINT_ANTH, CORPUS, "reference-a-v1")


def test_every_request_asks_for_enrichment_once_and_a_retry_adds_nothing(world):
    row = world.add(reference_row())
    first = world.ask(row)
    (queued,) = lane_rows(world.table)
    assert first["queued"] == 1 and queued["predictFor"]["enrich"] is True and "enrichOnly" not in queued["predictFor"]
    assert queued["sourceId"] == queue.prediction_source_id(ENDPOINT_ANTH, CORPUS, row["id"])
    again = world.ask(row)
    assert again["queued"] == 0 and again["alreadyQueued"] == 1 and len(lane_rows(world.table)) == 1
    assert queue.wants_enrichment(queued) and not queue.is_enrich_only(queued)
    legacy = {**queued, "predictFor": {k: v for k, v in queued["predictFor"].items() if k != "enrich"}}
    assert not queue.wants_enrichment(legacy) and not queue.wants_enrichment(None)


def test_an_enrich_only_request_has_its_own_key_so_a_settled_prediction_row_does_not_hide_it(world):
    row = world.add(reference_row())
    world.ask(row)
    done = queue.queue_reference_predictions(world.queue_store, endpoint=ENDPOINT_ANTH, references=[{**request_of(row), "enrichOnly": True}], subject="operator")
    assert done["queued"] == 1 and len(lane_rows(world.table)) == 2
    assert done["sourceIds"] == [queue.enrichment_source_id(ENDPOINT_ANTH, CORPUS, row["id"])]
    assert queue.queue_reference_predictions(world.queue_store, endpoint=ENDPOINT_ANTH, references=[{**request_of(row), "enrichOnly": True}],
                                             subject="operator")["alreadyQueued"] == 1


def test_the_backfill_picks_current_unarchived_references_whose_content_is_not_captured():
    rows = [reference_row("reference-a-v1"), reference_row("reference-b-v1", captureState="full"), reference_row("reference-c-v1", captureState="thin"),
            reference_row("reference-d-v1", captureState="running"), reference_row("reference-e-v1", curationStatus="archived"),
            reference_row("reference-f-v1", versionState="superseded"), reference_row("reference-g-v1", address="")]
    assert [item["referenceId"] for item in queue.references_for_enrichment(rows)] == ["reference-a-v1", "reference-c-v1"]
    assert all(item["enrichOnly"] for item in queue.references_for_enrichment(rows))


def test_videos_are_counted_and_the_line_says_which_command_to_run():
    items = [{"sourceUri": VIDEO}, {"sourceUri": PAGE}, {"sourceUri": "https://youtu.be/dQw4w9WgXcQ"}]
    assert queue.videos_needing_local_run(items) == 2
    line = queue.video_line("references\tcreate-from-catalog", 2)
    assert "2 videos need a local run: papyrus references capture-thumbnails --write" in line
    assert "1 video needs a local run" in queue.video_line("p", 1) and queue.video_line("p", 0) is None


# --- the router ------------------------------------------------------------------------------------------------------------------


def test_the_router_enriches_the_existing_reference_before_it_decides_and_decides_on_the_enriched_text(world):
    row = world.add(reference_row())
    world.ask(row)
    result = world.drain()
    assert result["counts"]["referencesEnriched"] == 1 and result["counts"]["curationCopied"] == 1 and result["counts"]["predicted"] == 1
    card = world.client.card(row["id"])
    assert card["summary"]["text"] == SUMMARY and card["capture"]["status"] == "completed" and card["origin"]["kind"] == "item-enrichment"
    (post,) = world.cyclotron.posts()
    values = post[2]["payload"]["item"]["values"]
    assert values["summary"] == SUMMARY and values["text"].endswith(ARTICLE)   # enrich before decide
    assert stored(world)["predictedAcceptProbability"] is not None
    assert len([r for k, r in world.client.rows.items() if k[0] == "Reference"]) == 1   # the EXISTING Reference: nothing was created
    assert not lane_rows(world.table)


def test_enrichment_runs_once_however_often_the_request_is_worked(world):
    row = world.add(reference_row())
    world.ask(row)
    capture = Capturer(good())
    world.drain(capture=capture)
    assert len(capture.calls) == 1
    world.ask(row)   # a retried creation: the request is already settled
    world.drain(now=3000, capture=capture)
    assert len(capture.calls) == 1 and len(world.cyclotron.posts()) == 1


def test_an_enrichment_that_failed_is_recorded_on_the_reference_and_does_not_block_the_prediction(world, capsys):
    row = world.add(reference_row())
    world.ask(row)
    result = world.drain(capture=Capturer(failed("blocked")))
    assert result["counts"]["enrichmentFailed"] == 1 and result["counts"]["predicted"] == 1
    card = world.client.card(row["id"])
    assert card["capture"]["status"] == "failed" and card["capture"]["reason"] and card["status"] == "capture_failed"   # on the Reference, with its reason
    assert '"referenceEnrichment": "failed"' in capsys.readouterr().out
    assert stored(world)["predictedAcceptProbability"] is not None
    (post,) = world.cyclotron.posts()
    assert "summary" not in post[2]["payload"]["item"]["values"]   # decided on what exists


def test_a_transient_failure_waits_for_the_next_run_and_the_prediction_follows_the_enrichment(world):
    row = world.add(reference_row())
    world.ask(row)
    capture = Capturer(failed("timeout", transient=True), good())
    first = world.drain(capture=capture)
    assert first["counts"]["predicted"] == 0 and first["counts"]["enrichmentWaiting"] == 1 and world.cyclotron.posts() == []
    assert len(lane_rows(world.table)) == 1 and "predictedAcceptProbability" not in stored(world)
    second = world.drain(now=2000 + 3600, capture=capture)
    assert second["counts"]["predicted"] == 1 and world.client.card(row["id"])["summary"]["text"] == SUMMARY


def test_one_reference_that_blows_up_does_not_stop_the_others(world):
    first, second = world.add(reference_row("reference-one-v1", address="https://example.org/one")), world.add(reference_row("reference-two-v1", address="https://example.org/two"))
    world.ask(first, second)
    original = world.client.upsert

    def flaky(model, row):
        if model == "ReferenceAttachment" and row.get("referenceId") == first["id"] and row.get("role") == "curation":
            raise RuntimeError("AppSync unavailable")
        return original(model, row)

    world.client.upsert = flaky
    result = world.drain(capture=Capturer(good()))
    assert result["counts"]["curationCopyFailed"] == 1 and result["counts"]["enrichmentFailed"] == 1 and result["counts"]["predicted"] == 2
    assert world.client.card(second["id"]) and stored(world, "reference-one-v1")["predictedAcceptProbability"] is not None


def test_without_an_enricher_the_request_is_decided_as_before_and_says_why_it_was_not_enriched(world):
    row = world.add(reference_row())
    world.ask(row)
    result = go(world.table, *setup_pair(world), now=2000, task="email-references", appsync=lambda endpoint: world.client)
    assert result["counts"]["predicted"] == 1 and result["counts"]["referencesEnriched"] == 0
    route = next(r for k, r in world.table.items.items() if k[1].startswith("ROUTE#"))
    assert route["enrichment"]["reason"] == "enrichment_not_configured"


def setup_pair(world):
    from procedures.newsroom.tests.test_monitoring_router import RouterStore
    return RouterStore(world.table), world.cyclotron


def test_a_request_queued_before_enrichment_existed_is_decided_without_it(world):
    row = world.add(reference_row())
    world.ask(row)
    for queued in lane_rows(world.table):
        queued["predictFor"].pop("enrich")
    capture = Capturer(good())
    result = world.drain(capture=capture)
    assert capture.calls == [] and result["counts"]["predicted"] == 1 and world.client.card(row["id"]) is None


def test_a_video_is_enriched_as_far_as_the_cloud_can_and_left_for_the_local_runners(world):
    row = world.add(reference_row("reference-video-v1", address=VIDEO, title="A talk", medium="video"))
    world.ask(row)
    result = world.drain(capture=Capturer(failed("blocked")))
    assert result["counts"]["videosNeedLocalRun"] == 1 and result["counts"]["predicted"] == 1
    video = stored(world, "reference-video-v1")
    assert video["contentNeededKey"] == f"{CORPUS}#video#needs_content#pending"   # the index capture-transcripts reads
    route = next(r for k, r in world.table.items.items() if k[1].startswith("ROUTE#"))
    assert route["enrichment"]["needsLocalRun"] is True and route["enrichment"]["hasThumbnail"] is False


def test_a_captured_page_description_leaves_a_video_thin_and_in_the_content_needed_index(world):
    text = "A talk about transit. " * 10
    page = good(text)
    page.text_reason = "awaiting_transcript"
    row = world.add(reference_row("reference-video-v1", address=VIDEO, title="A talk", medium="video"))
    world.ask(row)
    world.drain(capture=Capturer(page))
    video = stored(world, "reference-video-v1")
    assert video["captureState"] == "thin" and video["contentNeededKey"] == f"{CORPUS}#video#needs_content#pending"


def test_an_enrich_only_request_enriches_a_predicted_reference_and_decides_nothing(world):
    row = world.add(reference_row(predictedAcceptProbability=0.7, predictionDecidedAt="2026-11-05T09:00:00.000Z"))
    done = queue.queue_reference_predictions(world.queue_store, endpoint=ENDPOINT_ANTH, references=[{**request_of(row), "enrichOnly": True}], subject="operator")
    assert done["queued"] == 1
    result = world.drain()
    assert result["counts"]["referencesEnriched"] == 1 and world.cyclotron.posts() == [] and result["counts"]["predicted"] == 0
    assert world.client.card(row["id"])["summary"]["text"] == SUMMARY and stored(world)["predictedAcceptProbability"] == 0.7
    assert not lane_rows(world.table)


def test_an_enrich_only_request_for_a_missing_reference_is_refused_not_enriched(world):
    gone = reference_row("reference-gone-v1")
    queue.queue_reference_predictions(world.queue_store, endpoint=ENDPOINT_ANTH, references=[{**request_of(gone), "enrichOnly": True}], subject="operator")
    capture = Capturer(good())
    result = world.drain(capture=capture)
    assert capture.calls == [] and result["counts"]["refused"] == 1 and not lane_rows(world.table)


def test_a_monitor_item_is_enriched_and_delivered_exactly_as_before():
    from procedures.newsroom.tests.test_monitoring_enrichment import enricher
    from procedures.newsroom.tests.test_monitoring_router import ONE_FEED, collected_table
    table = collected_table(ONE_FEED)
    store, cyclotron = setup_router(table)
    result = go(table, store, cyclotron, enricher=enricher(good()))
    assert result["counts"]["enriched"] == 1 and result["counts"]["decided"] == 1
    assert result["counts"]["referencesEnriched"] == 0 and result["counts"]["videosNeedLocalRun"] == 0


# --- distinct states, labels and precedence (PPY-d683da, PPY-47e246) -----------------------------------------------------------------


@pytest.mark.parametrize("capture,copied,state", [
    ({"status": "completed"}, "copied", "enriched"),
    ({"status": "completed"}, "kept", "kept"),
    ({"status": "failed", "reason": "too_large"}, "copied", "oversized"),
    ({"status": "failed", "reason": "blocked"}, "copied", "blocked"),
    ({"status": "failed", "reason": "unsupported_media"}, "copied", "blocked"),
    ({"status": "failed", "reason": "unreadable"}, "copied", "capture_failed"),
    ({"status": "completed"}, "failed: boom", "copy_failed"),
])
def test_each_enrichment_outcome_has_its_own_state(capture, copied, state):
    assert mr.enrichment_state(capture, copied) == state


def test_an_oversized_source_is_final_with_its_reason_on_the_reference_and_is_not_retried(world):
    row = world.add(reference_row())
    world.ask(row)
    capture = Capturer(failed("too_large"))
    result = world.drain(capture=capture)
    assert result["counts"]["predicted"] == 1 and len(capture.calls) == 1
    assert world.client.card(row["id"])["capture"]["reason"] == "too_large"
    route = next(r for k, r in world.table.items.items() if k[1].startswith("ROUTE#"))
    assert route["enrichment"]["state"] == "oversized"
    world.ask(row)
    world.drain(now=9000, capture=capture)
    assert len(capture.calls) == 1


def test_automated_text_is_labelled_as_not_checked_for_completeness(world):
    row = world.add(reference_row())
    world.ask(row)
    world.drain()
    origin = world.client.card(row["id"])["origin"]
    assert origin["completenessChecked"] is False and "not independently checked" in origin["note"]


def test_text_a_person_supplied_is_never_replaced(world):
    row = world.add(reference_row(captureState="full"))
    world.ask(row)
    capture = Capturer(good())
    result = world.drain(capture=capture)
    assert capture.calls == [] and world.client.card(row["id"]) is None and result["counts"]["predicted"] == 1
    route = next(r for k, r in world.table.items.items() if k[1].startswith("ROUTE#"))
    assert route["enrichment"]["state"] == "already_captured"


def test_a_correction_card_that_exists_is_kept_not_overwritten(world):
    row = world.add(reference_row())
    world.ask(row)
    world.client.tables["ReferenceAttachment"]["card"] = {"id": "card", "role": "curation", "referenceId": row["id"], "referenceLineageId": row["lineageId"],
                                                           "sortKey": "003-curation", "metadata": json.dumps({"summary": {"text": "by a person"}, "capture": {"status": "completed"}})}
    world.drain()
    assert world.client.card(row["id"])["summary"]["text"] == "by a person"


def test_a_stale_content_needed_key_on_a_captured_reference_is_repaired_and_reported(world):
    row = world.add(reference_row("reference-video-v1", address=VIDEO, title="A talk", medium="video", contentNeededKey=f"{CORPUS}#video#needs_content#pending"))
    world.ask(row)
    page = good("A talk about transit. " * 40)
    world.drain(capture=Capturer(page))
    route = next(r for k, r in world.table.items.items() if k[1].startswith("ROUTE#"))
    assert route["enrichment"]["needsLocalRun"] is True


# --- the creating routes -----------------------------------------------------------------------------------------------------------


def test_the_add_dialog_and_the_signed_in_cli_share_one_action_that_queues_one_enrichment_each_and_counts_videos(world):
    created = {"ok": True, "references": [
        {"id": "reference-user-intake-aaa-v1", "sourceUri": PAGE, "curationStatus": "pending"},
        {"id": "reference-user-intake-vid-v1", "sourceUri": VIDEO, "curationStatus": "pending"},
        {"id": "reference-old-v1", "sourceUri": "https://example.org/old", "curationStatus": "pending", "reusedExisting": True}]}
    env = {"PAPYRUS_GRAPHQL_ENDPOINT": ENDPOINT_ANTH}
    first = queue.queue_after_intake(created, {"items": []}, env=env, store=world.queue_store)
    assert first["queued"] == 2 and first["videos"] == 1
    rows = lane_rows(world.table)
    assert len(rows) == 2 and all(queue.wants_enrichment(row) for row in rows)
    again = queue.queue_after_intake(created, {"items": []}, env=env, store=world.queue_store)   # a re-run
    assert again["queued"] == 0 and again["alreadyQueued"] == 2 and len(lane_rows(world.table)) == 2


def test_the_signed_in_cli_says_how_many_videos_need_a_local_run(tmp_path, monkeypatch, capsys):
    from papyrus_content import reference_intake_cli as cli

    monkeypatch.setattr(cli, "resolve_catalog_corpus", lambda *a, **k: ({"key": "anth-us"}, None))
    monkeypatch.setattr(cli, "knowledge_corpus_id", lambda corpus: CORPUS)

    class Client:
        endpoint = ENDPOINT_ANTH

        def graphql(self, mutation, variables):
            item = json.loads(variables["input"])["items"][0]
            is_video = "youtube" in item["source_uri"]
            return {"intakePendingReferences": json.dumps({"ok": True, "references": [{"id": "r-" + item["title"], "curationStatus": "pending"}],
                                                           "prediction": {"ok": True, "requested": 1, "videos": int(is_video)}})}

    catalog = tmp_path / "c.json"
    catalog.write_text(json.dumps({"items": [{"source_uri": VIDEO, "title": "talk", "ingestion_rationale": "r"},
                                               {"source_uri": PAGE, "title": "page", "ingestion_rationale": "r"}]}))
    cli.register_pending_catalog(Client(), {"catalog": str(catalog)}, apply=True)
    out = capsys.readouterr().out
    assert "1 video needs a local run: papyrus references capture-thumbnails --write" in out


def test_the_iam_cli_branch_attaches_previews_to_the_references_it_created(monkeypatch):
    from papyrus_content import cli
    seen = []
    monkeypatch.setattr("papyrus_content.reference_images.attach_preview", lambda client, reference: seen.append(reference["id"]))
    changes = [{"modelName": "Reference", "action": "create", "expected": reference_row("reference-new-v1")},
               {"modelName": "Reference", "action": "update", "expected": reference_row("reference-old-v1")},
               {"modelName": "ReferenceAttachment", "action": "create", "expected": {"id": "x"}}]
    assert cli.attach_previews_for_created(object(), changes) == 1 and seen == ["reference-new-v1"]


def test_the_iam_cli_branch_requests_enrichment_with_its_prediction_and_prints_the_video_line(operator_world, capsys):
    changes = [{"modelName": "Reference", "action": "create", "expected": reference_row("reference-vid-v1", address=VIDEO)}]

    class Client:
        endpoint = ENDPOINT_ANTH

    done = queue.request_for_created(Client(), changes, "references\tcreate-from-catalog")
    out = capsys.readouterr().out
    assert done.ok and "1 video needs a local run" in out
    (row,) = lane_rows(operator_world.table)
    assert queue.wants_enrichment(row)


@pytest.fixture
def operator_world(monkeypatch):
    table = FakeTable()
    table.put_item(router_config())
    monkeypatch.setattr("papyrus_content.user_auth_mode.user_auth_requested", lambda: False)
    monkeypatch.setattr("papyrus_content.monitoring_view.default_email_store_factory", lambda env: (lambda: TableViewStore(table, "hn")))
    return type("Operator", (), {"table": table})
