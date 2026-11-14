"""Titles and addresses of the sources a research run files as References (PPY-0a5d52).

A search result's title is written for a results page: it carries the arXiv id in brackets, a site name, a "Proceedings of ..." line and a trailing ellipsis
where the engine cut it. The opened page's own ``<title>`` or the PDF's metadata title is better when the run read the source. All pure functions.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .reference_identity import arxiv_id

_ARXIV_PREFIX = re.compile(r"^\s*\[\s*(?:arxiv:\s*)?(?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Za-z]{2})?/\d{7})(?:v\d+)?\s*\]\s*", re.IGNORECASE)
_TRAILING_ELLIPSIS = re.compile(r"\s*(?:\.{3,}|…)\s*$")
_SEPARATOR = re.compile(r"\s+[|–—\-]\s+")
_PROCEEDINGS = re.compile(r"^(?:in\s+)?proceedings of\b", re.IGNORECASE)
#: What a blocked or empty page calls itself. These say nothing about the source.
_NOT_A_TITLE = re.compile(
    r"^(?:just a moment|access denied|attention required|are you a (?:robot|human)|redirecting|page not found|not found|forbidden|"
    r"(?:error )?\d{3}\b|error\b|cookies?\b|please (?:enable|wait)|sign in\b|log ?in\b|untitled|microsoft word)", re.IGNORECASE)
_FILE_NAME = re.compile(r"\.(?:pdf|docx?|tex|dvi|ps)$", re.IGNORECASE)
_SECOND_LEVEL = frozenset({"co", "com", "org", "gov", "ac", "net", "edu"})


def site_label(url: str) -> str:
    """The name of a site's registered domain, folded to letters and digits: ``springer`` for ``link.springer.com``, ``cornell`` for ``cs.cornell.edu``."""
    labels = [label for label in (urlsplit(url).hostname or "").lower().split(".") if label]
    if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2:
        return re.sub(r"[^a-z0-9]", "", labels[-3])
    return re.sub(r"[^a-z0-9]", "", labels[-2]) if len(labels) >= 2 else ""


def _names_the_site(segment: str, label: str) -> bool:
    return bool(label) and label in re.sub(r"[^a-z0-9]", "", segment.lower())


def clean_search_title(title: str, url: str = "") -> str:
    """A search result's title without what the results page added: an arXiv id in brackets at the start, a trailing ellipsis, and a trailing segment after
    ``|`` or a dash that names the site the page is on or is a "Proceedings of ..." line. Segments are only taken off while another remains."""
    text = _ARXIV_PREFIX.sub("", " ".join(str(title or "").split()))
    text = _TRAILING_ELLIPSIS.sub("", text).strip()
    label = site_label(url)
    pieces = re.split(r"(\s+[|\u2013\u2014\-]\s+)", text)
    segments, separators = pieces[0::2], pieces[1::2]
    while len(segments) > 1 and (_names_the_site(segments[-1], label) or _PROCEEDINGS.match(segments[-1].strip())):
        segments.pop()
        separators.pop()
    kept = segments[0]
    for separator, segment in zip(separators, segments[1:]):
        kept += separator + segment
    return _TRAILING_ELLIPSIS.sub("", kept).strip()


class _Title(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.title: list[str] = []
        self.heading = ""
        self.og = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            fields = dict(attrs)
            if (fields.get("property") or fields.get("name") or "").lower() in {"og:title", "citation_title", "dc.title"} and not self.og:
                self.og = (fields.get("content") or "").strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title.append(data)


def page_title(html: str) -> str | None:
    """The title a page gives itself: a scholarly ``citation_title`` or ``og:title`` meta tag when it has one, else its ``<title>``. None when absent or when it
    is what a blocked page says (``Just a moment...``)."""
    parser = _Title()
    try:
        parser.feed(html[:200_000])
        parser.close()
    except Exception:  # noqa: BLE001 - a page that will not parse has no title
        return None
    return usable_title(parser.og or " ".join("".join(parser.title).split()))


def usable_title(title: str | None) -> str | None:
    text = " ".join(str(title or "").split())
    if len(text) < 6 or _NOT_A_TITLE.match(text) or _FILE_NAME.search(text) or re.match(r"^https?://\S+$", text):
        return None
    return text


def canonical_record_url(url: str) -> str:
    """The record's address where a mirror was found: an arXiv paper under ar5iv, alphaxiv, export.arxiv.org or its pdf address becomes ``https://arxiv.org/abs/<id>``
    (no version). Any other address is returned as it is. DOI resolution is not attempted."""
    paper = arxiv_id(url)
    return f"https://arxiv.org/abs/{paper}" if paper else url
