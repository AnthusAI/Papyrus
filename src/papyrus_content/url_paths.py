"""Object keys and URL paths: one encoding for every address Papyrus writes (docs/multilingual-serving.md, "Unicode addresses")."""

from __future__ import annotations

import unicodedata
from urllib.parse import quote, unquote


#: What stays literal when a key becomes a URL path: RFC 3986 ``pchar`` minus ``%`` (unreserved, sub-delims, ``:`` and ``@``) and ``/``. Every other
#: character, a Chinese slug's above all, is percent-encoded as UTF-8 with upper-case hex, which is how browsers send it and how CloudFront hands the
#: path to the edge function and to S3.
URL_PATH_SAFE = "/!$&'()*+,;=:@-._~"


def encoded_path(path: str) -> str:
    """A site path (or object key) as a URL path: Unicode NFC, then percent-encoded. A key of slugs in ASCII is unchanged.

    This is the one place a path is encoded. Object keys (S3, the local build) are NFC text; every URL Papyrus writes (links, canonical, hreflang,
    sitemap, redirects, invalidation) is this encoded form of that key, so the two always name the same page."""
    return quote(unicodedata.normalize("NFC", path), safe=URL_PATH_SAFE)


def decoded_path(path: str) -> str:
    """The NFC text of an encoded URL path: what its object key is built from."""
    return unicodedata.normalize("NFC", unquote(path))
