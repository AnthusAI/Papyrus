"""The proposal record: what may be filed, which state changes are allowed, and who may make them.

A proposal is a change to the map written down where readers can see it: a story draft, a new concept, a rename, a merge,
a split, a new column or an element symbol. It is filed by AI (a reader proposer is part of the record but has no route yet)
and steered by votes; an editor decides. Staff reach this through the ``fileProposal`` and ``transitionProposal``
mutations (editors and admins; the function checks the groups again). An operator's IAM role in the function's own account
(an unattended automation or an agent without a browser sign-in) may also file an AI proposal and move it from draft to
in_steering or declined, and nothing else: approving, deciding after review and overriding stay with editors and admins.
``editProposal`` is the editor tier (pin, hold, exclude and restore votes): editors and admins only, never an operator. Every state change is appended to the proposal's
``history`` in the same conditional write that changes the state, so the history and the state cannot disagree.

Nothing here knows a person id. The proposer is ``"ai"`` or a reader's siteSubject, which is stored and never published; the
actor of a change is the staff member's Cognito subject, which is stored and never published either (the public file shows
"AI" or "Editor"). Votes are not counted here: they belong to the vote model and the snapshot joins them.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

KINDS = ("story_draft", "new_concept", "rename", "merge", "split", "new_column", "element_symbol")
DRAFT, IN_STEERING, EDITOR_REVIEW, APPROVED, DECLINED, OVERRIDDEN_BY_EDITOR = (
    "draft",
    "in_steering",
    "editor_review",
    "approved",
    "declined",
    "overridden_by_editor",
)
STATES = (DRAFT, IN_STEERING, EDITOR_REVIEW, APPROVED, DECLINED, OVERRIDDEN_BY_EDITOR)

#: Every allowed state change. Anything not listed is refused. Approved, declined and overridden are final.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    DRAFT: (IN_STEERING, DECLINED),
    IN_STEERING: (EDITOR_REVIEW,),
    EDITOR_REVIEW: (APPROVED, DECLINED, OVERRIDDEN_BY_EDITOR),
}
#: The changes that need a reason. Every reason is public; this one is also required, because it explains a decision against the community.
REASON_REQUIRED = frozenset({OVERRIDDEN_BY_EDITOR})
#: An override says what the editor decided against the community's view: approved or declined. Approve and decline are their own result.
OVERRIDE_RESULTS = (APPROVED, DECLINED)

#: How many target subjects each kind names, as (minimum, maximum), and the types a target may have.
TARGET_COUNTS: dict[str, tuple[int, int]] = {
    "story_draft": (0, 10),
    "new_concept": (0, 10),
    "rename": (1, 1),
    "merge": (2, 10),
    "split": (1, 1),
    "new_column": (0, 10),
    "element_symbol": (1, 1),
}
TARGET_TYPES = ("concept", "entity", "column", "story", "cluster")

MUTATIONS = ("fileProposal", "transitionProposal", "editProposal")
#: The one read an operator has: ``listStoryDrafts`` answers the story drafts and nothing else of them (never the body, the evidence, the
#: history, the proposer, a vote, the editor log or a reason), so an unattended run can avoid filing a near-duplicate of an earlier draft.
QUERIES = ("listStoryDrafts",)
STORY_DRAFT_FIELDS = ("id", "title", "summary", "targets", "state", "createdAt")
MAXIMUM_STORY_DRAFTS = 500

#: What ``editProposal`` does beyond moving the state. Editors and admins only: an operator is refused every one of them.
PIN, UNPIN, HOLD, RELEASE, EXCLUDE_VOTES, UNDO_EXCLUSION = "pin", "unpin", "hold", "release", "exclude_votes", "undo_exclusion"
EDIT_ACTIONS = (PIN, UNPIN, HOLD, RELEASE, EXCLUDE_VOTES, UNDO_EXCLUSION)
FINAL_STATES = (APPROVED, DECLINED, OVERRIDDEN_BY_EDITOR)
#: The batch rules for excluding votes. A rule excludes the votes on one proposal that were already cast, by accounts that were
#: younger than ``hours`` when they voted; the snapshot applies it (votes are not counted here). ``label`` is the public wording.
EXCLUSION_RULES: dict[str, dict[str, Any]] = {
    "new-accounts-24h": {"hours": 24, "label": "accounts under 24 h"},
}
EXCLUSION_ID = re.compile(r"exc-[0-9a-f]{12}")
MAXIMUM_EDITOR_LOG = 200


def event_field_name(event: dict[str, Any]) -> str | None:
    """The GraphQL field an AppSync invocation is for.

    The Amplify Gen 2 Lambda data source sends ``fieldName`` at the top level with no ``info`` key; a direct resolver nests it
    under ``info``. Accept both.
    """
    info = event.get("info")
    name = (info.get("fieldName") if isinstance(info, dict) else None) or event.get("fieldName")
    return name if isinstance(name, str) and name else None


def is_appsync_event(event: dict[str, Any]) -> bool:
    """True for an AppSync invocation (arguments plus ``info`` or a top-level ``fieldName``); the public path sends siteSubject, action and payload."""
    return "arguments" in event and ("info" in event or event_field_name(event) is not None)
PROPOSER_AI = "ai"
STAFF_GROUPS = frozenset({"editor", "admin"})
#: The only moves an operator's IAM role may make, as (from, to). Everything after the draft is an editor's decision.
OPERATOR_TRANSITIONS = frozenset({(DRAFT, IN_STEERING), (DRAFT, DECLINED)})
BY_STAFF, BY_OPERATOR = "staff", "operator"
MAXIMUM_OPERATOR_LABEL = 256
PROPOSAL_ID = re.compile(r"prop-[0-9a-f]{32}")
TARGET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}")
MAXIMUM_TITLE = 200
MAXIMUM_SUMMARY = 300
MAXIMUM_BODY = 50_000
MAXIMUM_REASON = 500
MAXIMUM_EVIDENCE_SOURCE = 200
MAXIMUM_EVIDENCE_SIGNALS = 1_000_000
#: An optional figure spec kept in ``evidence.figure``: a small chart of cited series (no image), approved with the copy.
FIGURE_TYPES = ("line", "bar")
MAXIMUM_FIGURE_POINTS = 60
MAXIMUM_FIGURE_SERIES = 6
MAXIMUM_FIGURE_BYTES = 8_000


@dataclass
class Outcome:
    status: str  # "ok" or "refused"
    id: str | None = None
    error: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "id": self.id, "error": self.error, "message": self.message}


def refused(error: str, message: str) -> Outcome:
    return Outcome("refused", error=error, message=message)


class ProposalStore(Protocol):
    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None: ...

    def create_proposal(self, row: dict[str, Any]) -> bool: ...

    def change_proposal(self, proposal_id: str, changes: dict[str, Any], expected_state: str, now_iso: str, *, expected_updated_at: str | None = None) -> bool: ...

    def list_story_drafts(self, limit: int) -> list[dict[str, Any]]: ...


def staff_subject(identity: dict[str, Any]) -> str | None:
    """The Cognito subject of an editor or admin, or ``None`` for anyone else."""
    claims = identity.get("claims") or {}
    groups = claims.get("cognito:groups") or identity.get("groups") or []
    if isinstance(groups, str):
        groups = [group.strip() for group in groups.strip("[]").replace(",", " ").split()]
    subject = identity.get("sub")
    if not isinstance(subject, str) or not subject or not STAFF_GROUPS.intersection(groups):
        return None
    return subject


def operator_actor(identity: dict[str, Any], account_id: str | None) -> str | None:
    """``operator:<principal ARN>`` for an IAM principal (a role or user) of the function's own account, or ``None``.

    A Cognito identity-pool user is also an IAM principal of this account, but it carries a Cognito identity id (and a
    user-pool caller carries a subject); neither is an operator. A principal of another account is refused, and so is a
    caller whose ARN names another account than the one AppSync reports.
    """
    if not isinstance(identity, dict) or not account_id:
        return None
    arn = identity.get("userArn")
    parts = arn.split(":") if isinstance(arn, str) else []
    if len(parts) < 6 or parts[0] != "arn" or parts[4] != account_id or identity.get("accountId") != account_id:
        return None
    if any(identity.get(key) for key in ("cognitoIdentityId", "cognitoIdentityPoolId", "cognitoIdentityAuthType", "sub", "claims")):
        return None
    return f"operator:{arn}"[:MAXIMUM_OPERATOR_LABEL]


def clean_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if text and len(text) <= limit else None


def parse_json(value: Any) -> Any:
    """AppSync delivers AWSJSON arguments as strings; the CLI and tests may pass the parsed value."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def clean_targets(kind: str, raw: Any) -> list[dict[str, str]] | Outcome:
    parsed = parse_json(raw) if raw is not None else []
    if not isinstance(parsed, list):
        return refused("invalid_targets", "targets must be a list of {type, id}.")
    minimum, maximum = TARGET_COUNTS[kind]
    targets: list[dict[str, str]] = []
    for entry in parsed:
        if not isinstance(entry, dict) or entry.get("type") not in TARGET_TYPES or not isinstance(entry.get("id"), str) or not TARGET_ID.fullmatch(entry["id"]):
            return refused("invalid_targets", f"Each target is {{type, id}} with a type of {', '.join(TARGET_TYPES)}.")
        target = {"type": entry["type"], "id": entry["id"]}
        if target in targets:
            return refused("invalid_targets", "A target is named twice.")
        targets.append(target)
    if not minimum <= len(targets) <= maximum:
        wanted = f"{minimum}" if minimum == maximum else f"{minimum} to {maximum}"
        return refused("invalid_targets", f"A {kind} proposal names {wanted} target(s).")
    return targets


def clean_figure(raw: Any) -> dict[str, Any] | None:
    """A chart spec ``{type, title, caption, unit, source, x, series: [{signal, label, values}]}``, or None when it is malformed.

    Unknown keys are dropped. Every series has exactly one value per ``x`` label; values are whole or decimal numbers, never text."""
    if not isinstance(raw, dict) or raw.get("type") not in FIGURE_TYPES:
        return None
    title, caption, unit, source = (clean_text(raw.get(key), limit) for key, limit in (("title", 200), ("caption", 300), ("unit", 60), ("source", MAXIMUM_EVIDENCE_SOURCE)))
    x, series = raw.get("x"), raw.get("series")
    if None in (title, caption, unit, source) or not isinstance(x, list) or not isinstance(series, list):
        return None
    if not 2 <= len(x) <= MAXIMUM_FIGURE_POINTS or not 1 <= len(series) <= MAXIMUM_FIGURE_SERIES:
        return None
    labels = [clean_text(label, 20) for label in x]
    if None in labels:
        return None
    cleaned = []
    for entry in series:
        if not isinstance(entry, dict):
            return None
        signal, label, values = clean_text(entry.get("signal"), 130), clean_text(entry.get("label"), 120), entry.get("values")
        if signal is None or label is None or not isinstance(values, list) or len(values) != len(labels):
            return None
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1_000_000_000 for value in values):
            return None
        cleaned.append({"signal": signal, "label": label, "values": list(values)})
    figure = {"type": raw["type"], "title": title, "caption": caption, "unit": unit, "source": source, "x": labels, "series": cleaned}
    return figure if len(json.dumps(figure)) <= MAXIMUM_FIGURE_BYTES else None


def clean_evidence(raw: Any) -> dict[str, Any] | None | Outcome:
    parsed = parse_json(raw) if raw is not None else None
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        return refused("invalid_evidence", "evidence must be {signals, source} with an optional figure.")
    signals, source = parsed.get("signals"), parsed.get("source")
    if not isinstance(signals, int) or isinstance(signals, bool) or not 0 <= signals <= MAXIMUM_EVIDENCE_SIGNALS:
        return refused("invalid_evidence", "evidence.signals must be a whole number of signals.")
    if source is not None and clean_text(source, MAXIMUM_EVIDENCE_SOURCE) is None:
        return refused("invalid_evidence", "evidence.source must be short text.")
    evidence = {"signals": signals, "source": source.strip() if isinstance(source, str) else None}
    if parsed.get("figure") is not None:
        figure = clean_figure(parsed["figure"])
        if figure is None:
            return refused("invalid_evidence", "evidence.figure must be a small chart spec: type line or bar, title, caption, unit, source, x labels and series with one value per label.")
        evidence["figure"] = figure
    return evidence


def file_proposal(arguments: dict[str, Any], *, actor_sub: str, now_iso: str, proposal_id: str | None = None) -> tuple[dict[str, Any] | None, Outcome | None]:
    """The new row for a proposal in ``draft``, or the refusal. The proposer is AI: reader filing has no route yet."""
    kind = arguments.get("kind")
    if kind not in KINDS:
        return None, refused("invalid_kind", f"kind must be one of {', '.join(KINDS)}.")
    title = clean_text(arguments.get("title"), MAXIMUM_TITLE)
    if title is None:
        return None, refused("invalid_title", f"A proposal needs a title of at most {MAXIMUM_TITLE} characters.")
    body = arguments.get("body")  # Markus source, kept byte for byte
    if not isinstance(body, str) or not body.strip() or len(body) > MAXIMUM_BODY:
        return None, refused("invalid_body", "A proposal needs a body (Markus), at most 50,000 characters.")
    summary = arguments.get("summary")
    if summary is not None and clean_text(summary, MAXIMUM_SUMMARY) is None:
        return None, refused("invalid_summary", f"summary is one line of at most {MAXIMUM_SUMMARY} characters.")
    targets = clean_targets(kind, arguments.get("targets"))
    if isinstance(targets, Outcome):
        return None, targets
    evidence = clean_evidence(arguments.get("evidence"))
    if isinstance(evidence, Outcome):
        return None, evidence
    identifier = proposal_id or "prop-" + uuid.uuid4().hex
    row: dict[str, Any] = {
        "id": identifier,
        "kind": kind,
        "title": title,
        "body": body,
        "targets": json.dumps(targets),
        "proposer": PROPOSER_AI,
        "state": DRAFT,
        "history": json.dumps([{"from": None, "to": DRAFT, "by": "ai", "actor": actor_sub, "reason": None, "at": now_iso}]),
        "createdAt": now_iso,
    }
    if summary is not None:
        row["summary"] = summary.strip()
    if evidence is not None:
        row["evidence"] = json.dumps(evidence)
    return row, None


def transition_plan(row: dict[str, Any], to_state: Any, reason: Any, *, actor_sub: str, now_iso: str, result: Any = None, by: str = BY_STAFF) -> dict[str, Any] | Outcome:
    """The changes that move ``row`` to ``to_state``, or why it may not move."""
    state = row.get("state")
    if to_state not in STATES:
        return refused("invalid_state", f"state must be one of {', '.join(STATES)}.")
    if to_state not in TRANSITIONS.get(state, ()):
        return refused("transition_not_allowed", f"A proposal in {state} cannot move to {to_state}.")
    if row.get("held"):
        return refused("proposal_held", "That proposal is on hold. Release it before it moves.")
    text = None
    if reason is not None and str(reason).strip():
        text = clean_text(reason, MAXIMUM_REASON)
        if text is None:
            return refused("invalid_reason", f"A reason is plain text of at most {MAXIMUM_REASON} characters.")
    if to_state in REASON_REQUIRED and text is None:
        return refused("reason_required", "Overriding the community needs a public reason.")
    if to_state == OVERRIDDEN_BY_EDITOR:
        if result not in OVERRIDE_RESULTS:
            return refused("result_required", f"An override says what the editor decided: {' or '.join(OVERRIDE_RESULTS)}.")
    elif result is not None:
        return refused("result_not_allowed", "Only an override carries a result; approve and decline are their own.")
    entry = {"from": state, "to": to_state, "by": by, "actor": actor_sub, "reason": text, "at": now_iso}
    if result is not None:
        entry["result"] = result
    history = [*(parse_json(row.get("history")) or []), entry]
    changes: dict[str, Any] = {"state": to_state, "history": json.dumps(history)}
    if to_state == OVERRIDDEN_BY_EDITOR:
        # Stored on the proposal beside the community result, which stays as it was: readers see both.
        changes["override"] = json.dumps({"result": result, "reason": text, "at": now_iso})
    return changes


def apply_transition(
    store: ProposalStore,
    *,
    proposal_id: Any,
    to_state: Any,
    reason: Any,
    actor_sub: str,
    now_iso: str,
    result: Any = None,
    by: str = BY_STAFF,
    allowed: frozenset[tuple[str, str]] | None = None,
) -> Outcome:
    """Move a proposal. ``allowed`` (as (from, to) pairs) narrows the road for a caller who may not take all of it."""
    if not isinstance(proposal_id, str) or not PROPOSAL_ID.fullmatch(proposal_id):
        return refused("invalid_proposal", "That is not a proposal id.")
    row = store.get_proposal(proposal_id)
    if row is None:
        return refused("not_found", "There is no such proposal.")
    if allowed is not None and (row.get("state"), to_state) not in allowed:
        return refused("operator_not_allowed", "An operator can only move a draft to in_steering or declined; the rest is for editors and admins.")
    plan = transition_plan(row, to_state, reason, actor_sub=actor_sub, now_iso=now_iso, result=result, by=by)
    if isinstance(plan, Outcome):
        return plan
    if not store.change_proposal(proposal_id, plan, row["state"], now_iso):
        return refused("target_changed", "Someone else changed that proposal first.")
    return Outcome("ok", id=proposal_id)


def log_entry(action: str, actor_sub: str, now_iso: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"action": action, "by": BY_STAFF, "actor": actor_sub, "at": now_iso}
    if detail:
        entry["detail"] = detail
    return entry


def edit_plan(row: dict[str, Any], action: Any, *, rule: Any = None, exclusion_id: Any = None, actor_sub: str, now_iso: str) -> dict[str, Any] | Outcome:
    """The changes for a pin, hold or vote-exclusion action on ``row``, or why it may not be done.

    Every action is appended to the private ``editorLog`` in the same write. Changing the exclusions clears the frozen
    ``communityResult`` so the next snapshot fixes it again with the exclusions applied; the function never counts votes itself.
    """
    if action not in EDIT_ACTIONS:
        return refused("invalid_action", f"action must be one of {', '.join(EDIT_ACTIONS)}.")
    detail: dict[str, Any] | None = None
    changes: dict[str, Any] = {}
    if action in (PIN, UNPIN):
        if bool(row.get("pinned")) == (action == PIN):
            return refused("already_pinned" if action == PIN else "not_pinned", "That proposal is already pinned." if action == PIN else "That proposal is not pinned.")
        changes["pinned"] = action == PIN
    elif action in (HOLD, RELEASE):
        if action == HOLD and row.get("state") in FINAL_STATES:
            return refused("proposal_decided", "A decided proposal cannot be put on hold.")
        if bool(row.get("held")) == (action == HOLD):
            return refused("already_held" if action == HOLD else "not_held", "That proposal is already on hold." if action == HOLD else "That proposal is not on hold.")
        changes["held"] = action == HOLD
    else:
        exclusions = parse_json(row.get("exclusions")) or []
        if action == EXCLUDE_VOTES:
            if rule not in EXCLUSION_RULES:
                return refused("invalid_rule", f"rule must be one of {', '.join(EXCLUSION_RULES)}.")
            identifier = "exc-" + uuid.uuid4().hex[:12]
            exclusions = [*exclusions, {"id": identifier, "rule": rule, "at": now_iso, "actor": actor_sub}]
            detail = {"exclusion": identifier, "rule": rule}
        else:
            if not isinstance(exclusion_id, str) or not EXCLUSION_ID.fullmatch(exclusion_id):
                return refused("invalid_exclusion", "That is not an exclusion id.")
            found = next((entry for entry in exclusions if entry.get("id") == exclusion_id), None)
            if found is None:
                return refused("unknown_exclusion", "That proposal has no such exclusion.")
            if found.get("undoneAt"):
                return refused("already_undone", "That exclusion was already undone.")
            found["undoneAt"], found["undoneBy"] = now_iso, actor_sub
            detail = {"exclusion": exclusion_id, "rule": found.get("rule")}
        changes["exclusions"] = json.dumps(exclusions)
        if row.get("communityResult"):
            changes["communityResult"] = None  # removed: the next snapshot fixes it again without the excluded votes
    log = [*(parse_json(row.get("editorLog")) or []), log_entry(action, actor_sub, now_iso, detail)][-MAXIMUM_EDITOR_LOG:]
    changes["editorLog"] = json.dumps(log)
    return changes


def apply_edit(store: ProposalStore, *, proposal_id: Any, action: Any, rule: Any, exclusion_id: Any, actor_sub: str, now_iso: str) -> Outcome:
    if not isinstance(proposal_id, str) or not PROPOSAL_ID.fullmatch(proposal_id):
        return refused("invalid_proposal", "That is not a proposal id.")
    row = store.get_proposal(proposal_id)
    if row is None:
        return refused("not_found", "There is no such proposal.")
    plan = edit_plan(row, action, rule=rule, exclusion_id=exclusion_id, actor_sub=actor_sub, now_iso=now_iso)
    if isinstance(plan, Outcome):
        return plan
    if not store.change_proposal(proposal_id, plan, row["state"], now_iso, expected_updated_at=row.get("updatedAt")):
        return refused("target_changed", "Someone else changed that proposal first.")
    # An exclusion's id is what undo_exclusion takes; the pin and hold receipts carry the proposal id.
    created = json.loads(plan["exclusions"])[-1]["id"] if action == EXCLUDE_VOTES else proposal_id
    return Outcome("ok", id=created)


def handle_proposal_event(event: dict[str, Any], store: ProposalStore, *, now_iso: str, account_id: str | None = None) -> dict[str, Any]:
    """``fileProposal``, ``transitionProposal`` or ``editProposal`` from AppSync. Answers a receipt, never an exception.

    Editors and admins act as themselves. An IAM principal of ``account_id`` (the function's own account) acts as an operator:
    it files AI proposals and moves draft to in_steering or declined, recorded as ``operator:<ARN>``. Anyone else is refused.
    """
    identity = event.get("identity") or {}
    staff = staff_subject(identity)
    operator = None if staff is not None else operator_actor(identity, account_id)
    actor = staff or operator
    if actor is None:
        return refused("not_staff", "Only editors, admins and operators of this account can file proposals; only editors and admins decide them.").to_dict()
    arguments = event.get("arguments") or {}
    field = event_field_name(event)
    if field == "editProposal":
        if staff is None:
            return refused("operator_not_allowed", "Pinning, holding and excluding votes are for editors and admins; an operator can only file proposals and move a draft to in_steering or declined.").to_dict()
        return apply_edit(
            store,
            proposal_id=arguments.get("proposalId"),
            action=arguments.get("action"),
            rule=arguments.get("rule"),
            exclusion_id=arguments.get("exclusionId"),
            actor_sub=staff,
            now_iso=now_iso,
        ).to_dict()
    if field == "fileProposal":
        row, problem = file_proposal(arguments, actor_sub=actor, now_iso=now_iso)
        if problem is not None:
            return problem.to_dict()
        if not store.create_proposal(row):
            return refused("exists", "That proposal already exists.").to_dict()
        return Outcome("ok", id=row["id"]).to_dict()
    return apply_transition(
        store,
        proposal_id=arguments.get("proposalId"),
        to_state=arguments.get("state"),
        reason=arguments.get("reason"),
        result=arguments.get("result"),
        actor_sub=actor,
        now_iso=now_iso,
        by=BY_OPERATOR if operator else BY_STAFF,
        allowed=OPERATOR_TRANSITIONS if operator else None,
    ).to_dict()


def story_draft_summary(row: dict[str, Any]) -> dict[str, Any]:
    """The six fields an operator may read of a story draft. ``targets`` stays the JSON text it is stored as."""
    summary = {field: row.get(field) for field in STORY_DRAFT_FIELDS}
    if summary["targets"] is not None and not isinstance(summary["targets"], str):
        summary["targets"] = json.dumps(summary["targets"])
    return summary


def handle_proposal_query(event: dict[str, Any], store: ProposalStore, *, account_id: str | None = None) -> dict[str, Any]:
    """``listStoryDrafts`` from AppSync: the story drafts, newest first, with only ``STORY_DRAFT_FIELDS``. Read only.

    The same caller check as :func:`handle_proposal_event`: an editor or admin, or an IAM principal of ``account_id`` (the function's own
    account) acting as an operator. An identity-pool user and a principal of any other account are refused. Answers a receipt-shaped
    object, never an exception.
    """
    identity = event.get("identity") or {}
    if staff_subject(identity) is None and operator_actor(identity, account_id) is None:
        return {**refused("not_staff", "Only editors, admins and operators of this account can list story drafts.").to_dict(), "drafts": []}
    rows = sorted(store.list_story_drafts(MAXIMUM_STORY_DRAFTS), key=lambda row: (row.get("createdAt") or "", row.get("id") or ""), reverse=True)
    return {"status": "ok", "id": None, "error": None, "message": None, "drafts": [story_draft_summary(row) for row in rows[:MAXIMUM_STORY_DRAFTS]]}
