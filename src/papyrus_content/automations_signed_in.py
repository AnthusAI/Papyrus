"""`papyrus automations list|show|runs|run` on the signed-in lane (PPY-544564).

They ask the site's own editor/admin API (`automationOverview` and `runAutomation`, the operations the console
Automation page uses) with the `papyrus login` session. No Lambda invoke, no monitoring-table read, no boto3, no IAM.
The server does the reads and the run start, with its own role. Every refusal is one line and exit status 2.

The server has no dry run and no run-count argument, so on this lane `run --dry-run` is refused and `runs --limit`
cannot ask for more than the server returns. Use the IAM lane (`PAPYRUS_GRAPHQL_AUTH=iam`) for those.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from . import signed_in_lane as lane
from .automations import DEFAULT_RUN_LIMIT, ENABLED_NOTE, AutomationError, _json_option, _line, _print_outside_runs, _print_runs, cost_summary_text, noticeless
from .signed_in_lane import Refusal

OVERVIEW_QUERY = "query AutomationOverview($automationId: String) { automationOverview(automationId: $automationId) }"
RUN_MUTATION = "mutation RunAutomation($automationId: String!, $input: AWSJSON) { runAutomation(automationId: $automationId, input: $input) }"


def _forbidden(what: str):
    return lambda: Refusal(f"Refused: {what} is for editors and admins; your signed-in account does not have that access.")


def run_command(command: str, options: dict[str, Any], *, as_json: bool, apply: bool | None = None, client=None, out=None) -> int:
    """Returns the exit status. `apply` is None for the reads and the resolved write flag for `run`."""
    out = out or sys.stdout
    try:
        site = options.get("site") if isinstance(options.get("site"), str) else None
        target = options.get("id") if isinstance(options.get("id"), str) else None
        if command in {"show", "runs", "run"} and not target:
            raise Refusal(f"papyrus automations {command} needs --id <automation id>.")
        if command == "run":
            if not apply:
                raise Refusal("--dry-run is not available when signed in with `papyrus login`: the site has no dry run for Run now. "
                              "Run it for real, or use the IAM lane (PAPYRUS_GRAPHQL_AUTH=iam) for a dry run.")
            supplied = _json_option(options, "input")
        limit = int(options["limit"]) if isinstance(options.get("limit"), str) else None
        if limit is not None and limit > DEFAULT_RUN_LIMIT:
            raise Refusal(f"--limit above {DEFAULT_RUN_LIMIT} is not available when signed in with `papyrus login`: "
                          "the site returns its most recent runs only. Use the IAM lane (PAPYRUS_GRAPHQL_AUTH=iam) for longer history.")
        client = client or lane.client(site)
        if command == "run":
            result = lane.fetch(client, RUN_MUTATION, "runAutomation",
                                {"automationId": target, "input": None if supplied is None else json.dumps(supplied)},
                                noun="Run now", forbidden=_forbidden("Run now"))
            if result.get("state") == "refused":
                raise Refusal(f"Run now refused: {result.get('reason') or 'no reason given'}")
            if result.get("state") != "started":
                raise Refusal("Run now is unavailable: the site could not start the run.")
            if as_json:
                print(json.dumps({"ok": True, "command": "automations run", **result}, indent=2), file=out)
            else:
                print("\t".join(["automations", target, "started", f"requested by {result.get('requestedBy')}", str(result.get("key"))]), file=out)
            return 0
        overview = lane.fetch(client, OVERVIEW_QUERY, "automationOverview", {"automationId": target},
                              noun="Automations", forbidden=_forbidden("the automations list"))
        if overview.get("state") not in ("ready", "empty"):
            raise Refusal("Automations are unavailable for this site right now.")
        automations = overview.get("automations") or []
        if target and not automations:
            raise Refusal(f"automation {target} does not exist.")
        monitoring = overview.get("monitoring")
        if command == "runs" and monitoring != "ready":
            raise Refusal(f"the run history needs the monitoring table: {monitoring or 'monitoring_not_configured'}.")
        if limit is not None:
            for automation in automations:
                automation["runs"] = (automation.get("runs") or [])[:limit]
        if as_json:
            print(json.dumps({"ok": True, "command": f"automations {command}", **overview}, indent=2, default=str), file=out)
            return 0
        for automation in automations:
            if command == "list":
                print(_line(automation, automation), file=out)
            elif command == "show":
                print(_line(automation, automation), file=out)
                print(f"title\t{automation['title']}\nprocedure\t{automation['procedureKey']}\ntrigger\t{json.dumps(automation['trigger'])}", file=out)
                print(f"input\t{json.dumps(automation['inputTemplate'])}\nlimits\t{json.dumps(automation['limits'])} ({automation['limitsNote']})", file=out)
                print(f"enabled\t{automation['enabled']} ({ENABLED_NOTE})", file=out)
                link = automation.get("link") or {"state": "not checked", "text": noticeless(automation)}
                print(f"router\t{link['state']}\t{link.get('text') or ''}", file=out)
                if monitoring != "ready":
                    print(f"runs\t{monitoring or 'monitoring_not_configured'}", file=out)
            else:
                _print_runs(automation["runs"])
                _print_outside_runs(automation["outsideRuns"])
                if automation["outsideNotice"]:
                    print(f"outside\tthe procedure's other runs could not be read ({automation['outsideNotice']})")
                if automation["skippedAlreadyHadReference"]:
                    print(f"skipped\t{automation['skippedAlreadyHadReference']} item(s) not started because the Reference already existed")
                print(f"cost\t{cost_summary_text(automation['runs'])}")
        return 0
    except (Refusal, AutomationError) as refusal:
        print(str(refusal), file=sys.stderr)
        return 2
    except ValueError as error:   # AuthError (signed out, expired, no site configured) is a ValueError
        print(f"Not signed in or session unusable: {str(error).splitlines()[0]}", file=sys.stderr)
        return 2
