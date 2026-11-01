"""Daily monitor stories, run by the monitoring router (docs/monitoring-cloud.md#monitor-stories).

The router task ``{"task": "monitor-stories"}`` writes a short cited story draft for every accepted, monitored Reference of each publication
that has none yet: the library behind ``papyrus ideas monitor-stories`` (``ideas/monitor_stories.py``), run in process with
``limit=None``, so nothing but a real constraint stops it. A draft is a private Item at the ``idea`` stage; one soft review request per
publication and run asks the editors to look, and links the Idea column of the Stories board. Nothing is published, and a Reference is never drafted twice.

It is on for every publication. A publication's router entry turns it off with ``"monitorStories": {"enabled": false}``, and shapes it with two more
keys (no numeric knob):

* ``singleItem`` (default true): draft a single idea for an accepted Reference that the signals single out.
* ``contextPacks`` (default ``{"enabled": true}``): ``enabled`` builds context packs from the newsroom's own activity (Messages, accepts) and drafts up to
  three theme ideas from each; ``signals`` lists the signals to use, from the closed set ``conversation``, ``acceptance``, ``hub``, ``cluster``,
  ``resurfaced``; omitted means every signal that has data. With ``contextPacks.enabled`` false the task is the single-item task as it was, ranked by the
  relevance Cyclotron.

Before either, the publication's vector index is kept current and suggestions are written (``monitoring_vectors.py``, docs/monitoring-cloud.md#vector-index-and-suggestions):
the order in a run is index sync (References accepted since the last pass, concept cards), suggestions for those References, then packs and single items.
Three more keys: ``suggestions`` (``{"enabled": true}`` by default), ``vectorIndexArn`` and ``storageBucketName``, both read from the site's ``amplify_outputs.json``
by ``seed_router_config.py`` and never typed. Without ``vectorIndexArn`` the sync and the suggestions are skipped and the log line says why.

With context packs on, the publication is read once (``ideas/signal_inputs.py``) and the run walks ONE ordered queue of packs and scored single items
(``ideas/signal_queue.py``, ``ideas/item_signals.py``): a pack goes to ``ideas/pack_stories.py``, an item to the single-item path, and both share one cost
meter and the stops below. A pack whose anchor already has an idea is offered again only with new evidence (``packsSkippedNoNewEvidence``).

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
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

# The drafting modules are imported inside the functions: this module is imported by every router invocation, and only the daily
# monitor-stories task needs them.

POLICY_KEYS = ("enabled", "store", "singleItem", "contextPacks", "suggestions", "vectorIndexArn", "storageBucketName")
VECTOR_INDEX_ARN = re.compile(r"arn:aws:s3vectors:[a-z0-9-]+:\d{12}:bucket/[A-Za-z0-9.-]+/index/[A-Za-z0-9.-]+")
BUCKET_NAME = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")
PACK_KEYS = ("enabled", "signals")
PACK_SIGNALS = ("conversation", "acceptance", "hub", "cluster", "resurfaced")   # the closed set of pack signals; an item signal is the single-item path's own
STORES = ("items",)   # where a draft is filed: an Item at the idea stage. "proposals" (a story_draft Proposal) was removed; a router entry that still says it is read as "items".
MAXIMUM_COST_USD = 0.50   # per publication and run; see the module docstring
READ_WORKERS = 8   # References of one publication read at a time: the API's throughput, not a limit on the work (a site with thousands of accepted
#                    References needs two queries each, and read one by one that alone would take most of the Lambda's time)
EMPTY_LINE = {"drafted": 0, "candidates": 0, "notAccepted": 0, "skipped": 0, "stoppedBy": None, "packs": 0, "ideasFromPacks": 0, "packsSkippedNoNewEvidence": 0, "packDetails": [],
              "indexed": 0, "conceptCardsWritten": 0, "suggestionsWritten": 0, "suggestionsSkippedReason": None}
REAL_EXPLORER = object()   # `explorer` default: follow the item's link and, failing that, search for it (tests pass None for the plain page reader)


def validate_monitor_stories(publication_id: str, raw: Any) -> dict[str, Any]:
    """The normalized ``monitorStories`` setting of a router publication. Absent means ON; ``{"enabled": false}`` turns it off.

    ``singleItem`` defaults to true. ``contextPacks`` defaults to ``{"enabled": true, "signals": None}``; ``signals`` is None (every signal that has
    data) or a non-empty list from ``PACK_SIGNALS``."""
    defaults = {"enabled": True, "store": "items", "singleItem": True, "contextPacks": {"enabled": True, "signals": None}, "suggestions": {"enabled": True},
                "vectorIndexArn": None, "storageBucketName": None}
    if raw is None:
        return defaults
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
    single_item = raw.get("singleItem", True)
    if not isinstance(single_item, bool):
        raise ValueError(f"router publication {publication_id} monitorStories.singleItem must be true or false")
    return {"enabled": enabled, "store": store, "singleItem": single_item, "contextPacks": validate_context_packs(publication_id, raw.get("contextPacks")),
            "suggestions": validate_suggestions(publication_id, raw.get("suggestions")),
            "vectorIndexArn": validate_text_setting(publication_id, "vectorIndexArn", raw.get("vectorIndexArn"), VECTOR_INDEX_ARN),
            "storageBucketName": validate_text_setting(publication_id, "storageBucketName", raw.get("storageBucketName"), BUCKET_NAME)}


def validate_suggestions(publication_id: str, raw: Any) -> dict[str, Any]:
    if raw is None:
        return {"enabled": True}
    if not isinstance(raw, dict) or set(raw) - {"enabled"} or not isinstance(raw.get("enabled", True), bool):
        raise ValueError(f"router publication {publication_id} monitorStories.suggestions must be {{\"enabled\": true or false}}")
    return {"enabled": raw.get("enabled", True)}


def validate_text_setting(publication_id: str, name: str, raw: Any, pattern: re.Pattern) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or not pattern.fullmatch(raw):
        raise ValueError(f"router publication {publication_id} monitorStories.{name} is not valid")
    return raw


def validate_context_packs(publication_id: str, raw: Any) -> dict[str, Any]:
    if raw is None:
        return {"enabled": True, "signals": None}
    if not isinstance(raw, dict):
        raise ValueError(f"router publication {publication_id} monitorStories.contextPacks must be an object")
    unknown = sorted(set(raw) - set(PACK_KEYS))
    if unknown:
        raise ValueError(f"router publication {publication_id} monitorStories.contextPacks has unknown keys: {', '.join(unknown)}")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"router publication {publication_id} monitorStories.contextPacks.enabled must be true or false")
    signals = raw.get("signals")
    if signals is not None:
        if not isinstance(signals, list) or not signals or any(signal not in PACK_SIGNALS for signal in signals) or len(set(signals)) != len(signals):
            raise ValueError(f"router publication {publication_id} monitorStories.contextPacks.signals must be a list of distinct signals from {', '.join(PACK_SIGNALS)}")
        signals = list(signals)
    return {"enabled": enabled, "signals": signals}


def lambda_openai_key(environment: dict[str, str] | None = None, *, ssm: Any = None) -> str | None:
    """The OpenAI key from the SSM SecureString ``ENRICHMENT_OPENAI_KEY_PARAMETER`` names (the key item enrichment already uses), or None when there is
    no parameter or it cannot be read. The model transport and the embeddings of the vector pass use it; it is held in memory only."""
    environment = os.environ if environment is None else environment
    parameter = (environment.get("ENRICHMENT_OPENAI_KEY_PARAMETER") or "").strip()
    if not parameter:
        return None
    try:
        if ssm is None:
            import boto3

            ssm = boto3.client("ssm")
        return str(ssm.get_parameter(Name=parameter, WithDecryption=True)["Parameter"]["Value"]).strip() or None
    except Exception:  # noqa: BLE001 - an unreadable key is "not configured": every publication logs the typed skip
        return None


def lambda_story_transport(environment: dict[str, str] | None = None, *, ssm: Any = None) -> Callable | None:
    """The model transport of the router Lambda, from ``lambda_openai_key``, or None when there is no key."""
    key = lambda_openai_key(environment, ssm=ssm)
    if not key:
        return None
    from .ideas import synthesis

    return synthesis.openai_transport(key)


def lambda_judgment_key(environment: dict[str, str] | None = None, *, ssm: Any = None) -> str | None:
    """The TypeSafe key for the judgment lane of the idea gate, from the SSM SecureString ``EDITORIAL_JUDGMENT_KEY_PARAMETER`` names (one shared key for
    every routed site), or None when there is no parameter or it cannot be read. None is not an error: the idea records that the judgment lane did not
    run and the rules lane still checks it. The key is placed only in the process environment Humanus reads, never logged or stored."""
    environment = os.environ if environment is None else environment
    parameter = (environment.get("EDITORIAL_JUDGMENT_KEY_PARAMETER") or "").strip()
    if not parameter:
        return None
    try:
        if ssm is None:
            import boto3

            ssm = boto3.client("ssm")
        return str(ssm.get_parameter(Name=parameter, WithDecryption=True)["Parameter"]["Value"]).strip() or None
    except Exception:  # noqa: BLE001 - an unreadable key means "judgment lane not run", recorded on each idea
        return None


def run_publication(client: Any, publication: dict[str, Any], *, transport: Callable, now: datetime, out_of_time: Callable[[], bool],
                    fetch: Any = None, explorer: Any = REAL_EXPLORER, maximum_cost_usd: float = MAXIMUM_COST_USD,
                    handled_references: Any = (), gate: Any = None, embedding_key: str | None = None,
                    read_watermark: Callable[[], str | None] = lambda: None, write_watermark: Callable[[str], None] = lambda value: None) -> dict[str, Any]:
    """Drafts one publication's undrafted accepted monitored References and returns its log record (the shape the router prints).
    ``fetch`` and ``explorer`` default to the real page reader and link explorer; tests pass fakes. ``handled_references`` are the ids of the References
    an Automation has a procedure run recorded or in progress for (the router reads them from its trigger rows); those are left to it."""
    from .ideas import monitor_stories
    from .ideas.context import load_context
    from .ideas.items import ItemStore
    from .ideas.gate import HumanusGate
    from .ideas.signal_queue import prepare_signal_run
    from .ideas.store import legacy_story_drafts

    from .monitoring_vectors import run_vector_pass

    policy = validate_monitor_stories(publication["publicationId"], publication.get("monitorStories"))
    vectors = run_vector_pass(client, publication, policy, now=now, out_of_time=out_of_time, maximum_cost_usd=maximum_cost_usd, embedding_key=embedding_key,
                              read_watermark=read_watermark, write_watermark=write_watermark)
    vector_line = {key: vectors[key] for key in ("indexed", "conceptCardsWritten", "suggestionsWritten", "suggestionsSkippedReason")}
    for key in ("indexSkippedReason", "newlyAccepted", "suggestionsFailed", "suggestionsWithoutVector", "watermarkError"):
        if vectors.get(key):
            vector_line[key] = vectors[key]
    if not policy["contextPacks"]["enabled"] and not policy["singleItem"]:
        return {**EMPTY_LINE, **vector_line, "publicationId": publication["publicationId"], "status": "complete", "costUsd": vectors["costUsd"], "stoppedBy": vectors["stoppedBy"]}

    # Each idea passes the same Humanus gate as `ideas monitor-stories --store items`, through this publication's own API.
    gate = gate if gate is not None else HumanusGate.for_client(client, judgment_key=lambda_judgment_key())
    context = load_context(client, now=now)
    signal_run = None
    if policy["contextPacks"]["enabled"]:
        signals = policy["contextPacks"]["signals"]
        signal_run = prepare_signal_run(
            client, site=publication["corpusKey"], context=context, now=now, signals=tuple(signals) if signals else None, single_items=policy["singleItem"], gate=gate)

    run = monitor_stories.draft_monitor_stories(
        client=client, site=publication["publicationId"], corpus_key=publication["corpusKey"],
        context=context, json_store=None, idea_store=ItemStore(client, legacy=lambda: legacy_story_drafts(client), gate=gate), review_client=client,
        transport=transport, limit=None, dry_run=False, now=now, fetch=fetch or monitor_stories.fetch_source,
        explorer=monitor_stories.explore_item if explorer is REAL_EXPLORER else explorer, out_of_time=out_of_time,
        maximum_cost_usd=max(maximum_cost_usd - vectors["costUsd"], 0.0), read_workers=READ_WORKERS, automation_handled=handled_references, signal_run=signal_run)
    inputs, usage = run["inputs"], run.get("usage") or {}
    packs = run.get("packs") or []
    return {
        "publicationId": publication["publicationId"], "status": "stopped" if (run["stoppedBy"] or vectors["stoppedBy"]) else "complete",
        "drafted": len(run["drafts"]), "candidates": inputs["candidates"], "notAccepted": inputs["notAccepted"],
        "skipped": len(run["skipped"]), "stoppedBy": run["stoppedBy"] or vectors["stoppedBy"], "notMonitored": inputs["notMonitored"],
        "attempted": run["attempted"], "failedTheCheck": len(run["invalid"]),
        "refusedByEditorialCheck": sum(1 for entry in run["invalid"] if entry.get("reason") == "editorial_check_failed"), "duplicates": len(run["duplicates"]),
        "handledByAutomation": inputs.get("handledByAutomation", 0), "costUsd": round((usage.get("costUsd") or 0) + vectors["costUsd"], 6) if (usage.get("costUsd") is not None or vectors["costUsd"]) else None, **vector_line,
        "packs": len(packs), "ideasFromPacks": sum(1 for draft in run["drafts"] if draft.get("origin") == "context-pack"),
        "packsSkippedNoNewEvidence": run.get("packsSkippedNoNewEvidence", 0),
        "packDetails": [{"signal": pack["signal"], "anchor": pack["anchor"], "correctedPValue": pack["correctedPValue"], "ideas": pack["ideas"]} for pack in packs if pack["attempted"]],
        "review": (run.get("review") or {}).get("status"), **({"fileError": run["fileError"]} if run.get("fileError") else {}),
    }
