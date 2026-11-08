"""Topic modeling on recent References: the date index, the windows, the operation table and what is generated from it
(features_backend/topics-model.feature has the narrative). Nothing here calls a model, Biblicus or the network."""

from __future__ import annotations

import io
import json
import logging
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from papyrus_content import graphql_authoring as g
from papyrus_content.ids import deterministic_uuid
from papyrus_content.images.handlers import Caller
from papyrus_content.topics import cli as topics_cli
from papyrus_content.topics import generate, mcp
from papyrus_content.topics.cli_generated import COMMANDS
from papyrus_content.topics.engine import BiblicusTopicEngine, TopicEngineError, TopicDocument
from papyrus_content.topics.fakes import FakeTopicEngine
from papyrus_content.topics.handlers import execute, with_client
from papyrus_content.topics.model import TopicParams, run_topics, scaled_cluster_size, trend
from papyrus_content.topics.operations import BY_NAME, OPERATIONS
from papyrus_content.topics.select import INDEX, select_references
from papyrus_content.topics.store import FileTopicStore, MemoryTopicStore
from papyrus_content.topics.windows import current_window, previous_window

REPO = Path(__file__).resolve().parents[3]
CORPUS = "knowledge-corpus-demo"
AS_OF = date(2026, 11, 8)


# --- a backend that answers the date index the way the real one does -----------------------------------------------------------------------------

class FakeClient:
    tenant_id = None

    def __init__(self, rows):
        self.rows = rows
        self.asked: list[tuple] = []

    def list_by_index(self, name, key, **_):
        assert name == "knowledgeCorporaByRoleAndName"
        return [{"id": CORPUS, "name": "Demo", "role": "canonical"}]

    def get_record(self, model, record_id):
        return {"id": "section-security", "title": "Security"} if (model, record_id) == ("NewsroomSection", "section-security") else None

    def safe_list_records(self, model):
        return []

    def iterate_index_range(self, index, key, low, high, *, page_size=100):
        self.asked.append((index, key, low, high))
        inside = [row for row in self.rows if row["corpusId"] == key and row.get("sourcePublishedAt") and low <= row["sourcePublishedAt"] <= high]
        yield from sorted(inside, key=lambda row: row["sourcePublishedAt"], reverse=True)


def reference(number, title, day, **extra):
    return {"id": f"ref-{number}", "lineageId": f"lin-{number}", "versionState": "current", "corpusId": CORPUS, "title": title, "curationStatus": "accepted",
            "sourcePublishedAt": f"2026-{day}T09:00:00Z", "updatedAt": "2026-11-08T00:00:00Z", "sourceUri": f"https://example.invalid/{number}", **extra}


def library():
    """Ransomware stories pile up in the current window (10-26 to 11-08), voice stories were the earlier ones (10-12 to 10-25)."""
    rows, number = [], 0
    for theme, now, before in (("ransomware attack hospital", 24, 6), ("voice cloning speech", 10, 20)):
        for day, count in (("11-03", now), ("10-20", before)):
            for _ in range(count):
                number += 1
                rows.append(reference(number, f"{theme} {number}", day))
    return rows


def params(**extra):
    return TopicParams(corpus_id=CORPUS, as_of=AS_OF, **extra)


# --- windows ------------------------------------------------------------------------------------------------------------------------------------

def test_a_window_counts_whole_days_back_from_the_last_day_and_the_previous_one_ends_the_day_before():
    now = current_window("14d", AS_OF)
    assert now.describe() == {"start": "2026-10-26", "end": "2026-11-08", "days": 14}
    assert previous_window(now).describe() == {"start": "2026-10-12", "end": "2026-10-25", "days": 14}
    assert current_window(None, AS_OF).days == 14 and current_window("7d", AS_OF).days == 7 and current_window("28d", AS_OF).days == 28


def test_a_window_holds_a_date_only_source_date_on_its_first_and_last_day_and_nothing_outside_it():
    now = current_window("7d", AS_OF)
    assert now.contains("2026-11-02") and now.contains("2026-11-08") and now.contains("2026-11-08T23:00:00Z") and now.contains("2026-11-02T00:00:00Z")
    assert not now.contains("2026-11-01") and not now.contains("2026-11-09") and not now.contains(None) and not now.contains("")


# --- the date index -----------------------------------------------------------------------------------------------------------------------------

def test_the_date_index_is_registered_in_the_client_and_in_both_schema_files_and_is_read_by_range_newest_first():
    definition = g.INDEX_DEFINITIONS[INDEX]
    assert (definition["field"], definition["partitionKey"], definition["sortKey"]) == ("listReferencesByCorpusAndSourcePublishedAt", "corpusId", "sourcePublishedAt")
    line = 'index("corpusId").sortKeys(["sourcePublishedAt"]).queryField("listReferencesByCorpusAndSourcePublishedAt")'
    for name in ("schema.ts", "resource.ts"):
        assert line in (REPO / "amplify" / "data" / name).read_text(encoding="utf-8")

    asked = []

    class Client(g.PapyrusGraphQLAuthoringClient):
        def __init__(self):
            self.tenant_id = None

        def graphql(self, query, variables=None):
            asked.append((query, variables))
            first = variables["nextToken"] is None
            return {"listReferencesByCorpusAndSourcePublishedAt": {"items": [{"id": "a"}, None] if first else [{"id": "b"}], "nextToken": "more" if first else None}}

    rows = list(Client().iterate_index_range(INDEX, CORPUS, "2026-10-26", "2026-11-08T23:59:59.999Z"))
    assert [row["id"] for row in rows] == ["a", "b"] and len(asked) == 2
    query, variables = asked[0]
    assert "sortDirection: DESC" in query and "sourcePublishedAt: $sortRange" in query and "ModelStringKeyConditionInput" in query
    assert variables["corpusId"] == CORPUS and variables["sortRange"] == {"between": ["2026-10-26", "2026-11-08T23:59:59.999Z"]}


def test_a_selection_asks_the_index_for_the_window_only_and_keeps_current_accepted_and_pending_rows():
    rows = [reference(1, "kept", "11-05"), reference(2, "pending", "11-06", curationStatus="pending"), reference(3, "rejected", "11-06", curationStatus="rejected"),
            reference(4, "archived", "11-06", curationStatus="archived"), reference(5, "old version", "11-06", versionState="superseded"),
            reference(6, "too early", "10-01"), {**reference(7, "no date", "11-01"), "sourcePublishedAt": None}]
    client = FakeClient(rows)
    selection = select_references(client, CORPUS, current_window("14d", AS_OF))
    assert sorted(row["id"] for row in selection.rows) == ["ref-1", "ref-2"]
    assert client.asked == [(INDEX, CORPUS, "2026-10-26", "2026-11-08T23:59:59.999Z")]
    assert [row["id"] for row in select_references(client, CORPUS, current_window("14d", AS_OF), states=("rejected",)).rows] == ["ref-3"]


def test_a_section_and_a_monitor_narrow_the_returned_rows():
    rows = [reference(1, "a", "11-05", curationSectionId="section-security", discoveredByMonitorId="hn"), reference(2, "b", "11-05", curationSectionId="section-voice"),
            reference(3, "c", "11-05", discoveredByMonitorId="hn")]
    window = current_window("14d", AS_OF)
    assert [row["id"] for row in select_references(FakeClient(rows), CORPUS, window, section_id="section-security").rows] == ["ref-1"]
    assert sorted(row["id"] for row in select_references(FakeClient(rows), CORPUS, window, monitor="hn").rows) == ["ref-1", "ref-3"]


def test_max_references_is_a_safety_stop_that_says_so_in_the_result_and_in_the_log(caplog):
    rows = [reference(number, f"story {number}", "11-05") for number in range(1, 11)]
    with caplog.at_level(logging.WARNING, logger="papyrus.topics"):
        selection = select_references(FakeClient(rows), CORPUS, current_window("14d", AS_OF), max_references=4)
    assert len(selection.rows) == 4 and selection.stopped
    assert selection.warnings[0]["code"] == "max_references_reached" and "max_references is 4" in selection.warnings[0]["message"]
    assert "max_references is 4" in caplog.text
    assert not select_references(FakeClient(rows), CORPUS, current_window("14d", AS_OF)).stopped


# --- the model ----------------------------------------------------------------------------------------------------------------------------------

def test_the_smallest_topic_scales_with_the_number_of_references_and_never_drops_under_three():
    assert [scaled_cluster_size(count) for count in (0, 4, 9, 36, 60, 400, 10000)] == [3, 3, 3, 6, 8, 20, 100]


def test_a_trend_compares_a_topics_share_of_each_window():
    assert trend(24, 6, 34, 26) == "rising"
    assert trend(10, 20, 34, 26) == "falling"
    assert trend(5, 4, 20, 16) == "steady"
    assert trend(7, 0, 20, 16) == "new"
    assert trend(0, 0, 20, 16) == "steady"


def run(rows=None, store=None, engine=None, **extra):
    engine = engine or FakeTopicEngine()
    return run_topics(FakeClient(rows if rows is not None else library()), params(**extra), engine=engine, store=store or MemoryTopicStore()), engine


def test_a_run_gives_topics_with_counts_marks_representatives_and_a_saved_id():
    outcome, _ = run()
    result = outcome.result
    assert result["window"] == {"start": "2026-10-26", "end": "2026-11-08", "days": 14} and result["compareTo"]["end"] == "2026-10-25"
    assert (result["referencesInWindow"], result["referencesInPreviousWindow"], result["minClusterSize"]) == (34, 26, 8)
    assert result["savedId"].startswith("topics-") and result["cached"] is False
    first, second = result["topics"]
    assert (first["topicId"], first["count"], first["previousCount"], first["trend"], first["mark"]) == ("t1", 24, 6, "rising", "▲")
    assert (second["topicId"], second["count"], second["previousCount"], second["trend"], second["mark"]) == ("t2", 10, 20, "falling", "▼")
    assert "ransomware" in first["terms"] and len(first["references"]) == 3 and all(entry["title"].startswith("ransomware") for entry in first["references"])
    assert "memberIds" not in first and result["unassigned"] == 0 and set(result["legend"]) == {"rising", "falling", "steady", "new"}
    assert outcome.warnings == ()


def test_the_comparison_can_be_left_out():
    result = run(compare=False)[0].result
    assert result["compareTo"] is None and result["referencesInPreviousWindow"] is None and result["legend"] is None
    assert [topic["count"] for topic in result["topics"]] == [24, 10]   # only the current window is read and modeled
    assert all("trend" not in topic and "previousCount" not in topic for topic in result["topics"])


def test_an_empty_previous_window_is_said_and_no_topic_is_marked():
    rows = [row for row in library() if row["sourcePublishedAt"] >= "2026-10-26"]
    outcome, _ = run(rows)
    assert [warning["code"] for warning in outcome.warnings] == ["no_previous_window"]
    assert all("trend" not in topic for topic in outcome.result["topics"])


def test_too_few_references_is_a_warning_and_an_empty_list_not_an_error():
    outcome, engine = run([reference(1, "one lonely story", "11-05")])
    assert outcome.result["topics"] == [] and engine.calls == []
    assert "too_few_references" in [warning["code"] for warning in outcome.warnings]


def test_the_same_question_on_the_same_references_is_answered_from_the_store_and_a_changed_reference_or_refresh_models_again():
    store = MemoryTopicStore()
    first, engine = run(store=store)
    again, _ = run(store=store, engine=engine)
    assert len(engine.calls) == 1 and again.result["cached"] is True and again.result["savedId"] == first.result["savedId"]
    assert {**again.result, "cached": False} == first.result
    run(store=store, engine=engine, refresh=True)
    assert len(engine.calls) == 2
    changed = library()
    changed[0] = {**changed[0], "updatedAt": "2026-11-09T00:00:00Z"}
    other, _ = run(changed, store=store, engine=engine)
    assert len(engine.calls) == 3 and other.result["savedId"] != first.result["savedId"]
    assert run(store=store, engine=engine, window="28d")[0].result["savedId"] not in {first.result["savedId"], other.result["savedId"]}


def test_the_store_keeps_the_whole_record_with_member_lists_and_the_printed_result_has_none(tmp_path):
    store = FileTopicStore(tmp_path)
    outcome, _ = run(store=store)
    kept = store.get(outcome.result["savedId"])
    assert len(kept["topics"][0]["memberIds"]) == 24 and "memberIds" not in json.dumps(outcome.result)
    assert store.get("topics-0000000000000000") is None
    with pytest.raises(ValueError):
        store.get("../escape")


# --- the operation: command, MCP tool and the fake backend ---------------------------------------------------------------------------------------

def handlers(rows=None):
    return with_client(FakeClient(rows if rows is not None else library()), engine=FakeTopicEngine(), store=MemoryTopicStore(), today=AS_OF)


def run_command(argv, **kwargs):
    out = io.StringIO()
    status = topics_cli.command(argv, handlers=kwargs.pop("handlers", handlers()), environ={}, stdout=out)
    return status, json.loads(out.getvalue())


def test_the_command_and_the_mcp_tool_give_identical_json_for_the_same_request():
    status, printed = run_command(["model", "--window", "14d", "--compare-to", "previous", "--as-of", "2026-11-08", "--states", "accepted", "--states", "pending"])
    called = mcp.call_topic_tool("topics_model", {"window": "14d", "compareTo": "previous", "asOf": "2026-11-08", "states": ["accepted", "pending"]}, Caller(), handlers())
    assert status == 0 and printed == called and printed["ok"] and printed["publication"] == "demo"
    assert printed["result"]["topics"][0]["trend"] == "rising"


def test_a_bad_request_is_an_error_envelope_and_exit_code_two():
    status, answer = run_command(["model", "--window", "90d"])
    assert status == 2 and answer["error"]["code"] == "invalid_input" and answer["error"]["details"]["path"] == "window"
    status, answer = run_command(["model", "--as-of", "yesterday"])
    assert status == 2 and answer["error"]["code"] == "invalid_input" and answer["error"]["details"]["path"] == "asOf"
    status, answer = run_command(["model", "--section", "nowhere"])
    assert status == 2 and answer["error"]["code"] == "not_found"
    status, answer = run_command(["model", "--nope"])
    assert status == 2 and "papyrus topics model" in answer["error"]["message"]
    assert run_command(["paint"])[1]["error"]["code"] == "unknown_operation"
    assert mcp.call_topic_tool("topics_paint", {}, Caller(), handlers())["error"]["code"] == "unknown_operation"
    assert mcp.call_topic_tool("topics_model", {"window": "7d", "extra": 1}, Caller(), handlers())["error"]["details"]["path"] == "extra"


def test_a_section_is_looked_up_and_its_id_is_what_narrows_the_rows():
    rows = [reference(number, f"security story {number}", "11-05", curationSectionId="section-security") for number in range(1, 9)]
    rows += [reference(number, f"voice story {number}", "11-05", curationSectionId="section-voice") for number in range(9, 17)]
    status, answer = run_command(["model", "--section", "section-security", "--compare-to", "none"], handlers=handlers(rows))
    assert status == 0 and answer["result"]["referencesInWindow"] == 8 and answer["result"]["filters"]["section"] == "section-security"


def test_an_engine_that_cannot_run_is_a_retryable_engine_failed_and_saves_nothing():
    class Broken:
        name, version = "broken", "0"

        def model(self, documents, *, min_cluster_size):
            raise TopicEngineError("Biblicus is not installed.")

    store = MemoryTopicStore()
    answer = mcp.call_topic_tool("topics_model", {}, Caller(), with_client(FakeClient(library()), engine=Broken(), store=store, today=AS_OF))
    assert answer["error"]["code"] == "engine_failed" and answer["error"]["retryable"] and "Biblicus is not installed" in answer["error"]["message"]
    assert store.records == {}


def test_the_fake_engine_is_deterministic():
    documents = [TopicDocument(f"d{number}", text) for number, text in enumerate(["red apple pie"] * 4 + ["blue ocean wave"] * 4)]
    first = FakeTopicEngine().model(documents, min_cluster_size=3)
    assert first == FakeTopicEngine().model(documents, min_cluster_size=3)
    assert sorted(len(topic.member_ids) for topic in first) == [4, 4]


# --- the Biblicus engine, with a runner that does not start Biblicus ---------------------------------------------------------------------------------

class FakeRunner:
    def __init__(self, report):
        self.report, self.commands, self.files = report, [], []

    def run(self, arguments, timeout_seconds=None):
        self.commands.append([str(argument) for argument in arguments])
        if arguments[0] == "extract":
            corpus = Path(arguments[arguments.index("--corpus") + 1])
            self.files = sorted(path.read_text(encoding="utf-8") for path in (corpus / "raw" / "papyrus").glob("*.md"))
            latest = corpus / "extracted" / "pipeline"
            latest.mkdir(parents=True)
            (latest / "latest.json").write_text(json.dumps({"snapshot_id": "snap-1"}), encoding="utf-8")
        if arguments[0] == "analyze":
            settings = Path(arguments[arguments.index("--configuration") + 1]).read_text(encoding="utf-8")
            self.settings = settings
            return SimpleNamespace(stdout=json.dumps(self.report))
        return SimpleNamespace(stdout="")


def test_the_biblicus_engine_builds_a_throwaway_corpus_runs_the_knowledge_runs_analysis_and_maps_the_answer_back():
    documents = [TopicDocument(f"lin-{number}", f"A title about hospitals {number}") for number in range(8)]
    report = {"report": {"errors": [], "topics": [
        {"topic_id": 0, "keywords": [{"keyword": "network", "score": 0.1}, {"keyword": "hospital", "score": 0.3}],
         "document_ids": [deterministic_uuid("lin-0"), deterministic_uuid("lin-1"), deterministic_uuid("lin-2"), "not-ours"]},
        {"topic_id": -1, "keywords": [{"keyword": "noise", "score": 1}], "document_ids": [deterministic_uuid("lin-5")]}]}}
    runner = FakeRunner(report)
    found = BiblicusTopicEngine(runner).model(documents, min_cluster_size=3)
    assert [command[:2] for command in runner.commands] == [["init", runner.commands[0][1]], ["reindex", "--corpus"], ["extract", "build"], ["analyze", "topics"]]
    assert len(runner.files) == 8 and all("biblicus:" in text and deterministic_uuid("lin-3") in "".join(runner.files) for text in runner.files)
    assert "--extraction-snapshot" in runner.commands[-1] and "pipeline:snap-1" in runner.commands[-1]
    assert "min_topic_size: 3" in runner.settings and "min_cluster_size: 3" in runner.settings and "min_text_characters: 20" in runner.settings
    assert [(topic.terms, topic.member_ids) for topic in found] == [(("hospital", "network"), ("lin-0", "lin-1", "lin-2"))]
    assert found[0].label == "hospital, network"


def test_the_biblicus_engine_reports_a_failed_or_unreadable_run_as_an_engine_error_and_skips_a_corpus_too_small_for_its_cluster_size():
    documents = [TopicDocument(f"d{number}", f"title number {number}") for number in range(8)]
    with pytest.raises(TopicEngineError, match="could not be read"):
        BiblicusTopicEngine(FakeRunner("not an answer")).model(documents, min_cluster_size=3)
    with pytest.raises(TopicEngineError, match="reported: bad"):
        BiblicusTopicEngine(FakeRunner({"report": {"errors": ["bad"], "topics": []}})).model(documents, min_cluster_size=3)

    class Raises(FakeRunner):
        def run(self, arguments, timeout_seconds=None):
            raise RuntimeError("exit 1")

    with pytest.raises(TopicEngineError, match="Topic modeling failed: exit 1"):
        BiblicusTopicEngine(Raises({})).model(documents, min_cluster_size=3)
    untouched = FakeRunner({})
    assert BiblicusTopicEngine(untouched).model(documents[:5], min_cluster_size=3) == [] and untouched.commands == []


# --- the table and what is generated from it ----------------------------------------------------------------------------------------------------

def test_the_generated_files_are_exactly_what_the_table_produces():
    assert generate.stale() == []
    assert generate.main(["--check"]) == 0


def test_every_front_end_lists_the_same_operations_as_the_table():
    names = [item.name for item in OPERATIONS]
    assert names == ["topics_model"]
    assert [entry["op"] for entry in COMMANDS] == names and list(mcp.topic_tools()) == names and list(mcp.topic_descriptions()) == names
    assert re.findall(r"^  (topics_[a-z_]+): \{ input:", generate.TS_TYPES.read_text(encoding="utf-8"), re.M) == names
    skill = generate.SKILL.read_text(encoding="utf-8")
    assert re.findall(r"^\| `(topics_[a-z_]+)` \| `papyrus topics", skill[skill.index(generate.BEGIN):skill.index(generate.END)], re.M) == names
    assert re.findall(r"^## (topics_[a-z_]+)$", generate.DOCS.read_text(encoding="utf-8"), re.M) == names


def test_the_documented_example_is_a_valid_input_and_the_window_presets_are_offered():
    from papyrus_content.images.handlers import check

    item = BY_NAME["topics_model"]
    assert check(item.input, item.examples[0].input) is None
    assert item.input["properties"]["window"]["enum"] == ["7d", "14d", "28d"]
    assert item.input["properties"]["states"]["items"]["enum"] == ["pending", "accepted", "rejected"]


def test_the_group_is_on_the_papyrus_command_line_and_in_its_help():
    from papyrus.operator.help_dispatch import all_routes
    from papyrus.operator.help_text import TOP_LEVEL_HELP

    assert ["topics", "model"] in all_routes() and any(line.split()[:1] == ["topics"] for line in TOP_LEVEL_HELP.splitlines())
    assert topics_cli.usage_for(["model"]).startswith("Usage: papyrus topics model ")
