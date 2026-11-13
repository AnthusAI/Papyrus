"""The announcement operations on the signed-in lane: each call opens the person's own authoring client, so the backend applies their rights. The settings and the X
connection are read and changed through the site's ``announcements`` function (``Functions``), which applies every rule and checks the role (editors read, admins
change); announcement rows are read through the account index. The same handlers serve the CLI, the MCP tools and the console door.

What the signed-in lane cannot do is read Caducus's delivery log or hand it an event: those need the site's own stack, so ``broadcaster`` is None here. ``show``
therefore shows a ``posting`` row as the site's function last recorded it.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Mapping

from papyrus_content.editorial_context import hosted_publication
from papyrus_content.images.handlers import Caller, Handler, ImageOperationError, Outcome

from . import operations
from .engine import Services
from .store import AnnouncementStore
from .x_account import AnnouncementError

ORIGIN_ENV, STYLE_ENV = "SITE_ORIGIN", "ITEM_URL_STYLE"


class Functions:
    """The settings document and the X connection as the site's ``announcements`` function serves them (PPY-2deb63, PPY-ae9d06): the signed-in person's own client calls its
    GraphQL operations, so the function applies every rule and the person's role is checked there (editors read, admins change). It has the reader and writer methods of
    ``settings.AnnouncementSettings`` and the status of ``x_account.XAccounts``, so the pipeline reads either in the same way."""

    def __init__(self, client: Any):
        self.client = client

    def _call(self, field: str, payload: dict, *, mutation: bool = False) -> dict:
        kind = "mutation" if mutation else "query"
        text = f"{kind} {field[0].upper() + field[1:]}($input: AWSJSON) {{ {field}(input: $input) }}"
        answer = json.loads(self.client.graphql(text, {"input": json.dumps(payload)})[field])
        if not answer.get("ok"):
            raise AnnouncementError(answer.get("error") or "refused", answer.get("message") or "The site refused the request.")
        return answer

    def read(self) -> dict:
        return self._call("announcementsSettings", {})["settings"]

    def save(self, proposed: dict, connection_status: str) -> dict:
        return self._call("announcementsSaveSettings", {"settings": proposed}, mutation=True)["settings"]

    def manual_pause(self, paused: bool, by: str) -> dict:
        return self._call("announcementsPause", {"paused": paused}, mutation=True)["settings"]

    def status(self) -> dict:
        return self._call("announcementsXStatus", {})["status"]


def build_services(client: Any, environ: Mapping[str, str] | None = None, *, model: bool = False, llm: Any = None, judge: Any = None, guidelines_text: str | None = None, files: Any = None, functions: Any = None) -> Services:
    environment = os.environ if environ is None else environ
    origin = (environment.get(ORIGIN_ENV) or "").strip()
    if not origin:
        raise ImageOperationError("service_unavailable", f"Set {ORIGIN_ENV} to the site's public address (for example https://news.example) so announcements can build the Story's link.")
    from papyrus_content.guidelines import GuidelineStore, resolve_guidelines
    from papyrus_content.guidelines.agent_text import writing_text
    from papyrus_content.guidelines.announcement import announcement_rules, announcement_text

    guidelines = GuidelineStore(client)

    def guidelines_for(story) -> str:
        if guidelines_text is not None:
            return guidelines_text
        writing = resolve_guidelines(guidelines, "writing", story.section)
        parts = [writing_text(writing["document"])] if writing["found"] else []
        parts.append(announcement_text(announcement_rules(client, guidelines)["document"]))
        return "\n\n".join(part for part in parts if part)

    from papyrus_content.model_defaults import DEFAULT_LLM_MODEL

    if model and llm is None:
        from papyrus_content import fact_check
        from papyrus_content.multi_search_research import openai_llm

        llm = openai_llm(model=DEFAULT_LLM_MODEL)
        judge = fact_check.llm_judge(llm, model=DEFAULT_LLM_MODEL)
    functions = functions or Functions(client)
    return Services(client=client, store=AnnouncementStore(client, files), settings=functions, connection=functions.status, site_origin=origin, item_url_style=environment.get(STYLE_ENV, "html"), guidelines_for=guidelines_for,
                    llm=llm, judge=judge, model=DEFAULT_LLM_MODEL)


def _publication(client: Any) -> str:
    try:
        return hosted_publication(client)["key"]
    except ValueError as error:
        raise ImageOperationError("service_unavailable", str(error)) from error


def _caller_name(caller: Caller) -> str:
    return caller.subject or "papyrus-cli"


def list_announcements(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    rows = operations.listing(services, state=arguments.get("state"), limit=int(arguments.get("limit") or 50))
    return Outcome({"announcements": rows}, _publication(client))


def show_announcement(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    account = operations.current(services)["accountId"]
    found = operations.show(services, f"{account}#{arguments['story']}") if account else None
    if found is None:
        raise ImageOperationError("not_found", f"No announcement for the Story {arguments['story']!r} on this site's account.")
    document = found.pop("document")
    return Outcome({"announcement": found, **({"document": document} if document else {})}, _publication(client))


def dry_run(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    try:
        return Outcome(operations.preview(services, arguments["story"]), _publication(client))
    except ValueError as error:
        raise ImageOperationError("not_found", str(error)) from error


def pause(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    settings = _refusal(lambda: operations.pause_announcements(services, by=_caller_name(caller)))
    return Outcome({"paused": settings["pause"]["paused"], "pausedBy": settings["pause"]["by"], "pausedAt": settings["pause"]["at"], "pauseReason": settings["pause"]["detail"]},
                   _publication(client))


def resume(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    done = _refusal(lambda: operations.resume_announcements(services, by=_caller_name(caller)))
    return Outcome({"released": done["released"], "paused": done["settings"]["pause"]["paused"]}, _publication(client))


def settings_show(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    return Outcome({"settings": services.settings.read(), "connection": services.connection()}, _publication(client))


def settings_set(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    done = _refusal(lambda: operations.update_settings(services, arguments, by=_caller_name(caller)))
    return Outcome({"settings": done["settings"], "released": done["released"]}, _publication(client))


def _refusal(action):
    try:
        return action()
    except AnnouncementError as refused:
        raise ImageOperationError("settings_refused", refused.message, details={"code": refused.code}) from refused


def account_status(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    return Outcome(operations.account_status(services), _publication(client))


#: operation name -> (function, whether it drafts with a model)
ANNOUNCEMENT_HANDLERS: dict[str, tuple[Callable[..., Outcome], bool]] = {
    "announcements_list": (list_announcements, False), "announcements_show": (show_announcement, False), "announcements_dry_run": (dry_run, True),
    "announcements_pause": (pause, False), "announcements_resume": (resume, True), "announcements_settings_show": (settings_show, False),
    "announcements_settings_set": (settings_set, True), "announcements_account_status": (account_status, False),
}


def signed_in_handlers(client_factory: Callable[[], Any] | None = None, environ: Mapping[str, str] | None = None, *, llm: Any = None, judge: Any = None, guidelines_text: str | None = None, files: Any = None, functions: Any = None) -> dict[str, Handler]:
    def factory():
        if client_factory is not None:
            return client_factory()
        from papyrus_content.graphql_authoring import create_authoring_client

        return create_authoring_client()[0]

    def wrap(function, drafts: bool):
        def handler(arguments: dict, caller: Caller) -> Outcome:
            client = factory()
            return function(client, arguments, caller, build_services(client, environ, model=drafts, llm=llm, judge=judge, guidelines_text=guidelines_text, files=files, functions=functions))
        return handler

    return {name: wrap(function, drafts) for name, (function, drafts) in ANNOUNCEMENT_HANDLERS.items()}
