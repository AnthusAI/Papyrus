"""Moderation transitions for reader submissions, comments and readers.

Staff reach this through the ``moderateReader`` mutation (editors and admins only); an AI moderator reaches it through the
same :func:`apply_action`, marked ``by: "ai"``. Every change is one ``ModerationAction`` row written in the same DynamoDB
transaction as the change it records, so the log and the state cannot disagree:

* a **submission** is ``pending``, ``promoted`` or ``hidden``; a **comment** is ``visible``, ``hidden`` or ``deleted``;
  a **reader** is ``active``, ``limited`` or ``banned``;
* ``moderation`` is ``new`` (waiting in the queue) or ``approved`` (reviewed). A report sets it back to ``new``;
* every action is checked against the state it expects, so two moderators cannot overwrite each other (``target_changed``);
* ``undo`` restores the state the original action replaced. It is refused when the target has moved on since, when the
  action was already undone, and for ``promote`` (a draft item exists by then).

Nothing here knows a siteSubject or a person id: staff see ``readerId`` and nothing else about a reader.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

TARGET_SUBMISSION = "submission"
TARGET_COMMENT = "comment"
TARGET_READER = "reader"
TARGET_TYPES = (TARGET_SUBMISSION, TARGET_COMMENT, TARGET_READER)
APPROVE, HIDE, UNHIDE, BAN, UNBAN, LIMIT, PROMOTE, UNDO = "approve", "hide", "unhide", "ban", "unban", "limit", "promote", "undo"
ACTIONS = (APPROVE, HIDE, UNHIDE, BAN, UNBAN, LIMIT, PROMOTE, UNDO)
BY_HUMAN, BY_AI = "human", "ai"
MODERATION_NEW, MODERATION_APPROVED = "new", "approved"
SUBMISSION_ID = re.compile(r"sub-[0-9a-f]{24}")
COMMENT_ID = re.compile(r"cmt-[0-9a-f]{32}")
READER_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
ACTION_ID = re.compile(r"mod-[0-9a-f]{32}")
MAXIMUM_REASON = 500
STAFF_GROUPS = frozenset({"editor", "admin"})

_GROUP_SEPARATORS = re.compile(r"[\s,]+")


def claim_groups(value: Any) -> list[str]:
    """Copy of ``papyrus_content.staff_groups.claim_groups`` (this function ships without that package; a test keeps them equal)."""
    if isinstance(value, (list, tuple, set, frozenset)):
        raw = [item for item in value if isinstance(item, str)]
    elif isinstance(value, str):
        raw = _GROUP_SEPARATORS.split(value)
    else:
        return []
    cleaned = (item.strip().strip("\"'[](){}").strip() for item in raw)
    return [item for item in cleaned if item]


def has_editor_rights(groups: Any) -> bool:
    """``admin`` has every editor right: an admin who is not in the ``editor`` group is staff."""
    return any(group.lower() in STAFF_GROUPS for group in claim_groups(groups))
ITEM_ID_PREFIX = "item-"


@dataclass
class Plan:
    """What an action changes: the new field values, the values it expects to find, and the log row's from/to."""

    changes: dict[str, Any]
    expected: dict[str, Any]
    from_state: str
    to_state: str
    from_moderation: str | None = None
    to_moderation: str | None = None
    item: dict[str, Any] | None = None
    reason_text: str = ""


@dataclass
class Outcome:
    status: str  # "ok" or "refused"
    id: str | None = None
    error: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "id": self.id, "error": self.error, "message": self.message}


class ModerationStore(Protocol):
    def get_submission(self, submission_id: str) -> dict[str, Any] | None: ...

    def get_comment(self, comment_id: str) -> dict[str, Any] | None: ...

    def get_profile_by_reader(self, reader_id: str) -> dict[str, Any] | None: ...

    def get_action(self, action_id: str) -> dict[str, Any] | None: ...

    def transact_moderation(
        self, action: dict[str, Any], target_type: str, target_key: str, plan: Plan, *, undoes: str | None = None
    ) -> str: ...

    def close_reports(self, target: str, now_iso: str) -> int: ...


def refused(error: str, message: str) -> Outcome:
    return Outcome("refused", error=error, message=message)


def visible_state(target_type: str, row: dict[str, Any]) -> str:
    if target_type == TARGET_COMMENT:
        return "visible"
    return "promoted" if row.get("itemId") else "pending"


def target_type_of(target: str) -> str | None:
    if SUBMISSION_ID.fullmatch(target):
        return TARGET_SUBMISSION
    if COMMENT_ID.fullmatch(target):
        return TARGET_COMMENT
    if READER_ID.fullmatch(target):
        return TARGET_READER
    return None


def load_target(store: ModerationStore, target_type: str, target: str) -> tuple[dict[str, Any] | None, str]:
    """The target row and the key to update it by (a reader is stored by siteSubject, which only the function sees)."""
    if target_type == TARGET_SUBMISSION:
        row = store.get_submission(target)
        return row, target
    if target_type == TARGET_COMMENT:
        row = store.get_comment(target)
        return row, target
    row = store.get_profile_by_reader(target)
    return row, (row["id"] if row else target)


def content_plan(action: str, target_type: str, row: dict[str, Any]) -> Plan | Outcome:
    state, moderation = row.get("state"), row.get("moderation") or MODERATION_NEW
    if target_type == TARGET_COMMENT and state == "deleted":
        return refused("target_deleted", "The author deleted that comment.")
    restored = visible_state(target_type, row)
    if action == APPROVE:
        if moderation != MODERATION_NEW:
            return refused("already_reviewed", "That item was already reviewed.")
        to_state = restored if state == "hidden" else state
        return Plan({"state": to_state, "moderation": MODERATION_APPROVED}, {"state": state, "moderation": moderation}, state, to_state, moderation, MODERATION_APPROVED)
    if action == HIDE:
        if state == "hidden" and moderation == MODERATION_NEW:
            # A held item (pre-moderation) the moderator turns down: it stays hidden and leaves the queue.
            return Plan({"moderation": MODERATION_APPROVED}, {"state": state, "moderation": moderation}, state, state, moderation, MODERATION_APPROVED)
        if state == "hidden":
            return refused("already_hidden", "That item is already hidden.")
        return Plan({"state": "hidden", "moderation": MODERATION_APPROVED}, {"state": state, "moderation": moderation}, state, "hidden", moderation, MODERATION_APPROVED)
    if action == UNHIDE:
        if state != "hidden":
            return refused("not_hidden", "That item is not hidden.")
        return Plan({"state": restored, "moderation": MODERATION_APPROVED}, {"state": state, "moderation": moderation}, state, restored, moderation, MODERATION_APPROVED)
    return refused("invalid_action", f"{action} does not apply to a {target_type}.")


def reader_plan(action: str, row: dict[str, Any]) -> Plan | Outcome:
    state = row.get("state", "active")
    if action == BAN:
        if state == "banned":
            return refused("already_banned", "That reader is already banned.")
        return Plan({"state": "banned"}, {"state": state}, state, "banned")
    if action == LIMIT:
        if state != "active":
            return refused("not_active", "Only an active reader can be limited.")
        return Plan({"state": "limited"}, {"state": state}, state, "limited")
    if action == UNBAN:
        if state == "active":
            return refused("not_restricted", "That reader is not banned or limited.")
        return Plan({"state": "active"}, {"state": state}, state, "active")
    return refused("invalid_action", f"{action} does not apply to a reader.")


def draft_item_record(submission: dict[str, Any], *, actor: str, now_iso: str, item_type: str, section: str) -> dict[str, Any]:
    """The draft ``Item`` (version 1, stage ``idea``) an editor promotes a submission into; the editor then works and publishes it as usual."""
    lineage = ITEM_ID_PREFIX + uuid.uuid4().hex[:12]
    title = submission["title"]
    fingerprint = hashlib.sha256(json.dumps([lineage, title], separators=(",", ":")).encode("utf-8")).hexdigest()[:8]
    metadata = {
        "createdFrom": "reader_submission",
        "submissionId": submission["id"],
        "sourceUrl": submission["canonicalUrl"],
        "kind": submission.get("kind"),
        "submittedBy": submission["readerId"],
    }
    record: dict[str, Any] = {
        "id": f"{lineage}-v1",
        "lineageId": lineage,
        "versionNumber": 1,
        "versionState": "draft",
        "versionCreatedAt": now_iso,
        "versionCreatedBy": actor,
        "changeReason": "reader-submission-promote",
        "type": item_type,
        "stage": "idea",
        "status": "draft",
        "typeStatus": f"{item_type}#draft",
        "slug": f"draft-{section}-{fingerprint}",
        "section": section,
        "sectionStatus": f"{section}#draft",
        "title": title,
        "headline": title,
        "sortTitle": title,
        "metadata": json.dumps(metadata, separators=(",", ":")),
        "updatedAt": now_iso,
        "__typename": "Item",
        "createdAt": now_iso,
    }
    if submission.get("note"):
        record["deck"] = submission["note"]
    record["contentHash"] = hashlib.sha256(json.dumps([record["type"], record["status"], record["slug"], record["section"], title], separators=(",", ":")).encode("utf-8")).hexdigest()
    return record


def promote_plan(row: dict[str, Any], *, actor: str, now_iso: str, item_type: str, section: str) -> Plan | Outcome:
    state, moderation = row.get("state"), row.get("moderation") or MODERATION_NEW
    if state != "pending":
        return refused("not_pending", "Only a pending submission can be promoted.")
    item = draft_item_record(row, actor=actor, now_iso=now_iso, item_type=item_type, section=section)
    return Plan(
        {"state": "promoted", "moderation": MODERATION_APPROVED, "itemId": item["lineageId"]},
        {"state": state, "moderation": moderation},
        state,
        "promoted",
        moderation,
        MODERATION_APPROVED,
        item=item,
    )


def undo_plan(store: ModerationStore, original: dict[str, Any], target_type: str, row: dict[str, Any]) -> Plan | Outcome:
    if original.get("undoneBy"):
        return refused("already_undone", "That action was already undone.")
    if original["action"] == PROMOTE:
        return refused("not_undoable", "A promotion cannot be undone; the draft item exists. Hide the submission instead.")
    state, moderation = row.get("state", "active"), row.get("moderation")
    if state != original["toState"] or (original.get("toModeration") and moderation != original["toModeration"]):
        return refused("target_changed", "That item changed after the action, so it cannot be undone.")
    changes: dict[str, Any] = {"state": original["fromState"]}
    expected: dict[str, Any] = {"state": state}
    if original.get("fromModeration"):
        changes["moderation"] = original["fromModeration"]
        expected["moderation"] = moderation
    return Plan(changes, expected, state, original["fromState"], moderation, original.get("fromModeration"))


def clean_reason(value: Any) -> tuple[str, Outcome | None]:
    if value is None:
        return "", None
    if not isinstance(value, str) or len(value.strip()) > MAXIMUM_REASON or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
        return "", refused("invalid_reason", f"A reason is plain text of at most {MAXIMUM_REASON} characters.")
    return value.strip(), None


@dataclass
class ModerationSettings:
    item_type: str = "brief"
    section: str = "unsectioned"
    extra: dict[str, Any] = field(default_factory=dict)


def apply_action(
    store: ModerationStore,
    *,
    action: Any,
    target_type: Any,
    target: Any,
    reason: Any,
    undo_of: Any,
    actor_sub: str,
    by: str,
    now_iso: str,
    settings: ModerationSettings,
) -> Outcome:
    """Validates an action, plans the transition and writes it with its log row in one transaction."""
    if action not in ACTIONS:
        return refused("invalid_action", "Unknown action.")
    if target_type not in TARGET_TYPES:
        return refused("invalid_target", "Unknown target type.")
    if not isinstance(target, str) or target_type_of(target) != target_type:
        return refused("invalid_target", "That is not a valid target.")
    reason_text, problem = clean_reason(reason)
    if problem:
        return problem
    row, key = load_target(store, target_type, target)
    if row is None:
        return refused("unknown_target", "That target does not exist.")
    undoes = None
    if action == UNDO:
        if not isinstance(undo_of, str) or not ACTION_ID.fullmatch(undo_of):
            return refused("invalid_undo", "Send the id of the action to undo.")
        original = store.get_action(undo_of)
        if original is None or original.get("target") != target or original.get("targetType") != target_type:
            return refused("invalid_undo", "That action does not belong to this target.")
        plan = undo_plan(store, original, target_type, row)
        undoes = undo_of
    elif target_type == TARGET_READER:
        plan = reader_plan(action, row)
    elif action == PROMOTE:
        if target_type != TARGET_SUBMISSION:
            return refused("invalid_action", "Only a submission can be promoted.")
        plan = promote_plan(row, actor=f"user:{actor_sub}" if by == BY_HUMAN else by, now_iso=now_iso, item_type=settings.item_type, section=settings.section)
    else:
        plan = content_plan(action, target_type, row)
    if isinstance(plan, Outcome):
        return plan
    record: dict[str, Any] = {
        "id": "mod-" + uuid.uuid4().hex,
        "by": by,
        "actorSub": actor_sub,
        "action": action,
        "targetType": target_type,
        "target": target,
        "reason": reason_text,
        "fromState": plan.from_state,
        "toState": plan.to_state,
        "at": now_iso,
        "createdAt": now_iso,
    }
    if plan.from_moderation:
        record["fromModeration"] = plan.from_moderation
    if plan.to_moderation:
        record["toModeration"] = plan.to_moderation
    if undoes:
        record["undoOf"] = undoes
    result = store.transact_moderation(record, target_type, key, plan, undoes=undoes)
    if result == "target_changed":
        return refused("target_changed", "That item changed while you were looking at it. Reload and try again.")
    if result == "already_undone":
        return refused("already_undone", "That action was already undone.")
    if target_type != TARGET_READER and action in (APPROVE, HIDE, PROMOTE):
        store.close_reports(target, now_iso)
    return Outcome("ok", id=record["id"])
