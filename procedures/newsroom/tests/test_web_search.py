"""papyrus_content.web_search: each provider's request and response mapping, key lookup, failure kinds and the fallback chain.
Fake HTTP throughout: nothing here touches the network."""
import json

import pytest

from papyrus_content.web_search import (BedrockProvider, GeminiProvider, HttpStatusError, OpenAIProvider, PerplexityProvider, SearchChain,
                                        SearchChainFailed, SearchHit, SearchRequest, SearchUnavailable, TavilyProvider, chain_names,
                                        classify, parse_names)


class FakeHttp:
    """Answers queued bodies (or raises queued errors) and remembers every call."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, url, headers, payload):
        self.calls.append((url, headers, payload))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def make(cls, http, **env):
    return cls(environ=env, http=http, sleep=lambda seconds: None)


# --- request and response mapping, one provider at a time -------------------------------------------------------------------------

def test_tavily_request_and_response():
    http = FakeHttp({"answer": "A", "usage": {"credits": 1}, "results": [
        {"url": "https://a.example/x", "title": "T", "content": "C", "score": 0.8, "published_date": "2026-10-31"}, {"title": "no url"}]})
    provider = make(TavilyProvider, http, TAVILY_API_KEY=" tvly-k ")
    response = provider.run(SearchRequest("q", limit=5, topic="news", start_date="2026-10-30", end_date="2026-10-31",
                                          include_domains=("a.example",), exclude_domains=("b.example",), want_answer=True))
    url, headers, payload = http.calls[0]
    assert url == "https://api.tavily.com/search" and headers["Authorization"] == "Bearer tvly-k"
    assert payload == {"query": "q", "max_results": 5, "search_depth": "basic", "include_answer": True, "topic": "news",
                       "start_date": "2026-10-30", "end_date": "2026-10-31", "include_domains": ["a.example"], "exclude_domains": ["b.example"]}
    assert response.hits == [SearchHit("https://a.example/x", "T", "C", 0.8, "2026-10-31")]
    assert response.answer == "A" and response.usage == {"credits": 1} and response.date_bounded


def test_openai_request_and_response_use_citations_for_titles_and_excerpts():
    text = "Regulators approved it. Other news."
    http = FakeHttp({"model": "m", "id": "resp_1", "output": [
        {"type": "web_search_call", "action": {"sources": [{"url": "https://a.example/1"}, {"url": "https://b.example/2"}]}},
        {"type": "message", "content": [{"type": "output_text", "text": text, "annotations": [
            {"type": "url_citation", "url": "https://a.example/1", "title": "Approved", "start_index": 0, "end_index": 23},
            {"type": "url_citation", "url": "https://c.example/3", "title": "Extra", "start_index": 24, "end_index": 35}]}]}]})
    provider = make(OpenAIProvider, http, OPENAI_API_KEY="sk-k")
    response = provider.run(SearchRequest("q", include_domains=("a.example",), exclude_domains=("spam.example",)))
    url, headers, payload = http.calls[0]
    assert url == "https://api.openai.com/v1/responses" and headers["Authorization"] == "Bearer sk-k"
    assert payload["tools"] == [{"type": "web_search", "filters": {"allowed_domains": ["a.example"], "blocked_domains": ["spam.example"]}}]
    assert payload["input"] == "q" and payload["tool_choice"] == "required" and "web_search_call.action.sources" in payload["include"]
    # the include filter also holds client side
    assert response.hits == [SearchHit("https://a.example/1", "Approved", "Regulators approved it.")]
    assert response.answer == text


def test_openai_defaults_to_the_repos_default_model_and_can_be_overridden():
    from papyrus_content.model_defaults import DEFAULT_LLM_MODEL
    body = {"output": []}
    http = FakeHttp(body, body)
    make(OpenAIProvider, http, OPENAI_API_KEY="k").run(SearchRequest("q"))
    make(OpenAIProvider, http, OPENAI_API_KEY="k", OPENAI_SEARCH_MODEL="gpt-x").run(SearchRequest("q"))
    assert http.calls[0][2]["model"] == DEFAULT_LLM_MODEL and http.calls[1][2]["model"] == "gpt-x"


def test_openai_sources_without_citations_are_titled_by_their_address():
    http = FakeHttp({"output": [{"action": {"sources": [{"url": "https://a.example/1"}, {"url": "https://a.example/1"}]}}]})
    assert make(OpenAIProvider, http, OPENAI_API_KEY="k").search("q") == [SearchHit("https://a.example/1", "https://a.example/1", "")]


def test_perplexity_request_and_response():
    http = FakeHttp({"id": "i", "results": [{"title": "T", "url": "https://a.example/x", "snippet": "S", "date": "2026-10-31", "last_updated": None}]})
    response = make(PerplexityProvider, http, PERPLEXITY_API_KEY="pplx-k").run(
        SearchRequest("q", limit=50, start_date="2026-10-30", end_date="2026-10-31", include_domains=("a.example",)))
    url, headers, payload = http.calls[0]
    assert url == "https://api.perplexity.ai/search" and headers["Authorization"] == "Bearer pplx-k"
    assert payload == {"query": "q", "max_results": 20, "search_domain_filter": ["a.example"],
                       "search_after_date_filter": "10/30/2026", "search_before_date_filter": "10/31/2026"}
    assert response.hits == [SearchHit("https://a.example/x", "T", "S", None, "2026-10-31")] and response.date_bounded


def test_gemini_request_and_response_read_inline_citations():
    text = "Cited sentence. Another."
    http = FakeHttp({"steps": [{"type": "google_search_call"}, {"type": "model_output", "content": [{"type": "text", "text": text, "annotations": [
        {"type": "url_citation", "url": "https://a.example/1", "title": "A", "start_index": 0, "end_index": 15}]}]}]})
    response = make(GeminiProvider, http, GEMINI_API_KEY="g-k").run(SearchRequest("q"))
    url, headers, payload = http.calls[0]
    assert url == "https://generativelanguage.googleapis.com/v1beta/interactions" and headers["x-goog-api-key"] == "g-k"
    assert payload == {"model": "gemini-3.8-flash", "input": "q", "tools": [{"type": "google_search"}]}
    assert response.hits == [SearchHit("https://a.example/1", "A", "Cited sentence.")] and response.answer == text


def test_gemini_also_reads_grounding_metadata():
    http = FakeHttp({"candidates": [{"content": {"parts": [{"text": "Hi"}]}, "groundingMetadata": {"groundingChunks": [{"web": {"uri": "https://a.example/1", "title": "a.example"}}]}}]})
    assert make(GeminiProvider, http, GEMINI_API_KEY="k").search("q") == [SearchHit("https://a.example/1", "a.example", "")]


def test_bedrock_uses_the_mantle_endpoint_a_signed_token_and_no_external_web_access():
    http = FakeHttp({"output": [{"action": {"sources": [{"url": "https://a.example/1"}]}}]})
    provider = BedrockProvider(environ={"AWS_REGION": "us-west-2", "BEDROCK_SEARCH_MODEL": "openai.test-model"}, http=http, token=lambda region: f"bedrock-api-key-{region}")
    assert [h.url for h in provider.run(SearchRequest("q")).hits] == ["https://a.example/1"]
    url, headers, payload = http.calls[0]
    assert url == "https://bedrock-mantle.us-west-2.api.aws/openai/v1/responses" and headers["Authorization"] == "Bearer bedrock-api-key-us-west-2"
    assert payload["tools"] == [{"type": "web_search", "external_web_access": False}] and payload["model"] == "openai.test-model"


def test_bedrock_without_a_model_is_unavailable():
    with pytest.raises(SearchUnavailable, match="BEDROCK_SEARCH_MODEL"):
        BedrockProvider(environ={}, http=FakeHttp(), token=lambda region: "t").search("q")


def test_bedrock_without_aws_credentials_is_unavailable():
    def no_credentials(region):
        raise RuntimeError("no AWS credentials")
    with pytest.raises(SearchUnavailable):
        BedrockProvider(environ={"BEDROCK_SEARCH_MODEL": "m"}, http=FakeHttp(), token=no_credentials).search("q")


def test_exclude_domains_hold_for_providers_that_cannot_express_them():
    http = FakeHttp({"results": [{"title": "T", "url": "https://www.spam.example/x", "snippet": ""}, {"title": "U", "url": "https://ok.example/y", "snippet": ""}]})
    hits = make(PerplexityProvider, http, PERPLEXITY_API_KEY="k").run(SearchRequest("q", exclude_domains=("spam.example",))).hits
    assert [h.url for h in hits] == ["https://ok.example/y"]


# --- keys --------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cls, env", [(TavilyProvider, "TAVILY_API_KEY"), (OpenAIProvider, "OPENAI_API_KEY"),
                                      (PerplexityProvider, "PERPLEXITY_API_KEY"), (GeminiProvider, "GEMINI_API_KEY")])
def test_each_provider_reads_its_key_from_its_environment_variable_or_its_ssm_parameter_once(cls, env):
    assert make(cls, FakeHttp(), **{env: " k "}).api_key() == "k"
    reads = []
    name = cls.name.upper()
    provider = cls(environ={f"PAPYRUS_{name}_KEY_PARAMETER": f"/papyrus/search/{cls.name}-api-key"}, http=FakeHttp(),
                   read_secret=lambda parameter: reads.append(parameter) or "from-ssm")
    assert provider.api_key() == provider.api_key() == "from-ssm"
    assert reads == [f"/papyrus/search/{cls.name}-api-key"]


def test_no_key_and_an_unreadable_parameter_are_unavailable_not_failures():
    with pytest.raises(SearchUnavailable):
        make(TavilyProvider, FakeHttp()).api_key()

    def denied(name):
        raise PermissionError(name)

    with pytest.raises(SearchUnavailable):
        TavilyProvider(environ={"PAPYRUS_TAVILY_KEY_PARAMETER": "/x"}, read_secret=denied).api_key()


# --- failure kinds -----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("status, body, kind", [
    (432, "", "plan_exhausted"), (433, "", "plan_exhausted"), (402, "", "plan_exhausted"),
    (401, "", "auth"), (403, "", "auth"), (429, "", "rate_limited"),
    (429, '{"error": {"code": "insufficient_quota"}}', "plan_exhausted"), (422, "", "bad_request"), (503, "", "server_error")])
def test_http_statuses_become_named_failure_kinds(status, body, kind):
    assert classify(status, body) == kind


def test_a_429_is_retried_once_after_a_short_retry_after_then_fails_as_rate_limited():
    waits = []
    http = FakeHttp(HttpStatusError(429, "", {"Retry-After": "3"}), HttpStatusError(429, "", {"Retry-After": "3"}))
    provider = TavilyProvider(environ={"TAVILY_API_KEY": "k"}, http=http, sleep=waits.append)
    with pytest.raises(Exception) as caught:
        provider.search("q")
    assert waits == [3.0] and len(http.calls) == 2 and str(caught.value) == "tavily: rate limited (429)"


def test_a_429_that_clears_on_the_retry_succeeds():
    http = FakeHttp(HttpStatusError(429), {"results": []})
    assert make(TavilyProvider, http, TAVILY_API_KEY="k").search("q") == [] and len(http.calls) == 2


def test_a_long_retry_after_is_not_waited_out_inside_one_request():
    http = FakeHttp(HttpStatusError(429, "", {"Retry-After": "120"}))
    with pytest.raises(Exception) as caught:
        make(TavilyProvider, http, TAVILY_API_KEY="k").search("q")
    assert len(http.calls) == 1 and caught.value.retry_after == 120.0


def test_a_malformed_answer_and_a_network_error_are_failures():
    for answer, text in ((FakeHttp({"unexpected": 1}), "unreadable answer"), (FakeHttp(OSError("down")), "unreachable")):
        with pytest.raises(Exception) as caught:
            make(TavilyProvider, answer, TAVILY_API_KEY="k").search("q")
        assert text in str(caught.value)


# --- configuration and the chain ---------------------------------------------------------------------------------------------

def test_chain_configuration_precedence():
    assert chain_names(None, {}) == ["gemini", "openai"]
    assert chain_names(None, {"WEB_SEARCH_PROVIDER": "openai"}) == ["openai"]
    assert chain_names(None, {"WEB_SEARCH_PROVIDER": "openai", "WEB_SEARCH_PROVIDERS": " Perplexity, openai ,tavily,openai,bogus"}) == ["perplexity", "openai", "tavily"]
    assert chain_names("gemini,tavily", {"WEB_SEARCH_PROVIDERS": "openai"}) == ["gemini", "tavily"]
    assert chain_names(None, {"WEB_SEARCH_PROVIDERS": "bogus"}) == ["gemini", "openai"]
    with pytest.raises(ValueError):
        parse_names("openai,bogus", strict=True)


def providers_with(**answers):
    return {name: make(cls, http, **{f"{name.upper()}_API_KEY": "k"}) for name, (cls, http) in answers.items()}


def test_an_exhausted_provider_falls_through_and_the_answer_says_why():
    exhausted = FakeHttp(HttpStatusError(432, "{}"))
    answered = FakeHttp({"output": [{"action": {"sources": [{"url": "https://a.example/1"}]}}]})
    chain = SearchChain(["tavily", "openai"], providers=providers_with(tavily=(TavilyProvider, exhausted), openai=(OpenAIProvider, answered)))
    response = chain.run(SearchRequest("q"))
    assert response.provider == "openai" and [h.url for h in response.hits] == ["https://a.example/1"]
    assert [s.describe() for s in response.skipped] == ["tavily: plan exhausted (432)"] and response.skipped[0].failure
    assert chain.name == "openai"


def test_a_provider_without_a_key_is_skipped_as_unavailable_not_as_a_failure():
    keyless = TavilyProvider(environ={}, http=FakeHttp())
    answered = FakeHttp({"results": [{"url": "https://a.example/1", "title": "T"}]})
    chain = SearchChain(["tavily", "perplexity"], providers={"tavily": keyless, "perplexity": make(PerplexityProvider, answered, PERPLEXITY_API_KEY="k")})
    response = chain.run(SearchRequest("q"))
    assert response.provider == "perplexity" and not response.skipped[0].failure and response.skipped[0].kind == "unavailable"


def test_all_providers_keyless_is_search_unavailable():
    chain = SearchChain(["tavily", "openai"], providers={"tavily": TavilyProvider(environ={}), "openai": OpenAIProvider(environ={})})
    with pytest.raises(SearchUnavailable, match="TAVILY_API_KEY"):
        chain.run(SearchRequest("q"))


def test_when_every_provider_fails_the_error_names_each_one():
    chain = SearchChain(["tavily", "openai"], providers=providers_with(
        tavily=(TavilyProvider, FakeHttp(HttpStatusError(432))), openai=(OpenAIProvider, FakeHttp(HttpStatusError(401)))))
    with pytest.raises(SearchChainFailed) as caught:
        chain.run(SearchRequest("q"))
    assert str(caught.value) == "tavily: plan exhausted (432); openai: authentication failed (401)" and not caught.value.rate_limited


def test_a_chain_that_only_met_rate_limits_says_so():
    limited = HttpStatusError(429, "", {"Retry-After": "30"})
    chain = SearchChain(["tavily"], providers=providers_with(tavily=(TavilyProvider, FakeHttp(limited, limited))))
    with pytest.raises(SearchChainFailed) as caught:
        chain.run(SearchRequest("q"))
    assert caught.value.rate_limited and caught.value.retry_after == 30.0


def test_the_chain_is_a_search_provider_for_link_exploration():
    http = FakeHttp({"results": [{"url": "https://a.example/1", "title": "T", "content": "C"}]})
    chain = SearchChain(["tavily"], providers=providers_with(tavily=(TavilyProvider, http)))
    assert chain.search("q", limit=3) == [SearchHit("https://a.example/1", "T", "C", None)] and chain.name == "tavily"
