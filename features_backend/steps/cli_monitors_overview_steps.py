"""Credential-free steps for `papyrus monitors overview|page`, through the real CLI dispatcher."""
import json
import shlex
import sys
import tempfile
from pathlib import Path

import pytest
from behave import given, when, then
from procedures.newsroom.tests.test_monitoring_view_cli import (
    Env, FakeResponse, graphql_answer, OVERVIEW, PAGE,
)


def _env(context, signed_in=True):
    temporary = tempfile.TemporaryDirectory()
    context.add_cleanup(temporary.cleanup)
    context.monkeypatch = pytest.MonkeyPatch()
    context.add_cleanup(context.monkeypatch.undo)
    context.monitors_env = Env(Path(temporary.name), context.monkeypatch, signed_in=signed_in)


@given("a signed-in editor on a machine with no AWS credentials and no AWS library")
def signed_in_editor(context):
    _env(context)


@given("an editor who has not signed in, on a machine with no AWS credentials and no AWS library")
def signed_out_editor(context):
    _env(context, signed_in=False)


@given("a signed-in user whose account the site does not allow to read monitoring")
def non_staff(context):
    _env(context)
    context.monitors_env.answer = lambda request: FakeResponse(200, json.dumps({"data": None, "errors": [{"message": "Not Authorized", "errorType": "Unauthorized"}]}))


@given("a signed-in editor whom the site refuses the whole pipeline")
def non_admin(context):
    _env(context)
    context.monitors_env.answer = graphql_answer("monitoringOverview", {"error": "forbidden"})


@given("the site's monitoring has one feed, one collection run and one item")
def overview_data(context):
    context.monitors_env.answer = graphql_answer("monitoringOverview", OVERVIEW)


@given("the site's monitoring has one older item to page to")
def page_data(context):
    context.monitors_env.answer = graphql_answer("monitoringPage", PAGE)


@when('the editor runs "papyrus {command}"')
def run(context, command):
    words = shlex.split(command)
    assert words[0] == "monitors"
    words = words[1:]
    context.result = context.monitors_env.run(words, context.monkeypatch)


@then("the command succeeds and prints the feed, the run and the item")
def prints_overview(context):
    code, out, err = context.result
    assert code == 0 and err == ""
    assert "feed-a" in out and "2026-01-02T03:00:00Z" in out and "A synthetic item" in out


@then("the command succeeds and prints exactly the response the site sent")
def prints_raw(context):
    code, out, _ = context.result
    assert code == 0 and json.loads(out) == OVERVIEW


@then("the request carried the editor's sign-in token and no AWS signature")
def token_only(context):
    headers = context.monitors_env.requests[0][2]
    assert headers["Authorization"]
    assert not [name for name in headers if name.lower().startswith("x-amz")]


@then("no AWS library was loaded")
def no_aws_library(context):
    assert [name for name in ("boto3", "botocore") if sys.modules.get(name) is not None] == []


@then("the command succeeds and prints the older item and that the list has ended")
def prints_page(context):
    code, out, _ = context.result
    assert code == 0 and "Older item" in out and "End of list." in out


def _variables(context):
    return context.monitors_env.requests[-1][1]["variables"]


@then('the request asked for the "{name}" list after cursor "{cursor}" for the publication scope')
def asked_after_cursor(context, name, cursor):
    assert _variables(context) == {"list": name, "cursor": cursor, "filter": None, "scope": "publication"}


@then('the request asked for the held filter on the "{name}" list')
def asked_held(context, name):
    variables = _variables(context)
    assert variables["list"] == name and variables["filter"] == "held"


def _single_line_failure(context, *words):
    code, out, err = context.result
    assert code != 0 and out == ""
    assert len(err.strip().splitlines()) == 1 and "Traceback" not in err
    for word in words:
        assert word in err, err


@then('the command fails with a single line telling them to run "papyrus login"')
def refuses_signed_out(context):
    _single_line_failure(context, "papyrus login")


@then("nothing was sent to the site")
def nothing_sent(context):
    assert context.monitors_env.requests == []


@then("the command fails with a single line saying monitoring is for editors and admins")
def refuses_non_staff(context):
    _single_line_failure(context, "editors and admins")


@then("the command fails with a single line saying the whole pipeline is for admins")
def refuses_non_admin(context):
    _single_line_failure(context, "whole pipeline", "admins")
