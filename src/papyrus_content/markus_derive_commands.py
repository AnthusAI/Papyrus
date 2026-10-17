"""CLI entry for ``papyrus content markus-derive`` (PPY-e169c5)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .markus_renderer.content_markup import split_front_matter
from .markus_renderer.derive import derive_body, envelope_byte_count
from .options import normalize_string, parse_options


def content_markus_derive(flags: list[str]) -> None:
    options = parse_options(flags)
    file_path = normalize_string(options.get("file"))
    use_stdin = bool(options.get("stdin"))
    if bool(file_path) == use_stdin:
        raise ValueError("Pass exactly one of --file <path.md> or --stdin.")

    text = sys.stdin.read() if use_stdin else Path(file_path).read_text(encoding="utf-8")
    front_matter_yaml, body_markus = split_front_matter(text)
    derivation = derive_body(front_matter_yaml, body_markus)

    payload = {
        "ok": derivation.ok,
        "errors": [error.to_dict() for error in derivation.errors],
        "bodyIrBytes": envelope_byte_count(derivation.body_ir) if derivation.body_ir else 0,
    }
    if options.get("emit-ir") and derivation.body_ir is not None:
        payload["bodyIr"] = derivation.body_ir
    print(json.dumps(payload, indent=2))
    if not derivation.ok:
        raise SystemExit(1)
