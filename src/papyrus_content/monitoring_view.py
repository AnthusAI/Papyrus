"""Read-only view of the monitoring pipeline for the newsroom's Monitoring page (PPY-31ba52).

The `papyrus-monitoring` stack keeps the collector's and router's state in one DynamoDB table
(docs/monitoring-cloud.md). This module turns that table into the overview an editor reads:
feeds watched, recent runs, the collected queue with routing state, per-publication relevance
and delivery, and usage against the Cyclotron ceilings.

Access is least privilege on purpose. The Lambda that calls this holds `dynamodb:GetItem` and
`dynamodb:Query` on that one table and nothing else. Nothing here can write. The response is
projected field by field, so endpoints, role ARNs, account and run identifiers of the shared
Cyclotron never leave the function. Editors get their own publication only; the whole shared
pipeline is admin-only, and that is enforced here, not only in the browser.

Imports stay light: stdlib, with boto3 (provided by the Lambda runtime) only inside the factory.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
import os
import re

LOG = logging.getLogger(__name__)
MONITOR_ID = "hn"
EDITOR_GROUPS = frozenset({"editor", "admin"})
SCOPES = ("publication", "all")
TABLE_PARAMETER = "/papyrus/monitoring/table-name"
MAX_ITEMS = 60
MAX_RUNS = 15
MAX_ROUTER_RUNS = 10
MAX_ERROR_TEXT = 160
MAX_DECISION_PAGES = 20
MAX_EMAIL_SUBMISSIONS = 20


class Forbidden(Exception):
    """The caller is not allowed to read this view."""


def _clean(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


class TableViewStore:
    """The only table access: `get_item` and `query`. It has no write method to call."""

    def __init__(self, table, monitor_id: str = MONITOR_ID):
        self.table, self.pk = table, f"MONITOR#{monitor_id}"

    def get(self, sk: str):
        item = self.table.get_item(Key={"pk": self.pk, "sk": sk}).get("Item")
        return _clean(item) if item else None

    def _query(self, prefix: str, **extra):
        return self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": self.pk, ":prefix": prefix}, **extra)

    def newest(self, prefix: str, limit: int) -> list[dict]:
        result = self._query(prefix, ScanIndexForward=False, Limit=limit)
        return [_clean(item) for item in result.get("Items", [])]

    def decision_times(self) -> list[str]:
        """`decidedAt` of every routed item (the router's ceilings are small, so this stays small)."""
        times, start = [], None
        for _ in range(MAX_DECISION_PAGES):
            extra = {"ProjectionExpression": "sk, #d.decidedAt", "ExpressionAttributeNames": {"#d": "decision"}}
            if start:
                extra["ExclusiveStartKey"] = start
            result = self._query("ROUTE#", **extra)
            times += [row["decision"]["decidedAt"] for row in map(_clean, result.get("Items", []))
                      if isinstance(row.get("decision"), dict) and row["decision"].get("decidedAt")]
            start = result.get("LastEvaluatedKey")
            if not start:
                break
        return times

    def email_details(self, receipt_digest: str) -> list[dict]:
        """Read private, inert rendering chunks for one bounded email receipt."""
        prefix, rows, start = f"EMAILDETAIL#{receipt_digest}#", [], None
        while True:
            extra = {"ScanIndexForward": True}
            if start:
                extra["ExclusiveStartKey"] = start
            result = self._query(prefix, **extra)
            rows.extend(_clean(item) for item in result.get("Items", []))
            start = result.get("LastEvaluatedKey")
            if not start:
                return rows


def _iso(epoch) -> str | None:
    try:
        return datetime.fromtimestamp(float(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _short(text) -> str | None:
    return str(text)[:MAX_ERROR_TEXT] if text else None


def _ceilings(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    out = {key: int(raw[key]) for key in ("decisionsTotal", "decisionsPerDay", "items")
           if isinstance(raw.get(key), (int, float)) and not isinstance(raw.get(key), bool) and raw[key] > 0}
    return out or None


def _feed(config: dict | None, state: dict | None) -> list[dict]:
    if not config:
        return []
    state = state or {}
    return [{"id": MONITOR_ID, "sourceUrl": config.get("sourceUrl"), "intervalSeconds": config.get("intervalSeconds"),
             "limit": config.get("limit"), "enabled": config.get("enabled", True) is not False,
             "lastStatus": state.get("lastStatus"), "lastFinishedAt": state.get("lastFinishedAt"),
             "nextDueAt": _iso(state.get("nextDueAt"))}]


def _run(row: dict) -> dict:
    return {"runId": row.get("runId"), "startedAt": row.get("startedAt"), "finishedAt": row.get("finishedAt"),
            "status": row.get("status"), "new": row.get("new", 0), "revised": row.get("revised", 0),
            "unchanged": row.get("unchanged", 0), "itemCount": row.get("itemCount"), "errorCount": row.get("errorCount", 0),
            "errors": [_short(e.get("message") if isinstance(e, dict) else e) for e in (row.get("errors") or [])[:3]]}


def _router_run(row: dict) -> dict:
    feedback = row.get("feedback") if isinstance(row.get("feedback"), dict) else {}
    return {"runId": row.get("runId"), "startedAt": row.get("startedAt"), "mode": row.get("mode"), "status": row.get("status"),
            "stoppedBy": row.get("stoppedBy"), "counts": row.get("counts") or {},
            "waitingForClassifier": [str(p) for p in (row.get("waitingForClassifier") or [])],
            "errorCount": len(row.get("errors") or []),
            "feedback": {key: feedback.get(key) for key in ("status", "sent", "pending", "skipped", "failed")}}


def _relevance(publication: dict, route: dict | None) -> dict:
    pid = publication["publicationId"]
    row = {"publicationId": pid, "site": publication.get("site"), "relevant": None, "label": None, "confidence": None,
           "delivery": {"state": None}}
    decided = ((route or {}).get("decision") or {}).get("publications", {}).get(pid)
    if not decided:
        return row
    row["label"] = decided.get("label")
    confidence = decided.get("confidence")
    row["confidence"] = confidence if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else None
    row["relevant"] = decided.get("label") == (publication.get("positiveLabel") or "include")
    if not row["relevant"]:
        row["delivery"] = {"state": "not_applicable"}
        return row
    state = ((route or {}).get("publications") or {}).get(pid) or {}
    if state.get("delivered"):
        row["delivery"] = {"state": "delivered", "referenceId": state.get("referenceId"),
                           "referenceLineageId": state.get("referenceLineageId") or state.get("referenceId"),
                           "deliveredAt": state.get("deliveredAt")}
    elif state.get("lastError"):
        row["delivery"] = {"state": "failed", "error": _short(state["lastError"]), "attempts": state.get("attempts")}
    else:
        row["delivery"] = {"state": "pending"}
    return row


def _item(disc: dict, route: dict | None, publications: list[dict]) -> dict:
    final = (route or {}).get("final") or {}
    decision = (route or {}).get("decision") or {}
    return {"sourceId": disc.get("sourceId"), "revision": disc.get("revision"), "title": disc.get("title"),
            "url": disc.get("canonicalUrl"), "discussionUrl": disc.get("sourceItemUrl"), "observedAt": disc.get("observedAt"),
            "sourcePublishedAt": disc.get("sourcePublishedAt"), "routing": disc.get("routing"),
            "routingNote": _short(final.get("reason")), "decidedAt": decision.get("decidedAt"),
            "relevance": [_relevance(p, route) for p in publications]}


def _email_summary(row: dict) -> dict:
    diagnostics = row.get("sesDiagnostics") if isinstance(row.get("sesDiagnostics"), dict) else {}
    verdicts = diagnostics.get("verdicts") if isinstance(diagnostics.get("verdicts"), dict) else {}
    return {"receiptId": row.get("sk"), "observedAt": row.get("observedAt"), "status": row.get("status"),
            "subject": _short(row.get("subject")), "envelopeSender": _short(row.get("sender")),
            "headerFrom": _short(row.get("headerFrom")), "warnings": [str(value) for value in row.get("warnings", [])],
            "verdicts": {key: verdicts.get(key, "UNAVAILABLE") for key in ("spf", "dkim", "dmarc", "spam", "virus")},
            "linkCount": int(row.get("linkCount") or 0), "processedCount": int(row.get("processedCount") or 0),
            "unresolvedLinkCount": int(row.get("unresolvedLinkCount") or 0),
            "reviewRequired": row.get("reviewRequired") is True,
            "errorCode": _short(row.get("errorCode"))}


def _latest_revisions(rows: list[dict]) -> list[dict]:
    latest: dict = {}
    for row in rows:
        key = row.get("sourceId")
        if key not in latest or int(row.get("revision") or 0) > int(latest[key].get("revision") or 0):
            latest[key] = row
    return sorted(latest.values(), key=lambda r: str(r.get("observedAt")), reverse=True)


def monitoring_overview(store, *, groups, site_endpoint, scope, now) -> dict:
    groups = set(groups or [])
    if not groups & EDITOR_GROUPS:
        raise Forbidden("monitoring is for editors and admins")
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    is_admin = "admin" in groups
    if scope == "all" and not is_admin:
        raise Forbidden("the whole pipeline is for admins")

    config, state = store.get("CONFIG"), store.get("STATE")
    router = store.get("CONFIG#router")
    discoveries = _latest_revisions(store.newest("DISC#", MAX_ITEMS))
    runs = [_run(r) for r in store.newest("RUN#", MAX_RUNS)]
    router_runs = [_router_run(r) for r in store.newest("ROUTERUN#", MAX_ROUTER_RUNS)]
    base = {"asOf": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if not (config or router or discoveries or runs):
        return {**base, "state": "empty", "scope": {"mode": scope, "publicationId": None, "site": None, "canViewAll": is_admin},
                "feeds": [], "runs": [], "routerRuns": [], "router": None, "usage": None, "items": [],
                "emailSubmissions": [], "hiddenNotRelevant": 0}

    configured = (router or {}).get("publications") or []
    own = next((p for p in configured if p.get("appsyncEndpoint") == site_endpoint), None) if site_endpoint else None
    selected = configured if scope == "all" else ([own] if own else [])
    allowed_publications = {p["publicationId"] for p in selected}
    submissions = []
    for index in store.newest("EMAILINDEX#", MAX_EMAIL_SUBMISSIONS):
        if not allowed_publications.intersection(index.get("destinationPublicationIds") or []):
            continue
        receipt = store.get(index.get("receiptId", ""))
        if (not receipt or receipt.get("emailTrustMode") != "data-only"
                or not allowed_publications.intersection(receipt.get("emailDestinationPublicationIds") or [])):
            continue
        submissions.append(_email_summary(receipt))
    result_scope = {"mode": scope, "publicationId": (own or {}).get("publicationId"), "site": (own or {}).get("site"), "canViewAll": is_admin}

    routes = {(r.get("sourceId"), r.get("revision")): r for r in store.newest("ROUTE#", MAX_ITEMS * 2)}
    items, hidden = [], 0
    for disc in discoveries:
        item = _item(disc, routes.get((disc.get("sourceId"), disc.get("revision"))), selected)
        if scope == "publication" and own and item["relevance"] and item["relevance"][0]["relevant"] is False:
            hidden += 1
            continue
        items.append(item)

    times = store.decision_times()
    today = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
    usage = {"day": today, "decisionsToday": sum(1 for t in times if str(t).startswith(today)), "decisionsTotal": len(times),
             "ceilings": _ceilings((router or {}).get("ceilings"))}
    out = {**base, "state": "ready", "scope": result_scope, "feeds": _feed(config, state), "runs": runs, "routerRuns": router_runs,
           "router": ({"mode": router.get("mode"), "feedback": router.get("feedback") is True, "enabled": router.get("enabled", True) is not False,
                       "maxItemsPerRun": router.get("maxItemsPerRun")} if router else None),
           "usage": usage, "items": items, "emailSubmissions": submissions, "hiddenNotRelevant": hidden}
    if scope == "publication" and not own:
        out["notice"] = "publication_not_routed"
    return out


def monitoring_email_submission(store, *, groups, site_endpoint, receipt_id) -> dict:
    """Return one safe rendering only to an editor of an explicitly routed destination."""
    if not set(groups or []) & EDITOR_GROUPS:
        raise Forbidden("email submissions are for editors and admins")
    if not isinstance(receipt_id, str) or not re.fullmatch(r"EMAIL#[a-f0-9]{64}", receipt_id):
        return {"error": "bad_request"}
    router = store.get("CONFIG#router") or {}
    publication = next((p for p in router.get("publications", [])
                        if site_endpoint and p.get("appsyncEndpoint") == site_endpoint), None)
    if not publication:
        raise Forbidden("site endpoint is not a configured publication")
    row = store.get(receipt_id)
    publication_id = publication["publicationId"]
    if (not row or row.get("status") not in {"queued", "processing", "failed", "pending_review"}
            or row.get("emailTrustMode") != "data-only"
            or publication_id not in (row.get("emailDestinationPublicationIds") or [])):
        raise Forbidden("email receipt is outside this publication")
    details = store.email_details(receipt_id.removeprefix("EMAIL#"))
    body = "".join(item.get("text", "") for item in details if "#BODY#" in item.get("sk", ""))
    links = []
    for item in details:
        if "#LINKS#" in item.get("sk", ""):
            links.extend(json.loads(item.get("json", "[]")))
    return {"submission": _email_summary(row), "safeBodyText": body,
            "candidateLinks": links, "sourceMaterialIsUntrusted": True}


# --- the Lambda boundary --------------------------------------------------------------------------

_table_name_cache: dict[str, str] = {}


def default_store_factory(env):
    """Finds the table through the SSM parameter the monitoring stack writes. None when it is absent."""
    def factory():
        import boto3  # provided by the Lambda runtime
        parameter = env.get("PAPYRUS_MONITORING_TABLE_PARAMETER") or TABLE_PARAMETER
        region = env.get("PAPYRUS_MONITORING_REGION") or env.get("AWS_REGION") or "us-east-1"
        if parameter not in _table_name_cache:
            ssm = boto3.client("ssm", region_name=region)
            try:
                _table_name_cache[parameter] = ssm.get_parameter(Name=parameter)["Parameter"]["Value"]
            except ssm.exceptions.ParameterNotFound:
                return None
        return TableViewStore(boto3.resource("dynamodb", region_name=region).Table(_table_name_cache[parameter]))
    return factory


def handle(event: dict, *, env=None, store_factory=None, now: float | None = None) -> dict:
    """AppSync resolver entry: `monitoringOverview(scope)`. Errors are states, never stack traces."""
    import time
    env = os.environ if env is None else env
    groups = (event.get("identity") or {}).get("groups")
    groups = [g for g in groups if isinstance(g, str)] if isinstance(groups, list) else []
    field_name = (event.get("info") or {}).get("fieldName", "monitoringOverview")
    args = event.get("arguments") or {}
    scope = args.get("scope") or "publication"
    if (not set(groups) & EDITOR_GROUPS
            or (field_name == "monitoringOverview" and scope == "all" and "admin" not in groups)):
        return {"error": "forbidden"}
    if field_name == "monitoringOverview" and scope not in SCOPES:
        return {"error": "bad_request"}
    try:
        store = (store_factory or default_store_factory(env))()
        if store is None:
            return {"state": "not_configured"}
        if field_name == "monitoringEmailSubmission":
            return monitoring_email_submission(store, groups=groups,
                                               site_endpoint=env.get("PAPYRUS_GRAPHQL_ENDPOINT"),
                                               receipt_id=args.get("receiptId"))
        if field_name != "monitoringOverview":
            return {"error": "bad_request"}
        return monitoring_overview(store, groups=groups, site_endpoint=env.get("PAPYRUS_GRAPHQL_ENDPOINT"), scope=scope,
                                   now=time.time() if now is None else now)
    except Forbidden:
        return {"error": "forbidden"}
    except Exception as error:   # the browser gets a state; the cause goes to the log by type only
        LOG.error("monitoring overview failed: %s", type(error).__name__)
        return {"state": "unavailable"}
