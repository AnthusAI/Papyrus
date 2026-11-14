"""What a Story's share picture really is: fetch the planned og:image address and read its status, type and size (check C4 and C12).

A share card names a picture by address. Building that address proves nothing about the file, so this module looks at the file itself:
the response status, the Content-Type, the format found in the bytes, and the pixel size and shape. It states what it saw directly. It does not
claim to know what LinkedIn, Facebook, X or any other crawler will do: JPEG and PNG are the formats the platforms document for share pictures,
so those pass; WebP and AVIF are flagged as a compatibility risk (not as proof of failure); anything it could not look at is *not verified*.

The network is a parameter (``fetch``), so tests give a fake and nothing here is fetched unless a caller passes ``fetch_over_http``.
"""

from __future__ import annotations

import struct
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

#: Formats documented for share pictures on the major platforms. Other formats are a compatibility risk.
SAFE_FORMATS = ("jpeg", "png")
RISKY_FORMATS = ("webp", "avif", "gif")
#: A picture narrower than this is flagged as small (a common recommended minimum for a large card; not a universal platform rule).
MIN_WIDTH, MIN_HEIGHT = 600, 315
#: The usual card shape is about 1.91:1. A picture much taller or wider than this is likely to be cropped.
RATIO_RANGE = (1.4, 2.4)
MAX_BYTES = 2_000_000
TIMEOUT_SECONDS = 10
MIME_BY_FORMAT = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "avif": "image/avif", "gif": "image/gif"}


class ShareImageUnavailable(Exception):
    """The picture could not be requested at all (no network, DNS failure, timeout)."""


@dataclass(frozen=True)
class Fetched:
    status: int
    content_type: str
    body: bytes


Fetch = Callable[[str], Fetched]


def fetch_over_http(url: str) -> Fetched:
    """GET the picture (at most ``MAX_BYTES``) and return its status, Content-Type and bytes. Raises ``ShareImageUnavailable`` when it cannot ask."""
    request = urllib.request.Request(url, headers={"User-Agent": "Papyrus-share-image-check/1", "Accept": "image/jpeg,image/png,image/*;q=0.8"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:   # noqa: S310 - https only, checked by the caller
            return Fetched(response.status, response.headers.get("Content-Type", ""), response.read(MAX_BYTES))
    except urllib.error.HTTPError as error:
        return Fetched(error.code, error.headers.get("Content-Type", "") if error.headers else "", b"")
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise ShareImageUnavailable(str(getattr(error, "reason", error))) from error


def sniff_format(body: bytes) -> str | None:
    if body[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if body[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "webp"
    if body[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if body[4:8] == b"ftyp" and body[8:12] in (b"avif", b"avis"):
        return "avif"
    return None


def dimensions(body: bytes, image_format: str | None) -> tuple[int, int] | None:
    """Pixel width and height read from the file's own header, or None when the bytes do not give them."""
    try:
        if image_format == "png":
            return struct.unpack(">II", body[16:24])
        if image_format == "gif":
            return struct.unpack("<HH", body[6:10])
        if image_format == "jpeg":
            return _jpeg_size(body)
        if image_format == "webp":
            return _webp_size(body)
        if image_format == "avif":
            at = body.find(b"ispe")
            return struct.unpack(">II", body[at + 8:at + 16]) if at > 0 else None
    except (struct.error, IndexError):
        return None
    return None


def _jpeg_size(body: bytes) -> tuple[int, int] | None:
    at = 2
    while at + 9 < len(body):
        if body[at] != 0xFF:
            at += 1
            continue
        marker = body[at + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            at += 1 if marker == 0xFF else 2
            continue
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", body[at + 5:at + 9])
            return width, height
        at += 2 + struct.unpack(">H", body[at + 2:at + 4])[0]
    return None


def _webp_size(body: bytes) -> tuple[int, int] | None:
    kind = body[12:16]
    if kind == b"VP8 ":
        width, height = struct.unpack("<HH", body[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if kind == b"VP8L":
        bits = struct.unpack("<I", body[21:25])[0]
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if kind == b"VP8X":
        return int.from_bytes(body[24:27], "little") + 1, int.from_bytes(body[27:30], "little") + 1
    return None


@dataclass(frozen=True)
class Verdict:
    """``result`` is ``ok``, ``warning`` or ``not_verified``; ``tested`` is the line to paste into the social checklist note."""

    result: str
    message: str
    evidence: dict

    @property
    def tested(self) -> str:
        return self.evidence["note"]


def _note(url: str | None, *, status: int | None = None, content_type: str | None = None, image_format: str | None = None,
          size: tuple[int, int] | None = None, result: str, why: str) -> dict:
    ratio = round(size[0] / size[1], 2) if size and size[1] else None
    shown = f"{size[0]}x{size[1]}" if size else "size unknown"
    note = f"Share picture {url or '(none)'}: status {status if status is not None else 'not fetched'}, type {content_type or 'unknown'}, format {image_format or 'unknown'}, {shown}, result {result} ({why})."
    return {"url": url, "status": status, "contentType": content_type, "format": image_format, "width": size[0] if size else None,
            "height": size[1] if size else None, "ratio": ratio, "result": result, "note": note}


def assess_share_image(url: str | None, fetch: Fetch | None) -> Verdict:
    """Look at the planned share picture ``url`` through ``fetch`` and say what is known. A missing ``fetch`` is *not verified*, never a pass."""
    if not url:
        why = "The Story has no share picture and the site has no default one, so a share card will have no picture. Add an image to the front matter."
        return Verdict("warning", why, _note(None, result="warning", why="no picture"))
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        why = f"The share picture address {url} is not an absolute HTTPS address, so crawlers may not fetch it. Use a full https:// address."
        return Verdict("warning", why, _note(url, result="warning", why="not an absolute HTTPS address"))
    if fetch is None:
        why = f"The share picture {url} was not fetched here, so its file, type and size are not verified. A built address does not prove the file exists."
        return Verdict("not_verified", why, _note(url, result="not_verified", why="not fetched"))
    try:
        got = fetch(url)
    except ShareImageUnavailable as error:
        why = f"The share picture {url} could not be requested ({error}), so it is not verified. Check it from a machine with network access."
        return Verdict("not_verified", why, _note(url, result="not_verified", why=f"unreachable: {error}"))
    content_type = got.content_type.split(";")[0].strip().lower()
    if got.status != 200:
        why = f"The share picture {url} answered with status {got.status}, so a crawler will not get a picture."
        return Verdict("warning", why, _note(url, status=got.status, content_type=content_type, result="warning", why=f"status {got.status}"))
    found = sniff_format(got.body)
    if not content_type.startswith("image/") and found is None:
        why = f"The share picture {url} answered with {content_type or 'no Content-Type'}, which is not an image."
        return Verdict("warning", why, _note(url, status=200, content_type=content_type, result="warning", why="not an image type"))
    size = dimensions(got.body, found)
    base = dict(status=200, content_type=content_type, image_format=found, size=size)
    declared = {mime: name for name, mime in MIME_BY_FORMAT.items()}.get(content_type.replace("image/jpg", "image/jpeg"))
    if found is None:
        why = f"The share picture {url} says it is {content_type} but the file is not a format Papyrus could read, so it is not verified."
        return Verdict("not_verified", why, _note(url, **base, result="not_verified", why="format not recognised"))
    if declared and declared != found:
        why = f"The share picture {url} is sent as {content_type} but the file is {found}. Crawlers may reject a picture whose type does not match."
        return Verdict("warning", why, _note(url, **base, result="warning", why="Content-Type does not match the file"))
    if found not in SAFE_FORMATS:
        why = (f"The share picture {url} is {found.upper()}. JPEG and PNG are the formats platforms document for share pictures, so {found.upper()} may not show a preview "
               "on every platform (a compatibility risk, not proof of failure). Make a JPEG or PNG share rendition and keep the modern format for the page.")
        return Verdict("warning", why, _note(url, **base, result="warning", why=f"{found} is not JPEG or PNG"))
    if size is None:
        why = f"The share picture {url} is {found.upper()} but its size could not be read, so it is not verified."
        return Verdict("not_verified", why, _note(url, **base, result="not_verified", why="size unreadable"))
    width, height = size
    ratio = width / height if height else 0
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        why = (f"The share picture {url} is {width}x{height}, smaller than the {MIN_WIDTH}x{MIN_HEIGHT} that gives a large card. Use a bigger original; do not upscale or pad "
               "it without recording that.")
        return Verdict("warning", why, _note(url, **base, result="warning", why="small"))
    if not RATIO_RANGE[0] <= ratio <= RATIO_RANGE[1]:
        why = f"The share picture {url} is {width}x{height} (ratio {ratio:.2f}); cards usually crop to about 1.91:1, so it may be cut."
        return Verdict("warning", why, _note(url, **base, result="warning", why="ratio far from 1.91:1"))
    why = f"The share picture {url} is a {found.upper()}, {width}x{height} (ratio {ratio:.2f}), served as {content_type} with status 200. Whether a given platform shows it is not checked here."
    return Verdict("ok", why, _note(url, **base, result="ok", why="JPEG/PNG, large enough"))
