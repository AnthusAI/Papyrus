"""Story variations: the different ways one Story could connect to what the newsroom knows, side by side for an editor to choose from (docs/story-variations.md).

A variation is not a version. Versions are a Story's one line of edits (``Item.lineageId`` and ``versionNumber``); variations are alternatives that exist at the same time.
Each makes its own ``point`` and names the ``connections`` it rests on: another Reference, another Story or a Concept. Rows are kept for good: nothing is deleted, and an
editor rejects with a reason, so what was turned down, and why, stays readable by people and by the Story's conversation.

``origin`` says where a variation came from: ``generated`` by an idea run, ``requested`` in the Story's conversation (``requestMessageId`` is the Message that asked, and
``basedOnVariationIds`` the variations it combines), or written by a ``person``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .ids import hash_short
from .publishing import utc_now_iso

MODEL = "StoryVariation"
INDEX = "storyVariationsByStoryAndNumber"

OFFERED, ACCEPTED, REJECTED = "offered", "accepted", "rejected"
GENERATED, REQUESTED, PERSON = "generated", "requested", "person"
ORIGINS = (GENERATED, REQUESTED, PERSON)
REFERENCE, STORY, CONCEPT = "reference", "story", "concept"
CONNECTION_KINDS = (REFERENCE, STORY, CONCEPT)


class VariationRefused(ValueError):
    """The variation or the decision breaks a rule; nothing was written."""


def variations_of(client: Any, story_lineage_id: str) -> list[dict[str, Any]]:
    """The Story's variations, first offered first, with ``connections`` and ``pointCheck`` read back as data."""
    rows = client.list_by_index(INDEX, story_lineage_id)
    return sorted((_read(row) for row in rows), key=lambda row: row["variationNumber"])


def offer_variation(
    client: Any, story_lineage_id: str, *, point: str, headline: str, connections: Sequence[Mapping[str, Any]], origin: str = GENERATED, deck: str | None = None,
    body_markus: str | None = None, section: str | None = None, based_on: Iterable[str] = (), request_message_id: str | None = None, point_check: Mapping[str, Any] | None = None,
    run_id: str | None = None, model: str | None = None, created_by: str | None = None, now: str | None = None,
) -> dict[str, Any]:
    """Adds one variation to a Story and returns it. The same wording offered twice finds the variation already there, so a retried run adds nothing."""
    point, headline = str(point or "").strip(), str(headline or "").strip()
    if not point:
        raise VariationRefused("A variation must make a point: a Story with nothing to add gets no variation.")
    if not headline:
        raise VariationRefused("A variation needs a headline.")
    if origin not in ORIGINS:
        raise VariationRefused(f"origin must be one of {', '.join(ORIGINS)}.")
    held = [_connection(row) for row in connections]
    if not held and origin != PERSON:
        raise VariationRefused("A generated variation must name what it connects to.")
    if origin == REQUESTED and not request_message_id:
        raise VariationRefused("A requested variation must name the Message that asked for it.")
    existing = variations_of(client, story_lineage_id)
    based_on = list(dict.fromkeys(based_on))
    unknown = set(based_on) - {row["id"] for row in existing}
    if unknown:
        raise VariationRefused(f"basedOnVariationIds names variations this Story does not have: {', '.join(sorted(unknown))}.")
    identifier = "variation-" + hash_short([story_lineage_id, point, headline, deck or "", body_markus or ""])
    for row in existing:
        if row["id"] == identifier:
            return row
    moment = now or utc_now_iso()
    row = {
        "id": identifier, "storyLineageId": story_lineage_id, "variationNumber": max((entry["variationNumber"] for entry in existing), default=0) + 1, "status": OFFERED,
        "point": point, "headline": headline, "deck": deck, "bodyMarkus": body_markus, "section": section, "connections": json.dumps(held), "origin": origin,
        "basedOnVariationIds": based_on or None, "requestMessageId": request_message_id, "pointCheck": json.dumps(dict(point_check)) if point_check else None,
        "runId": run_id, "model": model, "createdBy": created_by, "createdAt": moment, "updatedAt": moment,
    }
    client.create_record(MODEL, {key: value for key, value in row.items() if value is not None})
    return _read(row)


def decide_variation(
    client: Any, variation_id: str, decision: str, *, decided_by_sub: str | None = None, decided_by_label: str | None = None, reason: str | None = None, now: str | None = None,
) -> dict[str, Any]:
    """An editor accepts or rejects a variation and returns it. A Story has one accepted variation at a time, so accepting another puts the earlier one back on offer.
    A rejected variation can be accepted later: the decision is the latest one, not a final state."""
    if decision not in (ACCEPTED, REJECTED):
        raise VariationRefused(f"A decision is {ACCEPTED} or {REJECTED}.")
    row = client.get_record(MODEL, variation_id)
    if row is None:
        raise VariationRefused(f"Variation {variation_id} was not found.")
    moment = now or utc_now_iso()
    if decision == ACCEPTED:
        for other in variations_of(client, row["storyLineageId"]):
            if other["id"] != variation_id and other["status"] == ACCEPTED:
                client.update_record(MODEL, {"id": other["id"], "status": OFFERED, "updatedAt": moment})
    client.update_record(MODEL, {
        "id": variation_id, "status": decision, "decidedBySub": decided_by_sub, "decidedByLabel": decided_by_label, "decidedAt": moment,
        "decisionReason": str(reason or "").strip() or None, "updatedAt": moment,
    })
    return _read(client.get_record(MODEL, variation_id))


def _connection(row: Mapping[str, Any]) -> dict[str, Any]:
    kind, identifier, title = row.get("kind"), str(row.get("id") or "").strip(), str(row.get("title") or "").strip()
    if kind not in CONNECTION_KINDS:
        raise VariationRefused(f"A connection's kind is one of {', '.join(CONNECTION_KINDS)}.")
    if not identifier or not title:
        raise VariationRefused("A connection needs the id and the title of what it connects to.")
    return {"kind": kind, "id": identifier, "title": title, **({"how": str(row["how"]).strip()} if str(row.get("how") or "").strip() else {})}


def _read(row: Mapping[str, Any]) -> dict[str, Any]:
    held = dict(row)
    for key, empty in (("connections", []), ("pointCheck", None)):
        value = held.get(key)
        held[key] = json.loads(value) if isinstance(value, str) and value else (value if value else empty)
    return held
