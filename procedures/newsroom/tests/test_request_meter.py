"""Every AppSync request is counted by caller; a process over its budget warns and goes on
(features_backend/request-meter.feature)."""
from __future__ import annotations

import json

import pytest

from papyrus_content import request_meter
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient

from fake_appsync import FakeAppSync

ENDPOINT = "https://example.appsync-api.us-east-1.amazonaws.com/graphql"


def make_client(backend: FakeAppSync) -> PapyrusGraphQLAuthoringClient:
    client = PapyrusGraphQLAuthoringClient(endpoint=ENDPOINT, header_factory=lambda body: {}, site_tenant=False)
    client._open_connection = lambda: backend  # type: ignore[method-assign]
    return client


@pytest.fixture(autouse=True)
def fresh_meter(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")   # a signed-in CLI session on the developer machine would turn retries off
    monkeypatch.delenv(request_meter.ENV_MODE, raising=False)
    monkeypatch.delenv(request_meter.ENV_BUDGET, raising=False)
    request_meter.reset_for_tests()
    yield
    request_meter.reset_for_tests()


def reads(client: PapyrusGraphQLAuthoringClient, count: int) -> None:
    for n in range(count):
        client.get_record("Reference", f"ref-{n}")


def test_requests_are_counted_by_caller_model_and_operation(capsys):
    client = make_client(FakeAppSync(gets={"getReference": {"ref-0": {"id": "ref-0"}}}))
    with request_meter.run("cli:references show", units=1, emit="stderr") as run:
        reads(client, 3)
    assert run.requests == 3
    assert dict(run.by_key) == {("", "Reference", "GetReference"): 3}
    line = capsys.readouterr().err.strip().splitlines()[-1]
    assert line.startswith("papyrus requests: cli:references show total=3 budget=3/") and "Reference.GetReference x3" in line


def test_a_lambda_run_logs_a_structured_summary(capsys):
    client = make_client(FakeAppSync())
    with request_meter.run("lambda:router:auto-accept", emit="log"):
        reads(client, 2)
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["event"] == request_meter.SUMMARY_EVENT and summary["caller"] == "lambda:router:auto-accept"
    assert summary["requests"] == 2 and summary["top"] == {"Reference.GetReference": 2}


def test_the_budget_scales_with_the_input():
    one = request_meter.Run("cli:references show", units=1, emit="stderr")
    ten = request_meter.Run("cli:references show", units=10, emit="stderr")
    base, per_unit = request_meter.budget_parameters("cli:references show")
    assert one.budget() == base + per_unit and ten.budget() == base + 10 * per_unit
    assert request_meter.budget_parameters("lambda:router:auto-accept") != request_meter.budget_parameters("lambda:router:monitor-stories")


def test_over_budget_warns_once_and_the_work_continues(capsys, monkeypatch):
    client = make_client(FakeAppSync())
    with request_meter.run("cli:references show", units=0, emit="stderr", budget=5) as run:
        reads(client, 12)   # no exception
    assert run.requests == 12
    warnings = [line for line in capsys.readouterr().err.splitlines() if "WARNING papyrus request meter" in line]
    assert len(warnings) == 1
    assert "cli:references show" in warnings[0] and "12" not in warnings[0].split("budget of")[0] and "budget of 5" in warnings[0] and "overridden" in warnings[0]


def test_stop_mode_is_off_by_default_and_raises_only_when_switched_on(monkeypatch):
    client = make_client(FakeAppSync())
    with request_meter.run("cli:a", emit="stderr", budget=2):
        reads(client, 4)
    request_meter.reset_for_tests()
    monkeypatch.setenv(request_meter.ENV_MODE, "stop")
    with pytest.raises(request_meter.RequestBudgetExceeded):
        with request_meter.run("cli:b", emit="stderr", budget=2):
            reads(client, 4)


def test_a_named_sweep_is_counted_but_exempt(capsys):
    client = make_client(FakeAppSync())
    with request_meter.run("cli:references show", emit="stderr", budget=2) as run:
        with request_meter.sweep("test-sweep"):
            reads(client, 10)
    assert run.requests == 10 and run.budgeted == 0 and not run.warned
    assert "WARNING" not in capsys.readouterr().err


def test_commands_that_sweep_on_purpose_declare_themselves():
    assert request_meter.is_sweep_command("references", "backfill-feed-keys")
    assert request_meter.is_sweep_command("knowledge", "anything")
    assert not request_meter.is_sweep_command("references", "show")


def test_the_budget_flag_is_removed_and_logged(capsys):
    assert request_meter.split_budget_flag(["--budget", "40", "ref-1"]) == (["ref-1"], 40)
    assert request_meter.split_budget_flag(["--budget=7", "--site", "x"]) == (["--site", "x"], 7)
    assert request_meter.split_budget_flag(["ref-1"]) == (["ref-1"], None)
    with request_meter.run("cli:references show", emit="stderr", budget=40):
        pass
    assert "budget of 40 (override; the default would be" in capsys.readouterr().err


def test_an_unbounded_list_outside_a_sweep_is_logged_and_counted(capsys):
    client = make_client(FakeAppSync(indexes={"listReferences": {}}))
    with request_meter.run("lambda:router:route", emit="log") as run:
        client.list_records("Reference")
        client.list_records("Reference")
        with request_meter.sweep("all-references"):
            client.list_records("Reference")
    assert run.unbounded == {"Reference": 2}
    logged = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert [entry["event"] for entry in logged].count("papyrus_unbounded_list") == 1   # once per model per run
    assert logged[-1]["unboundedLists"] == {"Reference": 2}


def test_a_retry_is_counted_as_the_second_request_it_is():
    class FailsOnce(FakeAppSync):
        failed = False
        def getresponse(self):
            if not self.failed:
                self.failed = True
                raise OSError("reset")
            return super().getresponse()
    client = make_client(FailsOnce(gets={"getReference": {"r": {"id": "r"}}}))
    with request_meter.run("cli:x", emit="stderr") as run:
        client.get_record("Reference", "r")
    assert run.requests == 2


def test_a_wrapped_handler_runs_once_per_invocation(capsys):
    @request_meter.metered_handler("router")
    def handler(event, context):
        make_client(FakeAppSync()).get_record("Reference", "x")
        return "ok"
    assert handler({"task": "auto-accept"}, None) == "ok"
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["caller"] == "lambda:router:auto-accept"
