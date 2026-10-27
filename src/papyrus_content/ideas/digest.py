"""The digest: a site's recent references, grouped by section and relevance label. Deterministic; no model.

A reference arrives when it is created on the site (``createdAt``). Only current references in the asked-for curation statuses
are read: ``accepted`` by default, because only accepted references are evidence (docs/agent-rules-detail.md). ``pending`` is an
explicit opt-in for a site whose monitor delivers references for review; the digest labels every reference with its status so
nothing downstream mistakes an unreviewed reference for an accepted one.

"Section" for a reference is the knowledge corpus it sits in (a reference has no section of its own); the label is the
Cyclotron relevance label recorded for it (``include``), or ``unlabelled``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from .excerpt import Fetcher, excerpt_for, fetch_html

SCHEMA_VERSION = 1
ACCEPTED, PENDING = "accepted", "pending"
STATUSES = (ACCEPTED, PENDING)
RELEVANCE_PREDICATE = "relevance_decision_is"
RELEVANCE_NODE_PREFIX = "semantic-node-relevance-"
UNLABELLED = "unlabelled"
CORPUS_PREFIX = "knowledge-corpus-"
DEFAULT_WINDOW = "7d"
DEFAULT_MAXIMUM_REFERENCES = 60


def parse_window(value: str | None) -> timedelta:
    match = re.fullmatch(r"(\d{1,4})([dh])", (value or DEFAULT_WINDOW).strip().lower())
    if not match:
        raise ValueError(f"--since must look like 7d or 36h, not {value!r}.")
    amount = int(match.group(1))
    if amount == 0:
        raise ValueError("--since must be longer than zero.")
    return timedelta(days=amount) if match.group(2) == "d" else timedelta(hours=amount)


def parse_statuses(value: str | None) -> list[str]:
    statuses = [part.strip().lower() for part in (value or ACCEPTED).split(",") if part.strip()]
    unknown = [status for status in statuses if status not in STATUSES]
    if not statuses or unknown:
        raise ValueError(f"--status takes {' and/or '.join(STATUSES)} (comma separated), not {value!r}.")
    return list(dict.fromkeys(statuses))


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def corpus_key(corpus_id: str) -> str:
    return corpus_id.removeprefix(CORPUS_PREFIX)


def _metadata(relation: dict[str, Any]) -> dict[str, Any]:
    raw = relation.get("metadata")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _number(value: Any) -> float | None:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def relevance_of(relations: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """The newest current Cyclotron relevance decision among a reference's relations: its label, score and classifier."""
    decisions = [
        relation for relation in relations
        if relation.get("predicate") == RELEVANCE_PREDICATE and relation.get("relationState", "current") == "current"
    ]
    if not decisions:
        return None
    newest = max(decisions, key=lambda relation: str(relation.get("createdAt") or ""))
    node = str(newest.get("objectLineageId") or newest.get("objectId") or "")
    label = node.removeprefix(RELEVANCE_NODE_PREFIX).removesuffix("-v1") if node.startswith(RELEVANCE_NODE_PREFIX) else UNLABELLED
    metadata = _metadata(newest)
    return {
        "label": label or UNLABELLED,
        "score": _number(newest.get("score")),
        "confidence": _number(newest.get("confidence")),
        "classifier": metadata.get("classifier") or metadata.get("cyclotronId"),
        "decidedAt": metadata.get("decidedAt"),
        "positiveLabel": metadata.get("positiveLabel"),
    }


def entities_of(relations: Iterable[dict[str, Any]]) -> list[str]:
    """Semantic nodes the reference points at, other than its relevance label (empty when the site has none)."""
    found = {
        str(relation.get("objectLineageId") or relation.get("objectId"))
        for relation in relations
        if relation.get("objectKind") == "semanticNode"
        and relation.get("predicate") != RELEVANCE_PREDICATE
        and relation.get("relationState", "current") == "current"
        and (relation.get("objectLineageId") or relation.get("objectId"))
    }
    return sorted(found)


def source_of(uri: str | None) -> str | None:
    host = urlsplit(uri or "").hostname
    return host.removeprefix("www.") if host else None


def why_included(reference: dict[str, Any], relevance: dict[str, Any] | None) -> str:
    reason = str(reference.get("curationStatusReason") or "").strip()
    status = reference.get("curationStatus")
    parts = []
    if reason:
        parts.append(reason)
    if relevance:
        score = f", score {relevance['score']}" if relevance.get("score") is not None else ""
        parts.append(f"Relevance classifier {relevance.get('classifier') or 'unknown'} labelled it {relevance['label']}{score}.")
    if status == PENDING:
        parts.append("Not yet reviewed by an editor.")
    return " ".join(parts) or f"Curation status {status}."


def reference_entry(reference: dict[str, Any], relations: list[dict[str, Any]], excerpt: str | None) -> dict[str, Any]:
    relevance = relevance_of(relations)
    authors = reference.get("authors")
    if isinstance(authors, str):
        try:
            authors = json.loads(authors)
        except ValueError:
            authors = []
    return {
        "id": reference["id"],
        "lineageId": reference.get("lineageId"),
        "title": str(reference.get("title") or reference.get("sourceUri") or reference["id"]).strip(),
        "source": source_of(reference.get("sourceUri")),
        "sourceUri": reference.get("sourceUri"),
        "status": reference.get("curationStatus"),
        "arrivedAt": reference.get("createdAt"),
        "section": corpus_key(str(reference.get("corpusId") or "")) or UNLABELLED,
        "label": (relevance or {}).get("label", UNLABELLED),
        "relevance": relevance,
        "entities": entities_of(relations),
        "authors": authors if isinstance(authors, list) else [],
        "summary": excerpt,
        "whyIncluded": why_included(reference, relevance),
    }


def group_references(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Groups by (section, label); the biggest group first, ties by section then label. Members are newest first."""
    members: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in entries:
        members.setdefault((entry["section"], entry["label"]), []).append(entry)
    groups = [
        {"section": section, "label": label, "count": len(rows), "referenceIds": [row["id"] for row in rows]}
        for (section, label), rows in members.items()
    ]
    return sorted(groups, key=lambda group: (-group["count"], group["section"], group["label"]))


def order_references(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(entries, key=lambda entry: (str(entry.get("arrivedAt") or ""), entry["id"]), reverse=True)


def digest_id_for(content: dict[str, Any]) -> str:
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "digest-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]


def build_digest(
    *,
    publication: str,
    entries: list[dict[str, Any]],
    statuses: list[str],
    since: datetime,
    until: datetime,
    considered: int,
    now: datetime,
) -> dict[str, Any]:
    """The digest record. Its id hashes the publication, statuses and references, so the same references give the same digest."""
    ordered = order_references(entries)
    content = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "ideas-digest",
        "publication": publication,
        "window": {"since": iso(since), "until": iso(until)},
        "statuses": statuses,
        "counts": {
            "considered": considered,
            "included": len(ordered),
            "bySection": _count(ordered, "section"),
            "byLabel": _count(ordered, "label"),
            "byStatus": _count(ordered, "status"),
        },
        "groups": group_references(ordered),
        "references": ordered,
    }
    identity = {"publication": publication, "statuses": statuses, "references": ordered}
    return {"digestId": digest_id_for(identity), "generatedAt": iso(now), **content}


def _count(entries: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[str(entry.get(key))] = counts.get(str(entry.get(key)), 0) + 1
    return dict(sorted(counts.items()))


def current_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row and row.get("versionState", "current") == "current"]


def collect_references(client: Any, corpus_ids: list[str], statuses: list[str], since: datetime | None) -> list[dict[str, Any]]:
    """Every current Reference of the corpora in the statuses (each index is paged to the end); with ``since``, only those created at or after it."""
    found: list[dict[str, Any]] = []
    for corpus_id in corpus_ids:
        for status in statuses:
            rows = current_rows(client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#{status}"))
            found.extend(row for row in rows if since is None or (parse_time(row.get("createdAt")) or since) >= since)
    unique = {row["id"]: row for row in found}
    return list(unique.values())


def relations_of(client: Any, reference: dict[str, Any]) -> list[dict[str, Any]]:
    lineage = reference.get("lineageId")
    if not lineage:
        return []
    return list(client.list_semantic_relations_by_subject_state(f"reference#{lineage}#current"))


def make_digest(
    client: Any,
    *,
    publication: str,
    corpus_ids: list[str],
    since: str | None = DEFAULT_WINDOW,
    statuses: list[str] | None = None,
    maximum_references: int = DEFAULT_MAXIMUM_REFERENCES,
    excerpts: bool = False,
    fetch: Fetcher = fetch_html,
    now: datetime | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    window = parse_window(since)
    wanted = statuses or [ACCEPTED]
    rows = order_references(
        [{**row, "arrivedAt": row.get("createdAt"), "id": row["id"]} for row in collect_references(client, corpus_ids, wanted, moment - window)]
    )
    chosen = rows[:maximum_references]
    entries = []
    for row in chosen:
        text = excerpt_for(row["sourceUri"], fetch) if excerpts and row.get("sourceUri") else None
        if on_progress:
            on_progress(row["id"])
        entries.append(reference_entry(row, relations_of(client, row), text))
    return build_digest(
        publication=publication, entries=entries, statuses=wanted, since=moment - window, until=moment, considered=len(rows), now=moment
    )
