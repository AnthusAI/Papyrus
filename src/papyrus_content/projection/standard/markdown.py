"""Agent-readable representations: a Markdown file per page, ``llms.txt`` and ``llms-full.txt``.

Every published page has a Markdown twin next to it (``x.html`` -> ``x.md``, ``x/index.html`` -> ``x/index.md``,
``index.html`` -> ``index.md``) built from the same published content: an article is its front matter facts plus its
Markus source, a listing is a Markdown link list. HTML pages advertise their twin with
``<link rel="alternate" type="text/markdown">``. ``/llms.txt`` follows llmstxt.org (an H1, a blockquote summary and
H2 sections of links to the ``.md`` URLs). ``/llms-full.txt`` is the content concatenated, capped by item count and
bytes. The same eligibility as the sitemap and the feeds applies: only published pages, none for ``noindex`` entries,
none for the 404 page, and no ``llms`` files for a guarded (non-production) environment.

The twin is Markus source: every directive in a body passes through as written (``::image`` with all its attributes,
page blocks, and an island as its ``summary`` text). The ``.md`` extension and ``text/markdown`` type stay, because Markus
is a Markdown superset.
"""

from __future__ import annotations

import re

from ...authors import absolute_author_url, normalize_authors

FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n?", re.S)
LLMS_KEY = "llms.txt"
LLMS_FULL_KEY = "llms-full.txt"
MARKDOWN_TYPE = "text/markdown"


def md_key(html_key: str) -> str | None:
    """The Markdown key of a page key; ``None`` for the 404 page and anything that is not a page."""
    if html_key == "404.html" or not html_key.endswith(".html"):
        return None
    return html_key[: -len(".html")] + ".md"


def md_path(html_key: str) -> str | None:
    """The site path of the Markdown twin of a page key."""
    key = md_key(html_key)
    if key is None:
        return None
    return "/" + key


def static_twin_key(site_path: str) -> str | None:
    """The key of the Markdown twin of a hand-published (``static.copy``) route: ``/docs/x/`` -> ``docs/x/index.md``."""
    if site_path.endswith("/"):
        return site_path.lstrip("/") + "index.md"
    return md_key(site_path.lstrip("/"))


def body_of(source_text: str) -> str:
    """The Markus source of an item without its front matter, every directive as written."""
    return FRONT_MATTER.sub("", source_text, count=1).strip()


def _opens_with_heading(body: str) -> bool:
    """True when the first line of text is an H1; page-block lines (``::band``) before it do not count."""
    for line in body.split("\n"):
        if line.strip() and not line.startswith("::"):
            return line.startswith("# ")
    return False


def _link(origin: str | None, path: str) -> str:
    return (origin or "") + path


def byline_markdown(authors, origin: str | None = None) -> str:
    """Author names, each a Markdown link to the author's url when there is one (made absolute with the site origin)."""
    names = []
    for author in normalize_authors(authors):
        url = absolute_author_url(author.url, origin)
        names.append(f"[{author.name}]({url})" if url else author.name)
    return ", ".join(names)


def item_markdown(entry, source_text: str, canonical: str | None, notes: tuple[str, ...] = (), origin: str | None = None) -> str:
    body = body_of(source_text)
    lines = []
    if not _opens_with_heading(body):
        lines += [f"# {entry.title}", ""]
    facts = []
    if entry.authors:
        facts.append("By " + byline_markdown(entry.authors, origin))
    if entry.date:
        facts.append(f"Published {entry.date}")
    if entry.updated and entry.updated != entry.date:
        facts.append(f"Updated {entry.updated}")
    if entry.summary_text:
        lines += [f"> {entry.summary_text}", ""]
    if facts:
        lines += [" · ".join(facts), ""]
    for note in notes:
        lines += [f"> {note}", ""]
    if canonical:
        lines += [f"Canonical: {canonical}", ""]
    lines.append(body)
    return "\n".join(lines).rstrip() + "\n"


def home_markdown(title: str, description: str, source_text: str) -> str:
    """The home page twin: the Markus source of the home item, with the title and description only where the source lacks them.

    A home page written as page blocks opens with ``::band`` and carries its own H1, so a second title in front of it
    would not be in the source."""
    body = body_of(source_text)
    lines = [] if _opens_with_heading(body) else [f"# {title}", ""]
    if description:
        lines += [f"> {description}", ""]
    return "\n".join(lines + [body]).rstrip() + "\n"


def entry_line(entry, origin: str | None) -> str:
    target = md_path(entry.key) if entry.key else None
    href = _link(origin, target) if target else (entry.link or "")
    detail = f": {entry.summary_text}" if entry.summary_text else ""
    when = f" ({entry.date})" if entry.date else ""
    return f"- [{entry.title}]({href}){detail}{when}"


def listing_markdown(title: str, description: str, entries, origin: str | None, *, page: int = 1, pages: int = 1, page_md=None, note: str = "") -> str:
    lines = [f"# {title}", ""]
    if description:
        lines += [f"> {description}", ""]
    if note:
        lines += [note, ""]
    lines += [entry_line(entry, origin) for entry in entries] or ["_Nothing is published here yet._"]
    if pages > 1 and page_md is not None:
        navigation = [f"Page {page} of {pages}"]
        if page > 1:
            navigation.append(f"[previous]({_link(origin, page_md(page - 1))})")
        if page < pages:
            navigation.append(f"[next]({_link(origin, page_md(page + 1))})")
        lines += ["", " · ".join(navigation)]
    return "\n".join(lines).rstrip() + "\n"


def llms_txt(identity, groups, optional, origin: str | None) -> str:
    """``groups`` is ``[(heading, entries)]``; ``optional`` is ``[(label, path)]`` for secondary links."""
    lines = [f"# {identity.name}", ""]
    summary = identity.description or identity.tagline
    if summary:
        lines += [f"> {summary}", ""]
    for heading, entries in groups:
        if not entries:
            continue
        lines += [f"## {heading}", ""] + [entry_line(entry, origin) for entry in entries] + [""]
    if optional:
        lines += ["## Optional", ""] + [f"- [{label}]({_link(origin, path)})" for label, path in optional] + [""]
    return "\n".join(lines).rstrip() + "\n"


def llms_full_txt(identity, documents, max_bytes: int) -> str:
    """``documents`` is an iterable of Markdown strings; stops before the output would exceed ``max_bytes``."""
    parts = [f"# {identity.name}\n"]
    size = len(parts[0].encode("utf-8"))
    for document in documents:
        piece = "\n---\n\n" + document
        size += len(piece.encode("utf-8"))
        if size > max_bytes:
            parts.append("\n---\n\n_Further content is omitted to keep this file small; see /llms.txt._\n")
            break
        parts.append(piece)
    return "".join(parts)
