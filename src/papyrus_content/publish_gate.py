"""The per-site publish approval gate (PPY-8c5438).

A site decides whether anything may publish without a person's approval. The setting is site data: one row of
``EditorialCheckSettings`` with the id ``publish-gate`` (editors read it, only admins and operators write it), so a change needs no
deploy and no repository edit.

* ``not_required`` (the default, also when nothing is stored): publishing works as it always did.
* ``required``: ``publish_item`` refuses unless a person approved this version of the item. A person is approved by acting:
  an editor pressing Publish (or Save on a live article) in the console passes ``approved_by`` and is never blocked by their own gate.
  Every other caller (the CLI, an automation or procedure, the import and wiki commands, a Lambda without a signed-in editor) raises
  or reuses one ``hard_gate`` review request about that version and does not publish. When a person approves the request, the
  caller publishes the next time it runs; nothing waits and nothing publishes by itself at the moment of approval.

A version is the item record plus its content hash, so editing the text asks again; an approval never covers new words.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from . import review_requests as rr

SETTINGS_MODEL = "EditorialCheckSettings"
SETTINGS_ID = "publish-gate"
REQUIRED = "required"
NOT_REQUIRED = "not_required"
APPROVAL_VALUES = (REQUIRED, NOT_REQUIRED)
DEFAULT_APPROVAL = NOT_REQUIRED
RAISED_BY = "publish-gate"
APPROVAL_REQUIRED = "approval-required"
APPROVAL_REJECTED = "approval-rejected"


class PublishGateError(ValueError):
    """The setting was asked to take a value it does not have."""


def read_settings(client) -> dict[str, Any]:
    """The stored gate setting with defaults. Nothing stored means ``not_required``."""
    row = client.get_record(SETTINGS_MODEL, SETTINGS_ID)
    stored = row.get("settings") if row else None
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except ValueError:
            stored = {}
    stored = stored if isinstance(stored, dict) else {}
    approval = stored.get("approval")
    return {
        "approval": approval if approval in APPROVAL_VALUES else DEFAULT_APPROVAL,
        "updatedBy": stored.get("updatedBy"),
        "updatedAt": stored.get("updatedAt"),
        "stored": row is not None,
    }


def publish_approval(client) -> str:
    return read_settings(client)["approval"]


def set_publish_approval(client, approval: str, *, by: str, now: str | None = None) -> dict[str, Any]:
    if approval not in APPROVAL_VALUES:
        raise PublishGateError(f"approval must be one of {', '.join(APPROVAL_VALUES)}.")
    at = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    value = {"approval": approval, "updatedBy": by, "updatedAt": at}
    client.upsert(SETTINGS_MODEL, {"id": SETTINGS_ID, "settings": json.dumps(value)})
    return {**value, "stored": True}


def request_prefix(item: dict[str, Any]) -> str:
    """The id every review request about this version starts with: the record id and its content hash."""
    digest = hashlib.sha256(f"{item['id']}\n{item.get('contentHash') or ''}".encode("utf-8")).hexdigest()[:20]
    return f"rr-publish-{digest}"


def _requests_for(client, prefix: str) -> list[dict[str, Any]]:
    rows = [row for row in client.list_records("ReviewRequest") if row.get("id") == prefix or str(row.get("id", "")).startswith(prefix + "-")]
    return [rr.read_review(row) for row in rows]


def _title(item: dict[str, Any]) -> str:
    return re.sub(r"\s+", " ", str(item.get("title") or item.get("headline") or item.get("slug") or item["id"])).strip()[:160]


def ensure_publish_approval(client, item: dict[str, Any], *, approved_by: str | None, actor: str) -> None:
    """Raise ``PublishError`` unless this site allows publishing this version. Does nothing when the gate is off."""
    from .publishing import PublishError

    if publish_approval(client) != REQUIRED:
        return
    prefix = request_prefix(item)
    requests = _requests_for(client, prefix)
    if approved_by:
        for request in requests:
            if request["state"] == "open":  # the person's own publish settles the question the gate asked
                rr.answer_review(client, request["id"], decision="approve", by=approved_by, feedback="Published by this person.")
        return
    if any(request["outcome"] == "approved" for request in requests):
        return
    pending = next((request for request in requests if request["state"] == "open"), None)
    if pending is not None:
        raise PublishError(
            APPROVAL_REQUIRED,
            f"This site needs a person's approval to publish. Review request {pending['id']} is waiting in the Notification Center; "
            "once it is approved, publish again.",
        )
    declined = next((request for request in requests if request["outcome"] in ("rejected", "feedback")), None)
    if declined is not None:
        raise PublishError(
            APPROVAL_REJECTED,
            f"A person did not approve publishing this version (review request {declined['id']}). Change the text to ask again.",
        )
    lineage_id = item.get("lineageId") or item["id"]
    request_id = prefix if not requests else f"{prefix}-{len(requests) + 1}"  # earlier requests were withdrawn
    created = rr.raise_review(
        client,
        request_id=request_id,
        subject={"type": "story", "id": lineage_id},
        mode="hard_gate",
        reason=f"Approve publishing: {_title(item)}",
        ask=f"Publishing needs a person's approval on this site. Requested by {actor}. Approve to allow this version to publish; it does not publish by itself.",
        raised_by=RAISED_BY,
        links=[{"type": "story", "id": item["id"], "label": f"version {item.get('versionNumber') or 1}"}],
    )
    raise PublishError(
        APPROVAL_REQUIRED,
        f"This site needs a person's approval to publish. Review request {created['id']} was raised in the Notification Center; "
        "once it is approved, publish again.",
    )


def run_command(command: str, flags: list[str]) -> None:
    """``papyrus ops content publish-gate show`` and ``set --approval required|not_required [--dry-run] [--json]``."""
    from .graphql_authoring import create_authoring_client
    from .options import normalize_string, parse_options, resolve_mutation_apply

    options = parse_options(flags)
    as_json = bool(options.get("json"))
    client, claims = create_authoring_client()
    if command == "show":
        settings = read_settings(client)
        print(json.dumps({"ok": True, **settings}, indent=2) if as_json else
              f"publish-gate\tapproval={settings['approval']}\t{'stored' if settings['stored'] else 'default (nothing stored)'}"
              + (f"\tby {settings['updatedBy']} at {settings['updatedAt']}" if settings["updatedBy"] else ""))
        return
    if command != "set":
        raise ValueError("Usage: papyrus ops content publish-gate show | set --approval required|not_required [--dry-run] [--json]")
    apply = resolve_mutation_apply(options, "content publish-gate set")
    approval = normalize_string(options.get("approval"))
    if approval not in APPROVAL_VALUES:
        raise ValueError(f"--approval must be one of {', '.join(APPROVAL_VALUES)}.")
    before = read_settings(client)["approval"]
    by = normalize_string((claims or {}).get("sub")) or "papyrus-cli"
    if apply:
        set_publish_approval(client, approval, by=by)
    payload = {"ok": True, "dryRun": not apply, "before": before, "approval": approval, "changed": before != approval}
    print(json.dumps(payload, indent=2) if as_json else
          f"publish-gate\tapproval {before} -> {approval}\t{'written' if apply else 'dry run (nothing written)'}")
