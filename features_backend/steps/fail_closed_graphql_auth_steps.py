from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

from papyrus_content import graphql_http
from papyrus_content import operator_errors
from papyrus_content.operator_errors import OperatorError

ENDPOINT = "https://example.appsync-api.us-east-1.amazonaws.com/graphql"
REPO = Path(__file__).resolve().parents[2]

WORKERS = {
    "the knowledge run image": ("infra/knowledge-run/Dockerfile", "PAPYRUS_GRAPHQL_AUTH=iam"),
    "the procedure runner image": ("infra/procedures/Dockerfile", "PAPYRUS_GRAPHQL_AUTH=iam"),
    "the monitoring router function": ("infra/monitoring/papyrus-monitoring.yaml", "PAPYRUS_GRAPHQL_AUTH: iam"),
    "the scheduled knowledge run tasks": ("infra/scheduled-jobs/lib/knowledge-pipeline.ts", 'PAPYRUS_GRAPHQL_AUTH: "iam"'),
    "the newsletter functions": ("amplify/plugins/newsletter/papyrus.plugin.ts", 'PAPYRUS_GRAPHQL_AUTH: "iam"'),
    "the content actions function": ("amplify/site-backend.ts", "contentActionsLambda.addEnvironment(WORKER_GRAPHQL_AUTH_ENV, WORKER_GRAPHQL_AUTH)"),
    "the Slack delivery function": ("amplify/site-backend.ts", "backend.slackDelivery.addEnvironment(WORKER_GRAPHQL_AUTH_ENV, WORKER_GRAPHQL_AUTH)"),
    "the inbound email processor": ("amplify/site-backend.ts", "inboundProcessor.addEnvironment(WORKER_GRAPHQL_AUTH_ENV, WORKER_GRAPHQL_AUTH)"),
    "the automation view function": ("amplify/functions/automation-view/wire.ts", "WORKER_GRAPHQL_AUTH_ENV, WORKER_GRAPHQL_AUTH"),
    "the editorial checks function": ("amplify/functions/editorial-checks/wire.ts", "WORKER_GRAPHQL_AUTH_ENV, WORKER_GRAPHQL_AUTH"),
}


def _start_patch(context, patcher):
    started = patcher.start()
    context.add_cleanup(patcher.stop)
    return started


@given("a machine with AWS credentials in its environment and no Papyrus sign-in")
def machine_with_credentials(context):
    _start_patch(context, patch.dict("os.environ", {"AWS_ACCESS_KEY_ID": "AKIDEXAMPLE", "AWS_SECRET_ACCESS_KEY": "secret-example"}))
    graphql_http._credential_session = None
    context.add_cleanup(setattr, graphql_http, "_credential_session", None)
    real = graphql_http.iam_signed_graphql_headers
    context.signed = []
    context.local_engine_runs = []

    def recording(endpoint, body, session=None):
        context.signed.append(endpoint)
        return real(endpoint, body, session)

    _start_patch(context, patch.object(graphql_http, "iam_signed_graphql_headers", recording))


@given("the operator names the IAM lane with PAPYRUS_GRAPHQL_AUTH=iam")
def name_iam_lane(context):
    _start_patch(context, patch.dict("os.environ", {"PAPYRUS_GRAPHQL_AUTH": "iam"}))


@given("a sign-in session exists but yields no headers")
def session_without_headers(context):
    from papyrus_content import cli_user_auth

    state = tempfile.mkdtemp(prefix="papyrus-fail-closed-")
    (Path(state) / "user-session.json").write_text("{}")
    _start_patch(context, patch.dict("os.environ", {"PAPYRUS_CLI_STATE_DIR": state}))
    _start_patch(context, patch.object(cli_user_auth, "selected_headers", lambda endpoint: None))


def _capture(context, action):
    context.refusal = None
    context.result = None
    try:
        context.result = action()
    except OperatorError as error:
        context.refusal = error


@when("a command asks for headers to call the site API")
def ask_for_headers(context):
    _capture(context, lambda: graphql_http.graphql_request_headers(endpoint=ENDPOINT, body=b"{}"))


@when('the operator runs a knowledge query with execution "{execution}"')
def run_knowledge_query(context, execution):
    from papyrus_knowledge_query import cli

    def run():
        args = argparse.Namespace(execution=execution, site="", input="")
        with patch.object(cli, "_input_from_args", return_value={}), patch.object(cli, "build_environment_services", return_value=object()), patch.object(
            cli, "run_knowledge_query", side_effect=lambda payload, services: context.local_engine_runs.append(payload) or {}
        ):
            return cli.run_knowledge_query_cli(args)

    _capture(context, run)


@when("the operator CLI checks its cloud authoring access")
def check_cloud_access(context):
    from papyrus.operator.backends.cloud import CloudBackend

    backend = CloudBackend.__new__(CloudBackend)
    backend._config = type("Config", (), {"fixture_root": None})()
    _capture(context, backend._ensure_auth)


@then('it refuses with one line that says to run "papyrus login"')
def refuses_with_login(context):
    assert context.refusal is not None, "the command did not refuse"
    message = str(context.refusal)
    assert "papyrus login" in message and "\n" not in message.strip(), message


@then("the command would exit with status 2")
def exits_two(context):
    assert operator_errors.exit_code_for_error(context.refusal) == 2


@then("no request was signed with AWS credentials")
def nothing_signed(context):
    assert context.signed == []


@then("the request is signed with the AWS credentials")
def signed(context):
    assert context.refusal is None and context.result["Authorization"].startswith("AWS4-HMAC-SHA256 ")
    assert context.signed == [ENDPOINT]


@then("the local engine did not run")
def local_engine_idle(context):
    assert context.local_engine_runs == []


@then("the local engine ran once")
def local_engine_ran(context):
    assert context.refusal is None and len(context.local_engine_runs) == 1


@then("the message does not mention AWS_PROFILE")
def no_profile_hint(context):
    assert "AWS_PROFILE" not in str(context.refusal)


@then("{worker} names PAPYRUS_GRAPHQL_AUTH iam in its image or stack definition")
def worker_names_lane(context, worker):
    path, needle = WORKERS[worker]
    assert needle in (REPO / path).read_text(), f"{worker}: {path} lacks {needle}"
