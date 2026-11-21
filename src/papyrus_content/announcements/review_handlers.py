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
    if caller.kind == "agent":
        # An agent on a named person's instruction, in that person's admin session (agent_policy/delegation.py): recorded as theirs, entered by the agent.
        from papyrus_content.agent_policy import PolicyError
        from papyrus_content.agent_policy.delegation import delegated_caller
        from papyrus_content.images.profile_handlers import identify

        try:
            caller, added = delegated_caller(identify(client, caller), person=arguments.get("onInstructionOf", ""), quote=arguments.get("quote", ""), agent=arguments.get("agent", ""),
                                             rung=review_policy.RUNG_OF.get(approval) or "off")
        except PolicyError as error:
            raise ImageOperationError(error.code, error.message) from error
        reason = f"{reason.strip()} {added}"
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

    instruction = ""
    if caller.kind == "agent":
        # An agent on a named admin's instruction, in that person's own session (agent_policy/delegation.py): the person chose this one Delivery's review, the agent entered it.
        from papyrus_content.agent_policy import PolicyError
        from papyrus_content.agent_policy.delegation import on_instruction_of
        from papyrus_content.images.profile_handlers import identify

        # Behind the announcements write door the caller is already who the verified identity says; only a local command line reads its own login (identify).
        known = caller if caller.subject else identify(client, caller)
        try:
            caller, instruction = on_instruction_of(known, person=arguments.get("onInstructionOf", ""), quote=arguments.get("quote", ""), agent=arguments.get("agent", ""))
        except PolicyError as error:
            raise ImageOperationError(error.code, error.message) from error
    deliveries = Deliveries(client)
    row = deliveries.get(arguments["delivery"])
    if row is None:
        raise ImageOperationError("not_found", f"No Delivery {arguments['delivery']!r} on this site.")
    try:
        changed = deliveries.change_approval(row, arguments["approval"], by=f"{caller.subject} {instruction}".strip() if instruction else (caller.subject or "an editor"))
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


def correct(client: Any, arguments: dict, caller: Caller, policy: AgentPolicyStore, files: Any = None, judge: Any = None, story: Any = None, environ: Mapping[str, str] | None = None,
            removers: Callable[[Mapping[str, Any]], Any] | None = None) -> Outcome:
    """Correct a Delivery that went: the words are checked as a new Delivery's are, then the next generation is written (``Deliveries.supersede``). Writes nothing when the
    words fail or the Delivery may not be corrected, and says why in plain words. Sends nothing: the new Delivery goes through the worker under its own review.

    Where the channel can remove the old one (X) the old post is deleted as part of the correction, and the deletion cost is written on the old Delivery. The signed-in command line
    holds no rights on Caducus, so it has no ``removers`` and writes the correction only: the deliver side deletes the old post before it sends the new one (``x_runner.XRunner``)."""
    from . import corrections
    from .decisions import Announcements
    from .deliveries import Deliveries
    from .records import RecordError
    from .withdrawals import Withdrawals

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
        facts = story or (lambda: corrections.story_of(client, old["announcementId"], item_url_style=environment.get("ITEM_URL_STYLE", "html")))
        checks = corrections.check_words(old, arguments["text"], story=facts, site_origin=origin, judge=made_judge)
        by = caller.subject or "papyrus-cli"
        words = corrections.words(old, arguments["text"], story=facts, site_origin=origin)
        written = corrections.correct(deliveries, old, words, checks, by=by, drafted_by=by if caller.kind == "person" else "machine")
        if removers is not None:
            Withdrawals(deliveries, Announcements(client, deliveries), removers).delete_superseded(old, by=by)
    except corrections.ChecksFailed as failed:
        raise ImageOperationError("checks_failed", str(failed), details={"checks": failed.checks}) from failed
    except RecordError as refused:
        raise ImageOperationError("constraint_conflict", str(refused)) from refused
    return Outcome({"id": written["id"], "generation": int(written["generation"]), "supersedes": written["supersedes"], "state": written["state"], "approval": written["approval"],
                    "checks": [{"name": check["name"], "passed": check["passed"]} for check in checks]}, _publication(client))


def _retired(client: Any, announcement: str, environ: Mapping[str, str] | None) -> bool:
    """Whether every Story the Announcement is about was retired (and there is at least one)."""
    from . import link_reads
    from .eligibility import load_story

    environment = os.environ if environ is None else environ
    lineages = sorted({link["objectLineageId"] for link in link_reads.stories_of_announcement(client, announcement)})
    return bool(lineages) and all(load_story(client, lineage, item_url_style=environment.get("ITEM_URL_STYLE", "html")).retired for lineage in lineages)


def withdraw(client: Any, arguments: dict, caller: Caller, policy: AgentPolicyStore, files: Any = None, removers: Callable[[Mapping[str, Any]], Any] | None = None,
             environ: Mapping[str, str] | None = None) -> Outcome:
    """Withdraw a Delivery and record who. A person always may. An agent may only when every Story the Announcement is about was retired; otherwise it is told ``human_required`` and
    nothing is changed. What has not gone is stopped; a post on X is deleted through the site's own X channel (``removers``), which this lane may not hold."""
    from .decisions import Announcements
    from .deliveries import Deliveries
    from .records import RecordError
    from .withdrawals import ChannelUnavailable, Withdrawals

    deliveries = Deliveries(client, files)
    announcements = Announcements(client, deliveries)
    row = deliveries.get(arguments["delivery"])
    if row is None:
        raise ImageOperationError("not_found", f"No Delivery {arguments['delivery']!r} on this site.")
    by = caller.subject or "papyrus-cli"
    if caller.kind != "person" and not _retired(client, row["announcementId"], environ):
        raise ImageOperationError("human_required", "An agent withdraws a Delivery only when the Story it announces was retired. This Story was not, so a person decides: nothing was changed.")
    try:
        written = Withdrawals(deliveries, announcements, removers or (lambda row: None)).withdraw(row["id"], by=by)
    except ChannelUnavailable as unavailable:
        raise ImageOperationError("service_unavailable", str(unavailable)) from unavailable
    except RecordError as refused:
        raise ImageOperationError("constraint_conflict", str(refused)) from refused
    state = (announcements.get(row["announcementId"]) or {}).get("state")
    return Outcome({"id": written["id"], "state": written["state"], "withdrawnBy": by, "cost": written.get("cost"), "announcementState": state}, _publication(client))


REVIEW_HANDLERS: dict[str, Callable[..., Outcome]] = {"announcements_review_show": review_show, "announcements_review_set": review_set, "announcements_delivery_review_set": delivery_review_set,
                                                 "announcements_record_manual": record_manual, "announcements_correct": correct, "announcements_withdraw": withdraw}


def signed_in_handlers(client_factory: Callable[[], Any] | None = None, policy_factory: Callable[[Any], AgentPolicyStore] | None = None, files: Any = None, *, judge: Any = None, story: Any = None,
                       environ: Mapping[str, str] | None = None, removers: Callable[[Mapping[str, Any]], Any] | None = None) -> dict[str, Handler]:
    """Each call opens the signed-in person's own client and the site's policy store. ``files`` is where a Delivery's words are read (the Delivery's own attachments when None). ``judge``, ``story`` and ``environ`` are for the check of a correction's words (the model's judge, the
    Story's facts, ``SITE_ORIGIN``); a spec passes fakes. ``removers`` answers the channel that deletes a post (Caducus's ``x``), which this lane does not hold."""
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

    def wrap(function, name=None):
        def handler(arguments: dict, caller: Caller) -> Outcome:
            client = factory()
            if name in DOOR_WRITE_OPERATIONS and client_factory is None and signed_in_lane():
                return through_write_door(name, arguments, caller, client)
            return function(client, arguments, caller, store(client))
        return handler

    extras = {record_manual: {"files": files}, correct: {"files": files, "judge": judge, "story": story, "environ": environ, "removers": removers},
              withdraw: {"files": files, "removers": removers, "environ": environ}}
    return {name: wrap(partial(function, **extras[function]) if function in extras else function, name) for name, function in REVIEW_HANDLERS.items()}


#: What the announcements write door (``announcementsWrite``) serves: a person's decision about one Delivery. The person's own credential may not write Delivery records,
#: so the door checks who is asking and the image service function writes with its own role.
DOOR_WRITE_OPERATIONS = ("announcements_delivery_review_set",)
WRITE_DOOR = "announcementsWrite"
WRITE_DOOR_MUTATION = ("mutation AnnouncementsWrite($op: String!, $input: AWSJSON, $requestId: ID!, $actorKind: String) "
                       "{ announcementsWrite(op: $op, input: $input, requestId: $requestId, actorKind: $actorKind) }")


def door_write_handlers(client: Any) -> dict[str, Handler]:
    """The door's handlers over the service function's own client. ``delivery_review_set`` reads no agent policy, so no policy store is opened."""
    return {name: (lambda function: lambda arguments, caller: function(client, arguments, caller, None))(REVIEW_HANDLERS[name]) for name in DOOR_WRITE_OPERATIONS}


def through_write_door(name: str, arguments: dict, caller: Caller, client: Any) -> Outcome:
    """On the signed-in lane: hand the call to the site's ``announcementsWrite`` door, declaring an agent as one, and read its envelope back as the local handler's answer."""
    import json
    import uuid

    variables = {"op": name, "input": json.dumps(arguments), "requestId": caller.request_id or str(uuid.uuid4()), "actorKind": "agent" if caller.kind == "agent" else None}
    raw = client.graphql(WRITE_DOOR_MUTATION, variables)[WRITE_DOOR]
    envelope = json.loads(raw) if isinstance(raw, str) else raw
    if not envelope.get("ok"):
        error = envelope.get("error") or {}
        raise ImageOperationError(str(error.get("code") or "service_unavailable"), str(error.get("message") or "The announcements door refused the request."))
    return Outcome(envelope.get("result"), str(envelope.get("publication") or _publication(client)))


def signed_in_lane() -> bool:
    return (os.environ.get("PAPYRUS_GRAPHQL_AUTH") or "").strip().lower() != "iam"
