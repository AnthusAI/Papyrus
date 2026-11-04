"""The outbound links of a captured page, with the page's main-content links told apart from its navigation, footer and thanks (PPY-31821c).

Capture parses the page once; this reads the same HTML for its anchors and keeps every one with a ``kind``:

* ``content``: a link in the page's main content (inside ``<article>``, ``<main>`` or ``role="main"``), the links a follower may use;
* ``navigation``: a link in a ``<nav>``, a sidebar or ``<aside>``, a page or article ``<header>``, a menu, a share or social block, a breadcrumb,
  a comment, a related-posts or pager block, or marked ``rel="tag"``, ``rel="category"``, ``rel="author"``, ``rel="next"`` or ``rel="prev"``;
* ``footer``: a link in a ``<footer>`` or ``role="contentinfo"``;
* ``credit``: a link in a thanks or acknowledgements passage (the block starts with "Acknowledgements", "Thanks:" or "Special thanks", says "I would
  like to thank", or sits under a heading of that kind). A sentence that merely begins "Thanks to this method ..." is content;
* ``profile``: a link to a person's profile on a social site, wherever it is.

The rule reads structure the page already declares (HTML5 landmarks, ARIA roles and the common class names of themes); no publisher is named. It is
a rule, not a judgment, and it can be wrong: a page with no landmarks at all treats everything outside a ``nav``-ish class as content, a thanks
passage that does not use those words is content, and a "related posts" list in the article body is content. Nothing is followed here. The result
is stored, not acted on.
"""
from __future__ import annotations

import re
import urllib.parse
from html.parser import HTMLParser
from typing import Any

CONTENT, NAVIGATION, FOOTER, CREDIT, PROFILE = "content", "navigation", "footer", "credit", "profile"
KINDS = (CONTENT, NAVIGATION, FOOTER, CREDIT, PROFILE)
LABEL_CHARACTERS = 200

_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
_NAVIGATION_TAGS = frozenset({"nav", "aside", "header", "menu"})
_NAVIGATION_ROLES = frozenset({"navigation", "banner", "complementary", "search", "menu", "menubar"})
_FOOTER_ROLES = frozenset({"contentinfo"})
_MAIN_TAGS = frozenset({"article", "main"})
_BLOCK_TAGS = frozenset({"p", "li", "blockquote", "dd", "dt", "td", "figcaption"})
_NAVIGATION_CLASS_TOKENS = frozenset({
    "nav", "navbar", "navigation", "menu", "breadcrumb", "breadcrumbs", "sidebar", "share", "sharing", "social", "cookie", "cookies", "comment",
    "comments", "related", "pagination", "pager", "toc", "skip", "newsletter", "subscribe", "widget", "widgets", "masthead",
})
_FOOTER_CLASS_TOKENS = frozenset({"footer"})
_NAVIGATION_RELS = frozenset({"tag", "category", "author", "next", "prev", "previous", "home", "start", "index", "up", "me"})
_HEADING = re.compile(r"^h[1-6]$")
_CREDIT_START = re.compile(r"^\W*(?:acknowledg\w*|credits?\s*:|special thanks|with thanks|thanks\s*:|thank you\b)", re.IGNORECASE)
_CREDIT_SAYS = re.compile(r"\b(?:I|we)\s+(?:would\s+like\s+to\s+|want\s+to\s+|wish\s+to\s+|am\s+|are\s+)?(?:thank|grateful)\b", re.IGNORECASE)
_CREDIT_HEADING = re.compile(r"^\W*(?:acknowledg\w*|thanks|thank you|credits?|about the author)\W*$", re.IGNORECASE)
_SOCIAL_HOSTS = {"linkedin.com": 1, "twitter.com": 1, "x.com": 1, "facebook.com": 1, "instagram.com": 1, "threads.net": 1, "tiktok.com": 1}
_SOCIAL_LINKEDIN_PROFILE = re.compile(r"^/(?:in|company|pub|school)/[^/]+/?$")
_SOCIAL_RESERVED = frozenset({"home", "i", "intent", "share", "search", "hashtag", "explore", "settings", "login", "signup", "about", "tos", "privacy"})
_SKIPPED_SCHEMES = ("#", "javascript:", "mailto:", "tel:", "data:", "sms:", "blob:")


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.lower()) if token}


def _is_profile(address: str) -> bool:
    parts = urllib.parse.urlsplit(address)
    host = (parts.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    if host not in _SOCIAL_HOSTS:
        return False
    path = parts.path
    if host == "linkedin.com":
        return bool(_SOCIAL_LINKEDIN_PROFILE.match(path))
    segments = [segment for segment in path.split("/") if segment]
    return len(segments) == 1 and segments[0].lstrip("@").lower() not in _SOCIAL_RESERVED


class _Anchors(HTMLParser):
    """Every ``<a href>`` with its label, its enclosing landmarks and the text of the block it sits in."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.anchors: list[dict[str, Any]] = []
        self.blocks: list[dict[str, Any]] = []     # one per p/li/...: its text, so a thanks passage can be recognised as a whole
        self.heading: str = ""
        self._heading_text: list[str] | None = None
        self._anchor: dict[str, Any] | None = None
        self._ignored = 0                          # script/style depth

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = {name: (value or "") for name, value in attrs}
        if tag in {"script", "style", "template", "noscript"}:
            self._ignored += 1
            return
        if tag == "img" and self._anchor is not None:
            self._anchor["label"].append(fields.get("alt") or fields.get("title") or "")
        if tag in _VOID:
            return
        entry = {"tag": tag, "role": fields.get("role", "").lower(), "tokens": _tokens(f"{fields.get('class', '')} {fields.get('id', '')}")}
        if _HEADING.match(tag):
            self._heading_text = []
        if tag in _BLOCK_TAGS:
            entry["block"] = {"text": [], "anchors": []}
            self.blocks.append(entry["block"])
        self.stack.append(entry)
        if tag == "a" and fields.get("href", "").strip():
            self._anchor = {"href": fields["href"].strip(), "rel": _tokens(fields.get("rel", "")),
                            "label": [fields.get("aria-label", ""), fields.get("title", "")], "ancestors": list(self.stack[:-1]),
                            "heading": self.heading, "block": next((e["block"] for e in reversed(self.stack[:-1]) if "block" in e), None)}
            self.anchors.append(self._anchor)
            if self._anchor["block"] is not None:
                self._anchor["block"]["anchors"].append(self._anchor)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "template", "noscript"}:
            self._ignored = max(self._ignored - 1, 0)
            return
        if tag in _VOID:
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break
        if tag == "a":
            self._anchor = None
        if _HEADING.match(tag) and self._heading_text is not None:
            self.heading = re.sub(r"\s+", " ", "".join(self._heading_text)).strip()
            self._heading_text = None

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        if self._anchor is not None:
            self._anchor["label"].append(data)
        if self._heading_text is not None:
            self._heading_text.append(data)
        for entry in self.stack:
            if "block" in entry:
                entry["block"]["text"].append(data)


def _region(ancestors: list[dict[str, Any]]) -> str | None:
    """``footer`` or ``navigation`` when a landmark or a theme class says the link is not the page's content, else None."""
    for entry in ancestors:
        if entry["tag"] == "footer" or entry["role"] in _FOOTER_ROLES or entry["tokens"] & _FOOTER_CLASS_TOKENS:
            return FOOTER
    for entry in ancestors:
        if entry["tag"] in _NAVIGATION_TAGS or entry["role"] in _NAVIGATION_ROLES or entry["tokens"] & _NAVIGATION_CLASS_TOKENS:
            return NAVIGATION
    return None


def _in_main(ancestors: list[dict[str, Any]]) -> bool:
    return any(entry["tag"] in _MAIN_TAGS or entry["role"] == "main" for entry in ancestors)


def _in_list_item(ancestors: list[dict[str, Any]]) -> bool:
    return any(entry["tag"] == "li" for entry in ancestors)


def _is_credit(anchor: dict[str, Any]) -> bool:
    block = anchor["block"]
    text = re.sub(r"\s+", " ", "".join(block["text"])).strip() if block else ""
    return bool(_CREDIT_HEADING.match(anchor["heading"]) or _CREDIT_START.match(text) or _CREDIT_SAYS.search(text))


def _same_page(address: str, page: str) -> bool:
    def bare(value: str) -> str:
        parts = urllib.parse.urlsplit(value)
        return urllib.parse.urlunsplit((parts.scheme, (parts.hostname or "").lower(), parts.path.rstrip("/"), parts.query, ""))
    return bare(address) == bare(page)


def extract_links(html: str, base_url: str) -> list[dict[str, Any]]:
    """Every outbound http(s) link of a page, once each in page order: ``{"url", "label", "kind", "listed", "position"}``.

    ``listed`` is True for a link inside a list item (a series, a reading list). The same address twice keeps its first position and the best kind
    (content over the rest). A page that breaks the parser yields what was read so far. Never raises.
    """
    parser = _Anchors()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - a page that breaks the parser still yields the anchors read before it broke
        pass
    has_main = any(_in_main(anchor["ancestors"]) for anchor in parser.anchors)
    found: dict[str, dict[str, Any]] = {}
    for anchor in parser.anchors:
        href = anchor["href"]
        if href.lower().startswith(_SKIPPED_SCHEMES):
            continue
        try:
            absolute = urllib.parse.urldefrag(urllib.parse.urljoin(base_url, href))[0]
            parts = urllib.parse.urlsplit(absolute)
        except ValueError:
            continue
        if parts.scheme not in {"http", "https"} or not parts.hostname or _same_page(absolute, base_url):
            continue
        region = _region(anchor["ancestors"])
        if region is not None:
            kind = region
        elif has_main and not _in_main(anchor["ancestors"]):
            kind = NAVIGATION
        elif anchor["rel"] & _NAVIGATION_RELS:
            kind = NAVIGATION
        elif _is_profile(absolute):
            kind = PROFILE
        elif _is_credit(anchor):
            kind = CREDIT
        else:
            kind = CONTENT
        label = re.sub(r"\s+", " ", " ".join(piece for piece in anchor["label"] if piece)).strip()[:LABEL_CHARACTERS]
        record = {"url": absolute, "label": label, "kind": kind, "listed": _in_list_item(anchor["ancestors"]), "position": len(found) + 1}
        known = found.get(absolute)
        if known is None:
            found[absolute] = record
        elif kind == CONTENT and known["kind"] != CONTENT:
            known.update(kind=CONTENT, label=known["label"] or label)
    return list(found.values())


def summarize_links(links: list[dict[str, Any]]) -> dict[str, int]:
    """Counts for a curation card: how many links the page has and how many are content links."""
    return {"total": len(links), "content": sum(1 for link in links if link.get("kind") == CONTENT)}


def links_document(links: list[dict[str, Any]], page_url: str | None) -> str:
    """The stored body: the page's address and every link with its kind, as JSON text."""
    import json
    return json.dumps({"version": 1, "pageUrl": page_url, "links": links}, indent=2, sort_keys=True) + "\n"


def content_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The links a follower may use: only the main content's."""
    return [link for link in links if link.get("kind") == CONTENT]
