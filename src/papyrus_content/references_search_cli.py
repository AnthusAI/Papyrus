"""`papyrus references search "agent memory"`: the References page search box, from the command line.

It is the operator branch of the shared `references search` handler (see command_registry.py): it asks the site's `searchReferences` query (the one the newsroom References page uses) with the `papyrus login` session. Words and meaning run
together on the site; the answer is a page of References, rated or not, with how each was matched. Read-only: the only request is that one query. There
is no AWS lane: this module never imports boto3, reads an AWS profile or falls back to IAM, and every refusal is one line and a non-zero exit.
"""
from __future__ import annotations

import json
from typing import Any

from . import signed_in_lane as lane
from .signed_in_lane import Refusal

SEARCH_QUERY = "query SearchReferences($input: AWSJSON!) { searchReferences(input: $input) }"
SHOW_CHOICES = ["unrated", "rated", "accepted", "rejected", "all"]
DEFAULT_PAGE_SIZE = 24
FIELD_LABELS = {"title": "title", "authors": "author", "sourceUri": "link", "externalItemId": "id"}


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


def operator_reference_search(client, *, query: str, show: str | None, limit: int | None, cursor: str | None) -> dict[str, Any]:
    text = query.strip()
    if not text:
        raise Refusal("Say what to look for: papyrus references search \"agent memory\".")
    payload: dict[str, Any] = {"query": text, "show": show or "all", "limit": limit or DEFAULT_PAGE_SIZE}
    if cursor:
        payload["cursor"] = cursor
    data = lane.fetch(client, SEARCH_QUERY, "searchReferences", {"input": json.dumps(payload)}, noun="Reference search",
                      forbidden=lambda: Refusal("Refused: searching References is for editors and admins; your signed-in account does not have that access."))
    lanes = data.get("lanes") or {}
    if all((lanes.get(name) or {}).get("status") == "failed" for name in ("keyword", "meaning")):
        raise Refusal("Reference search is unavailable: neither word search nor meaning search could run.")
    return data


def registry_flags_from_words(argv: list[str]) -> list[str]:
    """`papyrus references search agent memory --limit 5`: the words before and between the flags are the query."""
    words: list[str] = []
    flags: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token.startswith("--"):
            takes_value = token != "--json" and index + 1 < len(argv) and not argv[index + 1].startswith("--")
            flags.extend(argv[index:index + 2] if takes_value else [token])
            index += 2 if takes_value else 1
        else:
            words.append(token)
            index += 1
    return ["--query", " ".join(words), *flags] if words else flags


def command(argv: list[str]) -> int:
    from .registered_commands import run_registered_command

    return run_registered_command("references:search", registry_flags_from_words(argv))
