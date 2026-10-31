"""Message threads in, public-safe threads out.

A thread is public only when it is an active conversation on a Reference that is in the current snapshot or on a published Story. A
Message is public only when it is an active comment that was never deleted. Every public Message is built from the fields named in
``PUBLIC_MESSAGE_FIELDS`` and nothing else: no sub, profile id, author label or any other id is ever written. The author is the person's
opt-in public handle, otherwise a role label. Free text is scrubbed of anything shaped like an email address, a UUID or a site subject
and stripped of raw HTML, but is otherwise published as written.

Nothing here imports the CLI login library: the Lambda bundles that run the snapshot task do not ship it.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from .export import KEY_LENGTH, PRIVATE_SHAPES, public_key
from .handles import public_author

if TYPE_CHECKING:
    from .settings import HomePageSettings

REFERENCE_THREAD_KIND = "reference_conversation"
STORY_THREAD_KIND = "story_conversation"
PUBLIC_THREAD_KINDS = (REFERENCE_THREAD_KIND, STORY_THREAD_KIND)
REFERENCE_ANCHOR_PREFIX = "reference#"
STORY_ANCHOR_PREFIX = "item#"
ACTIVE = "active"
PUBLIC_MESSAGE_KIND = "comment"
HANDLE_POLICY = "handle"

PUBLIC_MESSAGE_FIELDS = ("key", "at", "edited", "text", "author")
NEVER_PUBLISHED_FIELDS = (
    "authorSub", "authorUserProfileId", "authorLabel", "deletedBySub", "createdBySub", "createdByUserProfileId", "createdByLabel",
    "metadata", "responseOwner", "id", "threadId", "parentMessageId", "primaryAnchorId", "primaryAnchorLineageId", "primaryAnchorKey",
)

HTML_TAG = re.compile(r"</?[A-Za-z!][^>]*>")

StoryAnchor = Callable[[str], "Mapping[str, str] | None"]


def opaque_key(record_id: str) -> str:
    return hashlib.sha256(record_id.encode()).hexdigest()[:KEY_LENGTH]


def clean_text(text: Any) -> str | None:
    """Verbatim text minus raw HTML and anything shaped like an email address, a UUID or a site subject; line breaks are kept."""
    if text is None:
        return None
    cleaned = HTML_TAG.sub("", str(text))
    for pattern in PRIVATE_SHAPES:
        cleaned = pattern.sub("", cleaned)
    cleaned = cleaned.strip()
    return cleaned or None


def is_public_message(row: Mapping[str, Any]) -> bool:
    return row.get("status") == ACTIVE and row.get("messageKind") == PUBLIC_MESSAGE_KIND and not row.get("deletedAt")


class HandleLookup:
    """The opt-in public handle of a profile, read once per run; nothing else of the profile is read."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._handles: dict[str, str | None] = {}

    def handle_of(self, profile_id: Any) -> str | None:
        if not profile_id:
            return None
        key = str(profile_id)
        if key not in self._handles:
            profile = self._client.get_record("UserProfile", key)
            handle = (profile or {}).get("publicHandle")
            self._handles[key] = handle if isinstance(handle, str) and handle.strip() else None
        return self._handles[key]


def public_message(row: Mapping[str, Any], handles: HandleLookup, settings: HomePageSettings) -> dict[str, Any] | None:
    """One public Message, or ``None`` when it is not public or has no text left once scrubbed."""
    if not is_public_message(row):
        return None
    text = clean_text(row.get("content"))
    if text is None:
        return None
    handle = handles.handle_of(row.get("authorUserProfileId")) if settings.threads.authors == HANDLE_POLICY else None
    return {
        "key": opaque_key(str(row["id"])),
        "at": row.get("createdAt"),
        "edited": bool(row.get("editedAt")),
        "text": text,
        "author": public_author(handle, row.get("role"), settings.threads.anonymous_label),
    }


def anchor_of(thread: Mapping[str, Any], public_references: Mapping[str, str], story_anchor: StoryAnchor | None) -> dict[str, str] | None:
    """The public anchor of a thread, or ``None`` when its Reference is not in the snapshot or its Story is not published."""
    anchor_key = str(thread.get("primaryAnchorKey") or "")
    if thread.get("threadKind") == REFERENCE_THREAD_KIND and anchor_key.startswith(REFERENCE_ANCHOR_PREFIX):
        key = public_key(anchor_key.removeprefix(REFERENCE_ANCHOR_PREFIX))
        return {"kind": "reference", "key": key, "title": public_references[key]} if key in public_references else None
    if thread.get("threadKind") == STORY_THREAD_KIND and anchor_key.startswith(STORY_ANCHOR_PREFIX) and story_anchor is not None:
        story = story_anchor(anchor_key.removeprefix(STORY_ANCHOR_PREFIX))
        return {"kind": "story", "url": story["url"], "title": story["title"]} if story else None
    return None


def public_thread(
    thread: Mapping[str, Any],
    messages: list[Mapping[str, Any]],
    anchor: Mapping[str, str],
    handles: HandleLookup,
    settings: HomePageSettings,
) -> dict[str, Any] | None:
    """The public form of a thread: its title, anchor and its public Messages in sequence; ``None`` when none is public."""
    ordered = sorted(messages, key=lambda row: (row.get("sequenceNumber") is None, row.get("sequenceNumber") or 0, str(row.get("createdAt") or "")))
    public = [message for message in (public_message(row, handles, settings) for row in ordered) if message is not None]
    if not public:
        return None
    return {
        "key": opaque_key(str(thread["id"])),
        "title": clean_text(thread.get("title")) or anchor["title"],
        "anchor": dict(anchor),
        "messages": public,
    }


def collect_threads(
    client: Any,
    public_references: Mapping[str, str],
    settings: HomePageSettings,
    *,
    story_anchor: StoryAnchor | None = None,
) -> list[dict[str, Any]]:
    """The public threads of the site, most recently active first.

    ``public_references`` maps the public key of every Reference in the snapshot to its title; ``story_anchor`` turns a Story's lineage id
    into ``{"url", "title"}`` when that Story is published and has a page, and into ``None`` otherwise.
    """
    handles = HandleLookup(client)
    found: list[dict[str, Any]] = []
    for kind in PUBLIC_THREAD_KINDS:
        for thread in client.list_by_index("messageThreadsByKindAndUpdatedAt", kind):
            if not thread or thread.get("status") != ACTIVE or not thread.get("id"):
                continue
            anchor = anchor_of(thread, public_references, story_anchor)
            if anchor is None:
                continue
            messages = client.list_by_index("messagesByThreadAndSequence", str(thread["id"]))
            public = public_thread(thread, [row for row in messages if row], anchor, handles, settings)
            if public is not None:
                found.append(public)
    return sorted(found, key=lambda entry: (entry["messages"][-1]["at"] or "", entry["key"]), reverse=True)
