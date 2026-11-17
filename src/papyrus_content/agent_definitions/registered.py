"""The registered copy of an agent definition on a site's Automation record (PPY-fba046).

The definition file in Git says what an agent is; the site's backend holds the registered copy: the definition's id, the registered version, the digest
and the definition itself. The runner and Today read that copy, never the file in Git at run time. The digest is of the effective definition (a core
definition with what the site added to it), in a canonical form, so field order and formatting never change it.

Registering is the one thing this module does. It writes the four ``definition*`` fields and ``updatedBy``/``updatedAt`` and nothing else: not ``enabled``,
not the trigger, not the adopted responsibility, and never the agent policy document, so a deploy cannot move a rung, a pause or a budget. The first
registration is version 1; a changed digest writes the version one higher; an unchanged digest writes nothing. Applying every definition by release,
creating missing Automation records and retiring removed definitions is the next slice (D2, PPY-df3e74); it calls ``register`` for each definition.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..automations import AutomationError, build_record, read_record, stored_payload
from .definition import Definition

DIGEST_PREFIX = "sha256:"


def digest(data: dict[str, Any]) -> str:
    """The digest of one effective definition: SHA-256 of its canonical JSON (sorted keys, no spaces)."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return DIGEST_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def register(client, automation_id: str, definition: Definition, *, actor: str, apply: bool, now: str | None = None) -> dict[str, Any]:
    """Record ``definition`` as the registered copy on the Automation ``automation_id``. A dry run (``apply`` False) writes nothing."""
    row = client.get_record("Automation", automation_id)
    if not row:
        raise AutomationError(f"automation {automation_id} does not exist; a definition is registered onto an Automation record that exists.")
    existing = read_record(row)
    adopted = existing.get("responsibility")
    if adopted and adopted != definition.responsibility:
        raise AutomationError(f"automation {automation_id} is adopted as {adopted}; the definition {definition.id} is for {definition.responsibility}. Nothing was changed.")
    new_digest = digest(definition.data)
    if existing.get("definitionDigest") == new_digest and existing.get("definitionId") == definition.id:
        action, version = "unchanged", existing["definitionVersion"]
    elif existing.get("definitionDigest") is None:
        action, version = "registered", 1
    else:
        action, version = "updated", existing["definitionVersion"] + 1
    result = {"automationId": automation_id, "definitionId": definition.id, "version": version, "digest": new_digest, "action": action, "applied": False}
    if action == "unchanged" or not apply:
        return result
    record = build_record({"id": automation_id, "definitionId": definition.id, "definitionVersion": version, "definitionDigest": new_digest,
                           "definition": definition.data}, existing=existing, actor=actor, now=now)
    client.update_record("Automation", stored_payload(record))
    return {**result, "applied": True}
