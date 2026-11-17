"""Run outcomes from the real paths (features_backend/run-outcome-paths.feature). The shared backend, policy and wake steps are in runner_reads_policy_steps.py."""
from __future__ import annotations

import json
from pathlib import Path

from behave import given, then, when

from papyrus_content import procedure_runner as pr, procedure_runner_child, reference_curation
from papyrus_content.agent_policy import PersonStart

REPO = Path(__file__).resolve().parents[2]
CURATION = REPO / "procedures" / "newsroom" / "reference_curation.tac"
TENANT, BUCKET = "alpha", "site-bucket"


def _base(context, trigger):
    import test_procedure_runner as tpr
    request = {**tpr.REQUEST, "procedureKey": context.procedure_key, "wakeKey": f"{context.automation_id}|manual|{len(context.client.records)}",
               "tenantId": TENANT, "siteBucket": BUCKET, "trigger": trigger}
    if getattr(context, "reference_input", None):
        request["input"] = context.reference_input
    return request


def _run(context, policy=None, trigger=None):
    request = _base(context, trigger or {"kind": "manual", "automationId": context.automation_id})
    context.executed = []

    def execute(workdir, source_path, inputs, *, timeout_seconds, environment):
        context.executed.append(request["wakeKey"])
        if context.child_output is not None:
            return {"success": True, "output": context.child_output, "seconds": 1}
        return {**procedure_runner_child.run(source_path, inputs), "seconds": 1}

    policy = policy or pr.policy_for(request, context.client, lambda: context.s3)
    context.result = pr.run_procedure_request(request, policy=policy, client=context.client, execute=execute, seconds_available=900, environment={})


def _curation(context, outcome):
    context.child_output = None
    context.reference_input = {"reference_id": "reference-1", "force": False}
    original = reference_curation.curate_reference_by_id
    reference_curation.curate_reference_by_id = lambda reference_id, **_: {"referenceId": reference_id, "outcome": outcome, "status": "ready"}
    context.add_cleanup(setattr, reference_curation, "curate_reference_by_id", original)


@given("the procedure is the shipped Reference curation procedure")
def shipped(context):
    context.client.attachments[-1]["body"] = CURATION.read_bytes()


@given("the Reference is already curated")
def already(context):
    _curation(context, "already_curated")


@given("the Reference needs curating")
def needs(context):
    _curation(context, "curated")


@given('the procedure asks the gate for "{operation}"')
def asks(context, operation):
    context.child_output = {"title": "x", "gate_operations": [operation]}


@given('the procedure asks the gate for "{operation}" and says it did its work')
def asks_and_claims(context, operation):
    context.child_output = {"title": "x", "gate_operations": [operation], "run_outcome": "acted"}


@when("the runner takes a wake for the automation")
def wake_for_automation(context):
    _run(context)


@when("a person starts that procedure from their own session")
def person_start(context):
    _run(context, policy=PersonStart(), trigger={"kind": "cli"})


def _stored(context):
    (stored,) = context.client.records.values()
    return stored


@then('one review request is filed on the run, raised by "{raiser}", that a person must answer')
def one_request(context, raiser):
    (request,) = context.client.reviews.values()
    assert json.loads(request["subject"]) == {"type": "automation_run", "id": _stored(context)["id"]}, request
    assert (request["raisedBy"], request["mode"], request["state"]) == (raiser, "hard_gate", "open"), request


@then("no review request is filed")
def none_filed(context):
    assert context.client.reviews == {}


@then('the run record stores the gate\'s answer "{answer}" for "{operation}" under policy version {version:d}')
def stores_answer(context, answer, operation, version):
    gate = json.loads(_stored(context)["output"])["gate"] if isinstance(_stored(context)["output"], str) else _stored(context)["output"]["gate"]
    assert gate["policyVersion"] == version, gate
    assert [(entry["operation"], entry["answer"]) for entry in gate["gate"]] == [(operation, answer)], gate


@then('the run record is completed with the outcome "{outcome}" and the reason "{reason}"')
def completed_with(context, outcome, reason):
    stored = _stored(context)
    assert (stored["runStatus"], stored["outcome"], stored["outcomeReason"]) == ("completed", outcome, reason), stored
    assert context.executed, "the procedure itself ran, so the word is its own"
