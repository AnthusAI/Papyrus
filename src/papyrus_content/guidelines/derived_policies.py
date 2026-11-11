"""The editorial checks drawn from writing guidelines (PPY-457028).

Saving writing guidelines keeps the Humanus policies drawn from them in step, so the writer and the checker read the same data. The site document gives
publication-scope policies and a section document gives desk-scope policies for that section. A drawn policy is told apart by its source,
``writing-guidelines:<slug>:v<N>``; only policies with that source for this very document are ever created, updated or disabled. A starter-pack policy, a
hand-written one, and one an admin edited in the Editorial checks panel (which sets its source to ``custom``) are never touched.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import humanus

from papyrus_content.editorial_checks import PUBLICATION_SCOPE, policy_record_id, record_from_policy
from papyrus_content.editorial_policy_pack import _content

from .document import slug_for

SOURCE_PREFIX = "writing-guidelines:"
WRITING = "writing"
STAND_IN_PUBLICATION_KEY = "guidelines"


def source_for(section: str | None, version_number: int) -> str:
    return f"{SOURCE_PREFIX}{slug_for(WRITING, section)}:v{version_number}"


def _owned_prefix(section: str | None) -> str:
    return f"{SOURCE_PREFIX}{slug_for(WRITING, section)}:v"


def scope_for(section: str | None) -> str:
    return section if section else PUBLICATION_SCOPE


def drawn_policies(document: dict) -> list[dict]:
    """The Humanus policies the document yields (a section document has no publication key, so a stand-in is given for the reader)."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "writing-guidelines.json"
        path.write_text(json.dumps({"publicationKey": STAND_IN_PUBLICATION_KEY, **document}), encoding="utf-8")
        return humanus.policy_pack_from_style_profile(path)["policies"]


def plan_derived_policies(store, document: dict, section: str | None, version_number: int) -> list[dict]:
    """One step per policy: create, update, disable, unchanged, or skipped (a policy this document does not own sits under that key)."""
    scope, source, prefix = scope_for(section), source_for(section, version_number), _owned_prefix(section)
    existing = {row["id"]: row for row in store.list_policies()}
    steps: list[dict] = []
    wanted: set[str] = set()
    for policy in drawn_policies(document):
        record = record_from_policy(policy, scope=scope, source=source)
        wanted.add(record["id"])
        current = existing.get(record["id"])
        if current is None:
            steps.append({"action": "create", "key": policy["id"], "scope": scope, "record": record})
        elif not str(current.get("source") or "").startswith(prefix):
            steps.append({"action": "skipped", "key": policy["id"], "scope": scope, "reason": "not drawn from these guidelines"})
        elif _content(current) == _content(record):
            steps.append({"action": "unchanged", "key": policy["id"], "scope": scope})
        else:
            version = int(current.get("version") or 1) + 1
            steps.append({"action": "update", "key": policy["id"], "scope": scope, "record": {**record, "version": version}})
    for record_id, current in sorted(existing.items()):
        if record_id in wanted or current.get("scope") != scope or not str(current.get("source") or "").startswith(prefix) or not current.get("enabled", True):
            continue
        version = int(current.get("version") or 1) + 1
        steps.append({"action": "disable", "key": current["policyKey"], "scope": scope, "record": {**current, "enabled": False, "version": version}})
    return steps


def apply_derived_plan(store, steps: list[dict]) -> None:
    for step in steps:
        if step["action"] == "create":
            store.create_policy(step["record"])
        elif step["action"] in ("update", "disable"):
            store.update_policy(step["record"])


def describe_plan(steps: list[dict]) -> list[dict]:
    return [{"action": step["action"], "policy": step["key"], "scope": step["scope"], **({"reason": step["reason"]} if "reason" in step else {})} for step in steps]


def changed_steps(steps: list[dict]) -> list[dict]:
    return [step for step in steps if step["action"] in ("create", "update", "disable")]


__all__ = ["apply_derived_plan", "changed_steps", "describe_plan", "plan_derived_policies", "policy_record_id", "source_for"]
