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
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping

CitationFormatter = Callable[[Mapping[str, Any]], str]


class CitationError(RuntimeError):
    """Raised for an unknown citation key or an unsupported format."""


# -- CSL formatting --------------------------------------------------------

#: The exact style file ``citation-js`` (``@citation-js/plugin-csl`` 0.7.14)
#: bundles as its ``apa`` template, i.e. what the live Gatsby site formats
#: with. Copied verbatim; see ``csl/README.md`` for provenance and license.
APA_STYLE_PATH = Path(__file__).with_name("csl") / "apa.csl"

#: CSL name variables. ``citation-js`` accepts a *list* of names, each either a
#: CSL name object or a plain "Given Family" string, and silently discards any
#: other value, including a bare string such as ``"A. Author and B. Author"``
#: (the entry then renders without an author). The live site did exactly that,
#: so this does too.
_NAME_VARIABLES = ("author", "editor")


def _csl_names(value: Any) -> list[Mapping[str, Any]] | None:
    if not isinstance(value, list):
        return None
    names: list[Mapping[str, Any]] = []
    for name in value:
        if isinstance(name, str):
            given, _, family = name.strip().rpartition(" ")
            name = {"given": given, "family": family} if given else {"family": family}
        names.append(name)
    return names


@lru_cache(maxsize=None)
def _patch_citeproc() -> None:
    """Make ``<substitute><text macro=.../>`` suppress the variables it used.

    CSL says a variable rendered inside ``<substitute>`` is suppressed in the
    rest of the entry. citeproc-py only records a substituted child's own
    ``variable`` attribute, so a substituted *macro* suppresses nothing. APA
    substitutes its ``title`` macro for a missing author, which made every
    authorless entry print its title twice ("T. (n.d.). T. Site."), where
    citeproc-js (what citation-js uses) prints it once.
    """
    from citeproc.model import Substitute

    original = Substitute.add_to_repressed_list

    def add_to_repressed_list(self: Any, child: Any, context: Any) -> None:
        original(self, child, context)
        macro = child.get("macro")
        if macro is None:
            return
        repressed = context.get_layout().repressed
        for element in child.get_macro(macro).iter():
            variable = element.get("variable")
            if variable is not None:
                repressed.setdefault(element.tag, []).append(variable)

    Substitute.add_to_repressed_list = add_to_repressed_list


@lru_cache(maxsize=None)
def _style(path: str) -> Any:
    from citeproc import CitationStylesStyle

    _patch_citeproc()
    return CitationStylesStyle(path, validate=False)


def _format_csl(entry: Mapping[str, Any], style_path: Path) -> str:
    """One bibliography entry as plain text, formatted by citeproc.

    Each entry is formatted on its own, exactly as ``CitationsList`` did with
    one ``new Cite(entry)`` per list item, so cross-entry behaviour (sorting,
    year suffixes, "et al." disambiguation) never applies.
    """
    # Imported here so a publication that never formats a citation (Pilobol.us)
    # does not need citeproc-py installed just to import the renderer.
    from citeproc import Citation, CitationItem, CitationStylesBibliography, formatter
    from citeproc.source.json import CiteProcJSON

    item = {k: v for k, v in entry.items() if k not in ("id", "keywords")}
    for name_variable in _NAME_VARIABLES:
        names = _csl_names(item.pop(name_variable, None))
        if names:
            item[name_variable] = names
    item["id"] = "entry"
    bibliography = CitationStylesBibliography(
        _style(str(style_path)), CiteProcJSON([item]), formatter.plain
    )
    bibliography.register(Citation([CitationItem("entry")]))
    return "".join(str(rendered) for rendered in bibliography.bibliography()).strip()


def format_apa(entry: Mapping[str, Any]) -> str:
    """APA 7 plain text for one CSL-JSON entry, via citeproc and the CSL style.

    Output is plain text because the Gatsby component this replaces read
    ``.csl-entry`` ``textContent``, which discarded citeproc's ``<i>`` tags.
    """
    return _format_csl(entry, APA_STYLE_PATH)


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
