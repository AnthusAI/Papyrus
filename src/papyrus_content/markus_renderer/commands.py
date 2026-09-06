"""CLI entry for ``papyrus renderers markus-build``."""

from __future__ import annotations

import json
from pathlib import Path

from ..env import PAPYRUS_ROOT
from ..options import normalize_string, parse_options
from .build import DEFAULT_CONTENT_DIR, DEFAULT_OUT_DIR, DEFAULT_THEME, build_markus_site


def markus_build(flags: list[str]) -> None:
    options = parse_options(flags)
    content_raw = normalize_string(options.get("content"))
    out_raw = normalize_string(options.get("out"))
    theme = normalize_string(options.get("theme")) or DEFAULT_THEME
    markus_executable = normalize_string(options.get("markus")) or "markus"

    content_dir = Path(content_raw) if content_raw else DEFAULT_CONTENT_DIR
    if not content_dir.is_absolute():
        content_dir = PAPYRUS_ROOT / content_dir

    out_dir = Path(out_raw) if out_raw else DEFAULT_OUT_DIR
    if not out_dir.is_absolute():
        out_dir = PAPYRUS_ROOT / out_dir

    result = build_markus_site(
        content_dir=content_dir,
        out_dir=out_dir,
        theme=theme,
        markus_executable=markus_executable,
    )

    payload = {
        "ok": True,
        "command": "renderers markus-build",
        "contentDir": str(result.content_dir),
        "outDir": str(result.out_dir),
        "theme": theme,
        "pages": [str(path.relative_to(result.out_dir)) for path in result.pages],
    }
    if options.get("json"):
        print(json.dumps(payload, indent=2))
    else:
        print(f"Built Markus static site: {result.out_dir}")
        for page in result.pages:
            print(f"  - {page.relative_to(result.out_dir)}")
