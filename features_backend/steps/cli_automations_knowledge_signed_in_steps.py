"""Credential-free steps for the signed-in `papyrus automations` and `papyrus knowledge query`, through the real CLI dispatcher."""
import json
import shlex
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from behave import given, when, then
from procedures.newsroom.tests.test_automations_signed_in import OVERVIEW, RESULT, knowledge, mark_signed_in
from procedures.newsroom.tests.test_monitoring_view_cli import Env, FakeResponse, graphql_answer


def _env(context, signed_in=True):
    temporary = tempfile.TemporaryDirectory()
    context.add_cleanup(temporary.cleanup)
    context.monkeypatch = pytest.MonkeyPatch()
    context.add_cleanup(context.monkeypatch.undo)
    context.signed_in_env = context.monitors_env = Env(Path(temporary.name), context.monkeypatch, signed_in=signed_in)   # the shared monitors steps read monitors_env
    if signed_in:
        mark_signed_in(Path(temporary.name))
    return context.signed_in_env


@given("a signed-in editor of a site with one automation, on a machine with no AWS credentials and no AWS library")
def signed_in(context):
    env = _env(context)
    env.answer = graphql_answer("automationOverview", OVERVIEW)


@given("the site starts any run it is asked for")
def starts(context):
    context.signed_in_env.answer = graphql_answer("runAutomation", {"state": "started", "automationId": "distinctive.ttab", "requestedBy": "editor@example.test", "key": "MANUAL#synthetic"})


@given("a signed-in user whom the site does not allow to read automations")
def not_staff(context):
    env = _env(context)
    env.answer = lambda request: FakeResponse(200, json.dumps({"data": None, "errors": [{"message": "Not Authorized", "errorType": "Unauthorized"}]}))


@given("an editor who has chosen the signed-in lane but has not signed in")
def signed_out(context):
    _env(context, signed_in=False)
    context.monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "user")


@given("a scheduled job whose role holds AWS credentials and has chosen the IAM lane")
def job(context):
    context.monkeypatch = pytest.MonkeyPatch()
    context.add_cleanup(context.monkeypatch.undo)
    context.monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    context.monkeypatch.setenv("PAPYRUS_GRAPHQL_ENDPOINT", "https://abc.appsync-api.us-east-1.amazonaws.com/graphql")
    context.monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    context.monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret-example")


@when('the editor runs the signed-in command "papyrus {command}"')
def run(context, command):
    words = shlex.split(command)
    env = context.signed_in_env
    if words[0] == "knowledge":
        code, out, err, seen = knowledge(env, context.monkeypatch, *words[2:])
        context.result, context.knowledge_requests = (code, out, err), seen
        return
    context.result = env.run(words[1:], context.monkeypatch, group=("automations",))


@when("the job asks for a remote knowledge query")
def job_asks(context):
    from papyrus_knowledge_query import cli as kq
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"data": {"knowledgeQuery": json.dumps(RESULT)}}).encode()

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.headers.get("Authorization")
        return Response()

    with patch("papyrus_knowledge_query.cli.urllib.request.urlopen", fake_urlopen):
        kq._run_remote_knowledge_query({"semanticQuery": "x"})
    context.job_authorization = captured["authorization"]


@then("the command succeeds and prints the automation")
def prints_automation(context):
    code, out, err = context.result
    assert code == 0 and err == "" and "distinctive.ttab" in out


@then("the command succeeds and prints the automation's runs and their cost line")
def prints_runs(context):
    code, out, err = context.result
    assert code == 0 and "run-1" in out and "cost\t" in out


@then("the command succeeds and says the run started")
def says_started(context):
    code, out, err = context.result
    assert code == 0 and "started" in out and "MANUAL#synthetic" in out


@then('the site was asked to run "{automation_id}" with that input')
def asked(context, automation_id):
    body = context.signed_in_env.requests[0][1]
    assert "runAutomation" in body["query"]
    assert body["variables"] == {"automationId": automation_id, "input": '{"proceeding": "1"}'}


@then("the command fails with a single line saying a dry run is not available when signed in")
def no_dry_run(context):
    code, out, err = context.result
    assert code == 2 and out == "" and len(err.strip().splitlines()) == 1 and "--dry-run is not available" in err


@then("the command fails with a single line saying that history length is not available when signed in")
def no_long_history(context):
    code, out, err = context.result
    assert code == 2 and len(err.strip().splitlines()) == 1 and "--limit above" in err


@then("the command fails with a single line saying automations are for editors and admins")
def staff_only(context):
    code, out, err = context.result
    assert code == 2 and out == "" and len(err.strip().splitlines()) == 1 and "editors and admins" in err


@then("the command succeeds and prints the context the site returned")
def prints_context(context):
    code, out, err = context.result
    assert code == 0 and json.loads(out)["context"]["text"] == "synthetic context"


@then("the knowledge request carried the editor's sign-in token and no AWS signature")
def knowledge_token(context):
    headers = context.knowledge_requests[0][1]
    assert headers["Authorization"] and not [name for name in headers if name.lower().startswith("x-amz")]


@then("the request is signed with the job's AWS credentials")
def job_signed(context):
    assert context.job_authorization.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
