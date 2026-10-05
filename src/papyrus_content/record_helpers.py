"""Record helpers shared by seeding and publishing."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {key: entry for key, entry in value.items() if entry is not None}


def content_hash_for(value: Any) -> str:
    return "sha256:" + hashlib.sha256(stable_stringify(value).encode("utf-8")).hexdigest()


def stable_stringify(value: Any) -> str:
    if value is None or not isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(stable_stringify(entry) for entry in value) + "]"
    entries = [(key, entry) for key, entry in value.items() if entry is not None]
    return "{" + ",".join(f"{json.dumps(key, separators=(',', ':'))}:{stable_stringify(entry)}" for key, entry in sorted(entries)) + "}"


def to_aws_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def slugify(value: str) -> str:
    return re.sub(r"(^-+|-+$)", "", re.sub(r"[^a-z0-9]+", "-", value.lower()))
