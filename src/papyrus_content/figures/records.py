"""A site's design system as backend data (PPY-74ef89, slice 2).

The design system is one more kind of guideline document (``design-system``, registered in ``guidelines/document.py``), kept exactly as mission, policy and the
other guidelines are: a catalog row (``Item``, type ``doctrine``, slug ``editorial-doctrine-design-system``) holding only the slug, version, who, when, why and a
content hash, and the content in S3 as ModelAttachments of that version. Nothing here adds a table, an index or a subscription, and no text is stored in
DynamoDB.

Two kinds of file are attached to a version:

* one JSON **document** (role ``doctrine_document``) holding every text file of the design system verbatim, by its path relative to the design system's root:
  ``mapping.json``, the tokens file it names and each worked example's ``figure.svg`` and ``figure.json``; plus the site's figure ``settings`` and, for each font,
  its hash and size; and
* one **asset** (role ``doctrine_asset``, ``sortKey`` = the font's path) for each font file, which is media and not text.

Keeping the files verbatim means ``papyrus design-system pull`` hands back the folder that was pushed, and a ``BackendSource`` answers the three
``DesignSystemSource`` questions (``read_text``, ``read_bytes``, ``list_examples``) without anything about the design system changing. The document's content
hash covers the fonts through their hashes. The design system belongs to the site, so there is one lineage per site and tenant (a row carries ``tenantSlug``
exactly as the other guidelines do); a section has none of its own.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from papyrus_content.guidelines import GuidelineStore, Problem, digest as digest_of, slug_for

from .design_system import DesignSystemError, DesignSystemSource, load_design_system

KIND = "design-system"
SCHEMA_VERSION = 1
MAPPING_FILE = "mapping.json"
SETTINGS_FILE = "settings.json"        # in a design system folder only: the site's figure settings, kept in the document and not in `files`
SETTINGS = {
    "requireDarkFigures": "refuse to save a figure that has no dark picture",
    "illustrationRequiredTypes": "the Story types whose checklist needs an approved cover before publishing (a list; articles when unset)",
    "illustrationRequireApprovalCredit": "also require the cover's image line to say 'Approved by NAME' (off when unset; the approval itself is always metadata)",
}
LIST_SETTINGS = ("illustrationRequiredTypes",)   # the other settings are true or false
TOP_LEVEL = ("schemaVersion", "publication", "files", "media", "settings")


# --- the document ---------------------------------------------------------------------------------------------------------------------------------

def _safe_path(name: Any) -> str | None:
    """A message when ``name`` is not a plain relative path inside the design system (no absolute path, no ``..``, no empty part)."""
    if not isinstance(name, str) or not name:
        return "must be a file path"
    path = PurePosixPath(name)
    if path.is_absolute() or "\\" in name or any(part in ("", ".", "..") for part in name.split("/")):
        return "must be a relative path inside the design system"
    return None


def validate_design_system_document(document: Any, scope: str = "publication") -> list[Problem]:
    """Every structural problem with a stored design system document, by field path. Whether the mapping and tokens can draw is ``load_design_system``'s check."""
    from papyrus_content.model_attachments import attachment_safe_id

    if scope != "publication":
        return [Problem("", "A design system belongs to the site; a section has none of its own.", "publication_only")]
    if not isinstance(document, dict):
        return [Problem("", "A design system document is an object.")]
    problems: list[Problem] = []
    if document.get("schemaVersion") != SCHEMA_VERSION:
        problems.append(Problem("schemaVersion", f"must be {SCHEMA_VERSION}"))
    for key in document:
        if key not in TOP_LEVEL:
            problems.append(Problem(key, "is not a field of a design system document", "unknown_field"))
    if "publication" in document and not (isinstance(document["publication"], str) and document["publication"].strip()):
        problems.append(Problem("publication", "must be a non-empty name"))
    files, media = document.get("files"), document.get("media", {})
    if not isinstance(files, dict):
        problems.append(Problem("files", "must be an object of file path to text"))
        files = {}
    if not isinstance(media, dict):
        problems.append(Problem("media", "must be an object of file path to {sha256, byteSize}"))
        media = {}
    for name, text in files.items():
        message = _safe_path(name)
        if message:
            problems.append(Problem(f"files.{name}", message))
        elif not isinstance(text, str):
            problems.append(Problem(f"files.{name}", "must be the file's text"))
    if MAPPING_FILE not in files:
        problems.append(Problem(f"files.{MAPPING_FILE}", "is required"))
    seen: dict[str, str] = {}
    for name, entry in media.items():
        message = _safe_path(name)
        if message:
            problems.append(Problem(f"media.{name}", message))
            continue
        if name in files:
            problems.append(Problem(f"media.{name}", "is also a text file"))
        if not (isinstance(entry, dict) and re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256") or "")) and isinstance(entry.get("byteSize"), int)):
            problems.append(Problem(f"media.{name}", "needs a sha256 and a byteSize"))
        stored_as = attachment_safe_id(name)
        if stored_as in seen:
            problems.append(Problem(f"media.{name}", f"would be stored under the same name as {seen[stored_as]}"))
        seen[stored_as] = name
    settings = document.get("settings", {})
    if not isinstance(settings, dict):
        problems.append(Problem("settings", "must be an object"))
    else:
        for key, value in settings.items():
            if key not in SETTINGS:
                problems.append(Problem(f"settings.{key}", f"is not a figure setting; the settings are {', '.join(SETTINGS)}", "unknown_field"))
            elif key in LIST_SETTINGS:
                if not (isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)):
                    problems.append(Problem(f"settings.{key}", "must be a list of Story type names, for example [\"article\", \"post\"]"))
            elif not isinstance(value, bool):
                problems.append(Problem(f"settings.{key}", "must be true or false"))
    return problems


# --- the BackendSource ----------------------------------------------------------------------------------------------------------------------------

class BackendSource:
    """A ``DesignSystemSource`` over a stored design system. Text answers come from the document; a font is fetched (and checked against its hash) when asked for."""

    def __init__(self, document: dict, fetch_media, description: str):
        self.document = document
        self._files: dict[str, str] = document["files"]
        self._media: dict[str, dict] = document.get("media") or {}
        self._fetch = fetch_media
        self._cache: dict[str, bytes] = {}
        self.description = description

    def read_text(self, name: str) -> str:
        if name in self._files:
            return self._files[name]
        raise DesignSystemError(f"design system {self.description}: has no file {name}")

    def read_bytes(self, name: str) -> bytes:
        if name in self._media:
            if name not in self._cache:
                body = self._fetch(name)
                if hashlib.sha256(body).hexdigest() != self._media[name]["sha256"]:
                    raise DesignSystemError(f"design system {self.description}: the stored font {name} does not match its hash")
                self._cache[name] = body
            return self._cache[name]
        if name in self._files:
            return self._files[name].encode("utf-8")
        raise DesignSystemError(f"design system {self.description}: has no file {name}")

    def list_examples(self) -> list[str]:
        return sorted(str(PurePosixPath(name).parent) for name in self._files if re.fullmatch(r"examples/[^/]+/figure\.svg", name))

    def file_names(self) -> list[str]:
        return sorted([*self._files, *self._media])


# --- collecting a design system to push ------------------------------------------------------------------------------------------------------------

def collect(source: DesignSystemSource, settings: dict | None = None) -> tuple[dict, dict[str, bytes]]:
    """The document and the font files for a design system from any source, after checking that it can be used to draw (roles, tokens, a dark value for every color).

    Only what a design system is made of is collected: ``mapping.json``, the tokens file it names, the fonts it names and each example's ``figure.svg`` and ``figure.json``.
    """
    design_system = load_design_system(source)   # raises DesignSystemError naming the first thing to fix
    mapping = design_system.mapping
    files = {MAPPING_FILE: source.read_text(MAPPING_FILE)}
    if "tokens" not in mapping:
        files[mapping["tokens_file"]] = source.read_text(mapping["tokens_file"])
    assets: dict[str, bytes] = {}
    for font in mapping.get("fonts", {}).values():
        if font.get("file"):
            assets[font["file"]] = source.read_bytes(font["file"])
    for example in source.list_examples():
        for leaf in ("figure.svg", "figure.json"):
            files[f"{example}/{leaf}"] = source.read_text(f"{example}/{leaf}")
    document: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION, "publication": design_system.name, "files": files,
        "media": {name: {"sha256": hashlib.sha256(body).hexdigest(), "byteSize": len(body)} for name, body in sorted(assets.items())},
    }
    if settings:
        document["settings"] = dict(settings)
    return document, assets


def read_settings_file(folder: Path | str) -> dict | None:
    """The settings.json of a design system folder, or None when it has none."""
    path = Path(folder) / SETTINGS_FILE
    if not path.is_file():
        return None
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise DesignSystemError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(settings, dict):
        raise DesignSystemError(f"{path} must be an object, for example {{\"requireDarkFigures\": true}}")
    return settings


# --- the store ------------------------------------------------------------------------------------------------------------------------------------

@dataclass
class StoredDesignSystem:
    document: dict
    reference: dict
    row: dict
    source: BackendSource
    problems: list[str] = field(default_factory=list)

    @property
    def settings(self) -> dict:
        return dict(self.document.get("settings") or {})

    @property
    def version(self) -> int:
        return int(self.reference["versionNumber"])

    def write_to(self, folder: Path | str) -> list[str]:
        """Write the design system into a folder as it was pushed (text verbatim, fonts as bytes, settings.json when set). Returns the paths written."""
        root = Path(folder).resolve()
        written: list[str] = []
        names = self.source.file_names()
        for name in names:
            target = (root / name).resolve()
            if root not in target.parents:   # the document is validated on save; this guards a record someone wrote by hand
                raise DesignSystemError(f"{name} points outside the folder")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.source.read_bytes(name))
            written.append(name)
        if self.settings:
            (root / SETTINGS_FILE).write_text(json.dumps(self.settings, indent=2) + "\n", encoding="utf-8")
            written.append(SETTINGS_FILE)
        return written


class DesignSystemRecords:
    """Reading and pushing the site's design system. Every read is an index query plus a download; nothing lists or scans a table."""

    def __init__(self, client, files=None):
        self.client = client
        self.store = GuidelineStore(client, files)

    @property
    def slug(self) -> str:
        return slug_for(KIND)

    def current_row(self) -> dict | None:
        """The catalog row of the current version (one index query, nothing downloaded): enough to know that a design system exists."""
        return self.store.current_row(KIND)

    def history(self) -> list[dict]:
        return self.store.history(KIND)

    def read(self, version: int | None = None) -> StoredDesignSystem | None:
        found = self.store.read(KIND, version=version)
        if found is None:
            return None
        row, document = found["row"], found["document"]
        problems = validate_design_system_document(document)
        if problems:
            raise DesignSystemError("the stored design system is not valid: " + "; ".join(f"{p.path or 'document'} {p.message}" for p in problems))
        attachments = self.store.assets_of(row)

        def fetch(name: str) -> bytes:
            if name not in attachments:
                raise DesignSystemError(f"the stored design system has no file {name}")
            return self.store.get_asset(attachments[name])

        site = document.get("publication") or "the site"
        return StoredDesignSystem(document, found["reference"], row, BackendSource(document, fetch, f"{site} (stored version {found['reference']['versionNumber']})"))

    def settings(self) -> dict:
        found = self.store.read(KIND)
        return dict((found["document"].get("settings") or {}) if found else {})

    def plan_push(self, source: DesignSystemSource, settings: dict | None = None) -> tuple[dict, dict[str, bytes], dict | None]:
        """What a push would store: the document, the fonts and the current row (None for the first version). Writes nothing."""
        current = self.current_row()
        if settings is None and current is not None:
            settings = self.settings()          # a folder with no settings.json keeps the site's settings
        document, assets = collect(source, settings)
        problems = validate_design_system_document(document)
        if problems:
            raise DesignSystemError("the design system cannot be stored: " + "; ".join(f"{p.path or 'document'} {p.message}" for p in problems))
        return document, assets, current

    def push(self, source: DesignSystemSource, *, actor: str, reason: str, settings: dict | None = None, now: str | None = None) -> dict:
        """Store the design system as the lineage's next version. ``{changed, reference}``; an unchanged design system makes no version."""
        document, assets, current = self.plan_push(source, settings)
        return self.store.save(KIND, document, expected_current_version_id=current["id"] if current else "none", actor=actor, reason=reason, now=now, assets=assets)


def site_requires_dark_figures(client) -> bool:
    """The site's ``requireDarkFigures`` setting: False when the site has no design system or does not set it."""
    return bool(DesignSystemRecords(client).settings().get("requireDarkFigures"))


def open_records() -> DesignSystemRecords:
    """The records of the site the CLI is signed in to (or the backend the IAM lane points at)."""
    from papyrus_content.graphql_authoring import create_authoring_client

    client, _ = create_authoring_client()
    return DesignSystemRecords(client)


__all__ = ["BackendSource", "DesignSystemRecords", "StoredDesignSystem", "collect", "digest_of", "open_records", "site_requires_dark_figures", "validate_design_system_document"]
