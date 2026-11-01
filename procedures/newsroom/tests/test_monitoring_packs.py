"""The router task with context packs on: one read of the publication, one ordered queue of packs and single items, one cost meter, one review
(src/papyrus_content/monitoring_stories.py, features_backend/idea-context-packs.feature). The model, the pages and the backend are fakes; filing an
idea as an Item is replaced by a recorder (it is tested in test_idea_pack_stories.py and test_idea_items.py)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_monitoring_router as tr  # noqa: E402
from field_recorder import FieldRecorder  # noqa: E402
from ideas_fixtures import NOW, entity, reference  # noqa: E402
from test_idea_pack_stories import idea as pack_idea  # noqa: E402
from test_monitor_stories import MonitorClient, StoryModel, pages, provenance  # noqa: E402
from test_monitoring_stories import PUBLICATION, fake_idea_sink, iam_auth, quiet_gate, router, run_task  # noqa: E402,F401  (the fixtures are the task tests' own)
from papyrus_content.ideas import pack_stories  # noqa: E402

MONITOR_WINDOW_DAYS = 70


def days_before(days):
    from datetime import timedelta

    return (NOW - timedelta(days=days)).isoformat().replace("+00:00", "Z")


def human_vote(number, days_ago, concept):
    row = reference(number, days_ago=days_ago + 1)
    row.update({"curationActorKind": "human", "curationStatusUpdatedAt": days_before(days_ago), "curationStatusUpdatedBy": "editor-a",
                "curationStatusReason": "Worth following", "sourcePublishedAt": days_before(days_ago + 2)})
    return row, [entity(row, concept)]


class PackWorld(MonitorClient):
    """A backend with monitored References (r1..rN), the site's human votes, concepts, message threads and existing ideas."""

    def __init__(self, *args, threads=(), thread_messages=None, nodes=(), messages=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.threads = list(threads)
        self.thread_messages = thread_messages or {}
        self.nodes = list(nodes)
        self.messages = messages or {}

    def list_records(self, model):
        if model == "MessageThread":
            return list(self.threads)
        if model == "SemanticNode":
            return list(self.nodes)
        return super().list_records(model)

    def get_record(self, model, record_id):
        return dict(self.messages[record_id]) if model == "Message" and record_id in self.messages else super().get_record(model, record_id)

    def graphql(self, query, variables=None):
        if "listMessagesByThreadAndCreatedAt" in query:
            return {"listMessagesByThreadAndCreatedAt": {"items": self.thread_messages.get((variables or {})["threadId"], []), "nextToken": None}}
        return super().graphql(query, variables)


VOICE_NODE = {"id": "node-voice-v1", "lineageId": "concept-voice", "versionState": "current", "status": "accepted", "nodeKey": "concept--voice-cloning",
              "nodeKind": "concept", "displayName": "Voice cloning", "description": "Synthetic voices."}


def pack_world(monitored=2, *, lively=(), burst=9, ideas=()):
    """``monitored`` monitored References; ``burst`` human accepts of the voice concept in the last days after twenty-one steady accepts of another one;
    a lively thread of Messages on each monitored Reference number in ``lively``; ``ideas`` existing idea Items."""
    monitored_rows, base = [], None
    from test_monitor_stories import world

    monitored_rows, base = world(monitored)
    rows, relations, threads, thread_messages = list(monitored_rows), dict(base.relations), [], {}
    for number in range(1, 22):
        row, links = human_vote(100 + number, 70 - number * 3, "concept-other")
        rows.append(row)
        relations[row["lineageId"]] = links
    for number in range(1, burst + 1):
        row, links = human_vote(200 + number, 1 + number * 0.1, "concept-voice")
        rows.append(row)
        relations[row["lineageId"]] = links
    for number in lively:
        lineage = monitored_rows[number - 1]["lineageId"]
        threads.append({"id": f"thread-{number}", "threadKind": "reference_conversation", "primaryAnchorKind": "reference", "primaryAnchorKey": f"reference#{lineage}"})
        thread_messages[f"thread-{number}"] = [
            {"id": f"m-{number}-{count}", "threadId": f"thread-{number}", "status": "active", "role": "human", "authorKind": "staff", "content": f"Comment {count}",
             "createdAt": days_before(0.5 + count * 0.1)} for count in range(6)]
    return PackWorld(references=rows, relations=relations, incoming=base.incoming, sections=("Analysis", "Tools"), threads=threads,
                     thread_messages=thread_messages, nodes=[VOICE_NODE], items=list(ideas))


class RouterModel(StoryModel):
    """Answers a single-item request as StoryModel does and a pack request with two ideas that each cite two accepted References."""

    def __init__(self, ideas=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.pack_requests = []
        self.order = []   # "pack" or "item" for each request, in the order the model was asked
        self.pack_ideas = ideas or [pack_idea("Synthetic voices spread through newsrooms", ["R1", "R2", "C1"]),
                                    pack_idea("Consent rules lag behind cloning tools", ["R3", "R4"], dek="Editors keep returning to the same open question.")]

    def __call__(self, url, headers, payload):
        if payload["instructions"].startswith("You propose story ideas for a publication from a theme"):
            self.pack_requests.append(payload)
            self.order.append("pack")
            return {"output_text": json.dumps({"ideas": self.pack_ideas}), "usage": self.usage}
        self.order.append("item")
        return super().__call__(url, headers, payload)


class FilingRecorder:
    """Stands in for filing a pack idea as an Item: records the idea, files nothing."""

    def __init__(self, monkeypatch, fail_after=None) -> None:
        self.filed = []
        self.fail_after = fail_after
        monkeypatch.setattr(pack_stories, "file_idea_item", self.file)
        monkeypatch.setattr(pack_stories, "link_item_concept", lambda *args, **kwargs: None)

    def file(self, client, record, *, actor, source_text_reader=None, gate=None, **kwargs):
        if self.fail_after is not None and len(self.filed) >= self.fail_after:
            raise RuntimeError("AccessDenied")
        self.filed.append(record)
        return {"created": True, "itemId": f"item-{len(self.filed)}-v1", "lineageId": f"item-{len(self.filed)}", "linked": [t["id"] for t in record["targets"]], "check": None}


PACKS_ON = {"singleItem": True, "contextPacks": {"enabled": True}}


def run_packs(client, model, settings=None, **options):
    table, store = router(settings={PUBLICATION: settings or PACKS_ON})
    return run_task(store, {PUBLICATION: client}, model, **options)


def pack_lines(lines):
    return lines[PUBLICATION]


def test_one_run_walks_one_queue_of_a_pack_and_a_single_item_and_raises_one_review(monkeypatch):
    filing = FilingRecorder(monkeypatch)
    client = pack_world(2, lively=(1,))
    model = RouterModel()
    result, lines = run_packs(client, model)
    line = pack_lines(lines)
    assert (line["packs"], line["ideasFromPacks"], line["packsSkippedNoNewEvidence"]) == (1, 2, 0)
    assert line["packDetails"] == [{"signal": "acceptance", "anchor": "concept-voice", "correctedPValue": pytest.approx(5.9e-05, rel=0.2), "ideas": 2}]
    assert line["drafted"] == 3 and line["status"] == "complete" and line["stoppedBy"] is None   # two ideas from the pack and the one single item the signals single out
    assert line["candidates"] == 1 and len(model.pack_requests) == 1 and len(model.requests) == 1
    assert len(filing.filed) == 2 and len(client.filed) == 1
    assert {record["origin"] for record in filing.filed} == {"context-pack"}
    assert len(client.reviews) == 1   # one soft review request for the run, packs and single items together
    review = next(iter(client.reviews.values()))
    assert json.dumps(review).count("item-1") and json.dumps(review).count("item-2")   # the ideas the pack filed are among the review's links
    assert result["monitorStories"][PUBLICATION]["ideasFromPacks"] == 2


def test_a_reference_the_signals_do_not_single_out_is_not_a_single_item_candidate(monkeypatch):
    FilingRecorder(monkeypatch)
    client = pack_world(3, lively=(2,))
    _, lines = run_packs(client, RouterModel())
    line = pack_lines(lines)
    assert line["candidates"] == 1 and line["drafted"] == 3
    assert {json.loads(row["evidence"])["source"].split(": ")[1] for row in client.filed} == {"https://www.example2.org/post"}


def existing_idea_from(client, state_stage="idea"):
    """An idea Item that records the acceptance pack's anchor, window and References: what a first run leaves behind."""
    from papyrus_content.ideas.context import load_context
    from papyrus_content.ideas.context_packs import evidence_of
    from papyrus_content.ideas.signal_queue import prepare_signal_run

    context = load_context(client, now=NOW)
    run = prepare_signal_run(client, site=PUBLICATION, context=context, now=NOW, signals=None, single_items=True)
    front = "generated:\n  origin: context-pack\n  targets: []\n  evidence: " + json.dumps(evidence_of(run.packs[0])) + "\n"
    return {"id": "item-idea-1-v1", "lineageId": "item-idea-1", "versionState": "current", "stage": state_stage, "title": "Earlier theme idea", "deck": "",
            "versionCreatedAt": days_before(1), "metadata": json.dumps({"frontMatterYaml": front})}


def test_an_anchor_that_already_has_an_idea_is_not_offered_again_without_new_evidence(monkeypatch):
    filing = FilingRecorder(monkeypatch)
    client = pack_world(2, lively=(1,))
    client.items.append(existing_idea_from(client))
    model = RouterModel()
    _, lines = run_packs(client, model)
    line = pack_lines(lines)
    assert (line["packs"], line["packsSkippedNoNewEvidence"], line["ideasFromPacks"]) == (0, 1, 0)
    assert model.pack_requests == [] and filing.filed == []   # nothing was asked of the model for the pack
    assert line["drafted"] == 1   # the single item still goes


def test_a_second_run_does_not_repeat_the_first_runs_pack_ideas(monkeypatch):
    filing = FilingRecorder(monkeypatch)
    client = pack_world(2, lively=(1,))
    table, store = router(settings={PUBLICATION: PACKS_ON})
    model = RouterModel()
    run_task(store, {PUBLICATION: client}, model)
    first = list(filing.filed)
    client.items.append({"id": "item-1-v1", "lineageId": "item-1", "versionState": "current", "stage": "idea", "title": first[0]["title"], "deck": "",
                         "versionCreatedAt": days_before(0), "metadata": json.dumps({"frontMatterYaml": "generated:\n  origin: context-pack\n  targets: []\n  evidence: " + json.dumps(first[0]["evidence"]) + "\n"})})
    _, lines = run_task(store, {PUBLICATION: client}, model)
    assert pack_lines(lines)["packsSkippedNoNewEvidence"] == 1 and len(model.pack_requests) == 1 and len(filing.filed) == 2


def test_single_item_false_runs_the_packs_only(monkeypatch):
    filing = FilingRecorder(monkeypatch)
    client = pack_world(2, lively=(1,))
    model = RouterModel()
    _, lines = run_packs(client, model, {"singleItem": False})
    line = pack_lines(lines)
    assert line["drafted"] == 2 and line["candidates"] == 0 and model.requests == [] and len(filing.filed) == 2


def test_context_packs_off_with_single_item_on_is_the_task_as_it_was(monkeypatch):
    filing = FilingRecorder(monkeypatch)
    client = pack_world(2, lively=(1,))
    model = RouterModel()
    _, lines = run_packs(client, model, {"contextPacks": {"enabled": False}})
    line = pack_lines(lines)
    assert line["drafted"] == 2 and (line["packs"], line["ideasFromPacks"]) == (0, 0)   # the two References with source text, ranked by the Cyclotron
    assert model.pack_requests == [] and filing.filed == []


def test_both_off_does_nothing(monkeypatch):
    FilingRecorder(monkeypatch)
    client = pack_world(2, lively=(1,))
    model = RouterModel()
    _, lines = run_packs(client, model, {"singleItem": False, "contextPacks": {"enabled": False}})
    assert pack_lines(lines)["drafted"] == 0 and model.requests == [] and model.pack_requests == []


def test_a_signal_the_publication_did_not_ask_for_builds_no_pack(monkeypatch):
    FilingRecorder(monkeypatch)
    client = pack_world(2, lively=(1,))
    model = RouterModel()
    _, lines = run_packs(client, model, {"contextPacks": {"enabled": True, "signals": ["conversation"]}})
    line = pack_lines(lines)
    assert line["packs"] == 0 and model.pack_requests == [] and line["drafted"] == 1
    _, lines = run_packs(pack_world(2, lively=(1,)), RouterModel(), {"contextPacks": {"enabled": True, "signals": ["acceptance", "hub"]}})
    assert pack_lines(lines)["packs"] == 1


def test_packs_and_single_items_share_one_cost_meter_and_one_cost_stop(monkeypatch):
    filing = FilingRecorder(monkeypatch)
    client = pack_world(2, lively=(1,))
    model = RouterModel(input_tokens=400_000, output_tokens=6_000)
    table, store = router(settings={PUBLICATION: PACKS_ON})
    from functools import partial

    from papyrus_content.monitoring_stories import run_publication
    from test_monitoring_stories import pages

    _, lines = run_task_with(store, client, model, partial(run_publication, fetch=pages(1, 2), explorer=None, maximum_cost_usd=0.0435))
    line = pack_lines(lines)
    assert line["stoppedBy"] == "cost" and line["status"] == "stopped"
    assert line["costUsd"] == pytest.approx(0.043) and line["drafted"] == 2   # the pack went first and spent 0.043; the single item's estimate no longer fitted under 0.0435
    assert len(client.filed) == 0 and len(filing.filed) == 2


def run_task_with(store, client, model, drafter):
    import io
    from contextlib import redirect_stdout

    from papyrus_content.monitoring_router import run_router
    from test_monitoring_router import Delivery
    from ideas_fixtures import NOW as now

    endpoints = {tr.ENDPOINT.replace("abc123", "api0"): client}
    out = io.StringIO()
    with redirect_stdout(out):
        result = run_router(store, "hn", now=now.timestamp(), task="monitor-stories", appsync=lambda endpoint: endpoints[endpoint], deliver=Delivery(),
                            time_left=lambda: 1e9, story_transport=model, story_drafter=drafter)
    return result, {line["publicationId"]: line for line in map(json.loads, (l for l in out.getvalue().splitlines() if l.startswith('{"monitorStories"')))}


def test_the_queue_is_walked_in_order_and_the_model_is_asked_pack_first_then_item(monkeypatch):
    FilingRecorder(monkeypatch)
    model = RouterModel()
    run_packs(pack_world(2, lively=(1,)), model)
    assert model.order == ["pack", "item"]   # the acceptance pack is the more surprising of the two


def test_running_out_of_time_between_the_pack_and_the_item_stops_the_publication_and_keeps_the_pack_ideas(monkeypatch):
    filing = FilingRecorder(monkeypatch)
    model = RouterModel()
    from functools import partial

    from papyrus_content.monitoring_stories import run_publication
    from test_monitoring_stories import pages

    client = pack_world(2, lively=(1,))
    table, store = router(settings={PUBLICATION: PACKS_ON})

    def drafter(client, publication, **options):
        stop = lambda: bool(model.order)   # noqa: E731 - out of time as soon as the pack has been asked
        return partial(run_publication, fetch=pages(1, 2), explorer=None)(client, publication, **{**options, "out_of_time": stop})

    _, lines = run_task_with(store, client, model, drafter)
    line = pack_lines(lines)
    assert line["stoppedBy"] == "time" and line["status"] == "stopped"
    assert model.order == ["pack"] and line["ideasFromPacks"] == 2 and len(filing.filed) == 2 and len(client.filed) == 0


def test_a_filing_error_on_a_pack_idea_stops_the_publication_before_more_money_is_spent(monkeypatch):
    FilingRecorder(monkeypatch, fail_after=0)
    model = RouterModel()
    _, lines = run_packs(pack_world(2, lively=(1,)), model)
    line = pack_lines(lines)
    assert line["stoppedBy"] == "file_error" and "AccessDenied" in line["fileError"]
    assert model.order == ["pack"]   # the single item was not asked for


def test_a_pack_the_model_fails_on_is_recorded_and_the_run_goes_on(monkeypatch):
    FilingRecorder(monkeypatch)
    from papyrus_content.ideas import synthesis

    class Failing(RouterModel):
        def __call__(self, url, headers, payload):
            if payload["instructions"].startswith("You propose story ideas for a publication from a theme"):
                self.order.append("pack")
                raise synthesis.SynthesisError("The model returned no complete answer.")
            return super().__call__(url, headers, payload)

    model = Failing()
    _, lines = run_packs(pack_world(2, lively=(1,)), model)
    line = pack_lines(lines)
    assert line["ideasFromPacks"] == 0 and line["failedTheCheck"] == 1 and line["drafted"] == 1   # the pack failed; the single item was drafted


def test_an_idea_with_one_reference_is_dropped_and_the_pack_goes_on(monkeypatch):
    filing = FilingRecorder(monkeypatch)
    model = RouterModel(ideas=[pack_idea("Only one source", ["R1"]), pack_idea("Consent rules lag behind cloning tools", ["R3", "R4"])])
    _, lines = run_packs(pack_world(2), model)
    line = pack_lines(lines)
    assert line["ideasFromPacks"] == 1 and line["failedTheCheck"] == 1 and len(filing.filed) == 1


def test_the_monitor_stories_setting_takes_single_item_and_context_packs_and_nothing_numeric():
    from papyrus_content.monitoring_stories import validate_monitor_stories

    assert validate_monitor_stories("p", {"singleItem": False})["singleItem"] is False
    assert validate_monitor_stories("p", {"contextPacks": {"enabled": False}})["contextPacks"] == {"enabled": False, "signals": None}
    assert validate_monitor_stories("p", {"contextPacks": {"signals": ["conversation", "acceptance"]}})["contextPacks"] == {"enabled": True, "signals": ["conversation", "acceptance"]}
    for signal in ("conversation", "acceptance", "hub", "cluster", "resurfaced"):
        assert validate_monitor_stories("p", {"contextPacks": {"signals": [signal]}})["contextPacks"]["signals"] == [signal]
    for bad in ({"singleItem": "yes"}, {"contextPacks": "on"}, {"contextPacks": {"limit": 3}}, {"contextPacks": {"packs": 3}}, {"contextPacks": {"enabled": 1}},
                {"contextPacks": {"signals": []}}, {"contextPacks": {"signals": ["item"]}}, {"contextPacks": {"signals": ["hub", "hub"]}}, {"contextPacks": {"signals": "hub"}},
                {"maximumPacks": 3}):
        with pytest.raises(ValueError):
            validate_monitor_stories("p", bad)
    again = validate_monitor_stories("p", {"singleItem": False, "contextPacks": {"signals": ["hub"]}})
    assert validate_monitor_stories("p", again) == again   # the normalized setting validates to itself


def test_the_example_router_config_validates():
    from papyrus_content.monitoring_router import validate_router_config

    root = Path(__file__).resolve().parents[3]
    example = json.loads((root / "docs" / "monitoring-router-config.example.json").read_text())
    publications = validate_router_config(example)["publications"]
    assert [p["monitorStories"]["contextPacks"]["signals"] for p in publications] == [None, ["conversation", "acceptance"], None]


# --- the command: papyrus ideas monitor-stories ------------------------------------------------------------------------------------------


def run_command(argv, client, model, monkeypatch, directory):
    import io
    import os
    import tempfile
    from contextlib import redirect_stderr, redirect_stdout
    from unittest import mock

    from papyrus import cli as papyrus_cli
    from papyrus_content.ideas import commands
    from papyrus_content.link_exploration import Exploration
    from papyrus_content.ideas import monitor_stories as stories
    from fake_idea_store import FakeIdeaStore
    from test_monitor_stories import PAGE, FixedClock

    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(commands, "create_authoring_client", return_value=(client, {})), \
         mock.patch.object(commands, "_idea_store", side_effect=lambda name, held: FakeIdeaStore(held) if name == "items" else None), \
         mock.patch.object(commands.synthesis, "openai_transport", return_value=model), \
         mock.patch.object(commands.monitor_stories, "fetch_source", side_effect=lambda url: PAGE), \
         mock.patch.object(commands.monitor_stories, "explore_item", side_effect=lambda item: Exploration(
             True, item.url, stories.read_source_text(item.url, lambda url: PAGE), "direct", readable=True)), \
         mock.patch("papyrus_content.cli.load_dotenv"), mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), \
         mock.patch.object(commands, "datetime", FixedClock), mock.patch.object(commands.monitor_stories, "datetime", FixedClock), \
         redirect_stdout(out), redirect_stderr(err):
        code = papyrus_cli.main(["--allow-cross-root", "ideas", "monitor-stories", "--site", PUBLICATION, "--store", "items", "--out", str(directory), *argv])
    return code, out.getvalue() + err.getvalue()


def test_a_dry_run_prints_the_packs_and_writes_nothing(monkeypatch, tmp_path):
    filing = FilingRecorder(monkeypatch)
    client = pack_world(2, lively=(1,))
    model = RouterModel()
    code, output = run_command(["--dry-run", "--limit", "5"], client, model, monkeypatch, tmp_path)
    assert code == 0, output
    assert "packs\toffered 1\tskipped for no new evidence 0" in output
    assert "pack\tacceptance\tconcept-voice\tcorrected p " in output and "9 accepted References\tdates: ingestion\t2 ideas would be filed" in output
    assert "would file 3" in output and "context-pack" in output
    assert filing.filed == [] and client.filed == [] and client.reviews == {}   # nothing was written, no review was requested
    assert not (tmp_path / "runs").exists()


def test_packs_only_asks_only_for_pack_ideas_and_single_only_asks_for_none(monkeypatch, tmp_path):
    FilingRecorder(monkeypatch)
    model = RouterModel()
    code, output = run_command(["--dry-run", "--packs-only", "--limit", "5"], pack_world(2, lively=(1,)), model, monkeypatch, tmp_path)
    assert code == 0, output
    assert model.order == ["pack"] and "would file 2" in output
    model = RouterModel()
    code, output = run_command(["--dry-run", "--single-only", "--limit", "5"], pack_world(2, lively=(1,)), model, monkeypatch, tmp_path)
    assert code == 0, output
    assert set(model.order) == {"item"} and "packs\t" not in output   # single items ranked by the Cyclotron, and no pack


def test_the_two_flags_cannot_be_combined_and_packs_need_the_item_store(monkeypatch, tmp_path):
    FilingRecorder(monkeypatch)
    code, output = run_command(["--packs-only", "--single-only"], pack_world(2), RouterModel(), monkeypatch, tmp_path)
    assert code != 0 and "cannot be used together" in output
    code, output = run_command(["--packs-only", "--store", "json"], pack_world(2), RouterModel(), monkeypatch, tmp_path)
    assert code != 0


# --- IAM: RouterIdeaPolicy grants everything the pack path asks of a publication's API -------------------------------------------------------

ROUTER_IDEA_POLICY_FIELDS = {
    ("Query", "getItem"), ("Query", "getMessage"), ("Query", "getReference"), ("Query", "getSemanticRelation"), ("Query", "listItems"),
    ("Query", "listItemsByLineageAndVersion"), ("Query", "listMessageThreads"), ("Query", "listMessagesByThreadAndCreatedAt"),
    ("Query", "listReferenceAttachmentsByReferenceLineageAndSortKey"), ("Query", "listReferencesByCurationStatusKeyAndUpdatedAt"),
    ("Query", "listReferencesByLineageAndVersion"), ("Query", "listSemanticNodes"), ("Query", "listSemanticRelationsByObjectState"),
    ("Query", "listSemanticRelationsBySubjectState"), ("Mutation", "createItem"), ("Mutation", "createSemanticRelation"), ("Mutation", "updateItem"),
}   # the pack path's own fields (the gate's fields are checked by test_the_router_idea_policy_grants_the_item_and_gate_fields_and_the_key_parameter)


def idea_policy_fields():
    import re

    text = (Path(__file__).resolve().parents[3] / "infra" / "monitoring" / "papyrus-monitoring.yaml").read_text()
    start = text.index("  RouterIdeaPolicy:")
    policy = text[start:text.index("\n\n  ", start)]
    return set(re.findall(r"apis/\*/types/(Query|Mutation)/fields/(\w+)\"", policy))


def test_the_router_idea_policy_grants_every_field_the_signals_the_lookups_and_the_pack_ideas_ask_for(monkeypatch):
    import test_idea_pack_stories as pack_support
    from papyrus_content.ideas.signal_queue import prepare_signal_run
    from papyrus_content.ideas.context import load_context

    recorder = FieldRecorder(pack_world(2, lively=(1,)))
    recorder.inner.messages["m-summary"] = {"id": "m-summary", "messageKind": "reference_summary", "status": "active", "summary": "A short summary."}
    recorder.inner.incoming = {lineage: [{"relationState": "current", "relationTypeKey": "reference_summary_200_tokens", "subjectKind": "message", "subjectId": "m-summary",
                                           "createdAt": days_before(1)}] for lineage in (row["lineageId"] for row in recorder.inner.references)}
    run = prepare_signal_run(recorder, site=PUBLICATION, context=load_context(recorder, now=NOW), now=NOW, signals=None, single_items=True)
    assert run.packs and run.packs[0].references[0]["summary"] == "A short summary."   # the lookups read the summary Message
    pack = pack_support.acceptance_pack()
    filing_client = FieldRecorder(pack_support.backend(pack))
    result = pack_support.run(pack, filing_client, pack_support.transport_of(pack_support.idea("Synthetic voices spread through newsrooms", ["R1", "R2", "C1"])))
    assert result.filed_count == 1
    recorded = recorder.fields | filing_client.fields
    reading = {("Query", "listMessageThreads"), ("Query", "listMessagesByThreadAndCreatedAt"), ("Query", "listReferencesByCurationStatusKeyAndUpdatedAt"),
               ("Query", "listSemanticRelationsBySubjectState"), ("Query", "listSemanticRelationsByObjectState"), ("Query", "listItems"), ("Query", "listSemanticNodes"),
               ("Query", "getMessage")}
    assert reading <= recorded
    granted = idea_policy_fields()
    assert ROUTER_IDEA_POLICY_FIELDS <= granted, sorted(ROUTER_IDEA_POLICY_FIELDS - granted)
    already_granted_per_api = {("Query", "itemBySlug"), ("Query", "listAutomations"), ("Query", "listNewsroomSections"), ("Query", "listStoryDrafts"),
                               ("Mutation", "createReviewRequest"), ("Query", "getReviewRequest"), ("Mutation", "fileProposal")}
    assert recorded <= granted | already_granted_per_api, sorted(recorded - granted - already_granted_per_api)


# --- the router zip carries the pack modules --------------------------------------------------------------------------------------------


def test_the_router_zip_closure_carries_the_pack_modules_and_they_import_with_only_the_standard_library_and_pyyaml(tmp_path):
    """The zip is the import closure of the router; copy exactly that closure (the wheels the editorial gate needs are not part of this check) and import
    the pack path in an isolated interpreter that must not load pydantic, biblicus, httpx or tiktoken."""
    import importlib.util
    import shutil
    import subprocess

    import yaml

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("monitoring_build", root / "infra/monitoring/build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    modules = build.router_modules()
    needed = ["ideas/signal_inputs", "ideas/signal_queue", "ideas/context_packs", "ideas/item_signals", "ideas/pack_stories", "monitoring_stories"]
    assert set(needed) <= set(modules), sorted(set(needed) - set(modules))
    task = tmp_path / "task"
    for name in ["__init__", *modules]:
        target = task / "papyrus_content" / f"{name}.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(root / "src" / "papyrus_content" / f"{name}.py", target)
    shutil.copytree(Path(yaml.__file__).parent, task / "yaml")
    script = ("import sys; sys.path.insert(0, sys.argv[1])\n"
              "from papyrus_content.ideas import signal_inputs, signal_queue, context_packs, item_signals, pack_stories\n"
              "from papyrus_content import monitoring_stories\n"
              "assert monitoring_stories.validate_monitor_stories('p', None)['contextPacks']['enabled']\n"
              "assert not any(m in sys.modules for m in ('pydantic', 'biblicus', 'httpx', 'tiktoken'))\n")
    done = subprocess.run([sys.executable, "-I", "-S", "-c", script, str(task)], capture_output=True, text=True, cwd=tmp_path, env={"PAPYRUS_ROOT": str(task)})
    assert done.returncode == 0, done.stderr[-800:]


def test_a_lively_thread_on_one_reference_yields_a_pack_with_related_accepted_references_and_the_agent_files_an_idea():
    import test_idea_pack_stories as pack_support
    from papyrus_content.ideas.context_packs import build_packs
    from papyrus_content.ideas.signal_inputs import ConceptLink
    from test_idea_context_packs import LOOKUPS, inputs, lit_thread_messages, vote

    others = [vote(f"other-{n}", 10 + n) for n in range(1, 4)]
    signals = inputs(messages=lit_thread_messages(), votes=[vote("ref-1", 3), *others],
                     links=[ConceptLink(lineage, "concept-voice", "mentions") for lineage in ("ref-1", "other-1", "other-2", "other-3")])
    [pack] = [p for p in build_packs(signals, LOOKUPS, now=NOW) if p.signal_type == "conversation"]
    assert pack.accepted_lineage_ids[0] == "ref-1" and len(pack.accepted_lineage_ids) == 4
    assert [row.get("relation") for row in pack.references] == [None, "shared concept #voice-cloning", "shared concept #voice-cloning", "shared concept #voice-cloning"]
    client = pack_support.backend(pack)
    result = pack_support.run(pack, client, pack_support.transport_of(pack_support.idea("Editors keep returning to one voice story", ["R1", "R2"])))
    assert result.filed_count == 1
