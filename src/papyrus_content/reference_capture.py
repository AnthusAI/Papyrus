"""Capture a Reference's source: its full readable text, and the signals that say how complete that capture looks.

``capture_source(url)`` is the first stage of curation before review (``docs/reference-curation-pipeline.md``). It reuses link
exploration for everything about the network (redirects, tracker wrappers, public addresses only, typed URL-free failures) and adds
what a reviewer needs and the excerpt readers do not give: the whole article (headings, paragraphs, list items) or every page of a PDF,
the bytes of the PDF (for GROBID), and a set of **completeness signals**.

The signals are facts about the capture (word counts against what the page declares, paywall phrases, how the text ends). They are not
a verdict. Whether a capture is complete is a decision for a classifier trained on editor labels (``reference_curation.apply_editor_correction``
records those labels), so nothing here sets a "complete" flag.

No network is used except through the ``explorer`` and ``download`` callables, which tests replace.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from papyrus_content import pdf_text, youtube_transcript
from papyrus_content.link_exploration import Context, Exploration, Response, explore
from papyrus_content.publication_dates import publication_date_from_html

# Capture failures that say the network or the server had a bad moment, not that the source is unreadable. A later run retries them.
TRANSIENT_CAPTURE_FAILURES = frozenset({"timeout", "connection", "http_5xx", "dns"})
# Bodies shorter than this many characters are COUNTED (``shortBodies``) so a thin capture shows up in the stats. It is a report
# threshold, never a gate: nothing is refused, retried or flagged because of it.
SHORT_BODY_CHARACTERS = 500

SCHOLARLY_HOSTS = (
    "arxiv.org", "biorxiv.org", "medrxiv.org", "openreview.net", "aclanthology.org", "proceedings.mlr.press", "papers.nips.cc",
    "proceedings.neurips.cc", "openaccess.thecvf.com", "dl.acm.org", "ieeexplore.ieee.org", "link.springer.com", "sciencedirect.com",
    "semanticscholar.org", "ssrn.com", "jmlr.org", "pnas.org", "science.org", "nature.com", "plos.org", "frontiersin.org", "mdpi.com",
    "onlinelibrary.wiley.com", "tandfonline.com", "journals.sagepub.com", "academic.oup.com", "cambridge.org",
)

PAYWALL_MARKERS = (
    ("subscribe_to_continue", re.compile(r"subscribe (?:now |today )?to (?:continue|read|unlock|get)", re.I)),
    ("sign_in_to_read", re.compile(r"(?:log|sign) ?in to (?:continue|read|view|access)", re.I)),
    ("subscribers_only", re.compile(r"(?:for|to|available to|exclusive to) (?:paid |paying |premium )?(?:subscribers|members)(?: only)?", re.I)),
    ("create_account_to_read", re.compile(r"(?:create|register for) (?:a |your )?(?:free )?account to (?:continue|read|view)", re.I)),
    ("continue_reading", re.compile(r"\bcontinue reading\b", re.I)),
    ("read_more_tail", re.compile(r"\bread (?:more|the full (?:article|story))\b", re.I)),
    ("premium_content", re.compile(r"premium (?:content|article|story|subscribers)", re.I)),
    ("article_limit", re.compile(r"(?:free )?article limit|last free article|reached your (?:free|monthly)|\d+ free articles?", re.I)),
)
TAIL_CHARACTERS = 600
TERMINAL = ".!?\"')]}”’»"


# --- the captured result ---------------------------------------------------------------------------------------------


@dataclass
class Capture:
    """What capture produced. ``ok`` means ``text`` is the source's readable text (however complete)."""

    ok: bool
    failure: str | None = None
    text: str = ""
    source_kind: str | None = None          # "html" or "pdf"
    content_type: str | None = None
    destination_url: str | None = None
    via: str | None = None                  # "direct", or "citation_pdf_url" / "alternate_pdf" / "linked_pdf" / "full_text_link" / "arxiv_pdf" when a PDF was followed
    pdf_bytes: bytes | None = field(default=None, repr=False)
    signals: dict[str, Any] = field(default_factory=dict)
    paper: dict[str, Any] = field(default_factory=dict)
    page: dict[str, Any] = field(default_factory=dict)   # what the page declares about itself (title, description, site name)
    preview: dict[str, Any] | None = None   # the page's link-preview metadata (imageUrl, description, siteName, title) read by this same fetch; None when no HTML page was read
    publication_date: dict[str, str] | None = None   # the date the HTML page declares for itself ({value, precision, source}); None when it declares none
    full_text_url: str | None = None        # the address the text actually came from when it is not the page itself (the PDF the page links)
    text_via: str | None = None             # YouTube links only: "youtube_transcript", or "youtube_description" when the transcript was unavailable
    text_reason: str | None = None          # why the transcript was not used: "blocked", "no_transcript", "unavailable", "unreadable", "library_missing"

    @property
    def transient(self) -> bool:
        return not self.ok and self.failure in TRANSIENT_CAPTURE_FAILURES


# --- HTML -> readable text -------------------------------------------------------------------------------------------


class _Article(HTMLParser):
    """Headings, paragraphs, list items, quotes and code blocks, preferring those inside <article> / <main>."""

    SKIPPED = {"script", "style", "noscript", "svg", "nav", "footer", "form", "template", "aside", "button", "iframe", "select"}
    BLOCKS = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "p": "", "li": "- ", "blockquote": "> ", "pre": ""}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_article = 0
        self.skip = 0
        self.header_skip = 0
        self.block: str | None = None
        self.parts: list[str] = []
        self.article_blocks: list[tuple[str, str]] = []
        self.page_blocks: list[tuple[str, str]] = []
        self.metas: dict[str, str] = {}
        self.json_ld: list[str] = []
        self._json_ld = False
        self._json_buffer: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = {name: value or "" for name, value in attrs}
        if tag == "meta":
            key = (fields.get("name") or fields.get("property") or "").lower()
            if key and key not in self.metas and fields.get("content"):
                self.metas[key] = fields["content"].strip()
            if key == "citation_author":
                self.metas["citation_author_count"] = str(int(self.metas.get("citation_author_count", "0")) + 1)
            return
        if tag == "title":
            self._in_title = True
            return
        if tag == "script":
            self._json_ld = "ld+json" in fields.get("type", "").lower()
            self._json_buffer = []
        if tag in self.SKIPPED:
            self.skip += 1
            return
        if tag == "header" and not self.in_article:
            self.header_skip += 1
            return
        if tag in {"article", "main"} or fields.get("role") == "main":
            self.in_article += 1
        if tag in self.BLOCKS and not self.skip and not self.header_skip and self.block is None:
            self.block, self.parts = tag, []
        elif tag == "br" and self.block is not None:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            return
        if tag == "script" and self._json_ld:
            self.json_ld.append("".join(self._json_buffer))
            self._json_ld = False
        if tag in self.SKIPPED:
            self.skip = max(self.skip - 1, 0)
            return
        if tag == "header" and self.header_skip:
            self.header_skip -= 1
            return
        if tag in {"article", "main"} and self.in_article:
            self.in_article -= 1
        if tag == self.block:
            raw = "".join(self.parts) if tag == "pre" else re.sub(r"\s+", " ", "".join(self.parts))
            text = raw.strip()
            if text:
                entry = (tag, f"{self.BLOCKS[tag]}{text}")
                self.page_blocks.append(entry)
                if self.in_article:
                    self.article_blocks.append(entry)
            self.block, self.parts = None, []

    def handle_data(self, data: str) -> None:
        if self._json_ld:
            self._json_buffer.append(data)
        elif self._in_title:
            self.title += data
        elif self.block is not None and not self.skip:
            self.parts.append(data)


def _words(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text))


def parse_html(html: str) -> dict[str, Any]:
    """``text`` (markdown-like article text), the page's declared facts and its structured data. Never raises."""
    parser = _Article()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - a page that breaks the parser has no readable text
        return {"text": "", "metas": {}, "structured": {}, "headingCount": 0, "paragraphCount": 0}
    article = parser.article_blocks
    use_article = sum(_words(text) for _, text in article) >= 80
    chosen = article if use_article else [(tag, text) for tag, text in parser.page_blocks if tag != "p" or len(text) >= 40]
    # Keep list items together under a blank-line-free run so the markdown reads as a list.
    lines: list[str] = []
    previous = ""
    for tag, text in chosen:
        if lines and not (tag == "li" and previous == "li"):
            lines.append("")
        lines.append(text)
        previous = tag
    return {
        "text": "\n".join(lines).strip(),
        "metas": parser.metas,
        "structured": structured_data(parser.json_ld),
        "documentTitle": re.sub(r"\s+", " ", parser.title).strip(),
        "headingCount": sum(1 for tag, _ in chosen if tag.startswith("h")),
        "paragraphCount": sum(1 for tag, _ in chosen if tag == "p"),
        "usedArticleElement": use_article,
    }


def structured_data(blocks: list[str]) -> dict[str, Any]:
    """The few schema.org facts that bear on completeness: declared word count, free access, article body length."""
    found: dict[str, Any] = {}

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for key, value in node.items():
                if key == "wordCount" and "declaredWordCount" not in found:
                    try:
                        found["declaredWordCount"] = int(str(value).replace(",", "").strip())
                    except ValueError:
                        pass
                elif key == "isAccessibleForFree" and "isAccessibleForFree" not in found:
                    found["isAccessibleForFree"] = str(value).strip().lower() not in {"false", "0", "no"}
                elif key == "articleBody" and isinstance(value, str) and "articleBodyWordCount" not in found:
                    found["articleBodyWordCount"] = _words(value)
                else:
                    walk(value)

    for block in blocks:
        try:
            walk(json.loads(block))
        except (ValueError, TypeError):
            continue
    return found


# --- PDF -> readable text --------------------------------------------------------------------------------------------


def pdf_to_text(data: bytes) -> tuple[str, dict[str, Any]]:
    """Every page's text, with line wraps and hyphenation undone. Returns (text, page facts). Raises on an unreadable file."""
    page_count, pages = pdf_text.extract_pages(data)
    chunks, empty = [], 0
    for page in pages:
        body = page["text"].replace("\r", "")
        body = re.sub(r"(?<=\w)-\n(?=[a-z])", "", body)
        body = re.sub(r"(?<!\n)\n(?!\n)", " ", body)
        body = re.sub(r"[ \t]+", " ", body).strip()
        if body:
            chunks.append(body)
        else:
            empty += 1
    return "\n\n".join(chunks), {"pdfPageCount": page_count, "pdfEmptyPageCount": empty}


# --- completeness signals --------------------------------------------------------------------------------------------


def ending_pattern(text: str) -> str:
    """How the text ends: a sentence, an ellipsis, a truncation marker, or mid-sentence. A fact, not a judgment."""
    tail = text.rstrip()
    if not tail:
        return "empty"
    if tail.endswith(("…", "...")):
        return "ellipsis"
    if re.search(r"(?:continue reading|read more|read the full (?:article|story)|subscribe to (?:read|continue))\W*$", tail[-120:], re.I):
        return "truncation_marker"
    if tail[-1] in TERMINAL:
        return "sentence_end"
    return "no_terminal_punctuation"


def completeness_signals(text: str, *, parsed: dict[str, Any] | None = None, pdf: dict[str, Any] | None = None,
                         response_truncated: bool = False, description: str = "") -> dict[str, Any]:
    """Facts about how complete a capture looks. No field here is a verdict; the fields are inputs to a later classifier."""
    parsed = parsed or {}
    structured = parsed.get("structured") or {}
    word_count = _words(text)
    description_words = _words(description)
    tail = text[-TAIL_CHARACTERS:]
    markers = [{"id": name, "inTail": bool(pattern.search(tail))} for name, pattern in PAYWALL_MARKERS if pattern.search(text)]
    signals: dict[str, Any] = {
        "wordCount": word_count,
        "characterCount": len(text),
        "paragraphCount": parsed.get("paragraphCount") if parsed else len([p for p in text.split("\n\n") if p.strip()]),
        "headingCount": parsed.get("headingCount", 0),
        "metaDescriptionWordCount": description_words,
        "bodyNotLongerThanDescription": bool(description_words) and word_count <= description_words,
        "wordsPerDescriptionWord": round(word_count / description_words, 2) if description_words else None,
        "paywallMarkers": markers,
        "endingPattern": ending_pattern(text),
        "endsWithTerminalPunctuation": bool(text.rstrip()) and text.rstrip()[-1] in TERMINAL,
        "tail": text.rstrip()[-120:],
        "responseTruncated": response_truncated,
    }
    if "declaredWordCount" in structured:
        declared = structured["declaredWordCount"]
        signals["declaredWordCount"] = declared
        signals["wordCountRatioToDeclared"] = round(word_count / declared, 2) if declared else None
    if "articleBodyWordCount" in structured:
        signals["structuredArticleBodyWordCount"] = structured["articleBodyWordCount"]
    if "isAccessibleForFree" in structured:
        signals["structuredAccessibleForFree"] = structured["isAccessibleForFree"]
    if pdf:
        signals.update(pdf)
        pages = pdf.get("pdfPageCount") or 0
        signals["wordsPerPdfPage"] = round(word_count / pages, 1) if pages else None
    return signals


# --- paper detection -------------------------------------------------------------------------------------------------


def arxiv_id(url: str) -> str | None:
    parts = urllib.parse.urlsplit(url)
    if not (parts.hostname or "").lower().endswith("arxiv.org"):
        return None
    match = re.match(r"^/(?:abs|pdf|html)/([a-z\-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?$", parts.path)
    return match.group(1) if match else None


def doi_of(url: str) -> str | None:
    parts = urllib.parse.urlsplit(url)
    if (parts.hostname or "").lower() in {"doi.org", "dx.doi.org"}:
        return urllib.parse.unquote(parts.path.lstrip("/")) or None
    return None


def detect_paper(source_url: str, destination_url: str | None, *, metas: dict[str, str] | None = None, text: str = "") -> dict[str, Any]:
    """Whether the source looks like a research paper, and why. ``isPaper`` is a routing decision for GROBID, not an editorial one."""
    metas = metas or {}
    basis: list[str] = []
    hosts = {(urllib.parse.urlsplit(url).hostname or "").lower() for url in (source_url, destination_url or "")}
    identifiers: dict[str, str] = {}
    for url in (source_url, destination_url or ""):
        if arxiv_id(url):
            identifiers["arxivId"] = arxiv_id(url) or ""
        if doi_of(url):
            identifiers["doi"] = doi_of(url) or ""
    if "arxivId" in identifiers:
        basis.append("arxiv")
    if "doi" in identifiers:
        basis.append("doi")
    if any(host == known or host.endswith("." + known) for host in hosts for known in SCHOLARLY_HOSTS):
        basis.append("scholarly_host")
    if metas.get("citation_title") and (metas.get("citation_author") or metas.get("citation_author_count")):
        basis.append("citation_meta")
        if metas.get("citation_doi") and "doi" not in identifiers:
            identifiers["doi"] = metas["citation_doi"]
    head, rest = text[:4000], text[4000:]
    if re.search(r"\babstract\b", head, re.I) and re.search(r"\b(?:references|bibliography)\b", rest or text, re.I) and "\n" in text:
        basis.append("paper_structure")
    return {"isPaper": bool(basis), "basis": basis, **identifiers}


# --- the page's own full-text link -------------------------------------------------------------------------------------


class _FullTextLinks(HTMLParser):
    """`<link rel="alternate" type="application/pdf">` and every anchor with its visible label."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.alternates: list[str] = []
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = {name: value or "" for name, value in attrs}
        if tag == "link" and fields.get("href") and "alternate" in fields.get("rel", "").lower().split() and "pdf" in fields.get("type", "").lower():
            self.alternates.append(fields["href"])
        elif tag == "a" and fields.get("href"):
            self._href, self._label = fields["href"], [fields.get("title", ""), fields.get("aria-label", "")]

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._label.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.anchors.append((self._href, re.sub(r"\s+", " ", " ".join(self._label)).strip()))
            self._href = None


FULL_TEXT_LABEL = re.compile(r"\bpdf\b|\bfull[\s-]?text\b", re.I)
PDF_PATH = re.compile(r"\.pdf($|[?#])", re.I)


def full_text_links(html: str, base_url: str, metas: dict[str, str]) -> list[tuple[str, str]]:
    """The page's own links to its full text as (absolute address, ``via``), best signal first and each address once:

    1. ``<meta name="citation_pdf_url">`` (``citation_pdf_url``);
    2. ``<link rel="alternate" type="application/pdf">`` (``alternate_pdf``);
    3. anchors on the page's own site to a ``.pdf`` (``linked_pdf``), then anchors on its own site labelled "PDF" or "full text"
       (``full_text_link``).

    No publisher is named anywhere; these are the standard signals journals already publish for indexers.
    """
    parser = _FullTextLinks()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - a page that breaks the parser links nothing
        return []
    host = urllib.parse.urlsplit(base_url).hostname
    found: list[tuple[str, str]] = []

    def add(href: str, via: str, *, same_site: bool) -> None:
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            return
        absolute = urllib.parse.urldefrag(urllib.parse.urljoin(base_url, href))[0]
        if urllib.parse.urlsplit(absolute).scheme not in {"http", "https"} or absolute == urllib.parse.urldefrag(base_url)[0]:
            return
        if same_site and urllib.parse.urlsplit(absolute).hostname != host:
            return
        if all(absolute != known for known, _ in found):
            found.append((absolute, via))

    if metas.get("citation_pdf_url"):
        add(metas["citation_pdf_url"], "citation_pdf_url", same_site=False)
    for href in parser.alternates:
        add(href, "alternate_pdf", same_site=False)
    for href, _ in parser.anchors:
        if PDF_PATH.search(href):
            add(href, "linked_pdf", same_site=True)
    for href, label in parser.anchors:
        if FULL_TEXT_LABEL.search(label):
            add(href, "full_text_link", same_site=True)
    return found


# --- capture ---------------------------------------------------------------------------------------------------------


Explorer = Callable[..., Exploration]


def _is_pdf(response: Response, url: str) -> bool:
    return ("pdf" in response.headers.get("content-type", "").lower() or pdf_text.is_pdf_bytes(response.body)
            or urllib.parse.urlsplit(url).path.lower().endswith(".pdf"))


def _decode(response: Response) -> str:
    match = re.search(r"charset=([\w-]+)", response.headers.get("content-type", ""), re.I)
    try:
        return response.body.decode(match.group(1) if match else "utf-8", errors="replace")
    except LookupError:
        return response.body.decode("utf-8", errors="replace")


def _fetch(explorer: Explorer, url: str, context: Context) -> tuple[Exploration | None, str | None]:
    found = explorer(url, context, want_text=False, use_search=False, keep_response=True)
    if found.response is None:
        return None, found.direct_failure or found.failure or "unreadable"
    return found, None


def _pdf_capture(found: Exploration, via: str) -> Capture:
    response = found.response
    assert response is not None
    if response.truncated:
        return Capture(False, "too_large", destination_url=found.url)
    try:
        text, pdf = pdf_to_text(response.body)
    except Exception:  # noqa: BLE001 - a file that will not parse has no text
        return Capture(False, "unreadable", destination_url=found.url)
    if not text:
        return Capture(False, "no_text", source_kind="pdf", content_type="application/pdf", destination_url=found.url, pdf_bytes=response.body,
                       signals={"pdfPageCount": pdf["pdfPageCount"], "pdfEmptyPageCount": pdf["pdfEmptyPageCount"], "wordCount": 0})
    return Capture(True, None, text, "pdf", "application/pdf", found.url, via, response.body,
                   completeness_signals(text, pdf=pdf))


def capture_source(source_url: str, *, title: str = "", explorer: Explorer = explore) -> Capture:
    """The page capture, and for a YouTube video its transcript in place of the page text (``_youtube_capture``)."""
    captured = _capture_page(source_url, title=title, explorer=explorer)
    identifier = youtube_transcript.video_id(source_url)
    return captured if identifier is None else _youtube_capture(captured, identifier)


def _youtube_capture(captured: Capture, identifier: str) -> Capture:
    """The video's transcript is the text. When YouTube will not give it, the page's title and description stand in, with the reason."""
    text, reason = youtube_transcript.fetch_transcript(identifier)
    if text:
        captured.ok, captured.failure, captured.text = True, None, text
        captured.source_kind, captured.content_type = "transcript", "text/plain"
        captured.signals = completeness_signals(text)
        captured.text_via, captured.text_reason = "youtube_transcript", None
        return captured
    captured.text_via, captured.text_reason = "youtube_description", reason
    if not captured.ok:
        blurb = "\n\n".join(captured.page[key] for key in ("title", "description") if captured.page.get(key))
        if blurb:
            captured.ok, captured.failure, captured.text = True, None, blurb
            captured.source_kind, captured.content_type = "html", "text/html"
            captured.signals = completeness_signals(blurb, description=captured.page.get("description", ""))
    return captured


def _capture_page(source_url: str, *, title: str = "", explorer: Explorer = explore) -> Capture:
    """Resolve the address, read the destination (whole HTML article or whole PDF) and describe how complete the text looks.

    Never raises. A source that cannot be captured returns ``ok=False`` with a typed, URL-free ``failure`` and any signals that were
    still observable (a bot-blocked page, an image-only PDF).
    """
    context = Context(title=title)
    arxiv = arxiv_id(source_url)
    target = f"https://arxiv.org/pdf/{arxiv}" if arxiv else source_url
    found, failure = _fetch(explorer, target, context)
    if found is None or found.response is None:
        return Capture(False, failure or "unreadable")
    response = found.response
    destination = found.url or target
    if _is_pdf(response, destination):
        capture = _pdf_capture(found, "arxiv_pdf" if arxiv else "direct")
        capture.paper = detect_paper(source_url, destination, text=capture.text)
        return capture
    if "html" not in response.headers.get("content-type", "").lower() and response.headers.get("content-type"):
        return Capture(False, "unsupported_media", content_type=response.headers.get("content-type", "").split(";")[0],
                       destination_url=destination)
    html = _decode(response)
    preview = found.metadata.as_dict() if found.metadata else {}
    parsed = parse_html(html)
    page_publication_date = publication_date_from_html(html)
    metas = parsed["metas"]
    description = metas.get("og:description") or metas.get("description") or metas.get("twitter:description") or ""
    page = {key: value for key, value in (("title", metas.get("og:title") or parsed.get("documentTitle")),
                                          ("description", description), ("siteName", metas.get("og:site_name"))) if value}
    text = parsed["text"]
    via, pdf_bytes = "direct", None
    # Thin is read off the page itself: its main-content text is no longer than what its own meta description already says, so the
    # page is a blurb in front of the article (a journal landing page that fronts a PDF). There is no word or character cap.
    thin = _words(text) <= _words(description)
    for linked_url, via_kind in full_text_links(html, destination, metas):
        if via_kind != "citation_pdf_url" and not thin:
            continue    # a full page of text is the article; only the page's own declared PDF replaces it regardless
        linked, _ = _fetch(explorer, linked_url, context)
        if linked is not None and linked.response is not None and _is_pdf(linked.response, linked.url or linked_url):
            pdf_capture = _pdf_capture(linked, via_kind)
            if pdf_capture.ok and (via_kind == "citation_pdf_url" or _words(pdf_capture.text) > _words(text)):
                pdf_capture.full_text_url = linked.url or linked_url
                pdf_capture.paper = detect_paper(source_url, destination, metas=metas, text=pdf_capture.text)
                pdf_capture.page = page
                pdf_capture.preview = preview
                pdf_capture.publication_date = page_publication_date
                pdf_capture.signals["pageWordCount"] = _words(text)
                pdf_capture.signals["metaDescriptionWordCount"] = _words(description)
                return pdf_capture
    if not text:
        text = _fallback_text(html)
    if not text:
        return Capture(False, "no_text", source_kind="html", content_type="text/html", destination_url=destination, page=page,
                       preview=preview, publication_date=page_publication_date, paper=detect_paper(source_url, destination, metas=metas),
                       signals=completeness_signals("", parsed=parsed, response_truncated=response.truncated, description=description))
    signals = completeness_signals(text, parsed=parsed, response_truncated=response.truncated, description=description)
    return Capture(True, None, text, "html", "text/html", destination, via, pdf_bytes, signals,
                   detect_paper(source_url, destination, metas=metas, text=text), page, preview=preview,
                   publication_date=page_publication_date)


def _fallback_text(html: str) -> str:
    from papyrus_content.ideas.excerpt import excerpt_from_html

    return excerpt_from_html(html, 10_000_000) or ""
