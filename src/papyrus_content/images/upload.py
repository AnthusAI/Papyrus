"""Uploading an example picture from the command line: the same three steps the newsroom takes (design section 5.8).

Ask for a signed upload address, ``PUT`` the file to it, then complete the upload (the backend checks the size, type and hash). The file is stored once, under
the newsroom's private prefix, named by its own SHA-256, so the same picture uploaded twice is one row and one file. Nothing here is public.
"""
from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path
from typing import Callable

from papyrus_content.newsroom_doctrine import VISUAL_STYLE_DEFINITION

from .examples import MAX_EXAMPLE_BYTES, ROLE_BY_KIND

EXTENSION_BY_TYPE = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


class PictureError(Exception):
    """The file cannot be an example picture. The message says why in plain words."""


def media_type_of(data: bytes) -> str | None:
    """The picture's type from its first bytes, not its file name."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def describe_picture(path: str, kind: str) -> tuple[dict, bytes]:
    """The attachment record for this file, and its bytes. Raises PictureError for a file that cannot be used."""
    try:
        data = Path(path).read_bytes()
    except OSError as error:
        raise PictureError(f"Could not read {path}: {error.strerror or error}.") from error
    if len(data) > MAX_EXAMPLE_BYTES:
        raise PictureError(f"{path} is {len(data) / (1024 * 1024):.1f} MB. Example pictures must be 10 MB or smaller.")
    media_type = media_type_of(data)
    if media_type is None:
        raise PictureError(f"{path} is not a PNG, JPEG or WebP picture. Those are the only types example pictures can be.")
    digest = hashlib.sha256(data).hexdigest()
    attachment = {"ownerKind": "item", "ownerId": VISUAL_STYLE_DEFINITION["lineageId"], "role": ROLE_BY_KIND[kind], "sortKey": digest,
                  "filename": f"{digest}.{EXTENSION_BY_TYPE[media_type]}", "mediaType": media_type, "byteSize": len(data), "sha256": digest}
    return attachment, data


def put_bytes(url: str, data: bytes, headers: dict) -> None:
    request = urllib.request.Request(url, data=data, method="PUT", headers=headers)
    with urllib.request.urlopen(request, timeout=120):   # noqa: S310 (a signed https address the backend just gave us)
        pass


def upload_picture(client, path: str, kind: str, *, put: Callable[[str, bytes, dict], None] = put_bytes) -> str:
    """Upload one picture for the profile and return its attachment id. Raises PictureError for a file that cannot be used."""
    attachment, data = describe_picture(path, kind)
    slot = client.create_model_attachment_upload(attachment)
    put(slot["uploadUrl"], data, dict(slot.get("requiredHeaders") or {"content-type": attachment["mediaType"]}))
    done = client.complete_model_attachment_upload(slot["uploadId"], attachment)
    return str(done.get("id") or slot["attachmentId"])
