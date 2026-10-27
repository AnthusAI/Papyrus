"""Content fingerprint that groups repeated copies of the same email submission.

The same newsletter is often forwarded more than once. Each forward is a separate SES
delivery with its own message id, so each gets its own receipt. The fingerprint is what
makes those receipts recognisable as one submission. It must survive what forwarding
changes (``Fwd:``/``Re:`` prefixes, forward header blocks, quoting, whitespace, link
tracking parameters) and must still separate different emails.

Definition (version 1), the SHA-256 of a canonical JSON document:

* ``subject``: lower-cased Unicode NFKC, every leading ``Re:``/``Fwd:``/``Fw:`` removed,
  whitespace collapsed.
* ``links``: the sorted set of distinct candidate-link URLs the intake extracted. These are
  already canonical (tracking parameters and fragments removed), so they do not depend on
  forward headers or body wrapping.
* ``body``: only when the message has no extracted links, so link-free messages with the same
  subject are not merged. It is the lower-cased, whitespace-collapsed plain text with quote
  markers and forward header lines (``From:``, ``To:``, ``Cc:``, ``Date:``, ``Sent:``,
  ``Subject:``, ``Forwarded message`` separators) removed.

The body is deliberately left out when links exist: forwards add headers and comments around
the same newsletter, and the link set identifies the content.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re
import unicodedata

VERSION = 1
GROUP_PREFIX = "EMAILGROUP#"
MEMBER_PREFIX = "EMAILFP#"
FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")
_SUBJECT_PREFIX = re.compile(r"^\s*(?:re|fwd?)\s*:\s*", re.IGNORECASE)
_FORWARD_LINE = re.compile(
    r"^\s*(?:from|to|cc|bcc|date|sent|subject|reply-to)\s*:.*$|^\s*-{2,}.*forwarded message.*$|^\s*begin forwarded message.*$",
    re.IGNORECASE)


def normalize_subject(subject) -> str:
    text = unicodedata.normalize("NFKC", subject if isinstance(subject, str) else "").lower()
    while True:
        stripped = _SUBJECT_PREFIX.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped
    return " ".join(text.split())


def normalize_body(body) -> str:
    lines = []
    for line in (body if isinstance(body, str) else "").splitlines():
        line = line.lstrip("> \t")
        if line and not _FORWARD_LINE.match(line):
            lines.append(line)
    return " ".join(unicodedata.normalize("NFKC", " ".join(lines)).lower().split())


def content_fingerprint(subject, links, body="") -> str:
    urls = sorted({link["url"].strip() for link in links or [] if isinstance(link, dict)
                   and isinstance(link.get("url"), str) and link["url"].strip()})
    document = {"v": VERSION, "subject": normalize_subject(subject), "links": urls}
    if not urls:
        document["body"] = normalize_body(body)
    return sha256(json.dumps(document, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def group_key(fingerprint: str) -> str:
    return GROUP_PREFIX + fingerprint


def member_key(fingerprint: str, receipt_id: str) -> str:
    return f"{MEMBER_PREFIX}{fingerprint}#{receipt_id.removeprefix('EMAIL#')}"
