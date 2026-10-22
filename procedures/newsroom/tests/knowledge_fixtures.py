"""Snapshot files that match the knowledge contract (schemaVersion 1), for the knowledge component tests."""

from __future__ import annotations

import json
from pathlib import Path

AS_OF = "2026-10-19"


def entity(key, kind, name, weeks, series8, last4, prior4, percent, *, href="", is_new=False, count=None):
    return {
        "key": key, "kind": kind, "name": name, "href": href or None, "itemCount": count if count is not None else sum(series8),
        "weeksOfHistory": weeks, "series8": series8, "change": {"last4": last4, "prior4": prior4, "percent": percent}, "isNew": is_new,
    }


ENTITIES = [
    entity("acme-loom", "maker", "Acme Loom", 12, [1, 1, 2, 2, 3, 4, 5, 6], 18, 6, 200, href="/wiki/acme-loom/"),
    entity("beta-spool", "tool", "Beta Spool", 6, [0, 0, 1, 1, 2, 2, 3, 3], 10, 2, None, href="/wiki/beta-spool/"),
    entity("gamma-new", "maker", "Gamma New", 2, [0, 0, 0, 0, 0, 0, 1, 2], 3, 0, None, is_new=True),
    entity("delta-fade", "maker", "Delta Fade", 20, [6, 6, 5, 5, 3, 2, 1, 1], 7, 22, -68, href="/wiki/delta-fade/"),
]

INDEX = {
    "schemaVersion": 1, "asOf": AS_OF, "entityCount": 4, "topicCount": 7,
    "kinds": [{"key": "maker", "label": "Maker", "count": 3}, {"key": "tool", "label": "Tool", "count": 1}],
    "beats": [],
    "entities": ENTITIES,
    "trending": ["acme-loom", "delta-fade", "beta-spool"],
    "conceptOfTheWeek": {"key": "acme-loom", "name": "Acme Loom", "href": "/wiki/acme-loom/", "lede": "A loom maker that doubled its output.", "itemCount": 36, "makerCount": 3},
}

ACME = {
    "schemaVersion": 1, "key": "acme-loom", "kind": "maker", "name": "Acme Loom", "aliases": [],
    "description": {"state": "reviewed", "reviewedOn": "2026-10-01"}, "href": "/wiki/acme-loom/", "itemCount": 24,
    "weeksOfHistory": 12, "series8": [1, 1, 2, 2, 3, 4, 5, 6],
    "series26": [0] * 14 + [1, 1, 2, 2, 3, 4, 5, 6, 0, 1, 2, 3],
    "change": {"last4": 18, "prior4": 6, "percent": 200},
    "neighbours": [
        {"relation": "made_by", "key": "delta-fade", "name": "Delta Fade", "kind": "maker", "weight": 2},
        {"relation": "built_on", "key": "beta-spool", "name": "Beta Spool", "kind": "tool", "weight": 5},
        {"relation": "built_on", "key": "gamma-new", "name": "Gamma New", "kind": "maker", "weight": 9},
        {"relation": "made_by", "key": "zeta", "name": "Zeta", "kind": "maker", "weight": 4},
    ],
    "relatedItems": [{"title": "Loom news", "url": "/posts/loom-news/", "publishedAt": "2026-10-12T08:00:00Z", "reason": "acme-loom"}],
}

NEW_ENTITY = {
    "schemaVersion": 1, "key": "gamma-new", "kind": "maker", "name": "Gamma New", "aliases": [], "description": {"state": "none", "reviewedOn": None},
    "href": None, "itemCount": 3, "weeksOfHistory": 2, "series8": [0, 0, 0, 0, 0, 0, 1, 2], "series26": [0] * 24 + [1, 2],
    "change": {"last4": 3, "prior4": 0, "percent": None}, "neighbours": [], "relatedItems": [],
}

CLUSTERS = {
    "schemaVersion": 1, "asOf": AS_OF, "runId": "run-1", "unacceptedClusters": "hide",
    "clusters": [
        {"uid": "c-1", "name": "Wearable looms", "state": "growing", "itemCount": 14, "topTerms": ["loom", "wearable", "textile"], "series8": [1, 1, 2, 2, 3, 3, 4, 5], "weeksOfData": 10, "href": "/topics/wearable-looms/"},
        {"uid": "c-2", "name": "Fresh theme", "state": "new", "itemCount": 3, "topTerms": ["fresh"], "series8": [0, 0, 0, 0, 0, 1, 1, 1], "weeksOfData": 3, "href": None},
        {"uid": "c-3", "name": None, "state": None, "itemCount": 6, "topTerms": ["secret"], "series8": [0, 0, 1, 1, 1, 1, 1, 1], "weeksOfData": 6, "href": None},
    ],
}


def write(directory: Path, *, index=INDEX, clusters=CLUSTERS, entities=(ACME, NEW_ENTITY)) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    if index is not None:
        (directory / "index.json").write_text(json.dumps(index, sort_keys=True), encoding="utf-8")
    if clusters is not None:
        (directory / "clusters.json").write_text(json.dumps(clusters, sort_keys=True), encoding="utf-8")
    for one in entities:
        target = directory / "entities" / f"{one['key']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(one, sort_keys=True), encoding="utf-8")
    return directory
