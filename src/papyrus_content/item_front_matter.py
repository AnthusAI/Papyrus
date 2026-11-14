"""Reading a stored Item row without the newsletter or the data store: its public path and its front matter.

Kept free of third-party imports at module level so the functions that bundle only the standard library (the image service, which also serves the announcement
operations) can read an Item's path and front matter without pulling in the newsletter's DynamoDB store.
"""
from __future__ import annotations

import json
from typing import Any, Mapping


def item_path(section: str | None, slug: str, url_style: str) -> str:
    base = f"/{section}" if section else ""
    if url_style == "directory":
        return f"{base}/{slug}/"
    if url_style == "clean":
        return f"{base}/{slug}"
    return f"{base}/{slug}.html"


def parse_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def front_matter(row: Mapping[str, Any]) -> dict[str, Any]:
    text = parse_object(row.get("metadata")).get("frontMatterYaml")
    if not isinstance(text, str) or not text.strip():
        return {}
    import yaml

    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}
