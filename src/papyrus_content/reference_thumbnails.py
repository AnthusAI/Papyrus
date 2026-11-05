"""A video Reference's own thumbnail: where it comes from, how it is checked, how it is named in our storage and how it is recorded.

A card for a video shows the video's thumbnail. The address comes from the video itself, not from the page's ``og:image``:

* YouTube: ``https://img.youtube.com/vi/<id>/hqdefault.jpg``, built from the id ``youtube_transcript.video_id`` reads. No API key, no page fetch.
  A missing video answers 404 with a grey 120 x 90 picture, so a picture narrower than ``MINIMUM_WIDTH`` is never taken.
* The other platforms in ``reference_medium.PLATFORMS`` that have an oEmbed endpoint (Vimeo, Dailymotion, Loom, Wistia, TED) are asked for
  ``thumbnail_url``. Twitch has no oEmbed endpoint, so a Twitch video gets none.

The picture is copied into our own storage (``media/assets/reference-thumbnails/...``, the media bucket the renditions function listens to) and
only that copy is published, so a reader's browser never contacts the platform and a takedown does not break the card. ``Reference.thumbnailPath``
holds the result: the site path of the copy, or ``none`` when the platform has no thumbnail (recorded so nobody asks again). A network failure
records nothing, so the next run tries again.

Fetching happens in ``papyrus references capture-thumbnails`` (``references_thumbnails.py``), on a connection YouTube answers: nothing here is
proven from a cloud address. This module holds the parts both the worker and the content-actions function use. Standard library and Pillow only.
"""
from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .ids import hash_short
from .reference_medium import MEDIUM_VIDEO, classify_address
from .youtube_transcript import video_id

DIRECTORY = "assets/reference-thumbnails"
NO_THUMBNAIL = "none"
FIELD = "thumbnailPath"
YOUTUBE_ADDRESS = "https://img.youtube.com/vi/{id}/hqdefault.jpg"
#: oEmbed endpoints by platform (``reference_medium.PLATFORMS``). Twitch has none.
OEMBED = {
    "vimeo": "https://vimeo.com/api/oembed.json?url={url}",
    "dailymotion": "https://www.dailymotion.com/services/oembed?format=json&url={url}",
    "loom": "https://www.loom.com/v1/oembed?url={url}",
    "wistia": "https://fast.wistia.com/oembed?url={url}",
    "ted": "https://www.ted.com/services/v1/oembed.json?url={url}",
}
#: YouTube's grey stand-in for a missing picture is 120 px wide; a real hqdefault is 480 px. oEmbed thumbnails can be small (Vimeo gives 295 px).
MINIMUM_WIDTH = {"youtube": 320}
DEFAULT_MINIMUM_WIDTH = 200
MAXIMUM_BYTES = 3_000_000
TIMEOUT_SECONDS = 20
FORMATS = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"), "WEBP": ("webp", "image/webp")}
SOURCE_PATH = re.compile(rf"^{re.escape(DIRECTORY)}/[0-9a-f]{{16}}-[0-9a-f]{{12}}\.(?:jpg|png|webp)$")
EDITOR_IMAGE = "editor"   # a preview attachment whose metadata says ``via: editor`` is an image a person chose; it is never replaced


class NoThumbnail(Exception):
    """The platform has no thumbnail for this video (or none we may take). Settled: recorded as ``none`` and not asked again."""


class Unreachable(Exception):
    """The platform could not be asked (network error, refusal, a server fault). Nothing is recorded; the next run tries again."""


class Refused(ValueError):
    """The record request is not one we accept (the content-actions function answers it as a rejected correction)."""


@dataclass(frozen=True)
class Response:
    status: int
    content_type: str
    body: bytes


Http = Callable[[str], Response]


@dataclass(frozen=True)
class Thumbnail:
    data: bytes
    media_type: str
    extension: str
    width: int
    height: int
    sha256: str
    source_url: str
    platform: str


def public_https_address(address: Any) -> str | None:
    """An https address on a named public host, or None. A literal IP, ``localhost`` and local names are refused, so a platform's answer cannot send the worker to a private address."""
    try:
        parts = urllib.parse.urlsplit(str(address or "").strip())
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    if "." not in host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home")):
        return None
    return parts.geturl()


def fetch_http(address: str) -> Response:
    """One GET with a short timeout and a size ceiling. Raises ``Unreachable`` for a network failure; an HTTP error status is a ``Response``."""
    request = urllib.request.Request(address, headers={"User-Agent": "papyrus-thumbnail-worker", "Accept": "image/*,application/json;q=0.8"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as answer:   # noqa: S310 - https only, see public_https_address
            body = answer.read(MAXIMUM_BYTES + 1)
            return Response(answer.status, answer.headers.get("Content-Type", ""), body)
    except urllib.error.HTTPError as error:
        return Response(error.code, error.headers.get("Content-Type", "") if error.headers else "", b"")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise Unreachable(f"{type(error).__name__}: {str(error)[:120]}") from error


def platform_of(address: Any) -> str | None:
    found = classify_address(address)
    return found.platform if found.medium == MEDIUM_VIDEO else None


def thumbnail_address(address: str, http: Http = fetch_http) -> tuple[str, str]:
    """``(platform, picture address)`` of a video address. YouTube is built from the id with no request; an oEmbed platform is asked once.

    Raises ``NoThumbnail`` when the address is no video, the platform has no oEmbed endpoint, or the platform says it has no picture, and
    ``Unreachable`` when the platform could not be asked.
    """
    platform = platform_of(address)
    if platform is None:
        raise NoThumbnail("not a video address")
    if platform == "youtube":
        identifier = video_id(address)
        if identifier is None:
            raise NoThumbnail("no video id")
        return platform, YOUTUBE_ADDRESS.format(id=identifier)
    template = OEMBED.get(platform)
    if template is None:
        raise NoThumbnail(f"{platform} has no oEmbed endpoint")
    answer = http(template.format(url=urllib.parse.quote(address, safe="")))
    if answer.status in (401, 403, 404, 410):
        raise NoThumbnail(f"{platform} oEmbed answered {answer.status}")
    if answer.status != 200:
        raise Unreachable(f"{platform} oEmbed answered {answer.status}")
    try:
        found = json.loads(answer.body.decode("utf-8")).get("thumbnail_url")
    except (ValueError, AttributeError) as error:
        raise Unreachable(f"{platform} oEmbed answer was not JSON") from error
    safe = public_https_address(found)
    if safe is None:
        raise NoThumbnail(f"{platform} oEmbed named no usable thumbnail")
    return platform, safe


def read_picture(body: bytes, platform: str, source_url: str) -> Thumbnail:
    """Check bytes are a real picture of a usable size and make the ``Thumbnail``. Raises ``NoThumbnail`` for anything else (including YouTube's grey stand-in)."""
    from PIL import Image

    if not body or len(body) > MAXIMUM_BYTES:
        raise NoThumbnail("empty or too large")
    try:
        with Image.open(io.BytesIO(body)) as picture:
            picture.verify()
        with Image.open(io.BytesIO(body)) as picture:
            kind, (width, height) = picture.format, picture.size
    except Exception as error:  # noqa: BLE001 - Pillow raises several kinds for damaged files
        raise NoThumbnail("not a picture") from error
    if kind not in FORMATS:
        raise NoThumbnail(f"unsupported picture format {kind}")
    if width < MINIMUM_WIDTH.get(platform, DEFAULT_MINIMUM_WIDTH):
        raise NoThumbnail(f"picture is only {width} px wide (a stand-in for a missing thumbnail)")
    extension, media_type = FORMATS[kind]
    return Thumbnail(body, media_type, extension, width, height, hashlib.sha256(body).hexdigest(), source_url, platform)


def fetch_thumbnail(address: str, http: Http = fetch_http) -> Thumbnail:
    """The checked thumbnail of a video address. Raises ``NoThumbnail`` (settled) or ``Unreachable`` (try again later)."""
    platform, picture = thumbnail_address(address, http)
    answer = http(picture)
    if answer.status in (404, 410):
        raise NoThumbnail(f"{platform} answered {answer.status} for the picture")
    if answer.status != 200:   # a 403 or 429 from the picture host may be this connection being refused: try again later, record nothing
        raise Unreachable(f"{platform} answered {answer.status} for the picture")
    return read_picture(answer.body, platform, picture)


def source_path(reference: Mapping[str, Any], thumbnail: Thumbnail) -> str:
    """The site path of the copy: the Reference's lineage and the picture's own hash, so the same picture is one object and a new one is a new address."""
    lineage = str(reference.get("lineageId") or reference["id"])
    return f"{DIRECTORY}/{hash_short(lineage)}-{thumbnail.sha256[:12]}.{thumbnail.extension}"


def media_key(path: str) -> str:
    """The object key in the media bucket: ``media/<path>``, the rule ``renditions.media_key_for_source`` states for story pictures.

    Written out here so the router and content-actions packages, which import this module, do not pull in the image pipeline. The path is checked
    against ``SOURCE_PATH`` first, so it can hold no ``..``.
    """
    if not SOURCE_PATH.match(path):
        raise ValueError(f"not a thumbnail path: {path!r}")
    return "media/" + path


def stored_request(reference: Mapping[str, Any], thumbnail: Thumbnail) -> dict[str, Any]:
    return {"state": "stored", "path": source_path(reference, thumbnail), "sha256": thumbnail.sha256, "width": thumbnail.width, "height": thumbnail.height,
            "mediaType": thumbnail.media_type, "platform": thumbnail.platform, "sourceUrl": thumbnail.source_url}


def none_request(reason: str) -> dict[str, Any]:
    return {"state": "none", "reason": reason[:200]}


def _preview_is_editors(client: Any, reference: Mapping[str, Any]) -> bool:
    from .reference_images import preview_attachment_id

    row = client.get_record("ReferenceAttachment", preview_attachment_id(dict(reference)))
    metadata = (row or {}).get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = {}
    return isinstance(metadata, Mapping) and metadata.get("via") == EDITOR_IMAGE


def record_thumbnail(client: Any, reference: dict[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    """Store the result of a thumbnail fetch on the Reference (the content-actions function calls this for ``correctReferenceCapture``).

    ``request`` is ``{"state": "stored", "path", "sha256", ...}`` or ``{"state": "none", "reason"}``. Only a video can have one, an image an editor
    set is never replaced, and an unchanged value writes nothing. Raises ``Refused`` with a plain reason.
    """
    if classify_address(reference.get("sourceUri")).medium != MEDIUM_VIDEO:
        raise Refused("A thumbnail can only be recorded on a video.")
    if _preview_is_editors(client, reference):
        raise Refused("An editor set this Reference's image; it is not replaced.")
    state = request.get("state")
    if state == "stored":
        path = str(request.get("path") or "")
        if not SOURCE_PATH.match(path):
            raise Refused(f"The thumbnail path must be under {DIRECTORY}/ and named for its hash.")
        if not re.match(r"^[0-9a-f]{64}$", str(request.get("sha256") or "")):
            raise Refused("The thumbnail needs its sha256.")
        value = path
    elif state == "none":
        value = NO_THUMBNAIL
    else:
        raise Refused("A thumbnail request is either stored or none.")
    if reference.get(FIELD) == value:
        return {"referenceId": reference["id"], "thumbnailPath": value, "changed": False}
    client.update_record("Reference", {"id": reference["id"], FIELD: value})
    reference[FIELD] = value
    return {"referenceId": reference["id"], "thumbnailPath": value, "changed": True}


def public_image(row: Mapping[str, Any]) -> str | None:
    """The site-relative address a public page shows for a video: the copy in our storage (``/assets/reference-thumbnails/...``), else nothing.

    A video never falls back to a platform's address; ``none`` and an unset field both mean no image yet.
    """
    path = row.get(FIELD)
    return f"/{path}" if isinstance(path, str) and SOURCE_PATH.match(path) else None
