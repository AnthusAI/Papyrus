"""The projection metadata stored on a ``PublishedItem`` at publish time.

Front matter is parsed once, when the item is published, and kept as JSON
under ``metadata.projection``. A projection that needs every item's front
matter (listing pages, collections) reads that JSON instead of parsing YAML
again on every invocation.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from ..markus_renderer.derive import compose_source
from ..markus_renderer.pages import read_title

PROJECTION_METADATA_KEY = "projection"


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def parse_front_matter(front_matter_yaml: str | None) -> dict:
    if not front_matter_yaml or not front_matter_yaml.strip():
        return {}
    import yaml

    loaded = yaml.safe_load(front_matter_yaml)
    if not isinstance(loaded, dict):
        return {}
    return json.loads(json.dumps(loaded, default=_json_default))


def projection_metadata(front_matter_yaml: str | None) -> dict:
    return {
        "frontMatter": parse_front_matter(front_matter_yaml),
        "pageTitle": read_title(compose_source(front_matter_yaml, ""), None),
    }
