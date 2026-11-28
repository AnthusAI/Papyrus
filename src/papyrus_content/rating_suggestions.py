"""Suggested ratings: a machine's stars beside a Story's rating, never in it (PPY-e61642, slice L2).

The rating agent suggests; a person rates. A suggestion is four fields on the Story's working record, next to the rating's own three:
``starSuggestion`` (3, 4, or 5 for a five-star candidate), ``starSuggestedBy`` (``agent:<responsibility>``), ``starSuggestedAt`` and
``starSuggestionRun`` (the run whose record holds the one-sentence reason; the reason itself is not stored on the Story). A suggestion is
*pending* while nobody has rated the Story. Confirming it makes it the person's rating through the editors' own path (``setItemStars``),
so the rating is the person's, not the machine's; changing it is rating it with other stars; ignoring it leaves it pending. A person's
rating always wins: nothing here writes ``starRating``, and a Story somebody rated is never given a suggestion.

Every suggestion a run makes is gathered into one soft review per day, "N ratings suggested, M five-star candidates", which links each
Story with its title, suggested stars and the agent's reason, so a person answers each row in the console (use the stars, choose others,
or leave it); the review is answered when every row is, or when the person dismisses it. A second run on the same day adds its Stories to that request while it is open; it never raises a second one.

The suggestion fields are read with their own query rather than through ``ITEM_FIELDS``, so a reader that never needs them keeps working
on a backend deployed before they existed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from papyrus_content import review_requests
from papyrus_content.item_stars import item_stars

SUGGESTED_STARS = (3, 4, 5)
FIVE = 5
DAILY_REVIEW_PREFIX = "rr-ratings-"
CANDIDATE_LABEL = "five-star candidate"   # the end of a candidate's link label: a link keeps only label, type and id, so the count reads it back

READ_SUGGESTION_QUERY = """
query StorySuggestion($id: ID!) {
  getItem(id: $id) { id lineageId starRating starSuggestion starSuggestedAt starSuggestedBy starSuggestionRun }
}
"""


class SuggestionError(ValueError):
    """A suggestion the rules refuse; the message is safe to show a person."""


def suggestion_of(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The suggestion on a Story's record, or None when it has none."""
    stars = (row or {}).get("starSuggestion")
    if isinstance(stars, bool) or stars not in SUGGESTED_STARS:
        return None
    return {"stars": int(stars), "by": row.get("starSuggestedBy"), "at": row.get("starSuggestedAt"), "run": row.get("starSuggestionRun"),
            "candidate": int(stars) == FIVE}


def pending_suggestion(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The suggestion a person has still to decide: there is one and nobody has rated the Story."""
    return suggestion_of(row) if item_stars(row) is None else None


def read_suggestion_row(client: Any, item_id: str) -> dict[str, Any]:
    row = (client.graphql(READ_SUGGESTION_QUERY, {"id": item_id}) or {}).get("getItem")
    if not row:
        raise SuggestionError(f"No Story record {item_id}.")
    return row


def write_suggestion(client: Any, row: Mapping[str, Any], stars: int, *, by: str, run: str | None, now: str) -> dict[str, Any]:
    """Puts a suggestion on the Story's working record. Refuses a Story somebody rated: a person's rating always wins."""
    if isinstance(stars, bool) or stars not in SUGGESTED_STARS:
        raise SuggestionError("A suggestion is three or four stars, or five for a five-star candidate a person decides.")
    rated = item_stars(row)
    if rated is not None:
        raise SuggestionError(f"{row.get('lineageId') or row['id']} already has a rating of {rated} stars; a suggestion never sits beside a person's rating.")
    fields = {"starSuggestion": stars, "starSuggestedAt": now, "starSuggestedBy": by, "starSuggestionRun": run}
    client.update_record("Item", {"id": row["id"], **fields})
    return suggestion_of(fields) or {}


def daily_review_id(day: str) -> str:
    return f"{DAILY_REVIEW_PREFIX}{day}"


def _reason(entries: list[Mapping[str, Any]]) -> str:
    ratings = sum(1 for entry in entries if entry.get("stars") != FIVE)
    candidates = len(entries) - ratings
    return (f"{ratings} {'rating' if ratings == 1 else 'ratings'} suggested, "
            f"{candidates} five-star {'candidate' if candidates == 1 else 'candidates'}")


def _link(entry: Mapping[str, Any]) -> dict[str, Any]:
    """One Story's row of the review: the link the console opens, and under ``rating`` what a person needs to answer it there (title, suggested
    stars, whether it is a five-star candidate, the agent's one-line reason). The person's answer to the row is added to ``rating`` later."""
    stars = int(entry["stars"])
    title = str(entry.get("title") or entry["story"])
    label = CANDIDATE_LABEL if stars == FIVE else f"{stars} stars suggested"
    return {"type": "story", "id": str(entry["story"]), "label": f"{title}: {label}",
            "rating": {"title": title, "stars": stars, "candidate": stars == FIVE, "reason": str(entry.get("reason") or "").strip()}}


def _stars_of(link: Mapping[str, Any]) -> int:
    rating = link.get("rating")
    if isinstance(rating, Mapping) and rating.get("stars") in SUGGESTED_STARS:
        return int(rating["stars"])
    return FIVE if str(link.get("label")).endswith(CANDIDATE_LABEL) else 3


ASK = ("For each Story, use the suggested stars, choose other stars, or leave it. A five-star candidate is never a rating until a person "
       "gives five stars. Your rating always wins and the agent never changes it.")


def raise_daily_review(client: Any, *, day: str, entries: list[Mapping[str, Any]], raised_by: str, now: datetime | None = None) -> dict[str, Any]:
    """The day's one soft review of suggested ratings. ``entries`` are ``{story, title, stars, reason}``. Raised once per day; a later run that day adds
    its Stories to it while it is open, and leaves an answered one as it is (the suggestions stay on the Stories in any case)."""
    if not entries:
        raise SuggestionError("A review of suggested ratings needs at least one suggestion.")
    request_id = daily_review_id(day)
    existing = client.get_record("ReviewRequest", request_id)
    if not existing:
        return review_requests.raise_review(client, subject={"type": "batch", "id": f"ratings-{day}"}, mode="soft_review", reason=_reason(entries),
                                            ask=ASK, raised_by=raised_by, links=[_link(entry) for entry in entries], request_id=request_id, now=now)
    request = review_requests.read_review(existing)
    known = {link.get("id") for link in request["links"] if link.get("type") == "story"}
    added = [entry for entry in entries if str(entry["story"]) not in known]
    if request["state"] != "open" or not added:
        return request
    links = [*request["links"], *(_link(entry) for entry in added)]
    every = [{"stars": _stars_of(link)} for link in links if link.get("type") == "story"]
    at = review_requests.now_iso(now or datetime.now(timezone.utc))
    client.update_record("ReviewRequest", {
        "id": request_id, "links": json.dumps(links), "reason": _reason(every), "updatedAt": at,
        "history": json.dumps(review_requests._history(request["history"], "suggestions_added", by=raised_by, at=at, note=f"{len(added)} more")),
    })
    return review_requests.read_review(client.get_record("ReviewRequest", request_id) or existing)
