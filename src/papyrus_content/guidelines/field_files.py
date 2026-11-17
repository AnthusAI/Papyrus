"""The writing guidelines as a set of guideline files (schema version 2), and the structured view the resolver and the console read from it.

A set is a map of path to text: ``<name>/GUIDELINE.md`` and any supporting files beside it. The cloud stores that map and nothing else (``store.py``). Two kinds of
guideline file live in a set:

* **Field files** have a fixed name, the kebab-case name of a field of the writing document (``tone``, ``voice-patterns``, ``lexicon``, ``glossary``...). The body
  holds the field's value, in one of three forms: ``text`` (the text itself), ``bullets`` (a list of sentences, one ``- `` line each) or ``json`` (one fenced
  block, for a value with structure). Together they are the **document view**: the dict every resolver, layering rule, derived check and agent text reads.
* **Rule files** are any other name: a guideline in the file form of ``files.py`` (severity, words to avoid, patterns, prose). Each ``error`` or ``warn`` rule file
  derives one editorial check; none is part of the document view.

Both are read with the one reader of ``files.py`` (``parse_text``), so a folder kept in a repository and a set read back from a site are checked the same way. This
module also holds the only writer of field files, and the check that a document turned into files and back is the same document (the conversion relies on it).
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import files as guideline_files
from . import front_matter
from .document import GuidelineError, safe_key

WRITING = "writing"
SCHEMA_VERSION = 2
FILE_NAME = guideline_files.FILE_NAME

TEXT, BULLETS, JSON = "text", "bullets", "json"

#: Every field of the writing document and how its value is written in the file's body. The name of the file is the field's name in kebab case.
FORMS: dict[str, str] = {
    "voice": JSON, "audience": TEXT, "headline": JSON, "editorialAim": TEXT, "register": TEXT, "tone": BULLETS, "sentenceStyle": BULLETS, "voicePatterns": BULLETS,
    "structure": BULLETS, "evidenceRules": BULLETS, "bodyMarkus": TEXT, "lexicon": JSON, "glossary": JSON, "exemplars": JSON, "constraints": JSON,
    "publicationKey": TEXT, "judge": JSON, "checks": JSON, "density": JSON, "rules": JSON, "compare": JSON, "referenceSamples": JSON, "locked": BULLETS,
}
LABELS: dict[str, str] = {"voice": "Voice", "audience": "Audience", "editorialAim": "Editorial aim", "bodyMarkus": "Guidance in your own words",
                          "lexicon": "Words to prefer and avoid", "constraints": "Binding rules", "locked": "Fields a section may not replace"}


def kebab(key: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", key).lower()


NAME_OF = {key: kebab(key) for key in FORMS}
KEY_OF = {name: key for key, name in NAME_OF.items()}


@dataclass
class SetView:
    document: dict[str, Any] = field(default_factory=dict)
    rules: list[dict[str, Any]] = field(default_factory=list)
    problems: list[guideline_files.Problem] = field(default_factory=list)


def lineage_scope(section: str | None) -> str:
    return f"section/{safe_key(section)}" if section else "publication"


def guideline_id(slug: str, name: str) -> str:
    """The permanent id of a field file: stable for the lineage and the name, so converting twice, or saving the same structured fields again, writes the same bytes."""
    return "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://papyrus.invalid/guideline/{slug}/{name}"))


# --- writing one field file --------------------------------------------------------------------------------------------------------------------------

def _front(meta: dict[str, Any]) -> str:
    return "---\n" + front_matter.dumps(meta) + "---\n"


def _body(form: str, value: Any) -> str:
    if form == TEXT:
        return f"{value}\n"
    if form == BULLETS:
        return "".join("- " + str(item).replace("\n", "\n  ") + "\n" for item in value)
    return "```json\n" + json.dumps(value, indent=2, ensure_ascii=False) + "\n```\n"


def field_file(key: str, value: Any, *, slug: str, section: str | None, language: str | None) -> str:
    name = NAME_OF[key]
    meta: dict[str, Any] = {"id": guideline_id(slug, name), "type": guideline_files.TYPE, "name": name, "description": f"{LABELS.get(key) or key[0].upper() + kebab(key)[1:].replace('-', ' ')} in the writing guidelines.",
                            "kind": WRITING, "scope": lineage_scope(section), "severity": "guidance"}
    if language:
        meta["language"] = language
    return _front(meta) + _body(FORMS[key], value)


def files_from_document(document: dict[str, Any], *, slug: str, section: str | None = None, language: str | None = None) -> dict[str, str]:
    """The field files of a document view. A key that is not a field of the writing document is refused (``validate_document`` names it first)."""
    files: dict[str, str] = {}
    for key, value in document.items():
        if key == "schemaVersion":
            continue
        if key not in FORMS:
            raise GuidelineError("invalid_input", f"{key} is not a field of the writing guidelines.", {"problems": [{"path": key, "message": "is not a field of this kind of guidelines", "code": "unknown_field"}]})
        files[f"{NAME_OF[key]}/{FILE_NAME}"] = field_file(key, value, slug=slug, section=section, language=language)
    return files


# --- reading a set -----------------------------------------------------------------------------------------------------------------------------------

def _value(form: str, raw: str) -> Any:
    if form == TEXT:
        return raw[:-1] if raw.endswith("\n") else raw
    if form == BULLETS:
        items: list[str] = []
        for line in raw.split("\n")[:-1] if raw.endswith("\n") else raw.split("\n"):
            if line.startswith("- "):
                items.append(line[2:])
            elif line.startswith("  ") and items:
                items[-1] += "\n" + line[2:]
            else:
                raise ValueError("each line starts with '- ', and a longer sentence continues on lines indented by two spaces")
        return items
    found = re.fullmatch(r"```json\n(.*)\n```\n?", raw, re.S)
    if found is None:
        raise ValueError("holds one fenced json block and nothing else")
    try:
        return json.loads(found.group(1))
    except ValueError as error:
        raise ValueError(f"has json that is not valid: {error}") from error


def _check_path(path: str) -> str | None:
    parts = path.split("/")
    if len(parts) < 2 or any(part in ("", ".", "..") or part.startswith(".") for part in parts) or "\\" in path:
        return "must be a file inside a guideline folder"
    return None


def parse_set(files: dict[str, str], *, section: str | None = None, language: str | None = None) -> SetView:
    """The document view and the rule files of a set, with every problem found. The set is for one lineage: its scope and language are the lineage's, so a file that says
    otherwise is refused (a section's rules never sit in the publication's set)."""
    view = SetView()
    problems = view.problems
    folders: dict[str, dict[str, str]] = {}
    for path, text in sorted(files.items()):
        bad = _check_path(path)
        if bad:
            problems.append(guideline_files.Problem(path, "", bad, "stray_file"))
        else:
            folders.setdefault(path.split("/", 1)[0], {})[path.split("/", 1)[1]] = text
    if not folders and not problems:
        problems.append(guideline_files.Problem("", "", "holds no guideline files", "empty"))
    scope, want_language = lineage_scope(section), language or "*"
    seen: dict[str, str] = {}
    document: dict[str, Any] = {}
    for name, inside in folders.items():
        if FILE_NAME not in inside:
            problems.append(guideline_files.Problem(name, "", f"has no {FILE_NAME}", "missing_file"))
            continue
        guideline, found = guideline_files.parse_text(name, inside[FILE_NAME])
        problems += found
        if guideline is None:
            continue
        meta = guideline.meta
        for key, wanted, label in (("kind", WRITING, "kind"), ("scope", scope, "scope")):
            if meta[key] != wanted:
                problems.append(guideline_files.Problem(name, key, f"must be {wanted} in this set of guidelines", "wrong_lineage"))
        if guideline.language.lower() != want_language.lower():
            problems.append(guideline_files.Problem(name, "language", f"must be {want_language} in this set of guidelines", "wrong_lineage"))
        other = seen.setdefault(meta["id"], name)
        if other != name:
            problems.append(guideline_files.Problem(name, "id", f"is already the id of {other}", "duplicate_id"))
        if name in KEY_OF:
            key = KEY_OF[name]
            if len(inside) > 1:
                problems.append(guideline_files.Problem(name, "", f"holds files beside {FILE_NAME}; the field file {name} holds only that", "supporting_file"))
            if guideline.severity != "guidance":
                problems.append(guideline_files.Problem(name, "severity", "must be guidance for a field file", "invalid_value"))
            raw = inside[FILE_NAME].replace("\r\n", "\n")
            found_front = guideline_files._FRONT.match(raw)
            try:
                document[key] = _value(FORMS[key], found_front.group(2))
            except ValueError as error:
                problems.append(guideline_files.Problem(name, "body", str(error), "invalid_body"))
        else:
            view.rules.append({**guideline.meta, "body": guideline.body, "files": sorted(inside)})
    if not problems:
        view.document = {"schemaVersion": SCHEMA_VERSION, **{key: document[key] for key in FORMS if key in document}}
    return view


def problem_details(problems: list[guideline_files.Problem]) -> dict[str, Any]:
    return {"problems": [{"path": f"{p.folder}/{p.key}".rstrip("/") if p.key else p.folder, "message": p.message, "code": p.code, "guideline": p.folder, "key": p.key} for p in problems]}


def view_of(files: dict[str, str], *, section: str | None = None, language: str | None = None) -> SetView:
    """The set's view, or ``GuidelineError`` (``invalid_input``) naming every problem by guideline and key."""
    view = parse_set(files, section=section, language=language)
    if view.problems:
        raise GuidelineError("invalid_input", "The guideline files have problems: " + "; ".join(f"{p.folder}{(' ' + p.key) if p.key else ''} {p.message}" for p in view.problems),
                             problem_details(view.problems))
    return view


def set_digest(files: dict[str, str]) -> str:
    """The hash over a set: its paths and bytes, in path order. It is the catalog row's ``contentHash``."""
    payload = json.dumps([[path, files[path]] for path in sorted(files)], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def rule_folders(files: dict[str, str]) -> dict[str, str]:
    """The files of every folder that is not a field file: what a save of the structured fields carries over unchanged."""
    return {path: text for path, text in files.items() if "/" in path and path.split("/", 1)[0] not in KEY_OF}


def with_fields(files: dict[str, str] | None, document: dict[str, Any], *, slug: str, section: str | None, language: str | None) -> dict[str, str]:
    """A save of structured fields: the field files of ``document``, and the rule files of the current set kept as they are."""
    return {**rule_folders(files or {}), **files_from_document(document, slug=slug, section=section, language=language)}


def assert_registered() -> None:
    from .document import WRITING_FIELDS

    missing = sorted(set(WRITING_FIELDS) - set(FORMS) - {"schemaVersion"})
    if missing:
        raise AssertionError(f"Writing fields with no file form: {', '.join(missing)}")

