"""Which request paths a page is cached under. Pure functions: no AWS, no site.

CloudFront caches by the URL a reader asked for, so ``/dir/`` and ``/dir/index.html`` are two cache entries for one page, and a site with
``urls.style: clean`` also answers ``/x`` for ``x.html``. A purge of one form leaves the other stale (observed 2026-11-08), so every page is
purged under every form it answers to, with its Markdown twin. A wildcard is never produced here.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

URL_STYLES = ("html", "directory", "clean")


class InvalidPagePath(ValueError):
    """A path the operation refuses: empty, a wildcard, or not a site path."""


def _directory_forms(directory: str) -> list[str]:
    """``/a/b/`` as the page of that directory: the slash form, ``index.html`` and the Markdown twin ``index.md``."""
    return [directory, f"{directory}index.html", f"{directory}index.md"]


def clean_site_path(raw: str) -> str:
    """A site path from what an editor typed: a path, or a full URL (scheme, host, query and fragment are dropped)."""
    text = str(raw or "").strip()
    if not text:
        raise InvalidPagePath("A page path is empty.")
    if "*" in text:
        raise InvalidPagePath(f"{text!r} has a wildcard; name the exact pages to refresh.")
    parts = urlsplit(text)
    path = parts.path if (parts.scheme or parts.netloc) else text.split("#", 1)[0].split("?", 1)[0]
    if not path:
        path = "/"
    if not path.startswith("/"):
        path = "/" + path
    return path


def forms_of_path(raw: str) -> list[str]:
    """Every request path one page the editor named is cached under, canonical form first.

    ``/`` and ``/dir/`` and ``/dir/index.html`` and ``/dir/index.md`` are the same page: slash form, ``index.html`` form and Markdown twin.
    ``/x.html`` is also ``/x`` (clean URLs) and ``/x.md``. ``/x.md`` is the twin of ``/x.html``. A bare ``/x`` is a clean page or a directory page
    without its slash, so both are covered.
    """
    path = clean_site_path(raw)
    if path.endswith("/"):
        return _directory_forms(path)
    for name in ("index.html", "index.md"):
        if path == "/" + name or path.endswith("/" + name):
            return _directory_forms(path[: -len(name)])
    if path.endswith(".html"):
        stem = path[: -len(".html")]
        return [path, stem, f"{stem}.md"]
    if path.endswith(".md"):
        stem = path[: -len(".md")]
        return [path, f"{stem}.html", stem]
    return [path, f"{path}.html", f"{path}.md", *_directory_forms(path + "/")]


def expand_site_paths(paths: Iterable[str]) -> list[str]:
    """The exact paths to invalidate for the pages named: every form of every page, without duplicates, in the order given."""
    expanded: list[str] = []
    for raw in paths:
        expanded.extend(forms_of_path(raw))
    return list(dict.fromkeys(expanded))


def paths_for_page_keys(keys: Iterable[str], url_style: str = "html") -> list[str]:
    """The request paths of generated pages, by object key (``a/index.html``, ``a/b.html``, ``a/index.md``).

    Every ``index.html`` page is purged as ``/dir/`` and ``/dir/index.html``; a page ``x.html`` of a ``clean`` site is also ``/x``; other keys
    (including Markdown twins) are purged as ``/key``. A key never yields a wildcard.
    """
    paths: list[str] = []
    for key in keys:
        name = key.rsplit("/", 1)[-1]
        paths.append("/" + key)
        if name == "index.html":
            directory = key[: -len("index.html")]
            paths.append("/" + directory)
        elif url_style == "clean" and key.endswith(".html"):
            paths.append("/" + key[: -len(".html")])
    return list(dict.fromkeys(paths))


def normalize_prefixes(prefixes: Iterable[str]) -> list[str]:
    """URL path prefixes from what an editor typed (a path, or a full URL whose scheme, host, query and fragment are dropped), without duplicates."""
    return list(dict.fromkeys(clean_site_path(prefix) for prefix in prefixes))


def _path_is_under(path: str, prefix: str) -> bool:
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path == prefix or path.startswith(prefix + "/")   # ``/posts`` stops at a path segment: it is not ``/postscript/``


def keys_under(keys: Iterable[str], prefixes: Iterable[str], url_style: str = "html") -> list[str]:
    """The page keys (sorted) any of whose request paths starts with one of the URL path prefixes.

    The match is on the URL path alone: it never looks at what kind of content a page lists, so no site-specific name appears here. A page
    matches when any form it is cached under does (``/dir/`` and ``/dir/index.html`` for ``dir/index.html``).
    """
    wanted = normalize_prefixes(prefixes)
    return sorted(
        {key for key in keys if any(_path_is_under(path, prefix) for path in paths_for_page_keys([key], url_style) for prefix in wanted)}
    )
