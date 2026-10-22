"""Create, version and export editorial policies from a Humanus `policy-pack-v1` file.

The newsroom's Editorial checks panel saves a policy as an `EditorialPolicy` record: version 1 when
new, the stored version plus one when edited. This does the same through the same store
(`create_policy` / `update_policy`), so a policy written here is indistinguishable from one saved in
the panel, except that its `source` records the operator CLI, the pack and the actor.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import humanus

from .editorial_checks import PUBLICATION_SCOPE, policy_from_record, policy_record_id, record_from_policy

DEFAULT_ACTOR = "papyrus-cli"
CONTENT_FIELDS = ("title", "guidance", "severity", "enabled", "detectors", "examples", "rewriteGuidance")


def load_pack_payload(path: Path) -> dict[str, Any]:
    """The pack file's payload, after Humanus validated it against `policy-pack-v1` (raises on any problem)."""
    if not path.is_file():
        raise ValueError(f"Policy-pack file not found: {path}")
    try:
        humanus.load_policy_pack(path)
    except humanus.ContractValidationError as error:
        raise ValueError(f"{path.name} is not a valid policy-pack-v1 document: {error}") from error
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    import yaml

    return yaml.safe_load(text)


def pack_source(pack_id: str, actor: str) -> str:
    """Provenance stored in the policy's `source`: where it came from and who ran it."""
    return f"operator-cli:{pack_id}:{actor}"


def _content(record: dict[str, Any]) -> dict[str, Any]:
    """The part of a policy record that makes a version: what the panel would show as changed."""
    policy = policy_from_record({**record, "version": 1})
    return {
        "title": policy["title"],
        "guidance": policy["guidance"],
        "severity": policy["severity"],
        "enabled": policy["enabled"],
        "detectors": policy["detectors"],
        "examples": policy.get("examples") or None,
        "rewriteGuidance": policy.get("rewriteGuidance") or None,
    }


def plan_policies(store, payload: dict[str, Any], *, actor: str = DEFAULT_ACTOR) -> list[dict[str, Any]]:
    """One step per pack policy: `create`, `update` (next version) or `unchanged`, each with the record to write."""
    existing = {policy_record_id(r["policyKey"], r["scope"]): r for r in store.list_policies()}
    source = pack_source(payload["packId"], actor)
    steps = []
    for policy in payload["policies"]:
        record = record_from_policy(policy, scope=PUBLICATION_SCOPE, source=source)
        current = existing.get(record["id"])
        if current is None:
            steps.append({"action": "create", "key": policy["id"], "record": record})
        elif _content(current) == _content(record):
            steps.append({"action": "unchanged", "key": policy["id"], "version": int(current.get("version") or 1)})
        else:
            version = int(current.get("version") or 1) + 1
            steps.append({"action": "update", "key": policy["id"], "from": int(current.get("version") or 1), "version": version, "record": {**record, "version": version}})
    return steps


def apply_plan(store, steps: list[dict[str, Any]]) -> None:
    for step in steps:
        if step["action"] == "create":
            store.create_policy(step["record"])
        elif step["action"] == "update":
            store.update_policy(step["record"])


def describe_step(step: dict[str, Any], *, done: bool) -> str:
    verbs = {"create": ("created", "would create"), "update": ("updated", "would update"), "unchanged": ("unchanged", "unchanged")}
    verb = verbs[step["action"]][0 if done else 1]
    if step["action"] == "update":
        return f"{verb}\t{step['key']}\tversion {step['from']} -> {step['version']}"
    return f"{verb}\t{step['key']}\tversion {step.get('version') or step['record']['version']}"


def export_pack(store, *, pack_id: str, pack_version: str | None = None) -> tuple[dict[str, Any], int]:
    """The site's publication policies as a `policy-pack-v1` payload, plus how many desk policies it left out."""
    rows = sorted(store.list_policies(), key=lambda row: row["policyKey"])
    publication = [row for row in rows if row["scope"] == PUBLICATION_SCOPE]
    pack = {
        "schemaVersion": 1,
        "packId": pack_id,
        "version": pack_version or str(max([int(row.get("version") or 1) for row in publication] or [1])),
        "policies": [policy_from_record(row) for row in publication],
    }
    humanus.load_policy_pack(pack)
    return pack, len(rows) - len(publication)


def write_pack(path: Path, pack: dict[str, Any]) -> None:
    if path.suffix.lower() in (".yml", ".yaml"):
        import yaml

        text = yaml.safe_dump(pack, sort_keys=False, allow_unicode=True)
    else:
        text = json.dumps(pack, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
