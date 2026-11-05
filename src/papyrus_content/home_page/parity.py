"""``papyrus home-page parity``: render a site's pages from the file and from the public index, into two scratch directories, and compare them before a site flips.

Nothing is written to the site: both renders go to local directories, and the backend is only read. A page that differs is listed with the first differing card, and
a page whose cards are the same but ordered differently only where their confidences round to the same percentage is classed ``rounding tier`` (the snapshot ranks on the
prediction rounded to two places, the index on the stored prediction; docs/plans/public-blocks-from-indexes.md, decision 1). Anything else is a difference to look at
before the flip.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from typing import Any

CARD = re.compile(r'<li>(<(?:article class="home-page-tile"|div class="home-page-row").*?)</li>', re.S)
TITLE = re.compile(r'class="home-page-title">(?:<a [^>]*>)?(?P<title>[^<]*)')
PERCENT = re.compile(r"(\d+)%(?: confidence|<span[^>]*> confidence)")
IDENTICAL, ROUNDING_TIER, DIFFERENT, MISSING = "identical", "rounding tier", "different", "missing"


def cards_of(page: str) -> list[str]:
    return [match.group(1) for match in CARD.finditer(page)]


def _title(card: str) -> str:
    found = TITLE.search(card)
    return html.unescape(found["title"]) if found else card[:60]


def _first_difference(snapshot: str, index: str) -> str:
    left, right = cards_of(snapshot), cards_of(index)
    for position, (a, b) in enumerate(zip(left, right), start=1):
        if a != b:
            return f"card {position}: the file has {_title(a)!r}, the index has {_title(b)!r}"
    if len(left) != len(right):
        return f"the file has {len(left)} cards, the index has {len(right)}"
    return "the pages differ outside their cards"


def _rounding_tier_only(snapshot: str, index: str) -> bool:
    """True when the two pages have the same cards in a different order and every card that moved shares its confidence percentage with the card it swapped with."""
    left, right = cards_of(snapshot), cards_of(index)
    if sorted(left) != sorted(right) or left == right:
        return False
    if re.sub(CARD, "", snapshot) != re.sub(CARD, "", index):
        return False   # something outside the cards differs
    percentages = {card: PERCENT.search(card).group(1) if PERCENT.search(card) else None for card in left}
    for a, b in zip(left, right):
        if a != b and (percentages[a] is None or percentages[a] != percentages[b]):
            return False
    return True


def _list_items(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("- [")]


def compare_pages(snapshot: Mapping[str, str], index: Mapping[str, str]) -> dict[str, Any]:
    """``{pages, identical, differing: [{page, kind, first}], missing: [...]}`` for two ``{page key: text}`` maps rendered from the same data.

    A Markdown twin lists the same References as its page, so it is a rounding-tier difference exactly when its page is and it holds the same items."""
    differing: list[dict[str, str]] = []
    missing = sorted(set(snapshot) ^ set(index))
    identical = 0
    tier_pages: set[str] = set()
    for key in sorted(set(snapshot) & set(index), key=lambda name: name.endswith(".md")):   # pages first, so their twins can follow them
        if snapshot[key] == index[key]:
            identical += 1
            continue
        if key.endswith(".md"):
            twin = key[:-3] + ".html"
            same_items = sorted(_list_items(snapshot[key])) == sorted(_list_items(index[key]))
            only_order = same_items and [line for line in snapshot[key].splitlines() if not line.startswith("- [")] == [line for line in index[key].splitlines() if not line.startswith("- [")]
            kind = ROUNDING_TIER if only_order and twin in tier_pages else DIFFERENT
            first = next((f"item {position}: the file has {a!r}, the index has {b!r}" for position, (a, b) in enumerate(zip(_list_items(snapshot[key]), _list_items(index[key])), start=1) if a != b),
                         "the pages differ outside their list")
        else:
            kind = ROUNDING_TIER if _rounding_tier_only(snapshot[key], index[key]) else DIFFERENT
            first = _first_difference(snapshot[key], index[key])
            if kind == ROUNDING_TIER:
                tier_pages.add(key)
        differing.append({"page": key, "kind": kind, "first": first})
    return {"pages": len(set(snapshot) | set(index)), "identical": identical, "differing": differing, "missing": missing,
            "ok": not missing and all(item["kind"] == ROUNDING_TIER for item in differing)}


def parity_report(client: Any, build: Any, *, site: str | None = None, workers: int = 1) -> dict[str, Any]:
    """Render every page that places a Reference from the file and from the index, and compare them.

    ``build(variant)`` returns ``(context, directory)`` for ``"snapshot"`` or ``"index"``: a projection context that writes into its own scratch directory. Both renders read
    the backend and write nothing else."""
    from dataclasses import replace
    from pathlib import Path

    from .render import run_home_page_render
    from .task import home_page_settings_of, reader_pages_of, run_home_page_snapshot

    rendered: dict[str, dict[str, str]] = {}
    for variant in ("snapshot", "index"):
        context, directory = build(variant)
        settings = home_page_settings_of(context.projector)
        settings = replace(settings, references=replace(settings.references, source=variant))
        if variant == "snapshot":
            run_home_page_snapshot(context, client, settings, site=site, workers=workers)
        else:
            run_home_page_render(context, client, settings, site=site)
        root = Path(directory)
        rendered[variant] = {key: (root / key).read_text(encoding="utf-8") for key in sorted(reader_pages_of(context.projector))
                             if key.endswith((".html", ".md")) and (root / key).is_file()}
    return compare_pages(rendered["snapshot"], rendered["index"])
