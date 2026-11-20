"""The editorial check's reads (features_backend/stories/editorial-check-input.feature): the real store over a recording transport that, like AppSync,
returns only the fields a query selects."""
from __future__ import annotations

import json
import re
from unittest import mock

from behave import given, then, when

from papyrus_content import editorial_checks
from papyrus_content.editorial_checks import GraphQLEditorialStore
from papyrus_content.editorial_context import _digest, build_context
from papyrus_content.editorial_languages import story_language

ROW = {"id": "story-v4", "lineageId": "story", "versionNumber": 4, "section": "news", "contentHash": "h", "bodyMarkus": "Text.\n",
       "language": "en", "languageGroupId": "story", "title": "Not selected by the check"}


def _selected(query: str) -> list[str]:
    return re.search(r"getItem\(id: \$id\) \{ ([^}]*) \}", query).group(1).split()


@given('a saved Story version written in "{language}" in its own language group')
def step_row(context, language):
    context.row = {**ROW, "language": language}


@when("the editorial check reads the saved version")
def step_read(context):
    context.queries = []

    def execute(query, variables):
        context.queries.append(query)
        return {"getItem": {name: context.row[name] for name in _selected(query) if name in context.row}}

    context.store = GraphQLEditorialStore(execute)
    context.item = context.store.get_item("story-v4")


@then('the version is read with its language "{language}" and its language group')
def step_with_language(context, language):
    assert context.item.get("language") == language and context.item.get("languageGroupId") == "story", context.item


@then('the language the check uses for it is "{language}"')
def step_check_language(context, language):
    assert story_language(context.item, {"languages": {"primary": "en", "enabled": ["en"]}}) == language


def _read_context(context, tenant, shared: bool) -> None:
    context.queries = []
    pack = build_context({"key": "example", "tenantId": tenant}, {"sectionId": "a"},
                         [{"scope": "publication", "kind": "policy", "text": "RULE", "source": {"id": "policy-v1"}}], mode="cloud")
    pack["contextHash"] = _digest({key: value for key, value in pack.items() if key not in ("contextHash", "resolvedAt")})

    def execute(query, variables):
        context.queries.append((query, variables))
        if "CanonicalEditorialPublication" in query:
            return {"listKnowledgeCorporaByRoleAndName": {"items": [{"id": "knowledge-corpus-example", "name": "Example", "role": "canonical"}], "nextToken": None}}
        return {"getEditorialContext": json.dumps(pack)}

    with mock.patch.object(editorial_checks, "is_shared_stack", return_value=shared):
        GraphQLEditorialStore(execute, tenant_id=tenant).get_editorial_context("a")
    context.context_query = next(entry for entry in context.queries if "EffectiveEditorialContext" in entry[0])


@when("the check reads the editorial context of a site that has its own backend")
def step_own_backend(context):
    _read_context(context, None, False)


@when('the check reads the editorial context of the tenant "{tenant}" on the shared stack')
def step_shared(context, tenant):
    _read_context(context, tenant, True)


@then("the query sent names no tenant argument")
def step_no_tenant(context):
    query, variables = context.context_query
    assert "tenantId" not in query and "tenantId" not in variables, context.context_query


@then('the query sent names the tenant "{tenant}"')
def step_tenant(context, tenant):
    query, variables = context.context_query
    assert "tenantId: $tenantId" in query and variables["tenantId"] == tenant, context.context_query
