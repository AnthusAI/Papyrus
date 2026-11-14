import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

import test_knowledge_query_openai_key as kq  # noqa: E402


@given("a knowledge-query function configured with a branch path and a shared path for its key")
def step_configured(context):
    context.kq = {"store": {}, "errors": {}, "ssm": None, "key": None, "error": None}


@given("the key is stored only at the shared path")
def step_shared_only(context):
    context.kq["store"] = {kq.SHARED: kq.PLACEHOLDER_VALUE}


@given("the key is stored at the branch path")
def step_branch(context):
    context.kq["store"] = {kq.BRANCH: kq.PLACEHOLDER_VALUE}


@given("reading the branch path is denied")
def step_denied(context):
    context.kq["errors"] = {kq.BRANCH: "AccessDeniedException"}


@when("semantic search loads its key")
def step_load(context):
    state = context.kq
    state["ssm"] = kq.StubSsm(state["store"], state["errors"])
    try:
        state["key"] = kq.resolve(state["ssm"])
    except Exception as error:  # noqa: BLE001 - the scenario inspects the failure
        state["error"] = error


@then("the key is found")
def step_found(context):
    assert context.kq["error"] is None, context.kq["error"]
    assert context.kq["key"] == kq.PLACEHOLDER_VALUE


@then("the branch path was tried before the shared path")
def step_order(context):
    assert context.kq["ssm"].calls == [kq.BRANCH, kq.SHARED], context.kq["ssm"].calls


@then("the shared path was never read")
def step_no_shared(context):
    assert kq.SHARED not in context.kq["ssm"].calls, context.kq["ssm"].calls


@then("loading fails with the access error")
def step_access_error(context):
    error = context.kq["error"]
    assert isinstance(error, kq.StubSsmError), repr(error)
    assert error.response["Error"]["Code"] == "AccessDeniedException"


@then("loading fails and names both paths")
def step_names_paths(context):
    error = context.kq["error"]
    assert isinstance(error, RuntimeError), repr(error)
    assert kq.BRANCH in str(error) and kq.SHARED in str(error)
