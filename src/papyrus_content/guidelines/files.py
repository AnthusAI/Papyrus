"""The guideline file form (PPY-9c2ea0): one guideline is one folder holding ``GUIDELINE.md``, and the files can be read and checked with no network.

    guidelines/
      plain-claims/
        GUIDELINE.md          flat front matter, then the prose
        examples/before.md    optional supporting files, never read here

The front matter follows the pod profile's rules: flat keys only (a value is text, a number, or a flat list of them), an explicit permanent ``id``, and an unknown
key is refused. A Guideline is a file kind of its own and never a page. ``kind``, ``scope`` and ``severity`` map onto the guideline system that already exists
(``document.kind_names``, a section's key, the severities of the editorial checks); nothing here is a second vocabulary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

FILE_NAME = "GUIDELINE.md"
TYPE = "papyrus:Guideline"
KINDS = ("writing", "image", "announcement")
SEVERITIES = ("error", "warn", "guidance")
REQUIRED = ("id", "type", "name", "description", "kind", "scope", "severity")
OPTIONAL = ("language", "avoid", "prefer", "pattern", "maxLength")
KEYS = (*REQUIRED, *OPTIONAL)
LIST_KEYS = ("avoid", "prefer", "pattern")
DECIDABLE = ("avoid", "pattern", "maxLength")   # what a program can decide with no model; ``prefer`` and the prose are for the writer

_WORD = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_NAME = re.compile(rf"^{_WORD}$")
_SCOPE = re.compile(rf"^(?:publication|section/{_WORD}|channel/{_WORD})$")
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:\S+$")
_LANGUAGE = re.compile(r"^(?:\*|[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)$")
_FRONT = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)(.*)\Z", re.S)


@dataclass(frozen=True)
class Problem:
    folder: str
    key: str
    message: str
    code: str = "invalid"

    def as_dict(self) -> dict[str, str]:
        return {"guideline": self.folder, "key": self.key, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class Guideline:
    folder: str
    meta: dict[str, Any]
    body: str

    @property
    def name(self) -> str:
        return self.meta["name"]

    @property
    def kind(self) -> str:
        return self.meta["kind"]

    @property
    def scope(self) -> str:
        return self.meta["scope"]

    @property
    def severity(self) -> str:
        return self.meta["severity"]

    @property
    def language(self) -> str:
        return self.meta.get("language", "*")

    def decidable(self) -> bool:
        return any(key in self.meta for key in DECIDABLE)


@dataclass
class Loaded:
    guidelines: list[Guideline] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float)) and not isinstance(value, bool)


def split_front_matter(text: str) -> tuple[Any, str] | None:
    """``(front matter as read, body)``, or None when the file does not open with a front matter block."""
    found = _FRONT.match(text.replace("\r\n", "\n"))
    if found is None:
        return None
    return yaml.safe_load(found.group(1)), found.group(2)


def validate_meta(folder: str, meta: Any) -> list[Problem]:
    """Every problem with one guideline's front matter, by key. The same checks run for a folder on a laptop and for a set read back from a site."""
    if not isinstance(meta, dict):
        return [Problem(folder, "", "The front matter must be a list of keys and values.", "not_flat")]
    problems = [Problem(folder, key, "is not a key of a guideline", "unknown_key") for key in meta if key not in KEYS]
    for key in REQUIRED:
        if key not in meta:
            problems.append(Problem(folder, key, "is required", "missing_key"))
    for key, value in meta.items():
        if key not in KEYS:
            continue
        if isinstance(value, dict) or (isinstance(value, list) and any(isinstance(item, (dict, list)) for item in value)):
            problems.append(Problem(folder, key, "must be flat: text, a number, or a list of them; nothing nested", "nested_value"))
        elif isinstance(value, list) and key not in LIST_KEYS:
            problems.append(Problem(folder, key, "must be a single value, not a list", "invalid_value"))
        elif key in LIST_KEYS and not isinstance(value, list):
            problems.append(Problem(folder, key, "must be a list", "invalid_value"))
    flat = {key: value for key, value in meta.items() if key in KEYS and not isinstance(value, dict)
            and not (isinstance(value, list) and any(isinstance(item, (dict, list)) for item in value))}

    def bad(key: str, message: str, code: str = "invalid_value") -> None:
        problems.append(Problem(folder, key, message, code))

    for key in ("id", "type", "name", "description", "kind", "scope", "severity", "language"):
        if key in flat and not (isinstance(flat[key], str) and flat[key].strip()):
            bad(key, "must be non-empty text")
            flat.pop(key)
    if "id" in flat and not _ID.match(flat["id"]):
        bad("id", "must be a permanent identifier with a scheme, such as https://example.org/id/2b9d")
    if "type" in flat and flat["type"] != TYPE:
        bad("type", f"must be {TYPE}")
    if "name" in flat:
        if not _NAME.match(flat["name"]):
            bad("name", "is lowercase words joined by hyphens")
        elif flat["name"] != folder:
            bad("name", f"must be the folder's name, {folder}")
    if "kind" in flat and flat["kind"] not in KINDS:
        bad("kind", f"must be one of {', '.join(KINDS)}")
    if "scope" in flat and not _SCOPE.match(flat["scope"]):
        bad("scope", "must be publication, section/<id> or channel/<name>")
    if "severity" in flat and flat["severity"] not in SEVERITIES:
        bad("severity", f"must be one of {', '.join(SEVERITIES)}")
    if "language" in flat and not _LANGUAGE.match(flat["language"]):
        bad("language", 'must be a language tag such as en or zh-Hans, or "*" for every language')
    for key in ("avoid", "prefer", "pattern"):
        if isinstance(flat.get(key), list):
            if not flat[key] or not all(isinstance(item, str) and item.strip() for item in flat[key]):
                bad(key, "must be a list of non-empty text")
            elif key == "pattern":
                for item in flat[key]:
                    try:
                        re.compile(item)
                    except re.error as error:
                        bad(key, f"{item!r} is not a valid pattern: {error}")
    if "maxLength" in flat and not (isinstance(flat["maxLength"], int) and not isinstance(flat["maxLength"], bool) and flat["maxLength"] > 0):
        bad("maxLength", "must be a whole number above zero")
    return problems


def load_guideline(folder: Path) -> tuple[Guideline | None, list[Problem]]:
    name = folder.name
    path = folder / FILE_NAME
    if not path.is_file():
        return None, [Problem(name, "", f"has no {FILE_NAME}", "missing_file")]
    try:
        parts = split_front_matter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        return None, [Problem(name, "", f"could not be read: {error}", "unreadable")]
    except yaml.YAMLError:
        return None, [Problem(name, "", "has front matter that is not valid", "not_flat")]
    if parts is None:
        return None, [Problem(name, "", "must open with a front matter block between two --- lines", "missing_front_matter")]
    meta, body = parts
    problems = validate_meta(name, meta)
    return (None if problems else Guideline(name, meta, body.strip())), problems


def load_directory(directory: Path) -> Loaded:
    """Read every guideline folder under ``directory``. A set is valid or refused: any problem is reported and the caller does not go on."""
    loaded = Loaded()
    if not directory.is_dir():
        loaded.problems.append(Problem(str(directory), "", "is not a folder", "not_a_folder"))
        return loaded
    seen: dict[str, str] = {}
    for folder in sorted(entry for entry in directory.iterdir() if entry.is_dir() and not entry.name.startswith(".")):
        guideline, problems = load_guideline(folder)
        loaded.problems += problems
        if guideline is None:
            continue
        other = seen.setdefault(guideline.meta["id"], guideline.folder)
        if other != guideline.folder:
            loaded.problems.append(Problem(guideline.folder, "id", f"is already the id of {other}", "duplicate_id"))
            continue
        loaded.guidelines.append(guideline)
    if not loaded.guidelines and not loaded.problems:
        loaded.problems.append(Problem(str(directory), "", "holds no guideline folders", "empty"))
    return loaded


# --- the offline check ---------------------------------------------------------------------------------------------------------------------------------

def _phrase(word: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w]){re.escape(word.strip())}(?![\w])", re.I)


def findings_for(guideline: Guideline, text: str, file: str) -> list[dict[str, Any]]:
    """What the rules a program can decide find in ``text``: a listed word or phrase (whole words, any case), a pattern, a length over the limit."""
    meta, found = guideline.meta, []

    def add(rule: str, message: str, line: int | None = None, match: str | None = None) -> None:
        found.append({"file": file, "guideline": guideline.name, "scope": guideline.scope, "severity": guideline.severity, "rule": rule, "message": message,
                      **({"line": line} if line else {}), **({"match": match} if match else {})})

    for word in meta.get("avoid", []):
        for hit in _phrase(word).finditer(text):
            add("avoid", f"uses {word!r}, which this guideline says to avoid", text.count("\n", 0, hit.start()) + 1, hit.group(0))
    for pattern in meta.get("pattern", []):
        for hit in re.finditer(pattern, text, re.M):
            add("pattern", f"matches the pattern {pattern!r}", text.count("\n", 0, hit.start()) + 1, hit.group(0)[:80])
    limit = meta.get("maxLength")
    if limit is not None and len(text.strip()) > limit:
        add("maxLength", f"is {len(text.strip())} characters; the limit is {limit}")
    return found


def check_files(guidelines: list[Guideline], files: list[Path], *, scopes: list[str], language: str | None) -> dict[str, Any]:
    """The answer of ``papyrus guidelines check``: findings, the rules not checked offline, and the exit rule (``error`` findings only).

    The publication's guidelines always apply; each scope in ``scopes`` (``section/<id>``, ``channel/<name>``) adds its own. A guideline for a language other than
    the one given (or any, when none is given) is not decided: it is listed as not checked, never guessed at."""
    applying = [item for item in guidelines if item.scope == "publication" or item.scope in scopes]
    findings: list[dict[str, Any]] = []
    unchecked: dict[tuple[str, str], dict[str, str]] = {}
    for guideline in applying:
        if guideline.severity == "guidance":
            continue
        if guideline.language != "*" and (language is None or guideline.language.split("-")[0].lower() != language.split("-")[0].lower()):
            unchecked[(guideline.name, "language")] = {"guideline": guideline.name, "reason": f"written for {guideline.language}; pass --language to check it"}
        elif not guideline.decidable():
            unchecked[(guideline.name, "judgement")] = {"guideline": guideline.name, "reason": "needs judgement"}
    for path in files:
        text = path.read_text(encoding="utf-8")
        for guideline in applying:
            if guideline.severity != "guidance" and (guideline.language == "*" or (language and guideline.language.split("-")[0].lower() == language.split("-")[0].lower())):
                findings += findings_for(guideline, text, str(path))
    errors = sum(1 for item in findings if item["severity"] == "error")
    return {"checked": [str(path) for path in files], "guidelinesApplied": [item.name for item in applying], "findings": findings,
            "notCheckedOffline": sorted(unchecked.values(), key=lambda item: item["guideline"]),
            "summary": {"errors": errors, "warnings": len(findings) - errors}}
