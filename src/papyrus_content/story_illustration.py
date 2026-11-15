"""The evidence behind the checklist step ``illustration`` (docs/story-procedure.md, "The Illustration step").

Pure over a small dict of inputs read once (``inputs_for_item``), so the checklist, ``papyrus stories next`` and the publish gate all give the same answer.
A cover is proved by records, never by hand:

* the Story's front matter names a cover picture (``image``, or ``cover``) that is a stored asset (a ``MediaAsset`` row of the version, matched by ``srcPath``);
* approval is NOT required by default. When a person has approved a cover, that is recorded as metadata in the front matter record ``coverImage`` for that picture
  (``srcPath``): ``approvedBy`` and ``approvedAt``, or ``pickedBy`` and ``pickedAt`` for a stock picture picked in the newsroom's Cover image; the evidence names
  the approver when present. A generated cover carries no credit line and a third-party picture keeps its own;
* where the site requires dark figures (the design system's ``requireDarkFigures``), a figure cover also has a stored dark picture (``imageDark``/``coverDark``
  or the directive's ``srcDark``). A stock photograph has no dark twin and is never asked for one.

Which Story types need a cover is the design-system setting ``illustrationRequiredTypes`` (a list of Item types), ``["article"]`` when unset.
Who approved a cover is never shown to a reader: it is metadata, and any "Approved by NAME" in an image credit is dropped when the page is rendered.
"""

from __future__ import annotations

import json
import re
from typing import Any

SETTING_REQUIRED_TYPES = "illustrationRequiredTypes"
DEFAULT_REQUIRED_TYPES = ("article",)

# The states mirror newsroom_process (not imported here: it imports this module lazily).
DONE, NOT_DONE, UNKNOWN, NOT_APPLICABLE = "done", "not_done", "unknown", "not_applicable"

_DIRECTIVE = re.compile(r"::image\{(.*?)\}", re.S)


def normalize_path(value: Any) -> str:
    """A stored path as ``MediaAsset.metadata.srcPath`` spells it: no leading slash, no ``media/`` prefix."""
    text = str(value or "").strip().lstrip("/")
    return text[len("media/"):] if text.startswith("media/") else text


def default_policy() -> dict[str, Any]:
    return {"requiredTypes": list(DEFAULT_REQUIRED_TYPES), "requireDark": False, "unreadable": False}


def read_policy(client) -> dict[str, Any]:
    """The site's illustration policy from its design-system settings: which types need a cover and whether figures need a dark picture.

    A site with no design system, or no such setting, gets the default (articles need a cover; dark pictures are not required).
    ``unreadable`` is True when the settings could not be read: the default types apply and the dark rule is unknown."""
    try:
        from .figures.records import DesignSystemRecords

        settings = DesignSystemRecords(client).settings()
    except Exception:  # noqa: BLE001 - say so in the evidence instead of guessing at the dark rule
        return {"requiredTypes": list(DEFAULT_REQUIRED_TYPES), "requireDark": False, "unreadable": True}
    types = settings.get(SETTING_REQUIRED_TYPES)
    return {
        "requiredTypes": [str(item) for item in types] if isinstance(types, list) else list(DEFAULT_REQUIRED_TYPES),
        "requireDark": bool(settings.get("requireDarkFigures")),
        "unreadable": False,
    }


def inputs_for_item(client, item: dict[str, Any], metadata: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """What the evidence reads, from one Story version: its type, front matter, body, stored media paths and the site's policy. Two index/record reads."""
    from .projection.stored import parse_front_matter

    try:
        front_matter = parse_front_matter(metadata.get("frontMatterYaml"))
    except Exception:  # noqa: BLE001 - unreadable front matter proves nothing
        front_matter = {}
    media = client.list_by_index("mediaAssetsByItemAndSortKey", item["id"])
    paths: list[str] = []
    alts: dict[str, dict[str, str]] = {}
    for row in media:
        value = row.get("metadata")
        if isinstance(value, str):
            try:
                value = json.loads(value) if value else {}
            except ValueError:
                value = {}
        if isinstance(value, dict) and value.get("srcPath"):
            path = normalize_path(value["srcPath"])
            paths.append(path)
            alts[path] = {"alt": str(row.get("alt") or ""), "brief": str(value.get("brief") or "")}
    return {
        "type": item.get("type"), "frontMatter": front_matter, "body": item.get("bodyMarkus") or "", "mediaPaths": paths, "mediaAlts": alts,
        "policy": policy if policy is not None else read_policy(client),
    }


def is_required(inputs: dict[str, Any]) -> bool:
    """A Story of a listed type needs a cover. A Story with no type yet (it cannot publish until one is chosen) counts as required, so the step is on its
    checklist from the start; once a type the site does not list is chosen, the step reads not applicable."""
    item_type = str(inputs.get("type") or "")
    return item_type in set(inputs["policy"]["requiredTypes"]) or item_type in ("", "untyped")


def _directive_for(body: str, path: str) -> dict[str, str] | None:
    for match in _DIRECTIVE.finditer(body):
        attrs = match.group(1)

        def attribute(name: str) -> str:
            found = re.search(rf"\b{name}\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", attrs)
            return next((part for part in found.groups() if part is not None), "") if found else ""

        if normalize_path(attribute("src")) == path:
            return {"credit": attribute("credit"), "srcDark": attribute("srcDark"), "alt": attribute("alt"), "hasAlt": re.search(r"\balt\s*=", attrs) is not None}
    return None


def _squash(text: Any) -> str:
    return " ".join(str(text or "").lower().split())


def alt_problem(alt: str, brief: str) -> str:
    """Why this alt text is not a description of the picture, or an empty string when it passes. A generation brief is an instruction to the image model
    and never a description, so alt text that is empty, equal to the brief or containing it fails."""
    text = _squash(alt)
    if not text:
        return "has no alt text"
    wanted = _squash(brief)
    if wanted and wanted in text:
        return "has alt text copied from the generation brief, which is an instruction to the image model and not a description of the picture"
    return ""


def cover_evidence(inputs: dict[str, Any] | None) -> tuple[str, str]:
    """``(state, text)``: ``done`` with what proves it, ``not_done`` with what is missing, ``unknown`` when it cannot be told, or ``not_applicable`` for a
    Story type the site does not require a cover for. The text is a reference to a record when done and the reason when not."""
    if not inputs:
        return UNKNOWN, "the cover evidence could not be read"
    if not is_required(inputs):
        return NOT_APPLICABLE, f"this site does not require a cover for {inputs.get('type') or 'this'} Stories"
    front_matter = inputs["frontMatter"]
    stored = set(inputs["mediaPaths"])
    cover = normalize_path(front_matter.get("image") or front_matter.get("cover"))
    if not cover:
        return NOT_DONE, "the Story has no cover picture (front matter `image`)"
    if cover.startswith(("http://", "https://")) or "://" in cover:
        return NOT_DONE, f"the cover {cover} is a remote address, not a stored asset"
    if cover not in stored:
        return NOT_DONE, f"the cover {cover} is not a stored asset of this version"
    record = front_matter.get("coverImage")
    record = record if isinstance(record, dict) and normalize_path(record.get("srcPath")) == cover else {}
    picked_by = str(record.get("pickedBy") or "").strip()
    approver = picked_by or str(record.get("approvedBy") or "").strip()
    approved_at = record.get("pickedAt") if picked_by else record.get("approvedAt")
    directive = _directive_for(inputs["body"], cover)
    policy = inputs["policy"]
    dark = normalize_path((directive or {}).get("srcDark") or front_matter.get("imageDark") or front_matter.get("coverDark"))
    if dark and dark not in stored:
        return NOT_DONE, f"the dark picture {dark} is not a stored asset of this version"
    if not picked_by:   # a figure or generated picture; a stock photograph has no dark twin and is never asked for one
        if policy.get("unreadable") and not dark:
            return UNKNOWN, "the site's requireDarkFigures setting could not be read, so a figure with no dark picture cannot be checked"
        if not dark and policy["requireDark"]:
            return NOT_DONE, f"the figure cover {cover} has no dark picture, and this site requires one (requireDarkFigures): run `papyrus figures render` and save SLUG.dark.png with it"
    recorded = (inputs.get("mediaAlts") or {}).get(cover, {})
    for label, alt in (("the cover's image directive", (directive or {}).get("alt") if (directive or {}).get("hasAlt") else None), ("the cover's media record", recorded.get("alt"))):
        if alt is None:
            continue
        problem = alt_problem(alt, recorded.get("brief", ""))
        if problem:
            return NOT_DONE, f"{label} {problem}: write the alt text from the picture itself (a person or agent who has seen it) and save a new version"
    who = (f", stock picture picked by {approver}" if picked_by else f", approved by {approver}") + (f" on {approved_at}" if approved_at else "") if approver else ""
    return DONE, f"cover {cover}{who}" + (f", dark {dark}" if dark and not picked_by else "")
