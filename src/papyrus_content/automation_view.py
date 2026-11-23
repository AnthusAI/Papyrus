"""The console's Automation page reads and acts through this function (PPY-9ff95b).

Three operations, one Lambda:

* `automationOverview(automationId)` reads the automation records with their router link, recent runs, the
  procedure's other runs and the cost of each. Editors and admins may read it, and so may an operator's IAM role
  in this account (an agent reading without a browser sign-in): AppSync admits only callers whose IAM policy
  allows the field, and this function admits a caller only when it is an IAM principal of the function's own
  account, not a Cognito identity-pool user.
* `todayOverview(day, timeZone)` is Today (`papyrus_content.today`): what ran in one day, what it decided to do nothing about and what it cost,
  read from the run status index. Same readers as `automationOverview`.
* `runAutomation(automationId, input)` starts a run now. Editors and admins only; an IAM caller is refused.
* `agentWake(input)` is the poke-in operation `agents_wake` (`agent_poke_in.wake`, PPY-e6f31e): one agent's latest wake for one subject goes on the
  site's wake queue again, once. Editors and admins only, as `papyrus agents wake` asks for it.
* `acknowledgeRun(runId)` takes one run off Today's attention list (`run_attention.acknowledge`): Acknowledge for a failure, Settle for an
  Outcome unknown. It records who and when; the run stays in the history. Editors and admins only; an IAM caller is refused.

The Lambda holds `dynamodb:GetItem` and `dynamodb:Query` on the monitoring table, `PutItem` for the Run now row,
`lambda:InvokeFunction` on the procedure runner, and `appsync:GraphQL` on a few fields of its own site's API (one of them a write:
`updateProcedureRun`, for acknowledging a run).
Trigger rows are read only for the publication this site is, so an editor cannot read another publication's runs.
Errors are states, never stack traces; the cause goes to the log by type only.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

from . import agent_wakes, run_attention
from .appsync_event import NoOperation, operation_name
from .staff_groups import STAFF_GROUPS
from .today import TodayError, today_overview
from .today_attention import site_time_zone
from .automations import (
    DEFAULT_RUN_LIMIT, AutomationError, MonitoringReader, MonitoringWriter, automation_overview,
    monitoring_reader_from_environment, monitoring_table_from_environment, read_record, run_now)

LOG = logging.getLogger(__name__)
EDITOR_GROUPS = STAFF_GROUPS


def default_client_factory(env):
    def factory():
        os.environ.setdefault("PAPYRUS_GRAPHQL_AUTH", "iam")   # the function's own role signs the call
        from .graphql_authoring import PapyrusGraphQLAuthoringClient
        return PapyrusGraphQLAuthoringClient(endpoint=env.get("PAPYRUS_GRAPHQL_ENDPOINT"))
    return factory


def is_operator(identity, account_id: str | None) -> bool:
    """An IAM principal (a role or user) of this account. A Cognito identity-pool user carries a Cognito identity id and is not one."""
    if not isinstance(identity, dict) or not account_id:
        return False
    arn = identity.get("userArn")
    return (isinstance(arn, str) and arn.startswith("arn:") and identity.get("accountId") == account_id
            and not identity.get("cognitoIdentityId") and not identity.get("sub"))


def actor_label(event: dict) -> str:
    identity = event.get("identity") or {}
    claims = identity.get("claims") or {}
    return str(claims.get("email") or identity.get("username") or "console")[:100]


def handle(event: dict, *, env=None, reader_factory=None, client_factory=None, now: float | None = None,
           account_id: str | None = None, table_factory=None, invoker=None) -> dict:
    """AppSync resolver entry: `automationOverview`, `todayOverview`, `runAutomation` or `agentWake`, named by the request's field (`appsync_event.operation_name`)."""
    env = os.environ if env is None else env
    identity = event.get("identity") or {}
    groups = identity.get("groups")
    groups = [group for group in groups if isinstance(group, str)] if isinstance(groups, list) else []
    is_editor = bool(set(groups) & EDITOR_GROUPS)
    try:
        field = operation_name(event)
    except NoOperation as error:
        return {"error": "bad_request", "message": str(error)}
    arguments = event.get("arguments") or {}
    automation_id = arguments.get("automationId") or None
    if automation_id is not None and not isinstance(automation_id, str):
        return {"error": "bad_request"}
    if field == "agentWake":
        if not is_editor:
            return {"ok": False, "error": "not_authorized", "message": "Only an editor or an admin wakes an agent now."}
        return _wake(event, arguments.get("input"), env=env, client_factory=client_factory, invoker=invoker)
    if field == "acknowledgeRun":
        if not is_editor:
            return {"error": "forbidden"}
        return _acknowledge(event, arguments.get("runId"), env=env, client_factory=client_factory, now=now)
    if field == "runAutomation":
        if not is_editor:
            return {"error": "forbidden"}
        if not automation_id:
            return {"error": "bad_request"}
        return _run(event, automation_id, arguments.get("input"), env=env, client_factory=client_factory,
                    table_factory=table_factory, invoker=invoker, now=now)
    if not (is_editor or is_operator(identity, account_id)):
        return {"error": "forbidden"}
    if field == "todayOverview":
        return _today(arguments, env=env, client_factory=client_factory, now=now)
    try:
        client = (client_factory or default_client_factory(env))()
        try:
            reader = (reader_factory or (lambda: monitoring_reader_from_environment(env)))()
        except Exception as error:   # records still list without the monitoring table
            LOG.error("monitoring table unavailable: %s", type(error).__name__)
            reader = None
        stamp = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return automation_overview(client, reader=reader, limit=DEFAULT_RUN_LIMIT, automation_id=automation_id,
                                   site_endpoint=env.get("PAPYRUS_GRAPHQL_ENDPOINT"), now=stamp)
    except Exception as error:   # the browser gets a state; the cause goes to the log by type only
        LOG.error("automation overview failed: %s", type(error).__name__)
        return {"state": "unavailable"}


def _today(arguments: dict, *, env, client_factory, now) -> dict:
    day, zone = arguments.get("day") or None, arguments.get("timeZone") or None
    if not all(value is None or isinstance(value, str) for value in (day, zone)):
        return {"error": "bad_request"}
    try:
        moment = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc)
        return today_overview((client_factory or default_client_factory(env))(), day=day, time_zone=zone, site_time_zone=site_time_zone(env), now=moment)
    except TodayError as error:   # the caller named a day or a zone that does not exist
        return {"error": "bad_request", "message": str(error)}
    except Exception as error:   # the browser gets a state; the cause goes to the log by type only
        LOG.error("today overview failed: %s", type(error).__name__)
        return {"state": "unavailable"}


def _wake(event: dict, supplied, *, env, client_factory, invoker) -> dict:
    """Wake now, answered as the operation table's envelope result: {"ok": true, "result"} or {"ok": false, "error", "message"}."""
    from .agent_policy.document import PolicyError
    from .agent_poke_in import PokeInError, RunLedger, wake
    from .images.handlers import Caller, check
    from .images.operations import operation

    try:
        request = json.loads(supplied) if isinstance(supplied, str) else supplied
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid_input", "message": "The input must be a JSON object."}
    if not isinstance(request, dict) or request.get("op") not in (None, "agents_wake"):
        return {"ok": False, "error": "invalid_input", "message": "The input is the agents_wake operation's: agent, subject and reason."}
    arguments = {name: value for name, value in request.items() if name != "op"}
    problem = check(operation("agents_wake").input, arguments)
    if problem:
        return {"ok": False, "error": "invalid_input", "message": problem[1]}
    if request.get("actorKind") == "agent":
        return {"ok": False, "error": "human_required", "message": "Wake now is a person's request. Nothing was sent."}
    try:
        client = (client_factory or default_client_factory(env))()
        result = wake(RunLedger(client, getattr(client, "tenant_id", None)), invoker or agent_wakes.wake_sender(), Caller(kind="person", subject=actor_label(event)),
                      agent=arguments["agent"], subject=arguments["subject"], reason=arguments["reason"])
        return {"ok": True, "result": result}
    except (PolicyError, PokeInError) as error:
        return {"ok": False, "error": error.code, "message": error.message}
    except Exception as error:   # the browser gets a state; the cause goes to the log by type only
        LOG.error("agent wake failed: %s", type(error).__name__)
        return {"ok": False, "error": "service_unavailable", "message": "The wake could not be sent right now. Nothing was sent; try again in a minute."}


def _acknowledge(event: dict, run_id, *, env, client_factory, now) -> dict:
    if not isinstance(run_id, str) or not run_id:
        return {"error": "bad_request", "message": "acknowledging a run needs its run id."}
    try:
        stamp = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        result = run_attention.acknowledge((client_factory or default_client_factory(env))(), run_id, actor_label(event), stamp)
        return {"state": "acknowledged" if result["changed"] else "unchanged", **result}
    except run_attention.AttentionError as error:   # the run does not exist: the message is written for the editor
        return {"state": "refused", "reason": str(error)}
    except Exception as error:
        LOG.error("acknowledge failed: %s", type(error).__name__)
        return {"state": "unavailable"}


def _run(event: dict, automation_id: str, supplied, *, env, client_factory, table_factory, invoker, now) -> dict:
    try:
        if isinstance(supplied, str):
            supplied = json.loads(supplied) if supplied.strip() else None
        client = (client_factory or default_client_factory(env))()
        row = client.get_record("Automation", automation_id)
        if not row:
            return {"state": "refused", "reason": f"automation {automation_id} does not exist."}
        table = (table_factory or (lambda: monitoring_table_from_environment(env)))()
        stamp = None if now is None else datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")
        result = run_now(read_record(row), reader=MonitoringReader(table) if table is not None else None,
                         writer=MonitoringWriter(table) if table is not None else None,
                         invoke=invoker or agent_wakes.wake_sender(), actor=actor_label(event),
                         supplied_input=supplied, site_endpoint=env.get("PAPYRUS_GRAPHQL_ENDPOINT"), now=stamp)
        return {"state": "started", "automationId": automation_id, "requestedBy": result["requestedBy"], "key": result["key"]}
    except AutomationError as error:   # a refusal the editor can act on: the message is written for them
        return {"state": "refused", "reason": str(error)}
    except json.JSONDecodeError:
        return {"state": "refused", "reason": "the input must be a JSON object."}
    except Exception as error:
        LOG.error("run now failed: %s", type(error).__name__)
        return {"state": "unavailable"}
