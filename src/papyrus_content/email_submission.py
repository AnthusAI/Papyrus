"""Bounded, offline extraction of reference candidates from untrusted MIME email.

This module supplies no authentication or authorization: From/To and all other
message headers are untrusted provenance. The SES intake verifies trusted receipt
verdicts, sender and envelope destinations before using this result. No URL is
fetched, no HTML is rendered, and body text is never an agent instruction.
"""
from __future__ import annotations

import ipaddress
import re
from email import policy
from email.parser import BytesParser
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

MAX_MESSAGE_BYTES = 1_048_576
MAX_MIME_PARTS = 64
MAX_MIME_DEPTH = 12
MAX_LINKS = 25
MAX_URL_LENGTH = 2048
MAX_TITLE_LENGTH = 256
MAX_CANDIDATES = 1000
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_CONTROL = re.compile(r"[\x00-\x20\x7f]")
_ACTION = re.compile(
    r"(?:^|[/._-])(?:unsubscrib\w*|subscrib\w*|preferences?|manage[-_]?subscriptions?|"
    r"log[-_]?in|sign[-_]?in|logout|confirm\w*|verif\w*|activate|reset\w*|"
    r"auth|oauth\w*|redirect\w*|click\w*|track\w*|pixel|open)(?:$|[/._-])", re.I)
_ACTION_LABEL = re.compile(
    r"\b(?:unsubscribe|subscribe|preferences|log\s*in|sign\s*in|reset\s+(?:your\s+)?password|"
    r"confirm\s+(?:your\s+)?(?:email|subscription|account)|verify\s+(?:your\s+)?(?:email|account))\b", re.I)
_TRACKING_KEYS = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid"}
_SECRET_KEY = re.compile(
    r"(?:token|secret|password|passwd|signature|credential|session|auth|nonce|api[-_]?key|"
    r"unsubscribe|redirect|return[-_]?url|destination|email|subscriber|recipient)", re.I)
_OPAQUE = re.compile(r"^[A-Za-z0-9_-]{32,}$")
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_IGNORED_HTML = {"script", "style", "head", "template", "noscript"}


class SubmissionRejected(ValueError):
    """A stable safe reason, without message content or secrets, for a held email."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _text(value, maximum=MAX_TITLE_LENGTH):
    return " ".join(str(value or "").split())[:maximum]


def _link_title(value: str, fallback: str) -> str:
    # Titles reach a classifier. Original headers and MIME remain private; do not
    # copy embedded secret URLs, addresses or common credential spellings across.
    value = _URL.sub(" ", value)
    value = re.sub(r"[\w.+-]+@[\w.-]+", " ", value)
    value = re.sub(r"\b(?:token|secret|password|signature|session|api[-_]?key)\s*[:=]\s*\S+", " ", value, flags=re.I)
    value = re.sub(r"\b[A-Za-z0-9_-]{32,}(?:\.[A-Za-z0-9_-]+)*\b", " ", value)
    return _text(value) or _text(fallback)


def safe_editorial_url(raw: str) -> str | None:
    """Conservatively exclude obvious actions/secrets; never resolve redirect links.

    DNS is deliberately not consulted here. Any later accession fetch must enforce
    its own DNS, redirect, byte and time bounds; a public-looking name is not proof
    that its resolved address is public.
    """
    if not isinstance(raw, str) or len(raw) > MAX_URL_LENGTH:
        return None
    raw = unescape(raw).strip()
    if not raw or _CONTROL.search(raw) or "\\" in raw:
        return None
    decoded = raw
    for _ in range(3):
        decoded = unquote(decoded)
    if _CONTROL.search(decoded) or "\\" in decoded:
        return None
    try:
        parts = urlsplit(raw)
        if parts.scheme.lower() not in {"http", "https"} or parts.username or parts.password:
            return None
        host = (parts.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        labels = host.split(".")
        if (len(labels) < 2 or len(host) > 253 or any(not _HOST_LABEL.fullmatch(label) for label in labels)
                or not re.fullmatch(r"[a-z][a-z0-9-]*", labels[-1])
                or labels[-1] in {"local", "localhost", "internal", "test", "invalid", "onion"}
                or any(label in {"click", "clicks", "track", "tracking", "pixel"} for label in labels[:-1])):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        if parts.port not in {None, 80 if parts.scheme.lower() == "http" else 443}:
            return None
        decoded_path = parts.path
        for _ in range(3):
            decoded_path = unquote(decoded_path)
        opaque_path = any(re.fullmatch(r"[A-Za-z0-9_]{32,}", segment)
                          and ((re.search(r"[a-z]", segment) and re.search(r"[A-Z]", segment)
                                and re.search(r"[0-9]", segment)) or re.fullmatch(r"[a-fA-F0-9]{32,}", segment))
                          for segment in decoded_path.split("/"))
        if _ACTION.search(decoded_path) or opaque_path or re.search(r"%[0-9a-fA-F]{2}", decoded_path):
            return None
        kept = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True, max_num_fields=64):
            inspected_key, inspected_value = key, value
            for _ in range(3):
                inspected_key, inspected_value = unquote(inspected_key), unquote(inspected_value)
            lowered = inspected_key.lower()
            if lowered.startswith("utm_") or lowered in _TRACKING_KEYS:
                continue
            if (_SECRET_KEY.search(inspected_key) or lowered in {"key", "code", "url", "u"}
                    or _ACTION.search(inspected_value)
                    or _OPAQUE.fullmatch(inspected_value) or "@" in inspected_value
                    or "http://" in inspected_value.lower() or "https://" in inspected_value.lower()
                    or re.search(r"%[0-9a-fA-F]{2}", inspected_key + inspected_value)
                    or inspected_value.count(".") == 2 and inspected_value.startswith("eyJ")):
                return None
            kept.append((key, value))
        return urlunsplit((parts.scheme.lower(), host, parts.path or "/", urlencode(sorted(kept)), ""))
    except (ValueError, UnicodeError):
        return None


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.ignored = []
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        if tag in _IGNORED_HTML:
            self.ignored.append(tag)
        if self.ignored:
            return
        if tag == "a":
            self._finish_anchor()
            values = dict(attrs)
            self.anchor = [values.get("href") or "", []]

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if tag == "a":
            self._finish_anchor()

    def handle_data(self, data):
        if self.anchor is not None and not self.ignored:
            self.anchor[1].append(data)

    def _finish_anchor(self):
        if self.anchor is not None:
            self.links.append((self.anchor[0], _text("".join(self.anchor[1]), MAX_MESSAGE_BYTES)))
            self.anchor = None
            if len(self.links) > MAX_CANDIDATES:
                raise SubmissionRejected("too_many_candidates")

    def close(self):
        super().close()
        self._finish_anchor()


def _addresses(message, name, *, single=False):
    headers = message.get_all(name, [])
    try:
        if single and len(headers) != 1:
            raise ValueError("one sender required")
        values = []
        for header in headers:
            if header.defects:
                raise ValueError("defective address")
            for address in header.addresses:
                value = address.addr_spec.lower()
                if (not address.username or not address.domain or not value.isascii()
                        or _CONTROL.search(value) or any(char in value for char in '<>"')):
                    raise ValueError("invalid address")
                values.append(value)
        if single and len(values) != 1:
            raise ValueError("one sender required")
        if len(values) > 50:
            raise ValueError("too many addresses")
        return values
    except (AttributeError, ValueError, TypeError):
        raise SubmissionRejected("invalid_sender" if single else "invalid_recipients") from None


def extract_submission(raw: bytes) -> dict:
    """Extract at most 25 safe unique links and private, explicitly untrusted headers.

    Ordinary attachments are ignored; bounded attached message/rfc822 bodies are
    inspected only for links and never used to authenticate the sender. Multi-part bodies
    contribute both HTML and plain text links. This first slice forwards no message
    prose or original unsafe URL into a classifier; retain the original privately
    in the intake's restricted object storage for inspection.
    """
    if not isinstance(raw, bytes) or not raw:
        raise SubmissionRejected("invalid_message")
    if len(raw) > MAX_MESSAGE_BYTES:
        raise SubmissionRejected("message_too_large")
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw)
    except (ValueError, RecursionError):
        raise SubmissionRejected("malformed_mime") from None
    if (any(str(value).strip().lower() != "no" for value in message.get_all("Auto-Submitted", []))
            or message.get("X-Papyrus-Submission") is not None
            or str(message.get("Return-Path") or "").strip() == "<>"
            or message.get_content_type() in {"multipart/report", "message/delivery-status", "message/disposition-notification"}):
        raise SubmissionRejected("automated_message")
    sender = _addresses(message, "From", single=True)[0]
    recipients = sorted(set(_addresses(message, "To") + _addresses(message, "Cc")))
    candidates, warnings = [], set()
    pending, count = [(message, 0, False)], 0
    while pending:
        part, depth, ignored_parent = pending.pop()
        count += 1
        if count > MAX_MIME_PARTS:
            raise SubmissionRejected("too_many_mime_parts")
        if depth > MAX_MIME_DEPTH:
            raise SubmissionRejected("mime_too_deep")
        if part.defects:
            raise SubmissionRejected("malformed_mime")
        forwarded_message = part.get_content_type() == "message/rfc822"
        ignored = ignored_parent or (not forwarded_message and
                                     (part.get_content_disposition() == "attachment" or part.get_filename() is not None))
        if ignored:
            warnings.add("ignored_attachments")
        if part.is_multipart():
            children = list(part.iter_parts())
            pending.extend((child, depth + 1, ignored or (part.get_content_maintype() == "message" and not forwarded_message))
                           for child in reversed(children))
            continue
        if ignored or part.get_content_type() not in {"text/plain", "text/html"}:
            continue
        if str(part.get("Content-Transfer-Encoding") or "7bit").lower() not in {"7bit", "8bit", "binary", "base64", "quoted-printable"}:
            raise SubmissionRejected("invalid_encoding")
        try:
            body = part.get_payload(decode=True).decode(part.get_content_charset() or "ascii", errors="strict")
        except (UnicodeError, LookupError, AttributeError, ValueError):
            raise SubmissionRejected("invalid_encoding") from None
        if part.defects:
            raise SubmissionRejected("invalid_encoding")
        if part.get_content_type() == "text/html":
            parser = _Links()
            parser.feed(body)
            parser.close()
            candidates.extend(parser.links)
        else:
            for line in body.splitlines():
                for match in _URL.finditer(line):
                    url = match.group(0).rstrip(".,;:!?\u201d\u2019]")
                    while url.endswith(")") and url.count(")") > url.count("("):
                        url = url[:-1]
                    label = "Account action" if _ACTION_LABEL.search(line) else ""
                    candidates.append((url, label))
                    if len(candidates) > MAX_CANDIDATES:
                        raise SubmissionRejected("too_many_candidates")
        if len(candidates) > MAX_CANDIDATES:
            raise SubmissionRejected("too_many_candidates")
    links, excluded = {}, set()
    for raw_url, title in candidates:
        url = safe_editorial_url(raw_url)
        if url is None:
            warnings.add("excluded_links")
            continue
        if title == "Account action" or _ACTION_LABEL.search(title):
            excluded.add(url)
            warnings.add("excluded_links")
            continue
        if url not in links or title:
            links[url] = {"url": url, "title": _link_title(title, url)}
    result_links = [item for url, item in links.items() if url not in excluded]
    if len(result_links) > MAX_LINKS:
        raise SubmissionRejected("too_many_links")
    return {"sender": sender, "recipients": recipients, "subject": _text(message.get("Subject")),
            "messageId": _text(message.get("Message-ID")), "date": _text(message.get("Date"), 128),
            "links": result_links, "warnings": sorted(warnings)}
