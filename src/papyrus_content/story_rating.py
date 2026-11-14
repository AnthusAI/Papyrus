"""The evidence behind the checklist step ``rated`` (docs/story-procedure.md, "The Rated step").

A site can require that a Story is rated before it publishes: the design-system setting ``publishRequiresRating`` (true or false; off when unset, so no
site is held to it unless it turns it on). Pure over a small dict of inputs read once (``inputs_for_item``), so the checklist, ``papyrus stories next`` and
the publish gate all give the same answer. The step is done when the Story has an editor's star rating of 1 to 5 recorded by a person (``starRating`` with
``starRatedBy``, set with ``papyrus stories set-stars``). A rating of 0 clears it, and a prediction made by a model is a different record that never counts.
"""

from __future__ import annotations

from typing import Any

from .item_stars import item_stars

SETTING_REQUIRED = "publishRequiresRating"

# The states mirror newsroom_process (not imported here: it imports this module lazily).
DONE, NOT_DONE, UNKNOWN, NOT_APPLICABLE = "done", "not_done", "unknown", "not_applicable"


def not_required() -> dict[str, Any]:
    return {"required": False, "stars": None, "ratedBy": "", "ratedAt": ""}


def read_required(client) -> bool:
    """Whether the site's design-system settings turn the rating requirement on. A site with no design system, or no such setting, is not held to it."""
    from .figures.records import DesignSystemRecords

    return DesignSystemRecords(client).settings().get(SETTING_REQUIRED) is True


def inputs_for_item(client, item: dict[str, Any]) -> dict[str, Any]:
    """What the evidence reads: whether the site requires a rating, and the rating on this version of the Story."""
    return {
        "required": read_required(client), "stars": item_stars(item),
        "ratedBy": str(item.get("starRatedBy") or "").strip(), "ratedAt": str(item.get("starRatedAt") or ""),
    }


def rating_evidence(inputs: dict[str, Any] | None) -> tuple[str, str]:
    """``(state, text)``: ``done`` with what proves it, ``not_done`` with what is missing, ``unknown`` when it cannot be told, or ``not_applicable`` for a site
    that does not require a rating."""
    if not inputs:
        return UNKNOWN, "the rating evidence could not be read"
    if not inputs["required"]:
        return NOT_APPLICABLE, f"this site does not require a rating before publishing ({SETTING_REQUIRED} is off)"
    if inputs["stars"] is None:
        return NOT_DONE, "the Story has no star rating from an editor"
    if not inputs["ratedBy"]:
        return NOT_DONE, f"the Story's {inputs['stars']}-star rating was not recorded by a person"
    when = f" on {inputs['ratedAt']}" if inputs["ratedAt"] else ""
    return DONE, f"rated {inputs['stars']} stars by {inputs['ratedBy']}{when}"
