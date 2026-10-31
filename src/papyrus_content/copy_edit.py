"""The copy-edit gate (PPY-0c33a7): fix only what is mechanical, attach rewrite options for the rest, never publish.

After copywriting saves a version, the copy-edit step runs the site's editorial checks on it and sorts the findings:

* **Mechanical** means a deterministic replacement the site's own policy declares: a rules-lane finding that carries a
  ``replacement`` (a phrase policy that names what the phrase becomes, such as a stale product name, or the built-in
  uncontracted-forms check in a policy the site enabled because its house voice wants contractions). Policy data decides:
  a policy with no replacement, and every classifier (judgment) finding, is never rewritten here. The policy's author
  accepted that its replacement is safe to apply without a person reading it.
* **Everything else stays a finding.** Each surviving violation or review finding that quotes text gets rewrite options
  (``suggest``, from the same operation the editor's "Rewrite options" button uses) stored with the version's check result,
  for a person to choose from. Nothing is applied.

The mechanical fixes are saved as one new version with a reason and the author "AI". A version with an error-severity
violation that survives is not advanced: the result says ``hold`` (the stage-bot contract: the engine raises a flag review
request), and the command-line form raises the review request itself. This module never publishes and never moves a stage.
"""
from __future__ import annotations

import json
from typing import Any

from humanus.check import Utf16Offsets

from . import review_requests
from .editorial_checks import FINDING_SUMMARY_FIELDS, Services, check_editorial, check_run_record, suggest_rewrite
from .story_reporting import latest_story_version, save_story_version, story_versions

AUTHOR = "AI"
RAISED_BY = "copy-edit"
SUGGEST_FIELDS = ("id", "replacement", "rationale", "factVerificationRequired", "unresolvedQuestions")
SURVIVING_SEVERITY = "error"


def mechanical_fixes(body: str, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The findings whose policy declares a deterministic replacement, as non-overlapping edits against ``body``."""
    offsets = Utf16Offsets(body)
    edits: list[dict[str, Any]] = []
    for finding in sorted(findings, key=lambda f: ((f.get("span") or {}).get("start", 0), (f.get("span") or {}).get("end", 0))):
        replacement = finding.get("replacement")
        if finding.get("lane") != "rules" or finding.get("status") != "violation" or not isinstance(replacement, str):
            continue
        excerpt = finding.get("excerpt") or ""
        try:
            start, end = offsets.to_index(finding["span"]["start"]), offsets.to_index(finding["span"]["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if not excerpt or body[start:end] != excerpt or replacement == excerpt:
            continue  # the text moved, or there is nothing to change: never guess
        if edits and start < edits[-1]["end"]:
            continue  # overlapping rules: the first one wins, the other stays a finding
        edits.append({"start": start, "end": end, "findingId": finding.get("id"), "policyId": finding.get("policyId"), "from": excerpt, "to": replacement})
    return edits


def apply_fixes(body: str, edits: list[dict[str, Any]]) -> str:
    for edit in reversed(edits):
        body = body[: edit["start"]] + edit["to"] + body[edit["end"] :]
    return body


def _front_matter_of(item: dict[str, Any]) -> str | None:
    metadata = item.get("metadata")
    metadata = json.loads(metadata) if isinstance(metadata, str) and metadata else (metadata or {})
    return metadata.get("frontMatterYaml") or None


def _wants_options(finding: dict[str, Any]) -> bool:
    return finding.get("status") in ("violation", "review") and finding.get("severity") != "info" and bool(finding.get("excerpt"))


def attach_options(findings: list[dict[str, Any]], body: str, section: str | None, services: Services) -> dict[str, Any]:
    """Ask for rewrite options for each finding that quotes text; they are stored, never applied. Returns a status line."""
    import humanus

    attached = failed = 0
    unavailable = None
    for finding in findings:
        if not _wants_options(finding):
            continue
        if unavailable:
            break
        try:
            reply = suggest_rewrite({"body": body, "format": "markus", "section": section, "finding": json.dumps(finding)}, services)
        except humanus.SuggestUnavailableError as error:
            unavailable = str(error)[:300]  # no provider key: say so once instead of failing every finding
            break
        except Exception as error:  # noqa: BLE001 - one finding that cannot be rewritten never stops the others
            finding["suggestError"] = str(error)[:200]
            failed += 1
            continue
        finding["suggest"] = [{key: option.get(key) for key in SUGGEST_FIELDS if key in option} for option in reply.get("options") or []]
        attached += 1
    status: dict[str, Any] = {"attached": attached, "failed": failed}
    if unavailable:
        status["unavailable"] = unavailable
    return status


def _finding_line(finding: dict[str, Any]) -> dict[str, Any]:
    return {key: finding.get(key) for key in (*FINDING_SUMMARY_FIELDS, "suggest", "suggestError") if finding.get(key) is not None}


def copy_edit_version(
    client,
    services: Services,
    *,
    story: str,
    version: str | None = None,
    actor: str = AUTHOR,
    suggest: bool = True,
    raise_review: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Copy-edit one saved version of a story (the newest by default). See the module docstring for the rules."""
    if version:
        item = client.get_record("Item", version)
        if item is None or (item.get("lineageId") or item["id"]) != story:
            raise ValueError(f"Version {version} is not a version of story {story}.")
    else:
        item = latest_story_version(client, story)
    stored = services.store.get_check_run(item["id"])
    if stored and stored.get("contentHash") == item.get("contentHash") and "copyEdit" in (_lanes_of(stored) or {}):
        return {"story": story, "version": item["id"], "versionNumber": int(item.get("versionNumber") or 1), "changed": False, "skipped": "already copy-edited", "hold": False}
    section = item.get("section")
    body = item.get("bodyMarkus") or ""
    rules_only = check_editorial({"body": body, "format": "markus", "section": section, "lanes": {"classifier": False}}, services)
    edits = mechanical_fixes(body, rules_only["findings"])
    fixes = [{key: edit[key] for key in ("findingId", "policyId", "from", "to")} for edit in edits]
    if dry_run:
        return {"story": story, "version": item["id"], "changed": False, "dryRun": True, "mechanicalFixes": fixes, "hold": False}
    input_version = item["id"]
    if edits:
        policies = sorted({edit["policyId"] for edit in edits})
        reason = f"copy edit: {len(edits)} mechanical fix{'es' if len(edits) != 1 else ''} ({', '.join(policies)})"
        item = save_story_version(client, story, front_matter_yaml=_front_matter_of(item), body_markus=apply_fixes(body, edits), actor=actor, change_reason=reason)
        body = item["bodyMarkus"]
    result = check_editorial({"body": body, "format": "markus", "section": section}, services)
    options = attach_options(result["findings"], body, section, services) if suggest else {"attached": 0, "failed": 0, "skipped": "suggest off"}
    record = check_run_record(item, result, services.now())
    if services.last_check_request:
        record["packVersion"] = services.last_check_request["pack"].get("version")
    by_id = {finding["id"]: finding for finding in result["findings"]}
    record["findings"] = [_finding_line(by_id.get(line.get("id")) or line) for line in record["findings"]]
    record["lanes"] = {**(record.get("lanes") or {}), "copyEdit": {"status": "ran", "editor": actor, "mechanicalFixes": len(edits), "options": options}}
    stored_run: dict[str, Any] = {"stored": True}
    try:
        services.store.put_check_run(record)
    except Exception as error:  # noqa: BLE001 - the version and the result below stand; the stored copy needs a role that may write check runs
        stored_run = {"stored": False, "error": str(error)[:300]}
    surviving = [finding for finding in result["findings"] if finding.get("severity") == SURVIVING_SEVERITY and finding.get("status") == "violation"]
    outcome: dict[str, Any] = {
        "story": story, "inputVersion": input_version, "version": item["id"], "versionNumber": int(item.get("versionNumber") or 1),
        "changed": bool(edits), "mechanicalFixes": fixes, "violations": record["violations"], "reviews": record["reviews"],
        "findings": [_finding_line(finding) for finding in result["findings"]], "rewriteOptions": options, "checkRun": stored_run,
        "hold": bool(surviving),
    }
    if surviving:
        policies = sorted({finding["policyId"] for finding in surviving})
        outcome["reason"] = f"copy edit left {len(surviving)} error finding{'s' if len(surviving) != 1 else ''} ({', '.join(policies)}); a person has to decide"
        if raise_review:
            request = review_requests.raise_review(
                client, subject={"type": "story", "id": story}, mode="flag", raised_by=RAISED_BY, request_id=f"rr-copy-edit-{item['id']}",
                reason=outcome["reason"][:1000],
                ask="Read the findings (rewrite options are stored with the version's check) and fix or dismiss them. The story did not advance.",
                links=[{"type": "story", "id": item["id"], "label": f"version {outcome['versionNumber']}"}],
            )
            outcome["reviewRequest"] = request["id"]
    return outcome


def _lanes_of(run: dict[str, Any]) -> dict[str, Any]:
    lanes = run.get("lanes")
    if isinstance(lanes, str):
        lanes = json.loads(lanes)
        if isinstance(lanes, str):  # AWSJSON arrives double-encoded from some resolvers
            lanes = json.loads(lanes)
    return lanes or {}


def run_command(flags: list[str]) -> None:
    """``papyrus editorial copy-edit --story LINEAGE [--version ID] [--no-suggest] [--dry-run] [--json]``."""
    import argparse

    from .editorial_checks import GraphQLEditorialStore
    from .graphql_authoring import create_authoring_client

    parser = argparse.ArgumentParser(prog="papyrus editorial copy-edit", description="Apply a policy's mechanical fixes to a story version as a new version by AI, attach rewrite options for the rest, and raise a review request when an error finding survives. Never publishes.")
    parser.add_argument("--story", required=True, help="The story's lineage id.")
    parser.add_argument("--version", default=None, help="A version id (default: the newest).")
    parser.add_argument("--no-suggest", action="store_true", help="Skip the rewrite options (no model call).")
    parser.add_argument("--dry-run", action="store_true", help="Print the mechanical fixes; write nothing.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(flags)
    client, _ = create_authoring_client()
    services = Services(store=GraphQLEditorialStore(execute=client.graphql))
    outcome = copy_edit_version(client, services, story=args.story, version=args.version, suggest=not args.no_suggest, raise_review=True, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(outcome, indent=2, ensure_ascii=False))
        return
    print(f"editorial\tcopy-edit\t{outcome['story']}\t{outcome.get('version')}\t{len(outcome.get('mechanicalFixes') or [])} mechanical fixes"
          + ("\tdry run" if outcome.get("dryRun") else f"\t{outcome.get('violations', 0)} violations\t{outcome.get('reviews', 0)} for review\t{'HOLD: ' + outcome['reason'] if outcome['hold'] else 'clear'}"))
