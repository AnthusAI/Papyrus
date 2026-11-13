"""Knowledge queries count tokens exactly or stop (features_backend/no-fallbacks-knowledge-query.feature)."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import tiktoken  # noqa: E402

from papyrus_knowledge_query import engine  # noqa: E402
from papyrus_knowledge_query.services import KnowledgeQueryServices  # noqa: E402
from papyrus_knowledge_query.tokens import TokenCounter  # noqa: E402

TEXT = "Production agents rely on human evaluation, task success, and regression checks."


def held(context) -> SimpleNamespace:
    if not hasattr(context, "kq"):
        context.kq = SimpleNamespace(counter=None, count=None, truncated=None, error=None, graph=None)
    return context.kq


@given("the token counter")
def _counter(context):
    held(context).counter = TokenCounter()


@when("it counts and truncates a sentence")
def _count(context):
    state = held(context)
    state.count = state.counter.count(TEXT)
    state.truncated = state.counter.truncate(TEXT, 5)


@when("the tokenizer model is one tiktoken does not know")
def _unknown(context):
    state = held(context)
    try:
        state.count = state.counter.with_model("no-such-model-for-tiktoken").count(TEXT)
    except Exception as error:  # the scenario asserts on it
        state.error = error


@then("the count equals tiktoken's count, truncation stays within the budget, and the counter has no regex or switch-off mode")
def _exact(context):
    state = held(context)
    encoding = tiktoken.get_encoding("o200k_base")
    assert state.count == len(encoding.encode(TEXT))
    assert state.counter.count(state.truncated) <= 5
    assert state.counter.metadata()["provider"] == "tiktoken"
    assert {field.name for field in dataclasses.fields(TokenCounter)} == {"tokenizer_model", "encoding_name"}
    assert not hasattr(TokenCounter, "_regex_count")


@then("counting raises tiktoken's error and no approximate count is returned")
def _raises(context):
    state = held(context)
    assert state.error is not None and state.count is None, f"expected an error, got count {state.count!r}"


class _FailingGraph:
    def resolve_anchor(self, anchor):
        raise RuntimeError("message lookup failed")


@given("a graph whose message lookup fails")
def _graph(context):
    held(context).graph = _FailingGraph()


@when("a reference summary is read through a relation")
def _read(context):
    state = held(context)
    relation = {
        "relationTypeKey": "reference_summary_100_tokens",
        "relationState": "current",
        "subjectKind": "message",
        "objectKind": "reference",
        "subjectId": "message-1",
    }
    try:
        engine._reference_summary_from_relation({"id": "reference-1"}, relation, state.graph, KnowledgeQueryServices())
    except Exception as error:
        state.error = error


@then("the lookup error reaches the caller")
def _reaches(context):
    error = held(context).error
    assert error is not None and "message lookup failed" in str(error), f"got {error!r}"
