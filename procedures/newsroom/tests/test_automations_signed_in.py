"""`papyrus automations list|show|runs|run` and `papyrus knowledge query` signed in: no AWS credentials, no boto3. Synthetic data."""
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

import pytest

import automation_fixture as fx
from papyrus_content import automations as au
from papyrus_content.automations import MonitoringReader
from procedures.newsroom.tests.test_monitoring_view_cli import Env, FakeResponse, graphql_answer

AUTOMATIONS = ("automations",)


def overview_for(*ids):
    rows = [fx.automation_row(id=name, title=f"Automation {name}") for name in ids] or None
    overview = au.automation_overview(fx.site_client(*(rows or [])), reader=MonitoringReader(fx.FakeMonitoringTable()),
                                      limit=au.DEFAULT_RUN_LIMIT, now="2026-10-24T09:00:00Z")
    return json.loads(json.dumps(overview, default=str))


def mark_signed_in(tmp_path):
    """`papyrus login` leaves its registry here; its existence is what selects the signed-in lane."""
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "user-session.json").write_text("{}")


@pytest.fixture
def env(tmp_path, monkeypatch):
    found = Env(tmp_path, monkeypatch)
    mark_signed_in(tmp_path)
    found.answer = lambda request: FakeResponse(200, json.dumps({"data": {"automationOverview": json.dumps(OVERVIEW)}}))
    return found


OVERVIEW = overview_for("distinctive.ttab")


def run(env, monkeypatch, *argv):
    return env.run(list(argv), monkeypatch, group=AUTOMATIONS)


def test_list_asks_the_site_with_the_signed_in_token_and_prints_the_automation(env, monkeypatch):
    code, out, err = run(env, monkeypatch, "list")
    assert code == 0 and err == ""
    method, body, headers = env.requests[0]
    assert "automationOverview" in body["query"] and body["variables"] == {"automationId": None}
    assert headers["Authorization"] and not [name for name in headers if name.lower().startswith("x-amz")]
    assert "distinctive.ttab" in out and "monitor" in out
    assert not any(name.startswith("boto") for name in sys.modules if sys.modules[name] is not None)


def test_show_names_one_automation_and_the_router_link(env, monkeypatch):
    code, out, _ = run(env, monkeypatch, "show", "--id", "distinctive.ttab")
    assert code == 0 and "title\tAutomation distinctive.ttab" in out and "router\t" in out
    assert env.requests[0][1]["variables"] == {"automationId": "distinctive.ttab"}


def test_runs_prints_each_run_and_the_cost_line(env, monkeypatch):
    code, out, _ = run(env, monkeypatch, "runs", "--id", "distinctive.ttab")
    assert code == 0 and "run-1" in out and "cost\t" in out


def test_runs_limit_cuts_the_list_and_a_longer_one_is_refused(env, monkeypatch):
    code, out, _ = run(env, monkeypatch, "runs", "--id", "distinctive.ttab", "--limit", "1")
    assert code == 0 and len([line for line in out.splitlines() if line.startswith("run\t")]) == 1
    count = len(env.requests)
    code, _, err = run(env, monkeypatch, "runs", "--id", "distinctive.ttab", "--limit", "500")
    assert code == 2 and len(err.strip().splitlines()) == 1 and "--limit above" in err and len(env.requests) == count


def test_json_prints_the_site_response_with_the_ok_envelope(env, monkeypatch):
    code, out, _ = run(env, monkeypatch, "list", "--json")
    printed = json.loads(out)
    assert code == 0 and printed["ok"] is True and printed["command"] == "automations list" and printed["automations"][0]["id"] == "distinctive.ttab"


def test_an_unknown_automation_and_a_missing_id_are_one_line(env, monkeypatch):
    env.answer = lambda request: FakeResponse(200, json.dumps({"data": {"automationOverview": json.dumps({"state": "empty", "automations": [], "monitoring": "ready"})}}))
    code, _, err = run(env, monkeypatch, "show", "--id", "nope")
    assert code == 2 and err.strip() == "automation nope does not exist."
    code, _, err = run(env, monkeypatch, "runs")
    assert code == 2 and "needs --id" in err


def test_runs_without_the_monitoring_table_is_refused(env, monkeypatch):
    env.answer = lambda request: FakeResponse(200, json.dumps({"data": {"automationOverview": json.dumps({**OVERVIEW, "monitoring": "not_configured"})}}))
    code, _, err = run(env, monkeypatch, "runs", "--id", "distinctive.ttab")
    assert code == 2 and "monitoring table" in err


def test_run_sends_the_input_to_run_automation_and_never_touches_lambda(env, monkeypatch):
    env.answer = graphql_answer("runAutomation", {"state": "started", "automationId": "distinctive.ttab", "requestedBy": "editor@example.test", "key": "MANUAL#x"})
    code, out, err = run(env, monkeypatch, "run", "--id", "distinctive.ttab", "--input", '{"proceeding": "1"}')
    assert code == 0 and err == "" and "started" in out and "MANUAL#x" in out
    body = env.requests[0][1]
    assert "runAutomation" in body["query"] and body["variables"] == {"automationId": "distinctive.ttab", "input": '{"proceeding": "1"}'}


def test_run_dry_run_is_refused_with_nothing_sent(env, monkeypatch):
    code, out, err = run(env, monkeypatch, "run", "--id", "distinctive.ttab", "--dry-run")
    assert code == 2 and out == "" and "--dry-run is not available" in err and len(err.strip().splitlines()) == 1 and env.requests == []


@pytest.mark.parametrize("answer, words", [
    ({"state": "refused", "reason": "this automation is disabled; enable it before running it."}, "disabled"),
    ({"state": "unavailable"}, "unavailable"),
    ({"error": "forbidden"}, "editors and admins"),
])
def test_run_refusals_from_the_site_are_one_line(env, monkeypatch, answer, words):
    env.answer = graphql_answer("runAutomation", answer)
    code, out, err = run(env, monkeypatch, "run", "--id", "distinctive.ttab")
    assert code == 2 and out == "" and len(err.strip().splitlines()) == 1 and words in err


def test_a_user_who_is_not_an_editor_is_refused_on_list(env, monkeypatch):
    env.answer = lambda request: FakeResponse(200, json.dumps({"data": None, "errors": [{"message": "Not Authorized", "errorType": "Unauthorized"}]}))
    code, out, err = run(env, monkeypatch, "list")
    assert code == 2 and out == "" and "editors and admins" in err and len(err.strip().splitlines()) == 1


def test_signed_out_with_an_iam_lane_chosen_keeps_the_old_path(tmp_path, monkeypatch):
    """Not signed in, no session file: the signed-in lane is not selected, so the AWS path (unchanged) is used."""
    found = Env(tmp_path, monkeypatch, signed_in=False)
    with patch("papyrus_content.graphql_authoring.create_authoring_client", side_effect=RuntimeError("old path reached")), \
         patch("papyrus_content.automations_signed_in.run_command", side_effect=AssertionError("signed-in lane used")):
        with pytest.raises(RuntimeError, match="old path reached"):
            from papyrus_content.automations import run_command
            run_command("list", [])


# --- papyrus knowledge query ---------------------------------------------------------------------------------

RESULT = {"context": {"text": "synthetic context"}, "debug": {}, "provenance": {}}


def knowledge(env, monkeypatch, *argv):
    from papyrus import cli
    for name in [m for m in sys.modules if m == "boto3" or m == "botocore" or m.startswith(("boto3.", "botocore."))]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.setitem(sys.modules, "botocore", None)

    def forbidden(*a, **k): raise AssertionError("the IAM lane was used")

    class Response:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(self.body).encode()

    seen = []

    def fake_urlopen(request, timeout):
        seen.append((json.loads(request.data), dict(request.header_items())))
        return Response({"data": {"knowledgeQuery": json.dumps(RESULT)}})

    out, err = StringIO(), StringIO()
    with patch("papyrus_content.cli_user_auth.session_for", return_value=env.session), \
         patch("papyrus_content.cli_user_auth.config_for_endpoint", return_value=env.config), \
         patch("papyrus_content.graphql_http.iam_signed_graphql_headers", forbidden), \
         patch("papyrus_knowledge_query.cli.iam_signed_graphql_headers", forbidden), \
         patch("papyrus_content.graphql_http._aws_credentials", forbidden), \
         patch("papyrus_knowledge_query.cli.urllib.request.urlopen", fake_urlopen), \
         redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(["knowledge", "query", *argv])
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue(), seen


def test_knowledge_query_runs_on_the_signed_in_session_with_no_aws(env, monkeypatch):
    code, out, err, seen = knowledge(env, monkeypatch, "--query", "synthetic topic")
    assert code == 0, err
    body, headers = seen[0]
    assert "knowledgeQuery" in body["query"] and json.loads(body["variables"]["input"])["semanticQuery"] == "synthetic topic"
    assert headers["Authorization"] and not [name for name in headers if name.lower().startswith("x-amz")]
    assert json.loads(out)["debug"]["cliExecution"] == "remote"


def test_knowledge_query_signed_out_is_one_line_and_not_iam(tmp_path, monkeypatch):
    found = Env(tmp_path, monkeypatch, signed_in=False)
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "user")   # the signed-in lane chosen, but there is no session
    code, out, err, seen = knowledge(found, monkeypatch, "--query", "x", "--execution", "remote")
    assert code != 0 and out == "" and seen == [] and "papyrus login" in err and "Traceback" not in err


def test_knowledge_query_iam_lane_is_still_available_for_roles(tmp_path, monkeypatch):
    """PAPYRUS_GRAPHQL_AUTH=iam never looks at a session: scheduled jobs and Lambdas keep their own role."""
    from papyrus_knowledge_query import cli as kq
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    monkeypatch.setenv("PAPYRUS_GRAPHQL_ENDPOINT", "https://abc.appsync-api.us-east-1.amazonaws.com/graphql")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret-example")
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"data": {"knowledgeQuery": json.dumps(RESULT)}}).encode()

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.headers.get("Authorization")
        return Response()

    with patch("papyrus_knowledge_query.cli.urllib.request.urlopen", fake_urlopen):
        assert kq._run_remote_knowledge_query({"semanticQuery": "x"}) == RESULT
    assert captured["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
