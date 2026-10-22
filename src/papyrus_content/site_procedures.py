"""A publication's own Tactus procedures, registered in its newsroom so the cloud runner can execute them.

`papyrus procedures register <file.tac> --key <procedureKey>` stores the source as the version's `code`
attachment (sort key `code`) and every file of every skill directory its agents name as a further `code`
attachment with sort key `skill:<relative path>` (the newsroom accepts the `code` role on procedure versions).
The version id is a digest of all of those files, so registering unchanged files is a no-op and any change
publishes a new version, archiving the previous one.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ids import safe_id

PROCEDURE_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
SKILL_SORT_KEY_PREFIX = "skill:"
MAX_SKILL_FILES = 50
MAX_SKILL_BYTES = 512_000
TACTUS_TYPE_TO_JSON_SCHEMA = {"string": "string", "number": "number", "integer": "integer", "boolean": "boolean",
                              "array": "array", "object": "object"}


def tactus_registry(source: str):
    from tactus.validation import TactusValidator, ValidationMode

    result = TactusValidator().validate(source, ValidationMode.FULL)
    if not result.valid or result.registry is None:
        problems = "; ".join(str(error) for error in (result.errors or []))[:500]
        raise ValueError(f"Tactus could not validate the procedure: {problems or 'no registry'}")
    return result.registry


def parameter_schema_from_tactus(input_schema: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    properties, required, defaults = {}, [], {}
    for name, field in (input_schema or {}).items():
        field_type = TACTUS_TYPE_TO_JSON_SCHEMA.get(str(field.get("type") or "string"), "string")
        properties[name] = {"type": field_type, **({"description": field["description"]} if field.get("description") else {})}
        if field.get("required"):
            required.append(name)
        if "default" in field and field["default"] is not None:
            defaults[name] = field["default"]
    return {"type": "object", "properties": properties, "required": required}, defaults


def skill_directories(registry) -> list[str]:
    directories = set()
    for agent in (registry.agents or {}).values():
        directories.update(str(path) for path in (getattr(agent, "skills", None) or []))
    return sorted(directories)


def skill_files(root: Path, directories: list[str]) -> list[tuple[str, bytes]]:
    """Every file under each skill directory, keyed by its path relative to `root` (the run's working directory)."""
    files = []
    resolved_root = root.resolve()
    for directory in directories:
        candidate = (root / directory).resolve()
        if not candidate.is_relative_to(resolved_root):
            raise ValueError(f"Skill directory {directory} is outside {root}")
        if not (candidate / "SKILL.md").is_file():
            raise ValueError(f"Skill directory {directory} has no SKILL.md under {root}")
        for path in sorted(candidate.rglob("*")):
            if path.is_file() and not any(part.startswith(".") for part in path.relative_to(candidate).parts):
                files.append((path.relative_to(resolved_root).as_posix(), path.read_bytes()))
    if len(files) > MAX_SKILL_FILES or sum(len(body) for _, body in files) > MAX_SKILL_BYTES:
        raise ValueError(f"Skills exceed {MAX_SKILL_FILES} files or {MAX_SKILL_BYTES} bytes")
    return files


def registration_plan(source_path: Path, *, root: Path, procedure_key: str, title: str | None = None,
                      description: str | None = None) -> dict[str, Any]:
    if not PROCEDURE_KEY.match(procedure_key):
        raise ValueError("procedure key must be lowercase letters, digits, dots, dashes or underscores")
    source = source_path.read_text(encoding="utf-8")
    registry = tactus_registry(source)
    parameter_schema, defaults = parameter_schema_from_tactus(registry.input_schema or {})
    skills = skill_files(root, skill_directories(registry))
    digest = hashlib.sha256()
    for name, body in [("code.tac", source.encode("utf-8")), *skills]:
        digest.update(name.encode("utf-8") + b"\0" + hashlib.sha256(body).digest())
    content_digest = digest.hexdigest()[:16]
    return {
        "procedureKey": procedure_key,
        "procedureId": f"procedure-{safe_id(procedure_key)}",
        "versionId": f"procedure-version-{safe_id(procedure_key)}-{content_digest}",
        "contentDigest": content_digest,
        "title": title or (registry.description or procedure_key).strip().splitlines()[0][:200],
        "description": description or (registry.description or "").strip(),
        "sourcePath": str(source_path),
        "source": source,
        "parameterSchema": parameter_schema,
        "defaults": defaults,
        "skills": skills,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _upload_text_attachment(client, *, version_id: str, role: str, sort_key: str, filename: str, body: bytes, now: str):
    from .model_attachments import build_model_payload_attachment, upload_attachment_body

    built = build_model_payload_attachment({
        "ownerKind": "procedureVersion", "ownerId": version_id, "ownerLineageId": version_id, "role": role,
        "sortKey": sort_key, "filename": filename, "mediaType": "text/plain", "content": body, "status": "active",
        "now": now})
    return upload_attachment_body(client, built["attachment"], built["body"])


def register_site_procedure(client, plan: dict[str, Any], *, actor: str = "papyrus-cli", now: str | None = None) -> dict[str, Any]:
    now = now or _now()
    definition = client.get_record("ProcedureDefinition", plan["procedureId"])
    if definition and definition.get("procedureKey") != plan["procedureKey"]:
        raise ValueError(f"ProcedureDefinition {plan['procedureId']} belongs to {definition.get('procedureKey')}")
    versions = client.list_by_index("procedureVersionsByProcedure", plan["procedureId"]) if definition else []
    unchanged = any(version.get("id") == plan["versionId"] and version.get("status") == "published" for version in versions)
    if unchanged and (definition or {}).get("currentVersionId") == plan["versionId"]:
        return {"procedureKey": plan["procedureKey"], "versionId": plan["versionId"], "status": "unchanged"}
    version_number = 1 + max([int(version.get("versionNumber") or 0) for version in versions] or [0])
    if not definition:
        client.create_record("ProcedureDefinition", {
            "id": plan["procedureId"], "procedureKey": plan["procedureKey"], "title": plan["title"],
            "category": "site", "description": plan["description"], "enabled": True, "enabledStatus": "enabled",
            "createdBy": actor, "createdAt": now, "updatedBy": actor, "updatedAt": now, "newsroomFeedKey": "procedures"})
    existing_version = next((version for version in versions if version.get("id") == plan["versionId"]), None)
    if not unchanged:
        if existing_version is None:
            client.create_record("ProcedureVersion", {
                "id": plan["versionId"], "procedureId": plan["procedureId"], "procedureKey": plan["procedureKey"],
                "versionNumber": version_number, "status": "draft", "isCurrent": False,
                "label": f"{plan['contentDigest']}", "tactusSource": "attachment://code.tac",
                "parameterSchema": json.dumps(plan["parameterSchema"]), "defaults": json.dumps(plan["defaults"]),
                "changelog": f"Registered from {Path(plan['sourcePath']).name} with {len(plan['skills'])} skill file(s).",
                "createdBy": actor, "createdAt": now, "updatedBy": actor, "updatedAt": now})
        else:
            version_number = int(existing_version.get("versionNumber") or version_number)
        for relative_path, body in plan["skills"]:
            _upload_text_attachment(client, version_id=plan["versionId"], role="code",
                                    sort_key=f"{SKILL_SORT_KEY_PREFIX}{relative_path}",
                                    filename=relative_path.replace("/", "__"), body=body, now=now)
        _upload_text_attachment(client, version_id=plan["versionId"], role="code", sort_key="code",
                                filename="code.tac", body=plan["source"].encode("utf-8"), now=now)
        client.update_record("ProcedureVersion", {"id": plan["versionId"], "status": "published", "isCurrent": True,
                                                  "updatedBy": actor, "updatedAt": now})
    for version in versions:
        if version.get("id") != plan["versionId"] and (version.get("isCurrent") or version.get("status") == "published"):
            client.update_record("ProcedureVersion", {"id": version["id"], "status": "archived", "isCurrent": False,
                                                      "updatedBy": actor, "updatedAt": now})
    client.update_record("ProcedureDefinition", {
        "id": plan["procedureId"], "currentVersionId": plan["versionId"], "title": plan["title"],
        "description": plan["description"], "enabled": True, "enabledStatus": "enabled", "updatedBy": actor, "updatedAt": now})
    return {"procedureKey": plan["procedureKey"], "versionId": plan["versionId"],
            "versionNumber": version_number, "status": "republished" if unchanged else "registered",
            "skillFiles": [path for path, _ in plan["skills"]]}


def procedures_register(flags: list[str]) -> None:
    """`papyrus procedures register --file <path.tac> --key <procedureKey> [--root DIR] [--title T] [--description D] [--dry-run] [--json]`"""
    from .graphql_authoring import create_authoring_client
    from .options import parse_options, resolve_mutation_apply

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "procedures register")
    if not isinstance(options.get("file"), str) or not isinstance(options.get("key"), str):
        raise ValueError("papyrus procedures register needs --file <path.tac> and --key <procedureKey>.")
    root = Path(options["root"] if isinstance(options.get("root"), str) else ".")
    plan = registration_plan(Path(options["file"]), root=root, procedure_key=options["key"],
                             title=options.get("title") if isinstance(options.get("title"), str) else None,
                             description=options.get("description") if isinstance(options.get("description"), str) else None)
    summary = {"procedureKey": plan["procedureKey"], "procedureId": plan["procedureId"], "versionId": plan["versionId"],
               "parameterSchema": plan["parameterSchema"], "skillFiles": [path for path, _ in plan["skills"]]}
    result = register_site_procedure(create_authoring_client()[0], plan) if apply else {"status": "dry-run"}
    if options.get("json"):
        print(json.dumps({"ok": True, "command": "procedures register", **summary, **result}, indent=2))
        return
    print(f"procedures\tregister\t{result.get('status')}\t{plan['procedureKey']}\t{plan['versionId']}"
          f"\tskills={len(plan['skills'])}")
