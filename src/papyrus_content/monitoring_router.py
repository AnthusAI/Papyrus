"""Cloud HN router (PPY-3212f1 step 4): collected discoveries -> Cyclotron -> References queues.

Reads discoveries the collector left at `routing: collected`, asks the shared Cyclotron
for one decision per item (one `decide` per publication binding; the bindings share one
native decision), and delivers items a publication's relevance output labels `include`
into THAT publication's newsroom References queue as `pending`, through the existing
`ReferenceIntake` over IAM-signed AppSync. A feedback pass reports editors' later
accept/reject decisions back to Cyclotron when `router.feedback` is enabled.

Everything (mode, endpoints, publications, account, run, binding revision) is data in the
`CONFIG#router` table item (docs/monitoring-cloud.md); nothing here hard-codes it.
`dry-run` mode never calls Cyclotron and never writes to a publication.

Imports stay light: stdlib, boto3/botocore (Lambda runtime) and the existing modules.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit
import uuid

from .monitoring import Monitor, SourceItem, _iso
from .monitoring_cloud import ConditionFailed, DynamoStore, pk

CONTRACT_VERSION = "cyclotron-publication/v1"
ROUTER_CONFIG_SK = "CONFIG#router"
ROUTER_LOCK_SK = "LOCK#router"
LEASE_SECONDS = 660                    # longer than the 600 s Lambda timeout
RECEIPT_TTL_SECONDS = 30 * 86400
MAX_REQUEST_BYTES = 32_768
MAX_PENDING_JOB_SECONDS = 6 * 3600
MIN_REMAINING_SECONDS = 120            # do not start another item with less time than this
WORKER_ACTOR = "papyrus-monitoring-worker"   # the intake's own curation actor; never a human
PARTITION_COLLECTED = "collected"
PARTITION_DRY_RUN = "dry-run-validated"
PARTITION_DECIDED = "decided"
FEEDBACK_PARTITION = "FEEDBACK#hn#pending"
ROUTING_FINAL = ("routed", "refused", "uncertain", "error")
NON_CONSUMING_REFUSALS = frozenset({"provider_key_unavailable", "request_ceiling_reached", "standing_capacity_reached"})
STOP_CODES = frozenset({"provider_key_unavailable", "request_ceiling_reached", "standing_capacity_reached", "run_busy"})
PENDING_STATUSES = frozenset({"pending", "queued", "running", "accepted", "in_progress"})
SOURCE_ID = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
PUBLICATION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
APPSYNC_HOST = re.compile(r"^[a-z0-9]+\.appsync-api\.[a-z0-9-]+\.amazonaws\.com$")
EXECUTE_API_HOST = re.compile(r"^[a-z0-9]+\.execute-api\.([a-z0-9-]+)\.amazonaws\.com$")
ROLE_ARN = re.compile(r"^arn:aws:iam::\d{12}:role/[\w+=,.@/-]{1,200}$")


class StopSweep(Exception):
    """A condition that must stop the whole sweep cleanly (no retry storm)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code, self.detail = code, detail


class ItemRefused(Exception):
    pass


class ItemUncertain(Exception):
    pass


class ItemInvalid(Exception):
    pass


# --- config ---------------------------------------------------------------------------------------

def validate_router_config(raw: dict) -> dict:
    mode = raw.get("mode")
    if mode not in ("dry-run", "live"):
        raise ValueError("router mode must be dry-run or live")
    maximum = int(raw.get("maxItemsPerRun", 5))
    if not 1 <= maximum <= 25:
        raise ValueError("router maxItemsPerRun must be between 1 and 25")
    cyclotron = raw.get("cyclotron") or {}
    endpoint = urlsplit(str(cyclotron.get("endpoint") or ""))
    match = EXECUTE_API_HOST.match(endpoint.netloc)
    if (endpoint.scheme != "https" or not match or endpoint.path not in ("", "/") or endpoint.query
            or endpoint.fragment):
        raise ValueError("router cyclotron.endpoint must be an https execute-api origin")
    account = str(cyclotron.get("accountId") or "").strip()
    revision = str(cyclotron.get("bindingRevision") or "").strip()
    if not account or not revision:
        raise ValueError("router cyclotron accountId and bindingRevision are required")
    run_id = str(cyclotron.get("runId") or "").strip()
    role_arn = str(cyclotron.get("roleArn") or "").strip()
    if mode == "live" and not ROLE_ARN.match(role_arn):
        raise ValueError("router cyclotron.roleArn (the machine invoker role) is required in live mode")
    poll = int(cyclotron.get("pollSeconds", 45))
    if not 5 <= poll <= 240:
        raise ValueError("router cyclotron.pollSeconds must be between 5 and 240")
    publications, seen = [], set()
    for entry in raw.get("publications") or []:
        publication_id = str(entry.get("publicationId") or "")
        site = str(entry.get("site") or "").strip()
        endpoint_url = urlsplit(str(entry.get("appsyncEndpoint") or ""))
        if (not PUBLICATION_ID.match(publication_id) or publication_id in seen or not site
                or endpoint_url.scheme != "https" or not APPSYNC_HOST.match(endpoint_url.netloc)
                or endpoint_url.path != "/graphql" or endpoint_url.query or endpoint_url.fragment):
            raise ValueError(f"router publication {publication_id or '?'} is invalid or duplicated")
        seen.add(publication_id)
        corpus_id = str(entry.get("corpusId") or f"knowledge-corpus-{publication_id}")
        publications.append({
            "publicationId": publication_id, "site": site, "appsyncEndpoint": entry["appsyncEndpoint"],
            "corpusId": corpus_id, "corpusKey": corpus_id.removeprefix("knowledge-corpus-"),
            "output": str(entry.get("output") or f"{publication_id}-relevance"),
            "positiveLabel": str(entry.get("positiveLabel") or "include"),
            "negativeLabel": str(entry.get("negativeLabel") or "exclude")})
    if not publications:
        raise ValueError("router needs at least one publication")
    return {"mode": mode, "enabled": raw.get("enabled", True) is not False, "maxItemsPerRun": maximum,
            "feedback": raw.get("feedback") is True, "publications": publications,
            "cyclotron": {"endpoint": f"https://{endpoint.netloc}", "region": match.group(1), "accountId": account,
                          "runId": run_id, "bindingRevision": revision, "roleArn": role_arn, "pollSeconds": poll}}


# --- request building -------------------------------------------------------------------------------

def request_id(account_id: str, run_id: str, publication_id: str, binding_revision: str, item_id: str,
               fingerprint: str, attempt: int = 0) -> str:
    """Deterministic: the same item revision against the same binding always has the same id.

    `attempt` is 0 until Cyclotron refuses a job without consuming any provider request (key missing,
    ceiling reached). Cyclotron keeps a refused job under its request id, so a later retry needs a new one.
    """
    parts = [account_id, run_id, f"{publication_id}@{binding_revision}", item_id, fingerprint]
    if attempt:
        parts.append(f"attempt-{attempt}")
    text = "\n".join(parts)
    return sha256(text.encode()).hexdigest()


def build_item(discovery: dict) -> dict:
    source_id = str(discovery.get("sourceId") or "")
    title, url = str(discovery.get("title") or ""), str(discovery.get("canonicalUrl") or "")
    if not SOURCE_ID.match(source_id) or not title.strip() or len(title) > 1000 or not url or len(url) > 2048:
        raise ItemInvalid("discovery is not a valid Cyclotron item")
    return {"id": f"hn-{source_id}", "values": {
        "title": title, "url": url, "source": "hacker-news",
        "sourceItemUrl": str(discovery.get("sourceItemUrl") or ""), "text": f"{title}\n{url}"}}


def build_decide_request(config: dict, publication: dict, discovery: dict, attempt: int = 0) -> dict:
    cyclotron, item = config["cyclotron"], build_item(discovery)
    body = {"contractVersion": CONTRACT_VERSION, "operation": "decide",
            "requestId": request_id(cyclotron["accountId"], cyclotron["runId"], publication["publicationId"],
                                    cyclotron["bindingRevision"], item["id"], str(discovery["fingerprint"]), attempt),
            "payload": {"bindingRevision": cyclotron["bindingRevision"], "item": item}}
    validate_request(body)
    return {"path": f"/machine/publications/{publication['publicationId']}/operations", "body": body}


def validate_request(body: dict) -> None:
    """Structural validation of a machine-API body; raises ValueError on anything off-contract."""
    if body.get("contractVersion") != CONTRACT_VERSION:
        raise ValueError("wrong contract version")
    if body.get("operation") not in ("decide", "feedback", "status"):
        raise ValueError("unknown operation")
    request = body.get("requestId")
    if body["operation"] != "status" and (not isinstance(request, str) or not 8 <= len(request) <= 128):
        raise ValueError("requestId must be 8 to 128 characters")
    payload = body.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if body["operation"] == "decide":
        item = payload.get("item") or {}
        values = item.get("values") or {}
        if set(payload) != {"bindingRevision", "item"} or not payload["bindingRevision"]:
            raise ValueError("decide payload shape")
        if set(item) != {"id", "values"} or not str(item["id"]).startswith("hn-"):
            raise ValueError("decide item shape")
        if set(values) != {"title", "url", "source", "sourceItemUrl", "text"} or values["source"] != "hacker-news":
            raise ValueError("decide item values shape")
        if any(not isinstance(v, str) or not v for v in values.values()) or values["text"] != f"{values['title']}\n{values['url']}":
            raise ValueError("decide item values content")
    elif body["operation"] == "feedback":
        required = {"bindingRevision", "itemId", "itemRevision", "output", "label", "editor"}
        if not required <= set(payload) or set(payload) - required - {"comment"}:
            raise ValueError("feedback payload shape")
        editor = payload["editor"]
        if not isinstance(editor, dict) or set(editor) != {"site", "subject"} or not all(editor.values()):
            raise ValueError("feedback editor shape")
    if len(json.dumps(body, separators=(",", ":")).encode()) > MAX_REQUEST_BYTES:
        raise ValueError("request body is too large")


# --- Cyclotron machine API ------------------------------------------------------------------------

def default_http(method: str, url: str, headers: dict, body: bytes | None, timeout: float):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw, status = response.read(), response.status
    except urllib.error.HTTPError as error:
        raw, status = error.read(), error.code
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        payload = {"unparsed": True}
    return status, payload if isinstance(payload, dict) else {"unparsed": True}


def assume_invoker(config: dict) -> Callable[[], dict]:
    """Credentials of the Cyclotron machine invoker role, cached until shortly before expiry."""
    cache: dict = {}

    def credentials():
        if cache.get("expires", 0) - time.time() < 120:
            import boto3  # provided by the Lambda runtime
            result = boto3.client("sts").assume_role(
                RoleArn=config["cyclotron"]["roleArn"], RoleSessionName="papyrus-monitoring-router",
                DurationSeconds=900)["Credentials"]
            cache.update(value={"key": result["AccessKeyId"], "secret": result["SecretAccessKey"],
                                "token": result["SessionToken"]}, expires=result["Expiration"].timestamp())
        return cache["value"]
    return credentials


def sigv4_signer(config: dict, credentials: Callable[[], dict]) -> Callable[[str, str, bytes], dict]:
    def sign(method: str, url: str, body: bytes) -> dict:
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.credentials import Credentials
        creds = credentials()
        request = AWSRequest(method=method, url=url, data=body, headers={
            "content-type": "application/json", "x-cyclotron-account": config["cyclotron"]["accountId"]})
        SigV4Auth(Credentials(creds["key"], creds["secret"], creds["token"]), "execute-api",
                  config["cyclotron"]["region"]).add_auth(request)
        return {str(k): str(v) for k, v in request.headers.items()}
    return sign


def refusal_code(status: int, payload: dict) -> str:
    error = payload.get("error")
    code = payload.get("code") or (error.get("code") if isinstance(error, dict) else error)
    return str(code) if isinstance(code, str) and code else f"http_{status}"


class CyclotronClient:
    def __init__(self, config: dict, *, sign: Callable[[str, str, bytes], dict], http=default_http,
                 sleep=time.sleep, clock=time.monotonic):
        self.config, self.sign, self.http, self.sleep, self.clock = config, sign, http, sleep, clock
        self.base = config["cyclotron"]["endpoint"]

    def _call(self, method: str, path: str, body: dict | None):
        data = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
        url = self.base + path
        return self.http(method, url, self.sign(method, url, data), data or None, 30)

    def classify(self, status: int, payload: dict) -> Exception:
        code = refusal_code(status, payload)
        if code == "source_refused":
            return ItemRefused(code)
        if code in STOP_CODES or status in (401, 403, 404, 429, 503, 507, 409):
            return StopSweep(code, f"http {status}")
        if status in (400, 413, 422):
            return ItemInvalid(code)
        return ItemUncertain(code)

    def post(self, publication_id: str, body: dict) -> tuple[str | None, dict | None]:
        """Returns (jobId, None) for an accepted job, or (None, completed response) for a synchronous result.
        A POST is never repeated: a transport failure or ambiguous answer raises ItemUncertain."""
        try:
            status, payload = self._call("POST", f"/machine/publications/{quote(publication_id)}/operations", body)
        except (OSError, TimeoutError) as error:
            raise ItemUncertain(f"no answer: {type(error).__name__}") from error
        if status in (200, 201, 202) and isinstance(payload.get("jobId"), str) and payload["jobId"]:
            return payload["jobId"], None
        if status == 200 and payload.get("decision"):
            return None, payload
        raise self.classify(status, payload)

    def _transient(self, status: int, payload: dict) -> bool:
        if status == 0 or status == 202 or str(payload.get("status") or "") in PENDING_STATUSES:
            return True
        return status >= 500 and status != 503 and refusal_code(status, payload) not in STOP_CODES

    def poll(self, publication_id: str, job_id: str) -> dict:
        """Polls only. Returns the completed response; raises StopSweep('pending') when still running."""
        deadline = self.clock() + self.config["cyclotron"]["pollSeconds"]
        delay = 1.0
        while True:
            try:
                status, payload = self._call("GET", f"/machine/publications/{quote(publication_id)}/commands/{quote(job_id)}", None)
            except (OSError, TimeoutError):
                status, payload = 0, {}
            if status == 200 and payload.get("decision"):
                return payload
            if not self._transient(status, payload):
                raise self.classify(status, payload)
            if self.clock() + delay > deadline:
                raise StopSweep("pending", "job still running")
            self.sleep(delay)
            delay = min(delay * 1.5, 8.0)

    def feedback(self, publication_id: str, body: dict) -> dict:
        """Feedback is idempotent by requestId, so an uncertain send may be retried by the next run."""
        job, completed = self.post_feedback(publication_id, body)
        return completed if completed is not None else self.poll_feedback(publication_id, job)

    def post_feedback(self, publication_id: str, body: dict):
        try:
            status, payload = self._call("POST", f"/machine/publications/{quote(publication_id)}/operations", body)
        except (OSError, TimeoutError) as error:
            raise ItemUncertain(f"no answer: {type(error).__name__}") from error
        if status == 200 and not payload.get("jobId"):
            return None, payload
        if status in (200, 201, 202) and isinstance(payload.get("jobId"), str):
            return payload["jobId"], None
        raise self.classify(status, payload)

    def poll_feedback(self, publication_id: str, job_id: str) -> dict:
        deadline = self.clock() + self.config["cyclotron"]["pollSeconds"]
        delay = 1.0
        while True:
            try:
                status, payload = self._call("GET", f"/machine/publications/{quote(publication_id)}/commands/{quote(job_id)}", None)
            except (OSError, TimeoutError):
                status, payload = 0, {}
            if status == 200 and not self._transient(status, payload):
                return payload
            if not self._transient(status, payload):
                raise self.classify(status, payload)
            if self.clock() + delay > deadline:
                raise ItemUncertain("feedback job still running")
            self.sleep(delay)
            delay = min(delay * 1.5, 8.0)


def checked_decision(response: dict, publication: dict, config: dict, item_id: str) -> dict:
    """Validate one completed `decide` response and reduce it to the receipt we keep."""
    decision = response.get("decision") if isinstance(response, dict) else None
    if not isinstance(decision, dict) or not isinstance(decision.get("decisionId"), str) or not decision["decisionId"]:
        raise ItemInvalid("response has no decisionId")
    if decision.get("itemId") not in (None, item_id):
        raise ItemInvalid("decision is for a different item")
    for key, expected in (("publicationId", publication["publicationId"]),
                          ("bindingRevision", config["cyclotron"]["bindingRevision"])):
        if response.get(key) not in (None, expected):
            raise ItemInvalid(f"response {key} mismatch")
    classifier = (decision.get("classifiers") or {}).get(publication["output"])
    if (not isinstance(classifier, dict) or classifier.get("label") not in (publication["positiveLabel"], publication["negativeLabel"])
            or not isinstance(classifier.get("fingerprint"), str) or not classifier["fingerprint"]
            or type(classifier.get("version")) is not int):
        raise ItemInvalid("response lacks a valid labelled output with fingerprint and version")
    source = response.get("source") if isinstance(response.get("source"), dict) else {}
    return {"decisionId": decision["decisionId"], "output": publication["output"], "label": classifier["label"],
            "fingerprint": classifier["fingerprint"], "version": classifier["version"],
            "source": {k: source[k] for k in ("id", "revision", "fingerprint") if k in source}}


# --- table ----------------------------------------------------------------------------------------

class RouterStore(DynamoStore):
    """Adds the router's keys to the collector's store (see docs/monitoring-cloud.md).

    pk=MONITOR#<id>  sk=CONFIG#router        router config as data
                     sk=LOCK#router          lease for the router/feedback invocation
                     sk=ROUTE#<sourceId>#<rev>   dry-run receipt, jobs, decision receipt, per-publication delivery
                     sk=DELIV#<pub>#<referenceId> a Reference this router delivered (feedback source)
                     sk=FB#<requestId>       feedback receipt
                     sk=ROUTERUN#<startedAt>#<runId>  run receipt (30 days)
    The `routing` GSI also lists `ROUTING#<id>#dry-run-validated`, `...#decided` and `FEEDBACK#<id>#pending`.
    """

    def get_router_config(self, monitor_id):
        return self._get(monitor_id, ROUTER_CONFIG_SK)

    def get_any(self, monitor_id, sk):
        return self._get(monitor_id, sk)

    def put_any(self, monitor_id, record):
        self.table.put_item(Item=record)

    def acquire_router_lock(self, monitor_id, owner, now, lease=LEASE_SECONDS) -> bool:
        try:
            self._conditional_put({"pk": pk(monitor_id), "sk": ROUTER_LOCK_SK, "owner": owner,
                                   "acquiredAt": _iso(now), "expiresAt": int(now + lease)},
                                  "attribute_not_exists(pk) OR expiresAt < :now", {":now": int(now)})
            return True
        except ConditionFailed:
            return False

    def release_router_lock(self, monitor_id, owner):
        try:
            self.table.delete_item(Key={"pk": pk(monitor_id), "sk": ROUTER_LOCK_SK},
                                   ConditionExpression="#o = :owner", ExpressionAttributeNames={"#o": "owner"},
                                   ExpressionAttributeValues={":owner": owner})
        except Exception as error:
            if getattr(error, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise

    def query_partition(self, partition: str, limit: int) -> list[dict]:
        """Oldest first from the sparse `routing` GSI."""
        result = self.table.query(IndexName="routing", KeyConditionExpression="gsi1pk = :p",
                                  ExpressionAttributeValues={":p": partition}, ScanIndexForward=True, Limit=limit)
        return [self._clean(item) for item in result.get("Items", [])]


def gsi_partition(monitor_id: str, name: str) -> str:
    return f"ROUTING#{monitor_id}#{name}"


def set_routing(store, monitor_id: str, disc: dict, routing: str, partition: str | None) -> dict:
    """Write the discovery's routing; a None partition removes it from the GSI (final)."""
    updated = {k: v for k, v in disc.items() if k not in ("gsi1pk",)}
    updated["routing"] = routing
    if partition:
        updated["gsi1pk"] = gsi_partition(monitor_id, partition)
    else:
        updated.pop("gsi1sk", None)
    store.put_any(monitor_id, updated)
    return updated


def route_key(disc: dict) -> str:
    return f"ROUTE#{disc['sourceId']}#{int(disc['revision']):06d}"


def new_route(monitor_id: str, disc: dict) -> dict:
    return {"pk": pk(monitor_id), "sk": route_key(disc), "sourceId": disc["sourceId"], "revision": int(disc["revision"]),
            "fingerprint": disc["fingerprint"], "itemId": f"hn-{disc['sourceId']}"}


def short(error: Exception) -> str:
    return f"{type(error).__name__}: {str(error)[:300]}"


# --- AppSync access and delivery --------------------------------------------------------------------

def make_appsync_client(endpoint: str):
    os.environ.setdefault("PAPYRUS_GRAPHQL_AUTH", "iam")
    from .graphql_authoring import PapyrusGraphQLAuthoringClient
    from .graphql_http import iam_signed_graphql_headers
    return PapyrusGraphQLAuthoringClient(endpoint=endpoint, header_factory=lambda body: iam_signed_graphql_headers(endpoint, body))


def editorial_context_receipt(client, publication: dict) -> dict:
    """The publication's editorial context hash, or null with the reason (never fails the run)."""
    try:
        from .editorial_context import resolve_editorial_context
        pack = resolve_editorial_context(client, endpoint=publication["appsyncEndpoint"],
                                         publication_key=publication["corpusKey"])
        return {"contextHash": pack["contextHash"], "reason": None}
    except Exception as error:
        return {"contextHash": None, "reason": short(error)[:200]}


def deliver_reference(client, publication: dict, disc: dict, decision: dict, config: dict) -> dict:
    """The existing ReferenceIntake: pending Reference + provenance Message recording the machine decision."""
    from .monitoring_intake import ReferenceIntake
    monitor = Monitor("hn", publication["corpusKey"], publication["corpusId"], publication["appsyncEndpoint"],
                      Path("/nonexistent"))
    item = SourceItem(str(disc["sourceId"]), disc["title"], disc["canonicalUrl"], disc["sourceItemUrl"],
                      disc.get("sourcePublishedAt"))
    if item.fingerprint != disc["fingerprint"]:
        raise ItemInvalid("stored fingerprint does not match the discovery")
    provenance = {**monitor.binding, "sourceId": item.source_id, "sourceItemUrl": item.source_item_url,
                  "fingerprint": item.fingerprint, "observedAt": disc["observedAt"], "revision": int(disc["revision"]),
                  "machineDecision": {
                      "kind": "machine decision", "system": "cyclotron", "decisionId": decision["decisionId"],
                      "output": decision["output"], "label": decision["label"],
                      "fingerprint": decision["fingerprint"], "version": decision["version"],
                      "accountId": config["cyclotron"]["accountId"], "runId": config["cyclotron"]["runId"],
                      "bindingRevision": config["cyclotron"]["bindingRevision"]}}
    return ReferenceIntake(client, monitor, auth_mode="iam")(item, provenance)


# --- the run ----------------------------------------------------------------------------------------

class Router:
    def __init__(self, store, config: dict, *, monitor_id="hn", now: float, run_id: str,
                 cyclotron: CyclotronClient | None, appsync: Callable[[str], Any], deliver=deliver_reference,
                 context_receipt=editorial_context_receipt, time_left: Callable[[], float] = lambda: 1e9):
        self.store, self.config, self.monitor_id, self.now, self.run_id = store, config, monitor_id, now, run_id
        self.cyclotron, self.appsync_factory, self.deliver = cyclotron, appsync, deliver
        self.context_receipt, self.time_left = context_receipt, time_left
        self._clients: dict = {}
        self._contexts: dict = {}
        self.publications = {p["publicationId"]: p for p in config["publications"]}
        self.counts = {"examined": 0, "dryRunValidated": 0, "decided": 0, "delivered": 0, "routed": 0,
                       "refused": 0, "uncertain": 0, "error": 0, "deliveryFailed": 0}

    def client(self, publication: dict):
        endpoint = publication["appsyncEndpoint"]
        if endpoint not in self._clients:
            self._clients[endpoint] = self.appsync_factory(endpoint)
        return self._clients[endpoint]

    def context_for(self, publication: dict) -> dict:
        key = publication["publicationId"]
        if key not in self._contexts:
            try:
                self._contexts[key] = self.context_receipt(self.client(publication), publication)
            except Exception as error:
                self._contexts[key] = {"contextHash": None, "reason": short(error)[:200]}
        return self._contexts[key]

    def get_route(self, disc: dict) -> dict:
        return self.store.get_any(self.monitor_id, route_key(disc)) or new_route(self.monitor_id, disc)

    def save(self, route: dict):
        self.store.put_any(self.monitor_id, route)

    # candidates -----------------------------------------------------------------------------------

    def candidates(self) -> list[dict]:
        limit, mode = self.config["maxItemsPerRun"], self.config["mode"]

        def part(name):
            return self.store.query_partition(gsi_partition(self.monitor_id, name), 50 if name == PARTITION_DECIDED else limit)

        if mode == "dry-run":
            return part(PARTITION_COLLECTED)[:limit]
        decided = [d for d in part(PARTITION_DECIDED)
                   if (self.get_route(d).get("nextAttemptAt") or 0) <= self.now]
        fresh = sorted(part(PARTITION_COLLECTED) + part(PARTITION_DRY_RUN), key=lambda d: d["gsi1sk"])
        return (decided + fresh)[:limit]

    # dry-run ----------------------------------------------------------------------------------------

    def dry_run(self, disc: dict):
        route = self.get_route(disc)
        requests = {}
        for publication in self.config["publications"]:
            try:
                built = build_decide_request(self.config, publication, disc)
            except (ItemInvalid, ValueError) as error:
                return self.finish(disc, route, "error", f"invalid request: {error}")
            requests[publication["publicationId"]] = {
                "path": built["path"], "requestId": built["body"]["requestId"], "bytes": len(json.dumps(built["body"], separators=(",", ":"))),
                "body": built["body"]}
        contexts = {p["publicationId"]: self.context_for(p) for p in self.config["publications"]}
        previous = route.get("dryRun") or {}
        route["dryRun"] = {"count": int(previous.get("count", 0)) + 1, "validatedAt": _iso(self.now),
                           "runId": self.run_id, "requests": requests, "contexts": contexts}
        self.save(route)
        set_routing(self.store, self.monitor_id, disc, PARTITION_DRY_RUN, PARTITION_DRY_RUN)
        self.counts["dryRunValidated"] += 1

    # live ---------------------------------------------------------------------------------------------

    def decide(self, disc: dict, route: dict) -> None:
        """One `decide` per binding. Jobs are recorded before and after sending; POST is never repeated."""
        jobs = route.setdefault("jobs", {})
        item_id = f"hn-{disc['sourceId']}"
        for publication in self.config["publications"]:
            pub_id = publication["publicationId"]
            built = build_decide_request(self.config, publication, disc, int(route.get("attempt", 0)))
            job = jobs.get(pub_id)
            if job and job.get("checked"):
                continue   # already decided under an earlier request id; the shared decision is cached
            if job and job.get("requestId") != built["body"]["requestId"]:
                raise ItemInvalid("stored job belongs to a different request")
            if job and job.get("jobId"):
                if self.now - int(job.get("postedAt", self.now)) > MAX_PENDING_JOB_SECONDS:
                    raise ItemInvalid("job pending longer than the allowed time; reconcile manually")
            elif job:
                raise ItemUncertain("an earlier POST had no recorded answer")
            else:
                jobs[pub_id] = {"requestId": built["body"]["requestId"], "postedAt": int(self.now)}
                self.save(route)   # recorded BEFORE sending: an interrupted run must not POST again
                try:
                    job_id, immediate = self.cyclotron.post(pub_id, built["body"])
                except ItemUncertain:
                    raise
                except Exception:
                    del jobs[pub_id]   # definitively refused: nothing was started, a later run may send it
                    self.save(route)
                    raise
                if job_id:
                    jobs[pub_id]["jobId"] = job_id
                    self.save(route)
                else:
                    jobs[pub_id]["checked"] = checked_decision(immediate, publication, self.config, item_id)
                    self.save(route)
                    continue
            try:
                response = self.cyclotron.poll(pub_id, jobs[pub_id]["jobId"])
            except StopSweep as stop:
                if stop.code in NON_CONSUMING_REFUSALS:
                    # Nothing ran at the provider. Drop the refused job and use a new request id next time.
                    del jobs[pub_id]
                    route["attempt"] = int(route.get("attempt", 0)) + 1
                    self.save(route)
                raise
            jobs[pub_id]["checked"] = checked_decision(response, publication, self.config, item_id)
            self.save(route)
        checked = {pid: jobs[pid]["checked"] for pid in (p["publicationId"] for p in self.config["publications"])}
        if len({c["decisionId"] for c in checked.values()}) != 1:
            raise ItemInvalid("publications did not share one native decision")
        if len({json.dumps(c["source"], sort_keys=True) for c in checked.values()}) != 1:
            raise ItemInvalid("publications reported different source revisions")
        first = next(iter(checked.values()))
        route["decision"] = {
            "decisionId": first["decisionId"], "source": first["source"], "decidedAt": _iso(self.now),
            "accountId": self.config["cyclotron"]["accountId"], "runId": self.config["cyclotron"]["runId"],
            "bindingRevision": self.config["cyclotron"]["bindingRevision"],
            "publications": {pid: {k: c[k] for k in ("output", "label", "fingerprint", "version")} for pid, c in checked.items()}}
        route["publications"] = {pid: {"label": c["label"], "delivered": False, "attempts": 0}
                                 for pid, c in checked.items() if c["label"] == self.publications[pid]["positiveLabel"]}
        route.pop("nextAttemptAt", None)
        self.save(route)
        self.counts["decided"] += 1

    def deliver_positive(self, disc: dict, route: dict) -> bool:
        """Deliver to every positive publication that is not yet delivered; failures stay per publication."""
        decision = route["decision"]
        all_delivered = True
        for pub_id, state in route["publications"].items():
            if state.get("delivered"):
                continue
            publication = self.publications.get(pub_id)
            try:
                if publication is None:
                    raise ItemInvalid("publication is no longer configured")
                receipt = {"decisionId": decision["decisionId"], **decision["publications"][pub_id]}
                result = self.deliver(self.client(publication), publication, disc, receipt, self.config)
                state.update(delivered=True, deliveredAt=_iso(self.now), referenceId=result["referenceId"],
                             referenceLineageId=result.get("referenceLineageId"),
                             provenanceMessageId=result.get("provenanceMessageId"), lastError=None)
                self.record_delivery(publication, disc, route, result)
                self.counts["delivered"] += 1
            except Exception as error:
                all_delivered = False
                attempts = int(state.get("attempts", 0)) + 1
                state.update(attempts=attempts, lastError=short(error), lastAttemptAt=_iso(self.now))
                route["nextAttemptAt"] = int(self.now + min(300 * 2 ** (attempts - 1), 6 * 3600))
                self.counts["deliveryFailed"] += 1
            self.save(route)   # per publication, so a later crash keeps earlier progress
        return all_delivered

    def record_delivery(self, publication: dict, disc: dict, route: dict, result: dict):
        decision = route["decision"]
        key = f"DELIV#{publication['publicationId']}#{result['referenceId']}"
        if self.store.get_any(self.monitor_id, key):
            return   # an earlier decision's feedback record stays authoritative
        self.store.put_any(self.monitor_id, {
            "pk": pk(self.monitor_id), "sk": key, "publicationId": publication["publicationId"],
            "referenceId": result["referenceId"], "sourceId": disc["sourceId"], "revision": int(disc["revision"]),
            "itemId": route["itemId"], "decisionId": decision["decisionId"], "source": decision["source"],
            "output": decision["publications"][publication["publicationId"]]["output"],
            "bindingRevision": decision["bindingRevision"], "deliveredAt": _iso(self.now),
            "gsi1pk": FEEDBACK_PARTITION, "gsi1sk": f"{_iso(self.now)}#{publication['publicationId']}#{result['referenceId']}"})

    def live(self, disc: dict):
        route = self.get_route(disc)
        try:
            if not route.get("decision"):
                self.decide(disc, route)
            if not self.deliver_positive(disc, route):
                set_routing(self.store, self.monitor_id, disc, "decided", PARTITION_DECIDED)
                return
            route["completedAt"] = _iso(self.now)
            self.save(route)
            set_routing(self.store, self.monitor_id, disc, "routed", None)
            self.counts["routed"] += 1
        except ItemRefused as error:
            self.finish(disc, route, "refused", str(error))
        except ItemUncertain as error:
            self.finish(disc, route, "uncertain", str(error))
        except ItemInvalid as error:
            self.finish(disc, route, "error", str(error))

    def finish(self, disc: dict, route: dict, routing: str, reason: str):
        route["final"] = {"routing": routing, "reason": reason[:300], "at": _iso(self.now)}
        self.save(route)
        set_routing(self.store, self.monitor_id, disc, routing, None)
        self.counts[routing] += 1

    # sweep ----------------------------------------------------------------------------------------

    def sweep(self) -> dict:
        status, stopped = "complete", None
        errors: list = []
        for disc in self.candidates():
            if self.time_left() < MIN_REMAINING_SECONDS:
                status, stopped = "stopped", "time_budget"
                break
            self.counts["examined"] += 1
            try:
                (self.dry_run if self.config["mode"] == "dry-run" else self.live)(disc)
            except StopSweep as stop:
                status, stopped = "stopped", stop.code
                break
            except Exception as error:   # one bad item must not hide the rest
                errors.append({"sourceId": disc.get("sourceId"), "message": short(error)})
                self.counts["error"] += 1
        if errors and status == "complete":
            status = "partial"
        return {"status": status, "stoppedBy": stopped, "errors": errors[:10]}

    # feedback ---------------------------------------------------------------------------------------

    def feedback(self) -> dict:
        result = {"status": "complete", "sent": 0, "pending": 0, "skipped": 0, "failed": 0, "stoppedBy": None}
        if self.config["mode"] != "live" or not self.config["feedback"]:
            return {**result, "status": "off"}
        for row in self.store.query_partition(FEEDBACK_PARTITION, 25):
            if self.time_left() < MIN_REMAINING_SECONDS:
                result.update(status="stopped", stoppedBy="time_budget")
                break
            publication = self.publications.get(row.get("publicationId"))
            if publication is None:
                result["skipped"] += 1
                self.rotate(row, "publication not configured")
                continue
            try:
                outcome = self.feedback_one(publication, row)
            except StopSweep as stop:
                result.update(status="stopped", stoppedBy=stop.code)
                break
            except Exception as error:
                result["failed"] += 1
                self.rotate(row, short(error))
                continue
            result[outcome] += 1
        return result

    def rotate(self, row: dict, note: str):
        """Move a checked row to the back of the queue so one stuck row cannot starve the rest."""
        row = {**row, "lastCheckedAt": _iso(self.now), "lastNote": note[:300],
               "gsi1sk": f"{_iso(self.now)}#{row['publicationId']}#{row['referenceId']}"}
        self.store.put_any(self.monitor_id, row)

    def feedback_one(self, publication: dict, row: dict) -> str:
        reference = self.client(publication).get_record("Reference", row["referenceId"])
        status = (reference or {}).get("curationStatus")
        if status not in ("accepted", "rejected"):
            self.rotate(row, f"curation {status or 'missing'}")
            return "pending"
        actor = str(reference.get("curationStatusUpdatedBy") or "")
        if not actor.startswith("user:") or not actor[5:].strip() or actor == WORKER_ACTOR:
            self.rotate(row, "curation actor is missing or not a human user")
            return "skipped"
        updated_at = str(reference.get("curationStatusUpdatedAt") or reference.get("updatedAt") or "")
        label = publication["positiveLabel"] if status == "accepted" else publication["negativeLabel"]
        body = {"contractVersion": CONTRACT_VERSION, "operation": "feedback",
                "requestId": sha256("\n".join([row["referenceId"], status, updated_at]).encode()).hexdigest(),
                "payload": {"bindingRevision": row["bindingRevision"], "itemId": row["itemId"],
                            "itemRevision": (row.get("source") or {}).get("revision"), "output": row["output"],
                            "label": label, "editor": {"site": publication["site"], "subject": actor}}}
        if body["payload"]["itemRevision"] is None:
            self.rotate(row, "decision receipt has no item revision")
            return "skipped"
        validate_request(body)
        receipt = {"pk": pk(self.monitor_id), "sk": f"FB#{body['requestId']}", "requestId": body["requestId"],
                   "publicationId": publication["publicationId"], "referenceId": row["referenceId"],
                   "curationStatus": status, "label": label, "output": row["output"], "itemId": row["itemId"],
                   "sentAt": _iso(self.now), "runId": self.run_id}
        try:
            response = self.cyclotron.feedback(publication["publicationId"], body)
        except ItemRefused as error:
            self.store.put_any(self.monitor_id, {**receipt, "outcome": "refused", "code": str(error)})
            self.store.put_any(self.monitor_id, {k: v for k, v in row.items() if k not in ("gsi1pk", "gsi1sk")} | {"feedback": "refused"})
            return "failed"
        except ItemInvalid as error:
            self.store.put_any(self.monitor_id, {**receipt, "outcome": "invalid", "code": str(error)})
            self.store.put_any(self.monitor_id, {k: v for k, v in row.items() if k not in ("gsi1pk", "gsi1sk")} | {"feedback": "invalid"})
            return "failed"
        except ItemUncertain as error:   # safe to retry later: same requestId
            self.rotate(row, f"uncertain: {error}")
            return "failed"
        self.store.put_any(self.monitor_id, {**receipt, "outcome": "sent",
                                             "response": {k: response[k] for k in ("status", "feedbackId", "accepted") if k in response
                                                          and isinstance(response[k], (str, bool, int))}})
        self.store.put_any(self.monitor_id, {k: v for k, v in row.items() if k not in ("gsi1pk", "gsi1sk")}
                           | {"feedback": "sent", "feedbackRequestId": body["requestId"], "feedbackAt": _iso(self.now)})
        return "sent"


def run_router(store, monitor_id: str = "hn", *, now: float | None = None, owner: str | None = None,
               run_id: str | None = None, task: str | None = None, cyclotron: CyclotronClient | None = None,
               appsync: Callable[[str], Any] = make_appsync_client, deliver=deliver_reference,
               context_receipt=editorial_context_receipt, time_left: Callable[[], float] = lambda: 1e9,
               cyclotron_factory: Callable[[dict], CyclotronClient] | None = None) -> dict:
    now = time.time() if now is None else now
    owner, run_id = owner or uuid.uuid4().hex, run_id or uuid.uuid4().hex
    raw = store.get_router_config(monitor_id)
    if raw is None:
        return {"monitorId": monitor_id, "runId": run_id, "status": "not_configured"}
    config = validate_router_config(raw)
    if not config["enabled"]:
        return {"monitorId": monitor_id, "runId": run_id, "status": "disabled"}
    if not store.acquire_router_lock(monitor_id, owner, now):
        return {"monitorId": monitor_id, "runId": run_id, "status": "locked"}
    try:
        if cyclotron is None and config["mode"] == "live":
            cyclotron = (cyclotron_factory or (lambda c: CyclotronClient(c, sign=sigv4_signer(c, assume_invoker(c)))))(config)
        router = Router(store, config, monitor_id=monitor_id, now=now, run_id=run_id, cyclotron=cyclotron,
                        appsync=appsync, deliver=deliver, context_receipt=context_receipt, time_left=time_left)
        outcome = {"status": "skipped"} if task == "feedback" else router.sweep()
        feedback = {"status": "skipped"} if task == "route" else router.feedback()
        result = {"monitorId": monitor_id, "runId": run_id, "mode": config["mode"], "startedAt": _iso(now),
                  "status": outcome["status"], "stoppedBy": outcome.get("stoppedBy"), "counts": router.counts,
                  "feedback": feedback, "errors": outcome.get("errors", [])}
        store.put_receipt(monitor_id, {
            "pk": pk(monitor_id), "sk": f"ROUTERUN#{result['startedAt']}#{run_id}", "runId": run_id,
            "startedAt": result["startedAt"], "mode": config["mode"], "status": result["status"],
            "stoppedBy": result["stoppedBy"], "counts": router.counts, "feedback": feedback,
            "errors": result["errors"], "ttl": int(now + RECEIPT_TTL_SECONDS)})
        return result
    finally:
        store.release_router_lock(monitor_id, owner)


def handler(event, context):
    """EventBridge Scheduler entry point. `{"task": "route"|"feedback"}` limits the pass (operator debugging)."""
    import boto3  # provided by the Lambda runtime

    event = event if isinstance(event, dict) else {}
    store = RouterStore(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))
    remaining = (lambda: context.get_remaining_time_in_millis() / 1000) if hasattr(context, "get_remaining_time_in_millis") else (lambda: 1e9)
    result = run_router(store, str(event.get("monitorId") or "hn"), task=event.get("task"), time_left=remaining)
    print(json.dumps({k: v for k, v in result.items() if k != "errors"} | {"errors": result.get("errors", [])[:3]}))
    return {k: result.get(k) for k in ("runId", "status", "mode", "stoppedBy", "counts", "feedback")}
