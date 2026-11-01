from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_web as tw  # noqa: E402
from test_web_search import FakeHttp  # noqa: E402
from papyrus_content.monitoring_web import search_fetch  # noqa: E402
from papyrus_content.web_search import (PROVIDERS, HttpStatusError, SearchChain, SearchChainFailed, SearchRequest,  # noqa: E402
                                        SearchUnavailable, chain_names)

ANSWERS = {
    "tavily": {"results": [{"url": "https://example.org/story-1", "title": "Story 1", "content": "Snippet 1", "score": 0.5}]},
    "perplexity": {"results": [{"url": "https://example.org/story-1", "title": "Story 1", "snippet": "Snippet 1"}]},
    "openai": {"output": [{"action": {"sources": [{"url": "https://example.org/story-1"}]}}]},
    "gemini": {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "x", "annotations": [
        {"type": "url_citation", "url": "https://example.org/story-1", "title": "Story 1", "start_index": 0, "end_index": 1}]}]}]},
}


def _state(context):
    if not hasattr(context, "ws"):
        context.ws = {"names": [], "http": {}, "env": {}, "reads": [], "monitor": None}
    return context.ws


def _names(text):
    return [n.strip() for n in text.split(",")]


@given('web search is configured with the providers "{names}"')
def step_providers(context, names):
    state = _state(context)
    state["names"] = _names(names)
    state["env"] = {f"{n.upper()}_API_KEY": "test-key" for n in state["names"]}


@given("web search has no provider configuration at all")
def step_no_configuration(context):
    _state(context)["env"] = {}


@given('web search is configured with the old single setting "{name}"')
def step_old_setting(context, name):
    _state(context)["env"] = {"WEB_SEARCH_PROVIDER": name}


@then('the provider chain is "{names}"')
def step_chain_is(context, names):
    assert chain_names(None, context.ws["env"]) == _names(names)


@given("{name} answers with one page")
def step_answers(context, name):
    _state(context)["http"].setdefault(name.lower(), FakeHttp(*[ANSWERS[name.lower()]] * 20))


@given("OpenAI answers with one source")
def step_openai_answers(context):
    _state(context)["http"]["openai"] = FakeHttp(*[ANSWERS["openai"]] * 20)


@given("Tavily refuses with its plan-exhausted status 432")
def step_tavily_432(context):
    _state(context)["http"]["tavily"] = FakeHttp(*[HttpStatusError(432, "{}")] * 20)


@given("OpenAI refuses the key with status 401")
def step_openai_401(context):
    _state(context)["http"]["openai"] = FakeHttp(*[HttpStatusError(401, "{}")] * 20)


@given("no Gemini key is configured")
def step_no_gemini(context):
    _state(context)["env"].pop("GEMINI_API_KEY", None)


@given('the {name} key is only in the parameter "{parameter}"')
def step_parameter(context, name, parameter):
    state = _state(context)
    state["env"].pop(f"{name.upper()}_API_KEY", None)
    state["env"][f"PAPYRUS_{name.upper()}_KEY_PARAMETER"] = parameter


def _chain(state, names):
    providers = {}
    for name in names:
        http = state["http"].get(name, FakeHttp())
        providers[name] = PROVIDERS[name](environ=state["env"], http=http, sleep=lambda s: None,
                                          read_secret=lambda parameter: state["reads"].append(parameter) or "from-ssm")
    return SearchChain(names, providers=providers)


@when('a search for "{query}" runs')
def step_search(context, query):
    state = context.ws
    context.error, context.response = None, None
    try:
        context.response = _chain(state, state["names"]).run(SearchRequest(query))
    except (SearchChainFailed, SearchUnavailable) as error:
        context.error = str(error)


@then("{name} answered")
def step_answered(context, name):
    assert context.response and context.response.provider == name.lower(), context.error


@then("the hit has the page's URL, title and snippet")
def step_hit(context):
    (hit,) = context.response.hits
    assert (hit.url, hit.title, hit.snippet) == ("https://example.org/story-1", "Story 1", "Snippet 1")


@then("no provider was skipped")
def step_none_skipped(context):
    assert context.response.skipped == []


@then('the result says "{message}"')
def step_says(context, message):
    assert message in [s.describe() for s in context.response.skipped]


@then("Gemini was skipped as unavailable and not as a failure")
def step_unavailable(context):
    (skip,) = context.response.skipped
    assert skip.provider == "gemini" and skip.kind == "unavailable" and not skip.failure


@then('the parameter "{parameter}" was read')
def step_read(context, parameter):
    assert context.ws["reads"] == [parameter]


@then('the search fails with "{message}"')
def step_fails(context, message):
    assert context.error == message, context.error


@given('a web monitor whose configuration says searchProviders is "{names}"')
def step_monitor(context, names):
    state = _state(context)
    state["monitor"] = _names(names)
    state["names"] = state["monitor"]
    state["env"] = {f"{n.upper()}_API_KEY": "test-key" for n in ["tavily", "perplexity"]}
    context.table_ = tw.web_table(searchProviders=state["monitor"])


@when("the monitor searches through its provider chain")
def step_monitor_collects(context):
    state = context.ws
    if state["monitor"] is None:   # the shared steps of monitoring-web-search.feature use their own context
        raise AssertionError("no web monitor was set up")
    chain = _chain(state, state["monitor"])
    context.result = tw.collect(context.table_, search_fetch({"searchProviders": state["monitor"]}, chain))


@then("Perplexity answered the monitor's searches")
def step_monitor_perplexity(context):
    assert len(context.ws["http"]["perplexity"].calls) >= 1


@then("Tavily was never asked")
def step_tavily_never(context):
    assert "tavily" not in context.ws["http"] or not context.ws["http"]["tavily"].calls


@then("the monitor's run recorded the page as found")
def step_found(context):
    assert context.result["new"] == 1 and len(tw.discs(context.table_)) == 1


@then('the query run says Perplexity answered and "{message}"')
def step_qrun(context, message):
    (run,) = tw.rows(context.table_, "QRUN#")
    assert list(run["providers"]) == ["perplexity"] and run["skipped"] == [message]
