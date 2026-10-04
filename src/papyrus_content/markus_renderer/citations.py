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

Behaviours of that package that are deliberately **not** reproduced:

1. It numbered by first *title* match but appended every ``<Citation>`` to the
   list, so two entries sharing a title produced a list item nobody linked to
   and an inline marker pointing at the wrong one. Here a citation is
   identified by its **key**, so repeating a key reuses the number and the
   list has exactly one entry per cited work.
2. Its server-rendered HTML numbers every marker ``0`` and leaves the list
   empty (React fills both in after hydration). This is a build-time formatter
   that emits the final numbers and list, with no runtime JavaScript at all.

Bibliography text is produced by citeproc-py with the APA CSL file that
``citation-js`` bundles; see ``docs/markus-content-markup.md`` ("Formatting").
"""

from __future__ import annotations

import html
import re
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

#: CSL name variables. A *list* of names (CSL name objects or "Given Family"
#: strings) is formatted as live does. A bare *string* is deliberately NOT
#: dropped the way live's citation-js drops it: it is split into people and
#: each is printed as written (a CSL literal name), see ``_split_people``.
_NAME_VARIABLES = ("author", "editor")

_PEOPLE_SEPARATOR = re.compile(r"\s+and\s+|\s+&\s+|;", re.IGNORECASE)


def _split_people(value: str) -> list[Mapping[str, Any]]:
    """``"A and B; C"`` -> three literal names. Commas never split."""
    parts = (part.strip() for part in _PEOPLE_SEPARATOR.split(value))
    return [{"literal": part} for part in parts if part]


def _csl_names(value: Any) -> list[Mapping[str, Any]] | None:
    if isinstance(value, str):
        return _split_people(value)
    if not isinstance(value, list):
        return None
    names: list[Mapping[str, Any]] = []
    for name in value:
        if isinstance(name, str):
            given, _, family = name.strip().rpartition(" ")
            name = {"given": given, "family": family} if given else {"family": family}
        names.append(name)
    return names


# citeproc-js ("title" text-case) splits on these, then capitalises each piece.
_TITLE_DELIMITERS = re.compile(
    "(\u2018|\u2019|\u201c|\u201d| \"| '|\"|'|[-\u2013\u2014/.,;?!:]|\\[|\\]|\\(|\\))"
)
_WHITESPACE = re.compile(r"([ \u00a0\u2000-\u200b\u205f\u3000]+)")
#: citeproc-js's English skip-words list (single-word entries only).
_SKIP_WORDS = frozenset(
    "about above across afore after against al along alongside amid amidst among "
    "amongst anenst apropos apud around as aside astride at athwart atop barring "
    "before behind below beneath beside besides between beyond but by circa despite "
    "down during et except for forenenst from given in inside into lest like modulo "
    "near next notwithstanding of off on onto out over per plus pro qua sans since "
    "than through thru throughout thruout till to toward towards under underneath "
    "until unto up upon versus vs v via with within without or yet so and nor a an "
    "the de von van c ca".split()
)


def _title_case(text: str) -> str:
    """citeproc-js's ``text-case="title"``, which citation-js (live) uses.

    It differs from citeproc-py's version in one way that shows in the corpus:
    the string is first split at ``. , - / : ( )`` and quotes, and every piece
    is capitalised on its own, so ``Data.gov`` becomes ``Data.Gov`` and
    ``X (formerly Twitter)`` becomes ``X (Formerly Twitter)``. A word is only
    capitalised if it is entirely lower case; skip-words ("of", "the") stay
    lower case except first, last, or after ``! ? :``.
    """
    parts = _TITLE_DELIMITERS.split(text)
    strings, tags = parts[0::2], parts[1::2]
    for i, tag in enumerate(tags):
        # citeproc-js keeps an apostrophe attached to the text after it.
        if tag == "'" and strings[i + 1]:
            strings[i + 1] = "'" + strings[i + 1]
            tags[i] = ""
    state = {"first": True, "after_punct": False, "last": None}

    def capitalise(index: int, following_tag: str) -> None:
        if not strings[index].strip():
            return
        pieces = _WHITESPACE.split(strings[index])
        words = range(0, len(pieces), 2)
        last_word = words[-1]
        for j in words:
            word = pieces[j]
            if not word:
                continue
            lower = word.lower()
            capitalize = (
                (len(word) > 1 and lower not in _SKIP_WORDS)
                or (j == last_word and following_tag == "-")
                or state["first"]
                or state["after_punct"]
            )
            if capitalize and word == lower:
                pieces[j] = word[0].upper() + word[1:]
            state.update(first=False, after_punct=False, last=(index, j))
        strings[index] = "".join(pieces)

    if strings[0].strip():
        capitalise(0, tags[0] if tags else "")
    for i, tag in enumerate(tags):
        if re.search(r"[!?:]$", tag):
            state["after_punct"] = True
        capitalise(i + 1, tags[i + 1] if i + 1 < len(tags) else "")
        if strings[i + 1].strip():
            state["first"] = state["after_punct"] = False
    if state["last"] is not None:
        index, j = state["last"]
        pieces = _WHITESPACE.split(strings[index])
        if len(pieces[j]) > 1 and pieces[j].lower() in _SKIP_WORDS:
            pieces[j] = pieces[j][0].upper() + pieces[j][1:]
        strings[index] = "".join(pieces)
    out = [strings[0]]
    for tag, string in zip(tags, strings[1:]):
        out += [tag, string]
    return "".join(out)


_URL = re.compile(r"(https?://\S+)")


def _typography(text: str) -> str:
    """The en-US punctuation citeproc-js applies to formatted text.

    Straight apostrophes and double quotes become typographic, a "." or ","
    after a closing quote moves inside it, and a "." never follows "?" or "!".
    URLs are left alone. Covers what the corpus uses, not all of citeproc-js's
    quote handling.
    """

    def fix(piece: str) -> str:
        piece = piece.replace("'", "\u2019")
        piece = re.sub(r'"([^"]*)"', "\u201c\\1\u201d", piece)
        piece = re.sub(r"\u201d([.,])", "\\1\u201d", piece)
        return re.sub(r"(?<=[?!])\.(?=\s|$)", "", piece)

    pieces = _URL.split(text)
    return "".join(p if i % 2 else fix(p) for i, p in enumerate(pieces))


@lru_cache(maxsize=None)
def _patch_citeproc() -> None:
    """Make a substituted macro suppress the variables it rendered.

    CSL says a variable rendered inside ``<substitute>`` is suppressed in the
    rest of the entry. citeproc-py only records a substituted child's own
    ``variable`` attribute, so a substituted *macro* suppresses nothing. This
    records the variables that were actually rendered instead. APA
    substitutes its ``title`` macro for a missing author, which made every
    authorless entry print its title twice ("T. (n.d.). T. Site."), where
    citeproc-js (what citation-js uses) prints it once.
    """
    from citeproc.model import Substitute, Text

    recording: list[list[tuple[str, str]]] = []
    original_variable = Text._variable
    original_render = Substitute.render

    def _variable(self: Any, item: Any, context: Any) -> Any:
        text = original_variable(self, item, context)
        if text and recording:
            recording[-1].append((self.tag, self.get("variable")))
        return text

    def render(self: Any, item: Any, context: Any = None, **kwargs: Any) -> Any:
        recording.append([])
        try:
            text = original_render(self, item, context=context, **kwargs)
        finally:
            used = recording.pop()
        if text:
            repressed = context.get_layout().repressed
            for tag, variable in used:
                repressed.setdefault(tag, []).append(variable)
        return text

    Text._variable = _variable
    Substitute.render = render

    from citeproc.model import TextCased

    original_case = TextCased.case

    def case(self: Any, text: Any, language: Any = None) -> Any:
        if self.get("text-case") == "title" and language == "en":
            return _title_case(str(text))
        return original_case(self, text, language)

    TextCased.case = case


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

    # citeproc-py wants strings for number-like fields; YAML parses ``volume: 162``
    # as an int.
    item = {
        k: str(v) if isinstance(v, int) and not isinstance(v, bool) else v
        for k, v in entry.items()
        if k not in ("id", "keywords")
    }
    for name_variable in _NAME_VARIABLES:
        names = _csl_names(item.pop(name_variable, None))
        if names:
            item[name_variable] = names
    item["id"] = "entry"
    bibliography = CitationStylesBibliography(
        _style(str(style_path)), CiteProcJSON([item]), formatter.plain
    )
    bibliography.register(Citation([CitationItem("entry")]))
    text = "".join(str(rendered) for rendered in bibliography.bibliography())
    return _typography(text)


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
                # Parity with gatsby-citation-manager, byte for byte: the first
                # occurrence of the URL is cut out of the formatted text (which
                # leaves any space before it) and the URL is appended as its
                # own link with nothing in between.
                text = text.replace(url, "", 1)
            body = html.escape(text, quote=False)
            if url:
                safe = html.escape(url, quote=True)
                body += (
                    f'<a href="{safe}" target="_blank" '
                    f'rel="noopener noreferrer">{html.escape(url, quote=False)}</a>'
                )
            anchor = html.escape(f"{self.config.anchor_prefix}{index}", quote=True)
            items.append(f'<li id="{anchor}">{body}</li>')
        klass = html.escape(self.config.list_class, quote=True)
        return f'<ol class="{klass}">' + "".join(items) + "</ol>"
