"""The image-service function: ``imageRead`` and ``imageWrite``, the one door to the image operations (PPY-6e05fd; design sections 3.2 and 5), and
``guidelinesRead`` and ``guidelinesWrite``, the same door for the guideline operations (PPY-8d41d7).

AppSync checks that the caller is signed in and in the editor or admin group before this function runs, and hands it the verified identity. The function
repeats the check (a caller outside the staff groups is refused), takes who is asking from that identity and never from the input, and runs the operation
with the same handlers the command line uses. It reaches the site's own data with its role, as the other core functions do; it writes only what an
operation says it writes (today: new versions of the visual style profile), recording the caller's name on them.

* ``imageRead(op, input)`` runs an operation that only reads; ``imageWrite(op, input, requestId)`` runs one that writes or spends. The wrong door is refused.
  ``guidelinesRead`` and ``guidelinesWrite`` do the same for the ``guidelines_*`` operations, and each family refuses the other's operations. Editors and admins
  read guidelines; saving is the handler's rule (an admin), because the group check at the door cannot tell the two apart.
* ``requestId`` makes a write safe to repeat: the same id from the same person gives the first answer.
* ``actorKind`` may declare the caller an agent. A declaration can only make a call stricter (an agent may not change a binding constraint); it cannot
  claim to be a person, because everyone is one by default. It rests on agents labelling themselves (design section 3.6).
Errors are the shared envelope (``{"ok": false, "error": {...}}``), never a stack trace; the cause of an unexpected failure goes to the log by type only.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

from .appsync_event import NoOperation, operation_name
from .images.handlers import Caller, error_envelope, execute
from .images.operations import operation
from .images.profile_handlers import SECTION_STYLE_FIELD, with_client
from .guidelines.handlers import with_client as guidelines_with_client
from .guidelines.s3_files import S3DocumentFiles
from .staff_groups import claim_groups, has_editor_rights

LOG = logging.getLogger(__name__)
DOORS = {"imageRead": ("read",), "imageWrite": ("write", "spend"), "guidelinesRead": ("read",), "guidelinesWrite": ("write",), "announcementsRead": ("read",),
         "announcementsWrite": ("write",)}
DOOR_GROUP = {"imageRead": "images", "imageWrite": "images", "guidelinesRead": "guidelines", "guidelinesWrite": "guidelines", "announcementsRead": "announcements",
              "announcementsWrite": "announcements"}
DOOR_FOR = {("images", True): "imageRead", ("images", False): "imageWrite", ("guidelines", True): "guidelinesRead", ("guidelines", False): "guidelinesWrite",
            ("announcements", True): "announcementsRead", ("announcements", False): "announcementsWrite"}
WRITE_DOORS = ("imageWrite", "guidelinesWrite", "announcementsWrite")


def announcement_write_door_operations() -> tuple[str, ...]:
    from .announcements.review_handlers import DOOR_WRITE_OPERATIONS

    return DOOR_WRITE_OPERATIONS


def default_client_factory(env: Any) -> Callable[[], Any]:
    def factory():
        os.environ.setdefault("PAPYRUS_GRAPHQL_AUTH", "iam")   # the function's own role signs the call
        from .graphql_authoring import PapyrusGraphQLAuthoringClient
        return PapyrusGraphQLAuthoringClient(endpoint=env.get("PAPYRUS_GRAPHQL_ENDPOINT"))
    return factory


def caller_from_identity(identity: dict, *, actor_kind: str | None = None, request_id: str | None = None) -> Caller:
    claims = identity.get("claims") or {}
    groups = [group.lower() for group in claim_groups(identity.get("groups") if identity.get("groups") is not None else claims.get("cognito:groups"))]
    subject = str(claims.get("name") or claims.get("email") or identity.get("username") or "").strip()[:100]
    return Caller(kind="agent" if actor_kind == "agent" else "person", subject=subject, is_admin="admin" in groups, request_id=request_id)


def _arguments(raw: Any) -> Any:
    if isinstance(raw, str):
        return json.loads(raw) if raw.strip() else {}
    return raw if raw is not None else {}


def site_delivery_timers(env: Any) -> Any:
    """The site's follow-up timers for its Deliveries, named by this function's environment (amplify/functions/image-service/wire.ts), so a person's change through the
    announcements write door moves a Delivery's timer with its due time (PPY-e2829f). None where the site is not named: the old timer then fires once and does nothing,
    and the new time is shown as Overdue (overdue.py)."""
    from .announcements.delivery_timers import DeliveryTimers
    from .follow_up_timers import SiteNotNamed

    try:
        return DeliveryTimers.from_environment(env, appsync_endpoint=str(env.get("PAPYRUS_GRAPHQL_ENDPOINT") or ""))
    except SiteNotNamed as missing:
        LOG.warning("announcements write door without follow-up timers: %s", missing)
        return None


def handle(event: dict, *, env: Any = None, client_factory: Callable[[], Any] | None = None, files_factory: Callable[[Any], Any] | None = None,
           delivery_files_factory: Callable[[Any], Any] | None = None, delivery_timers_factory: Callable[[], Any] | None = None) -> dict:
    """AppSync resolver entry for the four door fields. Returns the envelope as the field's JSON.

    ``files_factory(client)`` supplies where guideline documents are kept (S3 by default); tests pass an in-memory one. ``delivery_timers_factory()`` supplies the site's
    follow-up timers for the announcements write door: by default the ones this function's environment names, and none when a test gives its own client."""
    env = os.environ if env is None else env
    identity = event.get("identity") or {}
    claims = identity.get("claims") or {}
    groups = identity.get("groups") if identity.get("groups") is not None else claims.get("cognito:groups")
    arguments = event.get("arguments") or {}
    name = arguments.get("op")
    try:
        door = operation_name(event)
    except NoOperation as error:
        return error_envelope(str(name), "invalid_input", str(error))
    if door not in DOORS or not isinstance(name, str):
        return error_envelope(str(name), "invalid_input", "Give an op, through imageRead, imageWrite, guidelinesRead, guidelinesWrite, announcementsRead or announcementsWrite.", details={"path": "op"})
    if not has_editor_rights(groups):
        return error_envelope(name, "not_authorized")
    item = operation(name)
    write_door_serves = item is None or item.group != "announcements" or item.effect == "read" or item.name in announcement_write_door_operations()
    if item is not None and (item.group != DOOR_GROUP[door] or item.effect not in DOORS[door] or not write_door_serves):
        right = DOOR_FOR.get((item.group, item.effect == "read")) if write_door_serves else None
        if right is None:   # the announcements doors serve the console's reads and a person's decision about a Delivery; the rest of what changes an announcement is the command line's
            served = "it takes only a person's decision about one Delivery" if door == "announcementsWrite" else "this door only reads"
            return error_envelope(name, "invalid_input", f"{name} is not run through {door}: {served}.", details={"path": "op"})
        return error_envelope(name, "invalid_input", f"{name} is run through {right}, not {door}.", details={"path": "op"})
    try:
        payload = _arguments(arguments.get("input"))
    except ValueError:
        return error_envelope(name, "invalid_input", "input must be JSON.", details={"path": "input"})
    actor = arguments.get("actorKind")
    caller = caller_from_identity(identity, actor_kind=actor if actor in ("agent", "person") else None,
                                  request_id=arguments.get("requestId") if door in WRITE_DOORS else None)
    try:
        client = (client_factory or default_client_factory(env))()
        files = (files_factory or (lambda built: S3DocumentFiles(built, env=env)))(client)
        if DOOR_GROUP[door] == "guidelines":
            return execute(name, payload, caller, guidelines_with_client(client, files))
        if door == "announcementsWrite":
            # A person's decision about a Delivery, which the person's own credential may not write (Delivery records are the pipeline's): the door checks who is
            # asking and writes with this function's role (announcements/review_handlers.door_write_handlers).
            from .announcements.review_handlers import door_write_handlers

            timers = delivery_timers_factory() if delivery_timers_factory else (site_delivery_timers(env) if client_factory is None else None)
            return execute(name, payload, caller, door_write_handlers(client, delivery_files_factory(client) if delivery_files_factory else None, timers))
        if DOOR_GROUP[door] == "announcements":
            from .announcements.list_handlers import with_client as announcements_with_client

            return execute(name, payload, caller, announcements_with_client(client))
        return execute(name, payload, caller, with_client(client, section_fields=SECTION_STYLE_FIELD, files=files))
    except Exception as error:   # the browser gets a state; the cause goes to the log by type only
        LOG.error("image operation failed: %s %s", name, type(error).__name__)
        return error_envelope(name, "service_unavailable")
