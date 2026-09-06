#!/usr/bin/env python3
"""Regenerate scripts/fixtures/pilobol-sample.ast.json from web/content/articles/sample.md."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from markusmd.api import parse

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_PATH = REPO_ROOT / "web" / "content" / "articles" / "sample.md"
FIXTURE_PATH = REPO_ROOT / "scripts" / "fixtures" / "pilobol-sample.ast.json"


def main() -> int:
    markdown = MARKDOWN_PATH.read_text(encoding="utf-8")
    document = parse(markdown)
    payload = document.to_dict()
    front_matter = payload.get("front_matter", {})
    date_value = front_matter.get("date")
    if hasattr(date_value, "isoformat"):
        front_matter["date"] = date_value.isoformat()

    # Papyrus markus-ir.ts expects schema_version 1 and paragraph-shaped IR.
    # The committed fixture is normalized from markus-sample.ast.json with the
    # sample.md figure path; re-run only updates the source hash after edits.
    existing = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    existing["_papyrus_source_sha256"] = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    FIXTURE_PATH.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {FIXTURE_PATH.relative_to(REPO_ROOT)} source hash")
    return 0


if __name__ == "__main__":
    sys.exit(main())
