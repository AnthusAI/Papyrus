"""The editorial checks drawn from writing guidelines (PPY-457028).

Saving writing guidelines keeps the Humanus policies drawn from them in step, so the writer and the checker read the same data. The site document gives
publication-scope policies and a section document gives desk-scope policies for that section. A drawn policy is told apart by its source,
``writing-guidelines:<slug>:v<N>``; only policies with that source for this very document are ever created, updated or disabled. A starter-pack policy, a
hand-written one, and one an admin edited in the Editorial checks panel (which sets its source to ``custom``) are never touched.

Each drawn policy is written for one language (PPY-d0132d). The guidelines every language shares are written in the site's primary language, so their
words to avoid become primary-language policies; a language overlay (``language: zh-Hans``) gives policies for that language only. English phrase rules
never run on Chinese text, and the Chinese overlay's never on English.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .document import slug_for

PUBLICATION_SCOPE = "publication"
SOURCE_PREFIX = "writing-guidelines:"
WRITING = "writing"
STAND_IN_PUBLICATION_KEY = "guidelines"


def source_for(section: str | None, version_number: int, language: str | None = None) -> str:
    return f"{SOURCE_PREFIX}{slug_for(WRITING, section, language)}:v{version_number}"


def _owned_prefix(section: str | None, language: str | None = None) -> str:
    return f"{SOURCE_PREFIX}{slug_for(WRITING, section, language)}:v"


def drawn_language(store, language: str | None) -> str:
    """The language a document's policies are written for: the overlay's, or for the document every language shares, the site's primary language."""
    if language:
        return language
    from papyrus_content.editorial_checks import settings_from
    from papyrus_content.editorial_languages import primary_language

    return primary_language(settings_from(store))


def scope_for(section: str | None) -> str:
    return section if section else PUBLICATION_SCOPE


def drawn_policies(document: dict) -> list[dict]:
    """The Humanus policies the document yields (a section document has no publication key, so a stand-in is given for the reader)."""
    import humanus

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "writing-guidelines.json"
        path.write_text(json.dumps({"publicationKey": STAND_IN_PUBLICATION_KEY, **document}), encoding="utf-8")
        return humanus.policy_pack_from_style_profile(path)["policies"]


def plan_derived_policies(store, document: dict, section: str | None, version_number: int, language: str | None = None) -> list[dict]:
    """One step per policy: create, update, disable, unchanged, or skipped (a policy this document does not own sits under that key).

    ``language`` names the language overlay the document is (None for the guidelines every language shares)."""
    from papyrus_content.editorial_checks import policy_identity, record_from_policy
    from papyrus_content.editorial_policy_pack import _content

    scope, source, prefix = scope_for(section), source_for(section, version_number, language), _owned_prefix(section, language)
    written_for = drawn_language(store, language)
    rows = store.list_policies()
    existing = {policy_identity(row): row for row in rows}
    steps: list[dict] = []
    wanted: set[str] = set()
    for policy in drawn_policies(document):
        record = record_from_policy(policy, scope=scope, language=written_for, source=source)
        current = existing.get(policy_identity(record))
        if current is not None:
            record["id"] = current["id"]   # an older record keeps its id
        wanted.add(record["id"])
        if current is None:
            steps.append({"action": "create", "key": policy["id"], "scope": scope, "record": record})
        elif not str(current.get("source") or "").startswith(prefix):
            steps.append({"action": "skipped", "key": policy["id"], "scope": scope, "reason": "not drawn from these guidelines"})
        elif _content(current) == _content(record):
            steps.append({"action": "unchanged", "key": policy["id"], "scope": scope})
        else:
            version = int(current.get("version") or 1) + 1
            steps.append({"action": "update", "key": policy["id"], "scope": scope, "record": {**record, "version": version}})
    for current in sorted(rows, key=lambda row: row["id"]):
        record_id = current["id"]
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


__all__ = ["apply_derived_plan", "changed_steps", "describe_plan", "plan_derived_policies", "source_for"]
