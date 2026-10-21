"""`papyrus sections doctrine set` and `papyrus sections update`: edit publication doctrine and newsroom sections.

These make the same writes the newsroom does: the doctrine Item body (topic-steering workspace) and the NewsroomSection
update (Administration > Sections).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .graphql_authoring import create_authoring_client
from .newsroom_doctrine import DOCTRINE_DEFINITION_BY_KIND, DOCTRINE_KINDS, build_publication_doctrine_records
from .options import normalize_string, parse_boolean_option, parse_options, resolve_mutation_apply
from .publishing import utc_now_iso
from .tenancy import tenant_id_from_options

SECTION_TEXT_OPTIONS = {
    "editorial-mission-file": "editorialMission",
    "editorial-policy-file": "editorialPolicy",
    "assignment-guidance-file": "assignmentGuidance",
    "kill-criteria-file": "killCriteria",
}


def _read_text_file(path: str, label: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"Cannot read {label} {path}: {error.strerror or error}.") from error


def doctrine_text_to_body(text: str) -> list[str]:
    """The newsroom's doctrineTextToBody: paragraphs separated by blank lines."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n+", normalized) if paragraph.strip()]


def _current_doctrine_record(client, slug: str) -> dict[str, Any] | None:
    rows = [row for row in client.list_by_index("itemBySlug", slug) if row.get("versionState") in (None, "current")]
    return max(rows, key=lambda row: int(row.get("versionNumber") or 0)) if rows else None


def sections_doctrine_set(flags: list[str]) -> None:
    """papyrus sections doctrine set --kind mission|policy --file <md> [--dry-run]"""
    if not flags or flags[0] != "set":
        raise ValueError("Usage: papyrus sections doctrine set --kind mission|policy --file <md> [--dry-run]")
    options = parse_options(flags[1:])
    apply = resolve_mutation_apply(options, "sections doctrine set")
    kind = normalize_string(options.get("kind"))
    if kind not in DOCTRINE_KINDS:
        raise ValueError("--kind must be mission or policy.")
    file_path = normalize_string(options.get("file"))
    if not file_path:
        raise ValueError("--file is required.")
    body = doctrine_text_to_body(_read_text_file(file_path, "--file"))
    if not body:
        raise ValueError(f"{file_path} has no text; refusing to empty the {kind} doctrine.")
    client, _ = create_authoring_client(tenant_id_from_options(options))
    definition = DOCTRINE_DEFINITION_BY_KIND[kind]
    current = _current_doctrine_record(client, definition["slug"])
    before = len(current.get("body") or []) if current else 0
    mode = "write" if apply else "dry run"
    action = "update" if current else "create"
    print(f"sections\tdoctrine\tset\t{definition['slug']}\t{action}\t{before} -> {len(body)} paragraphs\t{mode}")
    if not apply:
        return
    now = utc_now_iso()
    if current:
        client.update_record("Item", {
            "id": current["id"], "title": definition["title"], "headline": definition["title"], "body": body,
            "editorial": json.dumps({"kind": kind}, separators=(",", ":")), "updatedAt": now,
        })
    else:
        record = build_publication_doctrine_records([{"kind": kind, "body": body}], now=now)[0]["expected"]
        client.upsert("Item", {**record, "headline": definition["title"], "editorial": json.dumps({"kind": kind}, separators=(",", ":"))})
    print(f"sections\tdoctrine\tset\tsaved\t{definition['slug']}")


def sections_update(flags: list[str]) -> None:
    """papyrus sections update --id <section id> [--editorial-mission-file F] [--editorial-policy-file F] [--assignment-guidance-file F] [--kill-criteria-file F] [--enabled true|false] [--dry-run]"""
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "sections update")
    section_id = normalize_string(options.get("id"))
    if not section_id:
        raise ValueError("--id is required.")
    wanted: dict[str, Any] = {}
    for option, field in SECTION_TEXT_OPTIONS.items():
        path = normalize_string(options.get(option))
        if path:
            text = _read_text_file(path, f"--{option}").strip()
            if not text and field in ("editorialMission", "editorialPolicy"):
                raise ValueError(f"{path} has no text; {field} cannot be empty.")
            wanted[field] = text or None
    if options.get("enabled") is not None:
        wanted["enabled"] = parse_boolean_option(options.get("enabled"), default=True, label="--enabled")
    if not wanted:
        raise ValueError("Nothing to update: pass at least one of " + ", ".join(f"--{name}" for name in SECTION_TEXT_OPTIONS) + ", --enabled.")
    client, _ = create_authoring_client(tenant_id_from_options(options))
    current = client.get_record("NewsroomSection", section_id)
    if current is None:
        raise ValueError(f"No newsroom section with id {section_id}.")
    changes = {field: value for field, value in wanted.items() if current.get(field) != value}
    if not changes:
        print(f"sections\tupdate\tunchanged\t{section_id}")
        return
    mode = "write" if apply else "dry run"
    for field, value in changes.items():
        before, after = current.get(field), value
        shown = f"{before} -> {after}" if isinstance(after, bool) else f"{len(before or '')} -> {len(after or '')} chars"
        print(f"sections\tupdate\t{section_id}\t{field}\t{shown}\t{mode}")
    if not apply:
        return
    payload = {"id": section_id, **changes, "updatedAt": utc_now_iso()}
    if "enabled" in changes:
        payload["enabledStatus"] = "enabled" if changes["enabled"] else "disabled"
    client.update_record("NewsroomSection", payload)
    print(f"sections\tupdate\tsaved\t{section_id}")
