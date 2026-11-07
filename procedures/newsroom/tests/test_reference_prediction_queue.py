"""One Cyclotron prediction for a Reference created without one (src/papyrus_content/reference_prediction_queue.py, PPY-eac36e).

Offline: an in-memory monitoring table, the scripted machine API of the router tests, and an in-memory AppSync client. No AWS, no network, no model.
"""
import json
from unittest.mock import patch

import pytest

from papyrus_content import monitoring_router as mr
from papyrus_content import reference_prediction_queue as queue
from papyrus_content.monitoring_view import TableViewStore
from papyrus_content.reference_intake_validation import IntakeError
from procedures.newsroom.tests.test_monitoring_router import ENDPOINT, FakeTable, LabAppSync, go, router_config, setup_router

ENDPOINT_ANTH = ENDPOINT.replace("abc123", "api0")
CORPUS = "knowledge-corpus-anth-us"
URL = "https://example.org/pasted"


def reference_row(identifier="reference-user-intake-aaa-v1", **more):
    return {"id": identifier, "lineageId": identifier.removesuffix("-v1"), "versionNumber": 1, "versionState": "current", "corpusId": CORPUS,
            "sourceUri": URL, "title": "A pasted page", "curationStatus": "pending", "createdAt": "2026-11-05T10:00:00Z",
            "feedStateKey": f"{CORPUS}#unrated", "feedArrivalAt": "2026-11-05T10:00:00.000Z",
            "predictionSortKey": f"0.500000#2026-11-05T10:00:00.000Z#{identifier}", **more}


def request_of(row=None):
    row = row or reference_row()
    return {"referenceId": row["id"], "sourceUri": row["sourceUri"], "title": row["title"]}


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr("papyrus_content.records.upload_attachment_body", lambda client, expected, body: None)
    table = FakeTable()
    store, cyclotron = setup_router(table)
    client = LabAppSync(ENDPOINT_ANTH, CORPUS)
    client.rows[("Reference", reference_row()["id"])] = reference_row()
    queue_store = TableViewStore(table, "hn")

    def ask(references=None, **kwargs):
        return queue.queue_reference_predictions(queue_store, endpoint=ENDPOINT_ANTH, references=references or [request_of()], subject="user-intake", **kwargs)

    def drain(now=2000, **kwargs):
        return go(table, store, cyclotron, now=now, task="email-references", appsync=lambda endpoint: client, **kwargs)

    return type("World", (), {"table": table, "cyclotron": cyclotron, "client": client, "ask": staticmethod(ask), "drain": staticmethod(drain),
                              "queue_store": queue_store, "router_store": store})


def lane_rows(table):
    return [row for row in table.by_prefix("DISC#") if row.get("gsi1pk") == f"ROUTING#hn#{queue.LANE}"]


def reference(world, identifier="reference-user-intake-aaa-v1"):
    return world.client.rows[("Reference", identifier)]


def test_a_request_is_one_idempotent_row_in_its_own_lane_and_creates_nothing_else(world):
    first = world.ask()
    assert first["queued"] == 1 and first["alreadyQueued"] == 0
    (row,) = lane_rows(world.table)
    assert row["sourceType"] == "reference" and row["canonicalUrl"] == URL and row["predictFor"]["referenceId"] == request_of()["referenceId"]
    before = repr(sorted(world.table.items.items(), key=str))
    again = world.ask()
    assert again["queued"] == 0 and again["alreadyQueued"] == 1 and again["sourceIds"] == first["sourceIds"]
    assert repr(sorted(world.table.items.items(), key=str)) == before
    assert not [op for op in world.client.ops if op[0] in ("create", "update")]   # asking never touches the publication


@pytest.mark.parametrize("override,message", [({"decisions": "direct"}, "not enabled"), ({"mode": "dry-run"}, "not enabled"), ({"enabled": False}, "not enabled")])
def test_nothing_is_queued_for_a_monitor_the_cyclotron_does_not_decide_for(override, message):
    table = FakeTable()
    table.put_item(router_config(**override))
    with pytest.raises(IntakeError, match=message):
        queue.queue_reference_predictions(TableViewStore(table, "hn"), endpoint=ENDPOINT_ANTH, references=[request_of()], subject="s")
    assert not table.by_prefix("DISC#")


def test_an_unknown_publication_or_a_bad_reference_is_refused_and_nothing_is_queued(world):
    with pytest.raises(IntakeError, match="not served"):
        queue.queue_reference_predictions(world.queue_store, endpoint="https://zzz.appsync-api.us-east-1.amazonaws.com/graphql", references=[request_of()], subject="s")
    with pytest.raises(IntakeError):
        world.ask([{"referenceId": "", "sourceUri": URL, "title": "t"}])
    with pytest.raises(IntakeError):
        world.ask([{"referenceId": "reference-x", "sourceUri": "not a url", "title": "t"}])
    assert not world.table.by_prefix("DISC#")


def test_the_router_decides_a_queued_reference_once_and_records_it_like_a_delivery(world):
    world.cyclotron.confidence = {(mr.item_id_for("hn", world.ask()["sourceIds"][0]), "anth-us"): 0.9}
    result = world.drain()
    assert result["counts"]["predicted"] == 1 and result["counts"]["deliveryFailed"] == 0 and result["status"] == "completed"
    row = reference(world)
    assert row["predictedAcceptProbability"] == 0.9 and row["predictionDecidedAt"] and row["predictionSortKey"].startswith("0.900000#")
    assert row["curationStatus"] == "pending" and row["feedStateKey"] == f"{CORPUS}#unrated"   # no vote, no status change
    (relation,) = world.client.relations()
    metadata = json.loads(relation["metadata"])
    assert relation["subjectId"] == row["id"] and metadata["label"] == "include" and metadata["provenance"]["system"] == "cyclotron-lab"
    assert not lane_rows(world.table)   # settled: it left the lane
    assert len(world.cyclotron.posts()) == 1
    # a second run decides nothing and calls nothing
    again = world.drain(now=2100)
    assert again["counts"]["predicted"] == 0 and len(world.cyclotron.posts()) == 1


def test_deciding_sends_nothing_back_to_the_model(world):
    world.ask()
    world.drain()
    assert [call for call in world.cyclotron.calls if call[2] and call[2].get("operation") == "feedback"] == []
    assert all(call[2]["operation"] == "decide" for call in world.cyclotron.posts())


def test_an_exclude_decision_is_recorded_too_with_a_low_probability(world):
    item = mr.item_id_for("hn", world.ask()["sourceIds"][0])
    world.cyclotron.labels = {(item, "anth-us"): "exclude"}
    world.cyclotron.confidence = {(item, "anth-us"): 0.8}
    world.drain()
    assert reference(world)["predictedAcceptProbability"] == pytest.approx(0.2)
    assert json.loads(world.client.relations()[0]["metadata"])["label"] == "exclude"


def test_the_decision_input_is_the_title_and_address_only_with_no_page_fetch_and_no_summary_model(world):
    world.ask()
    for row in lane_rows(world.table):
        row["predictFor"].pop("enrich")   # a request queued before enrichment existed
    world.drain(enricher=object())   # an enricher that would explode if it were used
    (post,) = world.cyclotron.posts()
    values = post[2]["payload"]["item"]["values"]
    assert values["text"] == f"A pasted page\n{URL}" and "summary" not in values and values["source"] == "email"


def test_a_reference_that_already_has_a_prediction_is_not_decided_again(world):
    reference(world).update(predictedAcceptProbability=0.7, predictionDecidedAt="2026-11-05T09:00:00.000Z")
    world.ask()
    result = world.drain()
    assert world.cyclotron.posts() == [] and result["counts"]["predictionSkipped"] == 1 and result["counts"]["predicted"] == 0
    assert reference(world)["predictedAcceptProbability"] == 0.7
    assert not lane_rows(world.table)


def test_a_time_without_a_number_is_not_a_prediction_and_is_decided_and_given_its_number(world):
    reference(world).update(predictionDecidedAt="2026-11-05T09:00:00.000Z")   # hidden by the public pages: no finite predictedAcceptProbability
    world.ask()
    assert world.drain()["counts"]["predicted"] == 1
    row = reference(world)
    assert isinstance(row["predictedAcceptProbability"], float) and row["predictionDecidedAt"] != "2026-11-05T09:00:00.000Z"
    assert queue.has_real_prediction(row) and not queue.has_real_prediction({"predictionDecidedAt": "x", "predictedAcceptProbability": None})
    assert not queue.has_real_prediction({"predictedAcceptProbability": float("nan")})


def test_a_reference_with_a_decision_but_no_prediction_fields_gets_them_copied_without_asking_the_model(world):
    world.ask()
    # The same Reference was decided before (the by-hand sweep): a current relation, no fields on the row.
    world.drain()   # records a real decision + the fields
    first = dict(world.client.relations()[0])
    row = reference(world)
    for key in ("predictedAcceptProbability", "predictionDecidedAt"):
        row.pop(key)
    world.table.items.clear()
    world.table.put_item(router_config())
    world.ask()
    posts_before = len(world.cyclotron.posts())
    result = world.drain(now=3000)
    assert len(world.cyclotron.posts()) == posts_before and result["counts"]["predictionSkipped"] == 1
    assert reference(world)["predictedAcceptProbability"] is not None and reference(world)["predictionDecidedAt"]
    assert world.client.relations()[0]["id"] == first["id"]   # the decision is the one that was already there


def test_an_unreachable_cyclotron_keeps_the_reference_hidden_and_the_request_retried_with_backoff_until_it_answers(world):
    world.ask()
    world.cyclotron.post_override["anth-us"] = (409, {"detail": "publication criteria are pending"})
    waiting = world.drain()
    assert waiting["counts"]["predicted"] == 0 and waiting["counts"]["parked"] == 1
    assert "predictedAcceptProbability" not in reference(world)   # the Reference exists and has no prediction: it stays hidden
    (row,) = lane_rows(world.table)   # still queued
    assert row["sourceType"] == "reference"
    world.cyclotron.post_override.clear()
    assert world.drain(now=2005)["counts"]["predicted"] == 0   # inside its backoff: no call at all
    done = world.drain(now=2000 + 24 * 3600)
    assert done["counts"]["predicted"] == 1 and reference(world)["predictedAcceptProbability"] is not None
    assert not lane_rows(world.table)


def test_a_failed_recording_is_retried_and_finishes_the_rest_without_deciding_twice(world):
    world.ask()
    original = world.client.update_record
    calls = {"n": 0}

    def flaky(model, payload):
        if model == "Reference" and "predictedAcceptProbability" in payload and not calls["n"]:
            calls["n"] += 1
            raise RuntimeError("AppSync unavailable")
        return original(model, payload)

    world.client.update_record = flaky
    first = world.drain()
    assert first["counts"]["deliveryFailed"] == 1 and "predictedAcceptProbability" not in reference(world)
    assert len(world.client.relations()) == 1   # the relation was written before the failure
    second = world.drain(now=2000 + 24 * 3600)
    assert second["counts"]["predicted"] == 1 and reference(world)["predictedAcceptProbability"] is not None
    assert len(world.client.relations()) == 1 and len(world.cyclotron.posts()) == 1   # one decision, one relation


def test_a_missing_or_superseded_reference_is_refused_loudly_and_never_decided(world, capsys):
    gone = reference_row("reference-gone-v1")
    world.ask([request_of(gone)])
    result = world.drain()
    assert result["counts"]["refused"] == 1 and result["counts"]["predictionFailed"] == 1 and world.cyclotron.posts() == []
    assert '"referencePrediction": "refused"' in capsys.readouterr().out
    assert not lane_rows(world.table)
    old = reference_row("reference-old-v1", versionState="superseded", sourceUri=URL)
    world.client.rows[("Reference", old["id"])] = old
    world.ask([request_of(old)])
    second = world.drain(now=2100)
    assert second["counts"]["refused"] == 1 and second["counts"]["predictionFailed"] == 1 and world.cyclotron.posts() == []


def test_a_reference_in_another_corpus_or_with_another_address_is_not_decided(world):
    world.client.rows[("Reference", reference_row()["id"])]["corpusId"] = "knowledge-corpus-elsewhere"
    world.ask()
    assert world.drain()["counts"]["refused"] == 1 and world.cyclotron.posts() == []


def test_a_catalog_import_of_many_is_one_row_each_and_the_router_works_through_them_in_its_own_time(world):
    rows = [reference_row(f"reference-import-{n}-v1", sourceUri=f"https://example.org/p{n}", title=f"Paper {n}") for n in range(30)]
    for row in rows:
        world.client.rows[("Reference", row["id"])] = row
    answer = world.ask([request_of(row) for row in rows])
    assert answer["queued"] == 30 and len(lane_rows(world.table)) == 30
    done = world.drain(time_left=lambda: 1e9)
    assert done["status"] == "completed" and world.cyclotron.posts().__len__() == 30
    assert all(reference(world, row["id"]).get("predictedAcceptProbability") is not None for row in rows)
    assert not lane_rows(world.table)


def test_the_router_stops_at_its_time_budget_and_the_rest_wait_in_the_lane(world):
    rows = [reference_row(f"reference-import-{n}-v1", sourceUri=f"https://example.org/p{n}", title=f"Paper {n}") for n in range(4)]
    for row in rows:
        world.client.rows[("Reference", row["id"])] = row
    world.ask([request_of(row) for row in rows])
    done = world.drain(time_left=lambda: 1e9 if len(world.cyclotron.posts()) < 2 else 10)   # the run is out of time once two are decided
    predicted = [row for row in rows if reference(world, row["id"]).get("predictedAcceptProbability") is not None]
    assert len(predicted) == 2 and len(lane_rows(world.table)) == 2 and done["counts"]["predicted"] == 2
    assert world.drain(now=2100)["counts"]["predicted"] == 2 and not lane_rows(world.table)   # the next run finishes them: nothing was lost


def test_a_monitor_that_stopped_deciding_leaves_the_requests_waiting_not_decided_and_not_lost(world):
    world.ask()
    world.table.put_item(router_config(decisions="direct"))
    result = go(world.table, world.router_store, None, now=2000, task="email-references", appsync=lambda endpoint: world.client)
    assert result["counts"]["predictionsWaiting"] == 1 and world.cyclotron.posts() == []
    assert len(lane_rows(world.table)) == 1 and "predictedAcceptProbability" not in reference(world)


def test_an_email_import_in_its_lane_is_untouched_by_the_new_lane(world):
    world.ask()
    assert world.drain()["status"] == "completed"
    assert mr.selected_lane({"editorSelectedReference": {"x": 1}}) == "email-references"
    assert mr.selected_lane({"sourceType": "reference", "predictFor": {}}) == queue.LANE
    assert mr.selected_lane({"sourceType": "hn-rss"}) is None


# --- the callers ---------------------------------------------------------------------------------------------------------------------------------------

def test_the_lambda_that_creates_the_reference_queues_it_and_reports_a_failure_in_its_answer(world, capsys):
    created = {"ok": True, "references": [{"id": "reference-user-intake-aaa-v1", "lineageId": "reference-user-intake-aaa", "versionNumber": 1,
                                           "sourceUri": URL, "curationStatus": "pending"},
                                          {"id": "reference-other-v1", "sourceUri": "https://example.org/held", "curationStatus": "pending", "reusedExisting": True},
                                          {"id": "reference-voted-v1", "sourceUri": "https://example.org/voted", "curationStatus": "accepted"}]}
    arguments = {"items": [{"source_uri": URL, "title": "Typed by the editor", "ingestion_rationale": "r"}]}
    env = {"PAPYRUS_GRAPHQL_ENDPOINT": ENDPOINT_ANTH}
    ok = queue.queue_after_intake(created, arguments, env=env, store=world.queue_store)
    assert ok == {"requested": 2, "ok": True, "queued": 2, "alreadyQueued": 0, "videos": 0}   # the new Reference and the one that arrived already voted; not the reused one
    row = next(row for row in lane_rows(world.table) if row["predictFor"]["referenceId"] == "reference-user-intake-aaa-v1")
    assert row["title"] == "Typed by the editor"
    broken = queue.queue_after_intake(created, arguments, env={"PAPYRUS_GRAPHQL_ENDPOINT": "https://zzz.appsync-api.us-east-1.amazonaws.com/graphql"}, store=world.queue_store)
    assert broken["ok"] is False and "not served" in broken["error"]
    assert '"referencePrediction": "queue_failed"' in capsys.readouterr().out


def test_a_store_that_cannot_be_reached_is_reported_never_raised():
    class Down:
        pk = "MONITOR#hn"

        def get(self, sk):
            raise RuntimeError("table unavailable")

    answer = queue.queue_after_intake({"references": [{"id": "reference-a-v1", "sourceUri": URL, "curationStatus": "pending"}]}, {"items": []},
                                      env={"PAPYRUS_GRAPHQL_ENDPOINT": ENDPOINT_ANTH}, store=Down())
    assert answer["ok"] is False and "table unavailable" in answer["error"]


def test_an_import_with_nothing_new_asks_for_nothing():
    assert queue.queue_after_intake({"references": [{"id": "r-v1", "sourceUri": URL, "curationStatus": "pending", "reusedExisting": True}]}, {}, store=object()) == {
        "requested": 0, "ok": True}


class Graphql:
    def __init__(self, answer):
        self.answer, self.sent = answer, []

    def graphql(self, query, variables):
        self.sent.append((query, variables))
        if isinstance(self.answer, Exception):
            raise self.answer
        return {"monitoringQueueReferencePredictions": self.answer}


def test_a_signed_in_command_asks_the_site_and_reports_the_answer():
    client = Graphql(json.dumps({"queued": 2, "alreadyQueued": 1, "sourceIds": []}))
    done = queue.request_predictions_through_appsync(client, [request_of(), request_of(reference_row("reference-b-v1"))])
    assert done.ok and done.requested == 3
    assert json.loads(client.sent[0][1]["input"])["references"][0]["referenceId"] == request_of()["referenceId"]


@pytest.mark.parametrize("answer", [{"error": "queue_rejected", "message": "Cloud predictions are not enabled for this publication."},
                                    RuntimeError("Not Authorized"), None])
def test_a_refusal_or_a_failure_is_the_result_not_an_exception_and_names_what_to_do(answer):
    done = queue.request_predictions_through_appsync(Graphql(answer), [request_of()])
    assert not done.ok and done.error
    line = queue.request_line("references\tcreate-from-catalog", done)
    assert "NOT-REQUESTED" in line and "papyrus references queue-predictions" in line and "hidden" in line


def test_the_created_references_of_a_plan_are_the_only_ones_requested():
    changes = [{"modelName": "Reference", "action": "create", "expected": reference_row("reference-new-v1")},
               {"modelName": "Reference", "action": "update", "expected": reference_row("reference-old-v1")},
               {"modelName": "Reference", "action": "create", "expected": reference_row("reference-done-v1", predictionDecidedAt="2026-11-05T09:00:00.000Z", predictedAcceptProbability=0.6)},
               {"modelName": "Reference", "action": "create", "expected": reference_row("reference-voted-v1", curationStatus="accepted")},
               {"modelName": "Assignment", "action": "create", "expected": {"id": "assignment-1"}}]
    assert [item["referenceId"] for item in queue.references_created_by(changes)] == ["reference-new-v1", "reference-voted-v1"]   # a Reference created already voted still needs a prediction


def test_the_site_function_queues_for_editors_only_and_answers_a_rejection_as_data(world):
    from papyrus_content import monitoring_view as mv
    from procedures.newsroom.tests.test_reference_intake import ENV, IDENTITY
    env = {**ENV, "PAPYRUS_GRAPHQL_ENDPOINT": ENDPOINT_ANTH}
    event = {"fieldName": "monitoringQueueReferencePredictions", "arguments": {"input": json.dumps({"references": [request_of()]})},
             "identity": {**IDENTITY, "groups": ["editor"]}}
    with patch.dict("os.environ", env):   # the editor check reads the process environment, as the Lambda's is
        answer = mv.handle(event, env=env, store_factory=lambda monitor_id=None: world.queue_store, email_store_factory=lambda: world.queue_store)
    assert answer.get("queued") == 1, answer
    assert len(lane_rows(world.table)) == 1
    assert mv.handle({**event, "identity": {**IDENTITY, "groups": ["reader"]}}, env=env, email_store_factory=lambda: world.queue_store) == {"error": "forbidden"}
    with patch.dict("os.environ", env):
        bad = mv.handle({**event, "arguments": {"input": json.dumps({"references": [], "extra": 1})}}, env=env, email_store_factory=lambda: world.queue_store)
    assert bad["error"] == "queue_rejected"
    assert len(lane_rows(world.table)) == 1


# --- the commands ---------------------------------------------------------------------------------------------------------------------------------------

class Listing:
    """The prediction index, highest score first, one partition at a time (``iterate_newest_first``)."""
    endpoint = ENDPOINT_ANTH

    def __init__(self, rows):
        self.rows = rows
        self.asked = []

    def iterate_newest_first(self, index, key):
        self.asked.append((index, key))
        yield from (row for row in self.rows if row.get("feedStateKey") == key)


@pytest.fixture
def operator(world, monkeypatch):
    """An operator with AWS credentials: no signed-in session, the monitoring table reachable."""
    monkeypatch.setattr("papyrus_content.user_auth_mode.user_auth_requested", lambda: False)
    monkeypatch.setattr("papyrus_content.monitoring_view.default_email_store_factory", lambda env: (lambda: world.queue_store))
    return world


def test_the_by_hand_command_reads_the_prediction_index_once_and_queues_only_those_without_a_prediction(operator, monkeypatch, capsys):
    from papyrus_content import references_commands as commands
    unrated, rated = f"{CORPUS}#unrated", f"{CORPUS}#rated"
    rows = [reference_row("reference-a-v1", sourceUri="https://example.org/a", feedStateKey=unrated, predictionSortKey="0.500000#x"),
            reference_row("reference-b-v1", sourceUri="https://example.org/b", predictionDecidedAt="2026-11-05T09:00:00.000Z", predictedAcceptProbability=0.4,
                          feedStateKey=unrated, predictionSortKey="0.400000#x"),
            reference_row("reference-c-v1", sourceUri="https://example.org/c", versionState="superseded", feedStateKey=unrated, predictionSortKey="0.500000#x"),
            reference_row("reference-d-v1", sourceUri="https://example.org/d", curationStatus="accepted", feedStateKey=rated, predictionSortKey="0.500000#x")]
    client = Listing(rows)
    monkeypatch.setattr(commands, "create_authoring_client", lambda: (client, {}))
    commands.references_queue_predictions(["--site", "anth-us", "--dry-run"])
    assert "without-prediction\t2\tdry-run" in capsys.readouterr().out and not lane_rows(operator.table)
    commands.references_queue_predictions(["--site", "anth-us"])
    out = capsys.readouterr().out
    assert "prediction\trequested\t2" in out
    assert client.asked == [("referencesByFeedStateAndPrediction", unrated), ("referencesByFeedStateAndPrediction", rated)] * 2
    assert sorted(row["predictFor"]["referenceId"] for row in lane_rows(operator.table)) == ["reference-a-v1", "reference-d-v1"]   # an accepted one too
    commands.references_queue_predictions(["--site", "anth-us"])   # again: nothing new is queued, nothing breaks
    assert len(lane_rows(operator.table)) == 2


def test_the_enrichment_backfill_queues_enrich_only_requests_for_uncaptured_references_and_is_idempotent(operator, monkeypatch, capsys):
    from papyrus_content import references_commands as commands
    unrated = f"{CORPUS}#unrated"
    rows = [reference_row("reference-a-v1", sourceUri="https://example.org/a", feedStateKey=unrated),
            reference_row("reference-b-v1", sourceUri="https://example.org/b", feedStateKey=unrated, captureState="full"),
            reference_row("reference-c-v1", sourceUri="https://www.youtube.com/watch?v=dQw4w9WgXcQ", feedStateKey=unrated, predictedAcceptProbability=0.4)]
    monkeypatch.setattr(commands, "create_authoring_client", lambda: (Listing(rows), {}))
    commands.references_queue_enrichment(["--site", "anth-us", "--dry-run"])
    out = capsys.readouterr().out
    assert "needing-enrichment\t2\tdry-run" in out and "1 video needs a local run" in out and not lane_rows(operator.table)
    commands.references_queue_enrichment(["--site", "anth-us"])
    assert "enrichment\trequested\t2" in capsys.readouterr().out
    assert sorted(row["predictFor"]["referenceId"] for row in lane_rows(operator.table)) == ["reference-a-v1", "reference-c-v1"]
    assert all(row["predictFor"]["enrichOnly"] for row in lane_rows(operator.table))
    commands.references_queue_enrichment(["--site", "anth-us"])
    assert len(lane_rows(operator.table)) == 2


def test_the_by_hand_command_fails_loudly_when_the_requests_cannot_be_made(monkeypatch, capsys):
    from papyrus_content import references_commands as commands
    monkeypatch.setattr("papyrus_content.user_auth_mode.user_auth_requested", lambda: False)
    monkeypatch.setattr("papyrus_content.monitoring_view.default_email_store_factory", lambda env: (lambda: None))
    monkeypatch.setattr(commands, "create_authoring_client", lambda: (Listing([reference_row(feedStateKey=f"{CORPUS}#unrated", predictionSortKey="0.500000#x")]), {}))
    with pytest.raises(ValueError, match="NOT-REQUESTED"):
        commands.references_queue_predictions(["--site", "anth-us"])
    assert "NOT-REQUESTED" in capsys.readouterr().out


def test_an_operator_command_that_creates_references_queues_them_and_prints_one_line(operator, capsys):
    changes = [{"modelName": "Reference", "action": "create", "expected": reference_row()}]

    class Client:
        endpoint = ENDPOINT_ANTH

    done = queue.request_for_created(Client(), changes, "references\tcreate-from-catalog")
    assert done.ok and "prediction\trequested\t1" in capsys.readouterr().out
    assert len(lane_rows(operator.table)) == 1
    assert queue.request_for_created(Client(), [], "x") is None


def test_a_route_that_cannot_reach_the_table_says_so_instead_of_raising(monkeypatch):
    monkeypatch.setattr("papyrus_content.user_auth_mode.user_auth_requested", lambda: False)
    monkeypatch.setattr("papyrus_content.monitoring_view.default_email_store_factory", lambda env: (lambda: (_ for _ in ()).throw(RuntimeError("no credentials"))))
    done = queue.request_predictions(object(), [request_of()])
    assert not done.ok and "no credentials" in done.error
