"""Public handle rules, the Python twin of lib/public-handle.ts (shared vectors: scripts/fixtures/public-handle-vectors.json)."""

from __future__ import annotations

import re
from dataclasses import dataclass

PUBLIC_HANDLE_MINIMUM_LENGTH = 3
PUBLIC_HANDLE_MAXIMUM_LENGTH = 24
PUBLIC_HANDLE_CHARACTERS = re.compile(r"[a-z0-9-]*")
PUBLIC_HANDLE_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
PUBLIC_HANDLE_RESERVED = frozenset({"admin", "editor", "ai", "papyrus", "anonymous"})


@dataclass(frozen=True)
class PublicHandleCheck:
    valid: bool
    handle: str | None = None
    reason: str | None = None


def normalize_public_handle(value: str) -> str:
    return value.strip().lower()


def check_public_handle(value: str) -> PublicHandleCheck:
    handle = normalize_public_handle(value)
    if "@" in handle:
        return PublicHandleCheck(valid=False, reason="at-sign")
    if not PUBLIC_HANDLE_CHARACTERS.fullmatch(handle):
        return PublicHandleCheck(valid=False, reason="characters")
    if not PUBLIC_HANDLE_MINIMUM_LENGTH <= len(handle) <= PUBLIC_HANDLE_MAXIMUM_LENGTH:
        return PublicHandleCheck(valid=False, reason="length")
    if not PUBLIC_HANDLE_PATTERN.fullmatch(handle):
        return PublicHandleCheck(valid=False, reason="characters")
    if handle in PUBLIC_HANDLE_RESERVED:
        return PublicHandleCheck(valid=False, reason="reserved")
    return PublicHandleCheck(valid=True, handle=handle)


def public_author(public_handle: str | None, role: str | None, anonymous_label: str = "Editor") -> dict[str, str]:
    """The author shown on a public Message: the person's handle when they set one, otherwise "Editor" (or "AI" when the Message is not a person's)."""
    if role is not None and role != "human":
        return {"label": "AI"}
    if public_handle and check_public_handle(public_handle).valid:
        return {"handle": normalize_public_handle(public_handle)}
    return {"label": anonymous_label}
