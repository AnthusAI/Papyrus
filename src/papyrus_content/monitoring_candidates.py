"""Candidates: one record per canonical URL for the whole monitoring table, whatever found it.

A Hacker News story, an email submission and a web-search hit that share a canonical URL are one candidate
(`CAND#<hash>` / `CAND`). It lists which monitors collected it (`collectedBy`) and every time anything found it
(`provenance[]`: monitor, query, run, score, published date, found-at). Finding a URL again appends provenance; it never
makes a second candidate. Dedupe across sources is this key (docs/search-monitors.md).

The read-modify-write is not atomic: two collectors racing on the same new URL can both collect it, which is the same
at-least-once the per-monitor `ITEM#` records already allow. Imports stay light: stdlib and `monitoring`.
"""
from __future__ import annotations

import hashlib

from .monitoring import canonical_url

CAND_SK = "CAND"
WEB_SEARCH = "web-search"


def url_hash(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()[:40]


def candidate_key(url: str) -> dict:
    return {"pk": f"CAND#{url_hash(url)}", "sk": CAND_SK}


def record_candidate(store, *, url: str, title: str, published_at: str | None, monitor_id: str, source_type: str,
                     group: str, source_id: str, found_at: str, run_id: str, collected: bool,
                     query_id: str | None = None, score_bp: int | None = None) -> dict:
    """Create the candidate or append to it. `collected` says this monitor made a discovery of it (rather than only
    meeting it again). Returns the stored candidate."""
    key = candidate_key(url)
    cand = store.get_raw(key["pk"], key["sk"]) or {**key, "canonicalUrl": canonical_url(url), "title": title,
                                                    "publishedAt": published_at, "firstFoundAt": found_at,
                                                    "collectedBy": [], "provenance": []}
    cand = {k: v for k, v in cand.items() if v is not None}
    entry = {"monitorId": monitor_id, "runId": run_id, "foundAt": found_at,
             **({"queryId": query_id} if query_id else {}), **({"publishedDate": published_at} if published_at else {}),
             **({"tavilyScoreBp": score_bp} if score_bp is not None else {})}
    if not any(p.get("monitorId") == monitor_id and p.get("runId") == run_id and p.get("queryId") == query_id
               for p in cand["provenance"]):
        cand["provenance"] = [*cand["provenance"], entry]
    if collected and not any(c.get("monitorId") == monitor_id for c in cand["collectedBy"]):
        cand["collectedBy"] = [*cand["collectedBy"], {"monitorId": monitor_id, "sourceType": source_type,
                                                     "candidateGroup": group, "sourceId": source_id}]
    store.put_raw(cand)
    return cand


def collected_elsewhere(candidate: dict | None, monitor_id: str, source_type: str, group: str) -> bool:
    """True when this candidate already has a discovery this monitor should not repeat: its own, any other source's, or (for a
    web monitor) another web monitor's in the same `candidateGroup`."""
    for holder in (candidate or {}).get("collectedBy") or []:
        if holder.get("monitorId") == monitor_id or holder.get("sourceType") != source_type:
            return True
        if holder.get("candidateGroup") == group:
            return True
    return False
