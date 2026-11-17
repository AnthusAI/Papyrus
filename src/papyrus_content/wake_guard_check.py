"""`papyrus procedures check-wake-guard`: proves, on a real site, that the once-only create refuses a second record for one wake key.

The newsroom function makes a run's record with an id derived from the wake key and a condition that the id is not taken
(`amplify/functions/procedure-action/handler.ts`). The check asks that function to start the same wake key twice, as a signed-in
person, and requires the second answer to say `duplicate: true` with the first answer's run id. The record it makes belongs to a
wake key no automation or router ever builds (`<owner>|manual|wake-guard-check-...`), no procedure is loaded or run, and the record
is finished as `nothing` with the reason `wake_guard_check`, so it does not stay `started`. A record made by the check stays in the
site as the evidence; it is not deleted.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import wake_keys
from .cloud_procedures import START_PROCEDURE_RUN_MUTATION, normalize_graphql_json_value, update_cloud_procedure_run_record

REASON = "wake_guard_check"
REQUEST_PREFIX = "wake-guard-check-"


class WakeGuardCheckFailed(RuntimeError):
    """The second start of one wake key was not answered as a duplicate of the first."""


def _start(client: Any, procedure_key: str, wake_key: str) -> dict[str, Any]:
    data = client.graphql(START_PROCEDURE_RUN_MUTATION, {
        "procedureKey": procedure_key, "wakeKey": wake_key, "actorLabel": "Wake guard check",
        "input": json.dumps({"__papyrusExecutionMode": "external_cli"}),
    })
    return normalize_graphql_json_value(data.get("startNewsroomProcedureRun")) or {}


GET_PROCEDURE_RUN_QUERY = """
  query GetProcedureRun($id: ID!) {
    getNewsroomProcedureRun(id: $id)
  }
"""


def new_request_id(now: datetime | None = None) -> str:
    return REQUEST_PREFIX + (now or datetime.now(timezone.utc)).strftime("%Y%m%dt%H%M%Sz")


def check_wake_guard(client: Any, *, procedure_key: str, request_id: str, apply: bool) -> dict[str, Any]:
    """Starts one wake key twice. Raises WakeGuardCheckFailed unless the answers are 'created' then 'duplicate of the same run'."""
    if not request_id.startswith(REQUEST_PREFIX):
        raise ValueError(f"A wake guard check's request id must start with {REQUEST_PREFIX!r}, so its record is recognisable.")
    wake_key = wake_keys.manual_key(wake_keys.owner(None, procedure_key), request_id)
    plan = {"procedureKey": procedure_key, "wakeKey": wake_key}
    if not apply:
        return {"status": "dry-run", **plan}
    first = _start(client, procedure_key, wake_key)
    run_id = str(first.get("runId") or "")
    if not run_id:
        raise WakeGuardCheckFailed(f"The first start answered without a run id: {first}")
    try:
        second = _start(client, procedure_key, wake_key)
        record = normalize_graphql_json_value(client.graphql(GET_PROCEDURE_RUN_QUERY, {"id": run_id}).get("getNewsroomProcedureRun")) or {}
    finally:
        # Whatever the second answer was, the first start made a record; it must not stay `started` for a run that never begins.
        update_cloud_procedure_run_record(client, {
            "id": run_id, "runStatus": "completed", "outcome": "nothing", "outcomeReason": REASON,
            "finishedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "resultSummary": "Wake guard check: this record proves the once-only create. No procedure ran.",
        })
    answers = {"first": first, "second": second}
    if first.get("duplicate") is not False or second.get("duplicate") is not True or second.get("runId") != run_id or record.get("wakeKey") != wake_key:
        raise WakeGuardCheckFailed(f"Expected created, then duplicate of {run_id}; got {json.dumps(answers, sort_keys=True)}")
    return {"status": "proved", **plan, "runId": run_id, "answers": answers}


def procedures_check_wake_guard(flags: list[str]) -> None:
    """`papyrus procedures check-wake-guard --procedure-key <key> [--request-id wake-guard-check-<id>] [--dry-run] [--json]`"""
    from .graphql_authoring import create_authoring_client
    from .options import parse_options, resolve_mutation_apply

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "procedures check-wake-guard")
    if not isinstance(options.get("procedure-key"), str):
        raise ValueError("papyrus procedures check-wake-guard needs --procedure-key <a published procedure with no required parameters>.")
    request_id = options["request-id"] if isinstance(options.get("request-id"), str) else new_request_id()
    result = check_wake_guard(create_authoring_client()[0], procedure_key=options["procedure-key"], request_id=request_id, apply=apply)
    if options.get("json"):
        print(json.dumps({"ok": True, "command": "procedures check-wake-guard", **result}, indent=2, sort_keys=True))
        return
    print(f"procedures\tcheck-wake-guard\t{result['status']}\t{result['wakeKey']}\t{result.get('runId', '')}")
