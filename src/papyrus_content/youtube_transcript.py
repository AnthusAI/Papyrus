"""The transcript of a YouTube video, read with ``youtube-transcript-api``, for the one capture path that turns a video link into text.

YouTube often refuses cloud addresses, so a failure is normal and typed: ``fetch_transcript`` never raises and answers ``(text, reason)``
with a URL-free reason (``blocked``, ``no_transcript``, ``unavailable``, ``unreadable`` or ``library_missing``). Every attempt prints one
structured line so CloudWatch can count how often YouTube blocks the Lambda.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Callable

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


def _reason(error: Exception) -> str:
    from youtube_transcript_api import (AgeRestricted, InvalidVideoId, NoTranscriptFound, RequestBlocked, TranscriptsDisabled,
                                        VideoUnavailable, VideoUnplayable, YouTubeRequestFailed)

    if isinstance(error, RequestBlocked) or (isinstance(error, YouTubeRequestFailed) and "429" in str(error)):
        return "blocked"
    if isinstance(error, (TranscriptsDisabled, NoTranscriptFound)):
        return "no_transcript"
    if isinstance(error, (VideoUnavailable, VideoUnplayable, InvalidVideoId, AgeRestricted)):
        return "unavailable"
    return "unreadable"


def fetch_transcript(identifier: str, *, api_factory: Callable[[], object] | None = None) -> tuple[str | None, str | None]:
    """``(text, None)`` with the spoken words as one paragraph, or ``(None, reason)``. English when offered, else the first track."""
    reason: str | None = None
    text: str | None = None
    try:
        if api_factory is None:
            from youtube_transcript_api import YouTubeTranscriptApi as api_factory  # noqa: N813
        tracks = api_factory().list(identifier)
        try:
            track = tracks.find_transcript(["en"])
        except Exception:  # noqa: BLE001 - no English track: take whatever YouTube offers first
            track = next(iter(tracks))
        text = " ".join(" ".join(snippet.text.split()) for snippet in track.fetch()).strip() or None
        reason = None if text else "no_transcript"
    except ImportError:
        reason = "library_missing"
    except Exception as error:  # noqa: BLE001 - YouTube refuses cloud addresses in many shapes; every one is a typed fallback
        reason = _reason(error)
    print(json.dumps({"youtubeTranscript": "captured" if text else "fallback", "videoId": identifier, "reason": reason,
                      "characters": len(text or "")}))
    return text, reason
