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

from .images.handlers import Caller, error_envelope, execute
from .images.operations import operation
from .images.profile_handlers import SECTION_STYLE_FIELD, with_client
from .guidelines.handlers import with_client as guidelines_with_client
from .guidelines.s3_files import S3DocumentFiles
from .staff_groups import claim_groups, has_editor_rights

LOG = logging.getLogger(__name__)
DOORS = {"imageRead": ("read",), "imageWrite": ("write", "spend"), "guidelinesRead": ("read",), "guidelinesWrite": ("write",)}
DOOR_GROUP = {"imageRead": "images", "imageWrite": "images", "guidelinesRead": "guidelines", "guidelinesWrite": "guidelines"}
DOOR_FOR = {("images", True): "imageRead", ("images", False): "imageWrite", ("guidelines", True): "guidelinesRead", ("guidelines", False): "guidelinesWrite"}
WRITE_DOORS = ("imageWrite", "guidelinesWrite")


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


def handle(event: dict, *, env: Any = None, client_factory: Callable[[], Any] | None = None, files_factory: Callable[[Any], Any] | None = None) -> dict:
    """AppSync resolver entry for the four door fields. Returns the envelope as the field's JSON.

    ``files_factory(client)`` supplies where guideline documents are kept (S3 by default); tests pass an in-memory one."""
    env = os.environ if env is None else env
    identity = event.get("identity") or {}
    claims = identity.get("claims") or {}
    groups = identity.get("groups") if identity.get("groups") is not None else claims.get("cognito:groups")
    door = str((event.get("info") or {}).get("fieldName") or "")
    arguments = event.get("arguments") or {}
    name = arguments.get("op")
    if door not in DOORS or not isinstance(name, str):
        return error_envelope(str(name), "invalid_input", "Give an op, through imageRead, imageWrite, guidelinesRead or guidelinesWrite.", details={"path": "op"})
    if not has_editor_rights(groups):
        return error_envelope(name, "not_authorized")
    item = operation(name)
    if item is not None and (item.group != DOOR_GROUP[door] or item.effect not in DOORS[door]):
        right = DOOR_FOR[(item.group, item.effect == "read")]
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
        if DOOR_GROUP[door] == "guidelines":
            files = (files_factory or (lambda built: S3DocumentFiles(built, env=env)))(client)
            return execute(name, payload, caller, guidelines_with_client(client, files))
        return execute(name, payload, caller, with_client(client, section_fields=SECTION_STYLE_FIELD))
    except Exception as error:   # the browser gets a state; the cause goes to the log by type only
        LOG.error("image operation failed: %s %s", name, type(error).__name__)
        return error_envelope(name, "service_unavailable")
