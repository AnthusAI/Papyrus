"""Daily monitor stories, run by the monitoring router (docs/monitoring-cloud.md#monitor-stories).

The router task ``{"task": "monitor-stories"}`` writes a short cited story draft for every accepted, monitored Reference of each publication
that has none yet: the library behind ``papyrus ideas monitor-stories`` (``ideas/monitor_stories.py``), run in process with
``limit=None``, so nothing but a real constraint stops it. A draft is a private Item at the ``idea`` stage; one soft review request per
publication and run asks the editors to look, and links the Idea column of the Stories board. Nothing is published, and a Reference is never drafted twice.

It is on for every publication. A publication's router entry turns it off with ``"monitorStories": {"enabled": false}``.

The real constraints, in the order they can stop a publication (``stoppedBy`` in its log line):

* ``time``: the Lambda's remaining time. Each publication gets an equal share of what is left for the publications after it, so a large
  backlog on one cannot starve the others; time one publication does not use passes to the next. The rest waits for the next run, which
  starts from the same ranking (best first) and skips what is already drafted.
* ``cost``: the model spend of one publication's run, ``MAXIMUM_COST_USD``. At the model's price it is far above what the time budget lets a
  run spend; it is only a backstop against a runaway loop, and a run that reaches it says so.
* ``file_error``: a draft could not be filed (usually a missing grant). The run stops rather than pay for drafts that cannot be kept.

Never raises into the router: a publication that fails is logged as ``failed`` and the others go on.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from typing import Any

# The drafting modules are imported inside the functions: this module is imported by every router invocation, and only the daily
# monitor-stories task needs them.

POLICY_KEYS = ("enabled", "store")
STORES = ("items",)   # where a draft is filed: an Item at the idea stage. "proposals" (a story_draft Proposal) was removed; a router entry that still says it is read as "items".
MAXIMUM_COST_USD = 0.50   # per publication and run; see the module docstring
READ_WORKERS = 8   # References of one publication read at a time: the API's throughput, not a limit on the work (a site with thousands of accepted
#                    References needs two queries each, and read one by one that alone would take most of the Lambda's time)
REAL_EXPLORER = object()   # `explorer` default: follow the item's link and, failing that, search for it (tests pass None for the plain page reader)


def validate_monitor_stories(publication_id: str, raw: Any) -> dict[str, Any]:
    """The normalized ``monitorStories`` setting of a router publication. Absent means ON; ``{"enabled": false}`` turns it off."""
    if raw is None:
        return {"enabled": True, "store": "items"}
    if not isinstance(raw, dict):
        raise ValueError(f"router publication {publication_id} has an invalid monitorStories (an object is needed)")
    unknown = sorted(set(raw) - set(POLICY_KEYS))
    if unknown:
        raise ValueError(f"router publication {publication_id} monitorStories has unknown keys: {', '.join(unknown)}")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"router publication {publication_id} monitorStories.enabled must be true or false")
    store = raw.get("store", "items")
    if store == "proposals":   # the removed store: the entry was written before ideas became Items
        store = "items"
    if store not in STORES:
        raise ValueError(f"router publication {publication_id} monitorStories.store must be {' or '.join(STORES)}")
    return {"enabled": enabled, "store": store}


def lambda_story_transport(environment: dict[str, str] | None = None, *, ssm: Any = None) -> Callable | None:
    """The model transport of the router Lambda, from the SSM SecureString ``ENRICHMENT_OPENAI_KEY_PARAMETER`` names (the key item
    enrichment already uses), or None when there is no parameter or it cannot be read. The key is held by the transport only."""
    environment = os.environ if environment is None else environment
    parameter = (environment.get("ENRICHMENT_OPENAI_KEY_PARAMETER") or "").strip()
    if not parameter:
        return None
    try:
        if ssm is None:
            import boto3

            ssm = boto3.client("ssm")
        key = str(ssm.get_parameter(Name=parameter, WithDecryption=True)["Parameter"]["Value"]).strip()
    except Exception:  # noqa: BLE001 - an unreadable key is "not configured": every publication logs the typed skip
        return None
    from .ideas import synthesis

    return synthesis.openai_transport(key) if key else None


def run_publication(client: Any, publication: dict[str, Any], *, transport: Callable, now: datetime, out_of_time: Callable[[], bool],
                    fetch: Any = None, explorer: Any = REAL_EXPLORER, maximum_cost_usd: float = MAXIMUM_COST_USD,
                    handled_references: Any = ()) -> dict[str, Any]:
    """Drafts one publication's undrafted accepted monitored References and returns its log record (the shape the router prints).
    ``fetch`` and ``explorer`` default to the real page reader and link explorer; tests pass fakes. ``handled_references`` are the ids of the References
    an Automation has a procedure run recorded or in progress for (the router reads them from its trigger rows); those are left to it."""
    from .ideas import monitor_stories
    from .ideas.context import load_context
    from .ideas.items import ItemStore
    from .ideas.store import legacy_story_drafts

    run = monitor_stories.draft_monitor_stories(
        client=client, site=publication["publicationId"], corpus_key=publication["corpusKey"],
        context=load_context(client, now=now), json_store=None, idea_store=ItemStore(client, legacy=lambda: legacy_story_drafts(client)), review_client=client,
        transport=transport, limit=None, dry_run=False, now=now, fetch=fetch or monitor_stories.fetch_source,
        explorer=monitor_stories.explore_item if explorer is REAL_EXPLORER else explorer, out_of_time=out_of_time,
        maximum_cost_usd=maximum_cost_usd, read_workers=READ_WORKERS, automation_handled=handled_references)
    inputs, usage = run["inputs"], run.get("usage") or {}
    return {
        "publicationId": publication["publicationId"], "status": "stopped" if run["stoppedBy"] else "complete",
        "drafted": len(run["drafts"]), "candidates": inputs["candidates"], "notAccepted": inputs["notAccepted"],
        "skipped": len(run["skipped"]), "stoppedBy": run["stoppedBy"], "notMonitored": inputs["notMonitored"],
        "attempted": run["attempted"], "failedTheCheck": len(run["invalid"]), "duplicates": len(run["duplicates"]),
        "handledByAutomation": inputs.get("handledByAutomation", 0), "costUsd": usage.get("costUsd"),
        "review": (run.get("review") or {}).get("status"), **({"fileError": run["fileError"]} if run.get("fileError") else {}),
    }
