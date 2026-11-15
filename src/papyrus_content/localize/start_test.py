"""papyrus stories localize without an automation: the runner's own code runs the registered procedure here."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from papyrus_content.localize import start

ENDPOINT = "https://abc123.appsync-api.us-east-1.amazonaws.com/graphql"


def client(tenant="machines-on-machines"):
    return SimpleNamespace(endpoint=ENDPOINT, tenant_id=tenant)


def test_the_procedure_key_is_the_site_host_and_story_localize():
    assert start.default_procedure_key("news.example.com") == "news.example.com.story-localize"
    with pytest.raises(ValueError, match="Name the site"):
        start.default_procedure_key(None)


def test_the_model_key_comes_from_the_process_or_the_named_parameter(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    assert start.openai_key(None) == "from-env"
    monkeypatch.delenv("OPENAI_API_KEY")
    assert start.openai_key("/amplify/x/OPENAI_API_KEY", get_parameter=lambda name: "from-" + name.split("/")[-1]) == "from-OPENAI_API_KEY"
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        start.openai_key(None)


def test_the_child_signs_as_the_operator_for_this_site_and_keeps_the_callers_environment(monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "operator")
    environment = start.child_environment(client(), openai_api_key="k")
    assert environment["PAPYRUS_GRAPHQL_ENDPOINT"] == ENDPOINT and environment["PAPYRUS_GRAPHQL_AUTH"] == "iam"
    assert environment["PAPYRUS_TENANT_ID"] == "machines-on-machines" and environment["AWS_PROFILE"] == "operator" and environment["OPENAI_API_KEY"] == "k"


def test_a_run_started_here_needs_the_operator_lane(monkeypatch):
    monkeypatch.delenv("PAPYRUS_GRAPHQL_AUTH", raising=False)
    with pytest.raises(ValueError, match="--auth iam"):
        start.run_from_cli(client(), story="s", language="es-419", ceiling_usd=None, procedure_key="site.story-localize", key="k")


def test_the_registered_procedure_runs_through_the_runner_with_the_story_and_language(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    with mock.patch.object(start, "run_procedure_request", return_value={"runId": "r1", "runStatus": "completed", "costUsd": 0.01}) as run:
        result = start.run_from_cli(client(), story="s", language="es-419", ceiling_usd=2.0, procedure_key="site.story-localize", key="k")
    assert result["runId"] == "r1"
    request = run.call_args.args[0]
    assert request["procedureKey"] == "site.story-localize" and request["appsyncEndpoint"] == ENDPOINT
    assert request["input"] == {"story": "s", "language": "es-419", "ceilingUsd": 2.0, "procedureKey": "site.story-localize"}
    assert "timeoutSeconds" not in request and run.call_args.kwargs["environment"]["OPENAI_API_KEY"] == "k"


def test_an_unregistered_procedure_says_how_to_register_it(monkeypatch):
    from papyrus_content.procedure_runner import ProcedureNotRunnable

    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    with mock.patch.object(start, "run_procedure_request", side_effect=ProcedureNotRunnable("ProcedureDefinition not found.")):
        with pytest.raises(ValueError, match="procedures register --file procedures/newsroom/story_localize.tac --key site.story-localize"):
            start.run_from_cli(client(), story="s", language="es-419", ceiling_usd=None, procedure_key="site.story-localize", key="k")
