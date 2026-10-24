"""``papyrus proposals``: file, decide, steer and publish proposals (docs/reader-steering.md).

``create|list|show|transition|publish`` are the filing and deciding commands. The editor tier adds ``approve``, ``decline``,
``override``, ``pin``, ``unpin``, ``hold``, ``release``, ``exclude-votes``, ``undo-exclusion`` and ``needs-a-look``: editors and
admins only (an IAM operator is refused all of them by the function).

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
    "  papyrus proposals approve PROPOSAL_ID [--reason TEXT] [--json]       (editor review -> approved)\n"
    "  papyrus proposals decline PROPOSAL_ID [--reason TEXT] [--json]       (draft or editor review -> declined)\n"
    "  papyrus proposals override PROPOSAL_ID --result approved|declined --reason TEXT [--json]   (against the community; the reason is public)\n"
    "  papyrus proposals pin|unpin|hold|release PROPOSAL_ID [--json]\n"
    "  papyrus proposals exclude-votes PROPOSAL_ID --rule new-accounts-24h [--json]   (prints the exclusion id)\n"
    "  papyrus proposals undo-exclusion PROPOSAL_ID --exclusion EXCLUSION_ID [--json]\n"
    "  papyrus proposals needs-a-look [--json]   (editor-only: vote spikes, new-account surges, community vs AI)\n"
    "  papyrus proposals publish [--json]   (writes public files only if the site sets proposals.publish)\n"
    "With PAPYRUS_GRAPHQL_AUTH=iam (an operator role of the site's own account) create, transition (draft to in_steering or declined only) and publish\n"
    "work; list and show, every other transition and every editor action above need an editor session (papyrus login).\n"
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
EDIT_MUTATION = """
mutation EditProposal($proposalId: String!, $action: String!, $rule: String, $exclusionId: String) {
  editProposal(proposalId: $proposalId, action: $action, rule: $rule, exclusionId: $exclusionId) { status id error message }
}
"""
FIELDS = "id kind title summary body targets evidence proposer state history communityResult pinned held override exclusions needsLook createdAt updatedAt"
LIST_QUERY = """
query ListProposals($limit: Int, $nextToken: String) {
  listProposals(limit: $limit, nextToken: $nextToken) {
    items { %FIELDS% }
    nextToken
  }
}
"""
GET_QUERY = """
query GetProposal($id: ID!) {
  getProposal(id: $id) { %FIELDS% }
}
"""


LIST_QUERY = LIST_QUERY.replace("%FIELDS%", FIELDS)
GET_QUERY = GET_QUERY.replace("%FIELDS%", FIELDS)


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
        print(json.dumps({"ok": True, "command": "proposals show", "proposal": {**row, "targets": parsed(row.get("targets")), "history": parsed(row.get("history")), "evidence": parsed(row.get("evidence")), "exclusions": parsed(row.get("exclusions")), "needsLook": parsed(row.get("needsLook"))}}, indent=2))
        return
    print(f"{row['id']}\t{row['state']}\t{row['kind']}\t{row['title']}")
    flags = [name for name in ("pinned", "held") if row.get(name)]
    if flags:
        print("flags\t" + ", ".join(flags))
    for exclusion in parsed(row.get("exclusions")) or []:
        print("\t".join(["exclusion", exclusion["id"], exclusion["rule"], exclusion["at"], "undone " + exclusion["undoneAt"] if exclusion.get("undoneAt") else "active"]))
    for found in (parsed(row.get("needsLook")) or {}).get("reasons", []):
        print(f"needs-a-look\t{found['code']}\t{found['detail']}")
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


def proposal_argument(flags: list[str], command: str) -> tuple[str, dict[str, Any]]:
    if not flags or flags[0].startswith("--"):
        raise ValueError(f"proposals {command} requires a proposal id.")
    return flags[0], parse_options(flags[1:])


def decide_command(command: str, state: str):
    """``approve`` and ``decline``: the transition to ``state`` with the editor's optional public reason."""

    def run_command(flags: list[str]) -> None:
        proposal_id, options = proposal_argument(flags, command)
        variables = {"proposalId": proposal_id, "state": state, "reason": normalize_string(options.get("reason")), "result": None}
        client, _ = create_authoring_client()
        receipt(client.graphql(TRANSITION_MUTATION, variables), "transitionProposal")
        emit(options, {"ok": True, "command": f"proposals {command}", "id": proposal_id, "state": state}, f"proposals\t{command}\t{proposal_id}\t{state}")

    return run_command


def override_command(flags: list[str]) -> None:
    proposal_id, options = proposal_argument(flags, "override")
    result, reason = normalize_string(options.get("result")), normalize_string(options.get("reason"))
    if result not in ("approved", "declined"):
        raise ValueError("proposals override requires --result approved or --result declined.")
    if not reason:
        raise ValueError("proposals override requires --reason: the reason is public.")
    variables = {"proposalId": proposal_id, "state": "overridden_by_editor", "reason": reason, "result": result}
    client, _ = create_authoring_client()
    receipt(client.graphql(TRANSITION_MUTATION, variables), "transitionProposal")
    emit(options, {"ok": True, "command": "proposals override", "id": proposal_id, "state": "overridden_by_editor", "result": result}, f"proposals\toverride\t{proposal_id}\t{result}")


def edit_command(command: str, action: str):
    """``pin``, ``unpin``, ``hold`` and ``release`` take only the proposal id."""

    def run_command(flags: list[str]) -> None:
        proposal_id, options = proposal_argument(flags, command)
        client, _ = create_authoring_client()
        receipt(client.graphql(EDIT_MUTATION, {"proposalId": proposal_id, "action": action}), "editProposal")
        emit(options, {"ok": True, "command": f"proposals {command}", "id": proposal_id}, f"proposals\t{command}\t{proposal_id}")

    return run_command


def exclude_votes_command(flags: list[str]) -> None:
    proposal_id, options = proposal_argument(flags, "exclude-votes")
    rule = normalize_string(options.get("rule"))
    if not rule:
        raise ValueError("proposals exclude-votes requires --rule (for example new-accounts-24h).")
    client, _ = create_authoring_client()
    exclusion = receipt(client.graphql(EDIT_MUTATION, {"proposalId": proposal_id, "action": "exclude_votes", "rule": rule}), "editProposal")
    emit(options, {"ok": True, "command": "proposals exclude-votes", "id": proposal_id, "exclusion": exclusion, "rule": rule}, f"proposals\texclude-votes\t{proposal_id}\t{exclusion}")


def undo_exclusion_command(flags: list[str]) -> None:
    proposal_id, options = proposal_argument(flags, "undo-exclusion")
    exclusion = normalize_string(options.get("exclusion"))
    if not exclusion:
        raise ValueError("proposals undo-exclusion requires --exclusion EXCLUSION_ID (papyrus proposals show lists them).")
    client, _ = create_authoring_client()
    receipt(client.graphql(EDIT_MUTATION, {"proposalId": proposal_id, "action": "undo_exclusion", "exclusionId": exclusion}), "editProposal")
    emit(options, {"ok": True, "command": "proposals undo-exclusion", "id": proposal_id, "exclusion": exclusion}, f"proposals\tundo-exclusion\t{proposal_id}\t{exclusion}")


def needs_a_look_command(flags: list[str]) -> None:
    """The proposals whose last snapshot found reasons for an editor to look; the reasons are stored on the private row, never published."""
    options = parse_options(flags)
    client, _ = create_authoring_client()
    try:
        everything = list_proposals(client)
    except Exception as error:  # noqa: BLE001
        if using_iam():
            raise reading_needs_an_editor(error) from error
        raise
    found = [(row, (parsed(row.get("needsLook")) or {}).get("reasons") or []) for row in everything]
    found = [(row, reasons) for row, reasons in found if reasons]
    if options.get("json"):
        print(json.dumps({"ok": True, "command": "proposals needs-a-look", "count": len(found), "proposals": [{**summary_of(row), "reasons": reasons} for row, reasons in found]}, indent=2))
        return
    for row, reasons in found:
        print("\t".join([row["id"], row["state"], row["title"], "; ".join(f"{reason['label']}: {reason['detail']}" for reason in reasons)]))


def publish_command(flags: list[str]) -> None:
    from .projection_trigger import trigger_projection

    options = parse_options(flags)
    result = trigger_projection({"task": "reader-snapshot"})
    if not result.get("ok"):
        raise ValueError(f"Could not start the snapshot: {result.get('error')}. Retry: papyrus proposals publish")
    emit(options, {"ok": True, "command": "proposals publish", **result}, f"proposals\tpublish\t{result.get('scheduled') or result.get('ran')}\t{result.get('via')}")


def emit(options: dict[str, Any], payload: dict[str, Any], line: str) -> None:
    print(json.dumps(payload, indent=2) if options.get("json") else line)


COMMANDS = {
    "create": create_command,
    "list": list_command,
    "show": show_command,
    "transition": transition_command,
    "approve": decide_command("approve", "approved"),
    "decline": decide_command("decline", "declined"),
    "override": override_command,
    "pin": edit_command("pin", "pin"),
    "unpin": edit_command("unpin", "unpin"),
    "hold": edit_command("hold", "hold"),
    "release": edit_command("release", "release"),
    "exclude-votes": exclude_votes_command,
    "undo-exclusion": undo_exclusion_command,
    "needs-a-look": needs_a_look_command,
    "publish": publish_command,
}


def proposals_command(command: str, flags: list[str]) -> None:
    handler = COMMANDS.get(command)
    if handler is None:
        print(USAGE, file=sys.stderr)
        raise ValueError(f"Unsupported papyrus proposals command: {command}")
    try:
        handler(flags)
    except ProposalRefused as error:
        raise ValueError(str(error)) from error
