"""Validate a SiteConfig against ``schema.json`` (v1) with ``jsonschema`` (Draft 2020-12).

The schema stays plain JSON Schema (the TypeScript twin reads the same file). ``additionalProperties`` is false everywhere, so a setting outside v1
fails the schema; the messages here name the setting, and say why when it is one a dedicated site can set (``REFUSED_SETTINGS``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

SCHEMA = json.loads((Path(__file__).with_name("schema.json")).read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
_VALIDATOR = Draft202012Validator(SCHEMA)

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


def _where(path) -> str:
    text = ""
    for part in path:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text


def schema_messages(error: ValidationError, subject: str = "SiteConfig") -> list[str]:
    """One message per problem, each naming the setting (a bad object can carry several refused keys); ``subject`` names the document type."""
    where = _where(error.absolute_path)
    prefix = f"{where}: " if where else ""
    rule, schema = error.validator, error.validator_value
    if rule == "required":
        return [f"{prefix}{name!r} is required" for name in schema if name not in error.instance]
    if rule == "additionalProperties":
        messages = []
        for name in sorted(set(error.instance) - set(error.schema.get("properties", {}))):
            here = f"{where}.{name}" if where else name
            reason = REFUSED_SETTINGS.get(name)
            messages.append(f"{here}: refused on the shared tier, {reason}" if reason else f"{here}: is not a {subject} setting")
        return messages
    if rule == "const":
        return [f"{prefix}must be {schema!r}"]
    if rule == "enum":
        return [f"{prefix}must be one of {', '.join(map(repr, schema))}"]
    if rule == "type":
        return [f"{prefix}must be a {schema}"]
    if rule == "minLength":
        return [f"{prefix}must not be empty"]
    if rule == "maxLength":
        return [f"{prefix}is longer than {schema} characters"]
    if rule == "maxItems":
        return [f"{prefix}has more than {schema} entries"]
    if rule == "pattern":
        return [f"{prefix}{error.instance!r} is not in the allowed form"]
    return [f"{prefix}{error.message}"]


def validate_site_config(config: object) -> list[str]:
    """Every problem with ``config``, each naming the setting; an empty list means it is valid for the shared tier."""
    if not isinstance(config, Mapping):
        return ["SiteConfig: must be an object"]
    errors = [message for error in sorted(_VALIDATOR.iter_errors(config), key=lambda e: list(map(str, e.absolute_path))) for message in schema_messages(error)]
    sections = config.get("sections")
    if isinstance(sections, list):
        for key in ("name", "slug"):
            seen = [s.get(key) for s in sections if isinstance(s, Mapping)]
            duplicates = sorted({v for v in seen if v is not None and seen.count(v) > 1})
            if duplicates:
                errors.append(f"sections: {key} {', '.join(map(repr, duplicates))} is used more than once")
    return errors
