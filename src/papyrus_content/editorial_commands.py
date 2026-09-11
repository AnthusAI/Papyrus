from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .editorial_diagnosis import diagnose_draft
from .editorial_diagnosis_schema import validate_diagnosis
from .editorial_markup import render_annotated_markus, render_annotated_xml
from .editorial_options_schema import validate_decisions
from .editorial_rewrite_options import generate_rewrite_options
from .editorial_style import load_style_profile
from .model_defaults import DEFAULT_EDITORIAL_REWRITE_MODEL


def editorial_diagnose(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="papyrus editorial diagnose")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--draft", help="Path to the draft file (read-only).")
    input_group.add_argument("--text", help="Draft text to diagnose without reading a file.")
    parser.add_argument("--profile", required=True, help="Path to the style profile YAML.")
    parser.add_argument("--output", default="", help="Optional path to write diagnostic JSON.")
    parser.add_argument(
        "--markup-out",
        default="",
        help="Optional path to write Markus-annotated Markdown (editorial-finding directives).",
    )
    parser.add_argument(
        "--xml-out",
        default="",
        help="Optional path to write editorial annotation XML.",
    )
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

    if args.markup_out:
        markup_path = Path(args.markup_out).resolve()
        markup_path.write_text(render_annotated_markus(draft_text, diagnosis), encoding="utf-8")

    if args.xml_out:
        xml_path = Path(args.xml_out).resolve()
        xml_path.write_text(render_annotated_xml(draft_text, diagnosis), encoding="utf-8")

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.write_text(rendered, encoding="utf-8")
        return

    sys.stdout.write(rendered)


def editorial_options(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="papyrus editorial options")
    parser.add_argument("--draft", required=True, help="Path to the draft file (read-only).")
    parser.add_argument("--profile", required=True, help="Path to the style profile YAML.")
    parser.add_argument("--diagnosis", required=True, help="Path to validated diagnostic JSON.")
    parser.add_argument("--decisions", required=True, help="Path to steering decisions JSON.")
    parser.add_argument("--output", default="", help="Optional path to write options JSON.")
    parser.add_argument("--model", default=DEFAULT_EDITORIAL_REWRITE_MODEL, help="OpenAI model id.")
    parser.add_argument(
        "--skill",
        default="",
        help="Optional path to editorial rewrite skill YAML.",
    )
    args = parser.parse_args(flags)

    draft_path = Path(args.draft).resolve()
    if not draft_path.is_file():
        raise ValueError(f"Draft file not found: {draft_path}")
    draft_text = draft_path.read_text(encoding="utf-8")

    diagnosis_path = Path(args.diagnosis).resolve()
    decisions_path = Path(args.decisions).resolve()
    diagnosis_payload = json.loads(diagnosis_path.read_text(encoding="utf-8"))
    decisions_payload = json.loads(decisions_path.read_text(encoding="utf-8"))
    if not isinstance(decisions_payload, list):
        raise ValueError("Decisions JSON must be a list.")

    style_profile = load_style_profile(Path(args.profile).resolve())
    validate_diagnosis(diagnosis_payload)
    validate_decisions(decisions_payload)

    options = generate_rewrite_options(
        draft_text,
        style_profile=style_profile,
        diagnosis=diagnosis_payload,
        decisions=decisions_payload,
        model=args.model,
        skill_path=args.skill or None,
    )
    rendered = json.dumps(options, indent=2) + "\n"

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.write_text(rendered, encoding="utf-8")
        return

    sys.stdout.write(rendered)
