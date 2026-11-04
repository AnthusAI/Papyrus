"""A Reference's medium, read off its address by rule (docs/reference-curation-pipeline.md, "Medium").

Medium is the third attribute of a Reference, separate from its evidence level and its voice (PPY-f8ff49). It is set from the address alone, by
no model, and only where the address is certain: ``video`` for the address of one video on a known platform, and nothing otherwise. An empty
medium means "not known", never "not a video".

Every platform is matched by exact URL shape (host, then the whole path), not by a substring: a channel page, a user page, a Vimeo category
or a ``youtube.com/about`` page is not a video. A playlist, showcase, album or collection is an aggregation: it gets ``evidenceLevel``
``aggregation`` (the same field PPY-f8ff49's decision model will write, with ``primary``, ``secondary`` and ``unknown``) and no medium, so a video
listing never includes it. A YouTube watch address that carries a ``list`` parameter names both a video and a playlist: it is the video,
and the playlist's own address is returned separately as ``playlist_url`` for the follow story (PPY-566e82).

YouTube's shapes come from ``youtube_transcript.video_id``, the same reader capture uses, so the two cannot disagree.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Mapping

from .youtube_transcript import video_id as youtube_video_id

MEDIUM_VIDEO = "video"
MEDIUMS = (MEDIUM_VIDEO,)
EVIDENCE_AGGREGATION = "aggregation"
PLATFORMS = ("youtube", "vimeo", "dailymotion", "loom", "wistia", "ted", "twitch")

YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com", "youtu.be"})
_PLAYLIST_ID = re.compile(r"^[\w-]{10,64}$")
_DIGITS = re.compile(r"^\d+$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_SLUG = re.compile(r"^[\w.~-]+$")
_WISTIA_ID = re.compile(r"^[a-z0-9]{10}$")
_DAILYMOTION_ID = re.compile(r"^[a-z0-9]{5,10}$")


@dataclass(frozen=True)
class Classification:
    """What an address says about a Reference. Every field is empty when the address says nothing certain."""

    medium: str | None = None
    evidence_level: str | None = None
    platform: str | None = None
    playlist_url: str | None = None


NOTHING = Classification()


def _segments(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def _query(parts: urllib.parse.SplitResult) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(parts.query)


def _youtube_playlist_url(identifier: str) -> str:
    return "https://www.youtube.com/playlist?" + urllib.parse.urlencode({"list": identifier})


def _youtube(parts: urllib.parse.SplitResult, address: str) -> Classification:
    query = _query(parts)
    listed = (query.get("list") or [""])[0]
    listed = listed if _PLAYLIST_ID.match(listed) else ""
    segments = _segments(parts.path)
    if parts.hostname == "youtu.be":
        pass
    elif segments[:1] == ["playlist"] and len(segments) == 1:
        return Classification(evidence_level=EVIDENCE_AGGREGATION, platform="youtube") if listed else NOTHING
    elif segments[:2] == ["embed", "videoseries"] and len(segments) == 2:
        return Classification(evidence_level=EVIDENCE_AGGREGATION, platform="youtube") if listed else NOTHING
    identifier = youtube_video_id(address)
    if identifier is None:
        return NOTHING
    return Classification(medium=MEDIUM_VIDEO, platform="youtube", playlist_url=_youtube_playlist_url(listed) if listed else None)


def _vimeo(parts: urllib.parse.SplitResult) -> Classification:
    host, segments = parts.hostname or "", _segments(parts.path)
    video = Classification(medium=MEDIUM_VIDEO, platform="vimeo")
    collection = Classification(evidence_level=EVIDENCE_AGGREGATION, platform="vimeo")
    if host == "player.vimeo.com":
        return video if len(segments) == 2 and segments[0] == "video" and _DIGITS.match(segments[1]) else NOTHING
    if host not in {"vimeo.com", "www.vimeo.com"} or not segments:
        return NOTHING
    if _DIGITS.match(segments[0]):
        # vimeo.com/<id> and the unlisted form vimeo.com/<id>/<hash>
        return video if len(segments) == 1 or (len(segments) == 2 and re.match(r"^[0-9a-f]{6,}$", segments[1])) else NOTHING
    if segments[0] in {"showcase", "album"}:
        if len(segments) == 2 and _DIGITS.match(segments[1]):
            return collection
        if len(segments) == 4 and _DIGITS.match(segments[1]) and segments[2] == "video" and _DIGITS.match(segments[3]):
            return video
        return NOTHING
    if segments[0] == "channels":
        if len(segments) == 2 and _SLUG.match(segments[1]):
            return collection
        if len(segments) == 3 and _SLUG.match(segments[1]) and _DIGITS.match(segments[2]):
            return video
        return NOTHING
    if segments[0] == "groups" and len(segments) == 4 and segments[2] == "videos" and _DIGITS.match(segments[3]):
        return video
    return NOTHING   # a user page, a category, ondemand, search: not certain


def _dailymotion(parts: urllib.parse.SplitResult) -> Classification:
    host, segments = parts.hostname or "", _segments(parts.path)
    if host == "dai.ly":
        return Classification(medium=MEDIUM_VIDEO, platform="dailymotion") if len(segments) == 1 and _DAILYMOTION_ID.match(segments[0]) else NOTHING
    if host not in {"dailymotion.com", "www.dailymotion.com", "geo.dailymotion.com"}:
        return NOTHING
    if segments[:1] == ["embed"]:
        segments = segments[1:]
    if len(segments) == 2 and segments[0] == "video" and _DAILYMOTION_ID.match(segments[1]):
        return Classification(medium=MEDIUM_VIDEO, platform="dailymotion")
    if len(segments) == 2 and segments[0] == "playlist" and _DAILYMOTION_ID.match(segments[1]):
        return Classification(evidence_level=EVIDENCE_AGGREGATION, platform="dailymotion")
    return NOTHING


def _loom(parts: urllib.parse.SplitResult) -> Classification:
    segments = _segments(parts.path)
    if parts.hostname in {"loom.com", "www.loom.com"} and len(segments) == 2 and segments[0] in {"share", "embed"} and _HEX32.match(segments[1].lower()):
        return Classification(medium=MEDIUM_VIDEO, platform="loom")
    return NOTHING


def _wistia(parts: urllib.parse.SplitResult) -> Classification:
    host, segments = parts.hostname or "", _segments(parts.path)
    if host.endswith(".wistia.com") and len(segments) == 2 and segments[0] == "medias" and _WISTIA_ID.match(segments[1]):
        return Classification(medium=MEDIUM_VIDEO, platform="wistia")
    if host == "fast.wistia.net" and len(segments) == 3 and segments[:2] == ["embed", "iframe"] and _WISTIA_ID.match(segments[2]):
        return Classification(medium=MEDIUM_VIDEO, platform="wistia")
    return NOTHING


def _ted(parts: urllib.parse.SplitResult) -> Classification:
    segments = _segments(parts.path)
    if parts.hostname not in {"ted.com", "www.ted.com"}:
        return NOTHING
    if len(segments) == 2 and segments[0] == "talks" and _SLUG.match(segments[1]):
        return Classification(medium=MEDIUM_VIDEO, platform="ted")
    if len(segments) == 3 and segments[0] == "playlists" and _DIGITS.match(segments[1]) and _SLUG.match(segments[2]):
        return Classification(evidence_level=EVIDENCE_AGGREGATION, platform="ted")
    return NOTHING   # /talks (the listing), a speaker, a topic, a transcript page


def _twitch(parts: urllib.parse.SplitResult) -> Classification:
    host, segments = parts.hostname or "", _segments(parts.path)
    video = Classification(medium=MEDIUM_VIDEO, platform="twitch")
    if host == "clips.twitch.tv":
        return video if len(segments) == 1 and _SLUG.match(segments[0]) else NOTHING
    if host not in {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}:
        return NOTHING
    if len(segments) == 2 and segments[0] == "videos" and _DIGITS.match(segments[1]):
        return video
    if len(segments) == 3 and segments[1] == "clip" and _SLUG.match(segments[2]):
        return video
    if len(segments) == 2 and segments[0] == "collections" and _SLUG.match(segments[1]):
        return Classification(evidence_level=EVIDENCE_AGGREGATION, platform="twitch")
    return NOTHING   # a channel page (live or not) is not one video


def classify_address(address: Any) -> Classification:
    """The medium, evidence level (aggregation only) and playlist address an address certainly says, else nothing. Never raises."""
    if not isinstance(address, str) or not address.strip():
        return NOTHING
    try:
        parts = urllib.parse.urlsplit(address.strip())
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return NOTHING
    if parts.scheme.lower() not in {"http", "https"} or not host:
        return NOTHING
    parts = parts._replace(netloc=host)   # one case for the host; the path keeps its own
    normalized = urllib.parse.urlunsplit(parts._replace(scheme=parts.scheme.lower()))
    if host in YOUTUBE_HOSTS:
        return _youtube(parts, normalized)
    if host.endswith("vimeo.com"):
        return _vimeo(parts)
    if host in {"dailymotion.com", "www.dailymotion.com", "geo.dailymotion.com", "dai.ly"}:
        return _dailymotion(parts)
    if host in {"loom.com", "www.loom.com"}:
        return _loom(parts)
    if host.endswith("wistia.com") or host == "fast.wistia.net":
        return _wistia(parts)
    if host in {"ted.com", "www.ted.com"}:
        return _ted(parts)
    if host.endswith("twitch.tv"):
        return _twitch(parts)
    return NOTHING


def medium_of(address: Any) -> str | None:
    return classify_address(address).medium


def medium_fields(reference: Mapping[str, Any]) -> dict[str, Any]:
    """The fields a new Reference gets from its address: only what the address says (nothing for an ordinary page).

    ``evidenceLevel`` is set only when the Reference has none, so a value written by an editor or the decision model is never overwritten.
    """
    found = classify_address(reference.get("sourceUri"))
    fields: dict[str, Any] = {}
    if found.medium:
        fields["medium"] = found.medium
    if found.playlist_url:
        fields["playlistUrl"] = found.playlist_url
    if found.evidence_level and not reference.get("evidenceLevel"):
        fields["evidenceLevel"] = found.evidence_level
    return fields


def stale_medium_fields(reference: Mapping[str, Any]) -> dict[str, Any]:
    """What the backfill writes: ``medium`` and ``playlistUrl`` made to match the address (cleared when it says nothing), ``evidenceLevel`` only filled."""
    wanted = medium_fields(reference)
    changes: dict[str, Any] = {}
    for field in ("medium", "playlistUrl"):
        if (reference.get(field) or None) != wanted.get(field):
            changes[field] = wanted.get(field)
    if wanted.get("evidenceLevel"):
        changes["evidenceLevel"] = wanted["evidenceLevel"]
    return changes


def medium_partition(corpus_id: str, medium: str = MEDIUM_VIDEO, status: str = "accepted") -> str:
    """The partition of the medium index a list reads: ``<corpusId>#<medium>#<status>``, for example ``knowledge-corpus-site#video#accepted``."""
    return f"{corpus_id}#{medium}#{status}"


def iterate_references_by_medium(client: Any, corpus_id: str, medium: str = MEDIUM_VIDEO, status: str = "accepted"):
    """Current Reference rows of one corpus with this medium and vote, newest arrival first, one page at a time and never a scan
    (``listReferencesByMediumFeedAndArrival``). With ``status="accepted"`` every row is a row a public page may show: the partition holds
    nothing else, so nothing is filtered after reading."""
    yield from client.iterate_newest_first("referencesByMediumFeedAndArrival", medium_partition(corpus_id, medium, status))
