"""The editing-window operations on the signed-in lane (PPY-e8ec54): save a Delivery's words as the next version, keep and choose candidates, change or unpin a pinned block, read
the versions, and unlock.

They are rows of the one operation table (``announcements_draft``, ``announcements_candidate_choose``, ``announcements_pinned_change``, ``announcements_versions``,
``announcements_unlock``), so the newsroom, the command line and the MCP tools call them the same way, and the one gate decides what an agent may do: drafting from the ``draft`` rung,
and a person only for unlocking and for a pinned block. A person's save is the person's (owner ``human``, pinned); an agent's is a redraft laid over the pinned blocks.

These handlers write Delivery rows and read words files, so they need no X settings and no site origin, and the module is imported by the call, not by the operation table.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from papyrus_content.editorial_context import hosted_publication
from papyrus_content.images.handlers import Caller, Handler, ImageOperationError, Outcome

if TYPE_CHECKING:
    from papyrus_content.agent_policy import AgentPolicyStore


def _publication(client: Any) -> str:
    try:
        return hosted_publication(client)["key"]
    except ValueError as error:
        raise ImageOperationError("service_unavailable", str(error)) from error


def _by(caller: Caller) -> str:
    return caller.subject or "papyrus-cli"


def _owner(caller: Caller) -> str:
    from .delivery_text import HUMAN, MACHINE

    return HUMAN if caller.kind == "person" else MACHINE


def _refused(error: Exception) -> ImageOperationError:
    """A refusal of the records in the operation table's words: the code a caller can act on, the plain sentence, and what it needs to read again."""
    from .delivery_versions import Locked, NoSuchBlock, NoSuchCandidate, StaleVersion

    if isinstance(error, StaleVersion):
        return ImageOperationError("stale_version", str(error), details={"head": error.head, "replacedBy": error.replaced_by})
    if isinstance(error, Locked):
        return ImageOperationError("locked", str(error))
    if isinstance(error, (NoSuchBlock, NoSuchCandidate)):
        return ImageOperationError("not_found", str(error))
    return ImageOperationError("constraint_conflict", str(error))


def _delivery(deliveries: Any, arguments: dict) -> dict[str, Any]:
    row = deliveries.get(arguments["delivery"])
    if row is None:
        raise ImageOperationError("not_found", f"No Delivery {arguments['delivery']!r} on this site.")
    return row


def _result(row: dict[str, Any], status: str, entry: dict[str, Any] | None = None, reason: str | None = None, candidate: str | None = None) -> dict[str, Any]:
    """The Delivery after a save, in the table's words: the newest version, what it replaced, the approved, locked and preferred versions, and each block's owner and pin."""
    from . import delivery_text as dt

    shown = entry or dt.head_entry(row)
    return {"id": row["id"], "status": status, "version": int(row["version"]), "replaces": entry.get("replaces") if entry else None,
            "approvedVersion": row.get("approvedVersion"), "lockedVersion": row.get("lockedVersion"), "preferredVersion": row.get("preferredVersion"),
            **({"reason": reason} if reason else {}), **({"candidate": candidate} if candidate else {}),
            "blocks": [{"owner": block["owner"], "pinned": bool(block["pinned"])} for block in dt.json_list(shown.get("blocks"))] if shown else []}


def draft(client: Any, arguments: dict, caller: Caller, policy: AgentPolicyStore, files: Any = None, now: str | None = None) -> Outcome:
    from .deliveries import Deliveries
    from .delivery_text import KEEP
    from .delivery_versions import Versions
    from .records import RecordError

    deliveries = Deliveries(client, files)
    row = _delivery(deliveries, arguments)
    versions, owner, by = Versions(deliveries), _owner(caller), _by(caller)
    text, image = arguments.get("text"), arguments.get("imageKey")
    try:
        if arguments.get("candidate"):
            written, candidate = versions.add_candidate(row["id"], text=text, image_key=image, by=by, owner=owner, now=now)
            return Outcome(_result(written, "candidate", candidate=candidate["id"]), _publication(client))
        if arguments.get("replaces") is None:
            raise ImageOperationError("invalid_input", "A save names the version it replaces (replaces): read the versions first.", details={"path": "replaces"})
        if text is None and (image is None or owner == "machine"):
            raise ImageOperationError("invalid_input", "Give the words to save (text)." if owner == "machine" else "Give the words (text) or the picture (imageKey) to save.", details={"path": "text"})
        if owner == "machine":
            saved = versions.redraft(row["id"], replaces=int(arguments["replaces"]), text=text, by=by, now=now)
        else:
            saved = versions.save(row["id"], replaces=int(arguments["replaces"]), text=text, image_key=image if image is not None else KEEP, by=by, owner=owner, now=now)
    except RecordError as refused:
        raise _refused(refused) from refused
    return Outcome(_result(saved.row, saved.status, saved.entry, saved.reason), _publication(client))


def candidate_choose(client: Any, arguments: dict, caller: Caller, policy: AgentPolicyStore, files: Any = None, now: str | None = None) -> Outcome:
    from .deliveries import Deliveries
    from .delivery_versions import Versions
    from .records import RecordError

    deliveries = Deliveries(client, files)
    row = _delivery(deliveries, arguments)
    try:
        saved = Versions(deliveries).choose_candidate(row["id"], arguments["candidate"], replaces=int(arguments["replaces"]), by=_by(caller), owner=_owner(caller), now=now)
    except RecordError as refused:
        raise _refused(refused) from refused
    return Outcome(_result(saved.row, saved.status, saved.entry, saved.reason), _publication(client))


def pinned_change(client: Any, arguments: dict, caller: Caller, policy: AgentPolicyStore, files: Any = None, now: str | None = None) -> Outcome:
    from .deliveries import Deliveries
    from .delivery_versions import Versions
    from .records import RecordError

    if caller.kind != "person":
        raise ImageOperationError("human_required", "A block a person pinned is changed or unpinned by a person.")
    deliveries = Deliveries(client, files)
    row = _delivery(deliveries, arguments)
    try:
        saved = Versions(deliveries).change_pinned(row["id"], replaces=int(arguments["replaces"]), block=int(arguments["block"]), by=_by(caller), text=arguments.get("text"),
                                                   unpin=bool(arguments.get("unpin")), now=now)
    except RecordError as refused:
        raise _refused(refused) from refused
    return Outcome(_result(saved.row, saved.status, saved.entry, saved.reason), _publication(client))


def versions_show(client: Any, arguments: dict, caller: Caller, policy: AgentPolicyStore, files: Any = None, now: str | None = None) -> Outcome:
    from .deliveries import Deliveries
    from .delivery_versions import Versions
    from .records import RecordError

    deliveries = Deliveries(client, files)
    row = _delivery(deliveries, arguments)
    versions = Versions(deliveries)
    listing = versions.listing(row)
    try:
        if arguments.get("version") is not None:
            listing["text"] = versions.text_of_version(row, int(arguments["version"]))
        elif arguments.get("candidate"):
            text = versions.text_of_candidate(row, arguments["candidate"])
            if text is not None:
                listing["text"] = text
    except RecordError as refused:
        raise _refused(refused) from refused
    return Outcome(listing, _publication(client))


def unlock(client: Any, arguments: dict, caller: Caller, policy: AgentPolicyStore, files: Any = None, now: str | None = None) -> Outcome:
    from .deliveries import Deliveries
    from .delivery_lock import unlock as lift
    from .records import RecordError

    if caller.kind != "person" or not caller.subject:
        raise ImageOperationError("human_required", "A Delivery is unlocked by a person: unlocking is their decision that a late edit is worth it.")
    deliveries = Deliveries(client, files)
    row = _delivery(deliveries, arguments)
    try:
        written = lift(deliveries, row["id"], by=caller.subject, lock_at=arguments.get("lockAt"), release_at=arguments.get("releaseAt"), now=now)
    except RecordError as refused:
        raise _refused(refused) from refused
    return Outcome({"id": written["id"], "lockAt": written["lockAt"], "releaseAt": written["releaseAt"], "lockedVersion": written.get("lockedVersion")}, _publication(client))


EDIT_HANDLERS: dict[str, Callable[..., Outcome]] = {"announcements_draft": draft, "announcements_candidate_choose": candidate_choose, "announcements_pinned_change": pinned_change,
                                                    "announcements_versions": versions_show, "announcements_unlock": unlock}


def signed_in_handlers(client_factory: Callable[[], Any] | None = None, policy_factory: Callable[[Any], AgentPolicyStore] | None = None, files: Any = None,
                       clock: Callable[[], str] | None = None) -> dict[str, Handler]:
    """Each call opens the signed-in person's own client. ``files`` is where a Delivery's words are read and written (the Delivery's own attachments when None); ``clock`` answers the time as UTC text (the real time when None); a spec passes fakes for both."""
    def factory():
        if client_factory is not None:
            return client_factory()
        from papyrus_content.graphql_authoring import create_authoring_client

        return create_authoring_client()[0]

    def wrap(function):
        def handler(arguments: dict, caller: Caller) -> Outcome:
            client = factory()
            return function(client, arguments, caller, policy_factory(client) if policy_factory else None, files, clock() if clock else None)
        return handler

    return {name: wrap(function) for name, function in EDIT_HANDLERS.items()}
