import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
from test_multi_search_research import FakeClient, FakeLlm, FakeProvider, assignment, hit  # noqa: E402
from papyrus_content import multi_search_research as ms  # noqa: E402
from papyrus_content.assignments_workflow import create_research_assignment  # noqa: E402
from papyrus_content.web_search import ProviderFailure  # noqa: E402

QUERIES = ("glide release", "glide benchmarks")


def _providers(context):
    if not hasattr(context, "ms_providers"):
        context.ms_providers = {}
    return context.ms_providers


def _provider(context, name):
    return _providers(context).setdefault(name, FakeProvider(name, default=[]))


def _finds(context, name, url):
    provider = _provider(context, name)
    provider.answers.setdefault(QUERIES[0], []).append(hit(url, "Page " + url.rsplit("/", 1)[-1], f"{name} snippet"))


@given('the multi-search providers "{first}" and "{second}" both find the page "{url}"')
def step_both(context, first, second, url):
    _finds(context, first, url)
    _finds(context, second, url)


@given('the multi-search provider "{name}" alone finds the page "{url}"')
def step_alone(context, name, url):
    _finds(context, name, url)


@given('the multi-search provider "{name}" finds other pages')
def step_other(context, name):
    _finds(context, name, f"https://{name}-other.example/page")


@given('the multi-search provider "{name}" has used up its plan')
def step_plan(context, name):
    _providers(context)[name] = FakeProvider(name, default=ProviderFailure(name, "plan_exhausted", 432))


@given("every multi-search provider refuses its key")
def step_refuse(context):
    for name in ("gemini", "openai"):
        _providers(context)[name] = FakeProvider(name, default=ProviderFailure(name, "auth", 401))


@when("the editor runs multi-search on the assignment")
def step_run(context):
    with mock.patch.object(ms, "apply_research_packet", return_value={"messageId": "m1"}) as packet, \
         mock.patch.object(ms, "intake_research_packet_proposals", return_value={"registeredReferenceCount": 0}), \
         mock.patch.object(ms, "build_record_changes", side_effect=lambda client, records: records), \
         mock.patch.object(ms, "apply_record_changes") as write, \
         mock.patch.object(ms, "update_newsroom_summary_after_research_packet_creates"):
        context.result = ms.research_multi(FakeClient(assignment()), {"assignment": "assignment-1"},
                                           llm=FakeLlm(), providers=_providers(context))
    context.written = write.call_args.args[1] if write.called else []
    context.packet = json.loads(packet.call_args.args[1]["research-json"]) if packet.called else None
    context.packet_calls = packet.call_count


def _source(context, url):
    return next(s for s in context.packet["source_snapshots"] if s["url"] == url)


@then('the packet has one source for "{url}"')
def step_one_source(context, url):
    assert [s["url"] for s in context.packet["source_snapshots"]].count(url) == 1


@then('the packet has a source for "{url}"')
def step_has_source(context, url):
    _source(context, url)


@then('that source names the providers "{names}"')
def step_names(context, names):
    url = next(s["url"] for s in context.packet["source_snapshots"] if s["providers"] == [n.strip() for n in names.split(",")])
    assert url


@then('the proposed reference for that source names the providers "{names}"')
def step_reference_names(context, names):
    expected = [n.strip() for n in names.split(",")]
    assert any(r["providers"] == expected for r in context.packet["proposed_references"])


@then('a research packet is made from the sources "{name}" found')
def step_packet_from(context, name):
    assert context.result["action"] == "completed" and context.packet_calls == 1
    assert all(name in s["providers"] for s in context.packet["source_snapshots"])


@then('the packet records that "{name}" failed with "{kind}"')
def step_failed(context, name, kind):
    failures = context.packet["multiSearch"]["providers"][name]["failures"]
    assert failures and failures[0]["kind"] == kind


@then("no research packet is made")
def step_no_packet(context):
    assert context.result["action"] == "failed" and context.packet_calls == 0


@then('the assignment records the error "{text}"')
def step_error(context, text):
    assert text in context.result["error"]
    message = next(r for r in context.written if r.get("modelName") == "Message")
    assert message["expected"]["messageKind"] == ms.MULTI_ERROR_MESSAGE_KIND and message["expected"]["summary"] == "Multi-search failed"
    assert text in context.written[-1]["expected"]["note"]


@then('the packet\'s contribution for "{name}" shows {hits:d} hits and {unique:d} unique sources')
def step_contribution(context, name, hits, unique):
    row = context.packet["multiSearch"]["providers"][name]
    assert (row["hits"], row["uniqueSources"]) == (hits, unique), row


@then("every provider's contribution shows its queries run, its failures and its elapsed milliseconds")
def step_contribution_fields(context):
    for row in context.packet["multiSearch"]["providers"].values():
        assert row["queriesRun"] == 2 and row["failures"] == [] and isinstance(row["elapsedMs"], int)


@then("each claim in the packet cites sources that exist")
def step_claims(context):
    count = len(context.packet["source_snapshots"])
    assert context.packet["claims"] and all(c["sources"] and all(1 <= i <= count for i in c["sources"]) for c in context.packet["claims"])


@then("the packet names where the sources disagree and what stayed open")
def step_disagree(context):
    assert context.packet["disagreements"] and context.packet["open_questions"]


@when("an editor creates a research assignment without choosing a type")
def step_create_default(context):
    client = mock.Mock()
    client.get_record.return_value = None
    with mock.patch("papyrus_content.assignments_workflow.publication_corpus_key", return_value="papyrus"), \
         mock.patch("papyrus_content.assignments_workflow.content_item_lineage_for_new_assignment", return_value=("lin", None)), \
         mock.patch("papyrus_content.assignments_workflow.build_record_changes", return_value=[]):
        context.created = create_research_assignment(client, {"title": "T", "dry-run": True})


@then("the assignment is a research.candidate and not a research.multi")
def step_candidate(context):
    assert context.created["assignmentTypeKey"] == "research.candidate"
