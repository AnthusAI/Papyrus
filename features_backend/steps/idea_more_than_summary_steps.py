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
from papyrus_content.ideas import connections as rules, monitor_stories, pack_stories, signal_inputs  # noqa: E402
from papyrus_content.ideas.signal_inputs import SignalMessage  # noqa: E402
from papyrus_content.ideas.signal_queue import ReferenceSummaries  # noqa: E402
from procedures.newsroom.tests.fake_idea_store import FakeIdeaStore  # noqa: E402
from test_idea_more_than_summary import LinkedClient, Model, link, story  # noqa: E402
from test_idea_pack_stories import acceptance_pack, backend as pack_backend, joined, run as run_pack, sentence, summarised, transport_of  # noqa: E402
from test_monitor_stories import PAGE, context as site_context, provenance  # noqa: E402

REASON = "Claim checking matters to our sourcing coverage."
UNREADABLE_DETAILS = {"likes": 5}


def held(context) -> SimpleNamespace:
    if not hasattr(context, "mts"):
        context.mts = SimpleNamespace(
            standard="more-than-summary", rows=[], summaries={}, comments=[], feed=[], unreadable=set(), shipped=True, model=Model(story()), client=None,
            runs=[], only=None, connections=None, cut=None,
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


@given('a site that holds its ideas to the minimum standard "{standard}"')
def step_standard(context, standard):
    held(context).standard = standard


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
def step_comment(context, title, text):
    held(context).comments.append((title, text))


@given('editors linked "{first}" to "{second}"')
def step_linked(context, first, second):
    held(context).feed.append(link(row_of(context, first), row_of(context, second), state="current", score=None))


@given('editors connected "{first}" to "{second}" and explained "{words}"')
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


@given("the model writes a story that states the editors' reason as a fact")
def step_fact_story(context):
    model_says(context, story(dek=("Claim checking matters to sourcing coverage.", "E1"), body=[
        ("Foo is an open tool that checks claims against their sources.", "I1"), ("Claim checking matters to sourcing coverage.", "E1", "I1")]))


@given("the model writes a story whose connecting sentence is about something else")
def step_unrelated_story(context):
    model_says(context, story(dek=("The editors liked a toaster.", "E1"), body=[("Foo is an open tool.", "I1"), ("The editors liked a toaster.", "I1", "E1")]))


@given("the model writes a story that calls claim checking a trend")
def step_trend_story(context):
    model_says(context, story(dek=("The editors see a trend in claim checking.", "E1")))


@given("the model writes a story that describes what the page contains")
def step_describes_story(context):
    model_says(context, story(dek=("A commenter says claim checking is overdue.", "M1", "I1"), body=[
        ("Foo is a tool that checks claims.", "I1"), ("A commenter says claim checking is overdue for the newsroom.", "M1", "I1")]))


@when("the model writes a story that rests on the comment and the editors' reason")
def step_comment_story(context):
    model_says(context, story(dek=("A commenter says claim checking is overdue.", "M1", "I1"), body=[
        ("A commenter says claim checking is overdue for the newsroom.", "M1", "I1"),
        ("The editors accepted it because claim checking matters to their sourcing coverage.", "E1", "I1")]))


@given("the model writes a story that rests on the related Reference")
def step_related_story(context):
    model_says(context, story(dek=("The editors link it to a tool that checks quotations against archives.", "E1", "R1"), body=[
        ("A tool that checks quotations against archives is close to this item.", "R1"),
        ("The editors accepted it because claim checking matters to their sourcing coverage.", "E1", "I1")]))


# --- the run -----------------------------------------------------------------------------------------------------------------------


def run_ideas(context, *, dry_run=False):
    state = held(context)
    client = client_of(context)
    state.runs.append(None)
    with mock.patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": "iam"}), explanations_as_shipped(context):
        run = monitor_stories.draft_monitor_stories(
            client=client, site="example-site", context=site_context(), json_store=None, transport=state.model, idea_store=FakeIdeaStore(client), review_client=client,
            limit=None, dry_run=dry_run, now=NOW, fetch=lambda url: None if url in state.unreadable else PAGE, minimum_standard=state.standard, knowledge=knowledge_of(context),
            ordered_candidates=[row_of(context, state.only)["lineageId"]] if state.only else None,
        )
    state.runs[-1] = run
    return run


@when("the run drafts ideas")
def step_run(context):
    run_ideas(context)


@when("the run drafts ideas as a dry run")
def step_dry(context):
    run_ideas(context, dry_run=True)


@when('the run drafts ideas for "{title}" only')
def step_only(context, title):
    held(context).only = title
    run_ideas(context)


@when('an editor accepts "{title}" again and writes "{reason}"')
def step_accepts_again(context, title, reason):
    row_of(context, title).update(curationActorKind="human", curationStatusReason=reason)


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


@then('"{title}" is skipped as "{reason}"')
def step_skipped(context, title, reason):
    assert [(row["title"], row["reason"]) for row in last(context)["skipped"]] == [(title, reason)], last(context)["skipped"]


@then("the run record says the draft failed with {reasons}")
def step_failed(context, reasons):
    failures = last(context)["checkFailures"]
    assert all(reason in failures for reason in re.findall(r'"([\w:]+)"', reasons)), failures


@then("the model was shown the editors' reason marked as their view and not as a fact")
def step_shown(context):
    shown = json.loads(held(context).model.requests[0]["input"])["what_the_newsroom_knows"][0]
    assert shown["handle"] == "E1" and shown["writtenBy"] == "editor" and shown["text"] == REASON and "not a fact" in shown["note"], shown


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


@then("no flag is raised")
def step_no_flag(context):
    assert flags(context) == []


@then("the model was not shown what the newsroom knows")
def step_not_shown(context):
    assert "what_the_newsroom_knows" not in json.loads(held(context).model.requests[0]["input"])


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


# --- the setting -----------------------------------------------------------------------------------------------------------------


@then('a site that says nothing about its minimum standard has "{standard}"')
def step_default(context, standard):
    assert monitoring_stories.validate_monitor_stories("p", None)["minimumStandard"] == standard
    assert monitoring_stories.validate_monitor_stories("p", {})["minimumStandard"] == standard


@then('a site may say "{standard}"')
def step_may_say(context, standard):
    assert monitoring_stories.validate_monitor_stories("p", {"minimumStandard": standard})["minimumStandard"] == standard


@then("any other minimum standard is refused")
def step_refused(context):
    for bad in ("anything", None, 3):
        try:
            monitoring_stories.validate_monitor_stories("p", {"minimumStandard": bad})
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} was accepted")


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


@when('the pack is written under the minimum standard "{standard}"')
def step_pack_run(context, standard):
    context.transport = transport_of(context.idea) if hasattr(context, "idea") else transport_of()
    context.result = run_pack(context.pack, pack_backend(context.pack), context.transport, standard=standard)


@then("the pack's model is asked {count:d} times")
def step_pack_asked(context, count):
    assert len(context.transport.calls) == count


@then('the pack is skipped as "{reason}"')
def step_pack_skipped(context, reason):
    assert [row["reason"] for row in context.result.dropped] == [reason] and context.result.filed_count == 0


@then("the pack files no idea")
def step_pack_none(context):
    assert context.result.filed_count == 0


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
    from test_idea_standard_replay import TwoWays, run

    context.replay = run(context.replay_client, TwoWays(), max_cost_usd=float(ceiling))


@then("the site's backend received no write")
def step_no_writes(context):
    assert context.replay_client.filed == [], context.replay_client.filed   # NoWritesClient also fails the run itself on any create, update, upsert, delete or mutation


@then("no review request exists on the site")
def step_no_reviews(context):
    assert context.replay_client.reviews == {}


@then("the old way would file {old:d} ideas and the new way {new:d}")
def step_ways(context, old, new):
    arms = context.replay["arms"]
    assert (arms["summary"]["filed"], arms["more-than-summary"]["filed"]) == (old, new), arms


@then('the new way reports {count:d} References with nothing to add, resting on "{kind}"')
def step_report(context, count, kind):
    arm = context.replay["arms"]["more-than-summary"]
    assert arm["nothingToAdd"] == count and arm["connectionsUsed"] == {kind: 2} and "checkFailures" in arm and arm["costUsd"] > 0, arm


@then("the sample has {pairs:d} pairs, each in a version A and a version B, with the connections shown and no word of which standard wrote which")
def step_sample(context, pairs):
    sample = context.replay["sample"]
    assert context.replay["pairs"] == pairs and sample.count("### Version A") == pairs and sample.count("### Version B") == pairs
    assert sample.count("What the newsroom had on this Reference") == pairs and "more-than-summary" not in sample


@then("the key names the standard behind each version")
def step_key(context):
    key = context.replay["key"]
    assert len(key) == 2 and all({entry["A"], entry["B"]} == {"summary", "more-than-summary"} for entry in key.values())


@then("the replay's cost is within {ceiling} dollars and it stopped for cost")
def step_cost(context, ceiling):
    assert context.replay["costUsd"] <= float(ceiling) and context.replay["arms"]["summary"]["stoppedBy"] == "cost"


@then("a replay with no ceiling is refused")
def step_refused_ceiling(context):
    from test_idea_standard_replay import TwoWays, run

    try:
        run(context.replay_client, TwoWays(), max_cost_usd=0)
    except ValueError:
        return
    raise AssertionError("a replay without a ceiling started")
