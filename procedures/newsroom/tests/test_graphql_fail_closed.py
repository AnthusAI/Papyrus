"""PPY-5f119a: the shared GraphQL client never picks AWS credentials by itself. Synthetic endpoints and credentials only."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from papyrus_content import graphql_http, operator_errors
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
from papyrus_content.operator_errors import OperatorError
from papyrus_content.user_auth_mode import LOGIN_REQUIRED_MESSAGE, iam_requested, user_auth_requested

ENDPOINT = "https://example.appsync-api.us-east-1.amazonaws.com/graphql"
CREDENTIALS = {"AWS_ACCESS_KEY_ID": "AKIDEXAMPLE", "AWS_SECRET_ACCESS_KEY": "secret-example"}
REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _fresh_credentials(monkeypatch):
    monkeypatch.setattr(graphql_http, "_credential_session", None)
    for name, value in CREDENTIALS.items():   # credentials are present throughout: the point is that they are not used unasked
        monkeypatch.setenv(name, value)


def test_no_session_and_no_opt_in_refuses_and_names_login():
    assert not iam_requested() and not user_auth_requested()
    with patch.object(graphql_http, "iam_signed_graphql_headers", side_effect=AssertionError("IAM fallback")):
        with pytest.raises(OperatorError) as refusal:
            graphql_http.graphql_request_headers(endpoint=ENDPOINT, body=b"{}")
    assert "papyrus login" in str(refusal.value) and "\n" not in str(refusal.value)
    assert refusal.value.exit_code == 2


def test_authoring_client_refuses_the_same_way():
    with pytest.raises(OperatorError, match="papyrus login"):
        PapyrusGraphQLAuthoringClient(endpoint=ENDPOINT)._request_headers(b"{}")


def test_the_refusal_exits_two_without_a_traceback(capsys):
    def run():
        graphql_http.graphql_request_headers(endpoint=ENDPOINT, body=b"{}")
        return 0

    assert operator_errors.run_with_operator_error_handling(run) == 2
    error = capsys.readouterr().err
    assert error.strip() == LOGIN_REQUIRED_MESSAGE and "Traceback" not in error


def test_explicit_iam_opt_in_signs(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    headers = graphql_http.graphql_request_headers(endpoint=ENDPOINT, body=b"{}")
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")


def test_credentials_alone_do_not_count_as_an_authoring_lane():
    assert not graphql_http.authoring_credentials_available()
    with patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": "iam"}):
        assert graphql_http.authoring_credentials_available()


def test_a_session_that_yields_no_headers_refuses_instead_of_signing(monkeypatch, tmp_path):
    (tmp_path / "user-session.json").write_text("{}")
    monkeypatch.setenv("PAPYRUS_CLI_STATE_DIR", str(tmp_path))
    assert user_auth_requested()
    from papyrus_content import cli_user_auth

    monkeypatch.setattr(cli_user_auth, "selected_headers", lambda endpoint: None)
    with patch.object(graphql_http, "iam_signed_graphql_headers", side_effect=AssertionError("IAM fallback")):
        with pytest.raises(OperatorError, match="papyrus login"):
            graphql_http.graphql_request_headers(endpoint=ENDPOINT, body=b"{}")


def test_recovery_guidance_points_at_login_unless_iam_was_chosen(monkeypatch):
    assert "aws sso login" not in operator_errors.credential_recovery_guidance()
    assert "papyrus login" in operator_errors.credential_recovery_guidance()
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    assert "PAPYRUS_GRAPHQL_AUTH=iam" in operator_errors.credential_recovery_guidance()


def test_cloud_backend_refuses_with_the_login_hint():
    from papyrus.operator.backends.cloud import CloudBackend

    backend = CloudBackend.__new__(CloudBackend)
    backend._config = type("Config", (), {"fixture_root": None})()
    with pytest.raises(OperatorError, match="papyrus login") as refusal:
        backend._ensure_auth()
    assert "AWS_PROFILE" not in str(refusal.value) and refusal.value.exit_code == 2


# knowledge query --execution

def _query_args(execution: str) -> argparse.Namespace:
    return argparse.Namespace(execution=execution, site="")


def test_knowledge_query_auto_refuses_when_signed_out():
    from papyrus_knowledge_query import cli

    with patch.dict(os.environ, {"PAPYRUS_GRAPHQL_ENDPOINT": ENDPOINT}):
        for execution in ("auto", "remote"):
            with pytest.raises(OperatorError, match="papyrus login"):
                cli._should_run_remote(_query_args(execution))


def test_knowledge_query_local_runs_only_when_asked_for():
    from papyrus_knowledge_query import cli

    assert cli._should_run_remote(_query_args("local")) is False
    ran = []
    args = argparse.Namespace(execution="local", site="", input="")
    with patch.object(cli, "_input_from_args", return_value={}), patch.object(cli, "build_environment_services", return_value=object()), patch.object(
        cli, "run_knowledge_query", side_effect=lambda payload, services: ran.append(payload) or {}
    ):
        cli.run_knowledge_query_cli(args)
    assert ran == [{}]


def test_knowledge_query_auto_refuses_when_signed_in_but_no_site_resolves(monkeypatch, tmp_path):
    from papyrus_content import signed_in_lane
    from papyrus_knowledge_query import cli

    (tmp_path / "user-session.json").write_text("{}")
    monkeypatch.setenv("PAPYRUS_CLI_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(signed_in_lane, "endpoint", lambda site: (_ for _ in ()).throw(ValueError("two sites")))
    with pytest.raises(OperatorError, match="papyrus login") as refusal:
        cli._should_run_remote(_query_args("auto"))
    assert "--execution local" in str(refusal.value)


def test_knowledge_query_iam_opt_in_keeps_the_remote_lane(monkeypatch):
    from papyrus_knowledge_query import cli

    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    monkeypatch.setenv("PAPYRUS_GRAPHQL_ENDPOINT", ENDPOINT)
    assert cli._should_run_remote(_query_args("remote")) is True
    assert cli._should_run_remote(_query_args("auto")) is True


# every worker that signs as itself names the lane

WORKER_DECLARATIONS = {
    "infra/knowledge-run/Dockerfile": r"PAPYRUS_GRAPHQL_AUTH=iam",
    "infra/procedures/Dockerfile": r"PAPYRUS_GRAPHQL_AUTH=iam",
    "infra/monitoring/papyrus-monitoring.yaml": r"PAPYRUS_GRAPHQL_AUTH: iam",
    "infra/scheduled-jobs/lib/knowledge-pipeline.ts": r'PAPYRUS_GRAPHQL_AUTH: "iam"',
    "amplify/plugins/newsletter/papyrus.plugin.ts": r'PAPYRUS_GRAPHQL_AUTH: "iam"',
    "amplify/functions/shared/worker-graphql-auth.ts": r'WORKER_GRAPHQL_AUTH = "iam"',
}


@pytest.mark.parametrize("path,pattern", sorted(WORKER_DECLARATIONS.items()))
def test_worker_images_and_stacks_declare_the_iam_lane(path, pattern):
    assert re.search(pattern, (REPO / path).read_text()), f"{path} must name the IAM lane"


def test_python_lambdas_that_call_the_site_api_declare_the_lane():
    backend = (REPO / "amplify/site-backend.ts").read_text()
    for function in ("contentActionsLambda", "backend.slackDelivery", "inboundProcessor"):
        assert f"{function}.addEnvironment(WORKER_GRAPHQL_AUTH_ENV, WORKER_GRAPHQL_AUTH)" in backend
    for wire in ("amplify/functions/automation-view/wire.ts", "amplify/functions/editorial-checks/wire.ts"):
        assert "lambda.addEnvironment(WORKER_GRAPHQL_AUTH_ENV, WORKER_GRAPHQL_AUTH)" in (REPO / wire).read_text()
