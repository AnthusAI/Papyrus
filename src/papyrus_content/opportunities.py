"""Find public X conversations worth an editor's review; never write to X."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
TOKEN_ENV = "PAPYRUS_X_BEARER_TOKEN"


class PilotError(Exception):
    pass


def required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PilotError(f"{field} must be a nonempty string")
    return value.strip()


def https_url(value: object, field: str) -> str:
    url = required_string(value, field)
    try:
        parts = urlsplit(url)
        valid = parts.scheme == "https" and parts.hostname and not parts.username and not parts.password
    except ValueError:
        valid = False
    if not valid or any(char.isspace() or ord(char) < 32 for char in url):
        raise PilotError(f"{field} must be an HTTPS URL without credentials")
    return url


@dataclass(frozen=True)
class Reference:
    title: str
    url: str
    query: str
    keywords: tuple[str, ...]
    contribution: str
    public_note_url: str | None
    evidence: str | None

    @classmethod
    def parse(cls, raw: object) -> Reference:
        if not isinstance(raw, Mapping):
            raise PilotError("each Reference must be an object")
        keywords = raw.get("keywords")
        if not isinstance(keywords, list) or not keywords:
            raise PilotError("each Reference needs at least one matching keyword or phrase")
        note = raw.get("public_note_url")
        evidence = raw.get("evidence")
        return cls(
            required_string(raw.get("title"), "title"),
            https_url(raw.get("url"), "url"),
            required_string(raw.get("query"), "query"),
            tuple(dict.fromkeys(required_string(word, "keyword").casefold() for word in keywords)),
            required_string(raw.get("contribution"), "contribution"),
            https_url(note, "public_note_url") if note is not None else None,
            required_string(evidence, "evidence") if evidence is not None else None,
        )


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def search_x(query: str, count: int, token: str) -> object:
    params = urlencode({
        "query": query,
        "max_results": count,
        "post.fields": "conversation_id,created_at,entities",
    })
    request = Request(f"{SEARCH_URL}?{params}", method="GET", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    try:
        with build_opener(NoRedirects()).open(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as error:
        # Do not include headers, response text or a credential in a diagnostic.
        error.close()
        raise PilotError(f"X Recent Search returned HTTP {error.code}; no automatic retry") from None
    except (URLError, OSError, ValueError):
        raise PilotError("X Recent Search failed; no automatic retry") from None


def load_input(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise PilotError(f"could not read JSON from {path}") from None


def ids_and_text(row: object) -> tuple[str, str, str] | None:
    if not isinstance(row, Mapping):
        return None
    post_id = row.get("id")
    conversation_id = row.get("conversation_id") or post_id
    content = row.get("text")
    if not all(isinstance(item, str) and re.fullmatch(r"[0-9]{1,20}", item) for item in (post_id, conversation_id)):
        return None
    if not isinstance(content, str) or not content.strip():
        return None
    return post_id, conversation_id, content


def comparison_url(url: str) -> tuple:
    result = urlsplit(url)
    query = tuple(sorted((key, value) for key, value in parse_qsl(result.query, keep_blank_values=True)
                         if not key.casefold().startswith("utm_")))
    return (result.hostname or "").removeprefix("www."), result.path.rstrip("/"), query


def cited_urls(row: Mapping) -> set[tuple]:
    entities = row.get("entities")
    entries = entities.get("urls", []) if isinstance(entities, Mapping) else []
    if not isinstance(entries, list):
        return set()
    urls = set()
    for entry in entries:
        if isinstance(entry, Mapping):
            for key in ("unwound_url", "expanded_url"):
                url = entry.get(key)
                if isinstance(url, str):
                    try:
                        urls.add(comparison_url(url))
                    except ValueError:
                        pass  # An invalid URL cannot match a valid source.
    return urls


def find_opportunities(references, read_limit, candidate_limit, fetch, price=None):
    groups = {}
    for ref in references:
        groups.setdefault(ref.query, []).append(ref)
    if read_limit < 10 * len(groups):
        raise PilotError("X requires at least 10 results per query; increase --max-reads or use fewer distinct queries")
    per_query = min(100, read_limit // len(groups))
    reads = 0
    search_receipts = []
    matches = {}
    for query, refs in groups.items():
        payload = fetch(query, per_query)
        if not isinstance(payload, Mapping) or payload.get("errors"):
            raise PilotError("search returned an error or unexpected JSON; no automatic retry")
        rows = payload.get("data", [])
        if not isinstance(rows, list) or len(rows) > per_query:
            raise PilotError("search returned an invalid or over-budget post list")
        reads += len(rows)
        meta = payload.get("meta")
        search_receipts.append({"query": query, "post_reads": len(rows),
                                "more_available": bool(meta.get("next_token") or meta.get("more_available")) if isinstance(meta, Mapping) else False})
        for row in rows:
            post = ids_and_text(row)
            if post is None:
                continue
            post_id, thread_id, content = post
            folded = content.casefold()
            already_cited = cited_urls(row)
            for ref in refs:
                matched = [phrase for phrase in ref.keywords if re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", folded)]
                if not matched or any(comparison_url(url) in already_cited or url.casefold() in folded
                                      for url in (ref.url, ref.public_note_url) if url):
                    continue
                if ref.contribution.casefold() in folded:
                    continue
                rank = (len(matched), post_id == thread_id, int(post_id))
                if thread_id in matches and rank <= matches[thread_id][0]:
                    continue
                matches[thread_id] = rank, {
                    "target_url": f"https://x.com/i/web/status/{post_id}",
                    "thread_url": f"https://x.com/i/web/status/{thread_id}",
                    "post_text": content,
                    "matched_keywords": matched,
                    "reference_title": ref.title,
                    "source_url": ref.url,
                    "share_url": ref.public_note_url or ref.url,
                    "contribution_to_review": ref.contribution,
                    "supporting_passage": ref.evidence,
                }
    return {
        "review_required": "Open the thread and check its current context before deciding whether to post.",
        "post_reads": reads,
        "requested_post_limit": per_query * len(groups),
        "estimated_usd": str(price * reads) if price is not None else None,
        "searches": search_receipts,
        "opportunities": [entry for _, entry in sorted(matches.values(), key=lambda pair: pair[0], reverse=True)[:candidate_limit]],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--references", type=Path, required=True, help="JSON list of curated References and search criteria")
    parser.add_argument("--posts", type=Path, help="offline JSON object keyed by exact X query, with search response values")
    parser.add_argument("--max-reads", type=int, required=True, help="overall cap on X posts requested")
    parser.add_argument("--max-candidates", type=int, default=5, help="maximum review candidates to show (default: 5)")
    parser.add_argument("--price-per-read", help="optional USD per post for an estimate, not a billing receipt")
    args = parser.parse_args(argv)
    try:
        refs = load_input(args.references)
        if not isinstance(refs, list) or not refs:
            raise PilotError("--references must be a nonempty JSON list")
        references = [Reference.parse(row) for row in refs]
        if args.max_reads < 1 or args.max_candidates < 1:
            raise PilotError("read and candidate limits must be positive")
        price = None
        if args.price_per_read is not None:
            try:
                price = Decimal(args.price_per_read)
            except InvalidOperation:
                raise PilotError("--price-per-read must be a nonnegative USD amount") from None
            if not price.is_finite() or price < 0:
                raise PilotError("--price-per-read must be a nonnegative USD amount")
        if args.posts:
            recorded = load_input(args.posts)
            if not isinstance(recorded, Mapping):
                raise PilotError("--posts must be a JSON object keyed by exact query")

            def fetch(query, _count):
                if query not in recorded:
                    raise PilotError("offline search input is missing a configured query")
                return recorded[query]
        else:
            token = os.environ.get(TOKEN_ENV, "").strip()
            if not token:
                raise PilotError(f"supply {TOKEN_ENV} securely for live read-only search, or use --posts")

            def fetch(query, count):
                return search_x(query, count, token)
        result = find_opportunities(references, args.max_reads, args.max_candidates, fetch, price)
        result["mode"] = "offline" if args.posts else "live"
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except PilotError as error:
        print(f"opportunities: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
