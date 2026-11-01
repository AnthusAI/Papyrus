"""papyrus_content.multi_search_research: plan, fan out, merge, synthesise and the packet, with fake providers and a fake model.
Nothing here touches the network."""
import json
from unittest import mock

import pytest

from papyrus_content import multi_search_research as ms
from papyrus_content.assignments_workflow import normalize_research_packet_bundle, research_packet_body
from papyrus_content.web_search import ProviderFailure, SearchHit, SearchResponse, SearchUnavailable


class FakeProvider:
    """Answers each query from ``answers`` (query -> hits or an exception); a provider with ``key=False`` has no key."""

    def __init__(self, name, answers=None, *, key=True, default=None):
        self.name, self.answers, self.key, self.default, self.calls = name, answers or {}, key, default, []

    def credential(self):
        if not self.key:
            raise SearchUnavailable(f"{self.name.upper()}_API_KEY is not set")
        return "k"

    def run(self, request):
        self.calls.append(request.query)
        answer = self.answers.get(request.query, self.default if self.default is not None else [])
        if isinstance(answer, Exception):
            raise answer
        return SearchResponse(list(answer), self.name)


def hit(url, title="", snippet=""):
    return SearchHit(url, title, snippet)


PLAN = {"queries": [{"query": "glide release", "purpose": "who released it"},
                    {"query": "glide benchmarks", "purpose": "independent benchmarks"}]}


class FakeLlm:
    def __init__(self, plan=PLAN, synthesis=None, fail=None):
        self.plan, self.synthesis, self.fail, self.calls = plan, synthesis, fail, []
        self.synthesis = synthesis if synthesis is not None else {
            "summary": "Two providers agree on the release.", "recommended_angle": "Check the benchmark claims.",
            "claims": [{"claim": "GLiDE was released in October.", "sources": [1, 2]}, {"claim": "Unsupported.", "sources": [99]}],
            "disagreements": [{"topic": "Score", "positions": [{"position": "81 percent", "sources": [1]},
                                                               {"position": "76 percent", "sources": [2, 42]}]}],
            "open_questions": ["Who ran the independent benchmark?"]}

    def __call__(self, system, user, schema):
        self.calls.append((schema["name"], user))
        if self.fail == schema["name"]:
            raise RuntimeError("model unavailable")
        return self.plan if schema["name"] == "search_plan" else self.synthesis


SHARED = "https://example.org/glide"


def two_providers():
    a = FakeProvider("gemini", {"glide release": [hit(SHARED + "/?utm_source=x", "GLiDE launch", "Gemini snippet"), hit("https://only-gemini.example/a", "Only Gemini")],
                                "glide benchmarks": []})
    b = FakeProvider("openai", {"glide release": [hit("https://www.example.org/glide/", "", "OpenAI snippet")],
                                "glide benchmarks": [hit("https://bench.example/results", "Benchmarks")]})
    return {"gemini": a, "openai": b}


def test_a_source_both_providers_found_is_merged_and_names_both():
    outcome = ms.run_multi_search("brief", llm=FakeLlm(), providers=two_providers())
    shared = next(s for s in outcome["sources"] if s["url"] == SHARED)
    assert shared["providers"] == ["gemini", "openai"]
    assert shared["queries"] == ["glide release"] and shared["purposes"] == ["who released it"]
    assert shared["bestRank"] == 1 and shared["title"] == "GLiDE launch"
    assert shared["snippets"] == ["Gemini snippet", "OpenAI snippet"]
    assert outcome["sources"][0] is shared                                # best supported first
    assert len(outcome["sources"]) == 3


def test_a_source_only_one_provider_found_is_kept():
    outcome = ms.run_multi_search("brief", llm=FakeLlm(), providers=two_providers())
    only = next(s for s in outcome["sources"] if s["url"] == "https://only-gemini.example/a")
    assert only["providers"] == ["gemini"]
    refs = {r["url"]: r for r in outcome["packet"]["proposed_references"]}
    assert refs["https://only-gemini.example/a"]["providers"] == ["gemini"]
    assert "Found by gemini" in refs["https://only-gemini.example/a"]["ingestion_rationale"]


def test_every_query_runs_on_every_provider():
    providers = two_providers()
    ms.run_multi_search("brief", llm=FakeLlm(), providers=providers)
    assert providers["gemini"].calls == providers["openai"].calls == ["glide release", "glide benchmarks"]


def test_one_provider_failing_is_recorded_and_the_packet_is_still_made():
    providers = two_providers()
    providers["gemini"] = FakeProvider("gemini", default=ProviderFailure("gemini", "plan_exhausted", 429))
    outcome = ms.run_multi_search("brief", llm=FakeLlm(), providers=providers)
    gemini = outcome["contribution"]["gemini"]
    assert gemini["queriesRun"] == 0 and gemini["failures"][0]["kind"] == "plan_exhausted"
    assert len(gemini["failures"]) == 1                                    # a spent plan is not asked again
    assert outcome["contribution"]["openai"]["queriesRun"] == 2
    assert outcome["packet"]["multiSearch"]["answeredProviders"] == ["openai"]


def test_a_transient_failure_does_not_stop_the_provider_s_other_queries():
    providers = two_providers()
    providers["gemini"].answers["glide release"] = ProviderFailure("gemini", "server_error", 500)
    gemini = ms.run_multi_search("brief", llm=FakeLlm(), providers=providers)["contribution"]["gemini"]
    assert gemini["queriesRun"] == 1 and [f["kind"] for f in gemini["failures"]] == ["server_error"]


def test_no_provider_answering_is_an_error_and_no_packet():
    providers = {n: FakeProvider(n, default=ProviderFailure(n, "auth", 401)) for n in ("gemini", "openai")}
    with pytest.raises(ms.MultiSearchFailed) as caught:
        ms.run_multi_search("brief", llm=FakeLlm(), providers=providers)
    assert "no search provider answered" in str(caught.value) and "gemini: gemini: authentication failed (401)" in str(caught.value)


def test_no_configured_provider_is_an_error_naming_each():
    providers = {"tavily": FakeProvider("tavily", key=False), "openai": FakeProvider("openai", key=False)}
    with pytest.raises(ms.MultiSearchFailed) as caught:
        ms.run_multi_search("brief", llm=FakeLlm(), providers=providers)
    assert "no search provider to ask" in str(caught.value) and "TAVILY_API_KEY" in str(caught.value)


def test_a_provider_without_a_key_is_listed_as_unavailable_not_failed():
    providers = {**two_providers(), "tavily": FakeProvider("tavily", key=False)}
    contribution = ms.run_multi_search("brief", llm=FakeLlm(), providers=providers)["contribution"]
    assert contribution["tavily"]["queriesRun"] == 0 and "TAVILY_API_KEY" in contribution["tavily"]["unavailable"]
    assert contribution["tavily"]["failures"] == []


def test_the_per_provider_contribution():
    contribution = ms.run_multi_search("brief", llm=FakeLlm(), providers=two_providers())["contribution"]
    assert set(contribution["gemini"]) >= {"queriesRun", "hits", "uniqueSources", "failures", "elapsedMs"}
    assert (contribution["gemini"]["queriesRun"], contribution["gemini"]["hits"], contribution["gemini"]["uniqueSources"]) == (2, 2, 1)
    assert (contribution["openai"]["queriesRun"], contribution["openai"]["hits"], contribution["openai"]["uniqueSources"]) == (2, 2, 1)
    assert contribution["openai"]["failures"] == [] and isinstance(contribution["openai"]["elapsedMs"], int)


def test_the_packet_carries_claims_disagreements_open_questions_and_provenance():
    packet = ms.run_multi_search("brief", llm=FakeLlm(), providers=two_providers())["packet"]
    assert packet["claims"] == [{"claim": "GLiDE was released in October.", "sources": [1, 2]}]    # the claim citing source 99 is dropped
    assert packet["multiSearch"]["droppedClaims"] == 1
    assert packet["disagreements"][0]["positions"][1]["sources"] == [2]                           # source 42 does not exist
    assert packet["open_questions"] == ["Who ran the independent benchmark?"]
    assert packet["multiSearch"]["sourceProviders"][0]["providers"] == ["gemini", "openai"]
    assert packet["multiSearch"]["queries"] == PLAN["queries"]


def test_the_packet_goes_through_the_normal_research_packet_normalisation():
    packet = ms.run_multi_search("brief", llm=FakeLlm(), providers=two_providers())["packet"]
    bundle = normalize_research_packet_bundle(packet, assignment={"corpusId": "c"}, assignment_meta={}, research_mode="source_discovery")
    assert len(bundle["proposedReferences"]) == 3 and bundle["sourceDiscovery"]["blockedReason"] is None
    assert bundle["multiSearch"]["providers"]["gemini"]["uniqueSources"] == 1 and bundle["claims"]
    body = research_packet_body(bundle)
    assert "Claims:" in body and "GLiDE was released in October. [1, 2]" in body and "Where sources disagree:" in body
    assert "Open questions:" in body


def test_an_ordinary_packet_body_is_unchanged():
    assert research_packet_body({"summary": "S", "researchMode": "source_discovery", "recommendedAngle": "A"}) == \
        "S\nResearch mode: source_discovery\nRecommended angle: A"


def test_planning_failure_is_an_error():
    with pytest.raises(ms.MultiSearchFailed, match="could not plan queries"):
        ms.run_multi_search("brief", llm=FakeLlm(fail="search_plan"), providers=two_providers())


def test_synthesis_failure_is_an_error_and_says_how_many_sources_were_found():
    with pytest.raises(ms.MultiSearchFailed, match="found 3 sources but could not synthesise"):
        ms.run_multi_search("brief", llm=FakeLlm(fail="research_synthesis"), providers=two_providers())


def test_the_number_of_queries_comes_from_the_plan():
    plan = {"queries": [{"query": f"q{i}", "purpose": "p"} for i in range(7)] + [{"query": "Q0", "purpose": "duplicate"}]}
    providers = {"gemini": FakeProvider("gemini", default=[hit("https://a.example/1")])}
    outcome = ms.run_multi_search("brief", llm=FakeLlm(plan=plan), providers=providers)
    assert len(outcome["queries"]) == 7 and len(providers["gemini"].calls) == 7


def test_brief_text_gathers_title_notes_and_context_once():
    text = ms.brief_text({"title": "T", "summary": "T", "brief": "B", "instructions": "I", "notes": "N"},
                         {"sectionTitle": "AI", "topicScopeCategoryKeys": ["a", "b"]})
    assert text.splitlines() == ["Title: T", "Brief: B", "Instructions: I", "Notes: N", "Section: AI", "Topics: a, b"]


def test_url_identity_ignores_tracking_fragment_www_and_trailing_slash():
    keys = {ms.source_key(u) for u in ("https://www.Example.org/a/?utm_source=x#f", "https://example.org/a")}
    assert len(keys) == 1 and ms.source_key("ftp://example.org/a") is None


def test_openai_llm_posts_a_schema_and_reads_the_output_text():
    http = mock.Mock(return_value={"output": [{"content": [{"type": "output_text", "text": json.dumps(PLAN)}]}]})
    call = ms.openai_llm(model="m", environ={"OPENAI_API_KEY": "sk-test"}, http=http)
    assert call("system", "user", ms.PLAN_SCHEMA) == PLAN
    url, headers, payload = http.call_args.args
    assert url == ms.RESPONSES_URL and headers["Authorization"] == "Bearer sk-test"
    assert payload["model"] == "m" and payload["text"]["format"]["name"] == "search_plan"


# --- writing it to the newsroom ---------------------------------------------------------------------------------------------------

class FakeClient:
    def __init__(self, assignment):
        self.assignment = assignment

    def get_record(self, model, record_id):
        return self.assignment if model == "Assignment" else None


def assignment(type_key="research.multi"):
    return {"id": "assignment-1", "assignmentTypeKey": type_key, "queueKey": "research:x:exploratory", "title": "Assess GLiDE",
            "status": "open", "metadata": json.dumps({"researchMode": "source_discovery", "corpusKey": "papyrus"})}


@pytest.fixture
def wired():
    with mock.patch.object(ms, "apply_research_packet", return_value={"messageId": "m1"}) as apply_packet, \
         mock.patch.object(ms, "intake_research_packet_proposals", return_value={"registeredReferenceCount": 3}) as intake, \
         mock.patch.object(ms, "build_record_changes", side_effect=lambda client, records: records) as build, \
         mock.patch.object(ms, "apply_record_changes") as write, \
         mock.patch.object(ms, "update_newsroom_summary_after_research_packet_creates"):
        yield apply_packet, intake, build, write


def test_the_packet_is_written_through_apply_research_packet_and_intake(wired):
    apply_packet, intake, _, write = wired
    result = ms.research_multi(FakeClient(assignment()), {"assignment": "assignment-1"}, llm=FakeLlm(), providers=two_providers())
    assert result["action"] == "completed" and result["researchPacketMessageId"] == "m1" and result["registeredReferenceCount"] == 3
    options = apply_packet.call_args.args[1]
    assert options["assignment"] == "assignment-1" and json.loads(options["research-json"])["multiSearch"]["providers"]
    assert intake.call_args.args[1]["corpus-key"] == "papyrus"
    event = write.call_args.args[1][-1]
    assert event["expected"]["eventType"] == "research.multi.completed"


def test_a_dry_run_writes_nothing(wired):
    apply_packet, intake, _, write = wired
    result = ms.research_multi(FakeClient(assignment()), {"assignment": "assignment-1", "dry-run": True}, llm=FakeLlm(), providers=two_providers())
    assert result["action"] == "dry-run" and result["packet"]["claims"] and result["contribution"]["gemini"]
    apply_packet.assert_not_called(); intake.assert_not_called(); write.assert_not_called()


def test_when_no_provider_answers_an_error_message_is_recorded_and_no_packet(wired):
    apply_packet, intake, build, write = wired
    providers = {n: FakeProvider(n, default=ProviderFailure(n, "auth", 401)) for n in ("gemini", "openai")}
    result = ms.research_multi(FakeClient(assignment()), {"assignment": "assignment-1"}, llm=FakeLlm(), providers=providers)
    assert result["action"] == "failed" and "no search provider answered" in result["error"]
    apply_packet.assert_not_called(); intake.assert_not_called()
    records = write.call_args.args[1]
    kinds = [r["expected"].get("messageKind") for r in records if r.get("modelName") == "Message"]
    assert kinds == [ms.MULTI_ERROR_MESSAGE_KIND]
    assert records[-1]["expected"]["eventType"] == "research.multi.failed"


def test_only_a_research_multi_assignment_can_run(wired):
    with pytest.raises(ValueError, match="is not research.multi"):
        ms.research_multi(FakeClient(assignment("research.candidate")), {"assignment": "assignment-1"}, llm=FakeLlm(), providers=two_providers())


def test_the_cli_takes_the_assignment_as_the_first_argument():
    with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(object(), None)), \
         mock.patch.object(ms, "research_multi", return_value={"action": "failed", "assignmentId": "a", "error": "e"}) as run:
        ms.research_multi_command(["a-1", "--dry-run"])
    assert run.call_args.args[1] == {"assignment": "a-1", "dry-run": True}


def test_creating_a_research_multi_assignment_is_opt_in():
    from papyrus_content.assignments_workflow import create_research_assignment

    client = mock.Mock()
    client.get_record.return_value = None
    planned = []
    with mock.patch("papyrus_content.assignments_workflow.publication_corpus_key", return_value="papyrus"), \
         mock.patch("papyrus_content.assignments_workflow.content_item_lineage_for_new_assignment", return_value=("lin", None)), \
         mock.patch("papyrus_content.assignments_workflow.build_record_changes", side_effect=lambda c, records: planned.append(records) or []):
        multi = create_research_assignment(client, {"title": "T", "type": "research.multi", "dry-run": True})
        default = create_research_assignment(client, {"title": "T", "dry-run": True})
    meta = json.loads(planned[0][0]["expected"]["metadata"])
    assert multi["assignmentTypeKey"] == "research.multi" and meta["researchBackend"] == "multi_search"
    assert default["assignmentTypeKey"] == "research.candidate"            # never the default
    assert "researchBackend" not in json.loads(planned[1][0]["expected"]["metadata"])
