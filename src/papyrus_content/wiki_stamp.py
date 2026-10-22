"""Review stamps of public wiki pages (PPY-f927a1, lifecycle epic PPY-964472).

A wiki page is an Item of type ``wiki_page``. Its front matter says who last put it in front of readers::

    review: {actor: ai, name: null, on: 2026-10-22}      # edited by an AI agent
    review: {actor: human, name: Ada Lovelace, on: 2026-10-22}
    superseded_by: /wiki/new-page/                         # the page is dead; readers are sent to the replacement

The stamp is written by the command that publishes the page (``papyrus knowledge wiki publish``) and checked, without a
language model, by :func:`stamp_problems` before any publish. Generated text that nobody accepted has no stamp, so it
is never public. Everything here is pure: no clock, no storage.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

WIKI_PAGE_ITEM_TYPE = "wiki_page"
REVIEW_KEY = "review"
SUPERSEDED_KEY = "superseded_by"
UPDATED_KEY = "updated"
ACTOR_AI = "ai"
ACTOR_HUMAN = "human"
ACTORS = (ACTOR_AI, ACTOR_HUMAN)
UNREVIEWED_TEXT = "Draft, not yet reviewed"


@dataclass(frozen=True)
class Review:
    actor: str
    name: str | None
    on: str


def _day(value: Any) -> str | None:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip()).isoformat()
        except ValueError:
            return None
    return None


def review_mapping(actor: str, name: str | None, on: str) -> dict:
    """The ``review`` front matter value, as written by the publish command."""
    problems = _problems({"actor": actor, "name": name, "on": on})
    if problems:
        raise ValueError("; ".join(problems))
    return {"actor": actor, "name": " ".join(name.split()) if name else None, "on": _day(on)}


def _problems(raw: Any) -> list[str]:
    if not isinstance(raw, Mapping):
        return ["review must be a mapping of actor, name and on"]
    problems: list[str] = []
    if raw.get("actor") not in ACTORS:
        problems.append(f"review.actor must be one of {', '.join(ACTORS)}")
    name = raw.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip() or "@" in name):
        problems.append("review.name must be a name, with no email address, or null")
    if _day(raw.get("on")) is None:
        problems.append("review.on must be a date such as 2026-10-22")
    return problems


def parse_review(front_matter: Mapping[str, Any]) -> Review | None:
    """The stamp of a front matter; ``None`` when it has none or an invalid one."""
    raw = front_matter.get(REVIEW_KEY)
    if _problems(raw):
        return None
    name = raw.get("name")
    return Review(actor=raw["actor"], name=" ".join(name.split()) if name else None, on=_day(raw["on"]))


def stamp_problems(front_matter: Mapping[str, Any]) -> list[str]:
    """What stops a wiki page from being published: an empty list means the stamp is in order."""
    if REVIEW_KEY not in front_matter or front_matter.get(REVIEW_KEY) is None:
        return ["the page has no review stamp (front matter review: actor, name, on)"]
    problems = _problems(front_matter[REVIEW_KEY])
    superseded = front_matter.get(SUPERSEDED_KEY)
    if superseded is not None and not (isinstance(superseded, str) and superseded.startswith(("/", "https://"))):
        problems.append("superseded_by must be a site path or an https URL")
    return problems


def _written(day: str, date_format: str) -> str:
    return dt.date.fromisoformat(day).strftime(date_format) if date_format else day


def stamp_text(review: Review | None, date_format: str = "") -> str:
    """The words readers see. Text an AI agent edited is a draft until a person reviews it, so it never reads as attested."""
    if review is None:
        return UNREVIEWED_TEXT
    when = _written(review.on, date_format)
    if review.actor == ACTOR_AI:
        return f"{UNREVIEWED_TEXT}. Edited by AI on {when}"
    return f"Reviewed by {review.name} on {when}" if review.name else f"Reviewed by an editor on {when}"
