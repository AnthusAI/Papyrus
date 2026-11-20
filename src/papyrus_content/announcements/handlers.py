"""The announcement operations on the signed-in lane: each call opens the person's own authoring client, so the backend applies their rights. The settings and the X
connection are read and changed through the site's ``announcements`` function (``Functions``), which applies every rule and checks the role (editors read, admins
change). The same handlers serve the CLI, the MCP tools and the console door.

What the signed-in lane cannot do is read Caducus's delivery log or hand it an event: those need the site's own stack. It writes Deliveries' own records (a pause lifted puts the
Deliveries it held back to ready) and leaves the sending to the deliver side (``x_runner.XRunner``). The Announcements themselves are read by ``where``, ``recent`` and ``explain``
(``list_handlers.py``).
"""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, Callable, Mapping

from papyrus_content import console_links
from papyrus_content.editorial_context import hosted_publication
from papyrus_content.images.handlers import Caller, Handler, ImageOperationError, Outcome

from . import operations
from .deliveries import Deliveries
from .operations import Services
from .spend import FunctionLedger
from .x_account import AnnouncementError
from .x_runner import SpendControl

if TYPE_CHECKING:   # the X part imports the review policy, which imports the operation table that imports this module
    from .x_announce import XServices

ORIGIN_ENV, STYLE_ENV = "SITE_ORIGIN", "ITEM_URL_STYLE"


class Functions:
    """The settings document and the X connection as the site's ``announcements`` function serves them (PPY-2deb63, PPY-ae9d06): the signed-in person's own client calls its
    GraphQL operations, so the function applies every rule and the person's role is checked there (editors read, admins change). It has the reader and writer methods of
    ``settings.AnnouncementSettings`` and the status of ``x_account.XAccounts``, so the announcement code reads either in the same way."""

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

    def spent(self, account_id: str, start: Any) -> str | None:
        """What the account spent on X in the cycle that starts on ``start``: the function reads it from the spend ledger, which a person's own client cannot."""
        return self._call("announcementsXSpend", {"accountId": account_id, "cycleStart": start.isoformat()})["spent"]

    def save_app(self, client_id: str, client_secret: str) -> dict:
        return self._call("announcementsXSaveApp", {"clientId": client_id, "clientSecret": client_secret}, mutation=True)["status"]


def _lazy_model() -> tuple[Callable[..., dict], Callable[..., dict]]:
    """The model and its judge, made when a draft first needs them: a site with X off, or a Story X does not carry, never builds either."""
    made: dict[str, Any] = {}

    def build() -> None:
        if made:
            return
        from papyrus_content import fact_check
        from papyrus_content.model_defaults import DEFAULT_LLM_MODEL
        from papyrus_content.multi_search_research import openai_llm

        made["llm"] = openai_llm(model=DEFAULT_LLM_MODEL)
        made["judge"] = fact_check.llm_judge(made["llm"], model=DEFAULT_LLM_MODEL)

    def llm(*arguments: Any, **keywords: Any) -> dict:
        build()
        return made["llm"](*arguments, **keywords)

    def judge(*arguments: Any, **keywords: Any) -> dict:
        build()
        return made["judge"](*arguments, **keywords)

    return llm, judge


def x_services(client: Any, environ: Mapping[str, str] | None = None, *, model: bool = False, llm: Any = None, judge: Any = None, guidelines_text: str | None = None,
               functions: Any = None) -> "XServices":
    """What the X part of the announcement code reaches outside itself for, over one signed-in client. ``model`` says the model may be called (its client is made when a draft first
    needs it); a spec passes ``llm`` and ``judge``."""
    environment = os.environ if environ is None else environ

    def origin() -> str:
        value = (environment.get(ORIGIN_ENV) or "").strip()
        if not value:
            raise ImageOperationError("service_unavailable", f"Set {ORIGIN_ENV} to the site's public address (for example https://news.example) so announcements can build the Story's link.")
        return value

    from papyrus_content.guidelines import GuidelineStore, resolve_guidelines
    from papyrus_content.guidelines.agent_text import writing_text
    from papyrus_content.guidelines.announcement import announcement_rules, announcement_text
    from papyrus_content.model_defaults import DEFAULT_LLM_MODEL

    from .eligibility import load_story
    from .x_announce import XServices

    guidelines = GuidelineStore(client)

    def guidelines_for(story) -> str:
        if guidelines_text is not None:
            return guidelines_text
        writing = resolve_guidelines(guidelines, "writing", story.section, channel="x")
        parts = [writing_text(writing["document"])] if writing["found"] else []
        parts.append(announcement_text(announcement_rules(client, guidelines)["document"]))
        return "\n\n".join(part for part in parts if part)

    def guideline_layers(story) -> list[dict]:
        if guidelines_text is not None:
            return []
        writing = resolve_guidelines(guidelines, "writing", story.section)
        return [{key: layer.get(key) for key in ("scope", "itemId", "versionNumber", "contentHash")} for layer in writing["layers"]]

    def learned():
        from . import learned_examples
        from .deliveries import Deliveries
        from .post import LINK

        return learned_examples.load(Deliveries(client), channel="x", kind="story_published", words_of=lambda text: LINK.sub("", text).strip())

    if model and llm is None:
        llm, judge = _lazy_model()
    functions = functions or Functions(client)
    style = environment.get(STYLE_ENV, "html")
    return XServices(settings=functions.read, connection=functions.status, story=lambda lineage: load_story(client, lineage, item_url_style=style), site_origin=origin,
                     guidelines_for=guidelines_for, llm=llm, judge=judge, model=DEFAULT_LLM_MODEL, learned=learned, guideline_layers=guideline_layers)


def build_services(client: Any, environ: Mapping[str, str] | None = None, *, model: bool = False, llm: Any = None, judge: Any = None, guidelines_text: str | None = None,
                   files: Any = None, functions: Any = None) -> Services:
    functions = functions or Functions(client)
    x = x_services(client, environ, model=model, llm=llm, judge=judge, guidelines_text=guidelines_text, functions=functions)
    return Services(client=client, x=x, control=SpendControl(settings=functions, connection=functions.status, ledger=FunctionLedger(functions)), deliveries=Deliveries(client, files))


def _publication(client: Any) -> str:
    try:
        return hosted_publication(client)["key"]
    except ValueError as error:
        raise ImageOperationError("service_unavailable", str(error)) from error


def _caller_name(caller: Caller) -> str:
    return caller.subject or "papyrus-cli"


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
    return Outcome({"settings": services.control.settings.read(), "connection": services.control.connection()}, _publication(client))


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


def account_connect(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    try:
        base = console_links.resolve_console_url()
    except console_links.ConsoleLinkError as unknown:
        raise ImageOperationError("service_unavailable", str(unknown)) from unknown
    return Outcome(operations.account_connect_link(base), _publication(client))


def account_set_app(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    status = _refusal(lambda: services.control.settings.save_app(arguments["clientId"], arguments["clientSecret"]))
    return Outcome({"status": status, "saved": True}, _publication(client))


def blocked(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    return Outcome({"blocked": operations.blocked_stories(services)}, _publication(client))


def retry(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    from .records import RecordError

    try:
        row = operations.retry_delivery(services, arguments["delivery"], by=_caller_name(caller))
    except RecordError as refused:
        raise ImageOperationError("constraint_conflict", str(refused)) from refused
    except ValueError as missing:
        raise ImageOperationError("not_found", str(missing)) from missing
    return Outcome({"id": row["id"], "state": row["state"]}, _publication(client))


#: operation name -> (function, whether it drafts with a model)
ANNOUNCEMENT_HANDLERS: dict[str, tuple[Callable[..., Outcome], bool]] = {
    "announcements_dry_run": (dry_run, True), "announcements_pause": (pause, False), "announcements_resume": (resume, False),
    "announcements_settings_show": (settings_show, False), "announcements_settings_set": (settings_set, False), "announcements_account_status": (account_status, False),
    "announcements_account_connect": (account_connect, False), "announcements_account_set_app": (account_set_app, False), "announcements_blocked": (blocked, False), "announcements_retry": (retry, False),
}


def signed_in_handlers(client_factory: Callable[[], Any] | None = None, environ: Mapping[str, str] | None = None, *, llm: Any = None, judge: Any = None, guidelines_text: str | None = None,
                       files: Any = None, functions: Any = None) -> dict[str, Handler]:
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
