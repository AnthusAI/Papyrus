"""An idea is more than a summary of its Reference (features_backend/idea-more-than-summary.feature and idea-more-than-summary-packs.feature).
The backend, the pages and the model are fakes."""

from __future__ import annotations

import json
import os
import re
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

from ideas_fixtures import NOW, reference  # noqa: E402
from papyrus_content import monitoring_stories, review_requests  # noqa: E402
from papyrus_content.ideas import connections as rules, monitor_stories, pack_stories, retry_memory, signal_inputs  # noqa: E402
from papyrus_content.ideas.signal_inputs import SignalMessage  # noqa: E402
from papyrus_content.ideas.signal_queue import ReferenceSummaries  # noqa: E402
from procedures.newsroom.tests.fake_idea_store import FakeIdeaStore  # noqa: E402
from test_idea_more_than_summary import ADDS, RESTATES, LinkedClient, Model, link, story, verdict  # noqa: E402
from test_idea_pack_stories import ADDS as PACK_ADDS, acceptance_pack, backend as pack_backend, joined, run as run_pack, sentence, summarised, transport_of  # noqa: E402
from test_monitor_stories import PAGE, context as site_context, provenance  # noqa: E402

REASON = "Claim checking matters to our sourcing coverage."
UNREADABLE_DETAILS = {"likes": 5}


def held(context) -> SimpleNamespace:
    if not hasattr(context, "mts"):
        context.mts = SimpleNamespace(
            rows=[], summaries={}, comments=[], feed=[], unreadable=set(), shipped=True, model=Model(story()), client=None,
            runs=[], only=None, connections=None, cut=None, memory=retry_memory.DictMemory(), limit=None, memory_broken=False,
        )
    return context.mts


def row_of(context, title):
    return next(row for row in held(context).rows if row["title"] == title)


def add_reference(context, title, *, status="accepted", summary="", details=None):
    state = held(context)
    number = len(state.rows) + 1
    row = reference(number, status=status, days_ago=number, title=title)
    row["curationStatusReason"] = ""
    provenance(row, "hn", details)
    state.rows.append(row)
    if summary:
        state.summaries[row["lineageId"]] = summary
    return row


def client_of(context) -> LinkedClient:
    state = held(context)
    if state.client is None:
        state.client = LinkedClient(references=state.rows, relations={}, incoming={}, sections=("Analysis", "Tools"), feed=state.feed)
    state.client.feed[:] = state.feed   # the backend's link feed is what the scenario says it is now
    return state.client


def knowledge_of(context) -> rules.Knowledge:
    state = held(context)
    comments = [
        SignalMessage(f"m{number}", "t1", "reference", f"reference#{row_of(context, title)['lineageId']}", "2026-10-30T09:00:00Z", "staff", text)
        for number, (title, text) in enumerate(state.comments, start=1)
    ]
    by_lineage = {row["lineageId"]: row for row in state.rows}
    return rules.Knowledge(client_of(context), summary_of=lambda lineage: state.summaries.get(lineage, ""), reference_of=by_lineage.get, inputs=SimpleNamespace(messages=comments))


@contextmanager
def explanations_as_shipped(context):
    """``signal_inputs.edges_of`` as it is (an edge carries ``explanation``, PR #1034), or as a build without that field has it."""
    state = held(context)
    real = signal_inputs.edges_of

    def without_words(relations):
        return [SimpleNamespace(subject_lineage_id=edge.subject_lineage_id, object_lineage_id=edge.object_lineage_id, predicate=edge.predicate) for edge in real(relations)]

    with mock.patch.object(signal_inputs, "edges_of", real if state.shipped else without_words):
        yield


# --- the world -------------------------------------------------------------------------------------------------------------------


@given('the accepted Reference "{title}" with the editors\' reason "{reason}"')
def step_with_reason(context, title, reason):
    add_reference(context, title)["curationActorKind"] = "human"
    row_of(context, title)["curationStatusReason"] = reason


@given('the accepted Reference "{title}" that no editor has said anything about')
def step_nothing_said(context, title):
    add_reference(context, title)


@given('the accepted Reference "{title}" with the summary "{summary}"')
def step_with_summary(context, title, summary):
    add_reference(context, title, summary=summary)


@given('the accepted Reference "{title}" with no summary')
def step_no_summary(context, title):
    add_reference(context, title)


@given('a pending Reference "{title}"')
def step_pending(context, title):
    add_reference(context, title, status="pending")


@given('four accepted References "{a}", "{b}", "{c}" and "{d}" each with a summary')
def step_four(context, a, b, c, d):
    for title in (a, b, c, d):
        add_reference(context, title, summary=f"About {title}.")


@given('the page of "{title}" cannot be read and the monitor stored no summary')
def step_unreadable(context, title):
    row = row_of(context, title)
    row["discoveryDetails"] = json.dumps(UNREADABLE_DETAILS)
    held(context).unreadable.add(row["sourceUri"])


@given('an editor commented on "{title}": "{text}"')
@when('an editor commented on "{title}": "{text}"')
def step_comment(context, title, text):
    held(context).comments.append((title, text))


@given('editors linked "{first}" to "{second}"')
@when('editors linked "{first}" to "{second}"')
def step_linked(context, first, second):
    held(context).feed.append(link(row_of(context, first), row_of(context, second), state="current", score=None))


@given('editors connected "{first}" to "{second}" and explained "{words}"')
@when('editors connected "{first}" to "{second}" and explained "{words}"')
def step_linked_explained(context, first, second, words):
    held(context).feed.append(link(row_of(context, first), row_of(context, second), state="current", score=None, note=words))


@given("the vector index suggests these matches:")
def step_suggests(context):
    for line in context.table:
        held(context).feed.append(link(row_of(context, line["first"]), row_of(context, line["second"]), score=float(line["similarity"])))


# --- what the model writes ---------------------------------------------------------------------------------------------------------


def model_says(context, answer):
    held(context).model.answer = answer


@given("the model writes a story whose every sentence cites only the source")
def step_summary_story(context):
    model_says(context, story(dek=("Foo links each claim to the source page it came from.", "I1"), body=[("Foo is an open tool.", "I1"), ("It was written in Rust.", "I1")]))


@given("the model writes a story that rests on the editors' reason")
@when("the model writes a story that rests on the editors' reason")
def step_reason_story(context):
    model_says(context, story())


@given("the model writes a story that reports why the editors accepted the item")
def step_process_story(context):
    model_says(context, story(dek=("Claim checking matters to sourcing coverage.", "E1"), body=[
        ("Foo is an open tool that checks claims against their sources.", "I1"), ("The editors accepted it because claim checking matters to sourcing coverage.", "E1", "I1")]))


@given("the model writes a story whose connecting sentence is about something else")
def step_unrelated_story(context):
    model_says(context, story(dek=("A toaster is on sale.", "E1"), body=[("Foo is an open tool.", "I1"), ("A toaster is on sale.", "I1", "E1")]))


@given("the model writes a story that calls claim checking a trend")
def step_trend_story(context):
    model_says(context, story(dek=("Claim checking shows a trend.", "E1")))


@given("the model writes a story with no point")
def step_no_point_story(context):
    model_says(context, story(point=""))


@given("the model writes a story that describes what the page contains")
def step_describes_story(context):
    model_says(context, story(dek=("A commenter says claim checking is overdue.", "M1", "I1"), body=[
        ("Foo is a tool that checks claims.", "I1"), ("A commenter says claim checking is overdue for sourcing coverage.", "M1", "I1")]))


@given("the model writes a story that rests on the comment and the editors' reason")
@when("the model writes a story that rests on the comment and the editors' reason")
def step_comment_story(context):
    model_says(context, story(dek=("A commenter says claim checking is overdue.", "M1", "I1"), body=[
        ("A commenter says claim checking is overdue for sourcing coverage.", "M1", "I1"),
        ("Claim checking is the sourcing work this item is about.", "E1", "I1")]))


@given("the model writes a story that rests on the related Reference")
def step_related_story(context):
    model_says(context, story(dek=("A second tool checks quotations against archives, a form of claim checking.", "E1", "R1"), body=[
        ("A tool that checks quotations against archives is close to this item.", "R1"),
        ("Claim checking is the sourcing work both tools do.", "E1", "I1")]))


ANSWERS = {
    "restates its source": RESTATES,
    "claims something its sources do not support": verdict(verdict="unsupported", claim="Foo is faster than every rival."),
    "repeats itself": verdict(repeats_itself=True),
    "talks about how the story came to be": verdict(exposes_process=True),
    "adds something": ADDS,
}


@given("the point check answers that the draft {answer}")
@when("the point check answers that the draft {answer}")
def step_check_answers(context, answer):
    model = held(context).model
    model.verdict = ANSWERS[answer]
    if hasattr(model, "usable"):
        model.usable = True   # a check that could not answer before can now


@given("the point check gives no usable answer")
def step_check_unusable(context):
    state = held(context)
    inner = state.model

    class Unsure(Model):
        def __call__(self, url, headers, payload):
            if payload["instructions"].startswith("You are a sceptical editor") and not self.usable:
                self.requests.append(payload)
                return {"status": "incomplete"}
            return super().__call__(url, headers, payload)

    unsure = Unsure(inner.answer, inner.verdict)
    unsure.usable = False
    state.model = unsure


@given('the run considers "{title}" only')
def step_considers(context, title):
    held(context).only = title


@given('"{title}" was rejected before and nothing new is known about it')
def step_rejected_before(context, title):
    state = held(context)
    knowledge = knowledge_of(context)
    items, _ = monitor_stories.collect_monitored_items(client_of(context), site="example-site", now=NOW)
    item = next(item for item in items if item.title == title)
    keys = retry_memory.single_keys(knowledge.connections_for(item))
    subject = retry_memory.single_subject(item.lineage_id)
    state.memory.remember(subject, retry_memory.rejection(subject, run_id="earlier", at="2026-10-22T00:00:00Z", reasons=["point_check_failed"], keys=keys))


@given("the memory of rejections is unavailable")
def step_memory_broken(context):
    class Broken:
        def recall(self, subject):
            raise RuntimeError("no table")

        def remember(self, subject, record):
            raise RuntimeError("no table")

    held(context).memory = Broken()


# --- the run -----------------------------------------------------------------------------------------------------------------------


def run_ideas(context, *, dry_run=False, **options):
    state = held(context)
    client = client_of(context)
    state.runs.append(None)
    with mock.patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": "iam"}), explanations_as_shipped(context):
        run = monitor_stories.draft_monitor_stories(
            client=client, site="example-site", context=site_context(), json_store=None, transport=state.model, idea_store=FakeIdeaStore(client), review_client=client,
            limit=state.limit, dry_run=dry_run, now=NOW, fetch=lambda url: None if url in state.unreadable else PAGE, knowledge=knowledge_of(context),
            ordered_candidates=[row_of(context, state.only)["lineageId"]] if state.only else None, retry_memory=state.memory, **options,
        )
    state.runs[-1] = run
    return run


@when("the run drafts ideas")
def step_run(context):
    run_ideas(context)


@when("the run drafts ideas with no time left")
def step_no_time(context):
    run_ideas(context, out_of_time=lambda: True)


@when("the run drafts ideas while the suggested links are still being written")
def step_suggestions_waiting(context):
    run_ideas(context, suggestions_waiting=True)


@when("the run drafts ideas as a dry run")
def step_dry(context):
    run_ideas(context, dry_run=True)


@when('the run drafts ideas for "{title}" only')
def step_only(context, title):
    held(context).only = title
    run_ideas(context)


@when('the run drafts ideas with room for {attempts:d} attempt')
def step_room(context, attempts):
    held(context).limit = attempts
    run_ideas(context)


@when('an editor accepts "{title}" again and writes "{reason}"')
def step_accepts_again(context, title, reason):
    row_of(context, title).update(curationActorKind="human", curationStatusReason=reason)


@when('editors confirm the link between "{first}" and "{second}"')
def step_confirm(context, first, second):
    held(context).feed[:] = [link(row_of(context, first), row_of(context, second), state="current", score=None)]


@when('the link between "{first}" and "{second}" goes away')
def step_gone(context, first, second):
    held(context).feed[:] = []


@when('the link between "{first}" and "{second}" comes back')
def step_back(context, first, second):
    held(context).feed[:] = [link(row_of(context, first), row_of(context, second), state="current", score=None)]


def last(context):
    return held(context).runs[-1]


def flags(context):
    return [request for request in review_requests.list_reviews(client_of(context)) if request["mode"] == "flag"]


@then("the run files {count:d} idea")
def step_files(context, count):
    assert len(client_of(context).filed) == count and len(last(context)["drafts"]) == count, (last(context)["invalid"], last(context)["skipped"])


@then("the run files no idea")
@then("the run files nothing")
def step_files_none(context):
    assert client_of(context).filed == [] and last(context)["drafts"] == []


@then("the model is asked {count:d} times")
def step_asked(context, count):
    assert len(held(context).model.requests) == count


@then("the model was asked nothing in that run")
def step_asked_nothing(context):
    assert last(context)["usage"]["calls"] == 0 and last(context)["attempted"] == 0, last(context)["usage"]


@then("the point check was not asked")
def step_check_not_asked(context):
    assert held(context).model.checks == []


@then("the point check was asked once about the idea and found that it adds something")
def step_check_asked(context):
    model = held(context).model
    [check] = last(context)["pointChecks"]
    assert len(model.checks) == 1 and check["failures"] == [] and check["verdict"]["verdict"] == "adds" and check["sentences"], check


@then('"{title}" is skipped as "{reason}"')
def step_skipped(context, title, reason):
    assert [(row["title"], row["reason"]) for row in last(context)["skipped"]] == [(title, reason)], last(context)["skipped"]


@then("the run record says the draft failed with {reasons}")
def step_failed(context, reasons):
    failures = last(context)["checkFailures"]
    assert all(reason in failures for reason in re.findall(r'"([\w:]+)"', reasons)), failures


@then("the model was shown the editors' reason marked as direction and not as a fact")
def step_shown(context):
    shown = json.loads(held(context).model.drafting[0]["input"])["what_the_newsroom_knows"][0]
    assert shown["handle"] == "E1" and shown["writtenBy"] == "editor" and shown["text"] == REASON and "not a fact" in shown["note"] and "not to be reported" in shown["note"], shown


@then("the idea records the connections {labels}")
def step_connections(context, labels):
    recorded = json.loads(client_of(context).filed[0]["evidence"])["connections"]
    assert recorded == re.findall(r'"([\w:]+)"', labels), recorded


@then("the idea body quotes the editors' reason apart from its sources")
def step_body(context):
    body = client_of(context).filed[0]["body"]
    assert "## What editors said" in body and REASON in body and body.index("## Source") < body.index("## What editors said"), body


@then('the run record counts 1 idea resting on "{kind}"')
def step_histogram(context, kind):
    assert last(context)["connectionsUsed"] == {kind: 1}, last(context)["connectionsUsed"]


@then('the idea still targets only "{title}"')
def step_targets(context, title):
    assert json.loads(client_of(context).filed[0]["targets"]) == [{"type": "entity", "id": f"reference:{row_of(context, title)['lineageId']}"}]


@then("one flag is open in the Notification Center")
def step_one_flag(context):
    open_flags = [flag for flag in flags(context) if flag["state"] == "open"]
    assert len(open_flags) == 1 and open_flags[0]["raisedBy"] == "idea-pipeline", flags(context)


@then('the flag says "{text}"')
def step_flag_says(context, text):
    assert [flag["reason"] for flag in flags(context)][0] == text


@then("the flag asks editors to add a reason when they accept, to confirm the suggested links waiting in Related and to comment, and names the waiting titles")
def step_flag_asks(context):
    ask = flags(context)[0]["ask"]
    assert "add a reason when you accept (2 of 2 have none)" in ask and "confirm the suggested links waiting in Related" in ask and "comment on the ones you care about" in ask, ask
    assert "A tool that checks claims" in ask and "A tool that checks quotations" in ask, ask


@then('the flag does not use the words "{first}" or "{second}"')
def step_flag_words(context, first, second):
    flag = flags(context)[0]
    assert not any(word in flag["reason"] + flag["ask"] for word in (first, second, first.lower()))


@then("the flag is acknowledged because ideas are flowing again")
def step_acknowledged(context):
    [flag] = flags(context)
    assert flag["state"] == "answered" and flag["answer"]["decision"] == "acknowledge" and "flowing again" in flag["answer"]["feedback"], flag


@then("the run was stopped by time")
def step_stopped_by_time(context):
    assert last(context)["stoppedBy"] == "time", last(context)["stoppedBy"]


@then("the run was not stopped")
def step_not_stopped(context):
    assert last(context)["stoppedBy"] is None, last(context)["stoppedBy"]


@then("no flag is raised")
def step_no_flag(context):
    assert flags(context) == []


@then("the point check's verdict and the draft's sentences are in the run record")
def step_verdict_recorded(context):
    [invalid] = last(context)["invalid"]
    [check] = last(context)["pointChecks"]
    assert invalid["verdict"] == check["verdict"] and invalid["failures"] == check["failures"] and check["sentences"] and check["point"], (invalid, check)


@then('nothing is remembered about "{title}"')
def step_nothing_remembered(context, title):
    assert held(context).memory.records == {}, held(context).memory.records


def remembered(context, title):
    return held(context).memory.recall(retry_memory.single_subject(row_of(context, title)["lineageId"]))


@then('"{title}" is remembered as rejected for "{reason}"')
def step_remembered(context, title, reason):
    record = remembered(context, title)
    assert record is not None and record["reasons"] == [reason] and record["runId"] == last(context)["runId"] and record["connections"], record


@then('"{title}" is remembered as rejected for "{reason}" against the accept reason')
def step_remembered_against(context, title, reason):
    record = remembered(context, title)
    assert record["reasons"] == [reason] and [key.split(":")[0] for key in record["connections"]] == ["acceptReason"], record


KEY_OF_CONNECTION = {
    "a new comment": ("message:",), "a new accept reason": ("acceptReason:",), "a new confirmed link": ("neighbour:", ":confirmed"),
    "a new link and explanation": ("neighbour:", "explanation:"),
}


@then('the run record says "{title}" was tried again because of {connection}')
def step_tried_again(context, title, connection):
    retries = [row for row in last(context)["retriedWithNewConnections"] if row["subject"] == retry_memory.single_subject(row_of(context, title)["lineageId"])]
    assert len(retries) == 1, last(context)["retriedWithNewConnections"]
    joined_keys = " ".join(retries[0]["newConnections"])
    assert all(part in joined_keys for part in KEY_OF_CONNECTION[connection]) and retries[0]["earlierReasons"] == ["point_check_failed"], retries


@then('the idea targets "{title}"')
def step_targets_one(context, title):
    assert [json.loads(row["targets"]) for row in client_of(context).filed] == [[{"type": "entity", "id": f"reference:{row_of(context, title)['lineageId']}"}]]


@then("the run record names the memory as unavailable")
def step_memory_named(context):
    assert last(context)["retryMemoryErrors"] == {"recall": "RuntimeError", "remember": "RuntimeError"} or "recall" in last(context)["retryMemoryErrors"], last(context)


@then("the flag says a rejected idea is written again as soon as there is something new to connect it to")
def step_flag_retry(context):
    assert "written again as soon as there is something new to connect it to" in flags(context)[0]["ask"]


# --- reading connections ---------------------------------------------------------------------------------------------------------


def read_connections(context, title):
    state = held(context)
    client = client_of(context)
    items, _ = monitor_stories.collect_monitored_items(client, site="example-site", now=NOW)
    item = next(item for item in items if item.title == title)
    knowledge = knowledge_of(context)
    with explanations_as_shipped(context):
        state.connections = knowledge.connections_for(item)
    state.cut = knowledge.neighbour_cut


@when('the connections of "{title}" are read')
def step_read(context, title):
    read_connections(context, title)


@when("the build has no editors' explanations on its links")
def step_unshipped(context):
    held(context).shipped = False


@then("the connections are {handles}")
def step_they_are(context, handles):
    assert [entry.handle for entry in held(context).connections.entries] == re.findall(r'"(\w+)"', handles)


@then('"{handle}" carries the editors\' explanation "{words}" as the editors\' view')
def step_explanation(context, handle, words):
    row = held(context).connections.by_handle()[handle].row
    assert row["editorsExplanation"] == {"writtenBy": "editor", "text": words} and "not a fact" in row["note"], row


@then('the related References are "{title}"')
def step_related(context, title):
    related = [entry.reference.title for entry in held(context).connections.entries if entry.kind == rules.NEIGHBOUR]
    assert related == [title], related


@then("there are no related References")
def step_no_related(context):
    assert [entry for entry in held(context).connections.entries if entry.kind == rules.NEIGHBOUR] == []


@then("the site's typical nearest-neighbour similarity is {value:f}")
def step_cut(context, value):
    assert abs(held(context).cut - value) < 1e-9, held(context).cut


# --- the retired setting ---------------------------------------------------------------------------------------------------------


@then('a stored config with the retired setting "{name}" still loads')
def step_retired_loads(context, name):
    context.retired = {}
    for value in ("summary", "more-than-summary", "anything"):
        context.retired[value] = monitoring_stories.validate_monitor_stories("p", {name: value, "singleItem": True})
    assert all(policy["singleItem"] is True for policy in context.retired.values())


@then("its value, whatever it was, changes nothing")
def step_retired_ignored(context):
    plain = monitoring_stories.validate_monitor_stories("p", {"singleItem": True})
    assert all(policy == plain and "minimumStandard" not in policy for policy in context.retired.values())


@then("an unknown setting is still refused")
def step_unknown_refused(context):
    try:
        monitoring_stories.validate_monitor_stories("p", {"minimumStandards": "summary"})
    except ValueError:
        return
    raise AssertionError("an unknown setting was accepted")


# --- packs -----------------------------------------------------------------------------------------------------------------------


@given("a pack of four accepted References of which one has a summary")
def step_pack_one(context):
    context.pack = summarised(acceptance_pack(), "R1")


@given("a pack of four accepted References of which two have summaries")
def step_pack_two(context):
    context.pack = summarised(acceptance_pack(), "R1", "R2")


@given("a pack of four accepted References that all have summaries")
def step_pack_all(context):
    context.pack = summarised(acceptance_pack(), "R1", "R2", "R3", "R4")


@given("the model writes an idea whose sentences each cite a single Reference")
def step_apart(context):
    idea = joined("Synthetic voices spread")
    idea["dek"] = sentence("Both sources describe voice cloning.", "R1")
    idea["paragraphs"] = [{"sentences": [sentence("The first source describes voice cloning.", "R1"), sentence("The second source describes voice cloning in newsrooms.", "R2")]}]
    context.idea = idea


@given("the model writes an idea with a sentence citing two References together")
def step_joined(context):
    context.idea = joined("Synthetic voices spread")


@given("the model writes an idea with a sentence citing a Reference without a summary")
def step_joined_without(context):
    context.idea = joined("Synthetic voices spread", ("R1", "R3"))


@given("the pack's point check answers that the idea {answer}")
def step_pack_check_answers(context, answer):
    context.pack_verdict = {**PACK_ANSWERS[answer]}


@given("the pack's point check gives no usable answer")
def step_pack_check_unusable(context):
    context.pack_verdict = {"status": "incomplete"}


PACK_ANSWERS = {
    "lists what each source says": {**PACK_ADDS, "verdict": "restates", "claim": "", "reason": "It lists what each source says."},
    "claims something its sources do not support": {**PACK_ADDS, "verdict": "unsupported"},
    "repeats itself": {**PACK_ADDS, "repeats_itself": True},
    "talks about how the idea came to be": {**PACK_ADDS, "exposes_process": True},
    "says something no single source says": PACK_ADDS,
}


@when("the pack is written")
def step_pack_run(context):
    ideas = [context.idea] if hasattr(context, "idea") else []
    context.transport = transport_of(*ideas, verdict=getattr(context, "pack_verdict", PACK_ADDS))
    context.client = pack_backend(context.pack)
    context.result = run_pack(context.pack, context.client, context.transport)


@then("the pack's model is asked {count:d} times")
def step_pack_asked(context, count):
    assert len(context.transport.calls) == count


@then('the pack is skipped as "{reason}"')
def step_pack_skipped(context, reason):
    assert [row["reason"] for row in context.result.dropped] == [reason] and context.result.filed_count == 0


@then("the pack files no idea")
def step_pack_none(context):
    assert context.result.filed_count == 0


@then("the pack's point check is asked {count:d} times")
def step_pack_checks(context, count):
    assert len(context.transport.checks) == count


@then("the point check was shown each Reference the idea cites on its own")
def step_pack_sources(context):
    sent = json.loads(context.transport.checks[0]["input"])
    assert "source" not in sent and len(sent["sources"]) == 2 and "none of the sources states" in context.transport.checks[0]["instructions"], sent


@then('the idea was dropped because the point check found "{reason}"')
def step_pack_dropped_check(context, reason):
    [drop] = context.result.dropped
    assert drop["reason"] == "point_check_failed" and drop["failures"] == [reason] and drop["verdict"], drop


@then("the idea was dropped because the point check gave no usable answer")
def step_pack_dropped_error(context):
    assert [drop["reason"] for drop in context.result.dropped] == ["point_check_error"] and context.result.filed_count == 0


@then("the pack files {count:d} idea")
def step_pack_files(context, count):
    assert context.result.filed_count == count, context.result.dropped


@then('the idea was dropped because it has "{reason}"')
def step_dropped(context, reason):
    assert [problem["reason"] for problem in context.result.dropped[0]["citationCheck"]["problems"]] == [reason], context.result.dropped


# --- the summary chain ---------------------------------------------------------------------------------------------------------------


class Attachments:
    def __init__(self, rows):
        self.rows = rows

    def list_semantic_relations_by_object_state(self, key):
        return []

    def list_reference_attachments_by_lineage(self, lineage):
        return self.rows


@given("a Reference whose preview attachment describes it and whose curation attachment summarises it")
def step_both(context):
    context.attachments = [{"role": "preview", "metadata": {"description": "A preview description."}},
                           {"role": "curation", "metadata": json.dumps({"summary": {"text": "A curated summary."}})}]
    context.title = "Some Title"


@given("a Reference whose preview attachment only repeats its title")
def step_repeats(context):
    context.attachments = [{"role": "preview", "metadata": {"description": "Some Title"}}]
    context.title = "Some Title"


def summary_of(context):
    return ReferenceSummaries(Attachments(context.attachments), titles={"l1": context.title})["l1"]


@then("its summary is the curation attachment's")
def step_curation(context):
    assert summary_of(context) == "A curated summary."


@then("it has no summary")
def step_none(context):
    assert summary_of(context) == ""


# --- the replay ------------------------------------------------------------------------------------------------------------------------


@given("a site with four accepted References of which two have an editor's reason")
def step_replay_site(context):
    from test_idea_standard_replay import backend

    context.replay_client = backend(4, 2)


@when("the replay runs with a ceiling of {ceiling} dollars")
def step_replay(context, ceiling):
    from test_idea_standard_replay import Writer, run

    context.replay = run(context.replay_client, Writer(restating=getattr(context, "replay_restating", ())), max_cost_usd=float(ceiling))


@given("the point check finds that the idea for the first of them only restates its source")
def step_replay_restates(context):
    context.replay_restating = [1]
    from test_idea_standard_replay import backend

    context.replay_client = backend(4, 4)


@then("the site's backend received no write")
def step_no_writes(context):
    assert context.replay_client.filed == [], context.replay_client.filed   # NoWritesClient also fails the run itself on any create, update, upsert, delete or mutation


@then("no review request exists on the site")
def step_no_reviews(context):
    assert context.replay_client.reviews == {}


@then("the replay would file {new:d} ideas")
def step_ways(context, new):
    assert context.replay["run"]["filed"] == new, context.replay["run"]


@then('the replay reports {count:d} References with nothing to add, resting on "{kind}"')
def step_report(context, count, kind):
    one = context.replay["run"]
    assert one["nothingToAdd"] == count and one["connectionsUsed"] == {kind: 2} and "checkFailures" in one and one["costUsd"] > 0, one


@then("the replay reports the point check's verdicts and the reasons drafts failed")
def step_reasons(context):
    one = context.replay["run"]
    assert one["pointChecks"] == 4 and one["pointCheckFailed"] == 1 and one["checkFailures"] == {"no_point_beyond_source": 1}, one


@then("the sample has {count:d} drafts, with the connections shown and the point check's verdict beside each")
def step_sample(context, count):
    text = context.replay["sampleText"]
    assert context.replay["sample"] == count and text.count("What the newsroom had on this Reference") == count and text.count("The point check said") == count, text


@then("the sample lists the rejected draft and why")
def step_sample_rejected(context):
    assert "## Rejected" in context.replay["sampleText"] and "point_check_failed (no_point_beyond_source)" in context.replay["sampleText"]


@then("the replay's cost is within {ceiling} dollars and it stopped for cost")
def step_cost(context, ceiling):
    assert context.replay["costUsd"] <= float(ceiling) and context.replay["run"]["stoppedBy"] == "cost"


@then("a replay with no ceiling is refused")
def step_refused_ceiling(context):
    from test_idea_standard_replay import Writer, run

    try:
        run(context.replay_client, Writer(), max_cost_usd=0)
    except ValueError:
        return
    raise AssertionError("a replay without a ceiling started")


# --- a pack whose ideas were all rejected -------------------------------------------------------------------------------------------------


@given("a context pack run on a site whose pack ideas the point check rejects")
def step_pack_memory_world(context):
    import idea_context_packs_steps as router_steps
    import test_monitoring_packs as router_support

    router_steps.start_patch(context, mock.patch.dict("os.environ", {"PAPYRUS_GRAPHQL_AUTH": "iam"}))
    router_steps.start_patch(context, mock.patch("papyrus_content.ideas.items.ItemStore", lambda client, **options: FakeIdeaStore(client, gate=options.get("gate"))))
    router_steps.start_patch(context, mock.patch("papyrus_content.ideas.gate.HumanusGate.for_client", classmethod(lambda cls, client, **options: router_steps.FakeGate())))
    filing = router_support.FilingRecorder(router_steps.Patching(context))
    table, store = router_support.router(settings={router_support.PUBLICATION: {"singleItem": False, "contextPacks": {"enabled": True}}})
    context.pack_memory = SimpleNamespace(
        client=router_support.pack_world(2, lively=(1,), reasoned=False), table=table, store=store, filing=filing, support=router_support,
        model=router_support.RouterModel(verdict={"verdict": "restates", "claim": "", "repeats_itself": False, "exposes_process": False, "reason": "It lists what each says."}),
        lines=[],
    )
    repeat_run(context)


def repeat_run(context):
    state = context.pack_memory
    _, lines = state.support.run_task(state.store, {state.support.PUBLICATION: state.client}, state.model)
    state.lines.append(state.support.pack_lines(lines))


@when("the run is repeated with nothing new in the pack")
@when("the run is repeated")
def step_repeat(context):
    repeat_run(context)


@when("another accepted Reference joins the pack")
def step_joins(context):
    state = context.pack_memory
    row, links = state.support.human_vote(300, 0.2, "concept-voice")
    state.client.references.append(row)
    state.client.relations[row["lineageId"]] = links


@then('the pack\'s model was not asked again and the run says the pack is "already_rejected"')
def step_pack_waits(context):
    state = context.pack_memory
    assert len(state.model.pack_requests) == 1 and state.lines[0]["failedTheCheck"] == 2 and state.lines[1]["alreadyRejected"] == 1 and state.filing.filed == [], state.lines


@then("the pack's model was asked again and the run says the pack was tried again because of a new connection")
def step_pack_retried(context):
    state = context.pack_memory
    assert len(state.model.pack_requests) == 2 and state.lines[2]["retriedWithNewConnections"] == 1 and state.lines[2]["alreadyRejected"] == 0, state.lines
