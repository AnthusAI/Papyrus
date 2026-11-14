from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from behave import given, then, when

from papyrus_content.relevance_audit import references_audit


class FakeClient:
    def __init__(self, rows):
        self.rows, self.writes = rows, 0

    def list_records(self, model):
        assert model == "Reference"
        return self.rows

    def update_record(self, *_args, **_kwargs):
        self.writes += 1

    create_record = delete_record = update_record


def _row(n, probability, status, **extra):
    return {"id": f"r{n}", "title": f"Reference {n}", "predictedAcceptProbability": probability, "curationStatus": status, "versionState": "current", **extra}


@given("a site whose References were scored and then reviewed by editors")
def step_site(context):
    context.client = FakeClient([
        _row(1, 0.95, "accepted"), _row(2, 0.75, "accepted"), _row(3, 0.72, "pending"), _row(4, 0.64, "pending"),
        _row(5, 0.78, "rejected", curationStatusReason="Off topic"), _row(6, 0.62, "rejected", curationReasonCode="duplicate"),
    ])


@when('an operator audits the relevance model')
def step_run(context):
    out = io.StringIO()
    with redirect_stdout(out):
        references_audit([], client=context.client)
    context.output = out.getvalue()


@when('an operator audits the relevance model with --json')
def step_run_json(context):
    out = io.StringIO()
    with redirect_stdout(out):
        references_audit(["--json"], client=context.client)
    context.report = json.loads(out.getvalue())


@then("the audit counts the references, the scored ones, and the accepted, rejected and untouched ones")
def step_counts(context):
    assert "references\t6\twith prediction\t6" in context.output and "accepted\t2\trejected\t2\tuntouched\t2" in context.output, context.output


@then("the audit gives the median score of accepted and of untouched references")
def step_medians(context):
    assert "accepted 0.85" in context.output and "untouched 0.68" in context.output, context.output


@then("the audit gives how often an accepted reference outscored an untouched one")
def step_auroc(context):
    assert "AUROC accepted vs untouched\t1.00" in context.output, context.output


@then("the first band starts at the lowest tenth that has a scored reference")
def step_first_band(context):
    assert "\n0.6-0.7\t" in context.output and "\n0.5-0.6\t" not in context.output, context.output


@then("each band shows how many were delivered, accepted and rejected")
def step_band_columns(context):
    assert "band\tdelivered\taccepted\trejected\taccept share" in context.output and "\n0.7-0.8\t3\t1\t1\t33%" in context.output, context.output


@then("each rejected reference is listed with its predicted probability and the editor's reason")
def step_rejects(context):
    assert [(r["predictedAcceptProbability"], r["reason"]) for r in context.report["rejects"]] == [(0.78, "Off topic"), (0.62, "duplicate")]


@then("the audit changed no reference")
def step_no_writes(context):
    assert context.client.writes == 0
