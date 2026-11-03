"""The router's hourly suggest-backlog task (src/papyrus_content/monitoring_router.py ``suggest_backlog``, src/papyrus_content/monitoring_vectors.py
``run_suggest_backlog``, features_backend/monitoring-suggest-backlog.feature): the vector pass's suggestions with no index sync, no embedding and no model call, one
invocation and one lock per publication. The index, the backends and the clock are fakes; nothing here reaches the network."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from functools import partial
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_monitoring_router as tr  # noqa: E402
import test_monitoring_stories as tms  # noqa: E402
import test_monitoring_vectors as tv  # noqa: E402
from ideas_fixtures import NOW  # noqa: E402
from papyrus_content import monitoring_router as mr  # noqa: E402
from papyrus_content import monitoring_vectors as vectors  # noqa: E402
from papyrus_content.monitoring_router import run_router  # noqa: E402

INDEXED = {**tms.SINGLE_ITEM_ONLY, "vectorIndexArn": tv.ARN, "storageBucketName": tv.BUCKET}


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    monkeypatch.setattr(vectors, "s3vectors_client_missing_reason", lambda region_name=None: None)


def fake_pass(monkeypatch, pass_):
    monkeypatch.setattr(mr, "run_suggest_backlog", partial(vectors.run_suggest_backlog, suggester=pass_.suggester, provider_for=lambda arn: ("provider", arn),
                                                         calibration_loader=lambda client: None, workers=1))


def run(store, client, monkeypatch, pass_, *, publication_id=tms.PUBLICATION, time_left=lambda: 600, fan_out=None, task="suggest-backlog"):
    fake_pass(monkeypatch, pass_)
    out = io.StringIO()
    with redirect_stdout(out):
        result = run_router(store, "hn", now=NOW.timestamp(), task=task, appsync=lambda endpoint: client, deliver=tr.Delivery(), time_left=time_left,
                            publication_id=publication_id, fan_out=fan_out)
    lines = [json.loads(line) for line in out.getvalue().splitlines() if line.startswith('{"suggestBacklog"')]
    return result, lines


def test_the_task_suggests_for_the_references_with_a_vector_in_order_writes_the_saved_place_and_the_owed_rows_and_logs_what_is_left(monkeypatch):
    table, store = tms.router(settings={tms.PUBLICATION: INDEXED})
    client = tv.AcceptedClient([tv.accepted(1, "2026-10-30T10:00:00Z"), tv.accepted(2, "2026-10-30T11:00:00Z"), tv.accepted(3, "2026-10-30T12:00:00Z")])
    pass_ = tv.Pass(no_vector={"ref-2"})
    result, lines = run(store, client, monkeypatch, pass_)
    assert pass_.order == ["suggest:ref-3", "suggest:ref-2", "suggest:ref-1"] and pass_.sync_calls == []   # no index sync, whatever the key
    (line,) = lines
    assert (line["status"], line["suggestionsWritten"], line["suggestionsRemaining"], line["awaitingIndex"], line["costUsd"]) == ("complete", 4, 1, 1, 0.0)
    assert {"planSeconds", "suggestSeconds"} <= set(line["timings"]) and "suggestionsPerSecond" in line
    assert result["suggestBacklog"][tms.PUBLICATION]["suggestionsWritten"] == 4
    place = json.loads(table.get_item({"pk": "MONITOR#hn", "sk": vectors.watermark_sort_key(tms.PUBLICATION)})["Item"]["watermark"])
    assert place["accepted"] == {"high": "2026-10-30T12:00:00Z#ref-3", "low": "2026-10-30T10:00:00Z#ref-1"}
    owed = [item for key, item in table.items.items() if key[1].startswith(vectors.owed_prefix(tms.PUBLICATION))]
    assert len(owed) == 1 and json.loads(owed[0]["entries"])["lineage-2"]["r"] is None


def test_the_task_needs_no_embedding_key_and_asks_no_model_and_the_handler_does_not_read_either():
    import inspect

    source = inspect.getsource(mr.handler)
    assert 'event.get("task") == "monitor-stories" and event.get("publicationId")' in source   # the model key and the OpenAI key are read for monitor-stories only
    assert "suggest-backlog" not in source.split("story_transport =")[1].split("cap =")[0]


def test_with_no_publication_named_the_task_starts_one_run_for_each_publication_with_an_index_and_suggestions_on_and_takes_no_lock(monkeypatch):
    table, store = tms.router(("a-site", "no-index", "no-suggestions", "disabled", "b-site"), {
        "a-site": INDEXED, "no-index": tms.SINGLE_ITEM_ONLY, "no-suggestions": {**INDEXED, "suggestions": {"enabled": False}}, "disabled": {**INDEXED, "enabled": False}, "b-site": INDEXED})
    started = []
    result, _ = run(store, tv.AcceptedClient([]), monkeypatch, tv.Pass(), publication_id=None, fan_out=started.append)
    assert started == ["a-site", "b-site"] and result["status"] == "fanned-out"
    assert not [key for key in table.items if key[1].startswith(("LOCK#", "ROUTERUN#"))]


def test_a_publication_run_takes_its_own_lock_and_a_second_run_of_the_same_publication_is_locked_while_the_other_tasks_are_not(monkeypatch):
    table, store = tms.router(settings={tms.PUBLICATION: INDEXED})
    assert store.acquire_router_lock("hn", "someone", now=NOW.timestamp(), sk=f"LOCK#suggest-backlog#{tms.PUBLICATION}")
    pass_ = tv.Pass()
    result, lines = run(store, tv.AcceptedClient([tv.accepted(1, "2026-10-30T10:00:00Z")]), monkeypatch, pass_)
    assert result["status"] == "locked" and pass_.order == [] and lines == []
    assert store.acquire_router_lock("hn", "route", now=NOW.timestamp())   # the routing lock and the monitor-stories lock are other rows
    assert store.acquire_router_lock("hn", "stories", now=NOW.timestamp(), sk=f"LOCK#monitor-stories#{tms.PUBLICATION}")


def test_an_unlisted_publication_is_refused_and_nothing_runs(monkeypatch):
    table, store = tms.router(settings={tms.PUBLICATION: INDEXED})
    pass_ = tv.Pass()
    result, _ = run(store, tv.AcceptedClient([]), monkeypatch, pass_, publication_id="nowhere")
    assert result["status"] == "error" and "nowhere" in result["reason"] and pass_.order == []


def test_a_dry_run_router_and_a_publication_without_an_index_write_nothing(monkeypatch):
    table, store = tms.router(settings={tms.PUBLICATION: tms.SINGLE_ITEM_ONLY})
    pass_ = tv.Pass()
    result, lines = run(store, tv.AcceptedClient([tv.accepted(1, "2026-10-30T10:00:00Z")]), monkeypatch, pass_)
    assert pass_.order == [] and lines[0]["status"] == "skipped" and result["suggestBacklog"][tms.PUBLICATION]["status"] == "skipped"
    table2, store2 = tms.router(settings={tms.PUBLICATION: INDEXED})
    config = table2.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"]
    table2.put_item({**config, "mode": "dry-run"})
    result, lines = run(store2, tv.AcceptedClient([tv.accepted(1, "2026-10-30T10:00:00Z")]), monkeypatch, pass_)
    assert pass_.order == [] and lines == [] and result["suggestBacklog"] == {}


def test_the_run_stops_with_the_time_left_for_finishing_and_the_next_hour_goes_on_from_the_saved_place(monkeypatch):
    table, store = tms.router(settings={tms.PUBLICATION: INDEXED})
    rows = [tv.accepted(number, f"2026-10-{number:02d}T10:00:00Z") for number in range(1, 6)]
    left = [600]

    class Slow(tv.Pass):
        def suggester(self, client, provider, reference_id, **options):
            left[0] -= 150   # each suggestion uses 150 seconds of the 600
            return super().suggester(client, provider, reference_id, **options)

    first = Slow()
    result, lines = run(store, tv.AcceptedClient(rows), monkeypatch, first, time_left=lambda: left[0])
    assert lines[0]["status"] == "stopped" and lines[0]["stoppedBy"] == "time" and lines[0]["suggestionsRemaining"] == 1   # 600 - 4 x 150 = 0: it looked at the time before each suggestion and kept 120 seconds to finish
    left[0] = 600
    second = tv.Pass()
    result, lines = run(store, tv.AcceptedClient(rows), monkeypatch, second, time_left=lambda: left[0])
    assert lines[0]["suggestionsRemaining"] == 0 and sorted(first.order + second.order) == sorted(f"suggest:ref-{n}" for n in range(1, 6))   # each once, none twice


def test_the_stack_schedules_the_task_every_hour_for_the_shared_monitor_and_for_distinctive_mark_without_retries_and_adds_no_permission():
    resources = tr._template()["Resources"]
    inputs = {name: json.loads(resources[name]["Properties"]["Target"]["Input"]) for name in ("SuggestBacklogSchedule", "DistinctiveSuggestBacklogSchedule")}
    assert inputs == {"SuggestBacklogSchedule": {"task": "suggest-backlog", "monitorId": "hn"}, "DistinctiveSuggestBacklogSchedule": {"task": "suggest-backlog", "monitorId": "web-distinctive"}}
    for name in inputs:
        properties = resources[name]["Properties"]
        assert properties["ScheduleExpression"].endswith("* * * ? *)") and properties["Target"]["RetryPolicy"]["MaximumRetryAttempts"] == 0
        assert properties["Target"]["RoleArn"] == ("GetAtt", "RouterScheduleRole.Arn")   # the role the other hourly tasks use: it may invoke the router and nothing else
    minutes = {int(resources[name]["Properties"]["ScheduleExpression"].split("(")[1].split()[0]) for name in inputs}
    assert minutes == {44, 14}   # neither overlaps the daily monitor-stories run at 07:30 (up to ten minutes) of the same publications
    # nothing is added to any IAM policy: the router role already reads and writes the monitoring table and the sites' indexes and APIs
    actions = {action for policy in resources["RouterRole"]["Properties"]["Policies"] for statement in policy["PolicyDocument"]["Statement"] for action in
               ([statement["Action"]] if isinstance(statement["Action"], str) else statement["Action"])}
    assert {"dynamodb:Query", "dynamodb:PutItem", "dynamodb:GetItem"} <= actions

