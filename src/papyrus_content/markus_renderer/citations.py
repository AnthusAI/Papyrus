"""Inline citations and an end-of-article citation list for Markus pages.

Relationship to Papyrus's other "citation" code
-----------------------------------------------
``papyrus_content.reference_citation_resolution`` /
``reference_discovery`` / ``references_commands`` are the **newsroom
knowledge-base** side of the house: they take curated ``Reference`` records
out of GraphQL, hit Crossref and OpenAlex to attach a DOI/arXiv identifier,
and write a ``citationResolution`` block back onto the record. Nothing there
produces HTML, formats a bibliography entry, or knows what a sentence looks
like. It operates on records whose ``externalItemId`` starts with
``citation:`` -- a KB identity, not a footnote marker.

What a *reader* needs is the other half: the author wrote a claim, attached a
source at that exact point in the prose, and expects a bracketed number there
and a numbered bibliography at the foot of the piece. That is a rendering
concern, it must work from repo-committed Markdown with no GraphQL round trip,
and it must run inside a static build. So this module lives alongside the KB
machinery rather than on top of it. The deliberate bridge between them is the
data format: citation entries here are **CSL-JSON**, which is what the KB
resolution code already emits identifiers for, so a later change can populate
a page's ``citations:`` block from curated references without touching this
renderer.

Parity target
-------------
The Anthus corpus (201 ``<Citation>`` + 25 ``<CitationsList>`` uses) rendered
through ``gatsby-citation-manager``:

* ``<Citation data={CSL}/>`` -> ``<span class="citation"><a href="#citation-N">N</a></span>``
  (the surrounding ``[`` ``]`` come from CSS ``::before``/``::after``).
* ``<CitationsList citationFormat="apa"/>`` -> ``<ol class="citationslist">``
  with ``<li id="citation-N">`` entries, the formatted text, and the URL
  appended as its own link.

Two behaviours of that package are deliberately **not** reproduced:

1. It numbered by first *title* match but appended every ``<Citation>`` to the
   list, so two entries sharing a title produced a list item nobody linked to
   and an inline marker pointing at the wrong one. Here a citation is
   identified by its **key**, so repeating a key reuses the number and the
   list has exactly one entry per cited work.
2. It ran ``citation-js`` in the browser. This is a build-time formatter with
   no runtime JavaScript at all.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

CitationFormatter = Callable[[Mapping[str, Any]], str]

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


class CitationError(RuntimeError):
    """Raised for an unknown citation key or an unsupported format."""


# -- name and date helpers -------------------------------------------------


def _initials(given: str) -> str:
    bits = [part for part in re.split(r"[\s.]+", given.strip()) if part]
    return " ".join(f"{part[0].upper()}." for part in bits)


def _one_name(value: Any) -> str:
    """APA-style inverted name from a CSL name, a dict, or a plain string."""
    if isinstance(value, Mapping):
        if value.get("literal"):
            return str(value["literal"]).strip()
        family = str(value.get("family") or "").strip()
        given = str(value.get("given") or "").strip()
        if family and given:
            return f"{family}, {_initials(given)}"
        return family or given
    text = str(value or "").strip()
    if not text:
        return ""
    if "," in text:
        # Already inverted ("Gundlach, Hans").
        family, _, given = text.partition(",")
        return f"{family.strip()}, {_initials(given)}" if given.strip() else family.strip()
    parts = text.split()
    if len(parts) == 1:
        return parts[0]
    return f"{parts[-1]}, {_initials(' '.join(parts[:-1]))}"


def _name_list(values: Any) -> str:
    if not values:
        return ""
    if isinstance(values, (str, Mapping)):
        values = [values]
    names = [name for name in (_one_name(v) for v in values) if name]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]}, & {names[1]}"
    if len(names) <= 20:
        return ", ".join(names[:-1]) + f", & {names[-1]}"
    return ", ".join(names[:19]) + ", ... " + names[-1]


def _date_parts(value: Any) -> list[int]:
    if not isinstance(value, Mapping):
        return []
    raw = value.get("date-parts")
    if not isinstance(raw, Sequence) or not raw:
        return []
    first = raw[0]
    if not isinstance(first, Sequence):
        return []
    out: list[int] = []
    for item in first:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            break
    return out


def _issued_text(entry: Mapping[str, Any]) -> str:
    parts = _date_parts(entry.get("issued"))
    if not parts:
        return "n.d."
    if len(parts) == 1:
        return str(parts[0])
    month = _MONTHS[parts[1] - 1] if 1 <= parts[1] <= 12 else ""
    if len(parts) == 2 or not month:
        return f"{parts[0]}, {month}".rstrip(", ")
    return f"{parts[0]}, {month} {parts[2]}"


def _accessed_text(entry: Mapping[str, Any]) -> str:
    parts = _date_parts(entry.get("accessed"))
    if len(parts) < 3:
        return ""
    month = _MONTHS[parts[1] - 1] if 1 <= parts[1] <= 12 else ""
    if not month:
        return ""
    return f"Retrieved {month} {parts[2]}, {parts[0]}"


def _sentence(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    return value if value.endswith((".", "!", "?")) else value + "."


# -- APA formatter ---------------------------------------------------------

#: Types whose container is a periodical, which APA renders before any
#: publisher and which take volume/issue/page detail.
_PERIODICAL_TYPES = frozenset(
    {"article-journal", "article-newspaper", "article-magazine", "article", "post-weblog"}
)


def format_apa(entry: Mapping[str, Any]) -> str:
    """APA-7-shaped plain text for one CSL-JSON entry.

    This is a deliberate, dependency-free approximation of what ``citation-js``
    plus ``@citation-js/plugin-csl`` produced for the corpus being ported, not a
    CSL processor. It covers the ten CSL ``type`` values and the seventeen
    fields that actually occur in that corpus. Output is plain text because the
    Gatsby component it replaces also rendered plain text (it read
    ``.csl-entry`` ``textContent``, which discarded citeproc's ``<i>`` tags).
    """
    authors = _name_list(entry.get("author"))
    editors = _name_list(entry.get("editor"))
    title = str(entry.get("title") or "").strip()
    container = str(entry.get("container-title") or "").strip()
    publisher = str(entry.get("publisher") or "").strip()
    kind = str(entry.get("type") or "").strip()
    issued = _issued_text(entry)

    chunks: list[str] = []
    if authors:
        chunks.append(_sentence(authors))
        chunks.append(f"({issued}).")
        if title:
            chunks.append(_sentence(title))
    else:
        if title:
            chunks.append(_sentence(title))
        chunks.append(f"({issued}).")

    if container:
        detail = container
        if kind in _PERIODICAL_TYPES:
            volume = str(entry.get("volume") or "").strip()
            issue = str(entry.get("issue") or "").strip()
            page = str(entry.get("page") or "").strip()
            if volume:
                detail += f", {volume}"
                if issue:
                    detail += f"({issue})"
            if page:
                detail += f", {page}"
        chunks.append(_sentence(detail))
    if editors and kind == "chapter":
        chunks.append(_sentence(f"In {editors} (Ed.)"))
    if publisher and publisher != container:
        chunks.append(_sentence(publisher))

    doi = str(entry.get("DOI") or entry.get("doi") or "").strip()
    if doi and not entry.get("URL"):
        chunks.append(f"https://doi.org/{doi.removeprefix('https://doi.org/')}")

    accessed = _accessed_text(entry)
    if accessed and not entry.get("issued"):
        chunks.append(_sentence(accessed))

    return " ".join(chunk for chunk in chunks if chunk).strip()


FORMATTERS: dict[str, CitationFormatter] = {"apa": format_apa}


# -- configuration ---------------------------------------------------------


@dataclass(frozen=True)
class CitationRendering:
    """Configuration for the inline-citation capability.

    Passing an instance of this to ``build_markus_site(citations=...)`` is what
    turns the capability on. Omitting it leaves fragments untouched.
    """

    default_format: str = "apa"
    marker_class: str = "citation"
    list_class: str = "citationslist"
    anchor_prefix: str = "citation-"
    #: Extra or overriding bibliography formatters by ``format`` name.
    formatters: Mapping[str, CitationFormatter] = field(default_factory=dict)
    #: Fail the build on a ``[@key]`` with no matching ``citations:`` entry.
    #: Off leaves the raw text in place.
    strict: bool = True

    def formatter(self, name: str) -> CitationFormatter:
        if name in self.formatters:
            return self.formatters[name]
        if name in FORMATTERS:
            return FORMATTERS[name]
        known = sorted(set(FORMATTERS) | set(self.formatters))
        raise CitationError(
            f"Unknown citation format {name!r}. Known formats: {', '.join(known)}. "
            "Add one via CitationRendering(formatters={...})."
        )


class CitationCollector:
    """Per-page numbering state: first reference order wins, keys dedupe."""

    def __init__(self, entries: Mapping[str, Mapping[str, Any]], config: CitationRendering) -> None:
        self.entries = entries
        self.config = config
        self._order: list[str] = []

    def number_for(self, key: str) -> int | None:
        if key not in self.entries:
            if self.config.strict:
                known = ", ".join(sorted(self.entries)) or "(none)"
                raise CitationError(
                    f"Unknown citation key {key!r}. Declare it in the page's "
                    f"front-matter `citations:` block. Known keys: {known}."
                )
            return None
        if key not in self._order:
            self._order.append(key)
        return self._order.index(key) + 1

    def marker_html(self, key: str) -> str | None:
        number = self.number_for(key)
        if number is None:
            return None
        href = f"#{self.config.anchor_prefix}{number}"
        return (
            f'<span class="{html.escape(self.config.marker_class, quote=True)}">'
            f'<a href="{html.escape(href, quote=True)}">{number}</a></span>'
        )

    def list_html(self, *, fmt: str | None = None) -> str:
        """The end-of-article bibliography, in first-reference order."""
        if not self._order:
            return ""
        formatter = self.config.formatter(fmt or self.config.default_format)
        items: list[str] = []
        for index, key in enumerate(self._order, start=1):
            entry = self.entries[key]
            text = formatter(entry)
            url = str(entry.get("URL") or entry.get("url") or "").strip()
            if url:
                # Parity with gatsby-citation-manager: the URL is stripped out
                # of the formatted text and re-attached as its own link.
                text = text.replace(url, "").strip()
            body = html.escape(text)
            if url:
                safe = html.escape(url, quote=True)
                body = (
                    f"{body} " if body else ""
                ) + f'<a href="{safe}" target="_blank" rel="noopener noreferrer">{html.escape(url)}</a>'
            anchor = html.escape(f"{self.config.anchor_prefix}{index}", quote=True)
            items.append(f'<li id="{anchor}">{body}</li>')
        klass = html.escape(self.config.list_class, quote=True)
        return f'<ol class="{klass}">' + "".join(items) + "</ol>"
