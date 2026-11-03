"""Read-only `papyrus monitors overview` and `papyrus monitors page`.

They ask the site's signed-in editor/admin API (the `monitoringOverview` and `monitoringPage` queries the newsroom
Monitoring page uses), authenticated with the `papyrus login` session. There is no AWS lane here: this module and the
client path it uses never import boto3, never read an AWS profile and never fall back to IAM. Every refusal is one
line and a non-zero exit.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from . import signed_in_lane as lane
from .signed_in_lane import SIGN_IN, Refusal

LISTS = ("runs", "routerRuns", "items", "emailSubmissions", "cyclotronStatus")
SCOPES = ("publication", "all")

OVERVIEW_QUERY = "query MonitoringOverview($scope: String) { monitoringOverview(scope: $scope) }"
PAGE_QUERY = ("query MonitoringPage($list: String!, $cursor: String, $filter: String, $scope: String) "
              "{ monitoringPage(list: $list, cursor: $cursor, filter: $filter, scope: $scope) }")

def add_arguments(sub) -> None:
    overview = sub.add_parser("overview", help="Read-only: monitoring state through your `papyrus login` session (no AWS credentials)")
    overview.add_argument("--scope", choices=SCOPES, default="publication", help="publication (default) or all (admins only)")
    overview.add_argument("--site", help="Which signed-in site, such as shipped.anth.us (needed when several are signed in)")
    overview.add_argument("--json", action="store_true", help="Print the raw response")
    page = sub.add_parser("page", help="Read-only: one page of a monitoring list through your `papyrus login` session (--list cyclotronStatus: this site's Cyclotron classifier status)")
    page.add_argument("--list", dest="list_name", required=True, choices=LISTS)
    page.add_argument("--cursor", help="Continue after this cursor (from the overview or a previous page)")
    page.add_argument("--held", action="store_true", help="Only held email submissions (emailSubmissions)")
    page.add_argument("--scope", choices=SCOPES, default="publication", help="publication (default) or all (admins only)")
    page.add_argument("--site", help="Which signed-in site, such as shipped.anth.us (needed when several are signed in)")
    page.add_argument("--json", action="store_true", help="Print the raw response")


def _client(site: str | None = None):
    """The shared authoring client, held to the signed-in user's headers: a missing session is an error, never IAM."""
    return lane.client(site)


def _refusal_for(scope: str) -> Refusal:
    if scope == "all":
        return Refusal("Refused: the whole pipeline (--scope all) is for admins, and monitoring is for editors and admins.")
    return Refusal("Refused: monitoring is for editors and admins; your signed-in account does not have that access.")


def fetch(client, query: str, field: str, variables: dict[str, Any], scope: str) -> Any:
    return lane.fetch(client, query, field, variables, noun="Monitoring", forbidden=lambda: _refusal_for(scope))


def _clip(value: Any, width: int = 70) -> str:
    text = " ".join(str(value if value is not None else "-").split())
    return text if len(text) <= width else text[: width - 1] + "..."


def _rows(rows: list[dict], line) -> list[str]:
    return ["  " + line(row) for row in rows] or ["  (none)"]


def _run_line(row: dict) -> str:
    return (f"{_clip(row.get('startedAt'), 25)}  {_clip(row.get('status'), 12)}  new {row.get('new', 0)}  "
            f"revised {row.get('revised', 0)}  errors {row.get('errorCount', 0)}")


def _router_line(row: dict) -> str:
    return f"{_clip(row.get('startedAt'), 25)}  {_clip(row.get('mode'), 10)}  {_clip(row.get('status'), 12)}  errors {row.get('errorCount', 0)}"


def _item_line(row: dict) -> str:
    return f"{_clip(row.get('routing'), 12)}  {_clip(row.get('sourceId'), 18)}  {_clip(row.get('title'))}"


def _email_line(row: dict) -> str:
    held = (row.get("quarantine") or {}).get("state")
    return f"{_clip(row.get('observedAt'), 25)}  {_clip(row.get('status'), 12)}  {'held ' if held == 'quarantined' else ''}{_clip(row.get('subject'))}"


def _status_line(row: dict) -> str:
    """One classifier snapshot of this site's publication, in the words the newsroom home page uses: a missing number is "not measured"."""
    status = row.get("status") or {}
    cyclotron, alignment = status.get("cyclotron") or {}, status.get("alignment") or {}
    accuracy = alignment.get("accuracy")
    agreement = f"{round(accuracy * 100)}%" if isinstance(accuracy, (int, float)) else "not measured"
    change = (status.get("lastChange") or {}).get("at")
    return (f"{_clip(row.get('output'), 28)}  as of {_clip(row.get('asOf'), 25)}  retrained {cyclotron.get('refits', 0)}x  "
            f"last change {_clip(change or 'none', 25)}  agreement {agreement}  labels {alignment.get('labels', 0)}")


LINES = {"runs": _run_line, "routerRuns": _router_line, "items": _item_line, "emailSubmissions": _email_line, "cyclotronStatus": _status_line}


def summarize_overview(data: dict) -> str:
    if data.get("state") in ("not_configured", "unavailable"):
        return f"Monitoring is {data['state'].replace('_', ' ')} for this site."
    scope = data.get("scope") or {}
    out = [f"Monitoring ({scope.get('mode', '?')}{', ' + str(scope['site']) if scope.get('site') else ''}) as of {data.get('asOf', '?')}"]
    if data.get("notice") == "publication_not_routed":
        out.append("Notice: this publication is not routed by any monitor.")
    router = data.get("router")
    if router:
        out.append(f"Router: {router.get('mode')}, {'enabled' if router.get('enabled') else 'disabled'}")
    usage = data.get("usage")
    if usage:
        out.append(f"Decisions: {usage.get('decisionsToday', 0)} today, {usage.get('decisionsTotal', 0)} total")
    feeds = data.get("feeds") or []
    out.append(f"Feeds ({len(feeds)}):")
    out += _rows(feeds, lambda f: f"{_clip(f.get('id'), 24)}  {'on ' if f.get('enabled') else 'off'}  {_clip(f.get('lastStatus'), 12)}  next {_clip(f.get('nextDueAt'), 25)}")
    for name, label in (("runs", "Collection runs"), ("routerRuns", "Router runs"), ("items", "Items"), ("emailSubmissions", "Email submissions")):
        rows = data.get(name) or []
        more = " (more: cursor available)" if (data.get("cursors") or {}).get(name) else ""
        out.append(f"{label} ({len(rows)} shown){more}:")
        out += _rows(rows, LINES[name])
    if data.get("hiddenNotRelevant"):
        out.append(f"Hidden as not relevant: {data['hiddenNotRelevant']}")
    if data.get("otherMonitors"):
        out.append("Other monitors: " + ", ".join(map(str, data["otherMonitors"])))
    return "\n".join(out)


def summarize_page(data: dict) -> str:
    if data.get("state") in ("not_configured", "unavailable"):
        return f"Monitoring is {data['state'].replace('_', ' ')} for this site."
    name = data.get("list", "?")
    rows = data.get("rows") or []
    out = [f"{name}: {len(rows)} rows"]
    out += _rows(rows, LINES.get(name, lambda r: _clip(json.dumps(r, sort_keys=True))))
    cursor = data.get("cursor")
    out.append(f"Next page: --cursor {cursor}" if cursor else "End of list.")
    return "\n".join(out)


def command(args, *, client=None, out=None) -> int:
    out = out or sys.stdout
    os.environ["PAPYRUS_GRAPHQL_AUTH"] = "user"   # the signed-in lane only; never IAM
    try:
        if args.command == "page" and args.held and args.list_name != "emailSubmissions":
            raise Refusal("--held applies only to --list emailSubmissions.")
        client = client or _client(args.site)
        if args.command == "overview":
            data = fetch(client, OVERVIEW_QUERY, "monitoringOverview", {"scope": args.scope}, args.scope)
            text = summarize_overview(data)
        else:
            variables = {"list": args.list_name, "cursor": args.cursor, "filter": "held" if args.held else None, "scope": args.scope}
            data = fetch(client, PAGE_QUERY, "monitoringPage", variables, args.scope)
            text = summarize_page(data)
        print(json.dumps(data, indent=2, sort_keys=True) if args.json else text, file=out)
        return 0
    except Refusal as refusal:
        print(str(refusal), file=sys.stderr)
        return 2
    except ValueError as error:   # AuthError (signed out, expired, no site configured) is a ValueError
        print(f"Not signed in or session unusable: {str(error).splitlines()[0]}", file=sys.stderr)
        return 2
