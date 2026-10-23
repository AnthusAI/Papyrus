"""A TTAB monitor's table rows and a site backend's records, shaped like the live ones, for the Automation read path.

Used by test_automations.py and features_backend/automation-records.feature. The trigger rows carry the runner
`request` on purpose (it holds an AppSync endpoint and an SSM parameter name): the history must never return it.
"""
import json
from copy import deepcopy

from fake_client import FakeAuthoringClient

SITE_ENDPOINT = "https://dist0.appsync-api.us-east-1.amazonaws.com/graphql"
OTHER_ENDPOINT = "https://other.appsync-api.us-east-1.amazonaws.com/graphql"
PROCEDURE = "distinctive.ttab.ruling-analysis"
TEMPLATE = {"proceeding": "{sourceIdPrefix}", "opinion_url": "{documentUrl}"}
PK = "MONITOR#ttab"
SECRET_MARKERS = ("appsync-api", "/amplify/shared", "openaiKeyParameter")


def trigger_row(source_id, status, *, run_id=None, started="2026-10-23T08:00:00Z", finished=None, run_error=None, error=None,
                publication="distinctive", procedure=PROCEDURE):
    row = {"pk": PK, "sk": f"TRIGGER#{publication}#{procedure}#{source_id}", "publicationId": publication, "procedureKey": procedure,
           "sourceId": source_id, "referenceId": f"ref-{source_id}", "routerRunId": "rr1", "createdAt": started, "status": status,
           "request": {"appsyncEndpoint": SITE_ENDPOINT, "openaiKeyParameter": "/amplify/shared/app/OPENAI_API_KEY"}}
    if status != "notTriggered":
        row["startedAt"] = started
    else:
        row["reason"] = "the Reference already existed"
    for key, value in (("runId", run_id), ("finishedAt", finished), ("runError", run_error), ("error", error)):
        if value:
            row[key] = value
    return row


def router_config(*, input_template=None, procedure=PROCEDURE, endpoint=SITE_ENDPOINT, publication="distinctive", with_trigger=True):
    trigger = [{"procedureKey": procedure, "input": TEMPLATE if input_template is None else input_template}] if with_trigger else []
    return {"pk": PK, "sk": "CONFIG#router", "mode": "live", "enabled": True,
            "publications": [{"publicationId": publication, "site": "distinctive.example", "appsyncEndpoint": endpoint,
                              "openaiKeyParameter": "/amplify/shared/app/OPENAI_API_KEY", "procedureTriggers": trigger}]}


def rows():
    return deepcopy([
        router_config(),
        trigger_row("97752244-EXA_26", "completed", run_id="run-1", started="2026-10-23T08:00:00Z", finished="2026-10-23T08:03:10Z"),
        trigger_row("97752245-EXA_26", "failed", run_id="run-2", started="2026-10-23T14:00:00Z", finished="2026-10-23T14:01:00Z",
                    run_error="the opinion could not be downloaded"),
        trigger_row("97752246-EXA_26", "started", started="2026-10-23T20:00:00Z"),
        trigger_row("97752247-EXA_26", "startFailed", started="2026-10-23T17:00:00Z", error="ClientError: throttled"),
        trigger_row("97752248-EXA_26", "completed", run_id="run-gone", started="2026-10-22T08:00:00Z", finished="2026-10-22T08:04:00Z"),
        trigger_row("97752200-EXA_26", "notTriggered", started="2026-10-21T08:00:00Z"),
        trigger_row("97752201-EXA_26", "notTriggered", started="2026-10-21T09:00:00Z"),
        # Another publication's trigger for the same procedure key must never appear.
        trigger_row("99999999-OTH_26", "completed", run_id="run-other", publication="other", started="2026-10-23T21:00:00Z"),
    ])


class FakeMonitoringTable:
    """GetItem and Query on a dict table. It has no write method, so a write cannot happen."""

    def __init__(self, table_rows=None, page_size=3):
        self.rows = {(r["pk"], r["sk"]): r for r in (rows() if table_rows is None else table_rows)}
        self.page_size, self.queries = page_size, 0

    def get_item(self, Key):
        row = self.rows.get((Key["pk"], Key["sk"]))
        return {"Item": deepcopy(row)} if row else {}

    def query(self, KeyConditionExpression, ExpressionAttributeValues, ExclusiveStartKey=None, **_):
        self.queries += 1
        pk, prefix = ExpressionAttributeValues[":pk"], ExpressionAttributeValues[":prefix"]
        found = sorted(((k, r) for k, r in self.rows.items() if k[0] == pk and k[1].startswith(prefix)), key=lambda pair: pair[0][1])
        start = 0
        if ExclusiveStartKey:
            start = next(i for i, (k, _) in enumerate(found) if k[1] == ExclusiveStartKey["sk"]) + 1
        page = found[start:start + self.page_size]
        result = {"Items": [deepcopy(r) for _, r in page]}
        if start + self.page_size < len(found):
            result["LastEvaluatedKey"] = {"pk": pk, "sk": page[-1][0][1]}
        return result


def procedure_run(run_id, status, *, started, finished, output=None, error_summary=None, error=None, cost=None, usage=None,
                  requested_by=None):
    row = {"id": run_id, "procedureId": "procedure-x", "procedureKey": PROCEDURE, "procedureVersionId": "v1", "runStatus": status,
           "requestedAt": started, "startedAt": started, "finishedAt": finished, "requestedBy": requested_by,
           "output": json.dumps(output) if output is not None else None, "errorSummary": error_summary,
           "error": json.dumps(error) if error is not None else None}
    if cost is not None or usage is not None:
        row.update(costUsd=cost, usage=json.dumps(usage) if usage is not None else None)
    return row


def usage_summary(**changes):
    return {"calls": 3, "promptTokens": 50000, "completionTokens": 4000, "models": {"gpt-6-luna": 3}, "complete": True,
            "unpricedModels": [], **changes}


def manual_row(automation_id="distinctive.ttab", stamp="2026-10-24T09:00:00Z", status="started", *, run_id=None, by="ryan@example.test", **extra):
    row = {"pk": PK, "sk": f"MANUAL#{automation_id}#{stamp}", "publicationId": "distinctive", "procedureKey": PROCEDURE,
           "automationId": automation_id, "requestedBy": by, "createdAt": stamp, "startedAt": stamp, "status": status,
           "request": {"appsyncEndpoint": SITE_ENDPOINT, "openaiKeyParameter": "/amplify/shared/app/OPENAI_API_KEY"}}
    if run_id:
        row["runId"] = run_id
    row.update(extra)
    return row


def automation_row(**changes):
    row = {"id": "distinctive.ttab", "title": "Analyze new TTAB rulings", "description": "A story for each new Board decision.",
           "enabled": True, "trigger": json.dumps({"kind": "monitor", "config": {"monitorId": "ttab", "publicationId": "distinctive"}}),
           "procedureKey": PROCEDURE, "inputTemplate": json.dumps(TEMPLATE),
           "limits": json.dumps({"timeoutSeconds": 840, "maxConcurrent": 1}), "createdBy": "tester", "createdAt": "2026-10-23T07:00:00Z",
           "updatedBy": "tester", "updatedAt": "2026-10-23T07:00:00Z"}
    row.update(changes)
    return row


def site_client(*automations):
    client = FakeAuthoringClient({
        "Automation": list(automations) if automations else [automation_row()],
        "ProcedureRun": [
            procedure_run("run-1", "completed", started="2026-10-23T08:00:05Z", finished="2026-10-23T08:03:10Z",
                          output={"story": "story-lineage-1", "version_id": "story-v2", "title": "Board refuses registration"}),
            procedure_run("run-2", "failed", started="2026-10-23T14:00:05Z", finished="2026-10-23T14:01:00Z",
                          error_summary="the opinion could not be downloaded", error={"message": "the opinion could not be downloaded"}),
            # No trigger row links this one: someone ran the procedure by hand, outside the automation.
            procedure_run("run-outside", "completed", started="2026-10-22T10:00:00Z", finished="2026-10-22T10:02:00Z",
                          requested_by="papyrus-cli"),
        ],
    })
    return client
