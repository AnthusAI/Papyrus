from __future__ import annotations

import json
from pathlib import Path

from behave import given, then, when

from papyrus_content.editorial_checks import GraphQLEditorialStore
from papyrus_content.editorial_context import _digest, build_context

ROOT = Path(__file__).resolve().parents[2]


def _tenant(text: str) -> str | None:
    return None if text == "none" else text


@when("the site backend's tenant build variable is compared with the Lambdas that receive it")
def compare_tenant_lambdas(context):
    backend = (ROOT / "amplify/site-backend.ts").read_text()
    block = backend[backend.index("const backendTenantId"):]
    loop = block[block.index("for (const tenantLambda of ["):]
    context.tenant_lambdas = loop[:loop.index("]) {")]


@then("the editorial-checks function receives the tenant")
def checks_function_receives_tenant(context):
    assert "backend.editorialChecks.resources.lambda" in context.tenant_lambdas, context.tenant_lambdas


@given('the site\'s editorial context belongs to the tenant "{tenant}"')
def context_tenant(context, tenant):
    pack = build_context({"key": "example", "tenantId": _tenant(tenant)}, {"sectionId": "a"},
                         [{"scope": "publication", "kind": "policy", "text": "RULE", "source": {"id": "policy-v1"}}], mode="cloud")
    context.editorial_pack = pack


@when('the checks function reads the editorial context with the tenant "{tenant}"')
def read_context(context, tenant):
    import os

    pack = context.editorial_pack
    pack["contextHash"] = _digest({key: value for key, value in pack.items() if key not in ("contextHash", "resolvedAt")})

    def execute(query, variables):
        if "CanonicalEditorialPublication" in query:
            rows = [{"id": "knowledge-corpus-example", "name": "Example", "role": "canonical"}]
            return {"listKnowledgeCorporaByRoleAndName": {"items": rows, "nextToken": None}}
        return {"getEditorialContext": json.dumps(pack)}

    previous = os.environ.pop("PAPYRUS_TENANT_ID", None)
    if _tenant(tenant):
        os.environ["PAPYRUS_TENANT_ID"] = tenant   # what the deployed Lambda gets from the site's build variable
    context.editorial_error = None
    try:
        GraphQLEditorialStore(execute).get_editorial_context("a")
    except ValueError as error:
        context.editorial_error = str(error)
    finally:
        os.environ.pop("PAPYRUS_TENANT_ID", None)
        if previous is not None:
            os.environ["PAPYRUS_TENANT_ID"] = previous


@then("the editorial context is accepted")
def context_accepted(context):
    assert context.editorial_error is None, context.editorial_error


@then('the editorial context is refused as an "{message}"')
def context_refused(context, message):
    assert context.editorial_error == message, context.editorial_error
