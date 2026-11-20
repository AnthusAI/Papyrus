"""The rating operation on the signed-in lane (``ratings_set``, PPY-d85860, slice L1).

A person's rating is the editor's value, as ``papyrus stories set-stars`` sets it. An agent's call is held to the rating policy at the write as well as at
the gate: three stars is the default, four is for a clearly better Story, a five is a person's decision alone, and a Story that already has a rating is
never rated again by a machine (it may be a person's, and a machine never replaces one). The refusals are here because the gate answers *whether this
agent may call the operation at this rung*, and the hard floors on *what it may write* hold at every rung (architecture section 5.4, slice E4).
"""
from __future__ import annotations

from typing import Any, Callable

from papyrus_content.editorial_context import hosted_publication
from papyrus_content.images.handlers import Caller, Handler, ImageOperationError, Outcome
from papyrus_content.item_stars import item_stars

MACHINE_STARS = (3, 4)


def _publication(client: Any) -> str:
    try:
        return hosted_publication(client)["key"]
    except ValueError as error:
        raise ImageOperationError("service_unavailable", str(error)) from error


def set_rating(client: Any, arguments: dict, caller: Caller) -> Outcome:
    from papyrus_content.story_reporting import current_story_version
    from papyrus_content.story_signals import set_story_stars

    lineage, stars = arguments["story"], arguments["stars"]
    if caller.kind == "agent" and stars not in MACHINE_STARS:
        raise ImageOperationError("invalid_input", "A machine rates three or four stars. A five is a person's decision, and nothing under three is given.", details={"path": "stars"})
    try:
        current = current_story_version(client, lineage)
    except ValueError as error:
        raise ImageOperationError("not_found", str(error)) from error
    previous = item_stars(current)
    if caller.kind == "agent" and previous is not None:
        raise ImageOperationError("constraint_conflict", f"{lineage} already has a rating of {previous} stars, and a machine never replaces a rating.",
                                  details={"constraint": "machine_never_replaces_a_rating", "stars": previous})
    label = f"agent:{caller.subject}" if caller.kind == "agent" and caller.subject else None
    set_story_stars(client, lineage, stars, apply=True, agent=label)
    return Outcome({"lineageId": lineage, "previous": previous or 0, "stars": stars, "ratedBy": label or caller.subject or "an editor"}, _publication(client))


RATING_HANDLERS: dict[str, Callable[..., Outcome]] = {"ratings_set": set_rating}


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
