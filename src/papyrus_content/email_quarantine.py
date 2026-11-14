"""Quarantined email submissions: one recorded editor decision per message.

A message the receiver cannot accept on its own (failed authentication signals, or a
refusal from the earlier authentication gate) is held privately as `pending_review`.
An editor or admin of a destination publication either *accepts* it (release: the
receiver then queues it exactly as if it had been accepted) or *rejects* it (discard).
Authentication signals never grant a role or choose a destination; only this recorded
human decision moves a held message forward.

The Monitoring view writes one append-only decision row (`EMAILACTION#<digest>`, first
decision wins). The receiver is the only writer of the receipt: it applies the decision
on its one-minute schedule. This module holds the vocabulary shared by both sides and
the view-side request; it imports nothing heavy.
"""
from __future__ import annotations

from datetime import UTC, datetime
import re

ACTION_PREFIX = "EMAILACTION#"
DECISIONS = ("release", "discard")
REASON_MAX_CHARACTERS = 500
RECEIPT_ID = re.compile(r"^EMAIL#[a-f0-9]{64}$")
QUARANTINE_STATUS = "pending_review"
#: Receipt refusals from the earlier authentication/membership gate. They never parsed the
#: MIME, so they have no stored text or links until the receiver quarantines them.
LEGACY_REJECTION_CODES = frozenset({"sender_authentication_failed", "sender_not_active_editor"})


def action_key(receipt_id: str) -> str:
    return ACTION_PREFIX + receipt_id.removeprefix("EMAIL#")


def clean_reason(value) -> str:
    """Optional free text from the editor: plain, single paragraph, bounded."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("reason_invalid")
    text = " ".join("".join(c if c.isprintable() or c in "\n\t" else " " for c in value).split())
    return text[:REASON_MAX_CHARACTERS]


def quarantine_state(receipt: dict, action: dict | None, *, now: float) -> str | None:
    """The precise state an editor sees, or None when the receipt was never quarantined."""
    status = receipt.get("status")
    if status == "discarded":
        return "discarded"
    if receipt.get("releasedAt"):
        return "release_failed" if status == "failed" else "released"
    if status != QUARANTINE_STATUS:
        return None
    ttl = receipt.get("ttl")
    if isinstance(ttl, int) and not isinstance(ttl, bool) and ttl <= now:
        return "expired"
    if action:
        if action.get("outcome") and action["outcome"] not in {"released", "discarded"}:
            return "decision_failed"
        return "release_requested" if action.get("decision") == "release" else "discard_requested"
    return "quarantined"


def quarantine_summary(receipt: dict, action: dict | None, *, now: float) -> dict | None:
    state = quarantine_state(receipt, action, now=now)
    if state is None:
        return None
    decision = receipt.get("decision") if isinstance(receipt.get("decision"), dict) else action
    shown = None
    if isinstance(decision, dict) and decision.get("decision") in DECISIONS:
        shown = {"action": "accept" if decision["decision"] == "release" else "reject",
                 "by": str(decision.get("actorEmail") or decision.get("actor") or "")[:254],
                 "at": decision.get("requestedAt"), "reason": str(decision.get("reason") or "")[:REASON_MAX_CHARACTERS],
                 "viaGroup": bool(decision.get("groupFingerprint"))}
    failure = action.get("outcome") if action and action.get("outcome") not in {None, "released", "discarded"} else None
    return {"state": state, "decision": shown, "failure": failure}


def correct_reason(store, row: dict, text: str, supplied, *, now: float) -> dict:
    """The same decision asked for again with a different reason: the recorded reason is corrected, once, until the receiver has applied it.

    The editor may add or change the explanation after the label ("any order"). Nothing else on the row changes. A decision the receiver has
    already applied (it carries ``outcome``) is left as it is, and the summary shows the reason the receipt kept. A request that supplies no
    reason at all (``None``) never changes anything, so a plain repeat click stays a no-op.
    """
    if supplied is None or row.get("outcome") or text == str(row.get("reason") or ""):
        return row
    edited = {**row, "reason": text, "reasonEditedAt": datetime.fromtimestamp(now, UTC).isoformat().replace("+00:00", "Z")}
    return edited if store.replace_email_decision(edited) else row


def request_decision(store, *, receipt: dict, receipt_id: str, decision: str, reason, actor: str,
                     actor_email: str | None, publication_id: str, now: float | None = None) -> dict:
    """Record the editor's decision for one held message; idempotent, first decision wins.

    `store` is the Monitoring view store of the email partition. The caller has already
    authenticated the editor and checked the receipt belongs to the editor's publication.
    """
    if decision not in DECISIONS:
        return {"error": "bad_request"}
    try:
        text = clean_reason(reason)
    except ValueError:
        return {"error": "bad_request"}
    now = datetime.now(UTC).timestamp() if now is None else now
    existing = store.get(action_key(receipt_id))
    if existing:
        if existing.get("decision") == decision:
            corrected = correct_reason(store, existing, text, reason, now=now)
            if corrected is not existing and existing.get("groupFingerprint"):
                from .email_fingerprint import group_key
                group = store.get(group_key(existing["groupFingerprint"]))
                if group:
                    correct_reason(store, group, text, reason, now=now)  # the group's record says what its copies say
            existing = corrected
            return {"ok": True, "already": True, "quarantine": quarantine_summary(receipt, existing, now=now)}
        return {"error": "already_decided", "quarantine": quarantine_summary(receipt, existing, now=now)}
    state = quarantine_state(receipt, None, now=now)
    if state != "quarantined":
        return {"error": "expired" if state == "expired" else "not_quarantined"}
    requested = datetime.fromtimestamp(now, UTC).isoformat().replace("+00:00", "Z")
    digest = receipt_id.removeprefix("EMAIL#")
    diagnostics = receipt.get("sesDiagnostics") if isinstance(receipt.get("sesDiagnostics"), dict) else {}
    item = {"sk": action_key(receipt_id), "receiptId": receipt_id, "decision": decision, "reason": text,
            "actor": actor, "publicationId": publication_id, "requestedAt": requested,
            "verdicts": dict(diagnostics.get("verdicts") or {}), "ttl": receipt.get("ttl"),
            "gsi1pk": f"EMAIL_ACTION#{store.pk.removeprefix('MONITOR#')}", "gsi1sk": f"{requested}#{digest}"}
    if actor_email:
        item["actorEmail"] = actor_email[:254]
    if not isinstance(item["ttl"], int) or isinstance(item["ttl"], bool):
        del item["ttl"]
    if store.put_email_decision(item):
        return {"ok": True, "already": False, "quarantine": quarantine_summary(receipt, item, now=now)}
    # Lost a race with another click or retry: report what is now recorded.
    recorded = store.get(action_key(receipt_id)) or {}
    if recorded.get("decision") == decision:
        return {"ok": True, "already": True, "quarantine": quarantine_summary(receipt, recorded, now=now)}
    return {"error": "already_decided", "quarantine": quarantine_summary(receipt, recorded, now=now)}


def _copy_action(copy_id: str, group: dict, *, receipt: dict, store_monitor_id: str) -> dict:
    """One copy's own decision row, recorded from a group decision (actor, time and reason are the group's)."""
    diagnostics = receipt.get("sesDiagnostics") if isinstance(receipt.get("sesDiagnostics"), dict) else {}
    digest = copy_id.removeprefix("EMAIL#")
    item = {"sk": action_key(copy_id), "receiptId": copy_id, "decision": group["decision"],
            "reason": group.get("reason", ""), "actor": group["actor"], "publicationId": group["publicationId"],
            "requestedAt": group["requestedAt"], "groupFingerprint": group["fingerprint"],
            "verdicts": dict(diagnostics.get("verdicts") or {}), "ttl": receipt.get("ttl"),
            "gsi1pk": f"EMAIL_ACTION#{store_monitor_id}", "gsi1sk": f"{group['requestedAt']}#{digest}"}
    if group.get("actorEmail"):
        item["actorEmail"] = group["actorEmail"]
    if not isinstance(item["ttl"], int) or isinstance(item["ttl"], bool):
        del item["ttl"]
    return item


def inherit_group_decision(store, monitor_id: str, group: dict, receipt: dict) -> None:
    """A copy that arrives after its group was decided takes that decision; the editor is never asked again."""
    store.put(monitor_id, _copy_action(receipt["sk"], group, receipt=receipt, store_monitor_id=monitor_id))


def request_group_decision(store, *, copies: list[dict], fingerprint: str, decision: str, reason, actor: str,
                           actor_email: str | None, publication_id: str, now: float | None = None) -> dict:
    """One decision for every copy of the same email. First group decision wins.

    ``copies`` are the group's receipts (the caller has already checked each belongs to the
    editor's publication). Each copy that is still held and undecided gets its own decision row
    that references the group decision; a copy already decided keeps its decision.
    """
    from .email_fingerprint import group_key

    if decision not in DECISIONS:
        return {"error": "bad_request"}
    try:
        text = clean_reason(reason)
    except ValueError:
        return {"error": "bad_request"}
    now = datetime.now(UTC).timestamp() if now is None else now
    shown = copies[0]
    monitor_id = store.pk.removeprefix("MONITOR#")
    actions = {copy["sk"]: store.get(action_key(copy["sk"])) for copy in copies}
    pending = [copy for copy in copies if quarantine_state(copy, actions[copy["sk"]], now=now) == "quarantined"]
    group = store.get(group_key(fingerprint))
    created = False
    if group is None:
        if not pending:
            states = {quarantine_state(copy, actions[copy["sk"]], now=now) for copy in copies}
            return {"error": "expired" if "expired" in states else "not_quarantined"}
        requested = datetime.fromtimestamp(now, UTC).isoformat().replace("+00:00", "Z")
        ttl = max((copy.get("ttl") for copy in copies if isinstance(copy.get("ttl"), int)), default=None)
        group = {"sk": group_key(fingerprint), "fingerprint": fingerprint, "decision": decision, "reason": text,
                 "actor": actor, "publicationId": publication_id, "requestedAt": requested,
                 "copyCount": len(copies)}
        if ttl is not None and not isinstance(ttl, bool):
            group["ttl"] = ttl
        if actor_email:
            group["actorEmail"] = actor_email[:254]
        created = store.put_email_decision(group)
        if not created:
            group = store.get(group_key(fingerprint)) or group  # lost a race: report what is recorded
    if group.get("decision") != decision:
        return {"error": "already_decided", "quarantine": quarantine_summary(shown, group, now=now)}
    if not created:
        # The same group decision again: a corrected reason reaches the group and every copy that has not been applied yet.
        corrected = correct_reason(store, group, text, reason, now=now)
        if corrected is not group:
            group = corrected
            for copy in copies:
                action = actions.get(copy["sk"])
                if action and action.get("groupFingerprint") == fingerprint:
                    correct_reason(store, action, text, reason, now=now)
    # Every held copy without a decision of its own takes the group decision. Idempotent, so a retry
    # completes what an interrupted request left undone; a copy already decided keeps its decision.
    for copy in pending:
        store.put_email_decision(_copy_action(copy["sk"], group, receipt=copy, store_monitor_id=monitor_id))
    return {"ok": True, "already": not created, "decidedCopies": len(pending),
            "quarantine": quarantine_summary(shown, group, now=now)}
