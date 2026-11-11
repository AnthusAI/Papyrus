"""The monitor-stories queue: the daily task plans, a worker drafts one step per message (src/papyrus_content/ideas/story_plan.py,
features_backend/monitoring-stories-queue.feature). The model, the pages, the backends, the queue and the clock are fakes; nothing here reaches the network."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_monitoring_router as tr  # noqa: E402
from ideas_fixtures import NOW  # noqa: E402
from test_monitor_stories import pages  # noqa: E402
from test_monitoring_packs import PACKS_ON, FilingRecorder, RouterModel, pack_world  # noqa: E402
from test_monitoring_stories import PUBLICATION, fake_idea_sink, iam_auth, quiet_gate, router  # noqa: E402,F401  (the autouse fixtures of the daily task's tests)

from papyrus_content.ideas import connections as connection_rules, story_plan  # noqa: E402
from papyrus_content.ideas.items import ItemStore  # noqa: E402
from papyrus_content.ideas.synthesis import SynthesisError  # noqa: E402
from fake_client import FakeAuthoringClient  # noqa: E402
from papyrus_content.monitoring_router import handle_story_queue, is_story_queue_event, run_router  # noqa: E402

QUEUE_URL = "https://sqs.example/papyrus-monitoring-stories.fifo"


class FakeSqs:
    """Records what is sent to the story queue."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_message_batch(self, QueueUrl, Entries):
        assert QueueUrl == QUEUE_URL
        self.sent += [{"body": json.loads(entry["MessageBody"]), "group": entry["MessageGroupId"], "dedup": entry["MessageDeduplicationId"]} for entry in Entries]
        return {"Successful": [{"Id": entry["Id"]} for entry in Entries]}


def plan(store, client, sqs, *, now=NOW, time_left=lambda: 1e9):
    """The daily task for the example publication, with the story queue; returns the log lines by name."""
    endpoints = {tr.ENDPOINT.replace("abc123", "api0"): client}
    out = io.StringIO()
    with redirect_stdout(out):
        result = run_router(store, "hn", now=now.timestamp(), task="monitor-stories", appsync=lambda endpoint: endpoints[endpoint], deliver=tr.Delivery(),
                            time_left=time_left, publication_id=PUBLICATION, story_queue=(sqs, QUEUE_URL), story_transport=None)
    lines = [json.loads(line) for line in out.getvalue().splitlines() if line.startswith('{"monitorStories"')]
    return result, {line["publicationId"]: line for line in lines}


def event_for(messages, *, receives=1):
    return {"Records": [{"eventSource": "aws:sqs", "messageId": f"m-{number}", "body": json.dumps(message["body"]), "attributes": {"ApproximateReceiveCount": str(receives)}}
                        for number, message in enumerate(messages)]}


def work(store, client, model, sqs_messages, *, receives=1, fetch=None):
    """Hands the messages to the story worker one at a time (a FIFO queue with one group does the same); returns the log lines and the failures."""
    endpoints = {tr.ENDPOINT.replace("abc123", "api0"): client}
    out, failures = io.StringIO(), []
    with redirect_stdout(out):
        for message in sqs_messages:
            response = handle_story_queue(store, event_for([message], receives=receives), appsync=lambda endpoint: endpoints[endpoint], transport=model, explorer=None,
                                          fetch=fetch or pages(1, 2), gate_for=lambda client: __import__("test_idea_items").FakeGate())
            failures += response["batchItemFailures"]
    return [json.loads(line) for line in out.getvalue().splitlines() if line.startswith("{")], failures


@pytest.fixture
def world_of_two(monkeypatch):
    """A site with one context pack and one single item that the signals single out, and the recorder that stands in for filing a pack idea."""
    filing = FilingRecorder(monkeypatch)
    return pack_world(2, lively=(1,)), filing


def test_the_daily_task_only_plans_it_queues_each_step_and_asks_the_model_for_nothing(world_of_two):
    client, filing = world_of_two
    table, store = router(settings={PUBLICATION: PACKS_ON})
    sqs = FakeSqs()
    model = RouterModel()
    result, lines = plan(store, client, sqs)
    line = lines[PUBLICATION]
    assert line["status"] == "planned" and line["drafted"] == 0 and line["stoppedBy"] is None
    assert line["planned"]["steps"] == 2 and (line["planned"]["packs"], line["planned"]["items"]) == (1, 1) and line["planned"]["queued"] == 2
    assert [message["body"]["step"] for message in sqs.sent] == [1, 2]
    assert {message["group"] for message in sqs.sent} == {PUBLICATION}   # one message group per publication: its steps run one at a time, in order
    assert len({message["dedup"] for message in sqs.sent}) == 2
    assert model.order == [] and not filing.filed and not client.filed and not client.reviews   # nothing was drafted, filed or reviewed by the plan


def test_each_step_is_drafted_by_its_own_invocation_and_the_plan_ends_with_one_review_and_one_summary(world_of_two):
    client, filing = world_of_two
    table, store = router(settings={PUBLICATION: PACKS_ON})
    sqs = FakeSqs()
    model = RouterModel()
    plan(store, client, sqs)
    lines, failures = work(store, client, model, sqs.sent)
    assert not failures
    assert model.order == ["pack", "item"]   # the plan's order: the acceptance pack is more surprising than the item
    assert len(filing.filed) == 2 and len(client.filed) == 1
    steps = [line for line in lines if "monitorStoriesStep" in line]
    assert [(line["step"], line["kind"], line["monitorStoriesStep"], line["drafted"]) for line in steps] == [(1, "pack", "drafted", 2), (2, "item", "drafted", 1)]
    [finished] = [line for line in lines if line.get("monitorStories") == "finished"]
    assert (finished["steps"], finished["drafted"], finished["failedSteps"], finished["status"]) == (2, 3, 0, "complete")
    assert len(client.reviews) == 1   # one soft review for the plan, whatever number of steps filed ideas
    [review] = client.reviews.values()
    links = json.loads(review["links"])
    assert len(links) == 3 and review["reason"] == "3 new monitor story drafts to review" and review["id"].startswith("rr-batch-monitor-stories-run-")


def test_a_redelivered_step_is_not_drafted_twice(world_of_two):
    client, filing = world_of_two
    table, store = router(settings={PUBLICATION: PACKS_ON})
    sqs = FakeSqs()
    model = RouterModel()
    plan(store, client, sqs)
    work(store, client, model, sqs.sent)
    asked = len(model.order)
    lines, failures = work(store, client, model, sqs.sent)
    assert len(model.order) == asked and not failures and [line["storyStep"] for line in lines if "storyStep" in line] == ["already", "already"]


def test_a_failed_step_is_tried_again_by_the_queue_and_the_work_of_the_others_is_kept(world_of_two):
    client, filing = world_of_two
    table, store = router(settings={PUBLICATION: PACKS_ON})
    sqs = FakeSqs()
    model = RouterModel()
    plan(store, client, sqs)

    class Down(RouterModel):
        broken = True

        def __call__(self, url, headers, payload):
            if self.broken and payload["instructions"].startswith("You propose story ideas for a publication from a theme"):
                raise SynthesisError("the model is overloaded")
            return super().__call__(url, headers, payload)

    flaky = Down()
    lines, failures = work(store, client, flaky, sqs.sent)
    assert [failure["itemIdentifier"] for failure in failures] == ["m-0"]   # the pack's step is delivered again; the item's step was not held up by it
    assert len(client.filed) == 1 and not filing.filed
    flaky.broken = False
    lines, failures = work(store, client, flaky, sqs.sent[:1], receives=2)
    assert not failures and len(filing.filed) == 2
    assert any(line.get("monitorStories") == "finished" for line in lines)


def test_a_step_that_fails_its_last_try_leaves_a_record_so_the_plan_still_finishes(world_of_two):
    client, filing = world_of_two
    table, store = router(settings={PUBLICATION: PACKS_ON})
    sqs = FakeSqs()
    plan(store, client, sqs)

    class Down(RouterModel):
        def __call__(self, url, headers, payload):
            if payload["instructions"].startswith("You propose story ideas for a publication from a theme"):
                raise SynthesisError("the model is overloaded")
            return super().__call__(url, headers, payload)

    lines, failures = work(store, client, Down(), sqs.sent, receives=story_plan.MAXIMUM_RECEIVES)
    assert [failure["itemIdentifier"] for failure in failures] == ["m-0"]   # the queue parks it in the dead-letter queue
    [finished] = [line for line in lines if line.get("monitorStories") == "finished"]
    assert finished["status"] == "complete_with_failures" and finished["failedSteps"] == 1 and finished["drafted"] == 1


def test_the_next_days_task_waits_for_a_plan_that_is_still_running_and_then_plans_only_what_remains(world_of_two):
    client, filing = world_of_two
    table, store = router(settings={PUBLICATION: PACKS_ON})
    sqs = FakeSqs()
    plan(store, client, sqs)
    _, lines = plan(store, client, sqs, now=NOW + timedelta(days=1))
    assert lines[PUBLICATION]["status"] == "waiting" and lines[PUBLICATION]["plan"] == {"planId": lines[PUBLICATION]["plan"]["planId"], "total": 2, "done": 0}
    assert len(sqs.sent) == 2   # nothing was queued twice
    work(store, client, RouterModel(), sqs.sent)
    again = FakeSqs()
    _, lines = plan(store, client, again, now=NOW + timedelta(days=1))
    assert lines[PUBLICATION]["status"] == "planned"
    assert [message["body"]["step"] for message in again.sent] == [1]   # the item is drafted (a story draft cites it): only the pack is offered again
    first = store.get_any("hn", story_plan.entry_key(PUBLICATION, lines[PUBLICATION]["planned"]["planId"], 1))
    assert first["kind"] == "pack" 


def test_a_quiet_site_plans_nothing_and_finishes_at_once():
    table, store = router(settings={PUBLICATION: PACKS_ON})
    sqs = FakeSqs()
    client = pack_world(0, burst=0)
    _, lines = plan(store, client, sqs)
    assert lines[PUBLICATION]["planned"]["steps"] == 0 and not sqs.sent
    assert store.get_any("hn", story_plan.pointer_key(PUBLICATION))["finalized"] is True   # the next day's task is not held up by an empty plan


def test_the_vector_pass_runs_even_when_the_plan_is_waiting(world_of_two, monkeypatch):
    client, filing = world_of_two
    table, store = router(settings={PUBLICATION: PACKS_ON})
    plan(store, client, FakeSqs())
    ran = []
    import papyrus_content.monitoring_vectors as vectors

    real = vectors.run_vector_pass
    monkeypatch.setattr(vectors, "run_vector_pass", lambda *args, **kwargs: ran.append(1) or real(*args, **kwargs))
    plan(store, client, FakeSqs(), now=NOW + timedelta(days=1))
    assert ran


def test_a_router_with_no_story_queue_still_drafts_in_process(world_of_two):
    client, filing = world_of_two
    table, store = router(settings={PUBLICATION: PACKS_ON})
    out = io.StringIO()
    endpoints = {tr.ENDPOINT.replace("abc123", "api0"): client}
    from functools import partial

    from papyrus_content.monitoring_stories import run_publication

    with redirect_stdout(out):
        run_router(store, "hn", now=NOW.timestamp(), task="monitor-stories", appsync=lambda endpoint: endpoints[endpoint], deliver=tr.Delivery(), publication_id=PUBLICATION,
                   story_transport=RouterModel(), story_drafter=partial(run_publication, fetch=pages(1, 2), explorer=None))
    line = next(json.loads(l) for l in out.getvalue().splitlines() if l.startswith('{"monitorStories"'))
    assert line["drafted"] == 3 and line["status"] == "complete"


# --- what a step carries ---------------------------------------------------------------------------------------------


def test_a_pack_an_item_and_its_connections_survive_the_trip_through_the_plan(world_of_two):
    from papyrus_content.ideas.context import load_context
    from papyrus_content.ideas.signal_queue import prepare_signal_run
    from ideas_fixtures import NOW as now

    client, _ = world_of_two
    run = prepare_signal_run(client, site=PUBLICATION, context=load_context(client, now=now), now=now, signals=None, single_items=True)
    pack = run.packs[0]
    assert story_plan.pack_from_json(json.loads(json.dumps(story_plan.pack_to_json(pack)))) == pack
    neighbour = connection_rules.Neighbour("ref-2", "Another", "https://x.example/a", "2026-10-01", "A summary.", "confirmed", None, "They share a method.")
    connections = connection_rules.build_connections("Worth following.", [{"author": "staff", "date": "2026-10-02", "text": "A comment."}], [neighbour], suggested_links=2, stars=4)
    assert story_plan.connections_from_json(json.loads(json.dumps(story_plan.connections_to_json(connections)))) == connections
    assert story_plan.decode(story_plan.encode({"a": [1, "é"]})) == {"a": [1, "é"]}


# --- the filing error ------------------------------------------------------------------------------------------------


def test_linking_the_references_of_a_new_idea_does_not_depend_on_the_lineage_index_having_caught_up():
    """The index is eventually consistent: asked for just after the story was created it can answer with nothing, which raised 'No story found for lineage'."""
    from papyrus_content.ideas.items import file_idea_item
    from test_idea_items import draft
    from test_story_from_reference import backend, reader
    from test_story_from_reference import NOW as when

    class LaggingIndex:
        def __init__(self, inner) -> None:
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def list_by_index(self, index, key):
            return [] if index == "itemsByLineageAndVersion" else self.inner.list_by_index(index, key)

    inner = backend()
    result = file_idea_item(LaggingIndex(inner), draft(), now=when, source_text_reader=reader)
    assert result["created"] and result["linked"] == ["reference-clef"]
    assert inner.tables["SemanticRelation"]


def test_a_story_message_is_told_from_a_suggestion_message():
    story = {"Records": [{"eventSource": "aws:sqs", "body": json.dumps(story_plan.step_message("hn", "p", "plan", 1))}]}
    suggestion = {"Records": [{"eventSource": "aws:sqs", "body": json.dumps({"v": 1, "monitorId": "hn", "publicationId": "p", "referenceLineageId": "r", "contentHash": "h"})}]}
    assert is_story_queue_event(story) and not is_story_queue_event(suggestion) and not is_story_queue_event({"task": "monitor-stories"})


# --- the worker's grants -------------------------------------------------------------------------------------------------


def story_worker_policy():
    import re

    text = (Path(__file__).resolve().parents[3] / "infra" / "monitoring" / "papyrus-monitoring.yaml").read_text()
    start = text.index("  StoryWorkerRole:")
    role = text[start:text.index("\n\n  StoryWorkerFunction:", start)]
    return {(kind, field) for kind, field in re.findall(r"apis/\*/types/(Query|Mutation)/fields/(\w+)\"", role)}


FILING_AND_GATE = {("Query", name) for name in ("getItem", "getPublishedItem", "getReference", "getSemanticRelation", "itemByTenantSlug", "listItemsByLineageAndVersion", "listNewsroomSections",
                                                "listReferencesByLineageAndVersion", "getEditorialCheckSettings", "getEditorialContext", "getEditorialCheckRun", "listEditorialFeedbacks",
                                                "listEditorialPolicies", "getReviewRequest", "listItemsByParentAndOrder", "listAssignmentsByItemLineageAndCreatedAt",
                                                "listReferenceAttachmentsByReferenceLineageAndSortKey")} | {
    ("Mutation", name) for name in ("createItem", "updateItem", "createSemanticRelation", "updateSemanticRelation", "createEditorialCheckRun", "updateEditorialCheckRun",
                                    "createReviewRequest", "updateReviewRequest")}
SMALL_CONFIGURATION_TABLES = {"NewsroomSection"}   # the section vocabulary: a handful of rows, granted to the worker as listNewsroomSections


class StrictStepClient(FakeAuthoringClient):
    """The site's backend as a step sees it, with the real ``ItemStore`` and filing code on top: a table of tables that holds a lot of other Items, and that REFUSES any
    read of a whole table (``list_records``) apart from the small configuration tables, so a step that scans the site fails here as it fails with the worker's role."""

    def list_records(self, model_name):
        assert model_name in SMALL_CONFIGURATION_TABLES, f"a step listed the whole {model_name} table"
        return super().list_records(model_name)

    def list_published_item_summaries(self):
        raise AssertionError("a step listed every published item")


def many_other_items(count=120):
    """Stories people wrote, ideas the pipeline made and checklist steps, in every stage: the table a step must not read."""
    stages = ("idea", "reporting", "copywriting", "published", "spiked", "held")
    rows = []
    for number in range(count):
        rows.append({"id": f"item-other-{number}-v1", "lineageId": f"item-other-{number}", "versionState": "current", "versionNumber": 1, "type": "article",
                     "stage": stages[number % len(stages)], "title": f"Another story {number}", "status": "draft", "section": "analysis",
                     "frontMatterYaml": "title: Another\n" if number % 2 else "generated:\n  origin: monitor\n  targets: []\n"})
    rows.append({"id": "item-subtask-1-v1", "lineageId": "item-subtask-1", "versionState": "current", "versionNumber": 1, "type": "sub-task", "stage": "idea", "title": "A step"})
    return rows


def strict_world_of(world):
    """A StrictStepClient holding the monitored world's References, its sections and many other Items."""
    client = StrictStepClient()
    client.tables["Reference"] = {row["id"]: row for row in world.references}
    client.tables["NewsroomSection"] = {section["id"]: dict(section) for section in world.sections}
    client.tables["Item"] = {row["id"]: row for row in many_other_items()}
    return client


@pytest.fixture
def real_filing(monkeypatch):
    """The step files through the real ItemStore and the real ``file_idea_item`` (the daily tests' autouse fixtures replace both with recording doubles, which is how the
    scan of the Item table went unseen)."""
    monkeypatch.setattr("papyrus_content.ideas.items.ItemStore", ItemStore)


def planned_world():
    """The daily task's plan for a pack and a single item (made with the recording doubles, as the daily task's own tests do), and the steps it queued."""
    world = pack_world(2, lively=(1,))
    table, store = router(settings={PUBLICATION: PACKS_ON})
    sqs = FakeSqs()
    plan(store, world, sqs)
    return world, store, sqs


def test_a_step_never_lists_a_table_and_the_worker_role_grants_every_field_it_asks_for(monkeypatch):
    from field_recorder import FieldRecorder

    world, store, sqs = planned_world()
    monkeypatch.setattr("papyrus_content.ideas.items.ItemStore", ItemStore)
    client = strict_world_of(world)
    recorder = FieldRecorder(client)
    lines, failures = work(store, recorder, RouterModel(), sqs.sent)
    assert not failures, failures
    steps = [line for line in lines if "monitorStoriesStep" in line]
    assert [(line["kind"], line["monitorStoriesStep"]) for line in steps] == [("pack", "drafted"), ("item", "drafted")]   # the whole path ran: read, dedupe, filing, linking
    filed = [row for row in client.tables["Item"].values() if row["id"].startswith("item-idea-")]
    assert len(filed) == 3 and all(row["stage"] == "idea" for row in filed)   # two ideas from the pack and one from the item
    assert not any(call[0] == "list" and call[1] == "Item" for call in client.calls)
    assert not set(recorder.unbounded) - SMALL_CONFIGURATION_TABLES, recorder.unbounded
    granted = story_worker_policy()
    assert recorder.fields <= granted, sorted(recorder.fields - granted)
    assert not {name for _, name in recorder.fields} & {"listItems", "listItemsByStageAndUpdatedAt"}   # nor does it read the site's stories by stage: the plan handed it the ideas
    assert FILING_AND_GATE <= granted, sorted(FILING_AND_GATE - granted)
    assert not {field for _, field in granted} & {"listReferences", "listItems", "listReviewRequests", "listMessageThreads", "listSemanticNodes", "listReferencesByCurationStatusKeyAndUpdatedAt"}


def test_a_store_given_its_plans_ideas_reads_nothing_to_know_the_existing_ideas():
    client = StrictStepClient()
    client.tables["Item"] = {row["id"]: row for row in many_other_items()}
    ideas = [{"id": "item-idea-1", "title": "An idea", "summary": "", "state": "draft", "targets": "[]"}]
    assert ItemStore(client, drafts=ideas).story_drafts() == ideas and client.calls == []


def test_the_idea_rows_the_plan_reads_come_from_the_stage_indexes_not_the_item_table():
    client = StrictStepClient()
    client.tables["Item"] = {row["id"]: row for row in many_other_items()}
    from papyrus_content.ideas.items import idea_rows

    rows = idea_rows(client)   # StrictStepClient raises on list_records("Item")
    assert rows == [] or all(row["kind"] == "story_draft" for row in rows)
    assert not [call for call in client.calls if call[0] == "list"]
    assert {call[2] for call in client.calls if call[0] == "list_by_index"} == {"idea", "assignment", "reporting", "copywriting", "illustration", "typesetting", "held", "spiked"}
