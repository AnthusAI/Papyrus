"""Public wiki pages in the standard front end: the review stamp, the superseded notice and the "suggest an edit" footer.

A wiki page is an item whose type is in ``wiki.types`` (default ``wiki_page``). Above its text the page says who last put
it in front of readers (``Edited by AI on DATE`` or ``Reviewed by NAME on DATE``, from the ``review`` front matter, see
``papyrus_content.wiki_stamp``); a page with no valid stamp says ``Draft, not yet reviewed``. A page whose front matter
names ``superseded_by`` carries a notice that links the replacement. Below the text a footer shows ``Updated DATE``, a
link to the entity's graph JSON when the knowledge snapshot has it, and, when ``wiki.suggestForm`` names a ``forms``
entry, that form behind a disclosure. Nothing here changes a page on submit: the form posts to the public form endpoint.
Every state is stated in words as well as by its mark.
"""

from __future__ import annotations

import datetime as dt
import html
from collections.abc import Mapping

from ...wiki_stamp import SUPERSEDED_KEY, parse_review, stamp_text
from .config import FormSpec, StandardSettings
from .forms import render_form
from .knowledge import entity_file_key

MARKS = {"ai": "✎", "human": "✓", "draft": "○"}
SUPERSEDED_MARK = "✕"


def _q(value) -> str:
    return html.escape(str(value), quote=True)


def is_wiki_entry(entry, settings: StandardSettings) -> bool:
    return entry is not None and entry.type in settings.wiki.types


def replacement_link(front_matter: Mapping, path_for) -> str | None:
    value = front_matter.get(SUPERSEDED_KEY)
    if not isinstance(value, str) or not value.startswith(("/", "https://")):
        return None
    return value if value.startswith("https://") else path_for(value)


def notes(front_matter: Mapping, date_format: str, path_for) -> list[str]:
    """The stamp and the superseded notice as plain lines, for the Markdown twin."""
    review = parse_review(front_matter)
    lines = [stamp_text(review, date_format)]
    link = replacement_link(front_matter, path_for)
    if link:
        lines.append(f"Superseded: this page has been replaced. See {link}")
    return lines


def stamp_html(front_matter: Mapping, date_format: str, path_for) -> str:
    review = parse_review(front_matter)
    state = review.actor if review else "draft"
    text = stamp_text(review, date_format)
    stamp = (
        f'<aside class="papyrus-wiki-stamp" data-state="{state}" aria-label="Review status">'
        f'<p><span class="papyrus-wiki-mark" aria-hidden="true">{MARKS[state]}</span> '
        f'<span class="papyrus-wiki-stamp-text">{_q(text)}</span></p></aside>'
    )
    link = replacement_link(front_matter, path_for)
    if not link:
        return stamp
    return (
        stamp
        + '<aside class="papyrus-wiki-superseded" role="note" aria-label="Superseded page">'
        f'<p><span class="papyrus-wiki-mark" aria-hidden="true">{SUPERSEDED_MARK}</span> '
        f'This page has been superseded. See <a href="{_q(link)}">the replacement page</a>.</p></aside>'
    )


def footer_html(
    entry, front_matter: Mapping, settings: StandardSettings, date_format: str, form: FormSpec | None, entity_keys: set[str], path_for
) -> str:
    parts = []
    if entry.updated:
        shown = dt.date.fromisoformat(entry.updated).strftime(date_format) if date_format else entry.updated
        parts.append(f'<p class="papyrus-wiki-updated">Updated <time datetime="{_q(entry.updated)}">{_q(shown)}</time></p>')
    key = front_matter.get("entityKey")
    if settings.wiki.data_link and isinstance(key, str) and key in entity_keys:
        parts.append(
            f'<p class="papyrus-wiki-data"><a href="{_q(path_for("/" + entity_file_key(key)))}">Data for this page (JSON)</a></p>'
        )
    if form is not None:
        parts.append(f'<details class="papyrus-wiki-suggest"><summary>Suggest an edit</summary>{render_form(form)}</details>')
    return f'<footer class="papyrus-wiki-footer">{"".join(parts)}</footer>' if parts else ""

