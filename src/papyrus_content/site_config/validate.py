"""Validate a SiteConfig against ``schema.json`` (v1).

The validator implements only the schema keywords ``schema.json`` uses, so the file stays plain JSON Schema (the TypeScript twin reads the same
file) without adding a dependency to the Python environment. Errors are strings that name the setting, so an owner sees which one was refused.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

SCHEMA = json.loads((Path(__file__).with_name("schema.json")).read_text(encoding="utf-8"))

#: Settings a dedicated site can have in projection.json that a shared tenant may not set in v1, with the reason shown to the owner.
REFUSED_SETTINGS = {
    "hooks": "hooks are code; the shared tier never loads them",
    "css": "custom CSS is not allowed; brand changes go through the brand pack",
    "customCss": "custom CSS is not allowed; brand changes go through the brand pack",
    "stylesheet": "custom CSS is not allowed; brand changes go through the brand pack",
    "stylesheets": "custom CSS is not allowed; brand changes go through the brand pack",
    "scripts": "scripts are code; the shared tier never loads them",
    "chrome": "page chrome carries stylesheets and scripts; use the brand pack",
    "sizes": "sizes are fixed by the shared stylesheet",
    "spacing": "spacing is fixed by the shared stylesheet",
    "imageRatio": "the image ratio is fixed by the shared stylesheet",
    "borders": "borders are fixed by the shared stylesheet",
    "urls": "URL structure is fixed on the shared tier (sections set their slug)",
    "basePath": "the base path is fixed on the shared tier",
    "redirects": "pattern redirects are not available on the shared tier",
    "imagePipeline": "the image pipeline is fixed on the shared tier",
    "cache": "cache settings are fixed on the shared tier",
    "plugins": "plugins are plan entitlements, not settings",
    "citations": "citation links use a fixed default",
}


def _type_ok(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def _resolve(node: Mapping) -> Mapping:
    ref = node.get("$ref")
    if not ref:
        return node
    target: object = SCHEMA
    for part in ref.removeprefix("#/").split("/"):
        target = target[part]  # type: ignore[index]
    return target  # type: ignore[return-value]


def _check(value: object, node: Mapping, path: str, errors: list[str]) -> None:
    node = _resolve(node)
    if "const" in node and (value != node["const"] or isinstance(value, bool) != isinstance(node["const"], bool)):
        errors.append(f"{path}: must be {node['const']!r}")
        return
    if "enum" in node and value not in node["enum"]:
        errors.append(f"{path}: must be one of {', '.join(map(repr, node['enum']))}")
        return
    if "type" in node and not _type_ok(value, node["type"]):
        errors.append(f"{path}: must be a {node['type']}")
        return
    if isinstance(value, str):
        if len(value) < node.get("minLength", 0):
            errors.append(f"{path}: must not be empty")
        if len(value) > node.get("maxLength", len(value)):
            errors.append(f"{path}: is longer than {node['maxLength']} characters")
        if "pattern" in node and not re.search(node["pattern"], value):
            errors.append(f"{path}: {value!r} is not in the allowed form")
    if isinstance(value, list):
        if len(value) > node.get("maxItems", len(value)):
            errors.append(f"{path}: has more than {node['maxItems']} entries")
        for index, item in enumerate(value):
            if "items" in node:
                _check(item, node["items"], f"{path}[{index}]", errors)
    if isinstance(value, Mapping):
        properties = node.get("properties", {})
        for name in node.get("required", ()):
            if name not in value:
                errors.append(f"{path}: {name!r} is required" if path != "SiteConfig" else f"{name!r} is required")
        for name, item in value.items():
            where = name if path == "SiteConfig" else f"{path}.{name}"
            if name in properties:
                _check(item, properties[name], where, errors)
            elif node.get("additionalProperties") is False:
                if name in REFUSED_SETTINGS:
                    errors.append(f"{where}: refused on the shared tier, {REFUSED_SETTINGS[name]}")
                else:
                    errors.append(f"{where}: is not a SiteConfig setting")


def validate_site_config(config: object) -> list[str]:
    """Every problem with ``config``, each naming the setting; an empty list means it is valid for the shared tier."""
    errors: list[str] = []
    if not isinstance(config, Mapping):
        return ["SiteConfig: must be an object"]
    _check(config, SCHEMA, "SiteConfig", errors)
    sections = config.get("sections")
    if isinstance(sections, list):
        for key in ("name", "slug"):
            seen = [s.get(key) for s in sections if isinstance(s, Mapping)]
            duplicates = sorted({v for v in seen if v is not None and seen.count(v) > 1})
            if duplicates:
                errors.append(f"sections: {key} {', '.join(map(repr, duplicates))} is used more than once")
    return errors
