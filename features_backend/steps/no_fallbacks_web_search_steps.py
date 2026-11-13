"""Web search providers are named in one place (features_backend/no-fallbacks-web-search.feature)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.web_search import chain_names  # noqa: E402


def held(context) -> SimpleNamespace:
    if not hasattr(context, "websearch"):
        context.websearch = SimpleNamespace(environ={}, chain=None, error=None)
    return context.websearch


@given("WEB_SEARCH_PROVIDERS names two providers")
def _chain(context):
    held(context).environ = {"WEB_SEARCH_PROVIDERS": "perplexity,tavily"}


@given("only the retired WEB_SEARCH_PROVIDER is set")
def _retired(context):
    held(context).environ = {"WEB_SEARCH_PROVIDER": "openai"}


@when("the provider chain is resolved")
def _resolve(context):
    state = held(context)
    try:
        state.chain = chain_names(None, state.environ)
    except ValueError as error:  # the scenario asserts on it
        state.error = error


@then("the chain is those two providers in order")
def _two(context):
    assert held(context).chain == ["perplexity", "tavily"]


@then("resolution fails and the error names WEB_SEARCH_PROVIDERS")
def _fails(context):
    state = held(context)
    assert state.error is not None and "WEB_SEARCH_PROVIDERS" in str(state.error) and state.chain is None
