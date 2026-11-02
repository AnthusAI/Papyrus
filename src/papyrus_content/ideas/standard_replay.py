"""Replay of the idea minimum standard on one site's accepted References, read only (ticket PPY-f40b36; ``scripts/replay_idea_standard.py`` is the command).

For the accepted References that have no story yet, the single-item path runs twice on the same References in the same order: once with
``minimumStandard`` ``summary`` (the old behaviour) and once with ``more-than-summary``. Both arms are dry runs: the model is asked and the draft checked, and
nothing is filed, stored, marked or requested. The backend is wrapped in ``ReadOnlyClient``, which raises on anything that is not a read, and no review client is
given, so no curation flag can be raised.

It writes (to a local directory only):

* ``result.json``: per arm, the candidates, what would be filed, ``nothingToAdd``, the ``connectionsUsed`` histogram, the check failures by reason and the cost.
* ``sample.md``: about twenty pairs for the owner to read. Each pair is the same Reference written both ways, shown as "Version A" and "Version B" in a random
  order, with the connections the newsroom had for that Reference and every sentence numbered to mark as *from the source*, *adds something* or *filler*.
* ``key.json``: which version was which, kept apart so the sample stays blind.

``max_cost_usd`` is a ceiling on the real cost of both arms together (``draft_monitor_stories`` stops before a call that would pass it and meters every call from the
usage the API returned). This module removes the summary standard's last use: delete ``connections.SUMMARY`` and ``SUMMARY_SYSTEM_PROMPT`` after the replay.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import connections as connection_rules, monitor_stories
from .context import load_context
from .digest import iso
from .store import assert_private

READS = ("list_", "get_")
PLAIN_ATTRIBUTES = frozenset({"tenant_id", "endpoint"})
ARMS = (connection_rules.SUMMARY, connection_rules.MORE_THAN_SUMMARY)
DEFAULT_PAIRS = 20


class ReplayWriteRefused(RuntimeError):
    """The replay asked the backend to change something. It never may."""


class ReadOnlyClient:
    """A backend client that can only read: ``list_*``, ``get_*`` and GraphQL queries pass through; everything else (create, update, upsert, delete, a mutation)
    raises ``ReplayWriteRefused`` before anything is sent."""

    def __init__(self, inner: Any) -> None:
        object.__setattr__(self, "_inner", inner)

    def __getattr__(self, name: str) -> Any:
        if name in PLAIN_ATTRIBUTES:
            return getattr(self._inner, name)
        if name.startswith(READS):
            return getattr(self._inner, name)
        if name == "graphql":
            return self._graphql
        raise ReplayWriteRefused(f"The replay is read only; {name} is not a read.")

    def __setattr__(self, name: str, value: Any) -> None:
        raise ReplayWriteRefused("The replay is read only.")

    def _graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        if not query.lstrip().startswith("query"):
            raise ReplayWriteRefused("The replay is read only; it sends no mutation.")
        return self._inner.graphql(query, variables)


def arm_summary(run: Mapping[str, Any]) -> dict[str, Any]:
    """What one arm did, in the shape the owner reads: candidates, filed, nothingToAdd, connectionsUsed, check failures by reason, cost."""
    usage = run.get("usage") or {}
    return {
        "minimumStandard": run["minimumStandard"], "candidates": run["inputs"]["candidates"], "attempted": run["attempted"], "filed": len(run["drafts"]),
        "nothingToAdd": run["nothingToAdd"], "connectionsUsed": run["connectionsUsed"], "checkFailures": run["checkFailures"],
        "skipped": sorted({row["reason"] for row in run["skipped"]}), "duplicates": len(run["duplicates"]), "modelCalls": usage.get("calls", 0),
        "costUsd": usage.get("costUsd") or 0.0, "stoppedBy": run["stoppedBy"], "stoppedForCost": run.get("stoppedForCost"),
        "knowledgeErrors": run.get("knowledgeErrors"),
    }


def sentences_of(draft: Mapping[str, Any]) -> list[str]:
    return [str(sentence["text"]) for sentence in draft["sentences"]]


def pair_markdown(number: int, title: str, url: str, connections: connection_rules.Connections, versions: Mapping[str, Mapping[str, Any]]) -> list[str]:
    lines = [f"## Pair {number}: {title}", "", url, "", "What the newsroom had on this Reference:", ""]
    if connections.entries:
        for entry in connections.entries:
            row = entry.row
            shown = row.get("text") or f"{row.get('title')}: {row.get('summary', '')}"
            if entry.kind == connection_rules.EDITORS_EXPLANATION:
                shown = row["editorsExplanation"]["text"]
            lines.append(f"- {entry.handle} ({entry.kind}{', ' + row['link'] if row.get('link') else ''}): {shown}")
    else:
        lines.append("- nothing: no accept reason, comment or related Reference")
    for name, draft in versions.items():
        lines += ["", f"### Version {name}", ""]
        for position, text in enumerate(sentences_of(draft), start=1):
            lines.append(f"{position}. {text}    [ source | adds | filler ]")
    return lines + [""]


def build_pairs(
    runs: Mapping[str, Mapping[str, Any]], knowledge: connection_rules.Knowledge, items: Mapping[str, Any], *, pairs: int, seed: int,
) -> tuple[list[str], dict[str, dict[str, str]]]:
    """(the sample as markdown lines, the key). A pair needs a draft from both arms for the same Reference; ``pairs`` of them are chosen at random and each is
    shown in a random order."""
    drafts = {arm: {draft["referenceLineageId"]: draft for draft in runs[arm]["drafts"]} for arm in ARMS}
    both = sorted(set(drafts[connection_rules.SUMMARY]) & set(drafts[connection_rules.MORE_THAN_SUMMARY]))
    chosen = sorted(random.Random(seed).sample(both, min(pairs, len(both))))
    lines = [
        "# Idea minimum standard: same Reference, written two ways", "",
        f"{len(chosen)} pair(s) of {len(both)} References that both versions wrote. In each, mark every numbered sentence: **source** (it only restates the source), "
        "**adds** (it says something the source does not) or **filler**. The versions are in random order; the key is in a separate file.", "",
    ]
    key: dict[str, dict[str, str]] = {}
    generator = random.Random(f"{seed}-order")
    for number, lineage in enumerate(chosen, start=1):
        order = list(ARMS)
        generator.shuffle(order)
        versions = {name: drafts[arm][lineage] for name, arm in zip("AB", order)}
        key[f"pair-{number}"] = {"referenceLineageId": lineage, **{name: arm for name, arm in zip("AB", order)}}
        item = items[lineage]
        lines += pair_markdown(number, item.title, item.url, knowledge.connections_for(item), versions)
    return lines, key


def replay_site(
    client: Any,
    *,
    site: str,
    corpus_key: str | None,
    transport: Callable,
    max_cost_usd: float,
    pairs: int = DEFAULT_PAIRS,
    references: int | None = None,
    seed: int = 20261102,
    model: str | None = None,
    fetch: Callable | None = None,
    explorer: Callable | None = None,
    now: datetime | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Runs both arms and returns ``{"site", "arms", "pairs", "sample", "key", "costUsd"}``. Never writes to the backend (``ReadOnlyClient``)."""
    from . import synthesis

    if max_cost_usd <= 0:
        raise ValueError("The replay needs a cost ceiling above zero.")
    moment = now or datetime.now(timezone.utc)
    readonly = ReadOnlyClient(client)
    held = context if context is not None else load_context(readonly, now=moment)
    items, _ = monitor_stories.collect_monitored_items(readonly, site=corpus_key or site, now=moment)
    by_lineage = {item.lineage_id: item for item in items if item.relevant is not False}
    order = sorted(by_lineage)
    random.Random(seed).shuffle(order)   # a stop for cost must not favour one end of the list; both arms walk the same order
    if references is not None:
        order = order[:references]
    knowledge = monitor_stories.default_knowledge(readonly)
    runs: dict[str, dict[str, Any]] = {}
    spent = 0.0
    for arm in ARMS:
        runs[arm] = monitor_stories.draft_monitor_stories(
            client=readonly, site=site, context=held, json_store=None, transport=transport, idea_store=None, review_client=None,
            model=model or synthesis.DEFAULT_MODEL, limit=None, dry_run=True, now=moment, fetch=fetch or monitor_stories.fetch_source, corpus_key=corpus_key,
            explorer=explorer, ordered_candidates=order, minimum_standard=arm, knowledge=knowledge, maximum_cost_usd=max(max_cost_usd - spent, 0.0),
        )
        spent += float((runs[arm].get("usage") or {}).get("costUsd") or 0.0)
    sample, key = build_pairs(runs, knowledge, by_lineage, pairs=pairs, seed=seed)
    return {
        "site": site, "corpusKey": corpus_key, "asOf": iso(moment), "seed": seed, "maxCostUsd": max_cost_usd, "costUsd": round(spent, 6), "referencesOffered": len(order),
        "arms": {arm: arm_summary(runs[arm]) for arm in ARMS}, "pairs": len(key), "sample": "\n".join(sample) + "\n", "key": key,
    }


def write_outputs(result: Mapping[str, Any], directory: Path) -> dict[str, Path]:
    """``result.json`` (without the sample text), ``sample.md`` and ``key.json``, in a private local directory."""
    target = assert_private(directory)
    target.mkdir(parents=True, exist_ok=True)
    paths = {"result": target / "result.json", "sample": target / "sample.md", "key": target / "key.json"}
    paths["result"].write_text(json.dumps({key: value for key, value in result.items() if key not in ("sample", "key")}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths["sample"].write_text(str(result["sample"]), encoding="utf-8")
    paths["key"].write_text(json.dumps(result["key"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return paths
