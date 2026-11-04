"""Share a Story by URL (docs/story-share-links.md).

A share link shows one Story, in the website's public layout, labelled DRAFT, to people who have no newsroom sign-in (or, by choice, only to people signed in to the
newsroom). This module is the rules; ``story_share_render.py`` draws the page and ``amplify/functions/content-actions/handler.py`` is the front door.

The token is 256 bits from the operating system's CSPRNG. Only its SHA-256 hash is stored (as the record's id, so a view is one keyed lookup), the token itself is returned
once when the link is made and is never written anywhere or logged. A link that is unknown, revoked or expired answers exactly the same way (``unavailable``), so a
stranger cannot tell which. Nothing here writes to the live site: a view is rendered into the response.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .ids import hash_short
from .publishing import published_item_id_for, utc_now_iso
from .record_helpers import to_aws_json
from .staff_groups import has_editor_rights
from .story_reporting import _current_of, current_story_version, story_versions

MODEL = "StoryShare"
INDEX = "storySharesByStoryAndCreatedAt"

TOKEN_BYTES = 32  # 256 bits
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")  # what secrets.token_urlsafe(32) produces: nothing else is ever looked up
EXPIRY_DAYS = (7, 30, 90)
DEFAULT_EXPIRY_DAYS = 30

ANYONE = "anyone"
SIGNED_IN = "signed-in"
VIEWERS = (ANYONE, SIGNED_IN)

ACTIVE, REVOKED, ENDED = "active", "revoked", "ended"
ENDED_PUBLISHED, ENDED_SPIKED = "published", "spiked"

# View answers. ``unavailable`` is the one answer for an unknown, expired, revoked or ended link.
OK, UNAVAILABLE, SIGN_IN, PUBLISHED_NOTICE = "ok", "unavailable", "sign-in", "published"

SHARE_EVENTS_KEY = "shareEvents"
# The events live in one version's metadata, and an Item row is bounded by DynamoDB's 400 KB. Each event is well under 300 bytes, so this keeps the list far inside it.
MAX_SHARE_EVENTS = 200


class ShareRefused(ValueError):
    """The request breaks a rule; nothing was written. The message is for the person who asked."""


# ------------------------------------------------------------------ token


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def well_formed(token: Any) -> bool:
    return isinstance(token, str) and TOKEN_PATTERN.fullmatch(token) is not None


# ------------------------------------------------------------------ who is asking


@dataclass(frozen=True)
class Viewer:
    """The person behind a request, as the backend saw it: never from anything the browser claims."""

    signed_in: bool = False
    groups: tuple[str, ...] = ()
    sub: str | None = None
    label: str | None = None

    @property
    def is_staff(self) -> bool:
        return self.signed_in and has_editor_rights(self.groups)


ANONYMOUS = Viewer()


def viewer_from_identity(identity: dict | None) -> Viewer:
    """The viewer of an AppSync Lambda event. A Cognito user pool identity has a ``sub`` and an ``issuer``; a guest or IAM identity has neither."""
    identity = identity or {}
    sub, issuer = identity.get("sub"), identity.get("issuer")
    if not sub or not issuer:
        return ANONYMOUS
    from .staff_groups import claim_groups

    claims = identity.get("claims") or {}
    groups = claim_groups(identity.get("groups") if identity.get("groups") is not None else claims.get("cognito:groups"))
    label = claims.get("email") or identity.get("username") or None
    return Viewer(signed_in=True, groups=tuple(groups), sub=str(sub), label=str(label) if label else None)


# ------------------------------------------------------------------ time


def _parse(moment: str | None) -> datetime | None:
    if not moment:
        return None
    try:
        return datetime.strptime(moment, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def expires_at(now: str, days: int) -> str:
    started = _parse(now)
    if started is None:
        raise ShareRefused("The time is not valid.")
    return _iso(started + timedelta(days=days))


def expired(share: dict, now: str) -> bool:
    deadline, current = _parse(share.get("expiresAt")), _parse(now)
    # A record with no readable deadline is treated as expired: a link never lives longer than it says.
    return deadline is None or current is None or current >= deadline


# ------------------------------------------------------------------ Story facts


def _versions(client: Any, lineage_id: str) -> list[dict]:
    return story_versions(client, lineage_id)


def _published(client: Any, lineage_id: str) -> dict | None:
    return client.get_record("PublishedItem", published_item_id_for(lineage_id))


def _is_spiked(version: dict) -> bool:
    return (version.get("stage") or "") == "spiked"


def pick_version(versions: list[dict], version_number: int | None) -> dict | None:
    """The version a link shows, from the Story's own versions: the current one (a link that follows new versions) or one pinned version of this lineage and no other."""
    if not versions:
        return None
    if version_number is None:
        return _current_of(versions)
    return next((row for row in versions if int(row.get("versionNumber") or 0) == int(version_number)), None)


def shown_version(client: Any, lineage_id: str, version_number: int | None) -> dict | None:
    return pick_version(_versions(client, lineage_id), version_number)


# ------------------------------------------------------------------ events on the Story


def record_story_event(client: Any, lineage_id: str, event: dict[str, Any]) -> None:
    """Writes one event onto the Story's record (the current version's metadata ``shareEvents``): who made a link, when it was opened (by day), when it ended."""
    versions = _versions(client, lineage_id)
    if not versions:
        return
    row = current_story_version(client, lineage_id)
    metadata = json.loads(row.get("metadata") or "{}") if isinstance(row.get("metadata"), str) else dict(row.get("metadata") or {})
    events = [entry for entry in metadata.get(SHARE_EVENTS_KEY) or [] if isinstance(entry, dict)]
    events.append(event)
    metadata[SHARE_EVENTS_KEY] = events[-MAX_SHARE_EVENTS:]
    client.update_record("Item", {"id": row["id"], "metadata": to_aws_json(metadata)})


def story_events(client: Any, lineage_id: str) -> list[dict]:
    versions = _versions(client, lineage_id)
    if not versions:
        return []
    row = current_story_version(client, lineage_id)
    metadata = json.loads(row.get("metadata") or "{}") if isinstance(row.get("metadata"), str) else dict(row.get("metadata") or {})
    return [entry for entry in metadata.get(SHARE_EVENTS_KEY) or [] if isinstance(entry, dict)]


# ------------------------------------------------------------------ making, listing, revoking


def create_share(
    client: Any,
    lineage_id: str,
    *,
    viewers: str = ANYONE,
    version_number: int | None = None,
    expires_in_days: int = DEFAULT_EXPIRY_DAYS,
    actor: Viewer,
    now: str | None = None,
) -> dict[str, Any]:
    """Makes a link and returns it with its token, the only time the token exists outside the person's hands. Raises ShareRefused for a Story that cannot be shared."""
    if not actor.is_staff:
        raise ShareRefused("Only editors and admins can share a draft.")
    if viewers not in VIEWERS:
        raise ShareRefused(f"Who can view is {ANYONE} or {SIGNED_IN}.")
    if expires_in_days not in EXPIRY_DAYS:
        raise ShareRefused(f"A link lasts {', '.join(str(days) for days in EXPIRY_DAYS[:-1])} or {EXPIRY_DAYS[-1]} days.")
    versions = _versions(client, lineage_id)
    if not versions:
        raise ShareRefused("That Story was not found.")
    if _is_spiked(_current_of(versions)):
        raise ShareRefused("This Story is spiked, so it cannot be shared.")
    shown = pick_version(versions, version_number)
    if shown is None:
        raise ShareRefused(f"This Story has no version {version_number}.")
    published = _published(client, lineage_id)
    if published is not None and published.get("sourceItemId") == shown["id"]:
        raise ShareRefused("That version is the published one, so it has no draft to share. Its page is public.")
    now = now or utc_now_iso()
    token = new_token()
    token_hash = hash_token(token)
    share_id = hash_short([token_hash, now])[:12]
    row = {
        "id": token_hash,
        "tokenHash": token_hash,
        "shareId": share_id,
        "storyLineageId": lineage_id,
        "viewers": viewers,
        "versionNumber": int(version_number) if version_number is not None else None,
        "expiresAt": expires_at(now, expires_in_days),
        "status": ACTIVE,
        "createdAt": now,
        "createdBy": actor.sub,
        "createdByLabel": actor.label,
        "openCount": 0,
    }
    client.create_record(MODEL, {key: value for key, value in row.items() if value is not None})
    record_story_event(client, lineage_id, {"at": now, "kind": "created", "shareId": share_id, "by": actor.label or actor.sub, "viewers": viewers,
                                            "version": int(version_number) if version_number is not None else "current", "expiresAt": row["expiresAt"]})
    return {"token": token, "share": public_share(row, now)}


def public_share(row: dict, now: str | None = None) -> dict[str, Any]:
    """A link as the newsroom lists it. Never the token, never its hash."""
    now = now or utc_now_iso()
    status = row.get("status") or ACTIVE
    state = status if status != ACTIVE else ("expired" if expired(row, now) else ACTIVE)
    return {
        "shareId": row.get("shareId"),
        "viewers": row.get("viewers"),
        "version": row.get("versionNumber") if row.get("versionNumber") is not None else "current",
        "createdAt": row.get("createdAt"),
        "createdBy": row.get("createdByLabel") or row.get("createdBy"),
        "expiresAt": row.get("expiresAt"),
        "state": state,
        "endedReason": row.get("endedReason"),
        "lastOpenedOn": row.get("lastOpenedOn"),
        "openCount": int(row.get("openCount") or 0),
    }


def list_shares(client: Any, lineage_id: str, *, actor: Viewer, now: str | None = None) -> list[dict[str, Any]]:
    if not actor.is_staff:
        raise ShareRefused("Only editors and admins can see a Story's links.")
    rows = client.list_by_index(INDEX, lineage_id)
    now = now or utc_now_iso()
    return [public_share(row, now) for row in sorted(rows, key=lambda entry: str(entry.get("createdAt") or ""), reverse=True)]


def revoke_share(client: Any, lineage_id: str, share_id: str, *, actor: Viewer, now: str | None = None) -> dict[str, Any]:
    if not actor.is_staff:
        raise ShareRefused("Only editors and admins can revoke a link.")
    now = now or utc_now_iso()
    row = next((entry for entry in client.list_by_index(INDEX, lineage_id) if entry.get("shareId") == share_id), None)
    if row is None:
        raise ShareRefused("That link was not found on this Story.")
    if (row.get("status") or ACTIVE) != ACTIVE:
        return {"changed": False, "share": public_share(row, now)}
    client.update_record(MODEL, {"id": row["id"], "status": REVOKED, "endedAt": now, "endedReason": REVOKED, "revokedBy": actor.label or actor.sub})
    record_story_event(client, lineage_id, {"at": now, "kind": "revoked", "shareId": share_id, "by": actor.label or actor.sub})
    return {"changed": True, "share": public_share({**row, "status": REVOKED, "endedReason": REVOKED}, now)}


def end_shares(client: Any, lineage_id: str, reason: str, *, now: str | None = None) -> int:
    """Ends every active link of a Story because the Story was published or spiked. Returns how many it ended."""
    now = now or utc_now_iso()
    ended = 0
    for row in client.list_by_index(INDEX, lineage_id):
        if (row.get("status") or ACTIVE) != ACTIVE:
            continue
        client.update_record(MODEL, {"id": row["id"], "status": ENDED, "endedAt": now, "endedReason": reason})
        record_story_event(client, lineage_id, {"at": now, "kind": "ended", "shareId": row.get("shareId"), "reason": reason})
        ended += 1
    return ended


# ------------------------------------------------------------------ viewing


@dataclass(frozen=True)
class Resolution:
    state: str
    share: dict | None = None
    version: dict | None = None
    published: dict | None = None


def _gone() -> Resolution:
    return Resolution(UNAVAILABLE)


def resolve_share(client: Any, token: Any, viewer: Viewer, *, now: str | None = None) -> Resolution:
    """What a token opens, for this viewer. Every way a link can be unusable (never made, revoked, expired, ended, the Story spiked, a version that is gone) is the same
    ``unavailable``. The only other answers come after the token has proved itself: ``sign-in`` (a signed-in link, nobody signed in) and ``published`` (the Story went live)."""
    if not well_formed(token):
        return _gone()
    token_hash = hash_token(token)
    share = client.get_record(MODEL, token_hash)
    if share is None or not hmac.compare_digest(str(share.get("tokenHash") or ""), token_hash):
        return _gone()
    now = now or utc_now_iso()
    status = share.get("status") or ACTIVE
    if status not in (ACTIVE, ENDED) or expired(share, now) or (status == ENDED and share.get("endedReason") != ENDED_PUBLISHED):
        return _gone()  # revoked, expired, or ended by a spike: nothing more to say
    if share.get("viewers") == SIGNED_IN:
        if not viewer.signed_in:
            return Resolution(SIGN_IN, share=share)
        if not viewer.is_staff:
            return _gone()  # signed in, but the newsroom's own rule says no: no more detail than a stranger gets
    elif share.get("viewers") != ANYONE:
        return _gone()
    lineage_id = share.get("storyLineageId")
    if not lineage_id:
        return _gone()
    versions = _versions(client, lineage_id)
    if not versions:
        return _gone()
    if _is_spiked(_current_of(versions)):
        return _gone()
    shown = pick_version(versions, share.get("versionNumber"))
    if shown is None:
        return _gone()
    published = _published(client, lineage_id)
    if status == ENDED:
        # Ended because the Story was published: the old address says so and points at the public page, if the Story is still live.
        return Resolution(PUBLISHED_NOTICE, share=share, published=published) if published is not None else _gone()
    if published is not None and (str(published.get("publishedAt") or "") >= str(share.get("createdAt") or "") or published.get("sourceItemId") == shown["id"]):
        return Resolution(PUBLISHED_NOTICE, share=share, published=published)
    return Resolution(OK, share=share, version=shown, published=published)


def record_open(client: Any, share: dict, *, now: str | None = None) -> None:
    """Counts an open, coarsely: a total and the day of the last one. Nothing about the viewer (no address, no agent, no identity) is read or kept."""
    now = now or utc_now_iso()
    today = now[:10]
    client.update_record(MODEL, {"id": share["id"], "openCount": int(share.get("openCount") or 0) + 1, "lastOpenedOn": today})
    if share.get("lastOpenedOn") != today:
        record_story_event(client, share["storyLineageId"], {"at": today, "kind": "opened", "shareId": share.get("shareId")})
