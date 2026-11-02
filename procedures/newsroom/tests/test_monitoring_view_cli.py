"""`papyrus monitors overview|page`: read-only, signed-in, no AWS. Synthetic data, no network, no keychain."""
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

import pytest
from papyrus_content.cli_user_auth import AuthConfig, SiteSession
from procedures.newsroom.tests.test_cli_user_auth import MemoryStore, Provider

ENDPOINT = "https://abc.appsync-api.us-east-1.amazonaws.com/graphql"
AWS_VARIABLES = ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_REGION",
                 "AWS_DEFAULT_REGION", "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE")

OVERVIEW = {
    "state": "ready", "asOf": "2026-01-02T03:04:05Z",
    "scope": {"mode": "publication", "publicationId": "pub-1", "site": "news.example.test", "canViewAll": False},
    "feeds": [{"id": "feed-a", "enabled": True, "lastStatus": "ok", "nextDueAt": "2026-01-02T04:00:00Z"}],
    "runs": [{"runId": "r1", "startedAt": "2026-01-02T03:00:00Z", "status": "ok", "new": 3, "revised": 1, "unchanged": 0, "errorCount": 0}],
    "routerRuns": [], "router": {"mode": "live", "feedback": True, "enabled": True},
    "usage": {"day": "2026-01-02", "decisionsToday": 4, "decisionsTotal": 40, "historyComplete": True},
    "items": [{"sourceId": "s-1", "revision": 1, "title": "A synthetic item", "routing": "routed", "relevance": []}],
    "emailSubmissions": [], "hiddenNotRelevant": 2, "cursors": {"items": "cursor-1"},
}
PAGE = {"list": "items", "rows": [{"sourceId": "s-2", "revision": 1, "title": "Older item", "routing": "decided", "relevance": []}], "cursor": None}


class FakeResponse:
    def __init__(self, status, body): self.status, self.reason, self._body = status, "", body
    def read(self): return self._body.encode()


class FakeConnection:
    """Stands in for the AppSync HTTPS connection; records every request."""
    def __init__(self, answer, log): self.answer, self.log = answer, log
    def request(self, method, path, body=None, headers=None): self.log.append((method, json.loads(body), dict(headers)))
    def getresponse(self): return self.answer(self.log[-1][1])
    def close(self): pass


def graphql_answer(field, value):
    return lambda request: FakeResponse(200, json.dumps({"data": {field: json.dumps(value)}}))


class Env:
    def __init__(self, tmp_path, monkeypatch, signed_in=True):
        for name in AWS_VARIABLES: monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("PAPYRUS_CLI_STATE_DIR", str(tmp_path / "state"))
        monkeypatch.setenv("PAPYRUS_GRAPHQL_ENDPOINT", ENDPOINT)
        monkeypatch.delenv("PAPYRUS_GRAPHQL_AUTH", raising=False)
        self.config = AuthConfig(publication="https://news.example.test", issuer="https://cognito-idp.us-east-1.amazonaws.com/pool",
                                 client_id="native-client", oauth_domain="https://news.auth.us-east-1.amazoncognito.com",
                                 graphql_endpoint=ENDPOINT, callback_uri="http://127.0.0.1:5182/oauth/callback", refresh_lifetime_seconds=172800)
        clock = [1000.0]
        self.session = SiteSession(self.config, store=MemoryStore(), provider=Provider(clock), clock=lambda: clock[0], receive=lambda *a: "fixture-code")
        if signed_in: self.session.login()
        self.requests = []
        self.answer = graphql_answer("monitoringOverview", OVERVIEW)

    def run(self, argv, monkeypatch, group=("monitors",)):
        """Run through the real CLI entry point with boto3 unimportable and any IAM path failing the test."""
        from papyrus import cli
        for name in [m for m in sys.modules if m == "boto3" or m == "botocore" or m.startswith(("boto3.", "botocore."))]:
            monkeypatch.delitem(sys.modules, name)
        monkeypatch.setitem(sys.modules, "boto3", None)
        monkeypatch.setitem(sys.modules, "botocore", None)
        def forbidden(*a, **k): raise AssertionError("the IAM lane was used")
        out, err = StringIO(), StringIO()
        with patch("papyrus_content.cli_user_auth.session_for", return_value=self.session), \
             patch("papyrus_content.cli_user_auth.config_for_endpoint", return_value=self.config), \
             patch("papyrus_content.graphql_http.iam_signed_graphql_headers", forbidden), \
             patch("papyrus_content.graphql_http._aws_credentials", forbidden), \
             patch("http.client.HTTPSConnection", lambda *a, **k: FakeConnection(self.answer, self.requests)), \
             redirect_stdout(out), redirect_stderr(err):
            try:
                code = cli.main([*group, *argv])
            except SystemExit as stop:   # a command that exits with its status
                code = stop.code
        return code, out.getvalue(), err.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch): return Env(tmp_path, monkeypatch)


def test_overview_summary_uses_the_signed_in_token_and_no_aws(env, monkeypatch):
    code, out, err = env.run(["overview"], monkeypatch)
    assert code == 0 and err == ""
    method, body, headers = env.requests[0]
    assert body["variables"] == {"scope": "publication"} and "monitoringOverview" in body["query"]
    assert headers["Authorization"] and "x-amz" not in " ".join(k.lower() for k in headers)
    assert "feed-a" in out and "A synthetic item" in out and "more: cursor available" in out and "Decisions: 4 today" in out
    assert not any(name.startswith("boto") for name in sys.modules if sys.modules[name] is not None)


def test_overview_json_prints_the_raw_response(env, monkeypatch):
    code, out, _ = env.run(["overview", "--json", "--scope", "all"], monkeypatch)
    assert code == 0 and json.loads(out) == OVERVIEW
    assert env.requests[0][1]["variables"] == {"scope": "all"}


def test_page_sends_list_cursor_and_held_filter(env, monkeypatch):
    env.answer = graphql_answer("monitoringPage", PAGE)
    code, out, _ = env.run(["page", "--list", "emailSubmissions", "--cursor", "c-1", "--held", "--json"], monkeypatch)
    assert code == 0 and json.loads(out) == PAGE
    assert env.requests[0][1]["variables"] == {"list": "emailSubmissions", "cursor": "c-1", "filter": "held", "scope": "publication"}
    code, out, _ = env.run(["page", "--list", "items"], monkeypatch)
    assert code == 0 and "Older item" in out and "End of list." in out
    assert env.requests[1][1]["variables"] == {"list": "items", "cursor": None, "filter": None, "scope": "publication"}


def test_site_option_picks_the_signed_in_site_endpoint(env, monkeypatch):
    monkeypatch.delenv("PAPYRUS_GRAPHQL_ENDPOINT")
    with patch("papyrus_content.cli_user_auth.registered_site", return_value=env.config) as found:
        code, out, _ = env.run(["overview", "--site", "news.example.test"], monkeypatch)
    assert code == 0 and "feed-a" in out
    found.assert_called_once_with("news.example.test")


def test_site_option_for_a_site_not_signed_in_is_one_line(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, signed_in=False)
    monkeypatch.delenv("PAPYRUS_GRAPHQL_ENDPOINT")
    code, _, err = env.run(["overview", "--site", "other.example.test"], monkeypatch)
    assert code == 2 and len(err.strip().splitlines()) == 1 and "papyrus login other.example.test" in err


def test_held_only_applies_to_email_submissions(env, monkeypatch):
    code, _, err = env.run(["page", "--list", "items", "--held"], monkeypatch)
    assert code == 2 and "--held applies only" in err and env.requests == []


def test_signed_out_is_one_line_and_never_falls_back(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, signed_in=False)
    code, out, err = env.run(["overview"], monkeypatch)
    assert code != 0 and out == "" and env.requests == []
    assert len(err.strip().splitlines()) == 1 and "Traceback" not in err and "papyrus login" in err


@pytest.mark.parametrize("answer,scope,words", [
    (lambda r: FakeResponse(200, json.dumps({"data": {"monitoringOverview": json.dumps({"error": "forbidden"})}})), "all", "admins"),
    (lambda r: FakeResponse(200, json.dumps({"data": None, "errors": [{"message": "Not Authorized to access monitoringOverview", "errorType": "Unauthorized"}]})), "publication", "editors and admins"),
    (lambda r: FakeResponse(401, "denied"), "publication", "editors and admins"),
])
def test_non_staff_and_non_admin_are_refused_in_one_line(env, monkeypatch, answer, scope, words):
    env.answer = answer
    code, out, err = env.run(["overview", "--scope", scope], monkeypatch)
    assert code == 2 and out == "" and "Traceback" not in err
    assert len(err.strip().splitlines()) == 1 and words in err


def test_unavailable_and_server_failures_are_one_line(env, monkeypatch):
    env.answer = lambda r: FakeResponse(200, json.dumps({"data": {"monitoringOverview": json.dumps({"state": "unavailable"})}}))
    code, out, _ = env.run(["overview"], monkeypatch)
    assert code == 0 and "unavailable" in out
    env.answer = lambda r: FakeResponse(500, "boom")
    code, _, err = env.run(["overview"], monkeypatch)
    assert code == 2 and len(err.strip().splitlines()) == 1


def test_the_module_imports_no_aws_library():
    import papyrus_content.monitoring_view_cli as module
    lines = [line.strip() for line in open(module.__file__) if line.strip().startswith(("import ", "from "))]
    assert not [line for line in lines if "boto" in line]
