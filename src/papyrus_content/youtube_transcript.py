"""Which addresses are YouTube videos (``video_id``), for the capture and the medium rule. Standard library only.

Nothing here fetches a transcript: YouTube refuses cloud addresses, so no Lambda tries. The transcript is read by the worker command
``papyrus references capture-transcripts`` (``references_transcripts.py``) on a non-cloud connection.
"""

from __future__ import annotations

import re
import urllib.parse

YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"})
VIDEO_ID = re.compile(r"^[\w-]{11}$")
PATH_PREFIXES = ("/shorts/", "/embed/", "/live/", "/v/")


def video_id(url: str) -> str | None:
    """The 11-character id of a watch, short, shorts, live or embed link; None for any other address."""
    parts = urllib.parse.urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host == "youtu.be":
        found = parts.path.lstrip("/").split("/")[0]
    elif host in YOUTUBE_HOSTS:
        found = next((parts.path[len(prefix):].split("/")[0] for prefix in PATH_PREFIXES if parts.path.startswith(prefix)), "")
        if parts.path == "/watch":
            found = (urllib.parse.parse_qs(parts.query).get("v") or [""])[0]
    else:
        return None
    return found if VIDEO_ID.match(found) else None
