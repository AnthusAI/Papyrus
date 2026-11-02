"""Replay of the idea standard on one site's accepted References, read only (ticket PPY-f40b36; ``scripts/replay_idea_standard.py`` is the command).

For the accepted References that have no story yet, the single-item path runs once as a dry run: the model is asked, the draft checked and the point check
judged, and nothing is filed, stored, marked or requested. The backend is wrapped in ``ReadOnlyClient``, which raises on anything that is not a read, no review
client is given (so no curation flag can be raised) and no retry memory is given (so every Reference is tried, whatever an earlier run rejected).

It writes (to a local directory only):

* ``result.json``: the candidates, what would be filed, ``nothingToAdd``, the ``connectionsUsed`` histogram, the check failures by reason, the point check's
  verdicts and the cost.
* ``sample.md``: about twenty drafts that would be filed, for the owner to read. Each shows the connections the newsroom had for the Reference, every sentence
  numbered to mark as *from the source*, *adds something* or *filler*, and the point check's verdict; then the drafts that were rejected, with the reasons.
* ``point-checks.json``: every verdict, with the sentences it judged.

``max_cost_usd`` is a ceiling on the real cost (``draft_monitor_stories`` stops before a call that would pass it and meters every call from the usage the API
returned).
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
DEFAULT_SAMPLE = 20


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


def run_summary(run: Mapping[str, Any]) -> dict[str, Any]:
    """What the run did, in the shape the owner reads: candidates, filed, nothingToAdd, connectionsUsed, check failures by reason, cost."""
    usage = run.get("usage") or {}
    return {
        "minimumStandard": run["minimumStandard"], "candidates": run["inputs"]["candidates"], "attempted": run["attempted"], "filed": len(run["drafts"]),
        "nothingToAdd": run["nothingToAdd"], "connectionsUsed": run["connectionsUsed"], "checkFailures": run["checkFailures"],
        "skipped": sorted({row["reason"] for row in run["skipped"]}), "duplicates": len(run["duplicates"]), "modelCalls": usage.get("calls", 0),
        "costUsd": usage.get("costUsd") or 0.0, "stoppedBy": run["stoppedBy"], "stoppedForCost": run.get("stoppedForCost"),
        "knowledgeErrors": run.get("knowledgeErrors"), "noPointOffered": run.get("noPointOffered", 0), "pointChecks": len(run.get("pointChecks") or []),
        "pointCheckFailed": sum(bool(row["failures"]) for row in run.get("pointChecks") or []),
    }


def sentences_of(draft: Mapping[str, Any]) -> list[str]:
    return [str(sentence["text"]) for sentence in draft["sentences"]]


def connection_lines(connections: connection_rules.Connections) -> list[str]:
    lines = ["What the newsroom had on this Reference:", ""]
    if not connections.entries:
        return lines + ["- nothing: no accept reason, comment or related Reference"]
    for entry in connections.entries:
        row = entry.row
        shown = row.get("text") or f"{row.get('title')}: {row.get('summary', '')}"
        if entry.kind == connection_rules.EDITORS_EXPLANATION:
            shown = row["editorsExplanation"]["text"]
        lines.append(f"- {entry.handle} ({entry.kind}{', ' + row['link'] if row.get('link') else ''}): {shown}")
    return lines


def build_sample(run: Mapping[str, Any], knowledge: connection_rules.Knowledge, items: Mapping[str, Any], *, size: int, seed: int) -> list[str]:
    """The sample as markdown lines: ``size`` of the drafts that would be filed, chosen at random, then the ones that were rejected and why."""
    drafts = {draft["referenceLineageId"]: draft for draft in run["drafts"]}
    chosen = sorted(random.Random(seed).sample(sorted(drafts), min(size, len(drafts))))
    verdicts = {row["lineageId"]: row for row in run.get("pointChecks") or []}
    lines = [
        "# Ideas under the standard: more than a summary", "",
        f"{len(chosen)} of the {len(drafts)} drafts that would be filed. Mark every numbered sentence: **source** (it only restates the source), "
        "**adds** (it says something the source does not) or **filler**.", "",
    ]
    for number, lineage in enumerate(chosen, start=1):
        item, draft = items[lineage], drafts[lineage]
        verdict = (verdicts.get(lineage) or {}).get("verdict") or {}
        said = f"{verdict.get('verdict', 'not asked')}: {verdict.get('reason', '')}".rstrip(": ")
        lines += [f"## {number}. {item.title}", "", item.url, "", *connection_lines(knowledge.connections_for(item)), "", f"The point check said {said}", ""]
        lines += [f"{position}. {text}    [ source | adds | filler ]" for position, text in enumerate(sentences_of(draft), start=1)]
        lines.append("")
    rejected = [row for row in run["invalid"] if row.get("reason") in ("point_check_failed", "citation_check_failed")]
    if rejected:
        lines += ["## Rejected", ""]
        for row in rejected:
            why = ", ".join(row.get("failures") or []) or ", ".join(sorted({str(p["reason"]).split(":")[0] for p in (row.get("citationCheck") or {}).get("problems", [])}))
            lines.append(f"- {row['title']}: {row['reason']} ({why}){' - ' + str(row['verdict'].get('reason')) if row.get('verdict') else ''}")
        lines.append("")
    return lines


def replay_site(
    client: Any,
    *,
    site: str,
    corpus_key: str | None,
    transport: Callable,
    max_cost_usd: float,
    sample: int = DEFAULT_SAMPLE,
    references: int | None = None,
    seed: int = 20261102,
    model: str | None = None,
    fetch: Callable | None = None,
    explorer: Callable | None = None,
    now: datetime | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Runs the single-item path once as a dry run and returns ``{"site", "run", "sample", "sampleText", "costUsd", ...}``. Never writes to the backend (``ReadOnlyClient``)."""
    from . import synthesis

    if max_cost_usd <= 0:
        raise ValueError("The replay needs a cost ceiling above zero.")
    moment = now or datetime.now(timezone.utc)
    readonly = ReadOnlyClient(client)
    held = context if context is not None else load_context(readonly, now=moment)
    items, _ = monitor_stories.collect_monitored_items(readonly, site=corpus_key or site, now=moment)
    by_lineage = {item.lineage_id: item for item in items if item.relevant is not False}
    order = sorted(by_lineage)
    random.Random(seed).shuffle(order)   # a stop for cost must not favour one end of the list
    if references is not None:
        order = order[:references]
    knowledge = monitor_stories.default_knowledge(readonly)
    run = monitor_stories.draft_monitor_stories(
        client=readonly, site=site, context=held, json_store=None, transport=transport, idea_store=None, review_client=None,
        model=model or synthesis.DEFAULT_MODEL, limit=None, dry_run=True, now=moment, fetch=fetch or monitor_stories.fetch_source, corpus_key=corpus_key,
        explorer=explorer, ordered_candidates=order, knowledge=knowledge, maximum_cost_usd=max_cost_usd,
    )
    spent = float((run.get("usage") or {}).get("costUsd") or 0.0)
    lines = build_sample(run, knowledge, by_lineage, size=sample, seed=seed)
    return {
        "site": site, "corpusKey": corpus_key, "asOf": iso(moment), "seed": seed, "maxCostUsd": max_cost_usd, "costUsd": round(spent, 6), "referencesOffered": len(order),
        "run": run_summary(run), "sample": min(sample, len(run["drafts"])),
        "sampleText": "\n".join(lines) + "\n", "pointChecks": run.get("pointChecks") or [],
    }


def write_outputs(result: Mapping[str, Any], directory: Path) -> dict[str, Path]:
    """``result.json`` (without the sample text), ``sample.md`` and ``point-checks.json``, in a private local directory."""
    target = assert_private(directory)
    target.mkdir(parents=True, exist_ok=True)
    paths = {"result": target / "result.json", "sample": target / "sample.md", "pointChecks": target / "point-checks.json"}
    paths["pointChecks"].write_text(json.dumps(result.get("pointChecks") or [], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths["result"].write_text(json.dumps({key: value for key, value in result.items() if key not in ("sampleText", "pointChecks")}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths["sample"].write_text(str(result["sampleText"]), encoding="utf-8")
    return paths
