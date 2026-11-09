"""Topic modeling on recent References and the source-date index (features_backend/topics-model.feature and reference-source-date-index.feature).
Nothing here calls a model, Biblicus, AWS or the network."""

from __future__ import annotations

import io
import json
import logging
import sys
from datetime import date
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import graphql_authoring as g  # noqa: E402
from papyrus_content.images.handlers import Caller  # noqa: E402
from papyrus_content.topics import cli as topics_cli  # noqa: E402
from papyrus_content.topics import generate, mcp  # noqa: E402
from papyrus_content.topics.engine import BiblicusTopicEngine, TopicDocument, TopicEngineError  # noqa: E402
from papyrus_content.topics.fakes import FakeTopicEngine  # noqa: E402
from papyrus_content.topics.handlers import with_client  # noqa: E402
from papyrus_content.topics.operations import BY_NAME  # noqa: E402
from papyrus_content.topics.select import INDEX, select_references  # noqa: E402
from papyrus_content.topics.store import MemoryTopicStore  # noqa: E402
from papyrus_content.topics.topics_test import CORPUS, FakeClient, FakeRunner, library, reference  # noqa: E402
from papyrus_content.topics.windows import current_window  # noqa: E402
from papyrus_content.whole_table_reads_test import test_no_new_whole_table_reads_outside_the_allowlist, whole_table_reads  # noqa: E402

AS_OF = date(2026, 11, 8)


class Broken:
    name, version = "broken", "0"

    def model(self, documents, *, min_cluster_size):
        raise TopicEngineError("Biblicus is not installed.")


def start(context, rows, engine=None):
    context.client = FakeClient(rows)
    context.engine = engine or FakeTopicEngine()
    context.store = MemoryTopicStore()
    context.handlers = with_client(context.client, engine=context.engine, store=context.store, today=AS_OF)


def ask(context, arguments):
    return mcp.call_topic_tool("topics_model", arguments, Caller(), context.handlers)


# --- the index -----------------------------------------------------------------------------------------------------------------------------------

@then("the Reference model in the deployed schema and in the typed schema both declare the index on corpusId and sourcePublishedAt")
def step_schema_files(context):
    line = 'index("corpusId").sortKeys(["sourcePublishedAt"]).queryField("listReferencesByCorpusAndSourcePublishedAt")'
    for name in ("schema.ts", "resource.ts"):
        assert line in (REPO_ROOT / "amplify" / "data" / name).read_text(encoding="utf-8"), name


@then("the authoring client knows the index and reads it by a range of source dates, newest first, a page at a time")
def step_client_index(context):
    definition = g.INDEX_DEFINITIONS[INDEX]
    assert (definition["partitionKey"], definition["sortKey"]) == ("corpusId", "sourcePublishedAt")
    asked = []

    class Client(g.PapyrusGraphQLAuthoringClient):
        def __init__(self):
            self.tenant_id = None

        def graphql(self, query, variables=None):
            asked.append((query, variables))
            first = variables["nextToken"] is None
            return {definition["field"]: {"items": [{"id": "a"}] if first else [{"id": "b"}], "nextToken": "more" if first else None}}

    assert [row["id"] for row in Client().iterate_index_range(INDEX, CORPUS, "2026-10-26", "2026-11-08T23:59:59.999Z")] == ["a", "b"]
    assert len(asked) == 2 and "sortDirection: DESC" in asked[0][0]
    assert asked[0][1]["sortRange"] == {"between": ["2026-10-26", "2026-11-08T23:59:59.999Z"]}


@given("a corpus with References published on many days, some already voted down or archived and some replaced by a newer version")
def step_many_days(context):
    start(context, [reference(1, "kept", "11-05"), reference(2, "pending", "11-06", curationStatus="pending"), reference(3, "rejected", "11-06", curationStatus="rejected"),
                    reference(4, "archived", "11-06", curationStatus="archived"), reference(5, "old version", "11-06", versionState="superseded"),
                    reference(6, "too early", "10-01"), reference(7, "too late", "11-09")])


@when("the References of the last 14 days ending on 2026-11-08 are selected")
def step_select_window(context):
    context.selection = select_references(context.client, CORPUS, current_window("14d", AS_OF))


@then("the index is asked once for the corpus between 2026-10-26 and the end of 2026-11-08")
def step_asked_once(context):
    assert context.client.asked == [(INDEX, CORPUS, "2026-10-26", "2026-11-08T23:59:59.999Z")]


@then("only the current accepted and pending References of those days are returned")
def step_returned(context):
    assert sorted(row["id"] for row in context.selection.rows) == ["ref-1", "ref-2"]


@given("a corpus with References from two sections and two monitors")
def step_two_sections(context):
    start(context, [reference(1, "a", "11-05", curationSectionId="section-security", discoveredByMonitorId="hn"), reference(2, "b", "11-05", curationSectionId="section-voice"),
                    reference(3, "c", "11-05", discoveredByMonitorId="hn"), reference(4, "d", "11-05", curationStatus="rejected")])


@when("the References of the window are selected for one section")
def step_select_section(context):
    context.selection = select_references(context.client, CORPUS, current_window("14d", AS_OF), section_id="section-security")


@then("only the References whose vote was filed under that section are returned")
def step_only_section(context):
    assert [row["id"] for row in context.selection.rows] == ["ref-1"]


@when("the References of the window are selected for one monitor")
def step_select_monitor(context):
    context.selection = select_references(context.client, CORPUS, current_window("14d", AS_OF), monitor="hn")


@then("only the References that monitor delivered are returned")
def step_only_monitor(context):
    assert sorted(row["id"] for row in context.selection.rows) == ["ref-1", "ref-3"]


@when("rejected References are asked for")
def step_select_rejected(context):
    context.selection = select_references(context.client, CORPUS, current_window("14d", AS_OF), states=("rejected",))


@then("only the rejected References of the window are returned")
def step_only_rejected(context):
    assert [row["id"] for row in context.selection.rows] == ["ref-4"]


@given("a corpus with ten References in the window")
def step_ten(context):
    start(context, [reference(number, f"story {number}", "11-05") for number in range(1, 11)])


@when("the References of the window are selected with a safety stop of four")
def step_safety_stop(context):
    handler = _Capture()
    logger = logging.getLogger("papyrus.topics")
    logger.addHandler(handler)
    try:
        context.selection = select_references(context.client, CORPUS, current_window("14d", AS_OF), max_references=4)
    finally:
        logger.removeHandler(handler)
    context.log_lines = handler.lines


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@then("four References are returned and the selection is marked stopped")
def step_four(context):
    assert len(context.selection.rows) == 4 and context.selection.stopped


@then("the warnings say the safety stop was reached and name the limit")
def step_stop_warning(context):
    warning = context.selection.warnings[0]
    assert warning["code"] == "max_references_reached" and "max_references is 4" in warning["message"]


@then("the log says the same")
def step_stop_log(context):
    assert any("max_references is 4" in line for line in context.log_lines)


@then("the topics code makes no whole-table read and the allowlist of whole-table reads has no new entry")
def step_no_scan(context):
    test_no_new_whole_table_reads_outside_the_allowlist()
    assert not [path for path in whole_table_reads() if "/topics/" in path]


# --- the operation -------------------------------------------------------------------------------------------------------------------------------

@then("the generated command spec, MCP schema, TypeScript types, skill reference block and docs for topics are all current")
def step_current(context):
    assert generate.stale() == []


@then("the topic generator's check mode reports nothing out of date")
def step_check_mode(context):
    assert generate.main(["--check"]) == 0


@given("a corpus where ransomware stories became common in the last two weeks and voice stories became rarer")
def step_library(context):
    start(context, library())


@given("a corpus with References only in the last two weeks")
def step_recent_only(context):
    start(context, [row for row in library() if row["sourcePublishedAt"] >= "2026-10-26"])


@given("a corpus with one Reference in the window")
def step_one(context):
    start(context, [reference(1, "one lonely story", "11-05")])


@given("an engine that cannot run")
def step_broken(context):
    start(context, library(), Broken())


@when("a person asks for topics with no options as of 2026-11-08")
@when("a person asks for topics as of 2026-11-08")
def step_ask(context):
    if not hasattr(context, "handlers"):
        start(context, library())
    context.answer = ask(context, {"asOf": "2026-11-08"})
    assert context.answer["ok"] or context.answer["error"]["code"] == "engine_failed", context.answer


@when("a person asks for topics with the comparison set to none")
def step_ask_none(context):
    context.answer = ask(context, {"asOf": "2026-11-08", "compareTo": "none"})


@when("a person asks for topics as of 2026-11-08 twice")
def step_ask_twice(context):
    context.first, context.answer = ask(context, {"asOf": "2026-11-08"}), ask(context, {"asOf": "2026-11-08"})


@then("the window runs from 2026-10-26 to 2026-11-08 and is compared with 2026-10-12 to 2026-10-25")
def step_default_window(context):
    result = context.answer["result"]
    assert result["window"] == {"start": "2026-10-26", "end": "2026-11-08", "days": 14}
    assert result["compareTo"] == {"start": "2026-10-12", "end": "2026-10-25", "days": 14}


@then("the operation offers the windows 7d, 14d and 28d and the votes pending, accepted and rejected")
def step_presets(context):
    properties = BY_NAME["topics_model"].input["properties"]
    assert properties["window"]["enum"] == ["7d", "14d", "28d"] and properties["states"]["items"]["enum"] == ["pending", "accepted", "rejected"]


def topic(context, word):
    return next(entry for entry in context.answer["result"]["topics"] if word in entry["terms"])


@then("the ransomware topic has 24 References now and 6 before, and is marked rising with the mark for rising")
def step_rising(context):
    entry = topic(context, "ransomware")
    assert (entry["count"], entry["previousCount"], entry["trend"], entry["mark"]) == (24, 6, "rising", "▲")


@then("the voice topic has 10 References now and 20 before, and is marked falling with the mark for falling")
def step_falling(context):
    entry = topic(context, "voice")
    assert (entry["count"], entry["previousCount"], entry["trend"], entry["mark"]) == (10, 20, "falling", "▼")


@then("each topic shows up to three representative References, newest first, and no member lists")
def step_representatives(context):
    for entry in context.answer["result"]["topics"]:
        dates = [reference_["sourcePublishedAt"] for reference_ in entry["references"]]
        assert 1 <= len(entry["references"]) <= 3 and dates == sorted(dates, reverse=True) and "memberIds" not in entry


@then("the result carries a legend that says in words what each mark means")
def step_legend(context):
    legend = context.answer["result"]["legend"]
    assert set(legend) == {"rising", "falling", "steady", "new"} and all(word in text for word, text in legend.items())


@then("the smallest topic scaled with the number of References, the square root of 60 rounded, which is 8")
def step_scaled(context):
    assert context.answer["result"]["minClusterSize"] == 8


@then("only the current window is read and modeled and no topic has a trend")
def step_only_current(context):
    result = context.answer["result"]
    assert result["compareTo"] is None and len(context.client.asked) == 1
    assert [entry["count"] for entry in result["topics"]] == [24, 10] and all("trend" not in entry for entry in result["topics"])


@then("the warnings say the previous window is empty and no topic is marked rising or falling")
def step_empty_previous(context):
    assert [warning["code"] for warning in context.answer["warnings"]] == ["no_previous_window"]
    assert all("trend" not in entry for entry in context.answer["result"]["topics"])


@then("there are no topics and the engine was never asked")
def step_no_topics(context):
    assert context.answer["result"]["topics"] == [] and context.engine.calls == []


@then("the warnings say there were too few References")
def step_too_few(context):
    assert "too_few_references" in [warning["code"] for warning in context.answer["warnings"]]


@then("the engine was asked once and the second answer says it was cached with the same saved id")
def step_cached(context):
    assert len(context.engine.calls) == 1 and context.answer["result"]["cached"] is True
    assert context.answer["result"]["savedId"] == context.first["result"]["savedId"]


@when("one Reference is updated and the question is asked again")
def step_update_one(context):
    context.before = context.answer["result"]["savedId"]
    context.client.rows[0] = {**context.client.rows[0], "updatedAt": "2026-11-09T00:00:00Z"}
    context.answer = ask(context, {"asOf": "2026-11-08"})


@then("the engine is asked again and the saved id is different")
def step_asked_again_different(context):
    assert len(context.engine.calls) == 2 and context.answer["result"]["savedId"] != context.before


@when("the question is asked again with refresh")
def step_refresh(context):
    context.answer = ask(context, {"asOf": "2026-11-08", "refresh": True})


@then("the engine is asked again")
def step_asked_again(context):
    assert len(context.engine.calls) == 3


@when("the example input is given as a command line and as the MCP tool")
def step_example(context):
    out = io.StringIO()
    context.cli_status = topics_cli.command(["model", "--window", "14d", "--as-of", "2026-11-08", "--compare-to", "previous", "--refresh"], handlers=context.handlers, environ={}, stdout=out)
    context.cli_answer = json.loads(out.getvalue())
    context.answer = ask(context, {"window": "14d", "asOf": "2026-11-08", "compareTo": "previous", "refresh": True})


@then("both answer with the same JSON, a success from the publication")
def step_same(context):
    assert context.cli_status == 0 and context.cli_answer == context.answer and context.answer["ok"] and context.answer["publication"] == "demo"


@when('a person runs the topics command "{line}"')
def step_command(context, line):
    start(context, library())
    out = io.StringIO()
    context.cli_status = topics_cli.command(line.split(), handlers=context.handlers, environ={}, stdout=out)
    context.cli_answer = json.loads(out.getvalue())


@then('the command exits with the error code and answers {code} naming "{field}"')
def step_refused(context, code, field):
    error = context.cli_answer["error"]
    assert context.cli_status == 2 and error["code"] == code
    assert error["details"].get("path") == field or field in error["details"]


@then("the answer is engine_failed and says it may be retried")
def step_engine_failed(context):
    error = context.answer["error"]
    assert error["code"] == "engine_failed" and error["retryable"] is True


@then("no topic run was saved")
def step_nothing_saved(context):
    assert context.store.records == {}


# --- the Biblicus engine ---------------------------------------------------------------------------------------------------------------------------

@given("a Biblicus runner that records its commands and answers like Biblicus")
def step_runner(context):
    from papyrus_content.ids import deterministic_uuid

    ids = [deterministic_uuid(f"lin-{number}") for number in range(8)]
    context.runner = FakeRunner({"report": {"errors": [], "topics": [
        {"topic_id": 0, "keywords": [{"keyword": "hospital", "score": 0.3}], "document_ids": ids[:3]},
        {"topic_id": -1, "keywords": [{"keyword": "noise", "score": 1}], "document_ids": ids[5:6]}]}})


@when("the Biblicus engine models eight documents with a smallest topic of three")
def step_model_eight(context):
    documents = [TopicDocument(f"lin-{number}", f"A title about hospitals {number}") for number in range(8)]
    context.found = BiblicusTopicEngine(context.runner).model(documents, min_cluster_size=3)


@then("it made a throwaway corpus, extracted the text and ran the topic analysis with the knowledge run's settings")
def step_commands(context):
    assert [command[0] for command in context.runner.commands] == ["init", "reindex", "extract", "analyze"]
    assert len(context.runner.files) == 8 and "min_cluster_size: 3" in context.runner.settings and "ngram_range" in context.runner.settings


@then("its topics carry the documents' own ids and drop the outlier group")
def step_ids(context):
    assert [topic_.member_ids for topic_ in context.found] == [("lin-0", "lin-1", "lin-2")]
