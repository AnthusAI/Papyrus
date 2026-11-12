"""The announcement operations on the signed-in lane: each call opens the person's own authoring client, so the backend applies their rights (admins write the
settings row; editors and admins write announcements). The same handlers serve the CLI, the MCP tools and the console door.

What the signed-in lane cannot do is read Caducus's delivery log or hand it an event: those need the site's own stack, so ``broadcaster`` is None here. ``show``
therefore shows a ``posting`` row as the site's function last recorded it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from papyrus_content.editorial_context import hosted_publication
from papyrus_content.images.handlers import Caller, Handler, ImageOperationError, Outcome
from papyrus_content.story_types import PROJECTION_SETTINGS_FILE, SITE_STATIC_DIRECTORY_ENV, read_projection_settings

from . import operations
from .engine import Services
from .settings import DEFAULT_QUALITY_FLOOR, SettingsRefused
from .store import AnnouncementStore

ORIGIN_ENV, STYLE_ENV = "SITE_ORIGIN", "ITEM_URL_STYLE"


def quality_floor(environ: Mapping[str, str] | None = None) -> int:
    """The site's quality floor in stars: ``quality.floor_stars`` of its ``projection.json`` (PPY-0e8d66), else the decision's default."""
    environment = os.environ if environ is None else environ
    directory = (environment.get(SITE_STATIC_DIRECTORY_ENV) or "").strip()
    found = (read_projection_settings(Path(directory) if directory else None).get("quality") or {}).get("floor_stars")
    return int(found) if found is not None else DEFAULT_QUALITY_FLOOR


def build_services(client: Any, environ: Mapping[str, str] | None = None, *, model: bool = False, llm: Any = None, judge: Any = None, guidelines_text: str | None = None, files: Any = None) -> Services:
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
    return Services(client=client, store=AnnouncementStore(client, files), site_origin=origin, item_url_style=environment.get(STYLE_ENV, "html"), guidelines_for=guidelines_for,
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
    account = services.store.settings().get("accountId")
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
    saved = operations.pause_announcements(services, by=_caller_name(caller), reason=arguments.get("reason"))
    return Outcome({key: saved.get(key) for key in ("paused", "pausedBy", "pausedAt", "pauseReason")}, _publication(client))


def resume(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    done = operations.resume_announcements(services, by=_caller_name(caller))
    return Outcome({"released": done["released"], "paused": bool(done["settings"].get("paused"))}, _publication(client))


def settings_show(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    return Outcome({"settings": services.store.settings(), "qualityFloor": quality_floor()}, _publication(client))


def settings_set(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    try:
        done = operations.update_settings(services, arguments, by=_caller_name(caller), quality_floor=quality_floor())
    except SettingsRefused as refused:
        raise ImageOperationError("settings_refused", str(refused), details={"problems": [{"field": field, "message": message} for field, message in refused.problems]}) from refused
    return Outcome({"settings": done["settings"], "released": done["released"]}, _publication(client))


def account_status(client, arguments: dict, caller: Caller, services: Services) -> Outcome:
    return Outcome(operations.account_status(services), _publication(client))


#: operation name -> (function, whether it drafts with a model)
ANNOUNCEMENT_HANDLERS: dict[str, tuple[Callable[..., Outcome], bool]] = {
    "announcements_list": (list_announcements, False), "announcements_show": (show_announcement, False), "announcements_dry_run": (dry_run, True),
    "announcements_pause": (pause, False), "announcements_resume": (resume, True), "announcements_settings_show": (settings_show, False),
    "announcements_settings_set": (settings_set, True), "announcements_account_status": (account_status, False),
}


def signed_in_handlers(client_factory: Callable[[], Any] | None = None, environ: Mapping[str, str] | None = None, *, llm: Any = None, judge: Any = None, guidelines_text: str | None = None, files: Any = None) -> dict[str, Handler]:
    def factory():
        if client_factory is not None:
            return client_factory()
        from papyrus_content.graphql_authoring import create_authoring_client

        return create_authoring_client()[0]

    def wrap(function, drafts: bool):
        def handler(arguments: dict, caller: Caller) -> Outcome:
            client = factory()
            return function(client, arguments, caller, build_services(client, environ, model=drafts, llm=llm, judge=judge, guidelines_text=guidelines_text, files=files))
        return handler

    return {name: wrap(function, drafts) for name, (function, drafts) in ANNOUNCEMENT_HANDLERS.items()}
