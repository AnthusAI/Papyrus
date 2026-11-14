"""A Reference whose title is its own web address, and the page's real title that replaces it (PPY-a1e2b0ea).

Why it happens: a web search that cites a page without naming it (the OpenAI and Gemini providers in ``web_search.py`` fall back to ``title or url``)
hands the monitor a result titled with the address, and the monitor keeps it as the new Reference's title. Capture and the link preview then read the
page's real title (``Capture.page["title"]``, the preview attachment's ``title``) but nothing wrote it back, so the card kept the address.

The rule here, used by every writer and by the one-time repair (``papyrus references repair-titles``):

* a title is replaceable only while it is empty or is an address (``http://`` or ``https://``, no spaces). Anything else was written by a person or came
  from the source, and is never replaced;
* the replacement is the page's own title, whitespace-collapsed, never an address, never a bot-wall or error page's stock title;
* the record is read again before the write, so a title set in the meantime wins.

``readable_name`` is the display fallback for a Reference that still has no real title (a blocked or unreadable page). It is never stored.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any

MAXIMUM_TITLE_CHARACTERS = 300

# What bot walls and error pages call themselves. A page that answers with one of these told us nothing about the page we wanted.
STOCK_TITLES = frozenset({
    "just a moment...", "just a moment", "attention required! | cloudflare", "access denied", "access denied | cloudflare", "403 forbidden", "forbidden",
    "404 not found", "404", "not found", "page not found", "error", "an error occurred", "robot check", "are you a robot?", "are you a human?",
    "verify you are human", "please wait...", "one moment, please...", "security check", "request blocked", "service unavailable", "502 bad gateway",
    "503 service unavailable", "pardon our interruption", "you have been blocked", "sign in", "log in", "login",
})

_ADDRESS = re.compile(r"^https?://\S+$", re.IGNORECASE)
_SPACES = re.compile(r"\s+")


def is_address(text: Any) -> bool:
    return isinstance(text, str) and bool(_ADDRESS.match(text.strip()))


def needs_title(reference: Any) -> bool:
    """True while the Reference's title is empty or is a web address: the only titles this module ever replaces."""
    title = (reference.get("title") if isinstance(reference, dict) else None) or ""
    return not str(title).strip() or is_address(title)


def usable_title(value: Any) -> str | None:
    """The page title worth storing, or None: empty, an address, or a bot wall's or error page's stock title."""
    if not isinstance(value, str):
        return None
    text = _SPACES.sub(" ", value).strip()
    if not text or is_address(text) or text.lower() in STOCK_TITLES:
        return None
    return text[:MAXIMUM_TITLE_CHARACTERS]


def first_usable_title(*values: Any) -> str | None:
    return next((found for found in map(usable_title, values) if found), None)


def record_page_title(client: Any, reference: dict[str, Any], title: Any) -> str:
    """Put the page's title on a Reference that still carries an address as its title. Returns ``set``, ``kept`` (it has a real title now) or ``unusable``.

    The row is read again first, so a title an editor or an earlier run set in the meantime is never overwritten. Raises only what the client raises;
    callers that must not fail wrap it.
    """
    found = usable_title(title)
    if found is None:
        return "unusable"
    current = client.get_record("Reference", reference["id"]) or reference
    if not needs_title(current):
        reference["title"] = current.get("title")
        return "kept"
    client.update_record("Reference", {"id": reference["id"], "title": found})
    reference["title"] = found
    return "set"


def readable_name(address: str, site_name: str | None = None) -> str:
    """A readable stand-in for a Reference with no real title, from what the address itself says: the site's name (or its host without ``www.``) and
    the words of the last meaningful path segment. ``https://labs.example.org/research/ai-coding-attack-surface-2026/`` with site "Lab Space" reads
    "Lab Space: ai coding attack surface 2026". Display only: it is not stored and is not presented as a title anywhere else."""
    parts = urllib.parse.urlsplit(address.strip())
    host = (parts.hostname or "").removeprefix("www.")
    name = _SPACES.sub(" ", site_name or "").strip() or host or address.strip()
    words = ""
    for segment in reversed([s for s in parts.path.split("/") if s]):
        decoded = urllib.parse.unquote(segment)
        decoded = re.sub(r"\.(html?|php|aspx?|pdf|md)$", "", decoded, flags=re.IGNORECASE)
        candidate = _SPACES.sub(" ", re.sub(r"[-_+.]+", " ", decoded)).strip()
        if re.search(r"[A-Za-z]{2}", candidate):
            words = candidate
            break
    return f"{name}: {words}"[:120].strip() if words else name[:120]
