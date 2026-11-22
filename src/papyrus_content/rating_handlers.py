"""The rating operations on the signed-in lane (PPY-d85860 slice L1, PPY-e61642 slice L2).

``ratings_set`` is a person's rating, the editor's value as ``papyrus stories set-stars`` sets it. A machine never writes a rating: an agent's call is
refused here at every rung, whatever the gate allows (the hard floor of architecture section 5.4). An agent *suggests* with ``ratings_suggest``: three or
four stars, or five for a five-star candidate, beside the rating and never in it, and never on a Story somebody rated. ``ratings_confirm`` is a person
deciding a suggestion: the suggested stars, or others, become that person's rating. ``ratings_suggestions_review`` raises the day's one grouped soft
review of the suggestions (``rating_suggestions.py``).
"""
from __future__ import annotations

from typing import Any, Callable

from papyrus_content.editorial_context import hosted_publication
from papyrus_content.images.handlers import Caller, Handler, ImageOperationError, Outcome
from papyrus_content.item_stars import item_stars



def _publication(client: Any) -> str:
    try:
        return hosted_publication(client)["key"]
    except ValueError as error:
        raise ImageOperationError("service_unavailable", str(error)) from error


def set_rating(client: Any, arguments: dict, caller: Caller) -> Outcome:
    from papyrus_content.story_signals import set_story_stars

    lineage, stars = arguments["story"], arguments["stars"]
    if caller.kind == "agent":
        raise ImageOperationError("not_authorized", "A machine never writes a rating; it suggests one with ratings_suggest, and a person decides.",
                                  details={"constraint": "machine_never_rates"})
    current = _current(client, lineage)
    previous = item_stars(current)
    set_story_stars(client, lineage, stars, apply=True)
    return Outcome({"lineageId": lineage, "previous": previous or 0, "stars": stars, "ratedBy": caller.subject or "an editor"}, _publication(client))


def _current(client: Any, lineage: str) -> dict:
    from papyrus_content.story_reporting import current_story_version

    try:
        return current_story_version(client, lineage)
    except ValueError as error:
        raise ImageOperationError("not_found", str(error)) from error


def suggest_rating(client: Any, arguments: dict, caller: Caller) -> Outcome:
    from datetime import datetime, timezone

    from papyrus_content import rating_suggestions

    lineage, stars = arguments["story"], arguments["stars"]
    if stars not in rating_suggestions.SUGGESTED_STARS or isinstance(stars, bool):
        raise ImageOperationError("invalid_input", "A suggestion is three or four stars, or five for a five-star candidate.", details={"path": "stars"})
    row = rating_suggestions.read_suggestion_row(client, _current(client, lineage)["id"])
    rated = item_stars(row)
    if rated is not None:
        raise ImageOperationError("constraint_conflict", f"{lineage} already has a rating of {rated} stars; a person's rating always wins.",
                                  details={"constraint": "person_rating_wins", "stars": rated})
    by = f"agent:{caller.subject}" if caller.kind == "agent" and caller.subject else (caller.subject or "an editor")
    run = getattr(caller.gate_run, "run_id", None)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    suggestion = rating_suggestions.write_suggestion(client, row, stars, by=by, run=run, now=now)
    return Outcome({"lineageId": lineage, "stars": stars, "candidate": suggestion["candidate"], "suggestedBy": by, "run": run}, _publication(client))


def confirm_suggestion(client: Any, arguments: dict, caller: Caller) -> Outcome:
    from papyrus_content import rating_suggestions
    from papyrus_content.story_signals import set_story_stars

    lineage = arguments["story"]
    if caller.kind == "agent":
        raise ImageOperationError("not_authorized", "Only a person decides a suggested rating.", details={"constraint": "machine_never_rates"})
    row = rating_suggestions.read_suggestion_row(client, _current(client, lineage)["id"])
    suggestion = rating_suggestions.suggestion_of(row)
    if suggestion is None:
        raise ImageOperationError("not_found", f"{lineage} has no suggested rating to confirm.")
    rated = item_stars(row)
    if rated is not None:
        raise ImageOperationError("constraint_conflict", f"{lineage} already has a rating of {rated} stars; rate it again with ratings_set to change it.",
                                  details={"constraint": "already_rated", "stars": rated})
    stars = arguments.get("stars") or suggestion["stars"]
    set_story_stars(client, lineage, stars, apply=True)
    return Outcome({"lineageId": lineage, "stars": stars, "suggested": suggestion["stars"], "changed": stars != suggestion["stars"],
                    "ratedBy": caller.subject or "an editor"}, _publication(client))


def suggestions_review(client: Any, arguments: dict, caller: Caller) -> Outcome:
    from papyrus_content import rating_suggestions

    by = f"agent:{caller.subject}" if caller.kind == "agent" and caller.subject else (caller.subject or "an editor")
    try:
        request = rating_suggestions.raise_daily_review(client, day=arguments["day"], entries=arguments["suggestions"], raised_by=by)
    except rating_suggestions.SuggestionError as error:
        raise ImageOperationError("invalid_input", str(error)) from error
    return Outcome({"request": request["id"], "reason": request["reason"], "state": request["state"],
                    "stories": [link["id"] for link in request["links"] if link.get("type") == "story"]}, _publication(client))


RATING_HANDLERS: dict[str, Callable[..., Outcome]] = {"ratings_set": set_rating, "ratings_suggest": suggest_rating, "ratings_confirm": confirm_suggestion,
                                                      "ratings_suggestions_review": suggestions_review}


def signed_in_handlers(client_factory: Callable[[], Any] | None = None) -> dict[str, Handler]:
    """Each call opens the authoring client of whoever runs it: a person's own session, or the procedure runner's role inside a run."""
    def factory():
        if client_factory is not None:
            return client_factory()
        from papyrus_content.graphql_authoring import create_authoring_client

        return create_authoring_client()[0]

    def wrap(function):
        def handler(arguments: dict, caller: Caller) -> Outcome:
            return function(factory(), arguments, caller)
        return handler

    return {name: wrap(function) for name, function in RATING_HANDLERS.items()}
