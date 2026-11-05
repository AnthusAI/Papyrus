"""One identity gate for References: when two rows are the same document.

``identity_keys(reference)`` returns the stable keys a row answers to. Two References that share a key are the same document, whatever
corpus they sit in. A key is one of:

* ``url:<host>/<path>[?<query>]`` the canonical URL (see ``canonical_url_key``);
* ``arxiv:<id>`` an arXiv paper, from its abs, pdf, html or format address, a version suffix removed, or from its ``10.48550/arXiv.<id>`` DOI;
* ``doi:<doi>`` a DOI, from a doi.org address, a ``/doi/`` publisher path, or the ``doi`` field of the row, lower-cased;
* ``text:<sha256>`` the hash of the captured text, only when the row carries ``capturedTextSha256`` and its ``captureState`` is ``full``.

The same title is not identity: ``title_candidate_key`` exists for the duplicates report, which counts same-title groups as candidates only.

Pure and stdlib-only: the router, the editor intake Lambda and the command line all import it, and a module added to the router's import closure
must load from the zip alone (procedures/newsroom/tests/test_research_assignments_worker.py).
"""
from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from .monitoring import canonical_url

ARXIV_HOSTS = {"arxiv.org", "export.arxiv.org", "ar5iv.org", "ar5iv.labs.arxiv.org", "alphaxiv.org"}
_ARXIV_NEW = r"\d{4}\.\d{4,5}"
_ARXIV_OLD = r"[a-z\-]+(?:\.[A-Za-z]{2})?/\d{7}"
_ARXIV_PATH = re.compile(rf"^/(?:abs|pdf|html|format|ar5iv/abs|ar5iv/html)/((?:{_ARXIV_NEW})|(?:{_ARXIV_OLD}))(?:v\d+)?(?:\.pdf)?/?$", re.IGNORECASE)
_ARXIV_DOI = re.compile(rf"^10\.48550/arxiv\.((?:{_ARXIV_NEW})|(?:{_ARXIV_OLD}))(?:v\d+)?$", re.IGNORECASE)
_DOI = re.compile(r"^10\.\d{4,9}/\S+$")
_DOI_IN_PATH = re.compile(r"/doi/(?:(?:abs|pdf|full|epdf|book|pdfdirect)/)?(10\.\d{4,9}/[^\s?#]+)", re.IGNORECASE)
_DOI_PREFIX = re.compile(r"^(?:doi:|https?://(?:dx\.)?doi\.org/)", re.IGNORECASE)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DEFAULT_PORTS = {"http": 80, "https": 443}
_TITLE_WORDS = re.compile(r"[^\W_]+", re.UNICODE)


def canonical_url_key(value: Any) -> str | None:
    """The URL key of an address, or None when it is not an HTTP(S) address.

    Starts from ``monitoring.canonical_url`` (scheme and host lower-cased, fragment dropped, tracking parameters dropped) and then
    also ignores what ``reference_intake_validation.canonical_source_url`` removes and the older monitor key keeps: the default port, and an
    internationalised host spelled in Unicode versus punycode. It additionally treats these as the same address: http and https, a leading
    ``www.``, a trailing slash on the path, and the order of query parameters.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        text = canonical_url(value)
        parts = urlsplit(text)
        host = (parts.hostname or "").encode("idna").decode("ascii").lower()
        port = parts.port
    except (ValueError, UnicodeError):
        return None
    if host.startswith("www."):
        host = host[4:]
    if ":" in host:
        host = f"[{host}]"
    if port is not None and port != _DEFAULT_PORTS[parts.scheme]:
        host += f":{port}"
    path = parts.path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return f"url:{host}{path}" + (f"?{query}" if query else "")


def arxiv_id(value: Any) -> str | None:
    """The versionless arXiv id of an arXiv address or arXiv DOI, lower-cased, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    doi = _ARXIV_DOI.match(_DOI_PREFIX.sub("", text))
    if doi:
        return doi.group(1).lower()
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if host.startswith("www."):
        host = host[4:]
    if host not in ARXIV_HOSTS:
        return None
    match = _ARXIV_PATH.match(unquote(parts.path))
    return match.group(1).lower() if match else None


def doi_of(value: Any) -> str | None:
    """The lower-cased DOI of a DOI, a ``doi:`` string, a doi.org address, or a publisher address with a ``/doi/`` path, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    bare = _DOI_PREFIX.sub("", text)
    if bare != text:
        candidate = unquote(urlsplit(text).path.lstrip("/")) if text.lower().startswith("http") else bare
        return _clean_doi(candidate)
    if _DOI.match(text):
        return _clean_doi(text)
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    found = _DOI_IN_PATH.search(unquote(parts.path))
    return _clean_doi(found.group(1)) if found else None


def _clean_doi(value: str) -> str | None:
    doi = value.strip().rstrip(").,;/").lower()
    return doi if _DOI.match(doi) else None


def identity_keys(reference: dict[str, Any]) -> set[str]:
    """Every identity key of a Reference row (or of a candidate shaped like one: ``sourceUri``, ``source_uri`` or ``url``, optional ``doi``, ``capturedTextSha256``, ``captureState``)."""
    keys: set[str] = set()
    for address in (reference.get("sourceUri"), reference.get("source_uri"), reference.get("url")):
        url = canonical_url_key(address)
        if url:
            keys.add(url)
        paper = arxiv_id(address)
        if paper:
            keys.add(f"arxiv:{paper}")
        doi = doi_of(address)
        if doi:
            keys.add(f"doi:{doi}")
    declared = reference.get("doi")
    declared_doi = doi_of(declared)
    if declared_doi:
        keys.add(f"doi:{declared_doi}")
        paper = arxiv_id(f"doi:{declared_doi}")
        if paper:
            keys.add(f"arxiv:{paper}")
    for key in list(keys):
        if key.startswith("doi:"):
            paper = arxiv_id(key[4:])
            if paper:
                keys.add(f"arxiv:{paper}")
    digest = reference.get("capturedTextSha256")
    if isinstance(digest, str) and _SHA256.match(digest.lower()) and reference.get("captureState") == "full":
        keys.add(f"text:{digest.lower()}")
    return keys


def title_candidate_key(reference: dict[str, Any]) -> str | None:
    """A case, punctuation and spacing blind title; None for a missing title or one that is only an address. Never identity."""
    title = reference.get("title")
    if not isinstance(title, str):
        return None
    stripped = title.strip()
    if not stripped or re.match(r"^https?://\S+$", stripped):
        return None
    words = _TITLE_WORDS.findall(stripped.casefold())
    return " ".join(words) if words else None


def is_current(row: dict[str, Any]) -> bool:
    return row.get("versionState") in {None, "current"}


class IdentityIndex:
    """The current References of a publication, looked up by identity key. Publication scope: rows of every corpus are held.

    Built from the listing a writer already has; it reads nothing and writes nothing.
    """

    def __init__(self, references: Iterable[dict[str, Any]] = ()):
        self._by_key: dict[str, list[dict[str, Any]]] = {}
        for row in references:
            self.add(row)

    def add(self, row: dict[str, Any]) -> None:
        if not is_current(row):
            return
        for key in identity_keys(row):
            self._by_key.setdefault(key, []).append(row)

    def hits(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        """Distinct existing rows sharing any identity key with the candidate."""
        found: dict[str, dict[str, Any]] = {}
        for key in identity_keys(candidate):
            for row in self._by_key.get(key, ()):
                found.setdefault(str(row.get("id")), row)
        return list(found.values())

    def existing_for(self, candidate: dict[str, Any], *, corpus_id: str | None = None) -> dict[str, Any] | None:
        return choose_existing(self.hits(candidate), corpus_id=corpus_id)


_STATUS_RANK = {"accepted": 0, "pending": 1}


def choose_existing(hits: list[dict[str, Any]], *, corpus_id: str | None = None) -> dict[str, Any] | None:
    """The row a duplicate should point at: the caller's own corpus first, then accepted, then pending, then the oldest, then the lowest id."""
    if not hits:
        return None
    return min(hits, key=lambda row: (row.get("corpusId") != corpus_id,
                                      _STATUS_RANK.get(str(row.get("curationStatus") or "pending"), 2),
                                      str(row.get("createdAt") or ""), str(row.get("id") or "")))


def identity_groups(references: Iterable[dict[str, Any]], *, kinds: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Groups of current References that share an identity key, joined transitively (a URL row and a DOI row join through an arXiv row).

    Each group: ``members`` (the rows, ordered by creation time then id) and ``keys`` (the shared keys that joined them, by kind).
    Single rows are not groups. ``kinds`` (``url``, ``arxiv``, ``doi``, ``text``) limits the keys that join rows.
    """
    wanted = tuple(f"{kind}:" for kind in kinds) if kinds is not None else None
    rows = [row for row in references if is_current(row)]
    parent = list(range(len(rows)))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    holders: dict[str, list[int]] = {}
    for position, row in enumerate(rows):
        for key in identity_keys(row):
            if wanted is None or key.startswith(wanted):
                holders.setdefault(key, []).append(position)
    for positions in holders.values():
        for other in positions[1:]:
            parent[find(other)] = find(positions[0])
    grouped: dict[int, list[int]] = {}
    for position in range(len(rows)):
        grouped.setdefault(find(position), []).append(position)
    groups = []
    for positions in grouped.values():
        if len(positions) < 2:
            continue
        members = sorted((rows[p] for p in positions), key=lambda row: (str(row.get("createdAt") or ""), str(row.get("id") or "")))
        shared = sorted(key for key, held in holders.items() if len(held) > 1 and held[0] in positions)
        groups.append({"members": members, "keys": shared})
    return sorted(groups, key=lambda group: str(group["members"][0].get("id") or ""))


def existing_row_summary(row: dict[str, Any], *, action: str = "existing", **extra: Any) -> dict[str, Any]:
    """What a writer reports for a candidate that matched an existing Reference: where it is and its status, never a change to it."""
    return {"referenceId": row.get("id"), "lineageId": row.get("lineageId"), "corpusId": row.get("corpusId"),
            "status": row.get("curationStatus") or "pending", "title": row.get("title"), "action": action, **extra}


def split_by_identity(index: IdentityIndex, items: list[dict[str, Any]], *, corpus_id: str | None = None,
                      status: str | None = None, reimport_lineage_of=None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Catalog items (``source_uri``, optional ``doi``) that are new, and the report rows of those that are not.

    An item that shares an identity key with an existing current Reference, in any corpus, is not new; neither is one that shares a key with an
    earlier item of this same batch. Nothing is written and no existing row changes. ``reimport_lineage_of(item)`` names the lineage an explicit
    re-import of the item would update; an item whose every hit is that lineage passes through, unless it would turn a decided Reference back to
    ``pending`` (``status``), which never happens.
    """
    fresh: list[dict[str, Any]] = []
    reported: list[dict[str, Any]] = []
    batch: dict[str, dict[str, Any]] = {}
    for item in items:
        hits = index.hits(item)
        if hits and reimport_lineage_of is not None:
            lineage = reimport_lineage_of(item)
            if all(row.get("lineageId") == lineage for row in hits) and not (
                    status == "pending" and any(str(row.get("curationStatus") or "pending") != "pending" for row in hits)):
                fresh.append(item)
                continue
        if hits:
            chosen = choose_existing(hits, corpus_id=corpus_id)
            reported.append(existing_row_summary(chosen, url=item.get("source_uri") or item.get("url")))
            continue
        keys = identity_keys(item)
        earlier = next((batch[key] for key in sorted(keys) if key in batch), None)
        if earlier is not None:
            reported.append({"referenceId": None, "status": "new", "title": item.get("title"), "action": "duplicate-in-batch",
                             "url": item.get("source_uri") or item.get("url"), "sameAs": earlier.get("source_uri") or earlier.get("url")})
            continue
        for key in keys:
            batch[key] = item
        fresh.append(item)
    return fresh, reported
