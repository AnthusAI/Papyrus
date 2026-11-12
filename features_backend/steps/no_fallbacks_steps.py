"""One correct path that fails clearly (features_backend/no-fallbacks.feature). The GraphQL call is a stand-in."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_newsroom import reference_curation_signals as signals  # noqa: E402

MISSING_FIELD = "Validation error of type FieldUndefined: Field 'listReferencesByNewsroomFeedAndImportedAt' in type 'Query' is undefined"


def held(context) -> SimpleNamespace:
    if not hasattr(context, "nofallbacks"):
        context.nofallbacks = SimpleNamespace(answer=None, result=None, error=None, queries=[])
    return context.nofallbacks


@given("the backend answers the import-date index with two current References and one superseded one")
def _two_current(context):
    rows = [{"id": "a", "versionState": "current"}, {"id": "b", "versionState": "current"}, {"id": "c", "versionState": "superseded"}]
    held(context).answer = {"listReferencesByNewsroomFeedAndImportedAt": {"items": rows, "nextToken": None}}


@given("the backend answers the import-date index with nothing")
def _nothing(context):
    held(context).answer = {"listReferencesByNewsroomFeedAndImportedAt": {"items": [], "nextToken": None}}


@given("the backend does not define the import-date index")
def _undefined(context):
    held(context).answer = RuntimeError(MISSING_FIELD)


@when("the References are listed by import date for a corpus")
def _list(context):
    state = held(context)

    def graphql(query, variables=None):
        state.queries.append(query)
        if isinstance(state.answer, Exception):
            raise state.answer
        return state.answer

    with mock.patch.object(signals, "execute_graphql", graphql):
        try:
            state.result = signals.list_references_by_newsroom_feed_imported(limit=10, corpus_id="corpus-1")
        except Exception as error:  # the scenario asserts on it
            state.error = error


@then("only the two current References come back from the import-date listing")
def _only_current(context):
    assert [row["id"] for row in held(context).result] == ["a", "b"], held(context).result


@then("the import-date listing is empty")
def _empty_listing(context):
    assert held(context).error is None and held(context).result == []


@then("the listing fails and the error names listReferencesByNewsroomFeedAndImportedAt")
def _fails(context):
    assert held(context).error is not None and "listReferencesByNewsroomFeedAndImportedAt" in str(held(context).error)


@then("the corpus index was not read for the import-date listing")
def _no_corpus(context):
    assert not any(signals.LIST_REFERENCES_BY_CORPUS_QUERY == query for query in held(context).queries), "the corpus index was read"
