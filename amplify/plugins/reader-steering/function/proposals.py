"""The proposal record: what may be filed, which state changes are allowed, and who may make them.

A proposal is a change to the map written down where readers can see it: a story draft, a new concept, a rename, a merge,
a split, a new column or an element symbol. It is filed by AI (a reader proposer is part of the record but has no route yet)
and steered by votes; an editor decides. Staff reach this through the ``fileProposal`` and ``transitionProposal``
mutations (editors and admins only; the function checks the groups again). Every state change is appended to the proposal's
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

MUTATIONS = ("fileProposal", "transitionProposal")
PROPOSER_AI = "ai"
STAFF_GROUPS = frozenset({"editor", "admin"})
PROPOSAL_ID = re.compile(r"prop-[0-9a-f]{32}")
TARGET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}")
MAXIMUM_TITLE = 200
MAXIMUM_SUMMARY = 300
MAXIMUM_BODY = 50_000
MAXIMUM_REASON = 500
MAXIMUM_EVIDENCE_SOURCE = 200
MAXIMUM_EVIDENCE_SIGNALS = 1_000_000


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

    def change_proposal(self, proposal_id: str, changes: dict[str, Any], expected_state: str, now_iso: str) -> bool: ...


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


def clean_evidence(raw: Any) -> dict[str, Any] | None | Outcome:
    parsed = parse_json(raw) if raw is not None else None
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        return refused("invalid_evidence", "evidence must be {signals, source}.")
    signals, source = parsed.get("signals"), parsed.get("source")
    if not isinstance(signals, int) or isinstance(signals, bool) or not 0 <= signals <= MAXIMUM_EVIDENCE_SIGNALS:
        return refused("invalid_evidence", "evidence.signals must be a whole number of signals.")
    if source is not None and clean_text(source, MAXIMUM_EVIDENCE_SOURCE) is None:
        return refused("invalid_evidence", "evidence.source must be short text.")
    return {"signals": signals, "source": source.strip() if isinstance(source, str) else None}


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


def transition_plan(row: dict[str, Any], to_state: Any, reason: Any, *, actor_sub: str, now_iso: str, result: Any = None) -> dict[str, Any] | Outcome:
    """The changes that move ``row`` to ``to_state``, or why it may not move."""
    state = row.get("state")
    if to_state not in STATES:
        return refused("invalid_state", f"state must be one of {', '.join(STATES)}.")
    if to_state not in TRANSITIONS.get(state, ()):
        return refused("transition_not_allowed", f"A proposal in {state} cannot move to {to_state}.")
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
    entry = {"from": state, "to": to_state, "by": "staff", "actor": actor_sub, "reason": text, "at": now_iso}
    if result is not None:
        entry["result"] = result
    history = [*(parse_json(row.get("history")) or []), entry]
    return {"state": to_state, "history": json.dumps(history)}


def apply_transition(store: ProposalStore, *, proposal_id: Any, to_state: Any, reason: Any, actor_sub: str, now_iso: str, result: Any = None) -> Outcome:
    if not isinstance(proposal_id, str) or not PROPOSAL_ID.fullmatch(proposal_id):
        return refused("invalid_proposal", "That is not a proposal id.")
    row = store.get_proposal(proposal_id)
    if row is None:
        return refused("not_found", "There is no such proposal.")
    plan = transition_plan(row, to_state, reason, actor_sub=actor_sub, now_iso=now_iso, result=result)
    if isinstance(plan, Outcome):
        return plan
    if not store.change_proposal(proposal_id, plan, row["state"], now_iso):
        return refused("target_changed", "Someone else changed that proposal first.")
    return Outcome("ok", id=proposal_id)


def handle_proposal_event(event: dict[str, Any], store: ProposalStore, *, now_iso: str) -> dict[str, Any]:
    """``fileProposal`` or ``transitionProposal`` from AppSync. Answers a receipt, never an exception."""
    actor = staff_subject(event.get("identity") or {})
    if actor is None:
        return refused("not_staff", "Only editors and admins can file or decide proposals.").to_dict()
    arguments = event.get("arguments") or {}
    field = (event.get("info") or {}).get("fieldName")
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
    ).to_dict()
