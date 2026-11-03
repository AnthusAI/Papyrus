"""`papyrus references search "agent memory"`: the References page search box, from the command line.

It asks the site's `searchReferences` query (the one the newsroom References page uses) with the `papyrus login` session. Words and meaning run
together on the site; the answer is a page of References, rated or not, with how each was matched. Read-only: the only request is that one query. There
is no AWS lane: this module never imports boto3, reads an AWS profile or falls back to IAM, and every refusal is one line and a non-zero exit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from . import signed_in_lane as lane
from .signed_in_lane import Refusal

SEARCH_QUERY = "query SearchReferences($input: AWSJSON!) { searchReferences(input: $input) }"
SHOW_CHOICES = ("unrated", "rated", "all")
FIELD_LABELS = {"title": "title", "authors": "author", "sourceUri": "link", "externalItemId": "id"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="papyrus references search", add_help=True,
                                     description="Read-only: find References by words and by meaning through your `papyrus login` session (no AWS credentials)")
    parser.add_argument("query", nargs="+", help="What to look for, such as: agent memory")
    parser.add_argument("--site", help="Which signed-in site, such as shipped.anth.us (needed when several are signed in)")
    parser.add_argument("--show", choices=SHOW_CHOICES, default="all", help="unrated, rated (accepted or rejected) or all (default)")
    parser.add_argument("--limit", type=int, default=24, help="How many References per page (1 to 100, default 24)")
    parser.add_argument("--cursor", help="Continue after this cursor (the `nextCursor` of the previous page)")
    parser.add_argument("--json", action="store_true", help="Print the raw response")
    return parser


def matched_text(item: dict[str, Any]) -> str:
    """'title, author', 'meaning', or 'title and meaning': the same words the page puts on a card."""
    fields = [FIELD_LABELS.get(name, name) for name in item.get("matchedFields") or []]
    meaning = "meaning" in (item.get("matchedBy") or [])
    text = ", ".join(fields)
    if meaning:
        text = f"{text} and meaning" if text else "meaning"
    return text or "-"


def _clip(value: Any, width: int = 70) -> str:
    text = " ".join(str(value if value not in (None, "") else "-").split())
    return text if len(text) <= width else text[: width - 1] + "..."


def summarize(data: dict[str, Any]) -> str:
    items = data.get("items") or []
    lanes = data.get("lanes") or {}
    out = [f"{len(items)} References"]
    for name, label in (("keyword", "Word search"), ("meaning", "Meaning search")):
        lane_state = lanes.get(name) or {}
        if lane_state.get("status") == "failed":
            out.append(f"{label} unavailable: {lane_state.get('message') or 'no reason given'}")
    for item in items:
        reference = item.get("reference") or {}
        state = str(reference.get("feedStateKey") or "").rsplit("#", 1)[-1] or "-"
        out.append("  " + "  ".join([_clip(reference.get("lineageId"), 36), _clip(state, 7).ljust(7), f"Matched: {matched_text(item)}".ljust(32), _clip(reference.get("title"))]))
    cursor = data.get("nextCursor")
    out.append(f"Next page: --cursor {cursor}" if cursor else "End of results.")
    return "\n".join(out)


def command(argv: list[str], *, client=None, out=None) -> int:
    out = out or sys.stdout
    os.environ["PAPYRUS_GRAPHQL_AUTH"] = "user"   # the signed-in lane only; never IAM
    try:
        args = build_parser().parse_args(argv)
        query = " ".join(args.query).strip()
        if not query:
            raise Refusal("Say what to look for: papyrus references search \"agent memory\".")
        if not 1 <= args.limit <= 100:
            raise Refusal("--limit must be between 1 and 100.")
        payload: dict[str, Any] = {"query": query, "show": args.show, "limit": args.limit}
        if args.cursor:
            payload["cursor"] = args.cursor
        client = client or lane.client(args.site)
        data = lane.fetch(client, SEARCH_QUERY, "searchReferences", {"input": json.dumps(payload)}, noun="Reference search",
                          forbidden=lambda: Refusal("Refused: searching References is for editors and admins; your signed-in account does not have that access."))
        lanes = data.get("lanes") or {}
        if all((lanes.get(name) or {}).get("status") == "failed" for name in ("keyword", "meaning")):
            raise Refusal("Reference search is unavailable: neither word search nor meaning search could run.")
        print(json.dumps(data, indent=2, sort_keys=True) if args.json else summarize(data), file=out)
        return 0
    except Refusal as refusal:
        print(str(refusal), file=sys.stderr)
        return 2
    except ValueError as error:   # AuthError (signed out, expired, no site configured) is a ValueError
        print(f"Not signed in or session unusable: {str(error).splitlines()[0]}", file=sys.stderr)
        return 2
