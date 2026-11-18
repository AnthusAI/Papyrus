"""The announcement review operations on the signed-in lane (PPY-97c0f2): show and set the ``announce`` rung and its overrides, and change one Delivery's review.

Setting the policy goes through ``AgentPolicyStore`` (admins who are people; an agent is blocked), so the document, its versions and its refusals are the ones
``papyrus agents set-rung`` uses. These handlers need no X settings and no site origin, so they do not build the announcement ``Services``.
"""
from __future__ import annotations

import os
from functools import partial
from typing import TYPE_CHECKING, Any, Callable, Mapping

from papyrus_content.editorial_context import hosted_publication
from papyrus_content.images.handlers import Caller, Handler, ImageOperationError, Outcome

if TYPE_CHECKING:   # the policy package imports the operation table, which imports this module's handlers: the real imports are made inside the calls
    from papyrus_content.agent_policy import AgentPolicyStore


def _publication(client: Any) -> str:
    try:
        return hosted_publication(client)["key"]
    except ValueError as error:
        raise ImageOperationError("service_unavailable", str(error)) from error


def _tenant(client: Any) -> str:
    tenant = getattr(client, "tenant_id", None)
    if not tenant:
        raise ImageOperationError("service_unavailable", "The site's tenant is not known: sign in to the site so the policy of one site is read.")
    return str(tenant)


def _scope(arguments: dict) -> dict[str, str]:
    return {name: arguments[name] for name in ("list", "kind", "channel") if arguments.get(name)}


def review_show(client: Any, arguments: dict, caller: Caller, policy: AgentPolicyStore) -> Outcome:
    from . import review_policy

    state = policy.read(_tenant(client))
    summary = review_policy.review_summary(state)
    if arguments.get("channel") and arguments.get("kind"):
        choice = review_policy.choose(state, channel=arguments["channel"], kind=arguments["kind"], list_id=arguments.get("list"))
        summary["chosen"] = {"approval": choice.approval, "rung": choice.rung, "policy": choice.policy, "reason": choice.reason}
    return Outcome(summary, _publication(client))


def review_set(client: Any, arguments: dict, caller: Caller, policy: AgentPolicyStore) -> Outcome:
    from papyrus_content.agent_policy import PolicyError

    from . import review_policy

    approval, scope, reason = arguments["approval"], _scope(arguments), arguments["reason"]
    tenant = _tenant(client)
    before = policy.read(tenant)
    try:
        if approval == "inherit":
            if not scope:
                raise PolicyError("invalid_input", "inherit takes an override away: name the channel, kind or list it was for.")
            after = review_policy.remove_override(policy, tenant, caller, scope, reason=reason)
        else:
            after = review_policy.set_review(policy, tenant, caller, approval, reason=reason, scope=scope or None)
    except PolicyError as error:
        raise ImageOperationError(error.code, error.message) from error
    rung = review_policy.RUNG_OF.get(approval)
    return Outcome({"policyVersion": after.version, "approval": None if approval == "inherit" else approval, "rung": rung or "inherit", "scope": scope or None,
                    "changed": after.version != before.version}, _publication(client))


def delivery_review_set(client: Any, arguments: dict, caller: Caller, policy: AgentPolicyStore) -> Outcome:
    from .deliveries import Deliveries   # the records read the relation types (yaml); the image service function imports this module with the standard library only
    from .records import RecordError

    deliveries = Deliveries(client)
    row = deliveries.get(arguments["delivery"])
    if row is None:
        raise ImageOperationError("not_found", f"No Delivery {arguments['delivery']!r} on this site.")
    try:
        changed = deliveries.change_approval(row, arguments["approval"], by=caller.subject or "an editor")
    except RecordError as error:
        raise ImageOperationError("constraint_conflict", str(error)) from error
    return Outcome({"id": changed["id"], "approval": changed["approval"], "approvalPolicy": changed["approvalPolicy"], "approvedBy": changed.get("approvedBy")}, _publication(client))


def record_manual(client: Any, arguments: dict, caller: Caller, policy: AgentPolicyStore, files: Any = None) -> Outcome:
    """A person posted a manual Delivery's words by hand: record the address. The attempt names the signed-in person (never a machine)."""
    from .attempts import Attempts
    from .deliveries import Deliveries
    from .records import RecordError, attempt_log

    if caller.kind != "person" or not caller.subject:
        raise ImageOperationError("human_required", "A manual post is recorded by the signed-in person who posted it.")
    deliveries = Deliveries(client, files)
    if deliveries.get(arguments["delivery"]) is None:
        raise ImageOperationError("not_found", f"No Delivery {arguments['delivery']!r} on this site.")
    try:
        written = Attempts(deliveries).record_manual(arguments["delivery"], arguments["url"], by=caller.subject)
    except RecordError as error:
        raise ImageOperationError("constraint_conflict", str(error)) from error
    return Outcome({"id": written["id"], "state": written["state"], "resultUrl": written["resultUrl"], "attempt": attempt_log(written)[-1]}, _publication(client))


def correct(client: Any, arguments: dict, caller: Caller, policy: AgentPolicyStore, files: Any = None, judge: Any = None, story: Any = None, environ: Mapping[str, str] | None = None) -> Outcome:
    """Correct a Delivery that went: the words are checked as a new Delivery's are, then the next generation is written (``Deliveries.supersede``). Writes nothing when the
    words fail or the Delivery may not be corrected, and says why in plain words. Sends nothing: the new Delivery goes through the worker under its own review."""
    from . import corrections
    from .deliveries import Deliveries
    from .records import RecordError

    environment = os.environ if environ is None else environ
    deliveries = Deliveries(client, files)
    old = deliveries.get(arguments["delivery"])
    if old is None:
        raise ImageOperationError("not_found", f"No Delivery {arguments['delivery']!r} on this site.")

    def origin() -> str:
        value = (environment.get("SITE_ORIGIN") or "").strip()
        if not value:
            raise ImageOperationError("service_unavailable", "Set SITE_ORIGIN to the site's public address (for example https://news.example) so the post's link can be checked.")
        return value

    def made_judge() -> Any:
        if judge is not None:
            return judge
        from papyrus_content import fact_check
        from papyrus_content.model_defaults import DEFAULT_LLM_MODEL
        from papyrus_content.multi_search_research import openai_llm

        return fact_check.llm_judge(openai_llm(model=DEFAULT_LLM_MODEL), model=DEFAULT_LLM_MODEL)

    try:
        checks = corrections.check_words(old, arguments["text"], story=story or (lambda: corrections.story_of(client, old["announcementId"], item_url_style=environment.get("ITEM_URL_STYLE", "html"))),
                                         site_origin=origin, judge=made_judge)
        by = caller.subject or "papyrus-cli"
        written = corrections.correct(deliveries, old, arguments["text"], checks, by=by, drafted_by=by if caller.kind == "person" else "machine")
    except corrections.ChecksFailed as failed:
        raise ImageOperationError("checks_failed", str(failed), details={"checks": failed.checks}) from failed
    except RecordError as refused:
        raise ImageOperationError("constraint_conflict", str(refused)) from refused
    return Outcome({"id": written["id"], "generation": int(written["generation"]), "supersedes": written["supersedes"], "state": written["state"], "approval": written["approval"],
                    "checks": [{"name": check["name"], "passed": check["passed"]} for check in checks]}, _publication(client))


REVIEW_HANDLERS: dict[str, Callable[..., Outcome]] = {"announcements_review_show": review_show, "announcements_review_set": review_set, "announcements_delivery_review_set": delivery_review_set,
                                                 "announcements_record_manual": record_manual, "announcements_correct": correct}


def signed_in_handlers(client_factory: Callable[[], Any] | None = None, policy_factory: Callable[[Any], AgentPolicyStore] | None = None, files: Any = None, *, judge: Any = None, story: Any = None,
                       environ: Mapping[str, str] | None = None) -> dict[str, Handler]:
    """Each call opens the signed-in person's own client and the site's policy store. ``files`` is where a Delivery's words are read (the Delivery's own attachments when None). ``judge``, ``story`` and ``environ`` are for the check of a correction's words (the model's judge, the
    Story's facts, ``SITE_ORIGIN``); a spec passes fakes."""
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

    def wrap(function):
        def handler(arguments: dict, caller: Caller) -> Outcome:
            client = factory()
            return function(client, arguments, caller, store(client))
        return handler

    extras = {record_manual: {"files": files}, correct: {"files": files, "judge": judge, "story": story, "environ": environ}}
    return {name: wrap(partial(function, **extras[function]) if function in extras else function) for name, function in REVIEW_HANDLERS.items()}
