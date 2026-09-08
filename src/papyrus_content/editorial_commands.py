from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .editorial_diagnosis import diagnose_draft
from .editorial_style import load_style_profile


def editorial_diagnose(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="papyrus editorial diagnose")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--draft", help="Path to the draft file (read-only).")
    input_group.add_argument("--text", help="Draft text to diagnose without reading a file.")
    parser.add_argument("--profile", required=True, help="Path to the style profile YAML.")
    parser.add_argument("--output", default="", help="Optional path to write diagnostic JSON.")
    args = parser.parse_args(flags)

    profile_path = Path(args.profile).resolve()
    if args.draft:
        draft_path = Path(args.draft).resolve()
        if not draft_path.is_file():
            raise ValueError(f"Draft file not found: {draft_path}")
        draft_text = draft_path.read_text(encoding="utf-8")
    else:
        draft_text = args.text

    style_profile = load_style_profile(profile_path)
    diagnosis = diagnose_draft(draft_text, style_profile=style_profile)
    rendered = json.dumps(diagnosis, indent=2) + "\n"

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.write_text(rendered, encoding="utf-8")
        return

    sys.stdout.write(rendered)
