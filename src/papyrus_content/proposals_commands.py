"""``papyrus proposals create|list|show|transition|publish``: file, decide and publish proposals (docs/reader-steering.md).

A proposal is a change to the map written down where readers can see it. These commands call the ``fileProposal`` and
``transitionProposal`` mutations as the signed-in editor or admin (``papyrus login``), or, for an unattended run, with
``PAPYRUS_GRAPHQL_AUTH=iam`` as an operator role of the site's own AWS account. An operator can create (always an AI proposal)
and move a draft to ``in_steering`` or ``declined``; approving, reviewing and overriding need an editor, and ``list`` and ``show``
read the Proposal model, which only editors and admins may. The function validates the kind, the targets and the transition, and
answers a receipt. ``publish`` asks the site to run the reader snapshot, which writes the
public proposal files only when the site has opted in with ``proposals.publish``; otherwise proposals stay private.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from .graphql_authoring import create_authoring_client
from .options import normalize_string, parse_options, parse_repeated_option

USAGE = (
    "Usage:\n"
    "  papyrus proposals create --kind KIND --title TITLE (--body TEXT | --body-file FILE) [--summary LINE]\n"
    "      [--target TYPE:ID ...] [--signals N --source TEXT] [--json]\n"
    "  papyrus proposals list [--state STATE] [--json]\n"
    "  papyrus proposals show PROPOSAL_ID [--json]\n"
    "  papyrus proposals transition PROPOSAL_ID --to STATE [--reason TEXT] [--result approved|declined] [--json]\n"
    "  papyrus proposals publish [--json]   (writes public files only if the site sets proposals.publish)\n"
    "With PAPYRUS_GRAPHQL_AUTH=iam (an operator role of the site's own account) create, transition (draft to in_steering or declined only) and publish\n"
    "work; list and show, and every other transition, need an editor session (papyrus login).\n"
    "Kinds: story_draft, new_concept, rename, merge, split, new_column, element_symbol.\n"
    "States: draft, in_steering, editor_review, approved, declined, overridden_by_editor."
)

FILE_MUTATION = """
mutation FileProposal($kind: String!, $title: String!, $body: String!, $summary: String, $targets: AWSJSON, $evidence: AWSJSON) {
  fileProposal(kind: $kind, title: $title, body: $body, summary: $summary, targets: $targets, evidence: $evidence) { status id error message }
}
"""
TRANSITION_MUTATION = """
mutation TransitionProposal($proposalId: String!, $state: String!, $reason: String, $result: String) {
  transitionProposal(proposalId: $proposalId, state: $state, reason: $reason, result: $result) { status id error message }
}
"""
LIST_QUERY = """
query ListProposals($limit: Int, $nextToken: String) {
  listProposals(limit: $limit, nextToken: $nextToken) {
    items { id kind title summary body targets evidence proposer state history communityResult createdAt updatedAt }
    nextToken
  }
}
"""
GET_QUERY = """
query GetProposal($id: ID!) {
  getProposal(id: $id) { id kind title summary body targets evidence proposer state history communityResult createdAt updatedAt }
}
"""


class ProposalRefused(ValueError):
    pass


def using_iam() -> bool:
    return os.environ.get("PAPYRUS_GRAPHQL_AUTH", "").strip().lower() == "iam"


def reading_needs_an_editor(error: Exception) -> ValueError:
    """Reading proposals is for editors and admins; under IAM say so instead of surfacing a bare authorization error."""
    return ValueError(f"Could not read proposals ({error}). Reading them needs an editor or admin session (papyrus login); with PAPYRUS_GRAPHQL_AUTH=iam an operator can only create proposals and move a draft to in_steering or declined.")


def parse_targets(values: list[str]) -> list[dict[str, str]]:
    targets = []
    for value in values:
        kind, separator, identifier = value.partition(":")
        if not separator or not kind or not identifier:
            raise ValueError(f"--target must be TYPE:ID (for example concept:agents), not {value!r}.")
        targets.append({"type": kind, "id": identifier})
    return targets


def read_body(options: dict[str, Any]) -> str:
    inline, path = normalize_string(options.get("body")), normalize_string(options.get("body-file"))
    if inline and path:
        raise ValueError("Pass --body or --body-file, not both.")
    if path:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    if not inline:
        raise ValueError("proposals create requires --body or --body-file (Markus).")
    return inline


def receipt(result: dict[str, Any], field: str) -> str:
    answer = result.get(field) or {}
    if answer.get("status") != "ok":
        raise ProposalRefused(f"{answer.get('error') or 'refused'}: {answer.get('message') or 'The newsroom refused that.'}")
    return str(answer["id"])


def parsed(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def list_proposals(client: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    token = None
    while True:
        page = client.graphql(LIST_QUERY, {"limit": 100, "nextToken": token}).get("listProposals") or {}
        rows.extend(row for row in page.get("items") or [] if row)
        token = page.get("nextToken")
        if not token:
            return sorted(rows, key=lambda row: (row["createdAt"], row["id"]), reverse=True)


def create_command(flags: list[str]) -> None:
    options = parse_options(strip_repeated(flags, "target"))
    kind, title = normalize_string(options.get("kind")), normalize_string(options.get("title"))
    if not kind or not title:
        raise ValueError("proposals create requires --kind and --title.")
    variables: dict[str, Any] = {"kind": kind, "title": title, "body": read_body(options)}
    summary = normalize_string(options.get("summary"))
    if summary:
        variables["summary"] = summary
    targets = parse_targets(parse_repeated_option(flags, "target"))
    if targets:
        variables["targets"] = json.dumps(targets)
    signals = normalize_string(options.get("signals"))
    if signals is not None:
        variables["evidence"] = json.dumps({"signals": int(signals), "source": normalize_string(options.get("source"))})
    client, _ = create_authoring_client()
    identifier = receipt(client.graphql(FILE_MUTATION, variables), "fileProposal")
    emit(options, {"ok": True, "command": "proposals create", "id": identifier, "state": "draft"}, f"proposals\tcreate\t{identifier}\tdraft")


def strip_repeated(flags: list[str], key: str) -> list[str]:
    kept: list[str] = []
    index = 0
    while index < len(flags):
        if flags[index] == f"--{key}":
            index += 2
            continue
        kept.append(flags[index])
        index += 1
    return kept


def list_command(flags: list[str]) -> None:
    options = parse_options(flags)
    state = normalize_string(options.get("state"))
    client, _ = create_authoring_client()
    try:
        everything = list_proposals(client)
    except Exception as error:  # noqa: BLE001 - only an IAM caller gets the hint; an editor sees the real error
        if using_iam():
            raise reading_needs_an_editor(error) from error
        raise
    rows = [row for row in everything if not state or row["state"] == state]
    if options.get("json"):
        print(json.dumps({"ok": True, "command": "proposals list", "count": len(rows), "proposals": [summary_of(row) for row in rows]}, indent=2))
        return
    for row in rows:
        print("\t".join([row["id"], row["state"], row["kind"], row["createdAt"], row["title"]]))


def summary_of(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in ("id", "kind", "state", "title", "createdAt", "updatedAt")}


def show_command(flags: list[str]) -> None:
    if not flags or flags[0].startswith("--"):
        raise ValueError("proposals show requires a proposal id.")
    options = parse_options(flags[1:])
    client, _ = create_authoring_client()
    try:
        row = client.graphql(GET_QUERY, {"id": flags[0]}).get("getProposal")
    except Exception as error:  # noqa: BLE001
        if using_iam():
            raise reading_needs_an_editor(error) from error
        raise
    if not row:
        raise ValueError(f"Proposal not found: {flags[0]}")
    if options.get("json"):
        print(json.dumps({"ok": True, "command": "proposals show", "proposal": {**row, "targets": parsed(row.get("targets")), "history": parsed(row.get("history")), "evidence": parsed(row.get("evidence"))}}, indent=2))
        return
    print(f"{row['id']}\t{row['state']}\t{row['kind']}\t{row['title']}")
    for target in parsed(row.get("targets")) or []:
        print(f"target\t{target['type']}\t{target['id']}")
    for entry in parsed(row.get("history")) or []:
        print("\t".join(["history", entry["at"], f"{entry.get('from') or '-'} -> {entry['to']}", entry.get("reason") or ""]))
    print()
    print(row["body"])


def transition_command(flags: list[str]) -> None:
    if not flags or flags[0].startswith("--"):
        raise ValueError("proposals transition requires a proposal id.")
    proposal_id = flags[0]
    options = parse_options(flags[1:])
    state = normalize_string(options.get("to"))
    if not state:
        raise ValueError("proposals transition requires --to STATE.")
    variables = {"proposalId": proposal_id, "state": state, "reason": normalize_string(options.get("reason")), "result": normalize_string(options.get("result"))}
    client, _ = create_authoring_client()
    receipt(client.graphql(TRANSITION_MUTATION, variables), "transitionProposal")
    emit(options, {"ok": True, "command": "proposals transition", "id": proposal_id, "state": state}, f"proposals\ttransition\t{proposal_id}\t{state}")


def publish_command(flags: list[str]) -> None:
    from .projection_trigger import trigger_projection

    options = parse_options(flags)
    result = trigger_projection({"task": "reader-snapshot"})
    if not result.get("ok"):
        raise ValueError(f"Could not start the snapshot: {result.get('error')}. Retry: papyrus proposals publish")
    emit(options, {"ok": True, "command": "proposals publish", **result}, f"proposals\tpublish\t{result.get('scheduled') or result.get('ran')}\t{result.get('via')}")


def emit(options: dict[str, Any], payload: dict[str, Any], line: str) -> None:
    print(json.dumps(payload, indent=2) if options.get("json") else line)


COMMANDS = {"create": create_command, "list": list_command, "show": show_command, "transition": transition_command, "publish": publish_command}


def proposals_command(command: str, flags: list[str]) -> None:
    handler = COMMANDS.get(command)
    if handler is None:
        print(USAGE, file=sys.stderr)
        raise ValueError(f"Unsupported papyrus proposals command: {command}")
    try:
        handler(flags)
    except ProposalRefused as error:
        raise ValueError(str(error)) from error
