"""Topic modeling on recent References (``topics_model``; docs/topics.md).

1. Read the References of the window, and of the previous window of the same length, through the source-date index (``select.py``).
2. Model both windows together in one pass, so that one topic means the same thing in both, then count each topic's members in each window.
3. Mark each topic rising, falling or steady by comparing its share of the current window with its share of the previous one (a two-proportion
   z-test, the usual 95 percent). A topic with nothing in the previous window is new.
4. Keep the record under a saved id that is a hash of the question, the engine and the exact Reference versions, and print the compact form.

The text of a Reference is its title and the summary held on its row (``cardSummary``). The engine sees nothing else.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from .engine import TopicDocument, TopicEngine
from .select import DEFAULT_STATES, Selection, select_references
from .store import TopicStore
from .windows import Window, current_window, previous_window

MARKS = {"rising": "▲", "falling": "▼", "steady": "=", "new": "+"}
LEGEND = {"rising": "▲ rising: a larger share of the window than before", "falling": "▼ falling: a smaller share than before",
          "steady": "= steady: no clear change", "new": "+ new: nothing like it in the previous window"}
Z_95 = 1.96
MINIMUM_CLUSTER = 3   # a pair is not a cluster
DEFAULT_REPRESENTATIVES = 3


@dataclass(frozen=True)
class TopicParams:
    corpus_id: str
    window: str = "14d"
    as_of: date | None = None
    section_id: str | None = None
    monitor: str | None = None
    states: tuple[str, ...] = DEFAULT_STATES
    min_cluster_size: int | None = None
    compare: bool = True
    max_references: int | None = None
    representatives: int = DEFAULT_REPRESENTATIVES
    refresh: bool = False


@dataclass(frozen=True)
class TopicOutcome:
    result: dict
    warnings: tuple[dict, ...] = field(default_factory=tuple)


def scaled_cluster_size(count: int) -> int:
    """The smallest topic worth reporting for this many References: the square root of the count, never under three."""
    return max(MINIMUM_CLUSTER, round(math.sqrt(count)))


def reference_key(row: dict) -> str:
    return str(row.get("lineageId") or row["id"])


def reference_text(row: dict) -> str:
    return "\n".join(part for part in (str(row.get("title") or "").strip(), str(row.get("cardSummary") or "").strip()) if part)


def trend(current: int, previous: int, current_total: int, previous_total: int) -> str:
    """How a topic's share of the current window compares with its share of the previous window."""
    if previous == 0:
        return "new" if current else "steady"
    pooled = (current + previous) / (current_total + previous_total)
    error = math.sqrt(pooled * (1 - pooled) * (1 / current_total + 1 / previous_total))
    if error == 0:
        return "steady"
    z = (current / current_total - previous / previous_total) / error
    return "rising" if z >= Z_95 else "falling" if z <= -Z_95 else "steady"


def cache_key(params: TopicParams, engine: TopicEngine, windows: list[Window], selected: list[Selection], min_cluster_size: int) -> str:
    versions = sorted(f"{row['id']}@{row.get('updatedAt') or ''}" for selection in selected for row in selection.rows)
    question = {
        "corpus": params.corpus_id, "windows": [window.describe() for window in windows], "section": params.section_id, "monitor": params.monitor,
        "states": sorted(params.states), "minClusterSize": min_cluster_size, "engine": [engine.name, engine.version], "versions": versions,
    }
    return "topics-" + hashlib.sha256(json.dumps(question, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def compact(record: dict) -> dict:
    """The record without member lists: what the command prints."""
    return {**record, "topics": [{key: value for key, value in topic.items() if key != "memberIds"} for topic in record["topics"]]}


def example(row: dict) -> dict:
    return {"id": row["id"], "lineageId": reference_key(row), "title": row.get("title") or "", "sourceUri": row.get("sourceUri") or "",
            "sourcePublishedAt": row.get("sourcePublishedAt") or "", "state": row.get("curationStatus") or "pending"}


def run_topics(client: Any, params: TopicParams, *, engine: TopicEngine, store: TopicStore, today: date | None = None) -> TopicOutcome:
    now = current_window(params.window, params.as_of or today or datetime.now(timezone.utc).date())
    windows = [now] + ([previous_window(now)] if params.compare else [])
    selected = [select_references(client, params.corpus_id, window, states=params.states, section_id=params.section_id, monitor=params.monitor,
                                  max_references=params.max_references) for window in windows]
    warnings = [warning for selection in selected for warning in selection.warnings]
    rows: dict[str, dict] = {}
    in_window: list[set[str]] = []
    for selection in selected:
        keys = set()
        for row in selection.rows:
            key = reference_key(row)
            if reference_text(row):
                rows.setdefault(key, row)
                keys.add(key)
        in_window.append(keys)
    modeled = sorted(rows)
    size = params.min_cluster_size or scaled_cluster_size(len(modeled))
    saved_id = cache_key(params, engine, windows, selected, size)
    if not params.refresh and (kept := store.get(saved_id)):
        return TopicOutcome({**compact(kept), "cached": True}, tuple(warnings))

    topics_found = []
    if len(modeled) < 2 * size:
        warnings.append({"code": "too_few_references", "message": f"{len(modeled)} References in the windows is too few for topics of at least {size}."})
    else:
        topics_found = engine.model([TopicDocument(key, reference_text(rows[key])) for key in modeled], min_cluster_size=size)
    current_keys = in_window[0]
    previous_keys = in_window[1] if params.compare else set()
    topics = []
    for found in topics_found:
        members = set(found.member_ids)
        count, before = len(members & current_keys), len(members & previous_keys)
        if not count:
            continue
        entry = {"label": found.label, "terms": list(found.terms), "count": count,
                 "references": [example(row) for row in sorted((rows[key] for key in members & current_keys),
                                                               key=lambda row: (str(row.get("sourcePublishedAt") or ""), reference_key(row)), reverse=True)[:params.representatives]],
                 "memberIds": sorted(members & current_keys)}
        if params.compare and previous_keys and current_keys:
            entry.update(previousCount=before, trend=(word := trend(count, before, len(current_keys), len(previous_keys))), mark=MARKS[word])
        topics.append(entry)
    topics.sort(key=lambda entry: (-entry["count"], entry["label"]))
    for position, entry in enumerate(topics, start=1):
        entry["topicId"] = f"t{position}"
    if params.compare and not previous_keys:
        warnings.append({"code": "no_previous_window", "message": "The previous window has no References, so no topic is marked rising or falling."})
    assigned = {key for entry in topics for key in entry["memberIds"]}
    record = {
        "savedId": saved_id, "cached": False, "engine": {"name": engine.name, "version": engine.version},
        "window": now.describe(), "compareTo": windows[1].describe() if params.compare else None,
        "filters": {"section": params.section_id, "monitor": params.monitor, "states": sorted(params.states)},
        "referencesInWindow": len(current_keys), "referencesInPreviousWindow": len(previous_keys) if params.compare else None,
        "minClusterSize": size, "unassigned": len(current_keys - assigned), "legend": LEGEND if params.compare else None, "topics": topics,
    }
    store.put(saved_id, record)
    return TopicOutcome(compact(record), tuple(warnings))
