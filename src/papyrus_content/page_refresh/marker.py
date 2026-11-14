"""The source-version marker: which version of a Story a stored page was rendered from.

An item page (and its Markdown twin) ends with ``<!-- papyrus-source-version: N -->``. The S3 object metadata carries the same number
(``papyrus-version``), but metadata does not travel to the edge; the marker is what lets ``site inspect`` and ``publish --verify`` read, from
the public URL, which version the edge is serving.
"""

from __future__ import annotations

import re

MARKER_PATTERN = re.compile(rb"<!-- papyrus-source-version: (\d+) -->\s*\Z")
MARKED_SUFFIXES = (".html", ".md")


def with_source_version(key: str, body: bytes, version: int | None) -> bytes:
    if version is None or not key.endswith(MARKED_SUFFIXES):
        return body
    return MARKER_PATTERN.sub(b"", body).rstrip(b"\n") + b"\n<!-- papyrus-source-version: " + str(int(version)).encode() + b" -->\n"


def source_version_of(body: bytes | str | None) -> int | None:
    if body is None:
        return None
    raw = body.encode("utf-8") if isinstance(body, str) else body
    match = MARKER_PATTERN.search(raw[-200:])
    return int(match.group(1)) if match else None
