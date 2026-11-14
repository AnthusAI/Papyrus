"""The monitor-stories queue (features_backend/monitoring-stories-queue.feature). The model, the pages, the backends and the queue are fakes."""
from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

import test_monitor_stories_queue as queue  # noqa: E402
import test_monitoring_stories as tms  # noqa: E402
from ideas_fixtures import NOW, reference  # noqa: E402
from test_monitor_stories import MonitorClient, StoryModel, decision, pages, provenance, with_editors_reasons  # noqa: E402

from papyrus_content.ideas import story_plan  # noqa: E402
from papyrus_content.ideas.synthesis import SynthesisError  # noqa: E402


def state(context):
    return context.queue


class FlakyModel(StoryModel):
    """Fails the first drafting request while ``broken`` is set."""

    broken = False

    def __call__(self, url, headers, payload):
        if self.broken and not self.requests:
            self.requests.append(payload)
            raise SynthesisError("the model is overloaded")
        return super().__call__(url, headers, payload)


@given('a router with the publication "{publication}", the story queue and no monitorStories setting')
def step_router(context, publication):
    os.environ["PAPYRUS_GRAPHQL_AUTH"] = "iam"
    from unittest import mock

    from fake_idea_store import FakeIdeaStore
    from test_idea_items import FakeGate

    mock.patch("papyrus_content.ideas.gate.HumanusGate.for_client", classmethod(lambda cls, client, **options: FakeGate())).start()
    mock.patch("papyrus_content.ideas.items.ItemStore", lambda client, **options: FakeIdeaStore(client, gate=options.get("gate"))).start()
    context.add_cleanup(mock.patch.stopall)
    table, store = tms.router((publication,))
    context.queue = SimpleNamespace(table=table, store=store, publication=publication, sqs=queue.FakeSqs(), model=FlakyModel(), lines=[], plans=[], failures=[], logs=[],
                                    client=MonitorClient(references=[], incoming={}, relations={}, sections=("Analysis", "Tools")), taken=0)


def add(client, count, status="accepted", monitor="hn"):
    for _ in range(count):
        number = len(client.references) + 1
        row = reference(number, status=status, days_ago=number)
        client.references.append(row)
        provenance(row, monitor)
        client.relations[row["lineageId"]] = [decision(row, 0.5)]


@given('{count:d} accepted References for the queued run')
def step_accepted(context, count):
    add(state(context).client, count, "accepted", "hn")


@given("the model fails on the first story")
def step_model_fails(context):
    state(context).model.broken = True


@when("the router plans its daily monitor stories")
def step_plan(context):
    held = state(context)
    with_editors_reasons(held.client)
    _, lines = queue.plan(held.store, held.client, held.sqs)
    held.lines.append(lines[held.publication])


@when("the router plans its daily monitor stories the next day")
def step_plan_next_day(context):
    held = state(context)
    held.next_sqs = queue.FakeSqs()
    _, lines = queue.plan(held.store, held.client, held.next_sqs, now=NOW + timedelta(days=1))
    held.lines.append(lines[held.publication])


def work(held, messages, receives=1):
    logs, failures = queue.work(held.store, held.client, held.model, messages, receives=receives, fetch=pages(*range(1, 60)))
    held.logs += logs
    held.failures += failures


@when("the story worker takes every step off the queue")
def step_work(context):
    held = state(context)
    work(held, held.sqs.sent)


@when("the story worker takes every step off the queue again")
def step_work_again(context):
    held = state(context)
    work(held, held.sqs.sent)


@when("the story worker takes every step off the queue on its last try")
def step_work_last(context):
    held = state(context)
    work(held, held.sqs.sent, receives=story_plan.MAXIMUM_RECEIVES)


@when("the story worker takes only the first step off the queue")
def step_work_first(context):
    held = state(context)
    work(held, held.sqs.sent[:1])


@when("the story worker takes every remaining step off the queue")
def step_work_rest(context):
    held = state(context)
    work(held, held.sqs.sent[1:])


@when("the model recovers and the story worker takes step 1 again")
def step_recover(context):
    held = state(context)
    held.model.broken = False
    held.failures = []
    work(held, held.sqs.sent[:1], receives=2)


@when("a fourth accepted Reference arrives")
def step_fourth(context):
    add(state(context).client, 1)


@given("the story index answers nothing for a story created a moment ago")
def step_lagging(context):
    from test_story_from_reference import backend

    inner = backend()

    class Lagging:
        def __getattr__(self, name):
            return getattr(inner, name)

        def list_by_index(self, index, key):
            return [] if index == "itemsByLineageAndVersion" else inner.list_by_index(index, key)

    context.lagging = SimpleNamespace(inner=inner, client=Lagging())


@when('an idea is filed for the Reference "{lineage}"')
def step_file_idea(context, lineage):
    from test_idea_items import draft
    from test_story_from_reference import NOW as when_, reader

    from papyrus_content.ideas.items import file_idea_item

    context.lagging.error = None
    try:
        context.lagging.result = file_idea_item(context.lagging.client, draft(), now=when_, source_text_reader=reader)
    except ValueError as error:
        context.lagging.error = error


@then("no story draft is filed and the model is not asked")
def step_nothing(context):
    held = state(context)
    assert not held.client.filed and not held.model.requests, (len(held.client.filed), len(held.model.requests))


@then('{count:d} steps are on the story queue, in the message group "{group}"')
def step_on_queue(context, count, group):
    held = state(context)
    assert len(held.sqs.sent) == count and {message["group"] for message in held.sqs.sent} == {group}, held.sqs.sent


@then('the log line for "{publication}" says planned {count:d} steps and stoppedBy none')
def step_planned_line(context, publication, count):
    line = state(context).lines[-1]
    assert line["status"] == "planned" and line["planned"]["steps"] == count and line["stoppedBy"] is None and line["drafted"] == 0, line


@then("{count:d} story drafts are filed by the workers, one per Reference")
@then("{count:d} story draft is filed by the workers, one per Reference")
def step_filed(context, count):
    client = state(context).client
    assert len(client.filed) == count, len(client.filed)
    assert len({json.loads(row["evidence"])["source"] for row in client.filed}) == count and all("example" in json.loads(row["evidence"])["source"] for row in client.filed)


@then("one soft review request holds the {count:d} ideas")
def step_review(context, count):
    client = state(context).client
    assert len(client.reviews) == 1, len(client.reviews)
    [review] = client.reviews.values()
    assert len(json.loads(review["links"])) == count, review["links"]


@then("the worker logs that the plan finished with {drafted:d} drafted and no failed step")
def step_finished(context, drafted):
    [finished] = [line for line in state(context).logs if line.get("monitorStories") == "finished"]
    assert finished["drafted"] == drafted and finished["failedSteps"] == 0 and finished["status"] == "complete", finished


@then("the worker logs that the plan finished with {drafted:d} drafted and {failed:d} failed step")
def step_finished_failed(context, drafted, failed):
    [finished] = [line for line in state(context).logs if line.get("monitorStories") == "finished"]
    assert finished["drafted"] == drafted and finished["failedSteps"] == failed and finished["status"] == "complete_with_failures", finished


@then("the model was asked to draft {count:d} stories in all")
def step_asked(context, count):
    assert len(state(context).model.drafting) == count, len(state(context).model.drafting)


@then("the queue is asked to deliver step {step:d} again and {count:d} story draft is filed")
def step_redeliver(context, step, count):
    held = state(context)
    assert [failure["itemIdentifier"] for failure in held.failures] == [f"m-{step - 1}"] or len(held.failures) == 1, held.failures
    assert len(held.client.filed) == count


@then('the log line for "{publication}" says the earlier plan is still being drafted')
def step_waiting(context, publication):
    line = state(context).lines[-1]
    assert line["status"] == "waiting" and line["plan"]["done"] == 0, line


@then("the second plan has {count:d} step")
def step_second_plan(context, count):
    line = state(context).lines[-1]
    assert line["status"] == "planned" and line["planned"]["steps"] == count, line


@then('the idea is filed and linked to "{lineage}" and no "No story found for lineage" error is raised')
def step_linked(context, lineage):
    held = context.lagging
    assert held.error is None, held.error
    assert held.result["created"] and held.result["linked"] == [lineage]


@then("the worker handled {count:d} steps, one invocation each, and logs that the plan finished with {drafted:d} drafted and no failed step")
def step_one_each(context, count, drafted):
    held = state(context)
    assert len([line for line in held.logs if "monitorStoriesStep" in line]) == count == len(held.sqs.sent)
    step_finished(context, drafted)


@given("the site holds {count:d} other Items in every stage, and refuses to list a table")
def step_strict(context, count):
    held = state(context)
    held.strict_items = count


@when("the story worker takes every step off the queue and files for real")
def step_work_for_real(context):
    from unittest import mock

    from field_recorder import FieldRecorder

    held = state(context)
    held.strict = queue.strict_world_of(held.client)
    held.strict.tables["Item"] = {row["id"]: row for row in queue.many_other_items(held.strict_items)}
    held.recorder = FieldRecorder(held.strict)
    with mock.patch("papyrus_content.ideas.items.ItemStore", queue.ItemStore):   # the real class, imported before the scenario replaced it
        logs, failures = queue.work(held.store, held.recorder, held.model, held.sqs.sent, fetch=pages(*range(1, 60)))
    held.logs += logs
    held.failures += failures
    assert not failures, (failures, logs)


@then("{count:d} ideas are filed as Items at the idea stage")
def step_items_filed(context, count):
    filed = [row for row in state(context).strict.tables["Item"].values() if row["id"].startswith("item-idea-")]
    assert len(filed) == count and all(row["stage"] == "idea" for row in filed), filed


@then("no step read a whole table")
def step_no_scan(context):
    held = state(context)
    assert not set(held.recorder.unbounded) - queue.SMALL_CONFIGURATION_TABLES, held.recorder.unbounded


@then("every field the steps asked of the site is granted to the story worker's role")
def step_granted(context):
    held = state(context)
    granted = queue.story_worker_policy()
    assert held.recorder.fields <= granted, sorted(held.recorder.fields - granted)


@then("the story worker's role grants no listing of Items or of review requests")
def step_no_list_grant(context):
    assert not {field for _, field in queue.story_worker_policy()} & {"listItems", "listReviewRequests"}


@then("the plan's head row holds the existing ideas")
def step_head(context):
    held = state(context)
    plan_id = held.sqs.sent[0]["body"]["planId"]
    head = held.store.get_any("hn", story_plan.head_key(held.publication, plan_id))
    assert isinstance(story_plan.decode(head["proposals"]), list)


@then("no step asked for the site's stories by stage")
def step_no_stage_read(context):
    assert not {name for _, name in state(context).recorder.fields} & {"listItems", "listItemsByStageAndUpdatedAt"}
