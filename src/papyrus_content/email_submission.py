"""Bounded extraction of reference candidates from untrusted MIME email.

This module supplies no authentication or authorization: From/To and all other
message headers are untrusted provenance. The SES intake validates its event source,
scan verdicts and exact envelope destination; SPF/DKIM/DMARC remain signals only.
No URL is fetched by default; the optional redirect helper requires explicit
injection. The body view is inert text and never an instruction.
"""
from __future__ import annotations

import ipaddress
import re
import time
from email import policy
from email.parser import BytesParser
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

MAX_MESSAGE_BYTES = 1_048_576
MAX_MIME_PARTS = 64
MAX_MIME_DEPTH = 12
LINK_BATCH_SIZE = 25  # work-unit size only; never an editorial/content ceiling
MAX_URL_LENGTH = 2048
MAX_TITLE_LENGTH = 256
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
_BLOCK_HTML = {"address", "article", "blockquote", "br", "div", "dl", "fieldset", "figcaption", "figure",
               "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main",
               "ol", "p", "pre", "section", "table", "tr", "ul"}
MAX_REDIRECTS = 5
REDIRECT_HOP_TIMEOUT_SECONDS = 2.0
REDIRECT_TOTAL_TIMEOUT_SECONDS = 8.0
MAX_REDIRECT_LOCATION_LENGTH = 2048
_REDIRECT_STATUS = {301, 302, 303, 307, 308}


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
        if parts.path.startswith("/ss/c/"):
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


class RedirectResolutionError(ValueError):
    """A stable, URL-free failure code for the optional redirect resolver."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def is_supported_email_tracking_url(raw: str) -> bool:
    """Recognize HTTPS Beehiiv or branded SendGrid wrappers without fetching them."""
    if not isinstance(raw, str) or len(raw) > MAX_URL_LENGTH or _CONTROL.search(raw) or "\\" in raw:
        return False
    try:
        parts = urlsplit(unescape(raw.strip()))
        host = (parts.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        if (parts.scheme.lower() != "https" or safe_editorial_url("https://" + host + "/") is None
                or not (host == "link.mail.beehiiv.com" or re.fullmatch(r"/ss/c/u001\.[A-Za-z0-9_.-]+", parts.path))
                or parts.username or parts.password or parts.port not in {None, 443}
                or not parts.path.startswith("/ss/c/")):
            return False
        if _ACTION.search(unquote(parts.path)) or _ACTION_LABEL.search(unquote(parts.path)):
            return False
        for key, value in parse_qsl(parts.query, keep_blank_values=True, max_num_fields=64):
            action_key = unquote(key).lower()
            action_value = unquote(value).lower()
            if action_key in {"action", "command", "mode", "operation"} and _ACTION.search(action_value):
                return False
            if action_key in {"unsubscribe", "preferences", "login", "logout", "confirm", "activate"}:
                return False
        return True
    except (ValueError, UnicodeError):
        return False


def is_supported_beehiiv_tracking_url(raw: str) -> bool:
    """Compatibility predicate restricted to the original Beehiiv host."""
    return is_supported_email_tracking_url(raw) and urlsplit(raw).hostname == "link.mail.beehiiv.com"


def _public_dns_addresses(host: str, resolve_host, timeout: float) -> tuple[str, ...]:
    try:
        values = resolve_host(host, timeout=timeout)
    except Exception:
        raise RedirectResolutionError("redirect_dns_failed") from None
    if not isinstance(values, (list, tuple, set)) or not values or len(values) > 16:
        raise RedirectResolutionError("redirect_dns_result_invalid")
    addresses = set()
    for value in values:
        try:
            address = ipaddress.ip_address(value)
        except (ValueError, TypeError):
            raise RedirectResolutionError("redirect_dns_result_invalid") from None
        if not address.is_global:
            raise RedirectResolutionError("redirect_address_not_public")
        addresses.add(str(address))
    if not addresses:
        raise RedirectResolutionError("redirect_dns_result_invalid")
    return tuple(sorted(addresses))


def _response_header(headers, name: str):
    if not hasattr(headers, "items"):
        return None
    return next((value for key, value in headers.items()
                 if isinstance(key, str) and key.lower() == name.lower()), None)


def resolve_email_tracking_url(raw: str, *, resolve_host, request, clock=None) -> str:
    """Resolve one supported wrapper using an explicitly supplied, pinned transport.

    This function has no default DNS resolver or HTTP client and is not used by the
    production email intake. A caller must explicitly provide both. The request
    DNS and request adapters must honor their supplied timeouts. The request
    adapter must connect only to the supplied public IPs, preserve HTTPS hostname
    verification/SNI, avoid ambient proxies/cookies, disable redirects, use HEAD,
    and read no response body. Every hop is re-resolved and validated before use.
    """
    if not is_supported_email_tracking_url(raw):
        raise RedirectResolutionError("redirect_source_not_supported")
    clock = clock or time.monotonic
    started = clock()
    parts = urlsplit(unescape(raw.strip()))
    current = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
    visited = set()
    redirects = 0
    while True:
        if current in visited:
            raise RedirectResolutionError("redirect_loop")
        visited.add(current)
        parts = urlsplit(current)
        host = (parts.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        remaining = REDIRECT_TOTAL_TIMEOUT_SECONDS - (clock() - started)
        if remaining <= 0:
            raise RedirectResolutionError("redirect_timeout")
        addresses = _public_dns_addresses(
            host, resolve_host, min(REDIRECT_HOP_TIMEOUT_SECONDS, remaining))
        remaining = REDIRECT_TOTAL_TIMEOUT_SECONDS - (clock() - started)
        if remaining <= 0:
            raise RedirectResolutionError("redirect_timeout")
        try:
            response = request(current, connect_addresses=addresses, method="HEAD", allow_redirects=False,
                               read_body=False, trust_env=False,
                               timeout=min(REDIRECT_HOP_TIMEOUT_SECONDS, remaining))
        except Exception:
            raise RedirectResolutionError("redirect_request_failed") from None
        if clock() - started > REDIRECT_TOTAL_TIMEOUT_SECONDS:
            raise RedirectResolutionError("redirect_timeout")
        if isinstance(response, dict):
            status, headers = response.get("status"), response.get("headers")
        else:
            status, headers = getattr(response, "status", None), getattr(response, "headers", None)
        if status in _REDIRECT_STATUS:
            if redirects >= MAX_REDIRECTS:
                raise RedirectResolutionError("redirect_limit_exceeded")
            location = _response_header(headers, "location")
            if (not isinstance(location, str) or not location or len(location) > MAX_REDIRECT_LOCATION_LENGTH
                    or _CONTROL.search(location) or "\\" in location):
                raise RedirectResolutionError("redirect_location_invalid")
            target = urljoin(current, location)
            normalized = safe_editorial_url(target)
            if normalized is None:
                raise RedirectResolutionError("redirect_target_unsafe")
            if urlsplit(normalized).scheme != "https":
                raise RedirectResolutionError("redirect_scheme_downgrade")
            current = normalized
            redirects += 1
            continue
        if status not in {200, 204}:
            raise RedirectResolutionError("redirect_response_unusable")
        final_url = safe_editorial_url(current)
        if final_url is None:
            raise RedirectResolutionError("redirect_target_unsafe")
        if redirects == 0:
            raise RedirectResolutionError("redirect_destination_missing")
        return final_url


def resolve_beehiiv_tracking_url(raw: str, *, resolve_host, request, clock=None) -> str:
    """Compatibility entry point restricted to the original supported provider."""
    if not is_supported_beehiiv_tracking_url(raw):
        raise RedirectResolutionError("redirect_source_not_supported")
    return resolve_email_tracking_url(raw, resolve_host=resolve_host, request=request, clock=clock)


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

    def close(self):
        super().close()
        self._finish_anchor()


class _SafeText(HTMLParser):
    """Convert HTML to inert readable text; never preserve markup or remote content."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored = []

    def handle_starttag(self, tag, attrs):
        if tag in _IGNORED_HTML:
            self.ignored.append(tag)
        elif not self.ignored and tag in _BLOCK_HTML:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
        elif tag in _BLOCK_HTML:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


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


def extract_submission(raw: bytes, *, tracking_resolver=None) -> dict:
    """Extract every safe unique link and an inert readable body within the MIME bound.

    Ordinary attachments are ignored; bounded attached message/rfc822 bodies are
    inspected only for links and never used to authenticate the sender. Multi-part bodies
    contribute both HTML and plain text links. Classifiers receive only normalized links,
    not email prose. The safe body is stored in private, expiring text chunks for editors
    and rendered as text, never HTML. Tracking wrappers remain excluded unless a caller
    explicitly supplies an offline-tested resolver; production intake does not supply one.
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
    warnings, candidates = set(), []
    try:
        sender = _addresses(message, "From", single=True)[0]
    except SubmissionRejected:
        sender = "unknown"
        warnings.add("mime_from_unavailable")
    try:
        recipients = sorted(set(_addresses(message, "To") + _addresses(message, "Cc")))
    except SubmissionRejected:
        recipients = []
        warnings.add("mime_recipients_unavailable")
    plain_bodies, html_bodies = [], []
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
            html_bodies.append(body)
            parser = _Links()
            parser.feed(body)
            parser.close()
            candidates.extend(parser.links)
        else:
            plain_bodies.append(body)
            for line in body.splitlines():
                for match in _URL.finditer(line):
                    url = match.group(0).rstrip(".,;:!?\u201d\u2019]")
                    while url.endswith(")") and url.count(")") > url.count("("):
                        url = url[:-1]
                    label = "Account action" if _ACTION_LABEL.search(line) else ""
                    candidates.append((url, label))
    links, excluded = {}, set()
    excluded_count = 0
    for raw_url, title in candidates:
        if title == "Account action" or _ACTION_LABEL.search(title):
            action_url = safe_editorial_url(raw_url)
            if action_url is not None:
                excluded.add(action_url)
            warnings.add("excluded_links")
            excluded_count += 1
            continue
        if is_supported_email_tracking_url(raw_url):
            if tracking_resolver is None:
                # Preserve the publisher's original click wrapper as private,
                # unresolved source material. Never dereference subscriber URLs
                # during extraction; the monitoring UI renders these as text.
                url = raw_url.strip()
                resolution_status = "unresolved"
            else:
                try:
                    resolved = tracking_resolver(raw_url)
                except Exception:
                    warnings.add("tracking_resolution_failed")
                    url = raw_url.strip()
                    resolution_status = "unresolved"
                else:
                    url = safe_editorial_url(resolved)
                    resolution_status = "resolved" if url is not None else "unresolved"
                    if url is None:
                        url = raw_url.strip()
        else:
            url = safe_editorial_url(raw_url)
            resolution_status = "resolved" if url is not None else "unresolved"
        if url is None:
            warnings.add("excluded_links")
            excluded_count += 1
            continue
        if url not in links or title:
            link = {"url": url, "title": _link_title(title, url)}
            if resolution_status != "resolved":
                link["resolutionStatus"] = "unresolved"
            links[url] = link
    result_links = [item for url, item in links.items() if url not in excluded]
    if plain_bodies:
        safe_body = "\n\n".join(plain_bodies)
    elif html_bodies:
        parser = _SafeText()
        for body in html_bodies:
            parser.feed(body)
            parser.parts.append("\n\n")
        parser.close()
        safe_body = "".join(parser.parts)
    else:
        safe_body = ""
    safe_body = "\n".join(line.rstrip() for line in safe_body.replace("\r", "").split("\n")).strip()
    return {"sender": sender, "recipients": recipients, "subject": _text(message.get("Subject")),
            "messageId": _text(message.get("Message-ID")), "date": _text(message.get("Date"), 128),
            "links": result_links, "warnings": sorted(warnings), "excludedLinkCount": excluded_count,
            "safeBodyText": safe_body}
