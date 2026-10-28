"""Cloud monitor router (PPY-3212f1 step 4): collected discoveries -> Cyclotron -> References queues.

Reads discoveries the collector left at `routing: collected`, asks the shared Cyclotron
for one decision per item (one `decide` per publication binding; the bindings share one
native decision), and delivers items a publication's relevance output labels `include`
into THAT publication's newsroom References queue as `pending`, through the existing
`ReferenceIntake` over IAM-signed AppSync. A feedback pass reports editors' later
accept/reject decisions back to Cyclotron when `router.feedback` is enabled.

Everything (mode, endpoints, publications, account, run, binding revision) is data in the
`CONFIG#router` table item (docs/monitoring-cloud.md); nothing here hard-codes it.
`dry-run` mode never calls Cyclotron and never writes to a publication.

A monitor whose router config says `decisions: direct` makes no relevance call at all: every
collected item goes to every configured publication, recorded as the monitor's own rule.
That suits sources a section covers exhaustively (every TTAB decision for a rulings tracker).
A direct monitor may add a `rule` (the same shape as a Hugging Face monitor's acceptance rule: `pipelineTags`,
`authors`, `minLikes`, `minDownloads`, and the `excludeTags`, `excludeBaseRelations`, `excludeIdPatterns`
exclusions): an item that fails it is finished as `routed` with the reason and
delivered nowhere, so a deterministic rule can stand in until Cyclotron criteria exist.

A publication may also list `procedureTriggers`: after the router creates a new Reference there, it starts
each named Tactus procedure once per source item by invoking the procedure runner asynchronously
(docs/procedure-runner.md). A `TRIGGER#` row, written only if absent, makes the start exactly-once.
Before it starts one, the router reads the site's Automation record for that trigger (docs/automations.md): a
disabled automation starts nothing (`skipped`), one at its maxConcurrent defers (`deferred`, retried on later runs), and its limits travel
with the request. With no record, or one that cannot be read, the router starts exactly as it always did.

Imports stay light: stdlib, boto3/botocore (Lambda runtime) and the existing modules.
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
import re
import string
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit

from .automation_gate import (
    START_AS_BEFORE,
    Gate,
    decide,
    manual_prefix,
    matching_automation,
    query_prefix,
    trigger_prefix,
)
from .email_submission_authorization import (
    EditorLookupUnavailable,
    publication_ids_for_editor,
)
from .monitoring import SOURCE_TYPES, Monitor, SourceItem, _iso
from .monitoring_cloud import ConditionFailed, DynamoStore, pk
from .monitoring_enrichment import Enricher, copy_curation, decision_inputs, enrich_item, enrich_sk, new_row
from .monitoring_huggingface import hf_accepts, validate_rule

CONTRACT_VERSION = "cyclotron-publication/v1"
ROUTER_CONFIG_SK = "CONFIG#router"
ROUTER_LOCK_SK = "LOCK#router"
LEASE_SECONDS = 660                    # longer than the 600 s Lambda timeout
RECEIPT_TTL_SECONDS = 30 * 86400
STALE_FINAL_REASON = "job pending longer than the allowed time; reconcile manually"   # an old limit's finals, reopened by hand
AWAITING = "awaiting"
MIN_REMAINING_SECONDS = 120            # do not start another item with less time than this
WORKER_ACTOR = "papyrus-monitoring-worker"   # the intake's own curation actor; never a human
# A human curator is recorded as `user:<x>` (CLI), the editor's sign-in email, a Cognito username
# (`google_<digits>`) or a Cognito sub (UUID). Everything else (worker, `ai`, `system:*`, `worker:*`,
# `papyrus*`, `behave-*`, `*-import`, the "Papyrus newsroom" fallback label) is a machine or unknown actor.
_EMAIL_ACTOR = re.compile(r"^[^@\s:]+@[^@\s:]+\.[^@\s:]+$")
_COGNITO_ACTOR = re.compile(r"^(?:[A-Za-z][A-Za-z0-9-]*_[0-9]+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")


def human_actor(actor: str) -> bool:
    actor = actor.strip()
    if not actor or actor == WORKER_ACTOR:
        return False
    if actor.startswith("user:"):
        return bool(actor[5:].strip())
    return bool(_EMAIL_ACTOR.match(actor) or _COGNITO_ACTOR.match(actor))


def editor_subject(site: str, actor: str) -> str:
    """The stable, non-PII editor subject sent to Cyclotron. Never an email address."""
    actor = actor.strip()
    if actor.startswith("user:") and "@" not in actor:
        return actor[:200]
    if _COGNITO_ACTOR.match(actor) and "_" not in actor:
        return f"cognito:{actor}"
    return "editor:" + sha256(f"{site}:{actor.lower()}".encode()).hexdigest()[:32]
PARTITION_COLLECTED = "collected"
PARTITION_DRY_RUN = "dry-run-validated"
PARTITION_DECIDED = "decided"
DECISIONS = ("cyclotron", "direct")
ROUTING_FINAL = ("routed", "refused", "uncertain", "error", "parked")
NON_CONSUMING_REFUSALS = frozenset({"provider_key_unavailable", "request_ceiling_reached", "standing_capacity_reached"})
STOP_CODES = frozenset({"provider_key_unavailable", "request_ceiling_reached", "standing_capacity_reached", "run_busy"})
NOT_READY_CODE = "criteria_pending"   # typed form of the 409 below, accepted if Cyclotron ever sends it
# The machine API (Cyclotron hosted_machine_publications.py) answers decide on a pending output with
# HTTP 409 and a FastAPI body {"detail": "publication criteria are pending"}: no typed code.
NOT_READY_DETAIL = "publication criteria are pending"
REQUEST_CONFLICT_CODE = "request_conflict"   # 409: the requestId was already used for a job with different content
BINDING_CHANGED_DETAIL = "publication binding changed"   # 409 from POST /machine/decisions: a key is no longer a standing binding
LOG = logging.getLogger(__name__)
PARK_PREFIX = "PARK#"
#: A story the lab refused for a non-permanent reason waits REFUSAL_BACKOFF_FIRST * 2**n seconds (n = refusals so far),
#: capped at REFUSAL_BACKOFF_MAX. This is a backoff between asks, not a limit: the router never gives up on the story.
REFUSAL_BACKOFF_FIRST, REFUSAL_BACKOFF_MAX = 900, 24 * 3600
PARK_BACKOFF_FIRST, PARK_BACKOFF_MAX = 1800, 6 * 3600
#: The lab answered 429 or 503: the whole monitor stops calling it until `labBackoffUntil` (STATE#labBackoff). The wait is
#: the lab's Retry-After when it sends one, otherwise LAB_BACKOFF_FIRST * 2**n seconds (n = consecutive refused runs),
#: capped at LAB_BACKOFF_MAX. A Retry-After is honoured up to LAB_RETRY_AFTER_MAX so a bad header cannot park the monitor
#: for good. This is a backoff between asks, not a limit: every job stays recorded and is asked about again afterwards.
#: A 429 WITHOUT a Retry-After is not the lab asking for a pause: it is the API Gateway stage throttle on the lab's HTTP API
#: ("Too Many Requests", 5 requests/second sustained, burst 10) saying "too fast this second". The client therefore paces
#: itself (below), waits LAB_THROTTLE_WAIT seconds (jittered) and repeats the same call up to LAB_THROTTLE_RETRIES times,
#: and never sets the monitor-level pause for it. Only a 503, or a 429 that carries a Retry-After, does.
LAB_BACKOFF_SK = "STATE#labBackoff"
#: Client-side pacing: at most cyclotron.maxRequestsPerSecond lab calls per second per invocation. The default is 4, just under
#: the API Gateway stage limit of 5 requests/second, which is a real constraint of the lab's endpoint (not an arbitrary cap).
LAB_REQUESTS_PER_SECOND = 4
LAB_THROTTLE_WAIT, LAB_THROTTLE_RETRIES, LAB_THROTTLE_SLOWEST_INTERVAL = (1.0, 2.0), 3, 2.0
LAB_BACKOFF_FIRST, LAB_BACKOFF_MAX, LAB_RETRY_AFTER_MAX = 60, 1800, 3600
#: A job that is still running is not asked about again until its own `nextPollAt`: POLL_BACKOFF_FIRST * 2**n seconds
#: after its n-th unanswered check, capped at the collector cadence times POLL_BACKOFF_CADENCES. Backoff, not a limit; the
#: counter is cleared when the job completes, and a Decision Ready doorbell for the job bypasses the wait.
COLLECT_CADENCE_SECONDS, POLL_BACKOFF_CADENCES, POLL_BACKOFF_FIRST = 120, 8, 30
POLL_BACKOFF_MAX = COLLECT_CADENCE_SECONDS * POLL_BACKOFF_CADENCES
PENDING_STATUSES = frozenset({"pending", "queued", "running", "accepted", "in_progress"})
SOURCE_ID = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
#: The `source` a Cyclotron item names, by the discovery's sourceType (HN discoveries carry none).
ITEM_SOURCES = {"email": "email", "huggingface-models": "huggingface"}
ITEM_SOURCE_NAMES = frozenset({"hacker-news", *ITEM_SOURCES.values()})
PUBLICATION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
APPSYNC_HOST = re.compile(r"^[a-z0-9]+\.appsync-api\.[a-z0-9-]+\.amazonaws\.com$")
EXECUTE_API_HOST = re.compile(r"^[a-z0-9]+\.execute-api\.([a-z0-9-]+)\.amazonaws\.com$")
ROLE_ARN = re.compile(r"^arn:aws:iam::\d{12}:role/[\w+=,.@/-]{1,200}$")
PROCEDURE_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
PROCEDURE_INPUT_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")
SSM_PARAMETER = re.compile(r"^/[A-Za-z0-9_./-]{1,1000}$")
TRIGGER_PLACEHOLDERS = frozenset({"sourceId", "sourceIdPrefix", "canonicalUrl", "documentUrl", "sourceItemUrl", "title",
                                  "publishedAt", "referenceId", "publicationId", "corpusId"})


class EnrichmentPending(Exception):
    """The item's enrichment has not finished (a retry is waiting, or this run is out of time): post nothing yet."""


class StopSweep(Exception):
    """A condition that must stop the whole sweep cleanly (no retry storm)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code, self.detail = code, detail


class JobRunning(Exception):
    """A posted job has not finished. Not a run-stopping event: the story keeps its recorded job and is collected later."""


class NotPosting(Exception):
    """The collector never posts. The story needs a new POST, so it is left for the route run."""


class BindingNotReady(Exception):
    """One binding's output has no classifier yet: skip that binding for the item, never the sweep."""


class CombinedUnavailable(Exception):
    """The Cyclotron deployment has no POST /machine/decisions (404): decide per publication instead."""


class JobGone(Exception):
    """Polling a stored job answered 404: the lab no longer knows it (for example after a run cutover).
    The router discards the stored job and re-posts once; it is never a run-stopping event."""


class JobFailed(Exception):
    """Polling a stored job answered a terminal failed state: nothing more will come from it. The router discards it
    and re-posts once under a new id; it is never a run-stopping event."""


class AllBindingsNotReady(Exception):
    """Every binding for the item is waiting for a classifier: nothing to decide or deliver yet."""


class ItemRefused(Exception):
    pass


class ItemUncertain(Exception):
    pass


class ItemInvalid(Exception):
    pass


class ItemRetryLater(ItemInvalid):
    """The lab refused this story's request for a reason that is not explicitly permanent (an unknown 409, another
    4xx the contract does not name). Nothing ran at the lab, so the story backs off and is asked again on a later run."""


class RequestConflict(ItemRetryLater):
    """409 request_conflict: the lab holds this requestId for a job with different content. Nothing ran; the request
    is re-posted once under a new id."""


class ItemExcluded(Exception):
    """The monitor's own rule (router `rule`, direct decisions) leaves this item out of every publication."""


# --- config ---------------------------------------------------------------------------------------

def feedback_partition(monitor_id: str) -> str:
    return f"FEEDBACK#{monitor_id}#pending"


RETIRED_ROUTER_FIELDS = ("ceilings", "maxItemsPerRun")   # limits the router no longer has; stored copies are ignored


def validate_router_config(raw: dict) -> dict:
    account = raw.get("accountId")
    if account is not None and (not isinstance(account, str) or not account.strip() or len(account) > 128):
        raise ValueError("router accountId must be a nonempty Account identifier")
    account_scope = {"accountId": account} if account is not None else {}
    mode = raw.get("mode")
    if mode not in ("dry-run", "live"):
        raise ValueError("router mode must be dry-run or live")
    retired = sorted(key for key in RETIRED_ROUTER_FIELDS if key in raw)
    if retired:   # the router no longer limits its work; an old config still loads so deploy order does not matter
        print(json.dumps({"router": "ignored_retired_config", "fields": retired}))
    decisions = str(raw.get("decisions") or "cyclotron")
    if decisions not in DECISIONS:
        raise ValueError("router decisions must be cyclotron or direct")
    publications = validate_router_publications(raw)
    if decisions != "direct" and raw.get("rule") is not None:
        raise ValueError("router rule applies only to decisions: direct")
    if decisions == "direct":
        if raw.get("feedback") is True:
            raise ValueError("router feedback needs Cyclotron decisions; a direct monitor has none to correct")
        rule = validate_rule(raw["rule"], name="router rule") if raw.get("rule") is not None else None
        return {"mode": mode, "enabled": raw.get("enabled", True) is not False,
                "holdDecisions": raw.get("holdDecisions") is True,
                "decisions": decisions, "feedback": False, "publications": publications,
                "cyclotron": None, "rule": rule, **account_scope}
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
    rate = cyclotron.get("maxRequestsPerSecond", LAB_REQUESTS_PER_SECOND)
    if isinstance(rate, bool) or not isinstance(rate, (int, float, Decimal)) or not rate > 0:
        raise ValueError("router cyclotron.maxRequestsPerSecond must be a positive number")
    return {"mode": mode, "enabled": raw.get("enabled", True) is not False,
            "holdDecisions": raw.get("holdDecisions") is True,
            "decisions": decisions, "feedback": raw.get("feedback") is True,
            "publications": publications,
            "cyclotron": {"endpoint": f"https://{endpoint.netloc}", "region": match.group(1), "accountId": account,
                          "runId": run_id, "bindingRevision": revision, "roleArn": role_arn, "pollSeconds": poll,
                          "maxRequestsPerSecond": float(rate)}, **account_scope}


def email_routing_fingerprint(config: dict) -> str:
    """Pin the Account, publication destinations and shared binding across retries.

    Mode, enabled state and batch size can change without redirecting a source.
    Any identity, endpoint, grant or procedure change requires explicit reconciliation.
    """
    scope = {key: config.get(key) for key in ("accountId", "decisions", "publications", "cyclotron", "feedback")}
    return sha256(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_email_discovery_scope(discovery: dict, config: dict) -> None:
    if discovery.get("sourceType") == "email":
        if (not config.get("accountId") or not discovery.get("emailProvenance")
                or discovery.get("emailRoutingFingerprint") != email_routing_fingerprint(config)):
            raise ItemInvalid("Email destination Account or publication binding changed; reconcile explicitly")
        configured = {row["publicationId"] for row in config["publications"]}
        if discovery.get("emailTrustMode") == "data-only":
            allowed = discovery.get("emailDestinationPublicationIds")
            if discovery.get("emailProvenance", {}).get("inputTrust") != "untrusted-source-material":
                raise ItemInvalid("Data-only email trust provenance is missing")
            selection = discovery.get("editorSelectedReference")
            if selection is not None and (not isinstance(selection, dict) or not selection.get("subject")
                    or not selection.get("referenceId")
                    or selection != discovery["emailProvenance"].get("editorSelection")
                    or allowed != [selection.get("publicationId")]):
                raise ItemInvalid("Invalid editor-selected Reference scope")
            diagnostics = discovery.get("emailProvenance", {}).get("sesDiagnostics") or {}
            if diagnostics.get("warnings") and not discovery.get("editorSelectedReference"):
                raise ItemInvalid("Email authentication warnings require editor review before routing")
        else:
            # Compatibility for discoveries queued by the earlier editor-gated path.
            allowed = discovery.get("emailAuthorizedPublicationIds")
        if (not isinstance(allowed, list) or not allowed
                or any(not isinstance(value, str) or not value for value in allowed)
                or len(allowed) != len(set(allowed)) or not set(allowed) <= configured):
            raise ItemInvalid("Email publication scope is missing or outside its configured destination")


def validate_router_publications(raw: dict) -> list[dict]:
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
        pool_id = entry.get("userPoolId")
        if pool_id is not None and (not isinstance(pool_id, str) or not re.fullmatch(r"[A-Za-z0-9-]+_[A-Za-z0-9]+", pool_id)):
            raise ValueError(f"router publication {publication_id} has an invalid editor user pool")
        since = entry.get("criteriaSince")
        if since is not None and (not isinstance(since, (str, int)) or not str(since).strip()):
            raise ValueError(f"router publication {publication_id} has an invalid criteriaSince")
        publications.append({
            **({"criteriaSince": str(since).strip()} if since is not None else {}),
            "publicationId": publication_id, "site": site, "appsyncEndpoint": entry["appsyncEndpoint"],
            **({"userPoolId": pool_id} if pool_id else {}),
            "corpusId": corpus_id, "corpusKey": corpus_id.removeprefix("knowledge-corpus-"),
            "output": str(entry.get("output") or f"{publication_id}-relevance"),
            "positiveLabel": str(entry.get("positiveLabel") or "include"),
            "negativeLabel": str(entry.get("negativeLabel") or "exclude"),
            "procedureTriggers": validate_procedure_triggers(publication_id, entry),
            "openaiKeyParameter": entry.get("openaiKeyParameter")})
    if not publications:
        raise ValueError("router needs at least one publication")
    return publications


DECISION_KEYS = ("output", "label", "fingerprint", "version", "confidence", "criteriaFingerprint")

VIA_DECISIONS, VIA_PUBLICATION = "decisions", "publication"


def job_via(route: dict, job: dict) -> str:
    """Which route a stored job was posted to. Entries stored before `via` existed are combined jobs when their jobId
    is the route's combined job; anything else was posted per publication."""
    if job.get("via") in (VIA_DECISIONS, VIA_PUBLICATION):
        return job["via"]
    combined = (route.get("combinedJob") or {}).get("jobId")
    return VIA_DECISIONS if combined and job.get("jobId") == combined else VIA_PUBLICATION


def criteria_unchanged(stored: str, since: str) -> bool:
    """True when a vote stored under binding revision `stored` was judged against criteria that still hold, given the
    earliest matching revision `since`. Integer revisions compare numerically; anything else must match exactly."""
    try:
        return int(stored) >= int(since)
    except (TypeError, ValueError):
        return str(stored) == str(since)


def validate_procedure_triggers(publication_id: str, entry: dict) -> list[dict]:
    triggers, seen = [], set()
    for trigger in entry.get("procedureTriggers") or []:
        key = str(trigger.get("procedureKey") or "")
        inputs = trigger.get("input") or {}
        if not PROCEDURE_KEY.match(key) or key in seen or not isinstance(inputs, dict):
            raise ValueError(f"router publication {publication_id} has an invalid or duplicated procedure trigger")
        for name, template in inputs.items():
            used = {field for _, field, _, _ in string.Formatter().parse(str(template)) if field is not None}
            if not PROCEDURE_INPUT_NAME.match(name) or not used <= TRIGGER_PLACEHOLDERS:
                raise ValueError(f"router publication {publication_id} trigger {key} input {name} is invalid")
        seen.add(key)
        triggers.append({"procedureKey": key, "input": {name: str(template) for name, template in inputs.items()}})
    parameter = entry.get("openaiKeyParameter")
    if triggers and not SSM_PARAMETER.match(str(parameter or "")):
        raise ValueError(f"router publication {publication_id} needs openaiKeyParameter for its procedure triggers")
    return triggers


def procedure_trigger_input(trigger: dict, publication: dict, disc: dict, reference_id: str) -> dict:
    values = {"sourceId": disc["sourceId"], "sourceIdPrefix": str(disc["sourceId"]).split("-", 1)[0],
              "canonicalUrl": disc["canonicalUrl"], "documentUrl": (list(disc.get("aliases") or []) or [disc["canonicalUrl"]])[0],
              "sourceItemUrl": disc.get("sourceItemUrl") or "",
              "title": disc.get("title") or "", "publishedAt": disc.get("sourcePublishedAt") or "",
              "referenceId": reference_id, "publicationId": publication["publicationId"],
              "corpusId": publication["corpusId"]}
    return {name: template.format(**values) for name, template in trigger["input"].items()}


def lambda_procedure_starter(function_name: str | None) -> Callable[[dict], None] | None:
    if not function_name:
        return None

    def start(request: dict) -> None:
        import boto3  # provided by the Lambda runtime
        boto3.client("lambda").invoke(FunctionName=function_name, InvocationType="Event",
                                      Payload=json.dumps(request).encode("utf-8"))
    return start


# --- request building -------------------------------------------------------------------------------

def canonical_json(value) -> str:
    """Sorted keys, no whitespace: the same content always serialises to the same text."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_id(account_id: str, run_id: str, publication_id: str, payload: dict, attempt: int = 0) -> str:
    """Content-addressed: the id is derived from the exact payload sent, so a retry of the same content reuses it
    and any change of content (bindings, item values) gets a new id instead of a `request_conflict` at the lab.

    `attempt` is 0 until Cyclotron refuses a job without consuming any provider request (key missing,
    ceiling reached). Cyclotron keeps a refused job under its request id, so a later retry needs a new one.
    """
    parts = [account_id, run_id, publication_id, canonical_json(payload)]
    if attempt:
        parts.append(f"attempt-{attempt}")
    return sha256("\n".join(parts).encode()).hexdigest()


def combined_request_id(account_id: str, run_id: str, payload: dict, attempt: int = 0) -> str:
    """Content-addressed over the whole POST /machine/decisions payload (sorted bindings map and item incl. values)."""
    parts = ["decisions", account_id, run_id, canonical_json(payload)]
    if attempt:
        parts.append(f"attempt-{attempt}")
    return sha256("\n".join(parts).encode()).hexdigest()


def item_id_for(monitor_id: str, source_id: str) -> str:
    return f"{monitor_id}-{source_id}"


def compose_text(title: str, url: str, summary: str = "", body: str = "") -> str:
    """`title\nurl`, then the summary, then the captured body, each after a blank line; absent parts are left out."""
    return "\n\n".join(part for part in (f"{title}\n{url}", summary, body) if part)


def build_item(discovery: dict, enrichment: dict | None = None) -> dict:
    """The Cyclotron item. `enrichment` is `{summary, body}` from item enrichment (docs/reference-curation-pipeline.md): `summary` and
    `body` (the full captured text) join `values`, and `text` = title, url, summary, body."""
    source_id = str(discovery.get("sourceId") or "")
    title, url = str(discovery.get("title") or ""), str(discovery.get("canonicalUrl") or "")
    if not SOURCE_ID.match(source_id) or not title.strip() or len(title) > 1000 or not url or len(url) > 2048:
        raise ItemInvalid("discovery is not a valid Cyclotron item")
    source = ITEM_SOURCES.get(discovery.get("sourceType"), "hacker-news")
    summary, body = str((enrichment or {}).get("summary") or ""), str((enrichment or {}).get("body") or "")
    values = {"title": title, "url": url, "source": source, "sourceItemUrl": str(discovery.get("sourceItemUrl") or ""),
              **({"summary": summary} if summary else {}), **({"body": body} if body else {}),
              "text": compose_text(title, url, summary, body)}
    return {"id": item_id_for(str(discovery.get("monitorId") or "hn"), source_id), "values": values}


PLACEHOLDER_REQUEST_ID = "0" * 64


def build_decide_request(config: dict, publication: dict, discovery: dict, attempt: int = 0, enrichment: dict | None = None) -> dict:
    validate_email_discovery_scope(discovery, config)
    cyclotron = config["cyclotron"]

    item = build_item(discovery, enrichment)
    payload = {"bindingRevision": cyclotron["bindingRevision"], "item": item}
    body = {"contractVersion": CONTRACT_VERSION, "operation": "decide",
            "requestId": request_id(cyclotron["accountId"], cyclotron["runId"], publication["publicationId"],
                                    payload, attempt),
            "payload": payload}
    validate_request(body)
    return {"path": f"/machine/publications/{publication['publicationId']}/operations", "body": body}


def build_combined_request(config: dict, publications: list[dict], discovery: dict, attempt: int = 0,
                           enrichment: dict | None = None) -> dict:
    """One POST /machine/decisions body for a story and every given publication's binding."""
    validate_email_discovery_scope(discovery, config)
    cyclotron = config["cyclotron"]
    bindings = {p["publicationId"]: cyclotron["bindingRevision"] for p in publications}
    if not bindings:
        raise ItemInvalid("no publication bindings to decide")

    item = build_item(discovery, enrichment)
    payload = {"bindings": dict(sorted(bindings.items())), "item": item}
    body = {"contractVersion": CONTRACT_VERSION,
            "requestId": combined_request_id(cyclotron["accountId"], cyclotron["runId"], payload, attempt),
            "payload": payload}
    validate_combined_request(body)
    return {"path": "/machine/decisions", "body": body}


def validate_combined_request(body: dict) -> None:
    if body.get("contractVersion") != CONTRACT_VERSION or set(body) != {"contractVersion", "requestId", "payload"}:
        raise ValueError("combined request shape")
    request = body["requestId"]
    if not isinstance(request, str) or not 8 <= len(request) <= 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", request):
        raise ValueError("requestId must be 8 to 128 characters of [A-Za-z0-9._:-]")
    payload = body["payload"]
    bindings = payload.get("bindings") if isinstance(payload, dict) else None
    if (set(payload) != {"bindings", "item"} or not isinstance(bindings, dict) or not bindings
            or any(not PUBLICATION_ID.match(str(k)) or not isinstance(v, str) or not v for k, v in bindings.items())):
        raise ValueError("combined payload shape")
    validate_request({"contractVersion": CONTRACT_VERSION, "operation": "decide", "requestId": request,
                      "payload": {"bindingRevision": "x", "item": payload["item"]}})


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
        valid_id = (str(item.get("id", "")).startswith("hn-") if values.get("source") == "hacker-news" else
                    bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}-[A-Za-z0-9_-]{1,64}", str(item.get("id", "")))))
        if set(item) != {"id", "values"} or not valid_id:
            raise ValueError("decide item shape")
        required = {"title", "url", "source", "sourceItemUrl", "text"}
        if not required <= set(values) or set(values) - required - {"summary", "body"} or values["source"] not in ITEM_SOURCE_NAMES:
            raise ValueError("decide item values shape")
        if (any(not isinstance(v, str) or not v for v in values.values())
                or values["text"] != compose_text(values["title"], values["url"], values.get("summary", ""), values.get("body", ""))):
            raise ValueError("decide item values content")
    elif body["operation"] == "feedback":
        required = {"bindingRevision", "itemId", "itemRevision", "output", "label", "editor"}
        if not required <= set(payload) or set(payload) - required - {"comment"}:
            raise ValueError("feedback payload shape")
        editor = payload["editor"]
        if not isinstance(editor, dict) or set(editor) != {"site", "subject"} or not all(editor.values()):
            raise ValueError("feedback editor shape")


# --- Cyclotron machine API ------------------------------------------------------------------------

LAB_OVERLOAD_STATUSES = (429, 503)


def parse_retry_after(value) -> int | None:
    """Seconds from a Retry-After value (delta-seconds or an HTTP date); None when absent or unusable."""
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = parsedate_to_datetime(str(value)).timestamp() - time.time()
        except (TypeError, ValueError):
            return None
    return max(1, int(math.ceil(seconds))) if seconds > 0 else None


def default_http(method: str, url: str, headers: dict, body: bytes | None, timeout: float):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw, status = response.read(), response.status
    except urllib.error.HTTPError as error:
        raw, status = error.read(), error.code
        retry_after = error.headers.get("Retry-After") if error.headers else None
    else:
        retry_after = None
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        payload = {"unparsed": True}
    payload = payload if isinstance(payload, dict) else {"unparsed": True}
    if retry_after and status in LAB_OVERLOAD_STATUSES:
        payload = {**payload, "_retryAfter": retry_after}   # the transport has no headers channel: carry the one we honour
    return status, payload


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


def body_excerpt(status: int, payload) -> str:
    """A short, secret-free description of a lab refusal: only its code and detail fields, never the whole body."""
    payload = payload if isinstance(payload, dict) else {}
    error = payload.get("error")
    parts = []
    for label, value in (("code", payload.get("code") or (error.get("code") if isinstance(error, dict) else error)),
                         ("detail", payload.get("detail"))):
        if value not in (None, "", [], {}):
            text = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"), default=str)
            parts.append(f"{label}={' '.join(text.split())}")
    return f"http {status}: {'; '.join(parts) or 'no detail'}"[:300]


def refusal_code(status: int, payload: dict) -> str:
    error = payload.get("error")
    code = payload.get("code") or (error.get("code") if isinstance(error, dict) else error)
    return str(code) if isinstance(code, str) and code else f"http_{status}"


class CyclotronClient:
    def __init__(self, config: dict, *, sign: Callable[[str, str, bytes], dict], http=default_http,
                 sleep=time.sleep, clock=time.monotonic, jitter=random.uniform):
        self.config, self.sign, self.http, self.sleep, self.clock, self.jitter = config, sign, http, sleep, clock, jitter
        rate = float(config["cyclotron"].get("maxRequestsPerSecond") or LAB_REQUESTS_PER_SECOND)
        self.interval = 1.0 / rate          # seconds between lab calls: the pacing, shared by every POST and GET
        self._next_slot = 0.0               # the earliest time the next call may leave
        self.throttled = 0                  # bare 429s (API Gateway "Too Many Requests") answered this run
        self.base = config["cyclotron"]["endpoint"]
        self.refusals: list[dict] = []   # every non-2xx the lab answered, for the run receipt's errors list
        self.rate_limited: dict | None = None   # the first 429/503 this run: {"status", "retryAfter"}; the monitor backs off
        self.answered = 0                        # calls the lab answered below 400 this run

    def _pace(self):
        """Waits for this call's slot: one call per `interval`, however the calls are spread over POST/GET/feedback."""
        now = self.clock()
        start = max(now, self._next_slot)
        self._next_slot = start + self.interval
        if start > now:
            self.sleep(start - now)

    @staticmethod
    def bare_throttle(status: int, payload: dict) -> bool:
        """API Gateway's stage throttle: a 429 with no Retry-After. The lab itself only refuses with 503 + Retry-After."""
        return (status == 429 and parse_retry_after(payload.get("_retryAfter") or payload.get("retryAfter")) is None
                and not (payload.get("code") or payload.get("error")))   # a coded 429 is the lab's own refusal

    def _call(self, method: str, path: str, body: dict | None):
        data = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
        url = self.base + path
        for attempt in range(LAB_THROTTLE_RETRIES + 1):
            self._pace()
            status, payload = self.http(method, url, self.sign(method, url, data), data or None, 30)
            if not self.bare_throttle(status, payload):
                break
            # too fast this second; the gateway refused before the lab saw the call, so repeating it is safe
            self.throttled += 1
            if self.throttled > 1:   # it keeps happening: slow the pacing for the rest of the run
                self.interval = min(self.interval * 1.5, LAB_THROTTLE_SLOWEST_INTERVAL)
            if attempt < LAB_THROTTLE_RETRIES:
                self.sleep(self.jitter(*LAB_THROTTLE_WAIT))
        if status < 400:
            self.answered += 1
        return status, payload

    def classify(self, status: int, payload: dict) -> Exception:
        code = refusal_code(status, payload)
        if status in LAB_OVERLOAD_STATUSES and not self.bare_throttle(status, payload) and self.rate_limited is None:
            self.rate_limited = {"status": status,
                                 "retryAfter": parse_retry_after(payload.get("_retryAfter") or payload.get("retryAfter"))}
        if not 200 <= status < 300:
            excerpt = body_excerpt(status, payload)
            LOG.warning("cyclotron refused: %s", excerpt)
            self.refusals.append({"sourceId": None, "message": f"cyclotron {excerpt}"})
        if code == "source_refused":
            return ItemRefused(code)
        if status == 409 and code == REQUEST_CONFLICT_CODE:
            return RequestConflict(body_excerpt(status, payload))
        if status == 409 and payload.get("detail") == BINDING_CHANGED_DETAIL:
            return StopSweep("binding_changed", "http 409")
        if status == 409 and (code == NOT_READY_CODE or payload.get("detail") == NOT_READY_DETAIL):
            return BindingNotReady(NOT_READY_CODE)
        if status == 409 and code not in STOP_CODES:
            # not a known conflict: it concerns this request only, so it must not stop the whole run, and it may
            # clear by itself, so the story is asked again later
            return ItemRetryLater(body_excerpt(status, payload))
        if code in STOP_CODES or status in (401, 403, 404, 429, 503, 507):
            return StopSweep(code, f"http {status}")
        if status in (400, 413, 422):
            return ItemInvalid(code)   # invalid per the contract: permanent
        if 400 <= status < 500:
            return ItemRetryLater(body_excerpt(status, payload))   # a definite refusal the contract does not call permanent
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

    def post_combined(self, body: dict) -> tuple[str | None, dict | None]:
        """POST /machine/decisions. (jobId, None) for an accepted job, (None, response) for a synchronous result.
        404 raises CombinedUnavailable. Never repeated: an ambiguous answer raises ItemUncertain."""
        try:
            status, payload = self._call("POST", "/machine/decisions", body)
        except (OSError, TimeoutError) as error:
            raise ItemUncertain(f"no answer: {type(error).__name__}") from error
        if status in (200, 201, 202) and isinstance(payload.get("jobId"), str) and payload["jobId"]:
            return payload["jobId"], None
        if status == 200 and isinstance(payload.get("publications"), dict):
            return None, payload
        if status == 404:
            raise CombinedUnavailable()
        raise self.classify(status, payload)

    def poll_combined(self, job_id: str, wait: bool = True) -> dict:
        """Polls GET /machine/decisions/{jobId}; the 200 body maps each publication to its single receipt.
        wait=False is one GET: a job that is still running raises JobRunning."""
        deadline = self.clock() + self.config["cyclotron"]["pollSeconds"]
        delay = 1.0
        while True:
            try:
                status, payload = self._call("GET", f"/machine/decisions/{quote(job_id)}", None)
            except (OSError, TimeoutError):
                status, payload = 0, {}
            if status == 200 and isinstance(payload.get("publications"), dict):
                return payload
            if status == 404:
                raise JobGone()
            if status == 200 and str(payload.get("status") or "") == "failed":
                raise JobFailed()
            if not self._transient(status, payload):
                raise self.classify(status, payload)
            if not wait:
                raise JobRunning()
            if self.clock() + delay > deadline:
                raise StopSweep("pending", "job still running")
            self.sleep(delay)
            delay = min(delay * 1.5, 8.0)

    def classify_entry(self, entry) -> Exception:
        """A publication's refusal inside a completed combined receipt: same shapes as the single receipt."""
        if not isinstance(entry, dict):
            return ItemInvalid("publication receipt is not an object")
        status = next((entry[k] for k in ("httpStatus", "statusCode", "status") if type(entry.get(k)) is int), 0)
        error = entry.get("error")
        code = entry.get("code") or (error.get("code") if isinstance(error, dict) else error)
        if code == NOT_READY_CODE or entry.get("detail") == NOT_READY_DETAIL:
            return BindingNotReady(NOT_READY_CODE)
        return self.classify(status, entry)

    def poll(self, publication_id: str, job_id: str, wait: bool = True) -> dict:
        """Polls only. Returns the completed response; raises StopSweep('pending') when still running,
        or JobRunning after a single GET when wait=False."""
        deadline = self.clock() + self.config["cyclotron"]["pollSeconds"]
        delay = 1.0
        while True:
            try:
                status, payload = self._call("GET", f"/machine/publications/{quote(publication_id)}/commands/{quote(job_id)}", None)
            except (OSError, TimeoutError):
                status, payload = 0, {}
            if status == 200 and payload.get("decision"):
                return payload
            if status == 404:
                raise JobGone()
            if status == 200 and str(payload.get("status") or "") == "failed":
                raise JobFailed()
            if not self._transient(status, payload):
                raise self.classify(status, payload)
            if not wait:
                raise JobRunning()
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


def criteria_fingerprint(response: dict, output_id: str) -> str | None:
    """The fingerprint of the criteria an output was judged against. Cyclotron sends it as `criteriaFingerprint` on each
    `outputs[]` entry; an envelope that only carries the output's `question` gets sha256 (hex) of that UTF-8 string, which is
    how Cyclotron derives it (assumed: no stored envelope carrying both was available to confirm against)."""
    for entry in (response.get("outputs") if isinstance(response, dict) else None) or []:
        if isinstance(entry, dict) and entry.get("id") == output_id:
            value = entry.get("criteriaFingerprint")
            if isinstance(value, str) and value:
                return value
            question = entry.get("question")
            return sha256(question.encode("utf-8")).hexdigest() if isinstance(question, str) and question else None
    return None


def checked_decision(response: dict, publication: dict, config: dict, item_id: str) -> dict:
    """Validate one completed `decide` response and reduce it to the receipt we keep."""
    decision = response.get("decision") if isinstance(response, dict) else None
    if not isinstance(decision, dict) or not isinstance(decision.get("decisionId"), str) or not decision["decisionId"]:
        raise ItemInvalid("response has no decisionId")
    if config.get("accountId"):
        expected = {"contractVersion": CONTRACT_VERSION, "accountId": config["accountId"],
                    "publicationId": publication["publicationId"],
                    "bindingRevision": config["cyclotron"]["bindingRevision"]}
        if any(response.get(key) != value for key, value in expected.items()) or decision.get("itemId") != item_id:
            raise ItemInvalid("Account-bound response identity mismatch")
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
    checked = {"decisionId": decision["decisionId"], "output": publication["output"], "label": classifier["label"],
               "fingerprint": classifier["fingerprint"], "version": classifier["version"],
               "source": {k: source[k] for k in ("id", "revision", "fingerprint") if k in source}}
    confidence = classifier.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and 0 <= confidence <= 1:
        checked["confidence"] = Decimal(str(round(float(confidence), 4)))   # for the Monitoring page; DynamoDB takes Decimal
    criteria = criteria_fingerprint(response, publication["output"])
    if criteria:
        checked["criteriaFingerprint"] = criteria
    return checked


# --- table ----------------------------------------------------------------------------------------

def decimalize(value):
    """DynamoStore._clean hands floats back on read; DynamoDB only accepts Decimal on write."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: decimalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decimalize(v) for v in value]
    return value


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
        self.table.put_item(Item=decimalize(record))

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

    def put_new(self, monitor_id, record) -> bool:
        try:
            self._conditional_put(decimalize(record), "attribute_not_exists(pk)")
            return True
        except ConditionFailed:
            return False

    def query_prefix(self, monitor_id, prefix) -> list[dict]:
        return [self._clean(item) for item in query_prefix(self.table, monitor_id, prefix)]

    def update_fields(self, monitor_id, sk, fields: dict):
        names = {f"#f{n}": key for n, key in enumerate(fields)}
        self.table.update_item(Key={"pk": pk(monitor_id), "sk": sk},
                               UpdateExpression="SET " + ", ".join(f"#f{n} = :v{n}" for n in range(len(fields))),
                               ExpressionAttributeNames=names,
                               ExpressionAttributeValues={f":v{n}": decimalize(value) for n, value in enumerate(fields.values())})

    def reopen_final(self, monitor_id, sk, reason) -> bool:
        """Remove `final` from a ROUTE row, only while its reason is still exactly `reason`; nothing else changes."""
        try:
            self.table.update_item(Key={"pk": pk(monitor_id), "sk": sk}, UpdateExpression="REMOVE #f",
                                   ConditionExpression="#f.#r = :r", ExpressionAttributeNames={"#f": "final", "#r": "reason"},
                                   ExpressionAttributeValues={":r": reason})
            return True
        except Exception as error:
            if getattr(error, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise

    def delete_any(self, monitor_id, sk):
        self.table.delete_item(Key={"pk": pk(monitor_id), "sk": sk})

    def query_partition(self, partition: str) -> list[dict]:
        """Every row of the partition, oldest first, from the sparse `routing` GSI (all pages)."""
        rows, start = [], {}
        while True:
            result = self.table.query(IndexName="routing", KeyConditionExpression="gsi1pk = :p",
                                      ExpressionAttributeValues={":p": partition}, ScanIndexForward=True, **start)
            rows.extend(self._clean(item) for item in result.get("Items", []))
            if not result.get("LastEvaluatedKey"):
                return rows
            start = {"ExclusiveStartKey": result["LastEvaluatedKey"]}


def park_item_prefix(pub_id: str) -> str:
    return f"{PARK_PREFIX}{pub_id}#"


def park_item_sk(pub_id: str, source_id: str, revision: int) -> str:
    """One row per parked item: PARK#<pub>#<sourceId>#<rev>."""
    return f"{park_item_prefix(pub_id)}{source_id}#{revision:06d}"


def gsi_partition(monitor_id: str, name: str) -> str:
    return f"ROUTING#{monitor_id}#{name}"


def set_routing(store, monitor_id: str, disc: dict, routing: str, partition: str | None) -> dict:
    """Write the discovery's routing; a None partition removes it from the GSI (final)."""
    updated = {k: v for k, v in disc.items() if k not in ("gsi1pk",)}
    updated["routing"] = routing
    if partition:
        updated["gsi1pk"] = gsi_partition(monitor_id, "email-references" if disc.get("editorSelectedReference") else partition)
    else:
        updated.pop("gsi1sk", None)
    store.put_any(monitor_id, updated)
    return updated


def route_key(disc: dict) -> str:
    return f"ROUTE#{disc['sourceId']}#{int(disc['revision']):06d}"


def new_route(monitor_id: str, disc: dict) -> dict:
    return {"pk": pk(monitor_id), "sk": route_key(disc), "sourceId": disc["sourceId"], "revision": int(disc["revision"]),
            "fingerprint": disc["fingerprint"], "itemId": item_id_for(monitor_id, disc["sourceId"])}


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


def source_name_for(source_url: str) -> str:
    host = urlsplit(source_url).hostname
    return next((source["name"] for source in SOURCE_TYPES.values() if source["host"] == host), "Monitor")


def lab_decision_records(client, publication: dict, decision: dict, config: dict, reference: dict, disc: dict) -> list[dict]:
    """The `relevance_decision_is` records for one lab decision, shaped by the same builder the sweep uses.

    The References tab builds its Suggestion row, Agree/Overrule and status from this relation. Any current
    decision relation for the Reference is superseded in the same batch (`current_relevance_decision`
    raises on two). The relation id derives from the decision id, so re-delivering the same decision finds
    it already current and writes nothing. Cost per item: one index query, then the builder's
    get-before-write on the node and relation (plus one get and one update per superseded relation).
    """
    from .relevance_decisions import RELEVANCE_RELATION, relevance_decision_records
    lineage_id = reference.get("lineageId") or reference["id"]
    current = [relation for relation in client.list_by_index("semanticRelationsBySubjectState", f"reference#{lineage_id}#current")
               if relation.get("predicate") == RELEVANCE_RELATION and relation.get("relationState") == "current"]
    if any(json.loads(relation.get("metadata") or "{}").get("decisionId") == decision["decisionId"] for relation in current):
        return []
    output = decision["output"]
    cyclotron = config["cyclotron"]
    confidence = decision.get("confidence")
    result = {"label": decision["label"], "version": decision["version"], "fingerprint": decision["fingerprint"],
              **({"confidence": float(confidence)} if confidence is not None else {})}   # GraphQL takes JSON floats
    lab_decision = {"decisionId": decision["decisionId"], "createdAt": decision.get("decidedAt"),
                    "classifiers": {output: result}, "review": {"selected": False}}
    labels = [publication["positiveLabel"], publication["negativeLabel"]]
    provenance = {"system": "cyclotron-lab", "accountId": cyclotron["accountId"], "runId": cyclotron["runId"],
                  "bindingRevision": cyclotron["bindingRevision"], "publicationId": publication["publicationId"],
                  "output": output, "decisionId": decision["decisionId"], "fingerprint": decision["fingerprint"],
                  "version": decision["version"], "labelSet": labels, "sourceId": disc["sourceId"]}
    return relevance_decision_records(
        reference, lab_decision, cyclotron_id=output, positive_label=publication["positiveLabel"],
        now=decision.get("decidedAt") or disc["observedAt"], current_relations=current, labels=labels,
        review_control="thumbs", provenance=provenance)


def deliver_reference(client, publication: dict, disc: dict, decision: dict, config: dict) -> dict:
    """The existing ReferenceIntake: pending Reference + provenance Message recording how it was chosen."""
    validate_email_discovery_scope(disc, config)
    from .monitoring_intake import ReferenceIntake
    source_url = str(disc.get("sourceUrl") or "")
    monitor = Monitor(str(disc.get("monitorId") or "hn"), publication["corpusKey"], publication["corpusId"],
                      publication["appsyncEndpoint"], Path("/nonexistent"), source_url=source_url,
                      source_name="Email submission" if disc.get("sourceType") == "email" else source_name_for(source_url))
    item = SourceItem(str(disc["sourceId"]), disc["title"], disc["canonicalUrl"], disc["sourceItemUrl"],
                      disc.get("sourcePublishedAt"), disc.get("mediaType") or "text/html", tuple(disc.get("aliases") or ()),
                      disc.get("details") or None)
    if item.fingerprint != disc["fingerprint"]:
        raise ItemInvalid("stored fingerprint does not match the discovery")
    if config.get("decisions") == "direct":
        chosen = {"kind": "monitor rule", "system": "direct", "decisionId": decision["decisionId"],
                  "output": decision["output"], "label": decision["label"],
                  "rule": config.get("rule") or "every collected item goes to every configured publication"}
    else:
        chosen = {"kind": "machine decision", "system": "cyclotron", "decisionId": decision["decisionId"],
                  "output": decision["output"], "label": decision["label"],
                  "fingerprint": decision["fingerprint"], "version": decision["version"],
                  "accountId": config["cyclotron"]["accountId"], "runId": config["cyclotron"]["runId"],
                  "bindingRevision": config["cyclotron"]["bindingRevision"]}
    provenance = {**monitor.binding, "sourceId": item.source_id, "sourceItemUrl": item.source_item_url,
                  "fingerprint": item.fingerprint, "observedAt": disc["observedAt"], "revision": int(disc["revision"]),
                  "machineDecision": chosen, **({"details": disc["details"]} if disc.get("details") else {})}
    if disc.get("sourceType") == "email":
        provenance["emailSubmission"] = disc["emailProvenance"]
        provenance["sectionHandoff"] = "pending-reference-site-sweep"
    intake = ReferenceIntake(client, monitor, auth_mode="iam")
    if config.get("decisions") == "direct":
        return intake(item, provenance)   # the monitor's own rule: no machine decision, so no decision relation
    return intake(item, provenance, lambda reference: lab_decision_records(client, publication, decision, config, reference, disc),
                  reference_id=(disc.get("editorSelectedReference") or {}).get("referenceId"))


# --- the run ----------------------------------------------------------------------------------------

class Router:
    def __init__(self, store, config: dict, *, monitor_id="hn", now: float, run_id: str,
                 cyclotron: CyclotronClient | None, appsync: Callable[[str], Any], deliver=deliver_reference,
                 context_receipt=editorial_context_receipt, time_left: Callable[[], float] = lambda: 1e9,
                 start_procedure: Callable[[dict], None] | None = None, cognito=None, rung_job_ids=(),
                 enricher: Enricher | None = None):
        self.store, self.config, self.monitor_id, self.now, self.run_id = store, config, monitor_id, now, run_id
        self.rung = {j for j in rung_job_ids if j}   # jobs a Decision Ready doorbell named: asked about despite their backoff
        self._fresh: set = set()     # jobs posted by this run: checked at once, their backoff starts with the next run
        self._grown: set = set()     # jobs whose backoff already grew this run: one growth per run
        self._lab_state = None
        self.start_procedure = start_procedure
        self.cognito = cognito
        self.enricher = enricher     # item enrichment (capture, summary, GROBID) before the decision; None leaves items as discovered
        self._enriched: dict = {}
        self.cyclotron, self.appsync_factory, self.deliver = cyclotron, appsync, deliver
        self.context_receipt, self.time_left = context_receipt, time_left
        self._clients: dict = {}
        self._contexts: dict = {}
        self.publications = {p["publicationId"]: p for p in config["publications"]}
        self.active_publications = None
        self.nowait = False        # live Cyclotron sweeps post and check once; the collect window does the waiting
        self.post_allowed = True   # the collector sets this False: it never sends a new POST
        self.holding = config.get("holdDecisions") is True   # CONFIG#router holdDecisions: no decide POST; enrichment, polling and feedback still run
        self.combined_unavailable = False   # a 404 from POST /machine/decisions, remembered for the run
        self.counts = {"examined": 0, "dryRunValidated": 0, "decided": 0, "delivered": 0, "routed": 0,
                       "refused": 0, "uncertain": 0, "awaiting": 0, "error": 0, "backedOff": 0, "deliveryFailed": 0, "skippedNotReady": 0,
                       "parked": 0, "backfilled": 0, "proceduresStarted": 0, "procedureStartFailed": 0,
                       "procedureNotTriggered": 0, "procedureSkipped": 0, "procedureDeferred": 0, "procedureRetried": 0,
                       "enriched": 0, "enrichmentWaiting": 0, "curationCopied": 0, "curationCopyFailed": 0}
        self._parks: dict = {}
        self._automation_rows: dict = {}

    # lab backoff ------------------------------------------------------------------------------------

    def lab_backoff_until(self) -> int:
        if self._lab_state is None:
            self._lab_state = self.store.get_any(self.monitor_id, LAB_BACKOFF_SK) or {}
            if self._lab_state.get("status") == 429 and not self._lab_state.get("retryAfter"):
                # an old pause caused by the API Gateway throttle, which is not the lab asking for one: clear it
                self.store.delete_any(self.monitor_id, LAB_BACKOFF_SK)
                self._lab_state = {}
        return int(self._lab_state.get("until", 0))

    def lab_paused(self) -> bool:
        """True while the lab asked this monitor to wait (a 429/503 earlier): no run calls the lab until then."""
        return (self.cyclotron is not None and self.config["mode"] == "live" and self.config["decisions"] == "cyclotron"
                and self.lab_backoff_until() > self.now)

    def paused_result(self) -> dict:
        return {"status": "stopped", "stoppedBy": "lab_backoff", "errors": [],
                "waitingForClassifier": []}

    def settle_lab_backoff(self) -> int | None:
        """After the run: a 429/503 sets `until` (Retry-After, else exponential on consecutive refused runs); a run the
        lab answered cleanly clears it. Returns the pause's end when one is in force."""
        client = self.cyclotron
        if client is None:
            return None
        refused = getattr(client, "rate_limited", None)
        if refused:
            strikes = int((self.store.get_any(self.monitor_id, LAB_BACKOFF_SK) or {}).get("strikes", 0)) + 1
            after = refused.get("retryAfter")
            wait = min(after, LAB_RETRY_AFTER_MAX) if after else min(LAB_BACKOFF_FIRST * 2 ** min(strikes - 1, 32), LAB_BACKOFF_MAX)
            until = int(self.now + wait)
            self.store.put_any(self.monitor_id, {"pk": pk(self.monitor_id), "sk": LAB_BACKOFF_SK, "until": until,
                                                 "strikes": strikes, "status": refused["status"],
                                                 "retryAfter": after, "at": _iso(self.now)})
            return until
        if getattr(client, "answered", 0) and self.lab_backoff_until():
            self.store.delete_any(self.monitor_id, LAB_BACKOFF_SK)
            return None
        return self.lab_backoff_until() if self.lab_backoff_until() > self.now else None

    # per-job backoff --------------------------------------------------------------------------------

    def job_due(self, job: dict) -> bool:
        return (int(job.get("nextPollAt", 0)) <= self.now or job.get("jobId") in self.rung
                or job.get("jobId") in self._fresh)

    def note_still_running(self, job: dict, route: dict):
        """The lab answered 'running': the job waits POLL_BACKOFF_FIRST * 2**n seconds before the next check."""
        job_id = job.get("jobId")
        self.rung.discard(job_id)   # a doorbell buys one check, not a standing bypass
        if job_id in self._fresh or job_id in self._grown:
            return
        checks = int(job.get("pollBackoffs", 0))
        job["nextPollAt"] = int(self.now + min(POLL_BACKOFF_FIRST * 2 ** min(checks, 32), POLL_BACKOFF_MAX))
        job["pollBackoffs"] = checks + 1
        self._grown.add(job_id)
        self.save(route)

    @staticmethod
    def job_done(job: dict):
        job.pop("nextPollAt", None)
        job.pop("pollBackoffs", None)

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
        mode = self.config["mode"]

        def part(name):
            return self.store.query_partition(gsi_partition(self.monitor_id, name))

        if mode == "dry-run":
            return part(PARTITION_COLLECTED)
        decided = [d for d in part(PARTITION_DECIDED)
                   if (self.get_route(d).get("nextAttemptAt") or 0) <= self.now]
        fresh = sorted((d for d in part(PARTITION_COLLECTED) + part(PARTITION_DRY_RUN)
                        if (self.get_route(d).get("nextAttemptAt") or 0) <= self.now), key=lambda d: d["gsi1sk"])
        return decided + fresh

    def selected_references(self, source_ids=None) -> dict:
        """Only editor-imported References; never sweep receipt discoveries, feedback or procedures."""
        if self.lab_paused():
            return {"status": "stopped", "stoppedBy": "lab_backoff"}
        if source_ids is not None:
            if (not isinstance(source_ids, list) or not 1 <= len(source_ids) <= 20
                    or any(not isinstance(s, str) or not re.fullmatch(r"[a-f0-9]{64}", s) for s in source_ids)):
                raise ValueError("Provide 1 to 20 exact selected source ids")
            candidates = [self.store.get_any(self.monitor_id, f"DISC#{source}#000001") for source in dict.fromkeys(source_ids)]
        else:
            candidates = self.store.query_partition(gsi_partition(self.monitor_id, "email-references"))
        for disc in candidates:
            if (not disc or not disc.get("editorSelectedReference") or disc.get("sourceType") != "email"
                    or disc.get("gsi1pk") != gsi_partition(self.monitor_id, "email-references")):
                continue
            if self.time_left() < MIN_REMAINING_SECONDS:
                break
            if (self.get_route(disc).get("nextAttemptAt") or 0) > self.now:
                continue
            try:
                (self.live if self.config["mode"] == "live" else self.dry_run)(disc)
            except StopSweep as error:
                return {"status": "stopped", "stoppedBy": str(error)[:200]}
        return {"status": "completed"}

    # enrichment -------------------------------------------------------------------------------------

    def inputs_for(self, disc: dict) -> dict | None:
        """`{summary, body}` the item's finished enrichment gives the decision, or None (no enricher, or not enriched).
        Never runs an enrichment."""
        if self.enricher is None:
            return None
        key = (disc["sourceId"], int(disc["revision"]))
        if key not in self._enriched:
            row = self.store.get_any(self.monitor_id, enrich_sk(disc))
            if not row or not row.get("final"):
                return None
            self._enriched[key] = decision_inputs(row, self.enricher.texts)
        return self._enriched[key]

    def enrichment_for(self, disc: dict, route: dict) -> dict | None:
        """Enrich the item once, before anything is posted. Returns its decision inputs, or None when enrichment is off or the item
        was posted before it existed. Raises EnrichmentPending while an attempt is waiting to be retried or this run is out of time:
        the item is simply picked up again next run (enrichment is attempted, then the decision proceeds with whatever exists)."""
        if self.enricher is None or self.config["mode"] != "live":
            return None
        if self.inputs_for(disc) is not None:
            return self.inputs_for(disc)
        if (route.get("combinedJob") or {}).get("requestId") or route.get("jobs"):
            return None   # already posted unenriched: the lab holds that text; do not change what it decided on
        if not self.post_allowed:
            raise EnrichmentPending()   # the collector never starts new work for an item
        sk = enrich_sk(disc)
        row = self.store.get_any(self.monitor_id, sk) or new_row(self.monitor_id, disc)
        if int(row.get("nextAttemptAt") or 0) > self.now or self.time_left() < MIN_REMAINING_SECONDS:
            self.counts["enrichmentWaiting"] += 1
            raise EnrichmentPending()
        row = enrich_item(row, disc, self.monitor_id, self.enricher, datetime.fromtimestamp(self.now, timezone.utc))
        self.store.put_any(self.monitor_id, row)
        if not row.get("final"):
            self.counts["enrichmentWaiting"] += 1
            raise EnrichmentPending()
        self.counts["enriched"] += 1
        return self.inputs_for(disc)

    def copy_curation(self, publication: dict, disc: dict, result: dict) -> str | None:
        """Give the delivered Reference the item's curation (the card and bodies the editor sees). Never fails the delivery: a
        Reference without it is filled in by the post-delivery curation procedure."""
        if self.enricher is None:
            return None
        row = self.store.get_any(self.monitor_id, enrich_sk(disc))
        if not row or not row.get("final"):
            return None
        try:
            client = self.client(publication)
            reference = client.get_record("Reference", result["referenceId"])
            outcome = copy_curation(client, reference, row, self.enricher.texts, datetime.fromtimestamp(self.now, timezone.utc))
        except Exception as error:
            self.counts["curationCopyFailed"] += 1
            return f"failed: {short(error)}"
        self.counts["curationCopied"] += outcome == "copied"
        return outcome

    # dry-run ----------------------------------------------------------------------------------------

    def dry_run(self, disc: dict):
        original_active = self.active_publications
        try:
            self._dry_run_scoped(disc)
        finally:
            self.active_publications = original_active

    def _dry_run_scoped(self, disc: dict):
        route = self.get_route(disc)
        try:
            validate_email_discovery_scope(disc, self.config)
            if disc.get("sourceType") == "email":
                self.active_publications = self.authorized_email_publications(disc)
                if not self.active_publications:
                    return self.finish(disc, route, "refused", "email destination no longer permits this publication")
        except ItemInvalid as error:
            return self.finish(disc, route, "error", str(error))
        requests = {}
        for publication in (self.active_publications or self.config["publications"]):
            if self.config["decisions"] == "direct":
                try:
                    self.check_rule(disc)
                    requests[publication["publicationId"]] = {"direct": True, "wouldDeliver": True}
                except ItemExcluded as excluded:
                    requests[publication["publicationId"]] = {"direct": True, "wouldDeliver": False, "reason": str(excluded)}
                continue
            try:
                built = build_decide_request(self.config, publication, disc, enrichment=self.inputs_for(disc))
            except (ItemInvalid, ValueError) as error:
                return self.finish(disc, route, "error", f"invalid request: {error}")
            requests[publication["publicationId"]] = {
                "path": built["path"], "requestId": built["body"]["requestId"], "bytes": len(json.dumps(built["body"], separators=(",", ":"))),
                "body": built["body"]}
        active = self.active_publications or self.config["publications"]
        contexts = {p["publicationId"]: self.context_for(p) for p in active}
        previous = route.get("dryRun") or {}
        route["dryRun"] = {"count": int(previous.get("count", 0)) + 1, "validatedAt": _iso(self.now),
                           "runId": self.run_id, "requests": requests, "contexts": contexts}
        if self.config["decisions"] == "cyclotron" and len(active) > 1:
            try:
                combined = build_combined_request(self.config, active, disc, enrichment=self.inputs_for(disc))
            except (ItemInvalid, ValueError) as error:
                return self.finish(disc, route, "error", f"invalid request: {error}")
            route["dryRun"]["combined"] = {
                "path": combined["path"], "requestId": combined["body"]["requestId"],
                "bytes": len(json.dumps(combined["body"], separators=(",", ":"))), "body": combined["body"]}
        self.save(route)
        set_routing(self.store, self.monitor_id, disc, PARTITION_DRY_RUN, PARTITION_DRY_RUN)
        self.counts["dryRunValidated"] += 1

    # live ---------------------------------------------------------------------------------------------

    # not-ready bindings and parking ---------------------------------------------------------------

    def park(self, pub_id: str) -> dict | None:
        """The binding's park header (`PARK#<pub>`: reason, backoff, probes, ready). Its parked items are rows of
        their own (`park_item_sk`), so nothing is dropped and no item can outgrow a DynamoDB row."""
        if pub_id not in self._parks:
            park = self.store.get_any(self.monitor_id, PARK_PREFIX + pub_id)
            if park and "items" in park:
                park = self.migrate_park(pub_id, park)
            self._parks[pub_id] = park
        return self._parks[pub_id]

    def migrate_park(self, pub_id: str, park: dict) -> dict:
        """A header written before items had rows of their own carried them in one list (kept to the last 25).
        Keep every one of them as a row, then rewrite the header without the list; a crash between the two is
        repaired by the next read."""
        for entry in park["items"]:
            self.put_park_item(pub_id, entry["sourceId"], int(entry["revision"]), park.get("since"))
        park = {k: v for k, v in park.items() if k != "items"}
        self.store.put_any(self.monitor_id, park)
        return park

    def put_park_item(self, pub_id: str, source_id: str, revision: int, parked_at: str | None = None):
        self.store.put_any(self.monitor_id, {"pk": pk(self.monitor_id), "sk": park_item_sk(pub_id, source_id, revision),
                                             "publicationId": pub_id, "sourceId": source_id, "revision": revision,
                                             "parkedAt": parked_at or _iso(self.now)})

    def parked_items(self, pub_id: str) -> list[dict]:
        """Every item parked for the binding (all pages of the partition's PARK#<pub># rows), oldest first."""
        return sorted(self.store.query_prefix(self.monitor_id, park_item_prefix(pub_id)),
                      key=lambda row: (str(row.get("parkedAt")), row["sk"]))

    def save_park(self, pub_id: str, park: dict):
        park = {k: v for k, v in park.items() if k != "items"}
        self._parks[pub_id] = park
        self.store.put_any(self.monitor_id, park)

    def gate_open(self, pub_id: str) -> bool:
        """False while the binding is parked and its next probe is not due. A due probe is claimed here, so
        only one item per run probes a waiting binding."""
        park = self.park(pub_id)
        if not park or park.get("ready") or int(park.get("nextProbeAt", 0)) <= self.now:
            if park and not park.get("ready"):
                backoff = min(int(park.get("backoffSeconds", PARK_BACKOFF_FIRST)) * 2, PARK_BACKOFF_MAX)
                self.save_park(pub_id, {**park, "backoffSeconds": backoff, "nextProbeAt": int(self.now + backoff),
                                        "probes": int(park.get("probes", 0)) + 1, "lastProbeAt": _iso(self.now)})
            return True
        return False

    def authorized_email_publications(self, disc: dict) -> list[dict]:
        if disc.get("emailTrustMode") == "data-only":
            validate_email_discovery_scope(disc, self.config)
            selection = disc.get("editorSelectedReference")
            if selection:
                if (selection != disc.get("emailProvenance", {}).get("editorSelection")
                        or not selection.get("subject")
                        or disc["emailDestinationPublicationIds"] != [selection.get("publicationId")]):
                    raise ItemInvalid("Invalid editor-selected Reference scope")
                publication = self.publications.get(selection["publicationId"])
                ref = self.client(publication).get_record("Reference", selection.get("referenceId")) if publication else None
                if (not ref or ref.get("corpusId") != publication["corpusId"]
                        or ref.get("sourceUri") != disc["canonicalUrl"] or ref.get("versionState") != "current"):
                    raise ItemInvalid("Imported Reference does not match the selected email candidate")

            allowed = set(disc["emailDestinationPublicationIds"])
            return [p for p in self.config["publications"] if p["publicationId"] in allowed]
        if self.cognito is None:
            raise ItemInvalid("Email editor membership lookup is unavailable")
        try:
            current = set(publication_ids_for_editor(
                disc["emailProvenance"]["sender"], self.config["publications"], self.cognito))
        except (EditorLookupUnavailable, KeyError) as error:
            raise ItemInvalid("Email editor membership lookup failed closed") from error
        allowed = set(disc["emailAuthorizedPublicationIds"]) & current
        return [p for p in self.config["publications"] if p["publicationId"] in allowed]

    def note_not_ready(self, pub_id: str, disc: dict, route: dict, reason: str):
        park = self.park(pub_id) or {"pk": pk(self.monitor_id), "sk": PARK_PREFIX + pub_id, "publicationId": pub_id,
                                      "since": _iso(self.now), "backoffSeconds": PARK_BACKOFF_FIRST,
                                      "nextProbeAt": int(self.now + PARK_BACKOFF_FIRST), "probes": 0}
        if not disc.get("editorSelectedReference"):
            self.put_park_item(pub_id, disc["sourceId"], int(disc["revision"]))
        self.save_park(pub_id, {**park, "reason": reason[:200], "ready": False})
        route.setdefault("notReady", {})[pub_id] = {"reason": reason[:200], "at": _iso(self.now)}
        self.counts["skippedNotReady"] += 1

    def note_ready(self, pub_id: str):
        park = self.park(pub_id)
        if not park or park.get("ready"):
            return
        if self.parked_items(pub_id):
            self.save_park(pub_id, {**park, "ready": True})   # parked items are decided by backfill()
        else:
            self.store.delete_any(self.monitor_id, PARK_PREFIX + pub_id)
            self._parks[pub_id] = None

    def waiting_for_classifier(self) -> list[str]:
        return sorted(p["publicationId"] for p in self.config["publications"]
                      if (self.park(p["publicationId"]) or {}).get("ready") is False)

    def backfill(self) -> int:
        """Decide parked items for bindings whose output became ready; bounded only by the invocation's time."""
        done = 0
        for publication in (self.active_publications or self.config["publications"]):
            pub_id = publication["publicationId"]
            park = self.park(pub_id)
            for row in (self.parked_items(pub_id) if park and park.get("ready") else ()):
                if self.time_left() < MIN_REMAINING_SECONDS:
                    return done
                entry = row
                self.store.delete_any(self.monitor_id, row["sk"])
                disc = self.store.get_any(self.monitor_id, f"DISC#{entry['sourceId']}#{int(entry['revision']):06d}")
                route = self.store.get_any(self.monitor_id, f"ROUTE#{entry['sourceId']}#{int(entry['revision']):06d}")
                if disc and route and route.get("decision"):
                    done += 1
                    self.backfill_one(publication, disc, route)
            if park and park.get("ready") and not self.store.query_prefix(self.monitor_id, park_item_prefix(pub_id)):
                self.store.delete_any(self.monitor_id, PARK_PREFIX + pub_id)
                self._parks[pub_id] = None
        return done

    def backfill_one(self, publication: dict, disc: dict, route: dict):
        original_active = self.active_publications
        if disc.get("sourceType") == "email":
            try:
                authorized = self.authorized_email_publications(disc)
            except ItemInvalid as error:
                route.setdefault("notReady", {})[publication["publicationId"]] = {"reason": str(error)[:200], "at": _iso(self.now)}
                self.save(route)
                return
            allowed = {p["publicationId"] for p in authorized}
            if publication["publicationId"] not in allowed:
                return
            self.active_publications = authorized
            route["publications"] = {key: value for key, value in route.get("publications", {}).items() if key in allowed}
            if route.get("decision"):
                route["decision"]["publications"] = {key: value for key, value in
                                                       route["decision"].get("publications", {}).items() if key in allowed}
        try:
            self._backfill_one(publication, disc, route)
        finally:
            self.active_publications = original_active

    def _backfill_one(self, publication: dict, disc: dict, route: dict):
        pub_id = publication["publicationId"]
        item_id = item_id_for(self.monitor_id, disc["sourceId"])
        try:
            self.decide_binding(publication, disc, route, item_id)
            checked = route["jobs"][pub_id]["checked"]
            if checked["decisionId"] != route["decision"]["decisionId"]:
                raise ItemInvalid("backfilled decision is not the item's shared decision")
        except BindingNotReady as error:
            self.note_not_ready(pub_id, disc, route, str(error))
            self.save(route)
            return
        except StopSweep:
            raise
        except Exception as error:
            route.setdefault("notReady", {})[pub_id] = {"reason": f"backfill failed: {short(error)}", "at": _iso(self.now)}
            self.save(route)
            return
        route["decision"]["publications"][pub_id] = {k: checked[k] for k in
                                                     DECISION_KEYS if k in checked}
        route.get("notReady", {}).pop(pub_id, None)
        if checked["label"] == publication["positiveLabel"] or disc.get("editorSelectedReference"):
            route.setdefault("publications", {})[pub_id] = {"label": checked["label"], "delivered": False, "attempts": 0}
        self.save(route)
        self.counts["backfilled"] += 1
        if route.get("publications", {}).get(pub_id) and not self.deliver_positive(disc, route):
            set_routing(self.store, self.monitor_id, disc, "decided", PARTITION_DECIDED)

    # live ---------------------------------------------------------------------------------------------

    def decide(self, disc: dict, route: dict) -> None:
        """One `decide` per binding. Jobs are recorded before and after sending; POST is never repeated.
        A binding whose output is not ready (criteria_pending) is skipped for this item and parked."""
        jobs = route.setdefault("jobs", {})
        item_id = item_id_for(self.monitor_id, disc["sourceId"])
        todo = []
        for publication in (self.active_publications or self.config["publications"]):
            pub_id = publication["publicationId"]
            if not jobs.get(pub_id, {}).get("checked"):
                if not self.gate_open(pub_id):
                    self.note_not_ready(pub_id, disc, route, (self.park(pub_id) or {}).get("reason", NOT_READY_CODE))
                    continue
                todo.append(publication)
        if todo:
            self.enrichment_for(disc, route)   # curation BEFORE the decision: capture, summary, GROBID; raises EnrichmentPending
        running = False
        for publication in self.decide_combined(todo, disc, route, item_id):
            pub_id = publication["publicationId"]
            try:
                self.decide_binding(publication, disc, route, item_id)
            except BindingNotReady as error:
                self.note_not_ready(pub_id, disc, route, str(error))
                continue
            except JobRunning:
                running = True   # post the story's other bindings now; all of them are collected together
                continue
            self.note_ready(pub_id)
        if running:
            raise JobRunning()
        active = self.active_publications or self.config["publications"]
        if not any(jobs.get(p["publicationId"], {}).get("checked") for p in active):
            raise AllBindingsNotReady()
        checked = {pid: jobs[pid]["checked"] for pid in (p["publicationId"] for p in active)
                   if jobs.get(pid, {}).get("checked")}
        if len({c["decisionId"] for c in checked.values()}) != 1:
            raise ItemInvalid("publications did not share one native decision")
        if len({json.dumps(c["source"], sort_keys=True) for c in checked.values()}) != 1:
            raise ItemInvalid("publications reported different source revisions")
        first = next(iter(checked.values()))
        route["decision"] = {
            "decisionId": first["decisionId"], "source": first["source"], "decidedAt": _iso(self.now),
            "accountId": self.config["cyclotron"]["accountId"], "runId": self.config["cyclotron"]["runId"],
            "bindingRevision": self.config["cyclotron"]["bindingRevision"],
            "publications": {pid: {k: c[k] for k in DECISION_KEYS if k in c}
                             for pid, c in checked.items()}}
        route["publications"] = {pid: {"label": c["label"], "delivered": False, "attempts": 0}
                                 for pid, c in checked.items() if c["label"] == self.publications[pid]["positiveLabel"] or disc.get("editorSelectedReference")}
        route.pop("nextAttemptAt", None)
        self.save(route)
        self.counts["decided"] += 1


    def check_decision(self, response: dict, publication: dict, item_id: str) -> dict:
        """checked_decision, plus remember the publication's latest criteria fingerprint for the feedback pass."""
        checked = checked_decision(response, publication, self.config, item_id)
        criteria = checked.get("criteriaFingerprint")
        key = f"CRIT#{publication['publicationId']}"
        if criteria and (self.store.get_any(self.monitor_id, key) or {}).get("criteriaFingerprint") != criteria:
            self.store.put_any(self.monitor_id, {"pk": pk(self.monitor_id), "sk": key, "criteriaFingerprint": criteria,
                                                 "output": checked["output"], "decisionId": checked["decisionId"],
                                                 "recordedAt": _iso(self.now)})
        return checked

    def posted_under(self) -> dict:
        """The run and binding revision a job is being posted under, stored with it."""
        cyclotron = self.config["cyclotron"]
        return {"runId": cyclotron["runId"], "bindingRevision": cyclotron["bindingRevision"]}

    def decide_combined(self, todo: list[dict], disc: dict, route: dict, item_id: str, reposted: bool = False) -> list[dict]:
        """One POST /machine/decisions for the story's unchecked bindings, one poll loop, then each publication's
        receipt is checked and stored under `jobs` exactly as a per-publication decide would. Returns the
        publications that still need the per-publication path (no combined endpoint, a pending output
        somewhere in the set, or a publication the receipt left out)."""
        stored = route.get("combinedJob")
        if self.cyclotron is None or not todo and not stored:
            return todo
        if not stored and (len(todo) < 2 or self.combined_unavailable):
            return todo
        # a stored job is always polled by its jobId, whatever request id or run it was posted under: only a 409
        # request_conflict, a failed job or a 404 (below) discards it
        if stored and not stored.get("jobId"):
            raise ItemUncertain("an earlier POST had no recorded answer")
        response = None
        if not stored:
            if not self.post_allowed or self.holding:
                return todo   # the collector sends nothing; stored per-publication jobs are still polled
            built = build_combined_request(self.config, todo, disc, int(route.get("attempt", 0)), enrichment=self.inputs_for(disc))
            stored = route["combinedJob"] = {"requestId": built["body"]["requestId"], "postedAt": int(self.now),
                                             "publications": list(built["body"]["payload"]["bindings"]),
                                             "via": VIA_DECISIONS, **self.posted_under()}
            self.save(route)   # recorded BEFORE sending: an interrupted run must not POST again
            try:
                job_id, response = self.cyclotron.post_combined(built["body"])
            except ItemUncertain:
                raise
            except RequestConflict:
                del route["combinedJob"]   # the lab knows this id under other content: discard, re-post once under a new id
                if reposted:
                    self.save(route)
                    raise
                route["attempt"] = int(route.get("attempt", 0)) + 1
                self.save(route)
                return self.decide_combined(todo, disc, route, item_id, True)
            except (CombinedUnavailable, BindingNotReady) as reason:
                del route["combinedJob"]   # nothing was started
                self.save(route)
                self.combined_unavailable = self.combined_unavailable or isinstance(reason, CombinedUnavailable)
                return todo
            except Exception:
                del route["combinedJob"]
                self.save(route)
                raise
            if job_id:
                stored["jobId"] = job_id
                self._fresh.add(job_id)
                self.save(route)
        if response is None:
            if not self.job_due(stored):
                raise JobRunning()   # still inside its own backoff: no call to the lab
            try:
                response = self.cyclotron.poll_combined(stored["jobId"], wait=not self.nowait)
            except JobRunning:
                self.note_still_running(stored, route)
                raise
            except BindingNotReady:
                del route["combinedJob"]   # a pending output in the set: the per-publication path finds out which
                self.save(route)
                return todo
            except JobGone:
                del route["combinedJob"]
                self.save(route)
                if reposted:
                    raise ItemInvalid("lab does not know the job posted for this story (404 after a re-post)")
                return self.decide_combined(todo, disc, route, item_id, True)
            except JobFailed:
                del route["combinedJob"]   # the job ended failed: re-post once under a new id
                route["attempt"] = int(route.get("attempt", 0)) + 1
                self.save(route)
                if reposted:
                    raise ItemInvalid("the job posted for this story failed again after a re-post")
                return self.decide_combined(todo, disc, route, item_id, True)
            except StopSweep as stop:
                if stop.code in NON_CONSUMING_REFUSALS:
                    del route["combinedJob"]
                    route["attempt"] = int(route.get("attempt", 0)) + 1
                    self.save(route)
                raise
        if response.get("accountId") not in (None, self.config["cyclotron"]["accountId"]) or \
                response.get("jobId") not in (None, stored["jobId"]):
            raise ItemInvalid("combined response identity mismatch")
        receipts = response.get("publications") or {}
        jobs = route.setdefault("jobs", {})
        remaining, failure = [], None
        for publication in todo:
            pub_id = publication["publicationId"]
            entry = receipts.get(pub_id)
            if entry is None:
                remaining.append(publication)
                continue
            try:
                if not isinstance(entry, dict) or not entry.get("decision"):
                    raise self.cyclotron.classify_entry(entry)
                jobs[pub_id] = {"requestId": stored["requestId"], "postedAt": int(stored["postedAt"]),
                                "jobId": stored["jobId"], "via": VIA_DECISIONS, **self.posted_under(),
                                "checked": self.check_decision(entry, publication, item_id)}
                self.note_ready(pub_id)
            except BindingNotReady as error:
                self.note_not_ready(pub_id, disc, route, str(error))
            except Exception as error:   # the first refusal decides the item; the others' receipts are kept
                failure = failure or error
        route.pop("combinedJob", None)
        if isinstance(failure, StopSweep) and failure.code in NON_CONSUMING_REFUSALS:
            route["attempt"] = int(route.get("attempt", 0)) + 1
        self.save(route)
        if failure:
            raise failure
        return remaining

    def decide_binding(self, publication: dict, disc: dict, route: dict, item_id: str, reposted: bool = False) -> None:
        validate_email_discovery_scope(disc, self.config)
        jobs = route.setdefault("jobs", {})
        pub_id = publication["publicationId"]
        built = build_decide_request(self.config, publication, disc, int(route.get("attempt", 0)), enrichment=self.inputs_for(disc))
        job = jobs.get(pub_id)
        if job and job.get("checked"):
            return   # already decided under an earlier request id; the shared decision is cached
        # a stored job is polled by its jobId whatever request id or run it was posted under
        if job and not job.get("jobId"):
            raise ItemUncertain("an earlier POST had no recorded answer")
        elif not job:
            if not self.post_allowed or self.holding:
                raise NotPosting()
            jobs[pub_id] = {"requestId": built["body"]["requestId"], "postedAt": int(self.now),
                            "via": VIA_PUBLICATION, **self.posted_under()}
            self.save(route)   # recorded BEFORE sending: an interrupted run must not POST again
            try:
                job_id, immediate = self.cyclotron.post(pub_id, built["body"])
            except ItemUncertain:
                raise
            except RequestConflict:
                del jobs[pub_id]   # the lab knows this id under other content: discard, re-post once under a new id
                if reposted:
                    self.save(route)
                    raise
                route["attempt"] = int(route.get("attempt", 0)) + 1
                self.save(route)
                return self.decide_binding(publication, disc, route, item_id, True)
            except Exception:
                del jobs[pub_id]   # definitively refused: nothing was started, a later run may send it
                self.save(route)
                raise
            if job_id:
                jobs[pub_id]["jobId"] = job_id
                self._fresh.add(job_id)
                self.save(route)
            else:
                jobs[pub_id]["checked"] = self.check_decision(immediate, publication, item_id)
                self.save(route)
                return
        if not self.job_due(jobs[pub_id]):
            raise JobRunning()   # still inside its own backoff: no call to the lab
        try:
            if job_via(route, jobs[pub_id]) == VIA_DECISIONS:
                # a combined job lives behind GET /machine/decisions/{jobId}; the per-publication route would 404 it
                response = self.poll_combined_entry(pub_id, jobs[pub_id]["jobId"])
            else:
                response = self.cyclotron.poll(pub_id, jobs[pub_id]["jobId"], wait=not self.nowait)
        except JobRunning:
            self.note_still_running(jobs[pub_id], route)
            raise
        except BindingNotReady:
            del jobs[pub_id]   # nothing ran at the provider; the park decides when to ask again
            self.save(route)
            raise
        except JobGone:
            del jobs[pub_id]
            self.save(route)
            if reposted:
                raise ItemInvalid("lab does not know the job posted for this publication (404 after a re-post)")
            return self.decide_binding(publication, disc, route, item_id, True)
        except JobFailed:
            del jobs[pub_id]   # the job ended failed: re-post once under a new id
            route["attempt"] = int(route.get("attempt", 0)) + 1
            self.save(route)
            if reposted:
                raise ItemInvalid("the job posted for this publication failed again after a re-post")
            return self.decide_binding(publication, disc, route, item_id, True)
        except StopSweep as stop:
            if stop.code in NON_CONSUMING_REFUSALS:
                # Nothing ran at the provider. Drop the refused job and use a new request id next time.
                del jobs[pub_id]
                route["attempt"] = int(route.get("attempt", 0)) + 1
                self.save(route)
            raise
        jobs[pub_id]["checked"] = self.check_decision(response, publication, item_id)
        self.job_done(jobs[pub_id])
        self.save(route)

    def poll_combined_entry(self, pub_id: str, job_id: str) -> dict:
        """One publication's receipt out of a combined job, polled through the route the job was posted to."""
        response = self.cyclotron.poll_combined(job_id, wait=not self.nowait)
        entry = (response.get("publications") or {}).get(pub_id)
        if entry is None:
            raise ItemInvalid("combined receipt has no entry for this publication")
        if not isinstance(entry, dict) or not entry.get("decision"):
            raise self.cyclotron.classify_entry(entry)
        return entry

    def check_rule(self, disc: dict) -> None:
        """A direct monitor's optional `rule`, run on the structured fields the collector stored."""
        rule = self.config.get("rule")
        if rule and not hf_accepts(disc.get("details") or {}, rule):
            raise ItemExcluded("excluded by the monitor's rule")

    def decide_direct(self, disc: dict, route: dict) -> None:
        """The monitor's own rule: deliver to every configured publication, no relevance call."""
        self.check_rule(disc)
        decision_id = f"direct-{self.monitor_id}-{disc['sourceId']}-{int(disc['revision']):06d}"
        route["decision"] = {
            "decisionId": decision_id, "source": {"revision": int(disc["revision"])}, "decidedAt": _iso(self.now),
            "system": "direct", "bindingRevision": "direct",
            "publications": {p["publicationId"]: {"output": f"{self.monitor_id}-direct", "label": p["positiveLabel"]}
        for p in (self.active_publications or self.config["publications"])}}
        route["publications"] = {p["publicationId"]: {"label": p["positiveLabel"], "delivered": False, "attempts": 0}
                                 for p in (self.active_publications or self.config["publications"])}
        route.pop("nextAttemptAt", None)
        self.save(route)
        self.counts["decided"] += 1

    def deliver_positive(self, disc: dict, route: dict) -> bool:
        """Deliver to every positive publication that is not yet delivered; failures stay per publication."""
        validate_email_discovery_scope(disc, self.config)
        decision = route["decision"]
        all_delivered = True
        for pub_id, state in route["publications"].items():
            if state.get("delivered"):
                continue
            publication = self.publications.get(pub_id)
            try:
                if publication is None:
                    raise ItemInvalid("publication is no longer configured")
                receipt = {"decisionId": decision["decisionId"], "decidedAt": decision.get("decidedAt"),
                           **decision["publications"][pub_id]}
                result = self.deliver(self.client(publication), publication, disc, receipt, self.config)
                state.update(delivered=True, deliveredAt=_iso(self.now), referenceId=result["referenceId"],
                             referenceLineageId=result.get("referenceLineageId"),
                             provenanceMessageId=result.get("provenanceMessageId"), lastError=None)
                self.record_delivery(publication, disc, route, result)
                self.counts["delivered"] += 1
                copied = self.copy_curation(publication, disc, result)   # before the procedure, so it only fills gaps
                if copied:
                    state["curationCopy"] = copied
                if not disc.get("editorSelectedReference"):
                    self.start_procedures(publication, disc, result)
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
        record = {
            "pk": pk(self.monitor_id), "sk": key, "publicationId": publication["publicationId"],
            "referenceId": result["referenceId"], "sourceId": disc["sourceId"], "revision": int(disc["revision"]),
            "itemId": route["itemId"], "decisionId": decision["decisionId"], "source": decision["source"],
            "output": decision["publications"][publication["publicationId"]]["output"],
            "bindingRevision": decision["bindingRevision"], "deliveredAt": _iso(self.now)}
        criteria = decision["publications"][publication["publicationId"]].get("criteriaFingerprint")
        if criteria:
            record["criteriaFingerprint"] = criteria
        if self.config["decisions"] == "cyclotron":
            record.update(gsi1pk=feedback_partition(self.monitor_id),
                          gsi1sk=f"{_iso(self.now)}#{publication['publicationId']}#{result['referenceId']}")
        self.store.put_any(self.monitor_id, record)

    def gate(self, publication: dict, trigger: dict) -> Gate:
        """What the site's Automation record for this trigger decides. Any failure to read it starts as before."""
        try:
            pid = publication["publicationId"]
            if pid not in self._automation_rows:   # one read per publication per sweep, and only when a start is due
                try:
                    self._automation_rows[pid] = self.client(publication).list_records("Automation")
                except Exception:
                    self._automation_rows[pid] = None
            automation = matching_automation(self._automation_rows[pid], monitor_id=self.monitor_id, publication_id=pid,
                                             procedure_key=trigger["procedureKey"])
            if automation is None:
                return START_AS_BEFORE
            rows = self.store.query_prefix(self.monitor_id, trigger_prefix(pid, trigger["procedureKey"])) \
                + self.store.query_prefix(self.monitor_id, manual_prefix(automation["id"]))
            return decide(automation, rows, now=self.now)
        except Exception:
            return START_AS_BEFORE

    def start_procedures(self, publication: dict, disc: dict, result: dict):
        """Fire-and-forget: each trigger starts at most once per source item, and never for a Reference that
        already existed (its decision may already have coverage). A failure here never fails the delivery."""
        for trigger in publication.get("procedureTriggers") or []:
            key = f"TRIGGER#{publication['publicationId']}#{trigger['procedureKey']}#{disc['sourceId']}"
            record = {"pk": pk(self.monitor_id), "sk": key, "publicationId": publication["publicationId"],
                      "procedureKey": trigger["procedureKey"], "sourceId": disc["sourceId"],
                      "referenceId": result["referenceId"], "routerRunId": self.run_id, "createdAt": _iso(self.now)}
            try:
                if result.get("referenceReused"):
                    self.store.put_new(self.monitor_id, {**record, "status": "notTriggered",
                                                         "reason": "the Reference already existed"})
                    self.counts["procedureNotTriggered"] += 1
                    continue
                gate = self.gate(publication, trigger)
                request = {"publicationId": publication["publicationId"], "appsyncEndpoint": publication["appsyncEndpoint"],
                           "openaiKeyParameter": publication["openaiKeyParameter"], "procedureKey": trigger["procedureKey"],
                           "input": procedure_trigger_input(trigger, publication, disc, result["referenceId"]),
                           "actorLabel": f"Papyrus monitor {self.monitor_id}",
                           "trigger": {"kind": "monitor", "monitorId": self.monitor_id, "sourceId": disc["sourceId"],
                                       "referenceId": result["referenceId"], "pk": record["pk"], "sk": key,
                                       "title": f"{trigger['procedureKey']}: {disc.get('title') or disc['sourceId']}"[:200],
                                       "summary": f"Started by monitor {self.monitor_id} for {disc['canonicalUrl']}"[:500]}}
                if gate.action != "start":
                    # Recorded, not started. A skipped item stays skipped. A deferred item (at its concurrency limit)
                    # keeps its resolved request on the row, and `retry_deferred` starts it on a later run.
                    reason = gate.reason if gate.action == "skip" else f"deferred: {gate.reason}"
                    if self.store.put_new(self.monitor_id, {**record, "status": gate.status, "reason": reason,
                                                            "automationId": gate.automation_id, "request": request}):
                        self.counts["procedureSkipped" if gate.action == "skip" else "procedureDeferred"] += 1
                    continue
                if gate.automation_id:   # an automation record governs this start: its limit goes with the request
                    request["timeoutSeconds"] = gate.timeout_seconds
                    request["trigger"]["automationId"] = gate.automation_id
                    record["automationId"] = gate.automation_id
                if not self.store.put_new(self.monitor_id, {**record, "status": "starting", "request": request}):
                    continue
                if self.start_procedure is None:
                    raise RuntimeError("no procedure runner is configured for this router")
                self.start_procedure(request)
                self.store.update_fields(self.monitor_id, key, {"status": "started", "startedAt": _iso(self.now)})
                self.counts["proceduresStarted"] += 1
            except Exception as error:
                self.counts["procedureStartFailed"] += 1
                try:
                    self.store.update_fields(self.monitor_id, key, {"status": "startFailed", "error": short(error)})
                except Exception:
                    pass

    def retry_deferred(self):
        """Starts the items an earlier run deferred at an automation's concurrency limit, oldest first, while there is
        room. The row keeps the request the item was deferred with; a failure here never fails the sweep."""
        for publication in self.publications.values():
            for trigger in publication.get("procedureTriggers") or []:
                try:
                    rows = self.store.query_prefix(self.monitor_id, trigger_prefix(publication["publicationId"], trigger["procedureKey"]))
                    waiting = sorted((row for row in rows if row.get("status") == "deferred" and isinstance(row.get("request"), dict)),
                                     key=lambda row: str(row.get("createdAt") or ""))
                    for row in waiting:
                        if self.time_left() < MIN_REMAINING_SECONDS:
                            return
                        gate = self.gate(publication, trigger)
                        if gate.action == "defer":
                            break   # still full: the rest wait too
                        key = row["sk"]
                        if gate.action == "skip":   # the automation was disabled while the item waited
                            self.store.put_any(self.monitor_id, {**row, "status": "skipped", "reason": gate.reason})
                            self.counts["procedureSkipped"] += 1
                            continue
                        request = dict(row["request"])
                        if gate.automation_id:
                            request["timeoutSeconds"] = gate.timeout_seconds
                            request["trigger"] = {**request.get("trigger", {}), "automationId": gate.automation_id}
                        row = {k: v for k, v in row.items() if k != "reason"}
                        try:
                            self.store.put_any(self.monitor_id, {**row, "status": "starting", "request": request, "retriedAt": _iso(self.now)})
                            if self.start_procedure is None:
                                raise RuntimeError("no procedure runner is configured for this router")
                            self.start_procedure(request)
                            self.store.put_any(self.monitor_id, {**row, "status": "started", "request": request,
                                                                 "retriedAt": _iso(self.now), "startedAt": _iso(self.now)})
                            self.counts["procedureRetried"] += 1
                        except Exception as error:
                            self.counts["procedureStartFailed"] += 1
                            try:
                                self.store.put_any(self.monitor_id, {**row, "status": "startFailed", "error": short(error)})
                            except Exception:
                                pass
                except Exception:
                    continue

    def live(self, disc: dict):
        """Returns AWAITING when the story's job is still running (its job stays recorded for the collector)."""
        route = self.get_route(disc)
        original_active_publications = self.active_publications
        try:
            validate_email_discovery_scope(disc, self.config)
            if disc.get("sourceType") == "email":
                self.active_publications = self.authorized_email_publications(disc)
                allowed = {p["publicationId"] for p in self.active_publications}
                if not allowed:
                    self.finish(disc, route, "refused", "email destination no longer permits this publication")
                    return
                route["publications"] = {key: value for key, value in route.get("publications", {}).items()
                                          if key in allowed}
                if route.get("decision"):
                    route["decision"]["publications"] = {
                        key: value for key, value in route["decision"].get("publications", {}).items()
                        if key in allowed}
            if not route.get("decision"):
                if self.config["decisions"] == "direct":
                    self.check_rule(disc)
                    self.enrichment_for(disc, route)
                    self.decide_direct(disc, route)
                else:
                    self.decide(disc, route)
            if not self.deliver_positive(disc, route):
                set_routing(self.store, self.monitor_id, disc, "decided", PARTITION_DECIDED)
                return
            route["completedAt"] = _iso(self.now)
            self.save(route)
            set_routing(self.store, self.monitor_id, disc, "routed", None)
            self.counts["routed"] += 1
        except JobRunning:
            return AWAITING
        except (NotPosting, EnrichmentPending):
            return None
        except AllBindingsNotReady:
            self.finish(disc, route, "parked", "every binding is waiting for a classifier")
        except ItemExcluded as error:
            self.finish(disc, route, "routed", str(error))
        except ItemRefused as error:
            self.finish(disc, route, "refused", str(error))
        except ItemUncertain as error:
            self.finish(disc, route, "uncertain", str(error))
        except ItemRetryLater as error:
            self.back_off(route, str(error))
        except ItemInvalid as error:
            self.finish(disc, route, "error", str(error))
        finally:
            self.active_publications = original_active_publications

    def back_off(self, route: dict, reason: str):
        """The lab refused the story for a non-permanent reason: keep it where it is, record the refusal, and ask
        again after an exponential backoff (REFUSAL_BACKOFF_FIRST * 2**n, capped at REFUSAL_BACKOFF_MAX). Never final."""
        refusals = int(route.get("refusals", 0))
        route["refusals"] = refusals + 1
        route["nextAttemptAt"] = int(self.now + min(REFUSAL_BACKOFF_FIRST * 2 ** min(refusals, 32), REFUSAL_BACKOFF_MAX))
        route["lastRefusal"] = {"message": reason[:300], "at": _iso(self.now), "refusals": refusals + 1}
        self.save(route)
        self.counts["backedOff"] += 1

    def finish(self, disc: dict, route: dict, routing: str, reason: str):
        route["final"] = {"routing": routing, "reason": reason[:300], "at": _iso(self.now)}
        partition = None
        if disc.get("editorSelectedReference") and routing == "parked":
            # Criteria can become ready later. Keep this exact job in its own lane;
            # ordinary backfill must never be needed to recover a selected Reference.
            publication_id = disc["editorSelectedReference"]["publicationId"]
            retry_at = max(int(self.now + 300), int((self.park(publication_id) or {}).get("nextProbeAt", 0)))
            route["nextAttemptAt"] = retry_at
            disc = {**disc, "gsi1sk": f"{_iso(retry_at)}#{disc['sourceId']}#{int(disc['revision']):06d}"}
            partition = "email-references"
        self.save(route)
        set_routing(self.store, self.monitor_id, disc, routing, partition)
        self.counts[routing] += 1

    # sweep ----------------------------------------------------------------------------------------

    def sweep(self) -> dict:
        """Post every candidate's job without waiting, then collect what finishes inside the collect window."""
        status, stopped = "complete", None
        errors: list = []
        if self.lab_paused():
            return self.paused_result()
        if self.config["mode"] == "live":
            self.retry_deferred()
        candidates = self.candidates()
        if self.config["mode"] == "live" and self.config["decisions"] == "cyclotron" and not self.holding:
            try:
                self.backfill()
            except StopSweep as stop:
                return {"status": "stopped", "stoppedBy": stop.code, "errors": self.with_lab_errors([]),
                        "waitingForClassifier": self.waiting_for_classifier()}
            self.nowait = True
        awaiting: list[dict] = []
        for disc in candidates:
            if self.time_left() < MIN_REMAINING_SECONDS:
                status, stopped = "stopped", "time_budget"
                break
            self.counts["examined"] += 1
            try:
                if (self.dry_run if self.config["mode"] == "dry-run" else self.live)(disc) == AWAITING:
                    awaiting.append(disc)
            except StopSweep as stop:
                status, stopped = "stopped", stop.code
                break
            except Exception as error:   # one bad item must not hide the rest
                errors.append({"sourceId": disc.get("sourceId"), "message": short(error)})
                self.counts["error"] += 1
        if awaiting and stopped in (None, "time_budget", "run_busy"):   # a busy lab stops new posts, not the collecting
            try:
                awaiting = self.collect_jobs(awaiting, errors)
            except StopSweep as stop:
                status, stopped = "stopped", stop.code
        self.counts["awaiting"] = len(awaiting)
        if errors and status == "complete":
            status = "partial"
        if awaiting and stopped is None:
            status, stopped = AWAITING, AWAITING   # jobs are still running at the lab; the collector delivers them
        if self.holding and stopped is None:
            stopped = "decisions_held"   # visible in the receipt: new decisions were not posted
        return {"status": status, "stoppedBy": stopped, "errors": self.with_lab_errors(errors),
                "waitingForClassifier": self.waiting_for_classifier() if self.config["decisions"] == "cyclotron" else []}

    def with_lab_errors(self, errors: list) -> list:
        """The receipt's errors: item errors first, then each non-2xx the lab answered (status + short excerpt)."""
        lab = list(getattr(self.cyclotron, "refusals", None) or [])
        return (errors + lab)[:10]

    def collect_jobs(self, awaiting: list[dict], errors: list) -> list[dict]:
        """Polls the outstanding jobs round-robin with backoff for at most cyclotron.pollSeconds (and never into the
        last MIN_REMAINING_SECONDS of the invocation), delivering each story as its job completes. Returns the stories
        whose jobs are still running. Nothing is posted here that was not already recorded."""
        client = self.cyclotron
        window = self.config["cyclotron"]["pollSeconds"]
        deadline, waited, delay = client.clock() + window, 0.0, 2.0
        while awaiting:
            if (client.clock() + delay > deadline or waited + delay > window
                    or self.time_left() - delay < MIN_REMAINING_SECONDS):
                break
            client.sleep(delay)
            waited += delay
            delay = min(delay * 1.5, 8.0)
            still = []
            for disc in awaiting:
                try:
                    if self.live(disc) == AWAITING:
                        still.append(disc)
                except StopSweep:
                    raise
                except Exception as error:
                    errors.append({"sourceId": disc.get("sourceId"), "message": short(error)})
                    self.counts["error"] += 1
            awaiting = still
        return awaiting

    def collect(self) -> dict:
        """The collector task: poll the stored jobs, deliver the finished ones, post nothing."""
        if self.config["mode"] != "live" or self.config["decisions"] != "cyclotron":
            return {"status": "complete", "stoppedBy": None, "errors": [], "waitingForClassifier": []}
        if self.lab_paused():
            return self.paused_result()
        self.nowait, self.post_allowed = True, False
        errors: list = []
        pending = []
        for disc in self.store.query_partition(gsi_partition(self.monitor_id, PARTITION_COLLECTED)):
            route = self.store.get_any(self.monitor_id, route_key(disc)) or {}
            if (route.get("combinedJob") or {}).get("jobId") or any(
                    job.get("jobId") and not job.get("checked") for job in (route.get("jobs") or {}).values()):
                pending.append((oldest_posted_at(route), disc))
        pending = [disc for _, disc in sorted(pending, key=lambda pair: pair[0])]   # oldest job first; the first 429 ends the pass
        self.counts["examined"] = len(pending)
        status, stopped = "complete", None
        try:
            # one pass first, so jobs that finished while nobody was looking are delivered without waiting
            still = []
            for index, disc in enumerate(pending):
                if self.time_left() < MIN_REMAINING_SECONDS:
                    status, stopped = "stopped", "time_budget"
                    still += pending[index:]
                    break
                try:
                    if self.live(disc) == AWAITING:
                        still.append(disc)
                except StopSweep:
                    raise
                except Exception as error:
                    errors.append({"sourceId": disc.get("sourceId"), "message": short(error)})
                    self.counts["error"] += 1
            if still and stopped is None:
                still = self.collect_jobs(still, errors)
        except StopSweep as stop:
            return {"status": "stopped", "stoppedBy": stop.code, "errors": self.with_lab_errors(errors), "waitingForClassifier": []}
        self.counts["awaiting"] = len(still)
        if errors and status == "complete":
            status = "partial"
        if still and stopped is None:
            status, stopped = AWAITING, AWAITING
        return {"status": status, "stoppedBy": stopped, "errors": self.with_lab_errors(errors),
                "waitingForClassifier": self.waiting_for_classifier()}

    # feedback ---------------------------------------------------------------------------------------

    def feedback(self) -> dict:
        result = {"status": "complete", "sent": 0, "pending": 0, "skipped": 0, "failed": 0, "stoppedBy": None}
        if self.config["mode"] != "live" or not self.config["feedback"]:
            return {**result, "status": "off"}
        if self.lab_paused():
            return {**result, "status": "stopped", "stoppedBy": "lab_backoff"}
        for row in self.store.query_partition(feedback_partition(self.monitor_id)):
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
        # Feedback goes out under the publication's CURRENT binding revision, not the one stored when the item was
        # decided: the lab refuses a stale revision (409 "publication binding changed") after a cutover. The
        # requestId does not include the revision, so retries stay idempotent.
        if self.publications.get(publication["publicationId"]) is not publication:
            self.rotate(row, "publication not in the current config")
            return "skipped"
        reference = self.client(publication).get_record("Reference", row["referenceId"])
        status = (reference or {}).get("curationStatus")
        if status not in ("accepted", "rejected"):
            self.rotate(row, f"curation {status or 'missing'}")
            return "pending"
        actor = str(reference.get("curationStatusUpdatedBy") or "")
        if not human_actor(actor):
            self.rotate(row, "curation actor is missing or not a human user")
            return "skipped"
        updated_at = str(reference.get("curationStatusUpdatedAt") or reference.get("updatedAt") or "")
        label = publication["positiveLabel"] if status == "accepted" else publication["negativeLabel"]
        body = {"contractVersion": CONTRACT_VERSION, "operation": "feedback",
                "requestId": sha256("\n".join([row["referenceId"], status, updated_at]).encode()).hexdigest(),
                "payload": {"bindingRevision": self.config["cyclotron"]["bindingRevision"], "itemId": row["itemId"],
                            "itemRevision": (row.get("source") or {}).get("revision"), "output": row["output"],
                            "label": label, "editor": {"site": publication["site"],
                                       "subject": editor_subject(publication["publicationId"], actor)}}}
        if body["payload"]["itemRevision"] is None:
            self.rotate(row, "decision receipt has no item revision")
            return "skipped"
        validate_request(body)
        current = str(self.config["cyclotron"]["bindingRevision"])
        voted = row.get("criteriaFingerprint")
        latest = (self.store.get_any(self.monitor_id, f"CRIT#{publication['publicationId']}") or {}).get("criteriaFingerprint")
        if voted and latest:   # the fingerprint decides; criteriaSince is only the fallback when either one is unknown
            changed, basis = voted != latest, {"votedFingerprint": voted, "currentFingerprint": latest}
        else:
            since = publication.get("criteriaSince", current)   # default: only votes under the current revision count
            changed, basis = not criteria_unchanged(row.get("bindingRevision"), since), {"criteriaSince": since}
        if changed:
            self.store.put_any(self.monitor_id, {
                "pk": pk(self.monitor_id), "sk": f"FB#{body['requestId']}", "requestId": body["requestId"],
                "publicationId": publication["publicationId"], "referenceId": row["referenceId"],
                "outcome": "stale", "code": "criteria changed since this vote", "votedUnder": str(row.get("bindingRevision")),
                **basis, "sentAt": _iso(self.now), "runId": self.run_id})
            self.store.put_any(self.monitor_id, {k: v for k, v in row.items() if k not in ("gsi1pk", "gsi1sk")} | {"feedback": "stale"})
            return "skipped"
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
        except StopSweep as stop:
            if stop.code != "binding_changed":
                raise
            # the body was logged by classify; the row stays queued and the next run asks again under the then-current revision
            self.rotate(row, f"binding_changed ({stop.detail}) under revision {body['payload']['bindingRevision']}; retry next run")
            return "failed"
        self.store.put_any(self.monitor_id, {**receipt, "outcome": "sent",
                                             "response": {k: response[k] for k in ("status", "feedbackId", "accepted") if k in response
                                                          and isinstance(response[k], (str, bool, int))}})
        self.store.put_any(self.monitor_id, {k: v for k, v in row.items() if k not in ("gsi1pk", "gsi1sk")}
                           | {"feedback": "sent", "feedbackRequestId": body["requestId"], "feedbackAt": _iso(self.now)})
        return "sent"


def oldest_posted_at(route: dict) -> int:
    posted = [int(job.get("postedAt", 0)) for job in [route.get("combinedJob") or {}, *(route.get("jobs") or {}).values()]
              if job.get("jobId") and not job.get("checked")]
    return min(posted) if posted else 0


def reopen_stale_finals(store, monitor_id: str) -> int:
    """One-off recovery for stories an old pending-age limit finalized as errors while the lab still held their jobs.
    Their stored jobs are kept; `final` is removed and the discovery returns to the collected partition, where the
    collector polls the jobs again. Returns how many routes were reopened."""
    reopened = 0
    for route in store.query_prefix(monitor_id, "ROUTE#"):
        if (route.get("final") or {}).get("reason") != STALE_FINAL_REASON:
            continue
        has_job = (route.get("combinedJob") or {}).get("jobId") or any(
            job.get("jobId") for job in (route.get("jobs") or {}).values())
        disc = store.get_any(monitor_id, f"DISC#{route['sourceId']}#{int(route['revision']):06d}")
        if not has_job or not disc or not store.reopen_final(monitor_id, route["sk"], STALE_FINAL_REASON):
            continue
        disc = {k: v for k, v in disc.items() if k != "gsi1sk"} | {
            "gsi1sk": f"{disc['observedAt']}#{disc['sourceId']}#{int(disc['revision']):06d}"}
        set_routing(store, monitor_id, disc, PARTITION_COLLECTED, PARTITION_COLLECTED)
        reopened += 1
    return reopened


def run_router(store, monitor_id: str = "hn", *, now: float | None = None, owner: str | None = None,
               run_id: str | None = None, task: str | None = None, cyclotron: CyclotronClient | None = None,
               appsync: Callable[[str], Any] = make_appsync_client, deliver=deliver_reference,
               context_receipt=editorial_context_receipt, time_left: Callable[[], float] = lambda: 1e9,
               cyclotron_factory: Callable[[dict], CyclotronClient] | None = None,
               start_procedure: Callable[[dict], None] | None = None, cognito=None, source_ids=None,
               rung_job_ids=(), enricher: Enricher | None = None) -> dict:
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
        if task == "reopen-stale-finals":
            return {"monitorId": monitor_id, "runId": run_id, "status": "complete", "reopened": reopen_stale_finals(store, monitor_id)}
        if cyclotron is None and config["mode"] == "live" and config["decisions"] == "cyclotron":
            cyclotron = (cyclotron_factory or (lambda c: CyclotronClient(c, sign=sigv4_signer(c, assume_invoker(c)))))(config)
        router = Router(store, config, monitor_id=monitor_id, now=now, run_id=run_id, cyclotron=cyclotron,
                        appsync=appsync, deliver=deliver, context_receipt=context_receipt, time_left=time_left,
                        start_procedure=start_procedure, cognito=cognito, rung_job_ids=rung_job_ids, enricher=enricher)
        outcome = (router.selected_references(source_ids) if task == "email-references" else
                   {"status": "skipped"} if task == "feedback" else router.collect() if task == "collect" else router.sweep())
        feedback = {"status": "skipped"} if task in ("route", "collect", "email-references") else router.feedback()
        paused_until = router.settle_lab_backoff()
        result = {"monitorId": monitor_id, "runId": run_id, "mode": config["mode"], "startedAt": _iso(now),
                  "status": outcome["status"], "stoppedBy": outcome.get("stoppedBy"), "counts": router.counts,
                  "feedback": feedback, "errors": outcome.get("errors", []),
                  "waitingForClassifier": outcome.get("waitingForClassifier", [])}
        store.put_receipt(monitor_id, {
            "pk": pk(monitor_id), "sk": f"ROUTERUN#{result['startedAt']}#{run_id}", "runId": run_id,
            "startedAt": result["startedAt"], "mode": config["mode"], "status": result["status"],
            "stoppedBy": result["stoppedBy"], "counts": router.counts, "feedback": feedback,
            "errors": result["errors"], "waitingForClassifier": result["waitingForClassifier"],
            **({"labBackoffUntil": _iso(paused_until)} if paused_until else {}), "ttl": int(now + RECEIPT_TTL_SECONDS)})
        return result
    finally:
        store.release_router_lock(monitor_id, owner)


DOORBELL_MONITORS = ("hn", "huggingface", "ttab")   # monitors that may carry a CONFIG#router item
DECISION_SOURCE, DECISION_DETAIL_TYPE = "cyclotron.lab", "Decision Ready"
DECISION_FIELDS = ("accountId", "runId", "jobId", "requestId", "itemId")


def is_decision_event(event) -> bool:
    return isinstance(event, dict) and ("detail-type" in event or "source" in event) and "monitorId" not in event


def parse_decision_event(event: dict) -> dict | None:
    """The validated detail of a Decision Ready event, or None. Never raises: a bad event is dropped, not retried."""
    detail = event.get("detail")
    if event.get("source") != DECISION_SOURCE or event.get("detail-type") != DECISION_DETAIL_TYPE or not isinstance(detail, dict):
        return None
    if detail.get("contractVersion") != CONTRACT_VERSION or detail.get("status") not in ("complete", "failed"):
        return None
    if any(not isinstance(detail.get(key), str) or not detail[key].strip() for key in DECISION_FIELDS):
        return None
    if not isinstance(detail.get("publications"), list):
        return None
    return detail


def handle_decision_ready(store, event, collect: Callable[..., dict]) -> dict:
    """A doorbell: the event carries no decision. Run the collect task for every monitor whose router config is
    bound to the event's Account and run, then let `collect` fetch the answer with the signed GET as usual."""
    detail = parse_decision_event(event) if isinstance(event, dict) else None
    if detail is None:
        print(json.dumps({"doorbell": "malformed"}))
        return {"status": "malformed", "collected": {}}
    collected, ignored = {}, 0
    for monitor_id in DOORBELL_MONITORS:
        raw = store.get_router_config(monitor_id)
        cyclotron = (raw or {}).get("cyclotron") if isinstance((raw or {}).get("cyclotron"), dict) else None
        if cyclotron is None:
            continue
        if cyclotron.get("accountId") != detail["accountId"] or cyclotron.get("runId") != detail["runId"]:
            ignored += 1
            continue
        try:
            collected[monitor_id] = collect(monitor_id, detail["jobId"]).get("status")
        except Exception as error:   # one monitor's failure must not stop the others or cause an EventBridge retry storm
            collected[monitor_id] = "error"
            print(json.dumps({"doorbell": "collect_failed", "monitorId": monitor_id, "error": short(error)}))
    status = "collected" if collected else "ignored"
    print(json.dumps({"doorbell": status, "jobId": detail["jobId"], "requestId": detail["requestId"],
                      "collected": collected, "ignoredMonitors": ignored}))
    return {"status": status, "collected": collected, "ignoredMonitors": ignored}


def handler(event, context):
    """EventBridge Scheduler entry point. `{"task": "route"|"collect"|"feedback"}` limits the pass (operator debugging)."""
    import boto3  # provided by the Lambda runtime

    event = event if isinstance(event, dict) else {}
    store = RouterStore(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))
    remaining = (lambda: context.get_remaining_time_in_millis() / 1000) if hasattr(context, "get_remaining_time_in_millis") else (lambda: 1e9)
    cognito, starter = boto3.client("cognito-idp"), lambda_procedure_starter(os.environ.get("PROCEDURE_RUNNER_FUNCTION"))
    from .monitoring_enrichment import lambda_enricher
    enricher = lambda_enricher()   # None unless the stack set ENRICHMENT_BUCKET
    if is_decision_event(event):
        return handle_decision_ready(store, event, lambda monitor_id, job_id=None: run_router(
            store, monitor_id, task="collect", time_left=remaining, cognito=cognito, start_procedure=starter,
            rung_job_ids=[job_id], enricher=enricher))
    result = run_router(store, str(event.get("monitorId") or "hn"), task=event.get("task"), time_left=remaining, source_ids=event.get("sourceIds"),
                        cognito=cognito, start_procedure=starter, enricher=enricher)
    print(json.dumps({k: v for k, v in result.items() if k != "errors"} | {"errors": result.get("errors", [])[:3]}))
    return {k: result.get(k) for k in ("runId", "status", "reopened", "mode", "stoppedBy", "counts", "feedback", "waitingForClassifier")}
