"""Backfill `relevance_decision_is` relations for References the router delivered before PPY-e987f2 (#517).

The router receipts (`ROUTE#<sourceId>#<rev>` under `MONITOR#<id>`) keep each lab decision and, per publication,
which Reference it delivered. For every delivered receipt this writes the relation the router would have written,
built by the router's own `lab_decision_records`. It never supersedes anything: a Reference that already has any
decision relation is left alone, and a decision that was already recorded (even if since superseded) is not
recreated. Dry-run is the default; `apply=True` is the only path that writes.

`backfill_collection` is the other kind of backfill: it loads a Hugging Face monitor's history (see below).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import time
from typing import Any, Callable
import uuid

from .monitoring import _digest, _iso
from .monitoring_cloud import DynamoStore, _validate_config, commit_item, pk
from .monitoring_huggingface import Reading, fetch_hf_page, hf_item, plan_queries, read_query, _parse_time
from .monitoring_router import ROUTER_CONFIG_SK, lab_decision_records, validate_router_config
from .relevance_decisions import RELEVANCE_RELATION

PRODUCTION_ACCOUNT = "712236451410"
TABLE_PARAMETER = "/papyrus/monitoring/table-name"


def parse_since(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--since needs a timezone, e.g. 2026-10-01T00:00:00Z")
    return parsed


def route_items(table, monitor_id: str):
    """Every ROUTE# item of the monitor, paginated."""
    from boto3.dynamodb.conditions import Key
    kwargs: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(pk(monitor_id)) & Key("sk").begins_with("ROUTE#"),
                              "ConsistentRead": True}
    while True:
        page = table.query(**kwargs)
        for item in page.get("Items", []):
            yield DynamoStore._clean(item)
        if not page.get("LastEvaluatedKey"):
            return
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def delivered_candidates(route: dict, publication_ids: set[str] | None):
    """(publicationId, state, receipt) for each publication this route delivered a positive lab decision to."""
    decision = route.get("decision") or {}
    for pub_id, state in sorted((route.get("publications") or {}).items()):
        if publication_ids and pub_id not in publication_ids:
            continue
        if not state.get("delivered") or not state.get("referenceId"):
            continue
        yield pub_id, state, {"decisionId": decision.get("decisionId"), "decidedAt": decision.get("decidedAt"),
                              **(decision.get("publications") or {}).get(pub_id, {})}


def backfill(table, monitor_id: str, *, appsync: Callable[[str], Any], apply: bool = False,
             publication_ids: list[str] | None = None, since: datetime | None = None, routes=None,
             emit: Callable[[str], None] = print) -> dict:
    """Plan (and with `apply`, write) the missing decision relations. Returns per-publication counts."""
    store = DynamoStore(table)
    raw = store._get(monitor_id, ROUTER_CONFIG_SK)
    if raw is None:
        raise ValueError(f"no router config for monitor {monitor_id}")
    config = validate_router_config(raw)
    if config["decisions"] != "cyclotron":
        raise ValueError(f"monitor {monitor_id} makes no lab decisions (decisions={config['decisions']})")
    publications = {p["publicationId"]: p for p in config["publications"]}
    wanted = set(publication_ids or ())
    if wanted - set(publications):
        raise ValueError("unknown publication(s): " + ", ".join(sorted(wanted - set(publications))))
    counts: dict[str, Counter] = {pid: Counter() for pid in (wanted or publications)}
    clients: dict[str, Any] = {}
    writes: list[dict] = []
    candidates = [(route, *candidate) for route in (routes() if routes else route_items(table, monitor_id))
                  for candidate in delivered_candidates(route, wanted or None)]
    # A Reference can be delivered by more than one decision (a re-decided item reuses it). The router would have
    # left the latest as the current relation and superseded the rest, so only the latest is backfilled.
    latest: dict[tuple, str] = {}
    for route, pub_id, state, receipt in candidates:
        stamp = str(receipt.get("decidedAt") or state.get("deliveredAt") or "")
        key = (pub_id, state["referenceId"])
        if key not in latest or stamp > latest[key][0]:
            latest[key] = (stamp, receipt["decisionId"])
    candidates.sort(key=lambda c: (c[1], str(c[3].get("decidedAt") or ""), c[0]["sk"]))
    for route, pub_id, state, receipt in candidates:
        tally = counts.setdefault(pub_id, Counter())
        tally["delivered"] += 1
        if latest[(pub_id, state["referenceId"])][1] != receipt["decisionId"]:
            tally["skipped: a later decision on the same Reference"] += 1
            continue
        if since and datetime.fromisoformat(str(state.get("deliveredAt", "")).replace("Z", "+00:00")) < since:
            tally["skipped: before --since"] += 1
            continue
        publication = publications.get(pub_id)
        if publication is None or not all(k in receipt for k in ("decisionId", "label", "output", "fingerprint", "version")):
            tally["skipped: incomplete receipt"] += 1
            emit(f"  ? {pub_id} {route['sk']}: receipt lacks decision fields or publication is no longer configured")
            continue
        if receipt["label"] != publication["positiveLabel"]:
            tally["skipped: not a positive label"] += 1
            continue
        disc = store._get(monitor_id, f"DISC#{route['sourceId']}#{int(route['revision']):06d}")
        if disc is None:
            tally["skipped: discovery missing"] += 1
            continue
        client = clients.get(pub_id) or clients.setdefault(pub_id, appsync(publication["appsyncEndpoint"]))
        reference = client.get_record("Reference", state["referenceId"])
        if not reference:
            tally["skipped: Reference not found"] += 1
            continue
        lineage_id = reference.get("lineageId") or reference["id"]
        existing = [r for r in client.list_by_index("semanticRelationsBySubjectState", f"reference#{lineage_id}#current")
                    if r.get("predicate") == RELEVANCE_RELATION]
        if any(r.get("relationState") == "current" for r in existing):
            tally["skipped: already has a current relation"] += 1
            continue
        if any(json.loads(r.get("metadata") or "{}").get("decisionId") == receipt["decisionId"] for r in existing):
            tally["skipped: decision already recorded (superseded)"] += 1
            continue
        # The decision's own account/run/binding, as the router stamped into provenance at the time.
        decided = route.get("decision") or {}
        cyclotron = {**config["cyclotron"], **{k: decided[k] for k in ("accountId", "runId", "bindingRevision") if decided.get(k)}}
        records = lab_decision_records(client, publication, receipt, {**config, "cyclotron": cyclotron}, reference, disc)
        if not records:
            tally["skipped: decision already current"] += 1
            continue
        tally["planned" if not apply else "written"] += 1
        confidence = receipt.get("confidence")
        emit(f"  {'write' if apply else 'plan '} {pub_id} {state['referenceId']} label={receipt['label']} "
             f"confidence={float(confidence) if confidence is not None else None} decision={receipt['decisionId']} "
             f"fingerprint={receipt['fingerprint']} version={receipt['version']}")
        if apply:
            from .records import apply_record_changes, build_record_changes
            apply_record_changes(client, build_record_changes(client, records))
        writes.append({"publicationId": pub_id, "referenceId": state["referenceId"], "label": receipt["label"],
                       "confidence": float(confidence) if confidence is not None else None})
    emit(f"{'APPLIED' if apply else 'DRY RUN (no writes)'} monitor={monitor_id}")
    for pub_id in sorted(counts):
        emit(f"{pub_id}: " + (", ".join(f"{k}={v}" for k, v in sorted(counts[pub_id].items())) or "nothing delivered"))
    return {"applied": apply, "counts": {p: dict(c) for p, c in counts.items()}, "writes": writes}


def open_table(region: str = "us-east-1", parameter: str = TABLE_PARAMETER):
    """The monitoring table via SSM, refusing any account but production."""
    import boto3
    account = boto3.client("sts", region_name=region).get_caller_identity()["Account"]
    if account != PRODUCTION_ACCOUNT:
        raise SystemExit(f"refusing to run in account {account}; expected {PRODUCTION_ACCOUNT} (use AWS_PROFILE=papyrus-production)")
    name = boto3.client("ssm", region_name=region).get_parameter(Name=parameter)["Parameter"]["Value"]
    return boto3.resource("dynamodb", region_name=region).Table(name)


def command(args) -> int:
    from .monitoring_router import make_appsync_client
    table = open_table()
    result = backfill(table, args.monitor, appsync=make_appsync_client, apply=args.apply,
                      publication_ids=args.publication, since=parse_since(args.since) if args.since else None)
    return 0 if result["counts"] is not None else 1


# --- collection backfill: a Hugging Face monitor's history -----------------------------------------------

BACKFILL_LEASE_SECONDS = 1800
CHUNK_PAGES = 5            # pages read, committed and checkpointed together


def backfill_sorts(config: dict) -> tuple[str, ...]:
    """The Hub cannot filter by date or likes, so a threshold is applied by paging the list sorted by that
    metric until it falls under the minimum. With no thresholds, newest first until the window starts."""
    sorts = tuple(sort for key, sort in (("minLikes", "likes"), ("minDownloads", "downloads")) if config.get(key) is not None)
    return sorts or ("createdAt",)


def backfill_collection(store, monitor_id: str, since: datetime, *, until: datetime | None = None,
                        fetch: Callable | None = None, now: float | None = None, max_pages: int = 50,
                        max_requests: int = 300, apply: bool = False, emit: Callable[[str], None] = print,
                        owner: str | None = None) -> dict:
    """Load the models created in [since, until) that the monitor's CONFIG would accept, through the collector's
    own dedupe (`ITEM#`), so it is idempotent and safe next to the live schedule.

    Bounded by `max_pages` per query and `max_requests` overall; it stops cleanly (`paused`) on either, or on a
    Hub 429. A checkpoint item `BACKFILL#...` keeps each query's cursor, so running the same command again
    continues where it stopped. Dry-run (the default) reads the Hub and counts, and writes nothing.
    """
    raw = store.get_config(monitor_id)
    if raw is None:
        raise ValueError(f"no config for monitor {monitor_id}")
    config = _validate_config(raw)
    if config["sourceType"] != "huggingface-models":
        raise ValueError(f"monitor {monitor_id} reads {config['sourceType']}; backfill-by-window is for huggingface-models")
    if since.tzinfo is None or (until is not None and until.tzinfo is None):
        raise ValueError("--since and --until need a timezone, e.g. 2025-10-25T00:00:00Z")
    now = time.time() if now is None else now
    fetch, run_id = fetch or fetch_hf_page, uuid.uuid4().hex
    queries = plan_queries(config, sorts=backfill_sorts(config))
    scope = _digest([since.isoformat(), [q["key"] for q in queries],
                     {k: config.get(k) for k in ("pipelineTags", "authors", "search", "minLikes", "minDownloads", "pageSize")}])[:10]
    checkpoint_sk = f"BACKFILL#{since.strftime('%Y%m%dT%H%M%SZ')}#{scope}"
    saved = store._get(monitor_id, checkpoint_sk) or {}
    state = {q["key"]: dict((saved.get("queries") or {}).get(q["key"]) or {"next": None, "done": False, "pages": 0, "accepted": 0})
             for q in queries}
    owner = owner or uuid.uuid4().hex
    if apply and not store.acquire_lock(monitor_id, owner, now, BACKFILL_LEASE_SECONDS):
        raise ValueError("the collector (or another backfill) holds this monitor's lock; try again shortly")
    reading, totals = Reading(None, max_requests), Counter()
    try:
        for query in queries:
            entry = state[query["key"]]
            while not entry["done"] and entry["pages"] < max_pages and reading.may_request():
                try:
                    result = read_query(config, query, since, fetch, reading, start_url=entry["next"],
                                        max_pages=min(CHUNK_PAGES, max_pages - entry["pages"]),
                                        stop_below={"likes": config.get("minLikes"), "downloads": config.get("minDownloads")})
                except Exception as error:
                    reading.errors.append({"query": query["key"], "message": str(error)[:300]})
                    emit(f"  ! {query['key']}: {error}")
                    break
                for details in result["items"]:
                    if until is not None and _parse_time(details["createdAt"]) >= until:
                        continue
                    item = hf_item(details)
                    if apply:
                        totals[commit_item(store, monitor_id, config, item, now=now, run_id=run_id)] += 1
                    else:
                        old = store.get_item(monitor_id, item.source_id)
                        totals["unchanged" if old and old["fingerprint"] == item.fingerprint else "would add"] += 1
                    entry["accepted"] += 1
                entry.update(next=result["next"], done=result["done"], pages=entry["pages"] + result["pages"])
                if apply:
                    store.put_item(monitor_id, {"pk": pk(monitor_id), "sk": checkpoint_sk, "since": _iso(since.timestamp()),
                                                "queries": state, "updatedAt": _iso(now), "runId": run_id})
                if result["pages"] == 0:
                    break
            emit(f"  {query['key']}: {'done' if entry['done'] else 'more to read'}, {entry['pages']} pages, {entry['accepted']} accepted")
    finally:
        if apply:
            store.release_lock(monitor_id, owner)
    finished = all(entry["done"] for entry in state.values())
    status = "complete" if finished else "paused"
    emit(f"{'APPLIED' if apply else 'DRY RUN (no writes)'} monitor={monitor_id} since={_iso(since.timestamp())}: "
         f"{status}, {reading.requests} requests, " + (", ".join(f"{k}={v}" for k, v in sorted(totals.items())) or "no models")
         + (f", stopped by {reading.stopped_by}" if reading.stopped_by else "")
         + ("" if finished else (" -- run the same command again to continue" if apply else " -- dry runs do not checkpoint; raise --max-pages/--max-requests to count more")))
    return {"applied": apply, "status": status, "requests": reading.requests, "stoppedBy": reading.stopped_by,
            "counts": dict(totals), "errors": reading.errors, "queries": state, "checkpoint": checkpoint_sk}


def collection_command(args) -> int:
    table = open_table()
    result = backfill_collection(DynamoStore(table), args.monitor, parse_since(args.since),
                                 until=parse_since(args.until) if args.until else None,
                                 max_pages=args.max_pages, max_requests=args.max_requests, apply=args.apply)
    return 1 if result["errors"] else 0
