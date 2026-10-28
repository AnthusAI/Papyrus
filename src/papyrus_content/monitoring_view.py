"""Publication-scoped Monitoring view and explicit email article-resolution action.

The `papyrus-monitoring` stack keeps the collector's and router's state in one DynamoDB table
(docs/monitoring-cloud.md). This module turns that table into the overview an editor reads:
feeds watched, recent runs, the collected queue with routing state, per-publication relevance
and delivery, and observed router decision counts.

Access is least privilege on purpose. The Lambda reads the monitoring table and can write only
the editor-requested resolved destination for one email candidate in the `MONITOR#hn` partition.
The response is
projected field by field, so endpoints, role ARNs, account and run identifiers of the shared
Cyclotron never leave the function. Editors get their own publication only; the whole shared
pipeline is admin-only, and that is enforced here, not only in the browser.

Imports stay light: stdlib, with boto3 (provided by the Lambda runtime) only inside the factory.
"""
from __future__ import annotations

import base64
from datetime import UTC, datetime, timezone
from decimal import Decimal
import http.client
import json
import logging
import os
import re

from .staff_groups import STAFF_GROUPS

LOG = logging.getLogger(__name__)
MONITOR_ID = "hn"
# The table has no registry of monitors and the view may not Scan, so the monitors it can look at are
# named here (override with PAPYRUS_MONITORING_MONITOR_IDS, comma separated). A new monitor is added here.
MONITOR_IDS = ("hn", "ttab", "huggingface", "p-apyr-us-email")
EMAIL_MONITOR_ID_ENV = "PAPYRUS_EMAIL_MONITOR_ID"
MONITOR_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
EDITOR_GROUPS = STAFF_GROUPS
SCOPES = ("publication", "all")
TABLE_PARAMETER = "/papyrus/monitoring/table-name"
# Page sizes, not totals: every list is paged with a cursor ("Load more"), so nothing scrolls out of reach.
ITEM_PAGE_SIZE = 60
RUN_PAGE_SIZE = 15
ROUTER_RUN_PAGE_SIZE = 10
EMAIL_PAGE_SIZE = 20
MAX_ERROR_TEXT = 160
MAX_DECISION_PAGES = 20
LISTS = {"runs": "RUN#", "routerRuns": "ROUTERUN#", "items": "DISC#", "emailSubmissions": "EMAILINDEX#"}
HELD_STATES = {"quarantined", "decision_failed"}
VIEWABLE_EMAIL_STATUSES = {"queued", "processing", "failed", "pending_review", "discarded"}


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
    """Scoped access to one Monitoring partition."""

    def __init__(self, table, monitor_id: str = MONITOR_ID):
        self.table, self.pk = table, f"MONITOR#{monitor_id}"

    def get(self, sk: str):
        item = self.table.get_item(Key={"pk": self.pk, "sk": sk}).get("Item")
        return _clean(item) if item else None

    def _query(self, prefix: str, **extra):
        return self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": self.pk, ":prefix": prefix}, **extra)

    def page(self, prefix: str, limit: int, start: dict | None = None) -> tuple[list[dict], dict | None]:
        """Newest-first rows under a prefix and the key to continue after them, or None at the end.

        One extra row is read so the continuation key exists only when more rows really follow.
        """
        extra = {"ScanIndexForward": False, "Limit": limit + 1}
        if start:
            if start.get("pk") != self.pk:
                raise ValueError("cursor is for another partition")
            extra["ExclusiveStartKey"] = start
        rows = [_clean(item) for item in self._query(prefix, **extra).get("Items", [])]
        if len(rows) <= limit:
            return rows, None
        return rows[:limit], {"pk": rows[limit - 1]["pk"], "sk": rows[limit - 1]["sk"]}

    def decision_times(self) -> tuple[list[str], bool]:
        """Inspected decision timestamps and whether the bounded history query was exhaustive."""
        times, start = [], None
        for _ in range(MAX_DECISION_PAGES):
            extra = {"ProjectionExpression": "sk, #d.decidedAt", "ExpressionAttributeNames": {"#d": "decision"}}
            if start:
                extra["ExclusiveStartKey"] = start
            extra["ScanIndexForward"] = False
            result = self._query("ROUTE#", **extra)
            times += [row["decision"]["decidedAt"] for row in map(_clean, result.get("Items", []))
                      if isinstance(row.get("decision"), dict) and row["decision"].get("decidedAt")]
            start = result.get("LastEvaluatedKey")
            if not start:
                break
        return times, start is None

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

    def email_group_members(self, fingerprint: str) -> list[dict]:
        """The membership rows of one fingerprint group: every received copy of the same email."""
        from .email_fingerprint import MEMBER_PREFIX

        rows, start = [], None
        while True:
            extra = {"ScanIndexForward": True}
            if start:
                extra["ExclusiveStartKey"] = start
            result = self._query(f"{MEMBER_PREFIX}{fingerprint}#", **extra)
            rows.extend(_clean(item) for item in result.get("Items", []))
            start = result.get("LastEvaluatedKey")
            if not start:
                return rows

    def put_email_decision(self, item: dict) -> bool:
        """Create the one decision row for a held message; False when one already exists."""
        try:
            self.table.put_item(Item={**item, "pk": self.pk}, ConditionExpression="attribute_not_exists(pk)")
            return True
        except Exception as error:
            if ("ConditionalCheckFailed" not in str(error)
                    and getattr(error, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException"):
                raise
            return False

    def replace_email_decision(self, item: dict) -> bool:
        """Rewrite a decision row that exists and has not been applied yet (only its reason changes); False when it is gone or applied.

        The receiver writes ``outcome`` when it applies a decision and is the receipt's only writer afterwards, so an applied row is left alone.
        """
        try:
            self.table.put_item(Item={**item, "pk": self.pk}, ConditionExpression="attribute_exists(pk) AND attribute_not_exists(outcome)")
            return True
        except Exception as error:
            if ("ConditionalCheckFailed" not in str(error)
                    and getattr(error, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException"):
                raise
            return False

    def record_email_resolution(self, receipt_digest: str, candidate_index: int, *, url: str, title: str, ttl=None,
                                found_via_search=None):
        """Persist one editor-requested destination so later Reference intake can verify it.

        ``found_via_search`` (query, match score, provider) marks a destination found by searching the headline because the
        original link could not be followed. Editors see it so they can check it; it never contains the original link.
        """
        sk = f"EMAILRESOLVED#{receipt_digest}#{candidate_index:06d}"
        item = {"pk": self.pk, "sk": sk, "receiptDigest": receipt_digest,
                "candidateIndex": candidate_index, "sourceUri": url, "title": title,
                "resolvedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z")}
        if isinstance(ttl, int) and not isinstance(ttl, bool):
            item["ttl"] = ttl
        if found_via_search:
            item["foundViaSearch"] = json.loads(json.dumps(found_via_search), parse_float=Decimal)
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
            return item
        except Exception as error:
            if "ConditionalCheckFailed" not in str(error):
                raise
        current = self.get(sk)
        if not current or current.get("sourceUri") != url:
            raise ValueError("email_candidate_resolution_conflict")
        return current


def _iso(epoch) -> str | None:
    try:
        return datetime.fromtimestamp(float(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _short(text) -> str | None:
    return str(text)[:MAX_ERROR_TEXT] if text else None


def _feed(config: dict | None, state: dict | None, monitor_id: str = MONITOR_ID) -> list[dict]:
    if not config:
        return []
    state = state or {}
    return [{"id": monitor_id, "sourceUrl": config.get("sourceUrl"), "intervalSeconds": config.get("intervalSeconds"),
             "enabled": config.get("enabled", True) is not False,
             "lastStatus": state.get("lastStatus"), "lastFinishedAt": state.get("lastFinishedAt"),
             "nextDueAt": _iso(state.get("nextDueAt"))}]


def _run(row: dict, monitor_id: str = MONITOR_ID) -> dict:
    return {"monitorId": monitor_id, "runId": row.get("runId"), "startedAt": row.get("startedAt"), "finishedAt": row.get("finishedAt"),
            "status": row.get("status"), "new": row.get("new", 0), "revised": row.get("revised", 0),
            "unchanged": row.get("unchanged", 0), "itemCount": row.get("itemCount"), "errorCount": row.get("errorCount", 0),
            "errors": [_short(e.get("message") if isinstance(e, dict) else e) for e in (row.get("errors") or [])[:3]]}


def _router_run(row: dict, monitor_id: str = MONITOR_ID) -> dict:
    feedback = row.get("feedback") if isinstance(row.get("feedback"), dict) else {}
    return {"monitorId": monitor_id, "runId": row.get("runId"), "startedAt": row.get("startedAt"), "mode": row.get("mode"), "status": row.get("status"),
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


def _item(disc: dict, route: dict | None, publications: list[dict], monitor_id: str = MONITOR_ID) -> dict:
    final = (route or {}).get("final") or {}
    decision = (route or {}).get("decision") or {}
    return {"monitorId": monitor_id, "sourceId": disc.get("sourceId"), "revision": disc.get("revision"), "title": disc.get("title"),
            "url": disc.get("canonicalUrl"), "discussionUrl": disc.get("sourceItemUrl"), "observedAt": disc.get("observedAt"),
            "sourcePublishedAt": disc.get("sourcePublishedAt"), "routing": disc.get("routing"),
            "routingNote": _short(final.get("reason")), "decidedAt": decision.get("decidedAt"),
            "relevance": [_relevance(p, route) for p in publications]}


def _email_summary(row: dict, action: dict | None = None, *, now: float | None = None) -> dict:
    import time
    from .email_quarantine import quarantine_summary
    diagnostics = row.get("sesDiagnostics") if isinstance(row.get("sesDiagnostics"), dict) else {}
    verdicts = diagnostics.get("verdicts") if isinstance(diagnostics.get("verdicts"), dict) else {}
    return {"receiptId": row.get("sk"), "observedAt": row.get("observedAt"), "status": row.get("status"),
            "subject": _short(row.get("subject")), "envelopeSender": _short(row.get("sender")),
            "headerFrom": _short(row.get("headerFrom")), "warnings": [str(value) for value in row.get("warnings", [])],
            "verdicts": {key: verdicts.get(key, "UNAVAILABLE") for key in ("spf", "dkim", "dmarc", "spam", "virus")},
            "linkCount": int(row.get("linkCount") or 0), "processedCount": int(row.get("processedCount") or 0),
            "unresolvedLinkCount": int(row.get("unresolvedLinkCount") or 0),
            "reviewRequired": row.get("reviewRequired") is True,
            "errorCode": _short(row.get("errorCode")),
            "quarantine": quarantine_summary(row, action, now=time.time() if now is None else now)}


def _held_action(store, receipt: dict) -> dict | None:
    """The recorded editor decision for a message that is still held, if any."""
    if receipt.get("status") != "pending_review" or not isinstance(receipt.get("sk"), str):
        return None
    from .email_quarantine import action_key
    return store.get(action_key(receipt["sk"]))


def _group_copies(store, receipt: dict, allowed: set) -> list[dict]:
    """Every received copy of this email that is the viewer's to see, newest first (just the receipt if ungrouped)."""
    fingerprint = receipt.get("contentFingerprint")
    found = {receipt["sk"]: receipt}
    if fingerprint:
        for member in store.email_group_members(fingerprint):
            copy_id = member.get("receiptId")
            if not isinstance(copy_id, str) or copy_id in found:
                continue
            copy = store.get(copy_id)
            if (copy and copy.get("emailTrustMode") == "data-only" and copy.get("contentFingerprint") == fingerprint
                    and copy.get("status") in VIEWABLE_EMAIL_STATUSES
                    and allowed.intersection(copy.get("emailDestinationPublicationIds") or [])):
                found[copy_id] = copy
    return sorted(found.values(), key=lambda c: (str(c.get("observedAt")), c["sk"]), reverse=True)


def _group_summary(store, copies: list[dict], *, now: float) -> dict:
    """One list item for all copies of the same email: the copy that needs a decision (else the newest), plus the copies."""
    summaries = [_email_summary(copy, _held_action(store, copy), now=now) for copy in copies]
    held = [s for s in summaries if (s["quarantine"] or {}).get("state") in HELD_STATES]
    shown = dict((held or summaries)[0])
    if len(copies) > 1:
        shown["group"] = {"fingerprint": copies[0].get("contentFingerprint"), "count": len(copies),
                          "copies": [{key: s[key] for key in ("receiptId", "observedAt", "status", "linkCount",
                                                              "processedCount", "quarantine")} for s in summaries]}
    return shown


def _latest_revisions(rows: list[dict]) -> list[dict]:
    latest: dict = {}
    for row in rows:
        key = row.get("sourceId")
        if key not in latest or int(row.get("revision") or 0) > int(latest[key].get("revision") or 0):
            latest[key] = row
    return sorted(latest.values(), key=lambda r: str(r.get("observedAt")), reverse=True)


def _key(row: dict) -> dict:
    return {"pk": row["pk"], "sk": row["sk"]}


def _valid_start(start, list_name: str):
    """A continuation key is two strings in the list's own key range; anything else is a bad request."""
    if start is None:
        return None
    if (not isinstance(start, dict) or set(start) != {"pk", "sk"} or not all(isinstance(v, str) for v in start.values())
            or not start["sk"].startswith(LISTS[list_name])):
        raise ValueError("bad cursor")
    return start


def encode_cursor(starts: dict) -> str | None:
    """One opaque cursor for a list across monitors: only monitors with more rows remain in it."""
    starts = {monitor: key for monitor, key in starts.items() if key}
    if not starts:
        return None
    return base64.urlsafe_b64encode(json.dumps(starts, separators=(",", ":"), sort_keys=True).encode()).decode()


def decode_cursor(cursor) -> dict:
    if cursor in (None, ""):
        return {}
    try:
        starts = json.loads(base64.urlsafe_b64decode(str(cursor).encode()))
    except (ValueError, TypeError):
        raise ValueError("bad cursor") from None
    if not isinstance(starts, dict):
        raise ValueError("bad cursor")
    return starts


class _Routing:
    """What one monitor's router config says about the viewing site: used by every list."""

    def __init__(self, store, email_store, *, site_endpoint, scope):
        self.config, self.state = store.get("CONFIG"), store.get("STATE")
        self.router = store.get("CONFIG#router")
        configured = (self.router or {}).get("publications") or []
        self.own = next((p for p in configured if p.get("appsyncEndpoint") == site_endpoint), None) if site_endpoint else None
        self.selected = configured if scope == "all" else ([self.own] if self.own else [])
        email_router = email_store.get("CONFIG#router")
        if email_router is None and email_store is store:
            email_router = self.router
        self.email_allowed = {
            p["publicationId"] for p in (email_router or {}).get("publications") or []
            if p.get("appsyncEndpoint") == site_endpoint
        } if site_endpoint else set()


def _email_rows(email_store, allowed: set, start, *, held_only: bool, now: float) -> tuple[list[dict], dict | None]:
    """A page of email receipts for this site, newest first, and where to continue.

    Index rows for receipts that are not this site's are skipped without counting. With ``held_only`` the page is filled
    with held messages only, reading as far back as it takes, so an old held message is always reachable.
    """
    out, position, groups = [], start, {}
    while allowed:
        rows, following = email_store.page("EMAILINDEX#", EMAIL_PAGE_SIZE, position)
        for offset, index in enumerate(rows):
            if not allowed.intersection(index.get("destinationPublicationIds") or []):
                continue
            receipt = email_store.get(index.get("receiptId", ""))
            if (not receipt or receipt.get("emailTrustMode") != "data-only"
                    or not allowed.intersection(receipt.get("emailDestinationPublicationIds") or [])):
                continue
            fingerprint = receipt.get("contentFingerprint")
            if fingerprint not in groups or not fingerprint:
                groups[fingerprint] = _group_copies(email_store, receipt, allowed)
            copies = groups[fingerprint] if fingerprint else [receipt]
            if copies[0]["sk"] != receipt["sk"]:
                continue  # an older copy: it is listed with the newest copy of the same email
            summary = _group_summary(email_store, copies, now=now)
            if held_only and not any((c["quarantine"] or {}).get("state") in HELD_STATES
                                     for c in (summary.get("group") or {}).get("copies", [summary])):
                continue
            out.append(summary)
            if len(out) >= EMAIL_PAGE_SIZE:
                return out, (_key(index) if offset + 1 < len(rows) or following else None)
        if not following:
            return out, None
        position = following
    return out, None


def _list_rows(store, email_store, routing: _Routing, name: str, start, *, monitor_id: str, scope: str,
               held_only: bool = False, now: float) -> tuple[list[dict], dict | None, int]:
    """One page of one list for one monitor: rows, the continuation key, and items hidden as not relevant."""
    start = _valid_start(start, name)
    if name == "emailSubmissions":
        rows, following = _email_rows(email_store, routing.email_allowed, start, held_only=held_only, now=now)
        return rows, following, 0
    if name == "runs":
        rows, following = store.page("RUN#", RUN_PAGE_SIZE, start)
        return [_run(r, monitor_id) for r in rows], following, 0
    if name == "routerRuns":
        rows, following = store.page("ROUTERUN#", ROUTER_RUN_PAGE_SIZE, start)
        return [_router_run(r, monitor_id) for r in rows], following, 0
    rows, following = store.page("DISC#", ITEM_PAGE_SIZE, start)
    items, hidden = [], 0
    for disc in _latest_revisions(rows):
        route = store.get(f"ROUTE#{disc.get('sourceId')}#{int(disc.get('revision') or 0):06d}")
        item = _item(disc, route, routing.selected, monitor_id)
        if scope == "publication" and routing.own and item["relevance"] and item["relevance"][0]["relevant"] is False:
            hidden += 1
            continue
        items.append(item)
    return items, following, hidden


def monitoring_overview(store, *, groups, site_endpoint, scope, now, monitor_id: str = MONITOR_ID, email_store=None) -> dict:
    """One monitor's overview, the newest page of each list. `monitoring_site_overview` combines the monitors routed to a site.

    ``cursors`` holds, per list, the key to continue after this page (None when the list ends here).
    """
    groups = set(groups or [])
    if not groups & EDITOR_GROUPS:
        raise Forbidden("monitoring is for editors and admins")
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    is_admin = "admin" in groups
    if scope == "all" and not is_admin:
        raise Forbidden("the whole pipeline is for admins")

    email_store = store if email_store is None else email_store
    routing = _Routing(store, email_store, site_endpoint=site_endpoint, scope=scope)
    pages, cursors, hidden = {}, {}, 0
    for name in LISTS:
        pages[name], cursors[name], more_hidden = _list_rows(
            store, email_store, routing, name, None, monitor_id=monitor_id, scope=scope, now=now)
        hidden += more_hidden
    base = {"asOf": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if not (routing.config or routing.router or pages["items"] or pages["runs"] or hidden):
        return {**base, "state": "empty", "scope": {"mode": scope, "publicationId": None, "site": None, "canViewAll": is_admin},
                "feeds": [], "runs": [], "routerRuns": [], "router": None, "usage": None, "items": [],
                "emailSubmissions": [], "hiddenNotRelevant": 0, "cursors": {}}

    router, own = routing.router, routing.own
    result_scope = {"mode": scope, "publicationId": (own or {}).get("publicationId"), "site": (own or {}).get("site"), "canViewAll": is_admin}
    times, history_complete = store.decision_times()
    today = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
    usage = {"day": today, "decisionsToday": sum(1 for t in times if str(t).startswith(today)),
             "decisionsTotal": len(times), "historyComplete": history_complete}
    out = {**base, "state": "ready", "scope": result_scope, "feeds": _feed(routing.config, routing.state, monitor_id),
           "runs": pages["runs"], "routerRuns": pages["routerRuns"],
           "router": ({"mode": router.get("mode"), "feedback": (router.get("decisions") or "cyclotron") == "cyclotron", "enabled": router.get("enabled", True) is not False} if router else None),
           "usage": usage, "items": pages["items"], "emailSubmissions": pages["emailSubmissions"], "hiddenNotRelevant": hidden,
           "cursors": cursors}
    if scope == "publication" and not own:
        out["notice"] = "publication_not_routed"
    return out


SORT_KEYS = {"runs": "startedAt", "routerRuns": "startedAt", "items": "observedAt", "emailSubmissions": "observedAt"}


def _newest(rows, key):
    return sorted(rows, key=lambda r: str(r.get(key)), reverse=True)


def monitoring_site_overview(stores: dict, *, groups, site_endpoint, scope, now) -> dict:
    """The page: only the monitors whose router config lists this site's publication.

    `stores` maps monitor id to its store. In publication scope a monitor that does not route to
    this site contributes nothing but its id, listed under `otherMonitors` (no items, runs or
    counts). An admin's whole-pipeline scope combines every monitor. Each list is the newest page
    from every monitor, with one cursor per list for `monitoring_list_page`.
    """
    parts, others = [], []
    for monitor_id, store in stores.items():
        part = monitoring_overview(store, groups=groups, site_endpoint=site_endpoint, scope=scope, now=now, monitor_id=monitor_id)
        if part["state"] == "empty":
            continue
        if scope == "publication" and part.get("notice") == "publication_not_routed":
            others.append(monitor_id)
            continue
        parts.append((monitor_id, part))
    base = {"asOf": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    is_admin = "admin" in set(groups or [])
    if not parts:
        out = {**base, "state": "ready" if others else "empty",
               "scope": {"mode": scope, "publicationId": None, "site": None, "canViewAll": is_admin},
               "feeds": [], "runs": [], "routerRuns": [], "router": None, "usage": None, "items": [],
               "emailSubmissions": [], "hiddenNotRelevant": 0, "otherMonitors": others, "cursors": {}}
        if others:
            out["notice"] = "publication_not_routed"
        return out

    usage = None
    for _, part in parts:
        if part["usage"]:
            usage = usage or {"day": part["usage"]["day"], "decisionsToday": 0, "decisionsTotal": 0, "historyComplete": True}
            usage["decisionsToday"] += part["usage"]["decisionsToday"]
            usage["decisionsTotal"] += part["usage"]["decisionsTotal"]
            usage["historyComplete"] = usage["historyComplete"] and part["usage"]["historyComplete"]
    combined = {name: _newest([r for _, part in parts for r in part[name]], SORT_KEYS[name]) for name in LISTS}
    return {**base, "state": "ready", "scope": parts[0][1]["scope"],
            "feeds": [f for _, part in parts for f in part["feeds"]],
            **combined,
            "router": next((part["router"] for _, part in parts if part["router"]), None),
            "usage": usage,
            "hiddenNotRelevant": sum(part["hiddenNotRelevant"] for _, part in parts),
            "cursors": {name: encode_cursor({monitor_id: part["cursors"].get(name) for monitor_id, part in parts}) for name in LISTS},
            "otherMonitors": others}


def monitoring_list_page(stores: dict, *, list_name, cursor, groups, site_endpoint, scope, now, held_only=False) -> dict:
    """The next page of one list, across the monitors the cursor still has rows in.

    ``cursor=None`` starts the list from its newest row (used by the Held-for-review filter, which restarts the email
    list with only held messages). Returns ``rows``, the same row shape as the overview, and a ``cursor`` that is None
    when the list is exhausted.
    """
    if not set(groups or []) & EDITOR_GROUPS:
        raise Forbidden("monitoring is for editors and admins")
    if list_name not in LISTS or scope not in SCOPES or (held_only and list_name != "emailSubmissions"):
        raise ValueError("bad request")
    if scope == "all" and "admin" not in set(groups or []):
        raise Forbidden("the whole pipeline is for admins")
    starts = decode_cursor(cursor)
    if cursor in (None, ""):
        wanted = dict.fromkeys(stores)
    else:
        if set(starts) - set(stores):
            raise ValueError("bad cursor")
        wanted = starts
    rows, following, hidden = [], {}, 0
    for monitor_id, start in wanted.items():
        store = stores[monitor_id]
        routing = _Routing(store, store, site_endpoint=site_endpoint, scope=scope)
        if scope == "publication" and not routing.own and not routing.email_allowed:
            continue  # a monitor that does not route to this site contributes nothing
        monitor_rows, following[monitor_id], more_hidden = _list_rows(
            store, store, routing, list_name, start, monitor_id=monitor_id, scope=scope, held_only=held_only, now=now)
        rows += monitor_rows
        hidden += more_hidden
    return {"list": list_name, "rows": _newest(rows, SORT_KEYS[list_name]), "cursor": encode_cursor(following),
            "hiddenNotRelevant": hidden}


def _authorized_receipt(store, *, groups, site_endpoint, receipt_id, statuses=None):
    """The receipt and publication, only for an editor of an explicitly routed destination."""
    if not set(groups or []) & EDITOR_GROUPS:
        raise Forbidden("email submissions are for editors and admins")
    router = store.get("CONFIG#router") or {}
    publication = next((p for p in router.get("publications", [])
                        if site_endpoint and p.get("appsyncEndpoint") == site_endpoint), None)
    if not publication:
        raise Forbidden("site endpoint is not a configured publication")
    row = store.get(receipt_id)
    if (not row or row.get("status") not in (statuses or VIEWABLE_EMAIL_STATUSES)
            or row.get("emailTrustMode") != "data-only"
            or publication["publicationId"] not in (row.get("emailDestinationPublicationIds") or [])):
        raise Forbidden("email receipt is outside this publication")
    return row, publication


def monitoring_email_submission(store, *, groups, site_endpoint, receipt_id) -> dict:
    """Return one safe rendering only to an editor of an explicitly routed destination."""
    if not set(groups or []) & EDITOR_GROUPS:
        raise Forbidden("email submissions are for editors and admins")
    if not isinstance(receipt_id, str) or not re.fullmatch(r"EMAIL#[a-f0-9]{64}", receipt_id):
        return {"error": "bad_request"}
    row, publication = _authorized_receipt(store, groups=groups, site_endpoint=site_endpoint, receipt_id=receipt_id)
    details = store.email_details(receipt_id.removeprefix("EMAIL#"))
    body = "".join(item.get("text", "") for item in details if "#BODY#" in item.get("sk", ""))
    links = []
    for item in details:
        if "#LINKS#" in item.get("sk", ""):
            links.extend(json.loads(item.get("json", "[]")))
    # Stored receipts may predate branded-wrapper recognition. Normalize only
    # this authorized detail response; never rewrite the receipt or follow links.
    from .email_submission import normalize_email_candidate
    links = [normalize_email_candidate(link) for link in links]
    return {"submission": {**_email_summary(row, _held_action(store, row)), "corpusId": publication.get("corpusId")},
            "safeBodyText": body, "candidateLinks": links, "sourceMaterialIsUntrusted": True}


def email_submission_accepted(submission: dict) -> bool:
    """True once a message is accepted: it never needed review, or an editor released it.

    A held, discarded or expired message is read-only: nothing is resolved or imported from it.
    """
    held = submission.get("quarantine")
    return held is None or held.get("state") == "released"


def monitoring_decide_email_submission(store, arguments, identity, *, groups, site_endpoint) -> dict:
    """Accept (release) or reject (discard) one held message; the receiver applies it.

    Only a validated editor or admin of a publication the message is routed to may decide.
    Nothing in the message, its sender or its authentication signals is consulted.
    """
    from .email_quarantine import RECEIPT_ID, action_key, request_decision, request_group_decision
    from .reference_intake_validation import IntakeError, _actor

    if not set(groups or []) & EDITOR_GROUPS:
        raise Forbidden("email submissions are for editors and admins")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return {"error": "bad_request"}
    if (not isinstance(arguments, dict) or set(arguments) - {"receiptId", "decision", "reason"}
            or not isinstance(arguments.get("receiptId"), str) or not RECEIPT_ID.fullmatch(arguments["receiptId"])):
        return {"error": "bad_request"}
    try:
        actor = _actor(identity)
    except IntakeError:
        raise Forbidden("a validated editor session is required") from None
    claims = (identity or {}).get("claims") or {}
    email = claims.get("email") if isinstance(claims.get("email"), str) else None
    row, publication = _authorized_receipt(store, groups=groups, site_endpoint=site_endpoint,
                                           receipt_id=arguments["receiptId"])
    fingerprint = row.get("contentFingerprint")
    if not fingerprint or store.get(action_key(row["sk"])):
        # Not fingerprinted yet, or already decided on its own before grouping existed.
        return request_decision(store, receipt=row, receipt_id=arguments["receiptId"],
                                decision=arguments.get("decision"), reason=arguments.get("reason"),
                                actor=actor, actor_email=email, publication_id=publication["publicationId"])
    # One decision covers every copy of the same email.
    copies = _group_copies(store, row, {publication["publicationId"]})
    return request_group_decision(store, copies=copies, fingerprint=fingerprint,
                                  decision=arguments.get("decision"), reason=arguments.get("reason"),
                                  actor=actor, actor_email=email, publication_id=publication["publicationId"])


def _explore_article(link: dict, submission: dict):
    """Follow a selected wrapper to its article, or find the article by its headline when the wrapper cannot be followed.

    Public http(s) only (link_exploration checks every hop and connects to the address it verified). The destination must also pass
    the intake's own editorial-address check, so an account action or a private-looking address is never offered for import.
    """
    from .email_submission import safe_editorial_url
    from .link_exploration import Context, explore

    return explore(
        link["url"], Context(title=str(link.get("title") or ""), sender=str(submission.get("sender") or "")),
        want_text=False, accept=safe_editorial_url,
    )


def monitoring_email_resolve_article_link(store, *, groups, site_endpoint, receipt_id, candidate_index, resolver=None):
    """Resolve exactly one selected, supported article wrapper from an authorized receipt."""
    from .email_submission import (
        RedirectResolutionError,
        is_supported_email_tracking_url,
    )

    detail = monitoring_email_submission(store, groups=groups, site_endpoint=site_endpoint, receipt_id=receipt_id)
    if "submission" not in detail:
        return detail
    if not email_submission_accepted(detail["submission"]):
        return {"error": "quarantined"}
    if type(candidate_index) is not int or not 0 <= candidate_index < len(detail["candidateLinks"]):
        return {"error": "bad_request"}
    link = detail["candidateLinks"][candidate_index]
    if link.get("resolutionStatus") != "unresolved" or not is_supported_email_tracking_url(link.get("url", "")):
        return {"error": "not_resolvable"}
    digest = receipt_id.removeprefix("EMAIL#")
    saved = store.get(f"EMAILRESOLVED#{digest}#{candidate_index:06d}")
    if saved:
        if (saved.get("receiptDigest") != digest or saved.get("candidateIndex") != candidate_index
                or (isinstance(saved.get("ttl"), int) and saved["ttl"] <= int(datetime.now(UTC).timestamp()))):
            return {"error": "resolution_failed", "reason": "resolution_record_invalid"}
        recorded = {"url": saved.get("sourceUri"), "title": str(saved.get("title") or ("" if str(link.get("title") or "").lower().startswith(("http://", "https://")) else link.get("title")) or "")[:1000],
                    "resolved": True}
        return {**recorded, "foundVia": "search", "search": saved["foundViaSearch"]} if saved.get("foundViaSearch") else recorded
    exploration = None
    title = str(link.get("title") or "")[:1000]
    if title.lower().startswith(("http://", "https://")):
        title = ""  # an anchor-less link is titled with its own (subscriber-specific) address; never echo or record it
    try:
        if resolver:
            destination = resolver(link["url"])
        else:
            exploration = _explore_article(link, detail["submission"])
            if not exploration.ok:
                LOG.warning("email article link resolution failed: %s", exploration.failure)
                return {"error": "resolution_failed", "reason": exploration.failure}
            destination = exploration.url
    except RedirectResolutionError as error:
        LOG.warning("email article link resolution rejected: %s", error.code)
        return {"error": "resolution_failed", "reason": error.code}
    except (OSError, TimeoutError, http.client.HTTPException) as error:
        LOG.error("email article link resolution failed: %s", type(error).__name__)
        return {"error": "resolution_failed", "reason": "redirect_request_failed"}
    found = exploration.search.as_dict() if exploration and exploration.via == "search" and exploration.search else None
    try:
        # Keep the AWS SDK imports local so importing this Lambda module remains lightweight.
        from botocore.exceptions import BotoCoreError, ClientError

        store.record_email_resolution(
            digest, candidate_index, url=destination,
            title=title, ttl=store.get(receipt_id).get("ttl"),
            found_via_search=found,
        )
    except (BotoCoreError, ClientError, ValueError) as error:
        LOG.error("email article resolution could not be recorded: %s", type(error).__name__)
        return {"error": "resolution_failed", "reason": "resolution_not_recorded"}
    result = {"url": destination, "title": title, "resolved": True}
    return {**result, "foundVia": "search", "search": found} if found else result


# --- the Lambda boundary --------------------------------------------------------------------------

_table_name_cache: dict[str, str] = {}


def default_store_factory(env, *, monitor_id=MONITOR_ID):
    """Finds the table through the SSM parameter the monitoring stack writes. None when it is absent."""
    default_id = monitor_id

    def factory(monitor_id: str | None = None):
        monitor_id = monitor_id or default_id
        import boto3  # provided by the Lambda runtime
        parameter = env.get("PAPYRUS_MONITORING_TABLE_PARAMETER") or TABLE_PARAMETER
        region = env.get("PAPYRUS_MONITORING_REGION") or env.get("AWS_REGION") or "us-east-1"
        if parameter not in _table_name_cache:
            ssm = boto3.client("ssm", region_name=region)
            try:
                _table_name_cache[parameter] = ssm.get_parameter(Name=parameter)["Parameter"]["Value"]
            except ssm.exceptions.ParameterNotFound:
                return None
        return TableViewStore(boto3.resource("dynamodb", region_name=region).Table(_table_name_cache[parameter]), monitor_id)
    return factory


def _monitor_ids(env) -> tuple[str, ...]:
    configured = [m.strip() for m in (env.get("PAPYRUS_MONITORING_MONITOR_IDS") or "").split(",") if m.strip()]
    return tuple(configured) or MONITOR_IDS


def configured_email_monitor_id(env) -> str:
    """Read the deployed, server-owned email partition name; never accept it from a request."""
    monitor_id = str(env.get(EMAIL_MONITOR_ID_ENV) or MONITOR_ID).strip()
    if not MONITOR_ID_PATTERN.fullmatch(monitor_id):
        raise ValueError("invalid configured email monitor id")
    return monitor_id


def default_email_store_factory(env):
    """Create the private intake partition store, distinct from the shared Monitoring view."""
    monitor_id = configured_email_monitor_id(env)
    return default_store_factory(env, monitor_id=monitor_id)


def handle(event: dict, *, env=None, store_factory=None, email_store_factory=None, now: float | None = None) -> dict:
    """AppSync resolver entry: `monitoringOverview(scope)`. Errors are states, never stack traces."""
    import time
    env = os.environ if env is None else env
    groups = (event.get("identity") or {}).get("groups")
    groups = [g for g in groups if isinstance(g, str)] if isinstance(groups, list) else []
    field_name = event.get("fieldName")
    info = event.get("info")
    nested_field = info.get("fieldName") if isinstance(info, dict) else None
    if field_name is not None and nested_field is not None and field_name != nested_field:
        return {"error": "bad_request"}
    field_name = field_name if field_name is not None else nested_field
    if not isinstance(field_name, str) or field_name not in {"monitoringOverview", "monitoringEmailSubmission", "monitoringResolveEmailArticleLink", "monitoringQueueEmailReference", "monitoringDecideEmailSubmission", "monitoringPage"}:
        return {"error": "bad_request"}
    args = event.get("arguments") or {}
    scope = args.get("scope") or "publication"
    if (not set(groups) & EDITOR_GROUPS
            or (field_name in ("monitoringOverview", "monitoringPage") and scope == "all" and "admin" not in groups)):
        return {"error": "forbidden"}
    if field_name in ("monitoringOverview", "monitoringPage") and scope not in SCOPES:
        return {"error": "bad_request"}
    try:
        make_store = store_factory or default_store_factory(env)
        if field_name in ("monitoringEmailSubmission", "monitoringResolveEmailArticleLink", "monitoringQueueEmailReference",
                          "monitoringDecideEmailSubmission"):
            email_monitor_id = configured_email_monitor_id(env)
            if email_monitor_id == MONITOR_ID and email_store_factory is None:
                email_store = make_store(MONITOR_ID)
            else:
                email_store = (email_store_factory or default_email_store_factory(env))()
            if email_store is None:
                return {"state": "not_configured"}
        if field_name == "monitoringEmailSubmission":
            return monitoring_email_submission(email_store, groups=groups,
                                               site_endpoint=env.get("PAPYRUS_GRAPHQL_ENDPOINT"),
                                               receipt_id=args.get("receiptId"))
        if field_name == "monitoringDecideEmailSubmission":
            return monitoring_decide_email_submission(
                email_store, {"receiptId": args.get("receiptId"), "decision": args.get("decision"),
                              "reason": args.get("reason")},
                event.get("identity") or {}, groups=groups, site_endpoint=env.get("PAPYRUS_GRAPHQL_ENDPOINT"))
        if field_name == "monitoringQueueEmailReference":
            from .email_reference_handoff import queue_email_reference
            from .reference_intake_validation import IntakeError
            try:
                payload = args.get("input")
                if isinstance(payload, str):
                    payload = json.loads(payload)
                return queue_email_reference(email_store, payload, event.get("identity") or {},
                                             endpoint=env.get("PAPYRUS_GRAPHQL_ENDPOINT"))
            except IntakeError as error:
                return {"error": "handoff_rejected", "message": str(error)}
        if field_name == "monitoringResolveEmailArticleLink":
            return monitoring_email_resolve_article_link(
                email_store, groups=groups, site_endpoint=env.get("PAPYRUS_GRAPHQL_ENDPOINT"),
                receipt_id=args.get("receiptId"), candidate_index=args.get("candidateIndex"),
            )
        if field_name not in ("monitoringOverview", "monitoringPage"):
            return {"error": "bad_request"}
        stores = {monitor_id: make_store(monitor_id) for monitor_id in _monitor_ids(env)}
        if any(store is None for store in stores.values()):
            return {"state": "not_configured"}
        if field_name == "monitoringPage":
            try:
                return monitoring_list_page(
                    stores, list_name=args.get("list"), cursor=args.get("cursor"), groups=groups,
                    site_endpoint=env.get("PAPYRUS_GRAPHQL_ENDPOINT"), scope=scope, now=time.time() if now is None else now,
                    held_only=args.get("filter") == "held")
            except ValueError:
                return {"error": "bad_request"}
        return monitoring_site_overview(stores, groups=groups, site_endpoint=env.get("PAPYRUS_GRAPHQL_ENDPOINT"), scope=scope,
                                        now=time.time() if now is None else now)
    except Forbidden:
        return {"error": "forbidden"}
    except Exception as error:   # the browser gets a state; the cause goes to the log by type only
        LOG.error("monitoring overview failed: %s", type(error).__name__)
        return {"state": "unavailable"}
