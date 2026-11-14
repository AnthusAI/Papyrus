"""Editor review of a story version (a stage bot's records, no model calls).

The editor-review procedure (`procedures/newsroom/editor_review.tac`) is a stage bot: it runs when a story enters a stage
(`copywriting` by default), judges the version against acceptance criteria and answers the engine with the stage-bot contract
`{version, hold, reason}` (docs/automations.md, "Story-state triggers").

Everything deterministic lives here so it is testable without a model:

* `gather_review_inputs` collects what the reviewer reads: the version, its linked References, the brief (or the doctrine
  as the brief), the editorial context and the stored editorial check, and the tables the check skips;
* `record_review` validates and normalizes the reviewer's answer, writes `Item.metadata.editorReview` on the version it
  reviewed, and returns the contract. A review that cannot be trusted never approves: an unassessed criterion, an error-level
  failure or an error-level editorial-check violation turns `approve` into `revise`.

Machine output goes on the record (the Item's metadata). This module never writes a Message, never changes the version's
state or stage (the engine moves the story) and never publishes.
"""

from __future__ import annotations

from typing import Any, Callable

from .record_helpers import to_aws_json
from .story_triggers import story_metadata

REVIEW_KEY = "editorReview"
BRIEF_METADATA_KEY = "editorBrief"
VERDICTS = ("approve", "revise", "reframe")
STATUSES = ("pass", "fail", "na")
SEVERITIES = ("error", "warn", "info")
REASON_LIMIT = 600
TEXT_LIMIT = 2000

# The acceptance criteria are generic: they name no publication, subject area or section. What a publication's doctrine
# adds is read from its editorial context at run time.
CRITERIA: tuple[dict[str, str], ...] = (
    {"key": "claims-attributed-and-linked",
     "question": "Is every claim that comes from outside the publication attributed to its actual source (not a second-hand page "
                 "that reports it) and linked, so a reader can open it?"},
    {"key": "own-numbers-traceable",
     "question": "Can every number about the publisher's own systems be traced to a record or a public file that the story links "
                 "or names?"},
    {"key": "no-untraceable-present-tense",
     "question": "Is every present-tense claim about the publisher's operations one the publication can show? Anything it cannot "
                 "show must be in the past tense, an offer, or removed."},
    {"key": "dates-sourced",
     "question": "Is every date or time claim (when something happened, 'this month', 'within days') taken from a dated source "
                 "rather than inferred, for example from when the publication's own monitor found it?"},
    {"key": "promises-kept",
     "question": "Does the story deliver what it promises (every row said to link to code does link, every list as long as said)?"},
    {"key": "tables-verified",
     "question": "Was every table checked by hand, cell by cell, against its evidence? The editorial check skips tables, so this "
                 "review is the only check they get. 'na' only when the version has no table."},
    {"key": "brief-met",
     "question": "Does the version do what its brief asks (angle, reader, sections, constraints)? 'na' when there is no brief; "
                 "the doctrine is then the brief."},
    {"key": "doctrine-fit",
     "question": "Does the version fit the publication's mission, policy and section guidance in the editorial context?"},
)
CRITERION_KEYS = tuple(entry["key"] for entry in CRITERIA)


def _text(value: Any, limit: int = TEXT_LIMIT) -> str:
    return str(value).strip()[:limit] if value is not None else ""


def find_tables(body: str) -> list[dict[str, Any]]:
    """The pipe tables of a Markus body (runs of two or more lines starting with `|`), with the line each one starts on."""
    tables: list[dict[str, Any]] = []
    run: list[str] = []
    start = 0
    for number, line in enumerate(body.splitlines() + [""], start=1):
        if line.lstrip().startswith("|"):
            if not run:
                start = number
            run.append(line)
            continue
        if len(run) >= 2:
            tables.append({"startLine": start, "text": "\n".join(run)})
        run = []
    return tables


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    return story_metadata(row)


def resolve_brief(client, row: dict[str, Any], lineage_id: str, read_attachment: Callable[[Any, dict[str, Any]], bytes | None] | None = None) -> dict[str, Any]:
    """The brief the version is reviewed against: `metadata.editorBrief` on the version, else the newest copywriting Assignment of the
    story (its `assignment_brief` attachment, else its summary), else none. With none, the doctrine is the brief."""
    text = _text(_metadata(row).get(BRIEF_METADATA_KEY), 20000)
    if text:
        return {"source": "story-metadata", "assignmentId": None, "text": text}
    if read_attachment is None:
        from .model_attachments import download_attachment_buffer as read_attachment
    assignments = [
        entry for entry in client.list_by_index("assignmentsByItemLineageAndCreatedAt", lineage_id)
        if str(entry.get("assignmentTypeKey") or "").startswith("copywriting.") and not entry.get("canceledAt") and entry.get("status") != "canceled"
    ]
    for assignment in sorted(assignments, key=lambda entry: str(entry.get("createdAt") or ""), reverse=True):
        attachments = [
            entry for entry in client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", assignment["id"])
            if entry.get("role") == "assignment_brief" and entry.get("status") != "deleted"
        ]
        if attachments:
            content = read_attachment(client, attachments[0])
            if content and content.decode("utf-8").strip():
                return {"source": "assignment-attachment", "assignmentId": assignment["id"], "text": content.decode("utf-8").strip()}
        if _text(assignment.get("summary")):
            return {"source": "assignment-summary", "assignmentId": assignment["id"], "text": _text(assignment.get("summary"), 20000)}
    return {"source": "none", "assignmentId": None, "text": ""}


def linked_references(client, lineage_id: str) -> list[dict[str, Any]]:
    from .story_reporting import current_reference, story_references

    rows = []
    for link in story_references(client, lineage_id):
        reference = current_reference(client, link["referenceLineageId"]) if link.get("referenceLineageId") else None
        rows.append({
            "referenceLineageId": link.get("referenceLineageId"), "role": link.get("role"), "citationKey": link.get("citationKey"),
            "note": link.get("note"), "title": (reference or {}).get("title"), "sourceUri": (reference or {}).get("sourceUri"),
            "sourcePublishedAt": (reference or {}).get("sourcePublishedAt"), "retrievedAt": (reference or {}).get("retrievedAt"),
        })
    return rows


def check_summary(check: dict[str, Any] | None) -> dict[str, Any]:
    """The editorial check as the reviewer and the record need it: status, counts, and the findings."""
    check = check or {}
    findings = [
        {key: finding.get(key) for key in ("rule", "severity", "status", "message", "quote", "scope", "probability")}
        for finding in check.get("findings") or []
    ]
    blocking = sorted({str(f.get("rule")) for f in findings if f.get("status") == "violation" and f.get("severity") == "error"})
    return {"status": check.get("status") or "not-run", "violations": int(check.get("violations") or 0), "reviews": int(check.get("reviews") or 0),
            "packVersion": check.get("packVersion"), "blocking": blocking, "findings": findings}


def gather_review_inputs(
    client, story: str, version: str, *, run_check: Callable[[str], dict[str, Any]], read_context: Callable[[str], dict[str, Any]],
    read_attachment: Callable[[Any, dict[str, Any]], bytes | None] | None = None,
) -> dict[str, Any]:
    """Everything the reviewer reads for one version. Runs the editorial check on it (`run_check(version_id)`)."""
    row = client.get_record("Item", version)
    if row is None:
        raise ValueError(f"Story version not found: {version}")
    if row.get("lineageId") != story:
        raise ValueError(f"Version {version} is not a version of story {story}.")
    body = row.get("bodyMarkus") or ""
    context = read_context(story)
    meta = _metadata(row)
    brief = resolve_brief(client, row, story, read_attachment)
    return {
        "story": story,
        "version": {"id": row["id"], "number": int(row.get("versionNumber") or 0), "state": row.get("versionState"), "stage": row.get("stage"),
                    "section": row.get("section"), "savedBy": row.get("versionCreatedBy"), "changeReason": row.get("changeReason"),
                    "botAction": meta.get("botAction"), "frontMatterYaml": meta.get("frontMatterYaml") or "", "bodyMarkus": body},
        "tables": find_tables(body),
        "references": linked_references(client, story),
        "brief": brief,
        "briefFallback": "no brief: the doctrine and policies in the editorial context are the brief" if brief["source"] == "none" else "",
        "editorialContext": {"text": context.get("text") or "", "hash": context.get("contextHash") or "", "warnings": context.get("warnings") or []},
        "editorialCheck": check_summary(run_check(row["id"])),
        "criteria": [dict(entry) for entry in CRITERIA],
    }


def _finding(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not _text(raw.get("criterion")):
        return None
    status = _text(raw.get("status")).lower()
    status = status if status in STATUSES else "fail"   # an unreadable status is never a pass
    severity = _text(raw.get("severity")).lower()
    severity = severity if severity in SEVERITIES else ("error" if status == "fail" else "info")
    return {"criterion": _text(raw["criterion"], 80), "status": status, "severity": severity, "quote": _text(raw.get("quote")), "note": _text(raw.get("note"))}


def _list(value: Any) -> list[str]:
    return [_text(entry) for entry in value if _text(entry)] if isinstance(value, list) else []


def normalize_review(raw: dict[str, Any], *, has_tables: bool, check: dict[str, Any] | None) -> dict[str, Any]:
    """The reviewer's answer as the record keeps it. Raises ValueError for an answer that is not a review (the run then fails and
    the engine raises a flag). Safety net: `approve` becomes `revise` when a criterion was not assessed, an error-level criterion
    failed, a table was not checked, or the editorial check found an error-level violation."""
    if not isinstance(raw, dict):
        raise ValueError("The editor review must be an object.")
    verdict = _text(raw.get("verdict")).lower()
    if verdict not in VERDICTS:
        raise ValueError(f"The editor review verdict must be one of {', '.join(VERDICTS)}, not {verdict or 'empty'}.")
    findings = [found for found in (_finding(entry) for entry in raw.get("findings") or []) if found]
    notes = _list(raw.get("revisionNotes"))
    answered = {found["criterion"]: found for found in findings}
    for key in CRITERION_KEYS:
        if key not in answered:
            findings.append({"criterion": key, "status": "fail", "severity": "error", "quote": "", "note": "Not assessed by the reviewer."})
    for found in findings:
        if found["criterion"] == "tables-verified" and has_tables and found["status"] == "na":
            found.update(status="fail", severity="error", note="The version has a table and the editorial check skips tables; they must be checked by hand.")
    summary = check_summary(check)
    reasons = [f"{found['criterion']}: {found['note'] or 'failed'}" for found in findings if found["status"] == "fail" and found["severity"] == "error"]
    reasons += [f"editorial check violation of {rule} (error severity)" for rule in summary["blocking"]]
    downgraded = None
    if verdict == "approve" and reasons:
        verdict, downgraded = "revise", "approve"
        notes = notes + [f"Not approved: {reason}" for reason in reasons if f"Not approved: {reason}" not in notes]
    if verdict != "approve" and not notes:
        notes = [f"{found['criterion']}: {found['note']}" for found in findings if found["status"] == "fail" and found["note"]] or ["The editor asked for a revision."]
    review: dict[str, Any] = {
        "verdict": verdict, "summary": _text(raw.get("summary")), "findings": findings, "revisionNotes": notes,
        "illustrationPlan": raw.get("illustrationPlan") if isinstance(raw.get("illustrationPlan"), dict) else {},
        "typesettingPlan": raw.get("typesettingPlan") if isinstance(raw.get("typesettingPlan"), dict) else {},
        "editorialCheck": {key: summary[key] for key in ("status", "violations", "reviews", "packVersion", "blocking")},
    }
    if downgraded:
        review["downgradedFrom"] = downgraded
    return review


def contract_for(review: dict[str, Any], version: str) -> dict[str, Any]:
    """The stage-bot contract for a review. The version is always the one reviewed: the editor does not edit. The engine moves an
    approved story to the automation's next stage; a revise or reframe holds it, and the engine raises a flag review request."""
    if review["verdict"] == "approve":
        return {"version": version, "hold": False, "reason": ""}
    reason = f"Editor review: {review['verdict']}. " + " ".join(review["revisionNotes"])
    return {"version": version, "hold": True, "reason": reason[:REASON_LIMIT]}


def record_review(
    client, story: str, version: str, raw: dict[str, Any], *, model: str, context_hash: str, check: dict[str, Any] | None, at: str,
) -> dict[str, Any]:
    """Normalize the reviewer's answer, store it as `Item.metadata.editorReview` on the version reviewed, return the contract.
    Writes the version's metadata only: no Message, no state or stage change, no publishing."""
    row = client.get_record("Item", version)
    if row is None or row.get("lineageId") != story:
        raise ValueError(f"Version {version} is not a version of story {story}.")
    review = normalize_review(raw, has_tables=bool(find_tables(row.get("bodyMarkus") or "")), check=check)
    review.update({"model": model, "contextHash": context_hash, "at": at, "versionId": row["id"], "versionNumber": int(row.get("versionNumber") or 0)})
    client.update_record("Item", {"id": row["id"], "metadata": to_aws_json({**_metadata(row), REVIEW_KEY: review})})
    result = {**contract_for(review, row["id"]), "verdict": review["verdict"]}
    if review.get("downgradedFrom"):
        result["downgradedFrom"] = review["downgradedFrom"]
    return result
