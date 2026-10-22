"""``papyrus reader feedback export``: reader comments as steering feedback for the Cyclotron loop (docs/reader-steering.md)."""

from __future__ import annotations

import sys
from datetime import datetime

from .graphql_authoring import create_authoring_client
from .options import normalize_string, parse_options
from .reader_steering.feedback_export import encode_lines, feedback_records, list_comments


def valid_since(value: str) -> str:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("--since must be an ISO time such as 2026-10-22T00:00:00Z.") from error
    return value


def reader_feedback(flags: list[str]) -> None:
    if not flags or flags[0] != "export":
        raise ValueError("Usage: papyrus reader feedback export [--since ISO_TIME] [--out FILE]")
    options = parse_options(flags[1:])
    since_text = normalize_string(options.get("since"))
    since = valid_since(since_text) if since_text else None
    out = normalize_string(options.get("out"))
    client, _ = create_authoring_client()
    text = encode_lines(feedback_records(list_comments(client), since))
    if out:
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"reader\tfeedback\texport\t{len(text.splitlines())}\t{out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
