"""An in-memory monitoring table shaped like the live one, for the Monitoring page's read path.

Used by test_monitoring_view.py and features_backend/monitoring-view.feature. The router config
carries endpoints and a role ARN on purpose: the page must never return them.
"""
from copy import deepcopy

NOW = 1_792_550_400.0      # 2026-10-21T02:40:00Z
APP_ANTH = "https://anth0.appsync-api.us-east-1.amazonaws.com/graphql"
APP_PAPYRUS = "https://papy1.appsync-api.us-east-1.amazonaws.com/graphql"
APP_TI = "https://ti002.appsync-api.us-east-1.amazonaws.com/graphql"
PK = "MONITOR#hn"
SECRET_MARKERS = ("execute-api", "role/cyclotron-machine-invoker", "appsync-api", "acct-1", "run-1")


def disc(source_id, title, routing, observed="2026-10-21T01:00:00.000000Z", revision=1):
    return {"pk": PK, "sk": f"DISC#{source_id}#{revision:06d}", "sourceId": source_id, "revision": revision, "title": title,
            "canonicalUrl": f"https://example.org/{source_id}", "sourceItemUrl": f"https://news.ycombinator.com/item?id={source_id}",
            "observedAt": observed, "sourcePublishedAt": observed, "routing": routing, "fingerprint": f"fp-{source_id}"}


def decision(decided_at, publications):
    return {"decisionId": "dec-1", "decidedAt": decided_at, "accountId": "acct-1", "runId": "run-1",
            "publications": {pid: {"output": f"{pid}-relevance", "label": label, "fingerprint": "f", "version": 3,
                                   **({"confidence": conf} if conf is not None else {})}
                             for pid, (label, conf) in publications.items()}}


def route(source_id, decided_at=None, publications=None, delivered=None, **extra):
    row = {"pk": PK, "sk": f"ROUTE#{source_id}#000001", "sourceId": source_id, "revision": 1, "itemId": f"hn-{source_id}"}
    if decided_at:
        row["decision"] = decision(decided_at, publications)
    if delivered is not None:
        row["publications"] = delivered
    row.update(extra)
    return row


def rows():
    router = {"pk": PK, "sk": "CONFIG#router", "mode": "live", "maxItemsPerRun": 5, "feedback": True, "enabled": True,
              "publications": [
                  {"publicationId": "anth-us", "site": "anth.us", "appsyncEndpoint": APP_ANTH},
                  {"publicationId": "p-apyr-us", "site": "p.apyr.us", "appsyncEndpoint": APP_PAPYRUS, "corpusId": "knowledge-corpus-ai-ml-research"},
                  {"publicationId": "threat-intelligence", "site": "threat-intelligence", "appsyncEndpoint": APP_TI}],
              "cyclotron": {"endpoint": "https://o01d28uizl.execute-api.us-east-1.amazonaws.com", "accountId": "acct-1", "runId": "run-1",
                            "bindingRevision": "1", "roleArn": "arn:aws:iam::682849160744:role/cyclotron-machine-invoker", "pollSeconds": 45}}
    table = [
        {"pk": PK, "sk": "CONFIG", "sourceUrl": "https://news.ycombinator.com/rss", "intervalSeconds": 900, "limit": 30, "enabled": True},
        {"pk": PK, "sk": "STATE", "nextDueAt": 1_792_551_000, "lastRunId": "r3", "lastStatus": "complete", "lastFinishedAt": "2026-10-21T02:33:00Z"},
        router,
        {"pk": PK, "sk": "RUN#2026-10-21T02:18:00.000000Z#r1", "runId": "r1", "startedAt": "2026-10-21T02:18:00.000000Z", "finishedAt": "2026-10-21T02:18:03Z",
         "status": "complete", "new": 0, "revised": 0, "unchanged": 30, "itemCount": 30, "errorCount": 0, "errors": []},
        {"pk": PK, "sk": "RUN#2026-10-21T02:33:00.000000Z#r3", "runId": "r3", "startedAt": "2026-10-21T02:33:00.000000Z", "finishedAt": "2026-10-21T02:33:02Z",
         "status": "complete", "new": 2, "revised": 1, "unchanged": 27, "itemCount": 30, "errorCount": 0, "errors": []},
        {"pk": PK, "sk": "RUN#2026-10-21T02:03:00.000000Z#r0", "runId": "r0", "startedAt": "2026-10-21T02:03:00.000000Z", "finishedAt": "2026-10-21T02:03:01Z",
         "status": "partial", "new": 1, "revised": 0, "unchanged": 28, "itemCount": 30, "errorCount": 1, "errors": [{"message": "ConnectionError: timeout"}]},
        {"pk": PK, "sk": "ROUTERUN#2026-10-21T02:37:00.000000Z#q2", "runId": "q2", "startedAt": "2026-10-21T02:37:00.000000Z", "mode": "live",
         "status": "stopped", "stoppedBy": "request_ceiling_reached", "errors": [],
         "counts": {"decided": 1, "delivered": 1, "deliveryFailed": 1, "error": 0, "examined": 3, "refused": 0, "routed": 1, "uncertain": 0, "dryRunValidated": 0},
         "feedback": {"status": "complete", "sent": 1, "pending": 0, "skipped": 0, "failed": 0, "stoppedBy": None}},
        disc("101", "Quantum paper on arXiv", "routed", "2026-10-21T00:10:00.000000Z"),
        disc("102", "A recipe for sourdough", "routed", "2026-10-21T00:40:00.000000Z"),
        disc("103", "Phishing kit leaks", "decided", "2026-10-20T23:00:00.000000Z"),
        disc("104", "Fresh Show HN", "collected", "2026-10-21T02:30:00.000000Z"),
        disc("105", "Broken request", "error", "2026-10-21T01:30:00.000000Z"),
        route("101", "2026-10-21T01:00:00Z", {"anth-us": ("include", 0.91), "p-apyr-us": ("exclude", 0.8), "threat-intelligence": ("include", None)},
              {"anth-us": {"label": "include", "delivered": True, "attempts": 1, "referenceId": "ref-1", "referenceLineageId": "lin-1", "deliveredAt": "2026-10-21T01:00:05Z"},
               "threat-intelligence": {"label": "include", "delivered": True, "attempts": 1, "referenceId": "ref-2", "referenceLineageId": "lin-2", "deliveredAt": "2026-10-21T01:00:06Z"}}),
        route("102", "2026-10-21T01:05:00Z", {"anth-us": ("exclude", 0.97), "p-apyr-us": ("exclude", 0.95), "threat-intelligence": ("exclude", 0.9)}, {}),
        route("103", "2026-10-20T23:10:00Z", {"anth-us": ("include", 0.7), "p-apyr-us": ("exclude", 0.6), "threat-intelligence": ("include", 0.88)},
              {"anth-us": {"label": "include", "delivered": False, "attempts": 2, "lastError": "ClientError: throttled"},
               "threat-intelligence": {"label": "include", "delivered": True, "attempts": 1, "referenceId": "ref-3", "referenceLineageId": "lin-3", "deliveredAt": "2026-10-20T23:10:09Z"}}),
        route("105", final={"routing": "error", "reason": "invalid request: bad title", "at": "2026-10-21T01:31:00Z"}),
    ]
    return deepcopy(table)


class FakeViewStore:
    """The read interface monitoring_view needs; refuses nothing because it can write nothing."""

    def __init__(self, table=None):
        self.table = {r["sk"]: r for r in (rows() if table is None else table)}

    def get(self, sk):
        return deepcopy(self.table.get(sk))

    def newest(self, prefix, limit):
        found = sorted((r for sk, r in self.table.items() if sk.startswith(prefix)), key=lambda r: r["sk"], reverse=True)
        return deepcopy(found[:limit])

    def email_details(self, receipt_digest):
        prefix = f"EMAILDETAIL#{receipt_digest}#"
        found = sorted((r for sk, r in self.table.items() if sk.startswith(prefix)), key=lambda r: r["sk"])
        return deepcopy(found)

    def decision_times(self):
        return ([r["decision"]["decidedAt"] for sk, r in sorted(self.table.items())
                 if sk.startswith("ROUTE#") and r.get("decision")], True)


def only_hn(store):
    """Store factory for the handler: the fixture is the hn monitor; other monitors have nothing."""
    return lambda monitor_id="hn": store if monitor_id == "hn" else FakeViewStore([])


def ttab_rows(endpoint, monitor="ttab"):
    """A second monitor routed to a single publication (distinctive, or p.apyr.us for huggingface)."""
    pk = f"MONITOR#{monitor}"
    publication = ("distinctive", "distinctive") if endpoint not in (APP_PAPYRUS,) else ("p-apyr-us", "p.apyr.us")
    title = "Decision on a mark" if monitor == "ttab" else "Model release"
    return deepcopy([
        {"pk": pk, "sk": "CONFIG", "sourceType": "x", "sourceUrl": f"https://{monitor}.example.org/feed", "intervalSeconds": 3600, "limit": 30, "enabled": True},
        {"pk": pk, "sk": "CONFIG#router", "mode": "live", "feedback": False, "enabled": True,
         "publications": [{"publicationId": publication[0], "site": publication[1], "appsyncEndpoint": endpoint}]},
        {"pk": pk, "sk": "RUN#2026-10-21T02:20:00.000000Z#t1", "runId": "t1", "startedAt": "2026-10-21T02:20:00.000000Z",
         "status": "complete", "new": 1, "revised": 0, "unchanged": 0, "itemCount": 1, "errorCount": 0, "errors": []},
        {"pk": pk, "sk": f"DISC#{monitor}-1#000001", "sourceId": f"{monitor}-1", "revision": 1, "title": title,
         "canonicalUrl": f"https://{monitor}.example.org/1", "sourceItemUrl": None, "observedAt": "2026-10-21T02:00:00.000000Z",
         "sourcePublishedAt": "2026-10-21T02:00:00.000000Z", "routing": "collected", "fingerprint": f"fp-{monitor}"},
    ])
