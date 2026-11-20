"""The Announcements list, the Story drawer's lines and the "why not announced" question, on the signed-in lane (PPY-e4ae3a).

These are reads of the Announcement and Delivery records (``lines.py``) and of the rules that decide an Announcement (``explain.py``). They write nothing. Like the review
handlers they need neither the site's origin nor the X settings' secrets, and the records read the relation types (yaml) the image service function does not carry, so the
image operation table imports this module by the call (``images/handlers.py``) and the monitoring router's zip leaves it out.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Callable

from papyrus_content.editorial_context import hosted_publication
from papyrus_content.images.handlers import Caller, Handler, ImageOperationError, Outcome

from .records import now_iso

if TYPE_CHECKING:
    from papyrus_content.agent_policy import AgentPolicyStore

DEFAULT_PAGE = 25
STYLE_ENV = "ITEM_URL_STYLE"


def _publication(client: Any) -> str:
    try:
        return hosted_publication(client)["key"]
    except ValueError as error:
        raise ImageOperationError("service_unavailable", str(error)) from error


def where(client: Any, arguments: dict, caller: Caller, policy: AgentPolicyStore | None, clock: Callable[[], str], functions: Any, stamps: Callable[[Any], Any] | None) -> Outcome:
    """Where a Story was announced: one line for each live Delivery under the Announcement that decided it."""
    from .lines import story_entries

    return Outcome({"story": arguments["story"], "announcements": story_entries(client, arguments["story"], clock())}, _publication(client))


def recent(client: Any, arguments: dict, caller: Caller, policy: AgentPolicyStore | None, clock: Callable[[], str], functions: Any, stamps: Callable[[Any], Any] | None) -> Outcome:
    """The Announcements list, a page at a time, with what is overdue."""
    from .lines import recent as read_recent

    limit = int(arguments.get("limit") or DEFAULT_PAGE)
    return Outcome(read_recent(client, clock(), limit=limit, before=arguments.get("before") or None), _publication(client))


def explain(client: Any, arguments: dict, caller: Caller, policy: AgentPolicyStore | None, clock: Callable[[], str], functions: Any, stamps: Callable[[Any], Any] | None) -> Outcome:
    """Why a Story was or was not announced, for each channel. Reads the rules and writes nothing."""
    from . import rules
    from .eligibility import load_story
    from .explain import explain as explain_story, explain_delivery
    from .handlers import Functions
    from .intake import ChecklistReviewStamps
    from .lines import story_entries

    if bool(arguments.get("story")) == bool(arguments.get("delivery")):
        raise ImageOperationError("invalid_input", "Ask about one thing: a Story (why it was or was not announced) or a Delivery (what its draft read).")
    if arguments.get("delivery"):
        from .deliveries import Deliveries

        deliveries = Deliveries(client)
        row = deliveries.get(arguments["delivery"])
        if row is None:
            raise ImageOperationError("not_found", f"No Delivery {arguments['delivery']!r} on this site.")
        from .x_announce import recorded_inputs

        named = (recorded_inputs(row) or {}).get("examples") or []
        return Outcome(explain_delivery(row, [found for found in (deliveries.get(example) for example in named) if found]), _publication(client))
    tenant = getattr(client, "tenant_id", None)
    if not tenant or policy is None:
        raise ImageOperationError("service_unavailable", "The site's tenant is not known: sign in to the site so the policy of one site is read.")
    try:
        story = load_story(client, arguments["story"], item_url_style=os.environ.get(STYLE_ENV, "html"))
    except (ValueError, KeyError, IndexError) as error:
        raise ImageOperationError("not_found", f"No Story {arguments['story']!r} on this site.") from error
    functions = functions or Functions(client)
    settings = rules.view(functions.read(), functions.status())
    answer = explain_story(story, settings, policy.read(str(tenant)), (stamps or ChecklistReviewStamps)(client), story_entries(client, story.lineage_id, clock()))
    return Outcome(answer, _publication(client))


LIST_HANDLERS: dict[str, Callable[..., Outcome]] = {"announcements_where": where, "announcements_recent": recent, "announcements_explain": explain}


def signed_in_handlers(client_factory: Callable[[], Any] | None = None, policy_factory: Callable[[Any], AgentPolicyStore] | None = None,
                       clock: Callable[[], str] = now_iso, functions: Any = None, stamps: Callable[[Any], Any] | None = None) -> dict[str, Handler]:
    """Each call opens the signed-in person's own client (and, for the question, the site's policy store). ``functions`` is the site's settings reader (``handlers.Functions``); ``stamps`` makes the reader of a Story's human review stamp (``intake.ChecklistReviewStamps``)."""
    def factory():
        if client_factory is not None:
            return client_factory()
        from papyrus_content.graphql_authoring import create_authoring_client

        return create_authoring_client()[0]

    def store(client):
        if policy_factory is not None:
            return policy_factory(client)
        from papyrus_content.agent_definitions.cli import _policy_store_for_site

        return _policy_store_for_site(client)

    def wrap(name: str, function):
        def handler(arguments: dict, caller: Caller) -> Outcome:
            client = factory()
            return function(client, arguments, caller, store(client) if name == "announcements_explain" else None, clock, functions, stamps)
        return handler

    return {name: wrap(name, function) for name, function in LIST_HANDLERS.items()}


#: What the console's announcements door (``announcementsRead``) serves. ``explain`` reads the site's agent policy and its settings function, which the image service function does not
#: bind; it is a command and an agents' tool.
DOOR_OPERATIONS = ("announcements_where", "announcements_recent")


def with_client(client: Any, clock: Callable[[], str] = now_iso) -> dict[str, Handler]:
    """The door's handlers over the service function's own client: the caller's role was checked at the door, and nothing is written."""
    handlers = signed_in_handlers(client_factory=lambda: client, clock=clock)
    return {name: handlers[name] for name in DOOR_OPERATIONS}
