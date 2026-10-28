"""Cloud HN router: dry-run, live decisions, refusals, delivery isolation, feedback, packaging, template."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest
import yaml

from papyrus_content import monitoring_router as mr
from papyrus_content.monitoring_cloud import DynamoStore, run_collection
from papyrus_content.monitoring_router import (
    CyclotronClient, RouterStore, build_decide_request, request_id, run_router, validate_request,
    validate_router_config)

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "infra" / "monitoring" / "papyrus-monitoring.yaml"
FEED = b'''<rss><channel>
<item><title>Alpha source</title><link>https://example.org/alpha</link><comments>https://news.ycombinator.com/item?id=101</comments></item>
<item><title>Beta source</title><link>https://example.org/beta</link><comments>https://news.ycombinator.com/item?id=102</comments></item>
<item><title>Gamma source</title><link>https://example.org/gamma</link><comments>https://news.ycombinator.com/item?id=103</comments></item>
</channel></rss>'''
COLLECTOR_CONFIG = {"pk": "MONITOR#hn", "sk": "CONFIG", "sourceUrl": "https://news.ycombinator.com/rss",
                    "intervalSeconds": 900, "enabled": True}
ENDPOINT = "https://abc123.appsync-api.us-east-1.amazonaws.com/graphql"
ONE_FEED = FEED.split(b"<item>")[0] + b"<item>" + FEED.split(b"<item>")[1] + b"</channel></rss>"   # the first story only
PUBS = ("anth-us", "p-apyr-us", "threat-intelligence")


def router_config(mode="live", **overrides):
    config = {"pk": "MONITOR#hn", "sk": "CONFIG#router", "mode": mode, "feedback": False,
              "publications": [{"publicationId": p, "site": f"{p}.example", "appsyncEndpoint": ENDPOINT.replace("abc123", f"api{n}")}
                               for n, p in enumerate(PUBS)],
              "cyclotron": {"endpoint": "https://o01d28uizl.execute-api.us-east-1.amazonaws.com", "accountId": "acct-1",
                            "runId": "run-1", "bindingRevision": "1",
                            "roleArn": "arn:aws:iam::682849160744:role/cyclotron-machine-invoker", "pollSeconds": 10}}
    config["publications"][1]["corpusId"] = "knowledge-corpus-ai-ml-research"
    config.update(overrides)
    return config


class Conditional(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    def __init__(self):
        self.items = {}

    @staticmethod
    def _types(value):
        if isinstance(value, dict):
            return {k: FakeTable._types(v) for k, v in value.items()}
        if isinstance(value, list):
            return [FakeTable._types(v) for v in value]
        return "float" if isinstance(value, float) else 0

    @staticmethod
    def _dec(value):
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        if isinstance(value, dict):
            return {k: FakeTable._dec(v) for k, v in value.items()}
        if isinstance(value, list):
            return [FakeTable._dec(v) for v in value]
        return value

    def get_item(self, Key, ConsistentRead=False):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": deepcopy(item)} if item else {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeValues=None):
        if "float" in json.dumps(self._types(Item)):
            raise TypeError("Float types are not supported. Use Decimal types instead.")
        key, existing = (Item["pk"], Item["sk"]), self.items.get((Item["pk"], Item["sk"]))
        if ConditionExpression == "attribute_not_exists(pk)" and existing:
            raise Conditional()
        if ConditionExpression == "attribute_not_exists(pk) OR expiresAt < :now" and existing:
            if not existing["expiresAt"] < ExpressionAttributeValues[":now"]:
                raise Conditional()
        self.items[key] = self._dec(deepcopy(Item))

    def update_item(self, Key, UpdateExpression, ConditionExpression, ExpressionAttributeNames, ExpressionAttributeValues):
        item = self.items.get((Key["pk"], Key["sk"]))
        assert UpdateExpression == "REMOVE #f" and ConditionExpression == "#f.#r = :r"
        if not item or (item.get("final") or {}).get("reason") != ExpressionAttributeValues[":r"]:
            raise Conditional()
        del item["final"]

    def delete_item(self, Key, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        existing = self.items.get((Key["pk"], Key["sk"]))
        if ConditionExpression is None:
            self.items.pop((Key["pk"], Key["sk"]), None)
            return
        if not existing or existing["owner"] != ExpressionAttributeValues[":owner"]:
            raise Conditional()
        del self.items[(Key["pk"], Key["sk"])]

    def query(self, KeyConditionExpression, ExpressionAttributeValues, IndexName=None, ScanIndexForward=True, Limit=None, **_):
        if IndexName is None:   # the base table: one partition, sort keys that start with a prefix
            assert KeyConditionExpression == "pk = :pk AND begins_with(sk, :prefix)"
            rows = [deepcopy(v) for k, v in sorted(self.items.items())
                    if k[0] == ExpressionAttributeValues[":pk"] and k[1].startswith(ExpressionAttributeValues[":prefix"])]
            page = getattr(self, "page_size", None)    # a table that answers a few rows at a time, as DynamoDB does at 1 MB
            if page:
                start = int(_.get("ExclusiveStartKey") or 0)
                return {"Items": rows[start:start + page], **({"LastEvaluatedKey": start + page} if start + page < len(rows) else {})}
            return {"Items": rows}
        assert IndexName == "routing" and KeyConditionExpression == "gsi1pk = :p"
        rows = sorted((v for v in self.items.values() if v.get("gsi1pk") == ExpressionAttributeValues[":p"]),
                      key=lambda v: v["gsi1sk"], reverse=not ScanIndexForward)
        page = getattr(self, "page_size", None)
        if page:
            start = int(_.get("ExclusiveStartKey") or 0)
            rows, more = rows[start:start + page], start + page < len(rows)
            return {"Items": [deepcopy(r) for r in rows], **({"LastEvaluatedKey": start + page} if more else {})}
        return {"Items": [deepcopy(r) for r in rows[:Limit]]}

    def by_prefix(self, prefix):
        return [v for k, v in sorted(self.items.items()) if k[1].startswith(prefix)]


class FakeCyclotron:
    """Scriptable machine API: records every call; decisions share one id per item."""

    def __init__(self, labels=None):
        self.calls, self.jobs = [], {}
        self.labels = labels or {}            # (itemId, pub) -> label; default include for all
        self.confidence = {}                  # (itemId, pub) -> confidence the machine API reports
        self.post_override, self.poll_override = {}, {}
        self.feedback_override = None
        self.pending_polls = 0
        self.polls_needed = 0                 # each job answers "running" this many times before it completes
        self.job_gets = {}
        self.combined_calls, self.combined_jobs = [], {}
        self.combined_enabled = False         # False: the deployment predates POST /machine/decisions (404)
        self.combined_post_override = None    # (status, body) for POST /machine/decisions
        self.combined_busy_after = None       # accept this many POSTs, then answer 409 run_busy
        self.combined_poll_override = None    # (status, body) for GET /machine/decisions/{job}
        self.combined_entry_override = {}     # pub -> entry replacing that publication's receipt
        self.combined_post_queue = []         # one-shot (status, body) answers to POST /machine/decisions, first in first out
        self.combined_poll_queue = []         # one-shot (status, body) answers to GET /machine/decisions/{job}, first in first out

    def combined(self, method, path, data):
        if not self.combined_enabled:
            return 404, {"detail": "Not Found"}
        if method == "POST":
            if self.combined_post_queue:
                return self.combined_post_queue.pop(0)
            if self.combined_post_override:
                return self.combined_post_override
            if self.combined_busy_after is not None and len(self.combined_jobs) >= self.combined_busy_after:
                return 409, {"code": "run_busy"}
            job = f"cjob-{len(self.combined_jobs)}"
            self.combined_jobs[job] = (sorted(data["payload"]["bindings"]), data["payload"]["item"]["id"])
            return 202, {"contractVersion": mr.CONTRACT_VERSION, "accountId": "acct-1", "runId": "run-1", "jobId": job,
                         "status": "accepted", "bindings": data["payload"]["bindings"]}
        if self.combined_poll_queue:
            return self.combined_poll_queue.pop(0)
        if self.combined_poll_override:
            return self.combined_poll_override
        if self.pending_polls:
            self.pending_polls -= 1
            return 202, {"status": "running"}
        if self.still_running(path.rsplit("/", 1)[1]):
            return 202, {"status": "running"}
        pubs, item = self.combined_jobs[path.rsplit("/", 1)[1]]
        return 200, {"contractVersion": mr.CONTRACT_VERSION, "accountId": "acct-1", "runId": "run-1",
                     "jobId": path.rsplit("/", 1)[1], "decisionId": f"dec-{item}",
                     "publications": {pub: self.combined_entry_override.get(pub) or self.single_receipt(pub, item)
                                      for pub in pubs}}

    def still_running(self, job):
        seen = self.job_gets[job] = self.job_gets.get(job, 0) + 1
        return seen <= self.polls_needed

    def output_entry(self, pub):
        entry = {"id": f"{pub}-relevance"}
        extra = getattr(self, "output_extra", {}).get(pub)
        return entry | extra if extra else entry

    def single_receipt(self, pub, item):
        return {"contractVersion": mr.CONTRACT_VERSION, "publicationId": pub, "bindingRevision": "1",
                "decision": {"decisionId": f"dec-{item}", "itemId": item, "classifiers": {
                    f"{pub}-relevance": {"label": self.labels.get((item, pub), "include"),
                                         "fingerprint": f"fp-{pub}", "version": 3,
                                         **({"confidence": self.confidence[(item, pub)]} if (item, pub) in self.confidence else {})}}},
                "outputs": [self.output_entry(pub)], "source": {"id": item, "revision": 2, "fingerprint": "sfp"}}

    def http(self, method, url, headers, body, timeout):
        path = url.split("amazonaws.com", 1)[1]
        if path.startswith("/machine/decisions"):
            self.combined_calls.append((method, path, json.loads(body) if body else None))
            return self.combined(method, path, json.loads(body) if body else None)
        self.calls.append((method, path, json.loads(body) if body else None))
        pub = path.split("/")[3]
        if method == "POST":
            data = json.loads(body)
            if data["operation"] == "feedback":
                return self.feedback_override or (200, {"status": "recorded", "feedbackId": "fb-" + data["requestId"][:8]})
            if pub in self.post_override:
                return self.post_override[pub]
            job = f"job-{pub}-{len(self.jobs)}"
            self.jobs[job] = (pub, data["payload"]["item"]["id"])
            return 202, {"jobId": job}
        job = path.rsplit("/", 1)[1]
        if pub in self.poll_override:
            return self.poll_override[pub]
        if self.pending_polls:
            self.pending_polls -= 1
            return 202, {"status": "running"}
        if self.still_running(job):
            return 202, {"status": "running"}
        _, item = self.jobs[job]
        return 200, {"contractVersion": mr.CONTRACT_VERSION, "publicationId": pub, "bindingRevision": "1",
                     "decision": {"decisionId": f"dec-{item}", "itemId": item, "classifiers": {
                         f"{pub}-relevance": {"label": self.labels.get((item, pub), "include"),
                                              "fingerprint": f"fp-{pub}", "version": 3,
                                              **({"confidence": self.confidence[(item, pub)]} if (item, pub) in self.confidence else {})}}},
                     "outputs": [self.output_entry(pub)], "source": {"id": item, "revision": 2, "fingerprint": "sfp"}}

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]


class Delivery:
    """Stands in for ReferenceIntake: idempotent by (publication, source id)."""

    def __init__(self):
        self.calls, self.fail = [], set()
        self.references = {}

    def __call__(self, client, publication, disc, decision, config):
        pub = publication["publicationId"]
        self.calls.append((pub, disc["sourceId"], decision["decisionId"], decision["label"]))
        if pub in self.fail:
            raise RuntimeError("backend unavailable")
        ref = self.references.setdefault((pub, disc["sourceId"]), f"reference-{pub}-{disc['sourceId']}")
        return {"referenceId": ref, "referenceLineageId": ref.removesuffix("-v1"), "referenceVersion": 1,
                "provenanceMessageId": "message-1"}


def collected_table(feed):
    t = FakeTable()
    t.put_item(COLLECTOR_CONFIG)
    run_collection(DynamoStore(t), "hn", fetch=lambda url: feed, now=1000)
    return t


@pytest.fixture
def table():
    return collected_table(ONE_FEED)      # one story: the router has no per-run batch limit, so tests that watch one story use one


@pytest.fixture
def table3():
    return collected_table(FEED)          # three stories


def setup_router(table, **config):
    table.put_item(router_config(**config))
    return RouterStore(table), FakeCyclotron()


def go(table, store, cyclotron, now=2000, **kwargs):
    kwargs.setdefault("deliver", Delivery())
    kwargs.setdefault("appsync", lambda endpoint: object())
    kwargs.setdefault("context_receipt", lambda client, publication: {"contextHash": "h-" + publication["publicationId"], "reason": None})
    client = CyclotronClient(validate_router_config(table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"]),
                             sign=lambda m, u, b: {}, http=cyclotron.http, sleep=lambda s: None, clock=lambda: 0) if cyclotron else None
    return run_router(store, "hn", now=now, cyclotron=client, **kwargs)


def routing_of(table):
    return {k[1]: v["routing"] for k, v in sorted(table.items.items()) if k[1].startswith("DISC#")}


# --- config and request building -------------------------------------------------------------------

def test_config_validation_accepts_the_shape_and_rejects_unsafe_values():
    parsed = validate_router_config(router_config())
    assert "maxItemsPerRun" not in parsed and parsed["feedback"] is False and parsed["mode"] == "live"
    assert parsed["publications"][1]["corpusKey"] == "ai-ml-research"
    assert parsed["publications"][0]["output"] == "anth-us-relevance"
    for bad in ({"mode": "maybe"}, {"publications": []},
                {"cyclotron": {**router_config()["cyclotron"], "endpoint": "https://example.org"}},
                {"cyclotron": {**router_config()["cyclotron"], "roleArn": ""}},
                {"publications": [{**router_config()["publications"][0], "appsyncEndpoint": "https://evil.example/graphql"}]},
                {"publications": [router_config()["publications"][0]] * 2}):
        with pytest.raises(ValueError):
            validate_router_config({**router_config(), **bad})
    assert validate_router_config(router_config("dry-run", cyclotron={**router_config()["cyclotron"], "roleArn": ""}))["mode"] == "dry-run"


def test_request_ids_are_content_addressed_and_bound_to_every_input():
    payload = {"bindingRevision": "1", "item": {"id": "hn-1", "values": {"title": "T"}}}
    base = request_id("a", "r", "p", payload)
    assert base == request_id("a", "r", "p", payload) and len(base) == 64
    assert base == request_id("a", "r", "p", {"item": {"values": {"title": "T"}, "id": "hn-1"}, "bindingRevision": "1"})
    changed_value = {**payload, "item": {"id": "hn-1", "values": {"title": "U"}}}
    assert len({base, request_id("b", "r", "p", payload), request_id("a", "s", "p", payload),
                request_id("a", "r", "q", payload), request_id("a", "r", "p", payload, 1),
                request_id("a", "r", "p", {**payload, "bindingRevision": "2"}),
                request_id("a", "r", "p", changed_value)}) == 7


def test_decide_request_has_the_exact_contract_shape(table):
    config = validate_router_config(router_config())
    disc = table.items[("MONITOR#hn", "DISC#101#000001")]
    built = build_decide_request(config, config["publications"][0], disc)
    body = built["body"]
    assert built["path"] == "/machine/publications/anth-us/operations"
    assert body["contractVersion"] == "cyclotron-publication/v1" and body["operation"] == "decide"
    assert body["requestId"] == request_id("acct-1", "run-1", "anth-us", body["payload"])
    assert body["payload"] == {"bindingRevision": "1", "item": {"id": "hn-101", "values": {
        "title": "Alpha source", "url": "https://example.org/alpha", "source": "hacker-news",
        "sourceItemUrl": "https://news.ycombinator.com/item?id=101", "text": "Alpha source\nhttps://example.org/alpha"}}}


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(contractVersion="v0"), lambda b: b.update(operation="delete"),
    lambda b: b.update(requestId="short"), lambda b: b["payload"].update(extra=1),
    lambda b: b["payload"]["item"]["values"].update(text="mismatch"),
    lambda b: b["payload"]["item"]["values"].pop("url"),
    lambda b: b["payload"]["item"].update(id="other-1")])
def test_validation_rejects_off_contract_bodies(table, mutate):
    config = validate_router_config(router_config())
    body = deepcopy(build_decide_request(config, config["publications"][0], table.items[("MONITOR#hn", "DISC#101#000001")])["body"])
    mutate(body)
    with pytest.raises(ValueError):
        validate_request(body)


# --- dry run ------------------------------------------------------------------------------------------

def test_dry_run_builds_validates_and_records_receipts_without_any_cyclotron_call(table3):
    store, _ = setup_router(table3, mode="dry-run")
    contexts = {"anth-us": {"contextHash": None, "reason": "no stored policy"},
                "p-apyr-us": {"contextHash": None, "reason": "no stored policy"},
                "threat-intelligence": {"contextHash": "abc", "reason": None}}
    result = go(table3, store, None, context_receipt=lambda client, pub: contexts[pub["publicationId"]])
    assert result["status"] == "complete" and result["mode"] == "dry-run" and result["counts"]["dryRunValidated"] == 3
    assert set(routing_of(table3).values()) == {"dry-run-validated"}     # every collected story, not a batch of them
    route = table3.items[("MONITOR#hn", "ROUTE#101#000001")]
    assert set(route["dryRun"]["requests"]) == set(PUBS) and route["dryRun"]["count"] == 1
    assert route["dryRun"]["contexts"]["anth-us"] == {"contextHash": None, "reason": "no stored policy"}
    assert route["dryRun"]["contexts"]["threat-intelligence"]["contextHash"] == "abc"
    request = route["dryRun"]["requests"]["p-apyr-us"]
    assert request["path"] == "/machine/publications/p-apyr-us/operations" and request["body"]["operation"] == "decide"
    receipt = table3.by_prefix("ROUTERUN#")[0]
    assert receipt["mode"] == "dry-run" and receipt["counts"]["dryRunValidated"] == 3
    # the next dry-run advances through the backlog instead of revalidating the same items
    go(table3, store, None, now=3000)
    assert routing_of(table3)["DISC#103#000001"] == "dry-run-validated"
    assert table3.items[("MONITOR#hn", "ROUTE#101#000001")]["dryRun"]["count"] == 1


def test_dry_run_context_failure_is_recorded_not_fatal(table):
    store, _ = setup_router(table, mode="dry-run")

    def explode(client, publication):
        raise RuntimeError("never reached: the real receipt function catches")

    result = go(table, store, None, appsync=lambda e: (_ for _ in ()).throw(OSError("no route")),
                context_receipt=mr.editorial_context_receipt)
    route = table.items[("MONITOR#hn", "ROUTE#101#000001")]
    assert result["status"] == "complete"
    assert route["dryRun"]["contexts"]["anth-us"]["contextHash"] is None and "no route" in route["dryRun"]["contexts"]["anth-us"]["reason"]


def test_flipping_to_live_after_dry_run_processes_validated_items_with_identical_request_ids(table):
    store, cyclotron = setup_router(table, mode="dry-run")
    go(table, store, None)
    dry_ids = {p: r["requestId"] for p, r in table.items[("MONITOR#hn", "ROUTE#101#000001")]["dryRun"]["requests"].items()}
    table.put_item(router_config("live"))
    delivery = Delivery()
    go(table, store, cyclotron, now=3000, deliver=delivery)
    assert {c[2]["requestId"] for c in cyclotron.posts()} == set(dry_ids.values())
    assert routing_of(table)["DISC#101#000001"] == "routed"


# --- live ---------------------------------------------------------------------------------------------

def test_live_happy_path_one_shared_decision_and_per_publication_delivery(table):
    store, cyclotron = setup_router(table)
    cyclotron.labels = {("hn-101", "p-apyr-us"): "exclude"}
    delivery = Delivery()
    result = go(table, store, cyclotron, deliver=delivery)
    assert result["status"] == "complete" and result["counts"]["decided"] == 1 and result["counts"]["routed"] == 1
    assert [c[1] for c in cyclotron.posts()] == [f"/machine/publications/{p}/operations" for p in PUBS]
    route = table.items[("MONITOR#hn", "ROUTE#101#000001")]
    decision = route["decision"]
    assert decision["decisionId"] == "dec-hn-101" and decision["source"]["revision"] == 2
    assert decision["publications"]["p-apyr-us"] == {"output": "p-apyr-us-relevance", "label": "exclude", "fingerprint": "fp-p-apyr-us", "version": 3}
    assert sorted(p for p, *_ in delivery.calls) == ["anth-us", "threat-intelligence"]
    assert set(route["publications"]) == {"anth-us", "threat-intelligence"} and all(s["delivered"] for s in route["publications"].values())
    disc = table.items[("MONITOR#hn", "DISC#101#000001")]
    assert disc["routing"] == "routed" and "gsi1pk" not in disc and "gsi1sk" not in disc
    assert {k[1] for k in table.items if k[1].startswith("DELIV#")} == {
        "DELIV#anth-us#reference-anth-us-101", "DELIV#threat-intelligence#reference-threat-intelligence-101"}
    feedback_row = table.items[("MONITOR#hn", "DELIV#anth-us#reference-anth-us-101")]
    assert feedback_row["gsi1pk"] == "FEEDBACK#hn#pending" and feedback_row["output"] == "anth-us-relevance"
    # a rerun neither re-sends nor re-delivers anything for the routed item
    go(table, store, cyclotron, now=3000, deliver=delivery)
    assert len([c for c in delivery.calls if c[1] == "101"]) == 2
    assert len([c for c in cyclotron.posts() if c[2]["payload"]["item"]["id"] == "hn-101"]) == 3
    assert routing_of(table)["DISC#101#000001"] == "routed"


def test_decision_receipt_keeps_a_valid_confidence_for_the_monitoring_page(table):
    store, cyclotron = setup_router(table)
    cyclotron.confidence = {("hn-101", "anth-us"): 0.91234, ("hn-101", "p-apyr-us"): 1.7, ("hn-101", "threat-intelligence"): "high"}
    go(table, store, cyclotron)
    publications = table.items[("MONITOR#hn", "ROUTE#101#000001")]["decision"]["publications"]
    assert publications["anth-us"]["confidence"] == Decimal("0.9123")
    assert "confidence" not in publications["p-apyr-us"] and "confidence" not in publications["threat-intelligence"]


def test_retired_ceilings_are_ignored_and_never_become_router_state():
    base = router_config()
    configured = validate_router_config({**base, "ceilings": {"decisionsTotal": 300, "decisionsPerDay": 100, "items": 300}})
    assert configured["mode"] == "live" and "ceilings" not in configured
    # Old stored quota payloads have no authority and may be malformed without
    # blocking routing or being reflected as active configuration.
    for retired in ({"decisionsTotal": 0}, {"decisionsPerDay": "many"}, {"items": -1}, {"surprise": 1}, "300"):
        assert "ceilings" not in validate_router_config({**base, "ceilings": retired})


def test_all_exclude_routes_without_delivery(table):
    store, cyclotron = setup_router(table)
    cyclotron.labels = {("hn-101", p): "exclude" for p in PUBS}
    delivery = Delivery()
    go(table, store, cyclotron, deliver=delivery)
    assert not delivery.calls and routing_of(table)["DISC#101#000001"] == "routed"
    assert not [k for k in table.items if k[1].startswith("DELIV#")]


@pytest.mark.parametrize("status,code", [(503, "provider_key_unavailable"), (429, "request_ceiling_reached"),
                                         (507, "standing_capacity_reached"), (409, "run_busy"),
                                         (503, "live publication predictions are disabled")])
def test_post_refusals_stop_the_sweep_and_leave_items_collected_without_retry(table, status, code):
    store, cyclotron = setup_router(table)
    cyclotron.post_override["anth-us"] = (status, {"code": code} if " " not in code else {"error": code})
    result = go(table, store, cyclotron)
    assert result["status"] == "stopped" and len(cyclotron.posts()) == 1
    assert set(routing_of(table).values()) == {"collected"}
    assert table.by_prefix("ROUTERUN#")[0]["stoppedBy"] == code
    assert "anth-us" not in table.items[("MONITOR#hn", "ROUTE#101#000001")].get("jobs", {})   # a refused POST may be sent later
    cyclotron.post_override.clear()
    go(table, store, cyclotron, now=3000)
    assert "routed" in set(routing_of(table).values())


def test_run_busy_poll_refusal_stops_the_sweep_and_never_reposts(table):
    store, cyclotron = setup_router(table)
    cyclotron.poll_override["p-apyr-us"] = (409, {"code": "run_busy"})
    result = go(table, store, cyclotron)
    assert result["status"] == "stopped" and result["stoppedBy"] == "run_busy"
    assert set(routing_of(table).values()) == {"collected"}
    posts = len(cyclotron.posts())
    cyclotron.poll_override.clear()
    go(table, store, cyclotron, now=3000)
    first = [c for c in cyclotron.posts() if c[2]["payload"]["item"]["id"] == "hn-101"]
    assert len(first) == 3 and len(cyclotron.posts()) > posts      # item 101 was not re-POSTed per publication
    assert routing_of(table)["DISC#101#000001"] == "routed"


@pytest.mark.parametrize("status,code", [(503, "provider_key_unavailable"), (429, "request_ceiling_reached"),
                                         (507, "standing_capacity_reached")])
def test_non_consuming_poll_refusals_retry_under_a_new_request_id(table, status, code):
    store, cyclotron = setup_router(table)
    cyclotron.poll_override["p-apyr-us"] = (status, {"code": code})
    result = go(table, store, cyclotron)
    assert result["status"] == "stopped" and result["stoppedBy"] == code
    assert set(routing_of(table).values()) == {"collected"}
    assert table.items[("MONITOR#hn", "ROUTE#101#000001")]["attempt"] == 1
    cyclotron.poll_override.clear()
    go(table, store, cyclotron, now=3000)
    ids = [c[2]["requestId"] for c in cyclotron.posts() if c[2]["payload"]["item"]["id"] == "hn-101"]
    assert len(ids) == len(set(ids)) and len(ids) >= 3
    assert routing_of(table)["DISC#101#000001"] == "routed"


def test_source_refused_marks_the_item_refused_and_moves_on(table):
    store, cyclotron = setup_router(table)
    cyclotron.post_override["anth-us"] = (409, {"code": "source_refused"})
    go(table, store, cyclotron)
    assert set(routing_of(table).values()) == {"refused"}
    disc = table.items[("MONITOR#hn", "DISC#101#000001")]
    assert "gsi1pk" not in disc and table.items[("MONITOR#hn", "ROUTE#101#000001")]["final"]["reason"] == "source_refused"


def test_uncertain_post_is_never_repeated(table):
    store, cyclotron = setup_router(table)
    cyclotron.post_override["anth-us"] = (500, {})
    go(table, store, cyclotron)
    assert routing_of(table)["DISC#101#000001"] == "uncertain"
    cyclotron.post_override.clear()
    go(table, store, cyclotron, now=3000)
    assert [c for c in cyclotron.posts() if c[2]["payload"]["item"]["id"] == "hn-101"] == [cyclotron.posts()[0]]


def test_pending_job_is_resumed_by_polling_only(table):
    store, cyclotron = setup_router(table)
    cyclotron.pending_polls = 10_000
    state = {"t": 0}
    config = validate_router_config(table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"])
    ticking = CyclotronClient(config, sign=lambda m, u, b: {}, http=cyclotron.http,
                              sleep=lambda s: state.__setitem__("t", state["t"] + s), clock=lambda: state["t"])
    result = run_router(store, "hn", now=2000, cyclotron=ticking, appsync=lambda e: object(), deliver=Delivery(),
                        context_receipt=lambda c, p: {})
    assert result["status"] == "awaiting" and result["stoppedBy"] == "awaiting"
    assert routing_of(table)["DISC#101#000001"] == "collected"
    job = table.items[("MONITOR#hn", "ROUTE#101#000001")]["jobs"]["anth-us"]
    assert job["jobId"] and len(cyclotron.posts()) == 3   # every binding is posted before anything waits
    cyclotron.pending_polls = 0
    go(table, store, cyclotron, now=2600)
    assert len(cyclotron.posts()) == 3          # one per publication in total: no POST was repeated
    assert routing_of(table)["DISC#101#000001"] == "routed"


def test_a_long_pending_job_is_never_finalized_and_is_collected_when_the_lab_completes(table):
    store, cyclotron = setup_router(table)
    cyclotron.pending_polls = 10_000
    go(table, store, cyclotron, now=2000)
    assert not hasattr(mr, "MAX_PENDING_JOB_SECONDS")
    go(table, store, cyclotron, now=2000 + 30 * 86400, task="collect")   # a month later, still pending
    assert routing_of(table)["DISC#101#000001"] == "collected"
    assert "final" not in table.items[("MONITOR#hn", "ROUTE#101#000001")]
    cyclotron.pending_polls = 0
    go(table, store, cyclotron, now=2000 + 31 * 86400, task="collect")
    assert routing_of(table)["DISC#101#000001"] == "routed"
    assert len(cyclotron.posts()) == 3


def test_reopen_stale_finals_restores_only_the_age_limit_finals_and_the_collector_delivers_them(table3):
    store, cyclotron = setup_router(table3)
    cyclotron.pending_polls = 10_000
    go(table3, store, cyclotron, now=2000)
    route_sk, disc_sk = ("MONITOR#hn", "ROUTE#101#000001"), ("MONITOR#hn", "DISC#101#000001")
    # what the old limit did: final error, out of the routing partition, jobs kept
    route = table3.items[route_sk]
    route["final"] = {"routing": "error", "reason": mr.STALE_FINAL_REASON, "at": "x"}
    original = dict(table3.items[disc_sk])
    mr.set_routing(store, "hn", table3.items[disc_sk], "error", None)
    other = table3.items[("MONITOR#hn", "ROUTE#102#000001")]
    other["final"] = {"routing": "error", "reason": "lab does not know the job", "at": "x"}
    mr.set_routing(store, "hn", table3.items[("MONITOR#hn", "DISC#102#000001")], "error", None)
    assert "gsi1pk" not in table3.items[disc_sk]
    jobs_before = deepcopy({k: route.get(k) for k in ("jobs", "combinedJob")})
    result = go(table3, store, cyclotron, now=3000, task="reopen-stale-finals")
    assert result["reopened"] == 1 and result["status"] == "complete"
    assert "final" not in table3.items[route_sk] and {k: table3.items[route_sk].get(k) for k in jobs_before} == jobs_before
    assert table3.items[disc_sk]["routing"] == "collected" and table3.items[disc_sk]["gsi1pk"] == "ROUTING#hn#collected"
    assert table3.items[disc_sk]["gsi1sk"] == original["gsi1sk"]
    assert table3.items[("MONITOR#hn", "ROUTE#102#000001")]["final"]["reason"] == "lab does not know the job"
    assert routing_of(table3)["DISC#102#000001"] == "error"
    assert go(table3, store, cyclotron, now=3001, task="reopen-stale-finals")["reopened"] == 0
    cyclotron.pending_polls = 0
    go(table3, store, cyclotron, now=4000, task="collect")
    assert routing_of(table3)["DISC#101#000001"] == "routed" and routing_of(table3)["DISC#102#000001"] == "error"


def test_divergent_decisions_are_an_error_not_a_delivery(table):
    store, cyclotron = setup_router(table)
    original = cyclotron.http

    def diverge(method, url, headers, body, timeout):
        status, payload = original(method, url, headers, body, timeout)
        if method == "GET" and "/threat-intelligence/" in url:
            payload["decision"]["decisionId"] = "other-decision"
        return status, payload

    cyclotron.http = diverge
    delivery = Delivery()
    go(table, store, cyclotron, deliver=delivery)
    assert routing_of(table)["DISC#101#000001"] == "error" and not delivery.calls


def test_delivery_failure_is_isolated_per_publication_and_retried_with_backoff(table3):
    store, cyclotron = setup_router(table3)
    delivery = Delivery()
    delivery.fail = {"p-apyr-us"}
    go(table3, store, cyclotron, deliver=delivery)
    route = table3.items[("MONITOR#hn", "ROUTE#101#000001")]
    assert route["publications"]["anth-us"]["delivered"] and route["publications"]["threat-intelligence"]["delivered"]
    assert not route["publications"]["p-apyr-us"]["delivered"] and route["publications"]["p-apyr-us"]["attempts"] == 1
    assert "backend unavailable" in route["publications"]["p-apyr-us"]["lastError"]
    disc = table3.items[("MONITOR#hn", "DISC#101#000001")]
    assert disc["routing"] == "decided" and disc["gsi1pk"] == "ROUTING#hn#decided"
    # not due yet: the decided item is skipped, new items proceed
    go(table3, store, cyclotron, now=2100, deliver=delivery)
    assert route["publications"]["p-apyr-us"]["attempts"] == 1
    assert routing_of(table3)["DISC#102#000001"] == "decided"    # a new item was decided and delivered to the healthy publications
    assert table3.items[("MONITOR#hn", "ROUTE#102#000001")]["publications"]["anth-us"]["delivered"]
    delivery.fail = set()
    before = list(delivery.calls)
    go(table3, store, cyclotron, now=2000 + 301, deliver=delivery)
    new_calls = delivery.calls[len(before):]
    assert ("p-apyr-us", "101") in {(p, s) for p, s, *_ in new_calls}
    assert not {(p, s) for p, s, *_ in new_calls} & {("anth-us", "101"), ("threat-intelligence", "101")}
    assert routing_of(table3)["DISC#101#000001"] == "routed"
    assert len([k for k in table3.items if k[1].startswith("DELIV#") and "-101" in k[1]]) == 3


def test_lease_contention_and_expiry(table):
    store, cyclotron = setup_router(table, mode="dry-run")
    assert store.acquire_router_lock("hn", "other", now=2000)
    assert go(table, store, None, now=2010)["status"] == "locked"
    assert not table.by_prefix("ROUTERUN#")
    assert ("MONITOR#hn", "LOCK") not in table.items          # the collector's lock key is separate
    assert go(table, store, None, now=2000 + mr.LEASE_SECONDS + 1)["status"] == "complete"
    assert ("MONITOR#hn", mr.ROUTER_LOCK_SK) not in table.items


def test_not_configured_and_disabled(table):
    store = RouterStore(table)
    assert run_router(store, "hn", now=1)["status"] == "not_configured"
    table.put_item(router_config(enabled=False))
    assert run_router(store, "hn", now=1)["status"] == "disabled"


# --- Cyclotron client -------------------------------------------------------------------------------------

def test_client_signs_with_sigv4_for_execute_api_and_the_account_header():
    pytest.importorskip("botocore")
    config = validate_router_config(router_config())
    sign = mr.sigv4_signer(config, lambda: {"key": "AKIDEXAMPLE", "secret": "secret", "token": "token"})
    headers = {k.lower(): v for k, v in sign("POST", config["cyclotron"]["endpoint"] + "/machine/publications/anth-us/operations", b"{}").items()}
    assert "/us-east-1/execute-api/aws4_request" in headers["authorization"]
    assert headers["x-cyclotron-account"] == "acct-1" and headers["x-amz-security-token"] == "token"
    assert "x-cyclotron-account" in headers["authorization"]


# --- feedback -----------------------------------------------------------------------------------------------

class FakeAppSync:
    def __init__(self, references):
        self.references = references

    def get_record(self, model, record_id):
        assert model == "Reference"
        return self.references.get(record_id)


def delivered_table(table, labels=None):
    store, cyclotron = setup_router(table, feedback=True)
    go(table, store, cyclotron, deliver=Delivery())
    return store, cyclotron


def feedback_run(table, store, cyclotron, references, now=5000, **kwargs):
    config = validate_router_config(table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"])
    client = CyclotronClient(config, sign=lambda m, u, b: {}, http=cyclotron.http, sleep=lambda s: None, clock=lambda: 0)
    return run_router(store, "hn", now=now, task="feedback", cyclotron=client,
                      appsync=lambda e: FakeAppSync(references), deliver=Delivery(), **kwargs)


def ref(status, actor, at="2026-10-21T01:00:00Z"):
    return {"curationStatus": status, "curationStatusUpdatedBy": actor, "curationStatusUpdatedAt": at}


def test_feedback_maps_accepted_and_rejected_to_labels_with_deterministic_request_ids(table):
    store, cyclotron = delivered_table(table)
    references = {"reference-anth-us-101": ref("accepted", "user:sub-1"),
                  "reference-p-apyr-us-101": ref("rejected", "user:sub-2"),
                  "reference-threat-intelligence-101": ref("pending", "papyrus-monitoring-worker")}
    result = feedback_run(table, store, cyclotron, references)
    assert result["feedback"]["sent"] == 2 and result["feedback"]["pending"] == 1
    sent = {c[1].split("/")[3]: c[2] for c in cyclotron.posts() if c[2]["operation"] == "feedback"}
    assert sent["anth-us"]["payload"] == {"bindingRevision": "1", "itemId": "hn-101", "itemRevision": 2,
                                          "output": "anth-us-relevance", "label": "include",
                                          "editor": {"site": "anth-us.example", "subject": "user:sub-1"}}
    assert sent["p-apyr-us"]["payload"]["label"] == "exclude"
    from hashlib import sha256
    assert sent["anth-us"]["requestId"] == sha256("\n".join(["reference-anth-us-101", "accepted", "2026-10-21T01:00:00Z"]).encode()).hexdigest()
    fb = [v for k, v in table.items.items() if k[1].startswith("FB#")]
    assert {f["outcome"] for f in fb} == {"sent"} and len(fb) == 2
    done = table.items[("MONITOR#hn", "DELIV#anth-us#reference-anth-us-101")]
    assert done["feedback"] == "sent" and "gsi1pk" not in done
    # rerun: sent rows are out of the queue, the pending one is checked again, nothing is re-sent
    again = feedback_run(table, store, cyclotron, references, now=6000)
    assert again["feedback"]["sent"] == 0 and len([c for c in cyclotron.posts() if c[2]["operation"] == "feedback"]) == 2


def test_held_decisions_send_no_decide_request_and_say_so_in_the_receipt(table):
    store, cyclotron = setup_router(table, holdDecisions=True)
    result = go(table, store, cyclotron)
    assert cyclotron.posts() == [] and result["stoppedBy"] == "decisions_held"
    receipt = [v for k, v in table.items.items() if k[1].startswith("ROUTERUN#")][0]
    assert receipt["stoppedBy"] == "decisions_held"


def test_a_disabled_router_still_does_nothing_even_when_decisions_are_held(table):
    store, cyclotron = setup_router(table, holdDecisions=True, enabled=False)
    assert go(table, store, cyclotron)["status"] == "disabled" and cyclotron.posts() == []


def test_feedback_is_still_sent_while_decisions_are_held(table):
    store, cyclotron = delivered_table(table)
    table.items[("MONITOR#hn", "CONFIG#router")]["holdDecisions"] = True
    before = len(cyclotron.posts())
    references = {"reference-anth-us-101": ref("accepted", "user:sub-1")}
    result = feedback_run(table, store, cyclotron, references)
    new = cyclotron.posts()[before:]
    assert result["feedback"]["sent"] == 1 and [c[2]["operation"] for c in new] == ["feedback"]


@pytest.mark.parametrize("record", [
    ref("accepted", None), ref("accepted", ""), ref("accepted", "papyrus-monitoring-worker"),
    ref("accepted", "system:auto"), ref("accepted", "user:")])
def test_feedback_skips_missing_or_non_human_actors_and_records_why(table, record):
    store, cyclotron = delivered_table(table)
    result = feedback_run(table, store, cyclotron, {"reference-anth-us-101": record})
    assert result["feedback"]["sent"] == 0 and result["feedback"]["skipped"] >= 1
    assert not [c for c in cyclotron.posts() if c[2]["operation"] == "feedback"]
    row = table.items[("MONITOR#hn", "DELIV#anth-us#reference-anth-us-101")]
    assert "not a human" in row["lastNote"] and row["gsi1pk"] == "FEEDBACK#hn#pending"


def test_feedback_is_off_unless_enabled_and_live(table):
    store, cyclotron = setup_router(table, feedback=False)
    go(table, store, cyclotron, deliver=Delivery())
    refs = {"reference-anth-us-101": ref("accepted", "user:s")}
    assert feedback_run(table, store, cyclotron, refs)["feedback"]["status"] == "off"
    table.put_item(router_config("dry-run", feedback=True))
    assert feedback_run(table, store, cyclotron, refs)["feedback"]["status"] == "off"
    assert not [c for c in cyclotron.posts() if c[2]["operation"] == "feedback"]


def test_feedback_refusal_stops_cleanly_and_uncertain_is_retried_later(table):
    store, cyclotron = delivered_table(table)
    refs = {"reference-anth-us-101": ref("accepted", "user:s")}
    cyclotron.feedback_override = (503, {"code": "provider_key_unavailable"})
    result = feedback_run(table, store, cyclotron, refs)
    assert result["feedback"]["status"] == "stopped" and result["feedback"]["stoppedBy"] == "provider_key_unavailable"
    assert table.items[("MONITOR#hn", "DELIV#anth-us#reference-anth-us-101")]["gsi1pk"] == "FEEDBACK#hn#pending"
    cyclotron.feedback_override = (500, {})
    assert feedback_run(table, store, cyclotron, refs, now=6000)["feedback"]["failed"] == 1
    cyclotron.feedback_override = None
    assert feedback_run(table, store, cyclotron, refs, now=7000)["feedback"]["sent"] == 1
    request_ids = {c[2]["requestId"] for c in cyclotron.posts() if c[2]["operation"] == "feedback"}
    assert len(request_ids) == 1           # every retry used the same idempotency key


def rebind(table, revision, since=None, only=None):
    cfg = router_config("live", feedback=True)
    cfg["cyclotron"] = cfg["cyclotron"] | {"bindingRevision": revision}
    for entry in cfg["publications"]:
        if since is not None and (only is None or entry["publicationId"] == only):
            entry["criteriaSince"] = since
    table.put_item(cfg)


def test_feedback_vote_under_older_binding_is_dropped_when_criteria_changed(table):
    store, cyclotron = delivered_table(table)
    rebind(table, "4", since="1", only="anth-us")          # anth-us criteria unchanged; the others default to "4"
    refs = {"reference-anth-us-101": ref("accepted", "user:a"), "reference-p-apyr-us-101": ref("accepted", "user:b")}
    result = feedback_run(table, store, cyclotron, refs)
    assert result["feedback"]["sent"] == 1 and result["feedback"]["skipped"] == 1
    sent = [c for c in cyclotron.posts() if c[2]["operation"] == "feedback"]
    assert len(sent) == 1 and "anth-us" in sent[0][1] and sent[0][2]["payload"]["bindingRevision"] == "4"
    dropped = table.items[("MONITOR#hn", "DELIV#p-apyr-us#reference-p-apyr-us-101")]
    assert dropped["feedback"] == "stale" and "gsi1pk" not in dropped
    assert [v["outcome"] for k, v in table.items.items() if k[1].startswith("FB#") and v["publicationId"] == "p-apyr-us"] == ["stale"]
    feedback_run(table, store, cyclotron, refs, now=6000)
    assert len([c for c in cyclotron.posts() if c[2]["operation"] == "feedback"]) == 1   # not retried


def test_criteria_unchanged_compares_numerically():
    from papyrus_content.monitoring_router import criteria_unchanged
    assert criteria_unchanged("10", "9") and not criteria_unchanged("3", "4") and criteria_unchanged("3", "3")
    assert criteria_unchanged("a", "a") and not criteria_unchanged("a", "b")


def test_feedback_for_an_item_decided_under_an_older_binding_is_sent_with_the_current_binding(table):
    store, cyclotron = delivered_table(table)
    rebind(table, "4", since="1")
    refs = {"reference-anth-us-101": ref("accepted", "user:s")}
    row = table.items[("MONITOR#hn", "DELIV#anth-us#reference-anth-us-101")]
    assert row["bindingRevision"] == "1"
    assert feedback_run(table, store, cyclotron, refs)["feedback"]["sent"] == 1
    sent = [c[2] for c in cyclotron.posts() if c[2]["operation"] == "feedback"]
    assert [p["payload"]["bindingRevision"] for p in sent] == ["4"]


def test_feedback_binding_changed_is_retried_next_run_instead_of_stopping_the_sweep(table):
    store, cyclotron = delivered_table(table)
    refs = {"reference-anth-us-101": ref("accepted", "user:s"), "reference-p-apyr-us-101": ref("accepted", "user:t")}
    cyclotron.feedback_override = (409, {"detail": "publication binding changed"})
    result = feedback_run(table, store, cyclotron, refs)
    assert result["feedback"]["status"] == "complete" and result["feedback"]["failed"] == 2
    assert table.items[("MONITOR#hn", "DELIV#anth-us#reference-anth-us-101")]["gsi1pk"] == "FEEDBACK#hn#pending"
    cyclotron.feedback_override = None
    assert feedback_run(table, store, cyclotron, refs, now=6000)["feedback"]["sent"] == 2


def test_feedback_for_a_publication_missing_from_the_config_is_skipped_without_posting(table):
    store, cyclotron = delivered_table(table)
    cfg = router_config("live", feedback=True)
    cfg["publications"] = [p for p in cfg["publications"] if p["publicationId"] != "anth-us"]
    table.put_item(cfg)
    result = feedback_run(table, store, cyclotron, {"reference-anth-us-101": ref("accepted", "user:s")})
    assert result["feedback"]["sent"] == 0 and result["feedback"]["skipped"] >= 1
    assert not [c for c in cyclotron.posts() if c[2]["operation"] == "feedback" and "anth-us" in c[1]]


# --- intake provenance, packaging, template --------------------------------------------------------------------

def test_intake_rationale_names_the_machine_decision():
    from papyrus_content.monitoring_intake import ReferenceIntake
    note = ReferenceIntake._machine_decision_note({"machineDecision": {"system": "cyclotron", "output": "x-relevance", "label": "include",
                                                                    "decisionId": "d1", "version": 3}})
    assert "cyclotron labelled x-relevance include" in note and "d1" in note
    assert ReferenceIntake._machine_decision_note({}) == ""


def test_router_zip_imports_with_only_the_standard_library(tmp_path):
    sys.path.insert(0, str(ROOT / "infra" / "monitoring"))
    try:
        import build
        out = tmp_path / "router.zip"
        build.build_router(out)
    finally:
        sys.path.pop(0)
    root = tmp_path / "task"
    zipfile.ZipFile(out).extractall(root)
    assert out.stat().st_size < 400_000
    code = (
        "import sys; sys.path.insert(0, sys.argv[1])\n"
        "import papyrus_content.monitoring_router as r, papyrus_content.monitoring_intake as i, papyrus_content.editorial_context as e\n"
        "from papyrus_content.relation_types import load_semantic_relation_type_seeds\n"
        "from papyrus_content.newsroom_doctrine import DOCTRINE_DEFINITION_BY_KIND\n"
        "assert load_semantic_relation_type_seeds() and DOCTRINE_DEFINITION_BY_KIND\n"
        "import yaml; assert not yaml.__with_libyaml__\n"
        "assert not any(m in sys.modules for m in ('pydantic', 'biblicus', 'httpx', 'tiktoken'))\n")
    env = {"PAPYRUS_ROOT": str(root), "PATH": "/usr/bin:/bin"}
    done = subprocess.run([sys.executable, "-S", "-c", code, str(root)], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert done.returncode == 0, done.stderr


def test_collector_zip_is_independent_of_the_router():
    sys.path.insert(0, str(ROOT / "infra" / "monitoring"))
    try:
        import build
    finally:
        sys.path.pop(0)
    collector = build.package_modules(build.COLLECTOR_ROOTS)
    assert "monitoring_router" not in collector
    assert {"monitoring", "monitoring_cloud", "monitoring_huggingface", "monitoring_paging"} <= set(collector)


def test_collector_zip_imports_everything_it_needs(tmp_path):
    """The collector zip is the import closure of its roots, so a module added to monitoring_cloud is never left out."""
    sys.path.insert(0, str(ROOT / "infra" / "monitoring"))
    try:
        import build
    finally:
        sys.path.pop(0)
    import subprocess
    import zipfile
    out = tmp_path / "collector.zip"
    build.build(out)
    zipfile.ZipFile(out).extractall(tmp_path / "unzipped")
    result = subprocess.run([sys.executable, "-I", "-c", "import papyrus_content.monitoring_cloud"],
                            cwd=tmp_path / "unzipped", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "web_structured_metadata" not in build.router_modules() and "monitoring_router" in build.router_modules()


def _template():
    class Loader(yaml.SafeLoader):
        pass
    Loader.add_multi_constructor("!", lambda loader, suffix, node: (suffix, loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode)
                                                                      else loader.construct_sequence(node, deep=True) if isinstance(node, yaml.SequenceNode)
                                                                      else loader.construct_mapping(node, deep=True)))
    return yaml.load(TEMPLATE.read_text(), Loader=Loader)


def test_router_role_is_least_privilege():
    template = _template()
    statements = template["Resources"]["RouterRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    assert {s["Sid"] for s in statements} == {"MonitoringTable", "OwnLogs", "FailedInvocations", "CyclotronMachineInvoker",
                                              "PublicationReferenceIntake"}
    by_sid = {s["Sid"]: s for s in statements}
    assert by_sid["CyclotronMachineInvoker"]["Action"] == "sts:AssumeRole" and by_sid["CyclotronMachineInvoker"]["Resource"] == ("Ref", "CyclotronInvokerRoleArn")
    assert template["Parameters"]["CyclotronInvokerRoleArn"]["Default"] == "arn:aws:iam::682849160744:role/cyclotron-machine-invoker"
    intake = by_sid["PublicationReferenceIntake"]
    assert intake["Action"] == "appsync:GraphQL"
    resources = [r[1] for r in intake["Resource"]]
    assert all("/types/" in r and "/fields/" in r and "*" not in r for r in resources)
    fields = {r.rsplit("/", 1)[1] for r in resources}
    assert not any(f.startswith(("delete", "update")) and f != "updateReferenceAttachment" for f in fields)
    assert {r.split("apis/")[1].split("/")[0] for r in resources} == {"${AnthUsApiId}", "${PapyrusApiId}", "${ThreatIntelApiId}"}
    assert all(len([r for r in resources if f"${{{p}}}" in r]) == len(fields) for p in ("AnthUsApiId", "PapyrusApiId", "ThreatIntelApiId"))
    distinctive = template["Resources"]["RouterDistinctiveIntakePolicy"]["Properties"]
    assert distinctive["Roles"] == [("Ref", "RouterRole")]
    (statement,) = distinctive["PolicyDocument"]["Statement"]
    assert statement["Action"] == "appsync:GraphQL"
    distinctive_resources = [r[1] for r in statement["Resource"]]
    assert {r.split("apis/")[1].split("/")[0] for r in distinctive_resources} == {"${DistinctiveApiId}"}
    assert {r.rsplit("/", 1)[1] for r in distinctive_resources} == fields and "*" not in "".join(distinctive_resources)
    # Lab decisions are written as relevance_decision_is relations (a SemanticNode per label; the old relation is superseded).
    # Only the cyclotron-decided publications get those grants; Distinctive is a `direct` monitor with no machine decision.
    relations = _template()["Resources"]["RouterDecisionRelationPolicy"]["Properties"]
    assert relations["Roles"] == [("Ref", "RouterRole")]
    (relation_statement,) = relations["PolicyDocument"]["Statement"]
    relation_resources = [r[1] for r in relation_statement["Resource"]]
    assert relation_statement["Action"] == "appsync:GraphQL" and "*" not in "".join(relation_resources)
    assert {r.rsplit("/", 1)[1] for r in relation_resources} == {
        "getSemanticNode", "listSemanticRelationsBySubjectState", "createSemanticNode", "updateSemanticRelation"}
    assert {r.split("apis/")[1].split("/")[0] for r in relation_resources} == {"${AnthUsApiId}", "${PapyrusApiId}", "${ThreatIntelApiId}", "${DataParadeApiId}", "${PilobolusApiId}", "${ShippedApiId}"}
    assert len(json.dumps(statements).replace(" ", "")) < 9_500    # IAM inline policy limit is 10,240 characters
    assert all(a != "dynamodb:Scan" for a in by_sid["MonitoringTable"]["Action"])


def test_data_parade_gets_exactly_the_cyclotron_decided_grants():
    template = _template()
    assert template["Parameters"]["DataParadeApiId"]["Default"] == "rgfkmmyyyrc7fb55qd5smbfrpm"
    inline = {s["Sid"]: s for s in template["Resources"]["RouterRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]}["PublicationReferenceIntake"]
    # Intake lives in its own managed policy (the inline policy is near IAM's size limit), like Distinctive's.
    policy = template["Resources"]["RouterDataParadeIntakePolicy"]["Properties"]
    assert policy["Roles"] == [("Ref", "RouterRole")]
    (intake,) = policy["PolicyDocument"]["Statement"]
    relations = template["Resources"]["RouterDecisionRelationPolicy"]["Properties"]["PolicyDocument"]["Statement"][0]
    anth_intake = [r[1] for r in inline["Resource"]]
    anth_fields = {r.rsplit("/fields/", 1)[1] for r in anth_intake if "apis/${AnthUsApiId}/" in r}
    for statement in (intake, relations):
        assert statement["Action"] == "appsync:GraphQL"
        resources = [r[1] for r in statement["Resource"]]
        assert "*" not in "".join(resources) and all("/types/" in r and "/fields/" in r for r in resources)
        data_parade = {r.rsplit("/fields/", 1)[1] for r in resources if "apis/${DataParadeApiId}/" in r}
        anth_us = {r.rsplit("/fields/", 1)[1] for r in resources if "apis/${AnthUsApiId}/" in r}
        assert data_parade and data_parade == (anth_fields if statement is intake else anth_us)
    assert not any("DataParadeApiId" in r for r in anth_intake)


def test_pilobolus_gets_exactly_the_cyclotron_decided_grants():
    template = _template()
    assert template["Parameters"]["PilobolusApiId"]["Default"] == "2tvll2u5ejafbmawb3v2sdonvi"
    inline = {s["Sid"]: s for s in template["Resources"]["RouterRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]}["PublicationReferenceIntake"]
    # Intake lives in its own managed policy (the inline policy is near IAM's size limit), like Distinctive's.
    policy = template["Resources"]["RouterPilobolusIntakePolicy"]["Properties"]
    assert policy["Roles"] == [("Ref", "RouterRole")]
    (intake,) = policy["PolicyDocument"]["Statement"]
    relations = template["Resources"]["RouterDecisionRelationPolicy"]["Properties"]["PolicyDocument"]["Statement"][0]
    anth_intake = [r[1] for r in inline["Resource"]]
    anth_fields = {r.rsplit("/fields/", 1)[1] for r in anth_intake if "apis/${AnthUsApiId}/" in r}
    for statement in (intake, relations):
        assert statement["Action"] == "appsync:GraphQL"
        resources = [r[1] for r in statement["Resource"]]
        assert "*" not in "".join(resources) and all("/types/" in r and "/fields/" in r for r in resources)
        pilobolus = {r.rsplit("/fields/", 1)[1] for r in resources if "apis/${PilobolusApiId}/" in r}
        anth_us = {r.rsplit("/fields/", 1)[1] for r in resources if "apis/${AnthUsApiId}/" in r}
        assert pilobolus and pilobolus == (anth_fields if statement is intake else anth_us)
    assert not any("PilobolusApiId" in r for r in anth_intake)


def test_shipped_gets_exactly_the_cyclotron_decided_grants():
    template = _template()
    assert template["Parameters"]["ShippedApiId"]["Default"] == "6sw6454pozbgvdgm233gqkxsxu"
    inline = {s["Sid"]: s for s in template["Resources"]["RouterRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]}["PublicationReferenceIntake"]
    # Intake lives in its own managed policy (the inline policy is near IAM's size limit), like Distinctive's.
    policy = template["Resources"]["RouterShippedIntakePolicy"]["Properties"]
    assert policy["Roles"] == [("Ref", "RouterRole")]
    (intake,) = policy["PolicyDocument"]["Statement"]
    relations = template["Resources"]["RouterDecisionRelationPolicy"]["Properties"]["PolicyDocument"]["Statement"][0]
    anth_intake = [r[1] for r in inline["Resource"]]
    anth_fields = {r.rsplit("/fields/", 1)[1] for r in anth_intake if "apis/${AnthUsApiId}/" in r}
    for statement in (intake, relations):
        assert statement["Action"] == "appsync:GraphQL"
        resources = [r[1] for r in statement["Resource"]]
        assert "*" not in "".join(resources) and all("/types/" in r and "/fields/" in r for r in resources)
        shipped = {r.rsplit("/fields/", 1)[1] for r in resources if "apis/${ShippedApiId}/" in r}
        anth_us = {r.rsplit("/fields/", 1)[1] for r in resources if "apis/${AnthUsApiId}/" in r}
        assert shipped and shipped == (anth_fields if statement is intake else anth_us)
    assert not any("ShippedApiId" in r for r in anth_intake)


def test_router_function_schedule_and_collector_isolation():
    template = _template()["Resources"]
    function = template["RouterFunction"]["Properties"]
    assert function["Handler"] == "papyrus_content.monitoring_router.handler" and function["Runtime"] == "python3.13"
    assert function["Timeout"] > 120 and function["Timeout"] <= 900 and mr.LEASE_SECONDS > function["Timeout"]
    assert function["Environment"]["Variables"]["PAPYRUS_ROOT"] == "/var/task"
    assert function["Code"]["S3Key"] == ("Ref", "RouterCodeKey") and template["CollectorFunction"]["Properties"]["Code"]["S3Key"] == ("Ref", "CodeKey")
    assert template["RouteSchedule"]["Properties"]["ScheduleExpression"] == "cron(7/15 * * * ? *)"
    assert template["RouterInvokeConfig"]["Properties"]["MaximumRetryAttempts"] == 0
    assert {"RouterErrorsAlarm", "RouterDeadLetterAlarm", "RouterLogGroup", "RouterDeadLetterQueue"} <= set(template)
    assert template["RouterLogGroup"]["Properties"]["RetentionInDays"] == 30


def test_table_name_is_published_for_the_read_only_monitoring_page():
    from papyrus_content.monitoring_view import TABLE_PARAMETER
    parameter = _template()["Resources"]["TableNameParameter"]
    assert parameter["Type"] == "AWS::SSM::Parameter"
    assert parameter["Properties"]["Name"] == TABLE_PARAMETER
    assert parameter["Properties"]["Value"] == ("Ref", "MonitoringTable")


def test_seed_cli_no_longer_accepts_ceiling_updates():
    import importlib.util
    spec = importlib.util.spec_from_file_location("seed_router_config", ROOT / "infra" / "monitoring" / "seed_router_config.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    for key, value in (("ceilings", "decisionsTotal=300,decisionsPerDay=100,items=300"), ("ceilings", "none")):
        with pytest.raises(ValueError, match="not ceilings"):
            seed.coerce(key, value)


# --- not-ready outputs (criteria_pending) --------------------------------------------------------------

def test_not_ready_binding_must_not_halt_the_sweep(table3):
    """Reproduces the halt: one binding answers 409 criteria_pending; the others must still decide and deliver."""
    store, cyclotron = setup_router(table3)
    cyclotron.post_override["threat-intelligence"] = (409, {"detail": "publication criteria are pending"})
    delivery = Delivery()
    result = go(table3, store, cyclotron, deliver=delivery)
    assert result["status"] == "complete" and result["stoppedBy"] is None
    assert result["counts"]["routed"] == 3                      # every candidate item reached the ready bindings
    assert {c[0] for c in delivery.calls} == {"anth-us", "p-apyr-us"}
    assert result["counts"]["skippedNotReady"] == 3
    assert result["waitingForClassifier"] == ["threat-intelligence"]
    assert [c for c in cyclotron.posts() if c[1].split("/")[3] == "threat-intelligence"][0:1]   # probed once, not per item
    assert len([c for c in cyclotron.posts() if c[1].split("/")[3] == "threat-intelligence"]) == 1


def parked(table, pub_id):
    """The rows of the items parked for a publication (PARK#<pub>#<sourceId>#<rev>), not its header."""
    return [v for k, v in sorted(table.items.items()) if k[1].startswith(f"PARK#{pub_id}#")]


def test_not_ready_binding_is_parked_probed_after_backoff_and_backfilled_when_ready(table3):
    store, cyclotron = setup_router(table3)
    cyclotron.post_override["threat-intelligence"] = (409, {"detail": "publication criteria are pending"})
    delivery = Delivery()
    ti = lambda: [c for c in cyclotron.posts() if c[1].split("/")[3] == "threat-intelligence"]
    first = go(table3, store, cyclotron, now=2000, deliver=delivery)
    assert first["status"] == "complete" and len(ti()) == 1
    park = table3.items[("MONITOR#hn", "PARK#threat-intelligence")]
    assert park["ready"] is False and park["nextProbeAt"] == 2000 + 1800 and len(parked(table3, "threat-intelligence")) == 3
    # inside the backoff window: no call at all for the waiting binding, other bindings carry on
    second = go(table3, store, cyclotron, now=2300, deliver=delivery)
    assert len(ti()) == 1 and second["waitingForClassifier"] == ["threat-intelligence"]
    # backoff elapsed and still pending: the next new story makes exactly one probe, backoff doubles
    delta = b"<item><title>Delta source</title><link>https://example.org/delta</link><comments>https://news.ycombinator.com/item?id=104</comments></item>"
    run_collection(DynamoStore(table3), "hn", fetch=lambda url: FEED.replace(b"</channel>", delta + b"</channel>"), now=3000)
    third = go(table3, store, cyclotron, now=3900, deliver=delivery)
    assert len(ti()) == 2 and third["status"] == "complete"
    park = table3.items[("MONITOR#hn", "PARK#threat-intelligence")]
    assert park["backoffSeconds"] == 3600 and park["probes"] == 1 and len(parked(table3, "threat-intelligence")) == 4
    # classifier ready: the next item's probe succeeds, then every parked item is decided
    cyclotron.post_override.clear()
    echo = b"<item><title>Echo source</title><link>https://example.org/echo</link><comments>https://news.ycombinator.com/item?id=105</comments></item>"
    run_collection(DynamoStore(table3), "hn", fetch=lambda url: FEED.replace(b"</channel>", delta + echo + b"</channel>"), now=7000)
    fourth = go(table3, store, cyclotron, now=8000, deliver=delivery)
    assert fourth["waitingForClassifier"] == [] and fourth["status"] == "complete"
    for n in range(1, 6):
        go(table3, store, cyclotron, now=8000 + 900 * n, deliver=delivery)
    assert {"101", "102", "103", "104", "105"} == {c[1] for c in delivery.calls if c[0] == "threat-intelligence"}
    assert ("MONITOR#hn", "PARK#threat-intelligence") not in table3.items


def many_stories(count, first=1000):
    items = "".join(f"<item><title>Story {n}</title><link>https://example.org/s{n}</link>"
                    f"<comments>https://news.ycombinator.com/item?id={n}</comments></item>" for n in range(first, first + count))
    return f"<rss><channel>{items}</channel></rss>".encode()


def test_more_than_25_parked_items_all_survive_and_are_backfilled_when_the_classifier_is_ready():
    table = collected_table(many_stories(40))
    table.page_size = 7                                   # DynamoDB answers a page at a time: the router must read them all
    store, cyclotron = setup_router(table)
    cyclotron.post_override["threat-intelligence"] = (409, {"detail": "publication criteria are pending"})
    delivery = Delivery()
    go(table, store, cyclotron, now=2000, deliver=delivery)
    assert len(parked(table, "threat-intelligence")) == 40       # nothing dropped: the old row kept the last 25
    assert not any("items" in v for k, v in table.items.items() if k[1].startswith("PARK#"))     # no row grows with the backlog

    cyclotron.post_override.clear()
    story = lambda n: f"<item><title>S{n}</title><link>https://example.org/s{n}</link><comments>https://news.ycombinator.com/item?id={n}</comments></item>".encode()
    run_collection(DynamoStore(table), "hn", fetch=lambda url: many_stories(40).replace(b"</channel>", story(2000) + b"</channel>"), now=7000)
    for n in range(12):
        go(table, store, cyclotron, now=8000 + 900 * n, deliver=delivery)
    expected = {str(n) for n in range(1000, 1040)} | {"2000"}
    assert expected == {c[1] for c in delivery.calls if c[0] == "threat-intelligence"}
    assert ("MONITOR#hn", "PARK#threat-intelligence") not in table.items and not parked(table, "threat-intelligence")


def test_a_park_row_written_with_its_items_inside_is_split_into_rows_when_read_and_keeps_every_item():
    table = collected_table(many_stories(3))
    store, cyclotron = setup_router(table)
    cyclotron.post_override["threat-intelligence"] = (409, {"detail": "publication criteria are pending"})
    go(table, store, cyclotron, now=2000)
    header = table.items[("MONITOR#hn", "PARK#threat-intelligence")]
    for key in [k for k in table.items if k[1].startswith("PARK#threat-intelligence#")]:
        del table.items[key]
    header["items"] = [{"sourceId": str(n), "revision": 1} for n in (1000, 1001, 1002)]        # the capped list of the old layout

    go(table, store, cyclotron, now=2300)                                                       # any run reads the park

    assert "items" not in table.items[("MONITOR#hn", "PARK#threat-intelligence")]
    assert [row["sourceId"] for row in parked(table, "threat-intelligence")] == ["1000", "1001", "1002"]


def test_unknown_409_skips_only_that_story_and_is_logged(table, caplog):
    store, cyclotron = setup_router(table)
    cyclotron.post_override["anth-us"] = (409, {"error": {"code": "something_else"}, "token": "SECRET"})
    with caplog.at_level("WARNING", logger="papyrus_content.monitoring_router"):
        result = go(table, store, cyclotron)
    assert result["status"] != "stopped" and result["stoppedBy"] is None
    assert "error" not in set(routing_of(table).values())   # not final: the story is retried later
    assert table.items[("MONITOR#hn", "ROUTE#101#000001")]["refusals"] == 1
    assert any("http 409" in e["message"] and "something_else" in e["message"] for e in result["errors"])
    assert "http 409" in caplog.text and "something_else" in caplog.text
    assert "SECRET" not in caplog.text and "SECRET" not in json.dumps(result["errors"])
    assert ("MONITOR#hn", "PARK#anth-us") not in table.items


def test_unknown_409_detail_is_truncated_to_300_characters():
    assert len(mr.body_excerpt(409, {"detail": "x" * 1000})) == 300
    assert mr.body_excerpt(502, {"detail": ["a", "b"]}) == 'http 502: detail=["a","b"]'
    assert mr.body_excerpt(500, "html") == "http 500: no detail"


def test_unknown_combined_409_continues_to_the_next_story(table):
    store, cyclotron = combined_setup(table)
    cyclotron.combined_post_override = (409, {"detail": "something odd"})
    result = go(table, store, cyclotron)
    assert result["stoppedBy"] is None and routing_of(table)["DISC#101#000001"] == "collected"
    assert any("something odd" in e["message"] for e in result["errors"])


def refused_route(table):
    return table.items[("MONITOR#hn", "ROUTE#101#000001")]


def test_unknown_409_backs_off_exponentially_is_retried_and_never_final(table):
    store, cyclotron = combined_setup(table)
    cyclotron.combined_post_override = (409, {"detail": "something odd"})
    waits = []
    for n, now in enumerate((2000, 2000 + 900, 2900 + 1800)):
        go(table, store, cyclotron, now=now)
        route = refused_route(table)
        waits.append(int(route["nextAttemptAt"]) - now)
        assert route["refusals"] == n + 1 and "final" not in route
        assert route["lastRefusal"]["message"].startswith("http 409") and "something odd" in route["lastRefusal"]["message"]
        assert routing_of(table)["DISC#101#000001"] == "collected"
    assert waits == [900, 1800, 3600]
    posts = len(post_ids(cyclotron))
    go(table, store, cyclotron, now=int(refused_route(table)["nextAttemptAt"]) - 1)   # still backing off: not asked
    assert len(post_ids(cyclotron)) == posts
    cyclotron.combined_post_override = None
    result = go(table, store, cyclotron, now=int(refused_route(table)["nextAttemptAt"]))
    assert result["status"] == "complete" and routing_of(table)["DISC#101#000001"] == "routed"
    assert len(set(post_ids(cyclotron))) == 1   # a refusal started nothing: the retry keeps the request identity


def test_the_backoff_is_capped_at_24_hours_and_has_no_limit_on_refusals(table):
    store, cyclotron = combined_setup(table)
    cyclotron.combined_post_override = (409, {"detail": "something odd"})
    go(table, store, cyclotron, now=2000)
    refused_route(table)["refusals"] = 40
    now = int(refused_route(table)["nextAttemptAt"])
    go(table, store, cyclotron, now=now)
    route = refused_route(table)
    assert route["refusals"] == 41 and "final" not in route
    assert int(route["nextAttemptAt"]) - now == mr.REFUSAL_BACKOFF_MAX == 24 * 3600


def test_a_backed_off_story_does_not_hold_back_the_other_stories(table3):
    store, cyclotron = combined_setup(table3)
    cyclotron.combined_post_queue = [(409, {"detail": "something odd"})]
    result = go(table3, store, cyclotron)
    assert result["stoppedBy"] is None
    states = routing_of(table3)
    assert list(states.values()).count("collected") == 1 and "routed" in states.values() and "error" not in states.values()


def test_other_definite_4xx_refusals_back_off_but_400_and_422_stay_final(table):
    store, cyclotron = setup_router(table)
    cyclotron.post_override["anth-us"] = (410, {"detail": "gone for now"})
    go(table, store, cyclotron)
    assert routing_of(table)["DISC#101#000001"] == "collected" and refused_route(table)["refusals"] == 1
    cyclotron.post_override["anth-us"] = (422, {"detail": "bad"})
    go(table, store, cyclotron, now=int(refused_route(table)["nextAttemptAt"]))
    assert routing_of(table)["DISC#101#000001"] == "error"


def test_ceiling_refusals_still_stop_the_sweep(table):
    store, cyclotron = setup_router(table)
    cyclotron.post_override["anth-us"] = (507, {"code": "standing_capacity_reached"})
    result = go(table, store, cyclotron)
    assert result["status"] == "stopped" and result["stoppedBy"] == "standing_capacity_reached"


def test_typed_criteria_pending_code_is_also_not_ready(table):
    store, cyclotron = setup_router(table)
    cyclotron.post_override["anth-us"] = (409, {"error": {"code": "criteria_pending"}})
    assert go(table, store, cyclotron)["waitingForClassifier"] == ["anth-us"]


def test_all_bindings_not_ready_parks_the_item_without_looping(table3):
    store, cyclotron = setup_router(table3)
    for pub in PUBS:
        cyclotron.post_override[pub] = (409, {"code": "criteria_pending"})
    result = go(table3, store, cyclotron)
    assert result["status"] == "complete" and result["counts"]["parked"] == 3
    assert sorted(result["waitingForClassifier"]) == sorted(PUBS)
    assert set(routing_of(table3).values()) == {"parked"}


def test_resumed_route_with_a_stored_confidence_saves_without_float_errors(table):
    """A sweep that stops mid-item leaves checked jobs with confidence; the next run reads them back as floats."""
    store, cyclotron = setup_router(table)
    cyclotron.confidence.update({("hn-101", p): 0.55 for p in PUBS})
    cyclotron.post_override["threat-intelligence"] = (429, {"code": "rate_limited"})
    stopped = go(table, store, cyclotron, now=2000)
    assert stopped["status"] == "stopped"
    cyclotron.post_override.clear()
    resumed = go(table, store, cyclotron, now=2900)
    assert resumed["status"] == "complete" and resumed["errors"] == []
    assert table.items[("MONITOR#hn", "ROUTE#101#000001")]["decision"]["publications"]["anth-us"]["confidence"] == Decimal("0.55")


# --- lab decisions become relevance_decision_is relations (PPY-e987f2) -----------------------------------------

class LabAppSync:
    """An in-memory AppSync client for the real ReferenceIntake: records every operation it is asked to make."""

    tenant_id = None

    def __init__(self, endpoint, corpus_id):
        self.endpoint, self.corpus_id = endpoint, corpus_id
        self.rows, self.ops = {}, []

    def list_records(self, model):
        self.ops.append(("list", model))
        if model == "KnowledgeCorpus":
            return [{"id": self.corpus_id, "role": "canonical"}]
        return [dict(r) for (m, _), r in self.rows.items() if m == model]

    def get_record(self, model, record_id):
        self.ops.append(("get", model))
        row = self.rows.get((model, record_id))
        return dict(row) if row else None

    def create_record(self, model, payload):
        self.ops.append(("create", model, payload.get("predicate")))
        if (model, payload["id"]) in self.rows:
            raise RuntimeError("ConditionalCheckFailed")
        json.dumps(payload)    # AppSync takes JSON: a Decimal anywhere in a write fails here
        self.rows[(model, payload["id"])] = dict(payload)

    def update_record(self, model, payload):
        self.ops.append(("update", model, payload.get("predicate")))
        json.dumps(payload)
        self.rows[(model, payload["id"])] = dict(payload)

    def list_by_index(self, index, key):
        self.ops.append(("index", index))
        return [dict(r) for (m, _), r in self.rows.items() if m == "SemanticRelation" and r.get("subjectStateKey") == key]

    def relations(self, state="current"):
        return [r for (m, _), r in self.rows.items() if m == "SemanticRelation" and r["predicate"] == "relevance_decision_is"
                and r["relationState"] == state]

    def writes(self):
        return [op for op in self.ops if op[0] in ("create", "update")]


@pytest.fixture
def lab(table, monkeypatch):
    monkeypatch.setattr("papyrus_content.records.upload_attachment_body", lambda client, expected, body: None)
    store, cyclotron = setup_router(table)
    clients = {}

    def appsync(endpoint):
        config = validate_router_config(table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"])
        pub = next(p for p in config["publications"] if p["appsyncEndpoint"] == endpoint)
        return clients.setdefault(pub["publicationId"], LabAppSync(endpoint, pub["corpusId"]))

    def run(now=2000, **kwargs):
        return go(table, store, cyclotron, now=now, deliver=mr.deliver_reference, appsync=appsync, **kwargs)

    return type("Lab", (), {"table": table, "store": store, "cyclotron": cyclotron, "clients": clients, "run": staticmethod(run)})


def test_delivery_writes_one_current_relation_with_the_lab_metadata(lab):
    lab.cyclotron.confidence = {("hn-101", "anth-us"): 0.91234}
    lab.cyclotron.labels = {("hn-101", "p-apyr-us"): "exclude"}
    result = lab.run()
    assert result["status"] == "complete" and result["counts"]["delivered"] == 2 and result["counts"]["deliveryFailed"] == 0
    client = lab.clients["anth-us"]
    (relation,) = client.relations()
    reference = next(r for (m, _), r in client.rows.items() if m == "Reference")
    assert (relation["subjectKind"], relation["subjectId"], relation["subjectLineageId"]) == (
        "reference", reference["id"], reference["lineageId"])
    assert relation["objectLineageId"] == "semantic-node-relevance-include" and relation["rank"] == 1
    assert relation["classifierId"] == "anth-us-relevance/anth-us-relevance" and relation["modelVersion"] == "3"
    assert relation["confidence"] == 0.9123 and relation["reviewRecommended"] is False
    metadata = json.loads(relation["metadata"])
    assert metadata["cyclotronId"] == "anth-us-relevance" and metadata["classifier"] == "anth-us-relevance"
    assert metadata["decisionId"] == "dec-hn-101" and metadata["label"] == "include" and metadata["version"] == 3
    assert metadata["fingerprint"] == "fp-anth-us" and metadata["labels"] == ["include", "exclude"]
    assert metadata["positiveLabel"] == "include" and metadata["reviewControl"] == "thumbs"
    assert metadata["provenance"] == {
        "system": "cyclotron-lab", "accountId": "acct-1", "runId": "run-1", "bindingRevision": "1",
        "publicationId": "anth-us", "output": "anth-us-relevance", "decisionId": "dec-hn-101", "fingerprint": "fp-anth-us",
        "version": 3, "labelSet": ["include", "exclude"], "sourceId": "101"}
    assert ("SemanticNode", "semantic-node-relevance-include-v1") in client.rows
    assert "p-apyr-us" not in lab.clients      # an exclude decision delivers nothing, so no suggestion either


def test_each_publication_gets_its_own_relation_naming_its_own_lab_output(lab):
    lab.run()
    assert {p: json.loads(lab.clients[p].relations()[0]["metadata"])["cyclotronId"] for p in PUBS} == {
        p: f"{p}-relevance" for p in PUBS}


def redeliver(lab, pub, **receipt_changes):
    """Call the real deliver_reference again for item 101, with the stored discovery and the stored decision receipt."""
    config = validate_router_config(lab.table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"])
    publication = next(p for p in config["publications"] if p["publicationId"] == pub)
    disc = lab.store.get_any("hn", "DISC#101#000001")
    decision = lab.store.get_any("hn", "ROUTE#101#000001")["decision"]
    receipt = {"decisionId": decision["decisionId"], "decidedAt": decision["decidedAt"], **decision["publications"][pub],
               **receipt_changes}
    return mr.deliver_reference(lab.clients[pub], publication, disc, receipt, config)


def test_redelivering_the_same_decision_writes_nothing_new(lab):
    lab.run()
    client = lab.clients["anth-us"]
    before = dict(client.rows)
    client.ops.clear()
    result = redeliver(lab, "anth-us")
    assert result["referenceId"] == next(r["id"] for (m, _), r in before.items() if m == "Reference")
    assert client.rows == before and not client.writes()
    assert len(client.relations()) == 1 and not client.relations("superseded")


def test_a_changed_decision_supersedes_the_old_relation_in_the_same_batch(lab):
    lab.run()
    client = lab.clients["anth-us"]
    (first,) = client.relations()
    client.ops.clear()
    redeliver(lab, "anth-us", decisionId="dec-hn-101-v2", decidedAt="2026-10-22T02:00:00Z", fingerprint="fp-new", version=4,
              confidence=Decimal("0.62"))
    (second,) = client.relations()
    assert second["id"] != first["id"] and json.loads(second["metadata"])["decisionId"] == "dec-hn-101-v2"
    assert second["confidence"] == 0.62 and second["modelVersion"] == "4"
    assert [r["id"] for r in client.relations("superseded")] == [first["id"]]
    from papyrus_content.relevance_decisions import current_relevance_decision
    current = current_relevance_decision([r for (m, _), r in client.rows.items() if m == "SemanticRelation"], first["subjectLineageId"])
    assert current["id"] == second["id"]    # does not raise: exactly one current


def test_a_sweep_relation_for_the_reference_is_superseded_by_the_lab_decision(lab):
    lab.run()
    client = lab.clients["anth-us"]
    (lab_first,) = client.relations()
    # a Mac-sweep relation that was current for the same Reference (as the references tab saw it before the lab delivered)
    sweep = {**lab_first, "id": "semantic-relation-sweep", "classifierId": "papyrus-relevance/relevance", "modelVersion": "9",
             "metadata": json.dumps({"decisionId": "sweep-1", "cyclotronId": "papyrus-relevance"})}
    client.rows[("SemanticRelation", sweep["id"])] = sweep
    del client.rows[("SemanticRelation", lab_first["id"])]
    redeliver(lab, "anth-us")
    assert [json.loads(r["metadata"])["decisionId"] for r in client.relations()] == ["dec-hn-101"]
    assert [r["id"] for r in client.relations("superseded")] == ["semantic-relation-sweep"]


def test_the_relation_adds_a_bounded_number_of_operations_and_no_cyclotron_calls(lab):
    lab.run()
    client = lab.clients["anth-us"]
    reads = [op for op in client.ops if op[0] == "index"]
    assert len(reads) == 1                                     # one query per delivered item, no whole-table list for relations
    assert ("list", "SemanticRelation") not in client.ops and ("list", "SemanticNode") not in client.ops
    decision_writes = [op for op in client.writes() if op[1] == "SemanticNode" or op[2] == "relevance_decision_is"]
    assert sorted(decision_writes) == [("create", "SemanticNode", None), ("create", "SemanticRelation", "relevance_decision_is")]
    assert len(lab.cyclotron.posts()) == 3                     # unchanged: one decide per binding, nothing for the relation


def test_a_parked_binding_gets_no_relation_and_the_others_still_do(lab):
    lab.cyclotron.post_override["threat-intelligence"] = (409, {"detail": "publication criteria are pending"})
    result = lab.run()
    assert result["status"] == "complete" and result["waitingForClassifier"] == ["threat-intelligence"]
    assert ("MONITOR#hn", "PARK#threat-intelligence") in lab.table.items
    assert len(lab.clients["anth-us"].relations()) == 1 and len(lab.clients["p-apyr-us"].relations()) == 1
    assert "threat-intelligence" not in lab.clients or not lab.clients["threat-intelligence"].relations()


def test_relation_confidence_is_json_safe_while_the_route_keeps_a_decimal(lab):
    lab.cyclotron.confidence = {("hn-101", p): 0.55 for p in PUBS}
    lab.cyclotron.post_override["threat-intelligence"] = (429, {"code": "rate_limited"})
    assert lab.run()["status"] == "stopped"
    lab.cyclotron.post_override.clear()
    resumed = lab.run(now=2900)               # confidence comes back from the table as a float, then a write must still serialise
    assert resumed["status"] == "complete" and resumed["errors"] == [] and resumed["counts"]["deliveryFailed"] == 0
    assert table_confidence(lab) == Decimal("0.55")
    assert [r["confidence"] for r in lab.clients["anth-us"].relations()] == [0.55]


def table_confidence(lab):
    return lab.table.items[("MONITOR#hn", "ROUTE#101#000001")]["decision"]["publications"]["anth-us"]["confidence"]


def test_a_direct_monitor_writes_no_decision_relation(lab):
    lab.table.put_item(router_config(decisions="direct", cyclotron=None))
    mr_result = go(lab.table, lab.store, None, now=2000, deliver=mr.deliver_reference,
                   appsync=lambda endpoint: lab.clients.setdefault(endpoint, LabAppSync(endpoint, "knowledge-corpus-" + (
                       "ai-ml-research" if "api1" in endpoint else "anth-us" if "api0" in endpoint else "threat-intelligence"))))
    assert mr_result["counts"]["delivered"] == 3
    assert not any(c.relations() for c in lab.clients.values())


# --- one combined machine request per story (POST /machine/decisions) --------------------------------------

def combined_setup(table, **config):
    store, cyclotron = setup_router(table, **config)
    cyclotron.combined_enabled = True
    return store, cyclotron


def test_combined_request_has_the_exact_contract_shape_and_a_stable_id(table):
    config = validate_router_config(router_config())
    disc = table.items[("MONITOR#hn", "DISC#101#000001")]
    built = mr.build_combined_request(config, config["publications"], disc)
    body = built["body"]
    assert built["path"] == "/machine/decisions"
    assert set(body) == {"contractVersion", "requestId", "payload"} and body["contractVersion"] == "cyclotron-publication/v1"
    assert body["payload"]["bindings"] == {p: "1" for p in sorted(PUBS)}
    assert body["payload"]["item"]["id"] == "hn-101" and "operation" not in body
    assert 8 <= len(body["requestId"]) <= 128 and mr.re.fullmatch(r"[A-Za-z0-9._:-]+", body["requestId"])
    assert body["requestId"] == mr.build_combined_request(config, config["publications"][::-1], disc)["body"]["requestId"]
    assert body["requestId"] != mr.build_combined_request(config, config["publications"][:2], disc)["body"]["requestId"]
    assert body["requestId"] != mr.build_combined_request(config, config["publications"], disc, 1)["body"]["requestId"]
    assert body["requestId"] == mr.build_combined_request(config, config["publications"], {**disc, "revision": 2})["body"]["requestId"]
    assert body["requestId"] != mr.build_combined_request(config, config["publications"], {**disc, "title": "Changed"})["body"]["requestId"]


def test_combined_success_is_one_post_one_poll_and_the_receipt_matches_the_per_publication_shape(table):
    store, cyclotron = combined_setup(table)
    cyclotron.labels = {("hn-101", "p-apyr-us"): "exclude"}
    delivery = Delivery()
    result = go(table, store, cyclotron, deliver=delivery)
    assert result["status"] == "complete" and result["counts"]["decided"] == 1 and result["counts"]["routed"] == 1
    assert cyclotron.calls == []                                   # no per-publication job at all
    assert [c[0] for c in cyclotron.combined_calls] == ["POST", "GET"]
    assert cyclotron.combined_calls[0][2]["payload"]["bindings"] == {p: "1" for p in sorted(PUBS)}
    route = table.items[("MONITOR#hn", "ROUTE#101#000001")]
    assert "combinedJob" not in route and set(route["jobs"]) == set(PUBS)
    assert route["jobs"]["anth-us"]["checked"] == {
        "decisionId": "dec-hn-101", "output": "anth-us-relevance", "label": "include", "fingerprint": "fp-anth-us",
        "version": 3, "source": {"id": "hn-101", "revision": 2, "fingerprint": "sfp"}}
    assert route["decision"]["publications"]["p-apyr-us"]["label"] == "exclude"
    assert sorted(c[0] for c in delivery.calls) == ["anth-us", "threat-intelligence"]
    # the same story decided publication by publication yields the identical receipt
    other = FakeTable()
    other.put_item(COLLECTOR_CONFIG)
    run_collection(DynamoStore(other), "hn", fetch=lambda url: FEED, now=1000)
    store2, single = setup_router(other)
    single.labels = cyclotron.labels
    go(other, store2, single)
    again = other.items[("MONITOR#hn", "ROUTE#101#000001")]
    assert again["decision"]["publications"] == route["decision"]["publications"]
    assert {p: j["checked"] for p, j in again["jobs"].items()} == {p: j["checked"] for p, j in route["jobs"].items()}


def test_combined_confidence_and_all_stories_use_one_job_each(table3):
    store, cyclotron = combined_setup(table3)
    cyclotron.confidence = {("hn-101", "anth-us"): 0.91234}
    go(table3, store, cyclotron)
    assert len([c for c in cyclotron.combined_calls if c[0] == "POST"]) == 3 and cyclotron.calls == []
    assert table3.items[("MONITOR#hn", "ROUTE#101#000001")]["jobs"]["anth-us"]["checked"]["confidence"] == Decimal("0.9123")


def test_a_404_falls_back_to_per_publication_jobs_and_is_cached_for_the_run(table3):
    store, cyclotron = setup_router(table3)       # combined_enabled is False: the endpoint is 404
    result = go(table3, store, cyclotron)
    assert result["status"] == "complete" and result["counts"]["routed"] == 3
    assert [c[0] for c in cyclotron.combined_calls] == ["POST"]    # asked once; the 404 is remembered for the run
    assert len(cyclotron.posts()) == 9
    assert ("MONITOR#hn", "ROUTE#101#000001") in table3.items and "combinedJob" not in table3.items[("MONITOR#hn", "ROUTE#101#000001")]


def test_combined_409_binding_changed_stops_the_sweep_and_a_later_run_reposts(table):
    store, cyclotron = combined_setup(table)
    cyclotron.combined_post_override = (409, {"detail": "publication binding changed"})
    result = go(table, store, cyclotron)
    assert result["status"] == "stopped" and result["stoppedBy"] == "binding_changed"
    assert set(routing_of(table).values()) == {"collected"} and cyclotron.calls == []
    assert "combinedJob" not in table.items[("MONITOR#hn", "ROUTE#101#000001")]
    cyclotron.combined_post_override = None
    go(table, store, cyclotron, now=3000)
    assert routing_of(table)["DISC#101#000001"] == "routed"


def test_combined_pending_output_409_decides_per_publication_for_that_story(table):
    store, cyclotron = combined_setup(table)
    cyclotron.combined_post_override = (409, {"detail": "publication criteria are pending"})
    cyclotron.post_override["threat-intelligence"] = (409, {"detail": "publication criteria are pending"})
    result = go(table, store, cyclotron)
    assert result["status"] == "complete" and result["waitingForClassifier"] == ["threat-intelligence"]
    assert result["counts"]["decided"] == 1 and result["counts"]["skippedNotReady"] == 1
    assert set(table.items[("MONITOR#hn", "ROUTE#101#000001")]["decision"]["publications"]) == {"anth-us", "p-apyr-us"}


@pytest.mark.parametrize("where", ["post", "poll"])
def test_combined_run_busy_defers_without_repeating_the_post(table, where):
    store, cyclotron = combined_setup(table)
    override = (409, {"code": "run_busy"})
    if where == "post":
        cyclotron.combined_post_override = override
    else:
        cyclotron.combined_poll_override = override
    result = go(table, store, cyclotron)
    assert result["status"] == "stopped" and result["stoppedBy"] == "run_busy"
    assert set(routing_of(table).values()) == {"collected"}
    route = table.items[("MONITOR#hn", "ROUTE#101#000001")]
    assert ("combinedJob" in route) == (where == "poll")           # a refused POST may be sent again; an accepted job is polled
    cyclotron.combined_post_override = cyclotron.combined_poll_override = None
    go(table, store, cyclotron, now=3000)
    ids = [c[2]["requestId"] for c in cyclotron.combined_calls if c[0] == "POST" and c[2]["payload"]["item"]["id"] == "hn-101"]
    assert len(ids) == (2 if where == "post" else 1) and len(set(ids)) == 1
    assert routing_of(table)["DISC#101#000001"] == "routed"


def post_ids(cyclotron, item="hn-101"):
    return [c[2]["requestId"] for c in cyclotron.combined_calls if c[0] == "POST" and c[2]["payload"]["item"]["id"] == item]


def test_combined_job_records_the_run_and_binding_it_was_posted_under(table):
    store, cyclotron = combined_setup(table)
    cyclotron.pending_polls = 1
    assert go(table, store, cyclotron)["status"] in ("awaiting", "complete")
    route = table.items[("MONITOR#hn", "ROUTE#101#000001")]
    holder = route.get("combinedJob") or next(iter(route["jobs"].values()))
    assert (holder["runId"], holder["bindingRevision"]) == ("run-1", "1")


def leave_job_pending(table, store, cyclotron):
    """Run once against a lab that never finishes, so the story keeps its recorded job."""
    cyclotron.pending_polls = 10_000
    state = {"t": 0}
    config = validate_router_config(table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"])
    ticking = CyclotronClient(config, sign=lambda m, u, b: {}, http=cyclotron.http,
                              sleep=lambda s: state.__setitem__("t", state["t"] + s), clock=lambda: state["t"])
    result = run_router(store, "hn", now=2000, cyclotron=ticking, appsync=lambda e: object(), deliver=Delivery(),
                        context_receipt=lambda c, p: {})
    assert routing_of(table)["DISC#101#000001"] == "collected"
    return result


def stale_combined_job(table, store, cyclotron, **marker):
    """Leave the story holding a real combined job, then rewrite it as posted under another run / binding."""
    leave_job_pending(table, store, cyclotron)
    job = table.items[("MONITOR#hn", "ROUTE#101#000001")]["combinedJob"]
    for key in ("runId", "bindingRevision"):
        job.pop(key, None)
    job.update(marker)
    if not marker:
        job["requestId"] = "stale-request-id-0"
    cyclotron.pending_polls, cyclotron.combined_calls = 0, []
    return job["jobId"]


@pytest.mark.parametrize("marker", [{"runId": "run-0", "bindingRevision": "0"}, {"runId": "run-1", "bindingRevision": "0"}, {}])
def test_a_stored_combined_job_from_an_earlier_run_or_id_is_polled_and_collected_without_a_new_post(table, marker):
    store, cyclotron = combined_setup(table)
    old = stale_combined_job(table, store, cyclotron, **marker)
    result = go(table, store, cyclotron, now=2100)
    assert result["status"] == "complete" and routing_of(table)["DISC#101#000001"] == "routed"
    assert any(c[0] == "GET" and c[1].endswith(old) for c in cyclotron.combined_calls)
    assert post_ids(cyclotron) == []


def test_a_stored_pending_combined_job_is_never_posted_behind(table):
    store, cyclotron = combined_setup(table)
    stale_combined_job(table, store, cyclotron)
    cyclotron.pending_polls = 10_000
    go(table, store, cyclotron, now=2100)
    go(table, store, cyclotron, now=2200)
    assert post_ids(cyclotron) == [] and routing_of(table)["DISC#101#000001"] == "collected"


def test_a_failed_combined_job_is_reposted_once_under_a_new_id(table):
    store, cyclotron = combined_setup(table)
    old = stale_combined_job(table, store, cyclotron)
    cyclotron.combined_poll_queue = [(200, {"status": "failed"})]
    result = go(table, store, cyclotron, now=2100)
    assert result["status"] == "complete" and routing_of(table)["DISC#101#000001"] == "routed"
    ids = post_ids(cyclotron)
    assert len(ids) == 1 and ids[0] != "stale-request-id-0"
    assert any(c[0] == "GET" and c[1].endswith(old) for c in cyclotron.combined_calls)


def test_a_combined_job_that_fails_again_after_the_repost_errors_the_story(table):
    store, cyclotron = combined_setup(table)
    stale_combined_job(table, store, cyclotron)
    cyclotron.combined_poll_override = (200, {"status": "failed"})
    go(table, store, cyclotron, now=2100)
    assert len(post_ids(cyclotron)) == 1 and routing_of(table)["DISC#101#000001"] == "error"


def test_combined_jobs_are_marked_and_never_polled_on_the_per_publication_route(table):
    store, cyclotron = combined_setup(table)
    go(table, store, cyclotron)
    route = table.items[("MONITOR#hn", "ROUTE#101#000001")]
    assert {j["via"] for j in route["jobs"].values()} == {"decisions"}
    assert not [c for c in cyclotron.calls if c[0] == "GET"]          # no GET on /machine/publications/*/commands/*


def test_a_combined_job_entry_without_a_receipt_is_polled_via_decisions_not_commands(table):
    store, cyclotron = combined_setup(table)
    leave_job_pending(table, store, cyclotron)
    route = table.items[("MONITOR#hn", "ROUTE#101#000001")]
    job_id = route["combinedJob"]["jobId"]
    route["jobs"] = {"anth-us": {"requestId": "r", "postedAt": 1500, "jobId": job_id, "via": "decisions"}}
    del route["combinedJob"]
    cfg = router_config()
    cfg["publications"] = cfg["publications"][:1]          # one publication: the per-publication path handles it
    table.put_item(cfg)
    cyclotron.pending_polls, cyclotron.calls, cyclotron.combined_calls = 0, [], []
    go(table, store, cyclotron, now=2100)
    assert not [c for c in cyclotron.calls if c[0] == "GET" and job_id in c[1]]
    assert any(c[0] == "GET" and c[1].endswith(job_id) for c in cyclotron.combined_calls)


def test_job_via_infers_decisions_for_legacy_entries_matching_the_combined_job():
    from papyrus_content.monitoring_router import job_via
    route = {"combinedJob": {"jobId": "cjob-0"}}
    assert job_via(route, {"jobId": "cjob-0"}) == "decisions"
    assert job_via(route, {"jobId": "job-x"}) == "publication"
    assert job_via({}, {"jobId": "cjob-0"}) == "publication"
    assert job_via(route, {"jobId": "cjob-0", "via": "publication"}) == "publication"


def test_a_404_on_a_stored_combined_job_reposts_once_in_the_same_run(table):
    store, cyclotron = combined_setup(table)
    stale_combined_job(table, store, cyclotron, runId="run-1", bindingRevision="1")
    cyclotron.combined_poll_queue = [(404, {"detail": "Not Found"})]
    result = go(table, store, cyclotron, now=2100)
    assert result["status"] == "complete" and routing_of(table)["DISC#101#000001"] == "routed"
    assert len(post_ids(cyclotron)) == 1


def test_a_repeated_404_errors_only_that_story_and_the_run_continues(table3):
    store, cyclotron = combined_setup(table3)
    cyclotron.combined_poll_queue = [(404, {"detail": "Not Found"}), (404, {"detail": "Not Found"})]
    result = go(table3, store, cyclotron)
    assert result["status"] == "complete" and not result.get("stoppedBy")
    assert len(post_ids(cyclotron)) + len(post_ids(cyclotron, "hn-102")) == 3   # first story twice, the next story once
    states = routing_of(table3)
    assert sorted(states.values()).count("error") == 1 and "routed" in states.values()


def test_a_404_on_a_stored_single_publication_job_reposts_once_and_a_repeat_errors_the_story(table):
    store, cyclotron = setup_router(table)
    cyclotron.poll_override["p-apyr-us"] = (404, {"detail": "Not Found"})
    result = go(table, store, cyclotron)
    assert result["status"] == "complete" and not result.get("stoppedBy")
    assert routing_of(table)["DISC#101#000001"] == "error"
    assert len([c for c in cyclotron.posts() if c[1].split("/")[3] == "p-apyr-us"]) == 2   # posted, then re-posted once


def test_a_single_publication_job_from_an_earlier_run_is_still_polled_and_collected(table):
    store, cyclotron = setup_router(table)
    leave_job_pending(table, store, cyclotron)
    route = table.items[("MONITOR#hn", "ROUTE#101#000001")]
    old = route["jobs"]["anth-us"]["jobId"]
    route["jobs"]["anth-us"].update(runId="run-0", bindingRevision="0")
    cyclotron.pending_polls, cyclotron.calls = 0, []
    result = go(table, store, cyclotron, now=2100)
    assert result["status"] == "complete" and routing_of(table)["DISC#101#000001"] == "routed"
    assert any(c[0] == "GET" and c[1].endswith(old) for c in cyclotron.calls)
    assert [c for c in cyclotron.posts() if c[1].split("/")[3] == "anth-us"] == []


def test_combined_503_provider_key_unavailable_retries_under_a_new_request_id(table):
    store, cyclotron = combined_setup(table)
    cyclotron.combined_poll_override = (503, {"code": "provider_key_unavailable"})
    result = go(table, store, cyclotron)
    assert result["stoppedBy"] == "provider_key_unavailable"
    route = table.items[("MONITOR#hn", "ROUTE#101#000001")]
    assert route["attempt"] == 1 and "combinedJob" not in route
    cyclotron.combined_poll_override = None
    go(table, store, cyclotron, now=3000)
    ids = [c[2]["requestId"] for c in cyclotron.combined_calls if c[0] == "POST" and c[2]["payload"]["item"]["id"] == "hn-101"]
    assert len(ids) == 2 and ids[0] != ids[1]


def test_combined_pending_job_is_resumed_by_polling_only(table):
    store, cyclotron = combined_setup(table)
    cyclotron.pending_polls = 10_000
    state = {"t": 0}
    config = validate_router_config(table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"])
    ticking = CyclotronClient(config, sign=lambda m, u, b: {}, http=cyclotron.http,
                              sleep=lambda s: state.__setitem__("t", state["t"] + s), clock=lambda: state["t"])
    result = run_router(store, "hn", now=2000, cyclotron=ticking, appsync=lambda e: object(), deliver=Delivery(),
                        context_receipt=lambda c, p: {})
    assert result["status"] == "awaiting" and routing_of(table)["DISC#101#000001"] == "collected"
    assert table.items[("MONITOR#hn", "ROUTE#101#000001")]["combinedJob"]["jobId"] == "cjob-0"
    cyclotron.pending_polls = 0
    go(table, store, cyclotron, now=2600)
    assert len([c for c in cyclotron.combined_calls if c[0] == "POST"]) == 1
    assert routing_of(table)["DISC#101#000001"] == "routed"


def test_a_pending_publication_inside_a_completed_receipt_is_parked_and_the_others_decided(table):
    store, cyclotron = combined_setup(table)
    cyclotron.combined_entry_override["threat-intelligence"] = {"status": 409, "detail": "publication criteria are pending"}
    result = go(table, store, cyclotron)
    assert result["status"] == "complete" and result["waitingForClassifier"] == ["threat-intelligence"]
    route = table.items[("MONITOR#hn", "ROUTE#101#000001")]
    assert set(route["decision"]["publications"]) == {"anth-us", "p-apyr-us"} and "threat-intelligence" in route["notReady"]
    assert routing_of(table)["DISC#101#000001"] == "routed"


def test_a_typed_criteria_pending_entry_is_also_not_ready(table):
    store, cyclotron = combined_setup(table)
    cyclotron.combined_entry_override["anth-us"] = {"error": {"code": "criteria_pending"}}
    assert go(table, store, cyclotron)["waitingForClassifier"] == ["anth-us"]


def test_a_source_refusal_inside_the_receipt_refuses_the_story_and_keeps_the_other_receipts(table):
    store, cyclotron = combined_setup(table)
    cyclotron.combined_entry_override["p-apyr-us"] = {"status": 409, "code": "source_refused"}
    go(table, store, cyclotron)
    assert routing_of(table)["DISC#101#000001"] == "refused"
    route = table.items[("MONITOR#hn", "ROUTE#101#000001")]
    assert route["final"]["reason"] == "source_refused" and "combinedJob" not in route
    assert {p for p, j in route["jobs"].items() if j.get("checked")} == {"anth-us", "threat-intelligence"}


def test_a_stop_code_inside_the_receipt_stops_the_sweep(table):
    store, cyclotron = combined_setup(table)
    cyclotron.combined_entry_override["anth-us"] = {"status": 429, "code": "request_ceiling_reached"}
    result = go(table, store, cyclotron)
    assert result["stoppedBy"] == "request_ceiling_reached" and set(routing_of(table).values()) == {"collected"}
    assert table.items[("MONITOR#hn", "ROUTE#101#000001")]["attempt"] == 1


def test_a_receipt_that_leaves_a_publication_out_is_completed_per_publication(table):
    store, cyclotron = combined_setup(table)
    original = cyclotron.combined

    def drop(method, path, data):
        status, body = original(method, path, data)
        if method == "GET" and status == 200:
            body["publications"].pop("anth-us")
        return status, body
    cyclotron.combined = drop
    go(table, store, cyclotron)
    assert routing_of(table)["DISC#101#000001"] == "routed"
    assert [c[1].split("/")[3] for c in cyclotron.posts()] == ["anth-us"]


def test_combined_response_for_another_account_is_an_error(table):
    store, cyclotron = combined_setup(table)
    original = cyclotron.combined

    def foreign(method, path, data):
        status, body = original(method, path, data)
        return status, {**body, "accountId": "other"} if method == "GET" and status == 200 else body
    cyclotron.combined = foreign
    go(table, store, cyclotron)
    assert routing_of(table)["DISC#101#000001"] == "error"


def test_dry_run_records_the_combined_request_the_live_run_sends(table):
    store, cyclotron = combined_setup(table, mode="dry-run")
    go(table, store, None)
    dry = table.items[("MONITOR#hn", "ROUTE#101#000001")]["dryRun"]["combined"]
    assert dry["path"] == "/machine/decisions" and dry["requestId"] == dry["body"]["requestId"]
    table.put_item(router_config("live"))
    go(table, store, cyclotron, now=3000)
    assert [c[2]["requestId"] for c in cyclotron.combined_calls if c[0] == "POST"] == [dry["requestId"]]


# --- post first, then collect --------------------------------------------------------------------------

def ticking_client(table, cyclotron):
    state = {"t": 0}
    config = validate_router_config(table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"])
    return CyclotronClient(config, sign=lambda m, u, b: {}, http=cyclotron.http,
                           sleep=lambda s: state.__setitem__("t", state["t"] + s), clock=lambda: state["t"])


def run_with(table, store, cyclotron, now=2000, deliver=None, **kwargs):
    return run_router(store, "hn", now=now, cyclotron=ticking_client(table, cyclotron), appsync=lambda e: object(),
                      deliver=deliver or Delivery(), context_receipt=lambda c, p: {}, **kwargs)


def combined_posts(cyclotron):
    return [c for c in cyclotron.combined_calls if c[0] == "POST"]


def test_slow_jobs_for_several_stories_are_all_posted_in_one_run(table3):
    store, cyclotron = combined_setup(table3)
    cyclotron.polls_needed = 10_000
    result = run_with(table3, store, cyclotron)
    assert len(combined_posts(cyclotron)) == 3
    assert result["status"] == "awaiting" and result["stoppedBy"] == "awaiting" and result["counts"]["awaiting"] == 3
    assert result["counts"]["examined"] == 3 and result["counts"]["routed"] == 0
    assert set(routing_of(table3).values()) == {"collected"}
    for n in (101, 102, 103):
        assert table3.items[("MONITOR#hn", f"ROUTE#{n}#000001")]["combinedJob"]["jobId"]
    receipt = next(v for k, v in table3.items.items() if k[1].startswith("ROUTERUN#"))
    assert receipt["stoppedBy"] == "awaiting" and receipt["counts"]["awaiting"] == 3


def test_jobs_that_finish_inside_the_collect_window_are_delivered_in_the_same_run(table3):
    store, cyclotron = combined_setup(table3)
    table3.items[("MONITOR#hn", "CONFIG#router")]["cyclotron"]["maxRequestsPerSecond"] = 1000   # pacing would eat the 10 s window
    cyclotron.polls_needed = 3          # running for the first check and the first two collect rounds
    delivery = Delivery()
    result = run_with(table3, store, cyclotron, deliver=delivery)
    assert result["status"] == "complete" and result["stoppedBy"] is None and result["counts"]["awaiting"] == 0
    assert set(routing_of(table3).values()) == {"routed"} and result["counts"]["routed"] == 3
    assert len(delivery.calls) == 9 and len(combined_posts(cyclotron)) == 3


def test_the_collect_window_is_bounded_by_poll_seconds(table):
    store, cyclotron = combined_setup(table)
    cyclotron.polls_needed = 10_000
    run_with(table, store, cyclotron)
    gets = [c for c in cyclotron.combined_calls if c[0] == "GET"]
    assert 1 < len(gets) <= 6           # pollSeconds is 10: a few backed-off rounds, not a busy wait


def test_a_job_still_running_at_run_end_is_resumed_by_the_collector_without_a_second_post(table3):
    store, cyclotron = combined_setup(table3)
    cyclotron.polls_needed = 10_000
    run_with(table3, store, cyclotron)
    assert len(combined_posts(cyclotron)) == 3 and set(routing_of(table3).values()) == {"collected"}
    cyclotron.polls_needed = 0
    delivery = Delivery()
    result = run_with(table3, store, cyclotron, now=2120, task="collect", deliver=delivery)
    assert result["status"] == "complete" and result["counts"]["routed"] == 3
    assert set(routing_of(table3).values()) == {"routed"}
    assert len(delivery.calls) == 9
    assert len(combined_posts(cyclotron)) == 3 and result["feedback"] == {"status": "skipped"}


def test_the_collector_never_posts_a_story_that_has_no_job(table3):
    store, cyclotron = combined_setup(table3)
    cyclotron.polls_needed = 10_000
    cyclotron.combined_busy_after = 1          # the lab takes the first story's job and refuses the rest
    run_with(table3, store, cyclotron)
    cyclotron.polls_needed = 0
    result = run_with(table3, store, cyclotron, now=2120, task="collect")
    assert result["counts"]["examined"] == 1
    assert len(cyclotron.combined_jobs) == 1
    assert routing_of(table3)["DISC#102#000001"] == "collected" and "combinedJob" not in table3.items.get(("MONITOR#hn", "ROUTE#102#000001"), {})


def test_the_collector_reports_jobs_that_are_still_running(table):
    store, cyclotron = combined_setup(table)
    cyclotron.polls_needed = 10_000
    run_with(table, store, cyclotron)
    result = run_with(table, store, cyclotron, now=2120, task="collect")
    assert result["status"] == "awaiting" and result["counts"]["awaiting"] == 1 and result["counts"]["routed"] == 0


def test_the_collector_and_the_route_run_share_the_per_monitor_lock(table):
    store, cyclotron = combined_setup(table)
    assert store.acquire_router_lock("hn", "route-run", 2000)
    assert run_with(table, store, cyclotron, now=2010, task="collect")["status"] == "locked"
    assert cyclotron.combined_calls == [] and cyclotron.calls == []
    store.release_router_lock("hn", "route-run")
    cyclotron.polls_needed = 10_000
    assert store.acquire_router_lock("hn", "collector", 2020)
    assert run_with(table, store, cyclotron, now=2030)["status"] == "locked"
    assert cyclotron.combined_calls == []
    store.release_router_lock("hn", "collector")


def test_the_per_publication_path_posts_all_bindings_before_it_waits(table):
    store, cyclotron = setup_router(table)     # no combined endpoint
    cyclotron.polls_needed = 10_000
    result = run_with(table, store, cyclotron)
    assert len(cyclotron.posts()) == 3 and result["status"] == "awaiting" and result["counts"]["awaiting"] == 1
    cyclotron.polls_needed = 0
    delivery = Delivery()
    result = run_with(table, store, cyclotron, now=2120, task="collect", deliver=delivery)
    assert len(cyclotron.posts()) == 3 and routing_of(table)["DISC#101#000001"] == "routed"
    assert len(delivery.calls) == 3


def test_a_stop_from_cyclotron_still_stops_the_run_and_is_not_reported_as_awaiting(table):
    store, cyclotron = combined_setup(table)
    cyclotron.combined_post_override = (409, {"code": "run_busy"})
    result = run_with(table, store, cyclotron)
    assert result["status"] == "stopped" and result["stoppedBy"] == "run_busy"


def test_the_template_schedules_the_collector_on_the_router_function_without_new_permissions():
    resources = _template()["Resources"]
    schedule = resources["RouterCollectSchedule"]["Properties"]
    assert schedule["ScheduleExpression"] == "rate(2 minutes)" and schedule["State"] == ("Ref", "ScheduleState")
    assert schedule["Target"]["Arn"] == resources["RouteSchedule"]["Properties"]["Target"]["Arn"]
    assert schedule["Target"]["RoleArn"] == resources["RouteSchedule"]["Properties"]["Target"]["RoleArn"]
    assert json.loads(schedule["Target"]["Input"]) == {"monitorId": "hn", "task": "collect"}


# --- decision-ready doorbell --------------------------------------------------------------------

def decision_event(**detail):
    base = {"contractVersion": mr.CONTRACT_VERSION, "accountId": "acct-1", "runId": "run-1", "jobId": "job-1",
            "requestId": "req-1", "itemId": "hn-101", "publications": [], "status": "complete"}
    return {"source": "cyclotron.lab", "detail-type": "Decision Ready", "detail": base | detail}


def ring(table, event, collected=None):
    calls = []
    outcome = mr.handle_decision_ready(mr.RouterStore(table), event, lambda m, job=None: calls.append(m) or {"status": "complete"})
    return outcome, calls


def test_doorbell_collects_every_configured_monitor_for_the_run(table):
    table.put_item(router_config())
    table.put_item(router_config() | {"pk": "MONITOR#ttab"})
    outcome, calls = ring(table, decision_event())
    assert calls == ["hn", "ttab"] and outcome["status"] == "collected"


def test_doorbell_ignores_an_old_run_or_other_account(table):
    table.put_item(router_config())
    assert ring(table, decision_event(runId="run-0"))[1] == []
    outcome, calls = ring(table, decision_event(accountId="acct-2"))
    assert calls == [] and outcome["status"] == "ignored" and outcome["ignoredMonitors"] == 1


@pytest.mark.parametrize("event", [
    None, {}, {"source": "other", "detail-type": "Decision Ready", "detail": {}},
    {"source": "cyclotron.lab", "detail-type": "Other", "detail": {}},
    {"source": "cyclotron.lab", "detail-type": "Decision Ready", "detail": "x"},
    decision_event(runId=""), decision_event(jobId=5), decision_event(status="weird"),
    decision_event(contractVersion="v0"), decision_event(publications="x"),
    {k: v for k, v in decision_event().items() if k != "detail"}])
def test_doorbell_drops_a_malformed_event_without_raising(table, event):
    table.put_item(router_config())
    outcome, calls = ring(table, event)
    assert outcome["status"] == "malformed" and calls == []


def test_doorbell_survives_a_failing_collect(table):
    table.put_item(router_config())
    def boom(m, job=None):
        raise RuntimeError("down")
    assert mr.handle_decision_ready(mr.RouterStore(table), decision_event(), boom)["collected"] == {"hn": "error"}


def test_doorbell_duplicate_and_locked_monitor_are_harmless(table):
    store, cyclotron = combined_setup(table)
    cyclotron.polls_needed = 10_000
    run_with(table, store, cyclotron)
    cyclotron.polls_needed = 0
    collect = lambda m, job=None: run_with(table, store, cyclotron, task="collect")
    first = mr.handle_decision_ready(store, decision_event(), collect)
    second = mr.handle_decision_ready(store, decision_event(), collect)
    assert first["collected"] == {"hn": "complete"} and second["collected"] == {"hn": "complete"}
    assert set(routing_of(table).values()) == {"routed"}
    assert store.acquire_router_lock("hn", "route-run", 2100)
    assert mr.handle_decision_ready(store, decision_event(), collect)["collected"] == {"hn": "locked"}


def test_scheduled_events_are_not_decision_events():
    assert not mr.is_decision_event({"monitorId": "hn", "task": "collect"}) and not mr.is_decision_event({})
    assert mr.is_decision_event(decision_event())


def test_template_bus_policy_names_only_the_cyclotron_worker_and_source():
    template, parameters = _template()["Resources"], _template()["Parameters"]
    policy = template["CyclotronDecisionsBusPolicy"]["Properties"]["Statement"]
    assert policy["Principal"] == {"AWS": ("Ref", "CyclotronWorkerRoleArn")}
    assert policy["Action"] == "events:PutEvents" and policy["Effect"] == "Allow"
    assert policy["Condition"] == {"StringEquals": {"events:source": "cyclotron.lab"}}
    assert parameters["CyclotronWorkerRoleArn"]["Default"] == "arn:aws:iam::682849160744:role/cyclotron-console-worker-runtime"
    assert template["CyclotronDecisionsBus"]["Properties"]["Name"] == "papyrus-cyclotron-decisions"


def test_template_rule_targets_the_router_with_a_permission_scoped_to_it():
    template, parameters = _template()["Resources"], _template()["Parameters"]
    rule = template["DecisionReadyRule"]["Properties"]
    assert rule["EventPattern"] == {"source": ["cyclotron.lab"], "detail-type": ["Decision Ready"]}
    target = rule["Targets"][0]
    assert target["Arn"] == ("GetAtt", "RouterFunction.Arn") and "Input" not in target and "InputTransformer" not in target
    assert target["DeadLetterConfig"]["Arn"] == ("GetAtt", "RouterDeadLetterQueue.Arn") and target["RetryPolicy"]
    permission = template["DecisionReadyInvokePermission"]["Properties"]
    assert permission["Principal"] == "events.amazonaws.com" and permission["SourceArn"] == ("GetAtt", "DecisionReadyRule.Arn")


SUB = "-".join(["1" * 8, "2" * 4, "3" * 4, "4" * 4, "5" * 12])   # placeholder Cognito sub


def test_feedback_is_sent_for_ui_editor_actors_with_a_non_pii_subject(table):
    store, cyclotron = delivered_table(table)
    references = {"reference-anth-us-101": ref("accepted", "Editor@Example.test"),
                  "reference-p-apyr-us-101": ref("rejected", "google_1234567890"),
                  "reference-threat-intelligence-101": ref("accepted", SUB)}
    result = feedback_run(table, store, cyclotron, references)
    assert result["feedback"]["sent"] == 3
    from hashlib import sha256
    sent = {c[1].split("/")[3]: c[2]["payload"]["editor"] for c in cyclotron.posts() if c[2]["operation"] == "feedback"}
    digest = sha256(b"anth-us:editor@example.test").hexdigest()[:32]
    assert sent["anth-us"] == {"site": "anth-us.example", "subject": f"editor:{digest}"}
    assert sent["p-apyr-us"]["subject"].startswith("editor:")
    assert sent["threat-intelligence"]["subject"] == f"cognito:{SUB}"
    assert all("@" not in e["subject"] for e in sent.values())


def test_feedback_skips_machine_and_missing_actors(table):
    store, cyclotron = delivered_table(table)
    references = {"reference-anth-us-101": ref("accepted", "ai"),
                  "reference-p-apyr-us-101": ref("accepted", "papyrus-monitoring-worker"),
                  "reference-threat-intelligence-101": ref("accepted", "Papyrus newsroom")}
    result = feedback_run(table, store, cyclotron, references)
    assert result["feedback"]["sent"] == 0 and result["feedback"]["skipped"] == 3
    for actor in ("", "user:", "system:monitor", "worker:abc", "papyrus-relevance", "demo-import", "behave-x"):
        assert not mr.human_actor(actor)


def test_run_busy_during_posting_still_collects_the_jobs_already_posted(table3):
    store, cyclotron = combined_setup(table3)
    cyclotron.combined_busy_after = 1
    result = go(table3, store, cyclotron)
    assert result["status"] == "stopped" and result["stoppedBy"] == "run_busy"
    assert sorted(routing_of(table3).values()).count("routed") == 1     # the posted story was collected and delivered
    refused = [k for k, v in table3.items.items() if k[1].startswith("ROUTE#") and "combinedJob" not in v]
    assert len(refused) == 2 and result["counts"]["error"] == 0       # refused posts store no job and are not errors


def test_old_ceilings_and_batch_size_load_ignored_with_one_log_line(capsys):
    configured = validate_router_config({**router_config(), "ceilings": {"decisionsTotal": 300}, "maxItemsPerRun": 1})
    assert "ceilings" not in configured and "maxItemsPerRun" not in configured
    lines = [l for l in capsys.readouterr().out.splitlines() if "ignored_retired_config" in l]
    assert len(lines) == 1 and "ceilings" in lines[0] and "maxItemsPerRun" in lines[0]
    validate_router_config(router_config())
    assert "ignored_retired_config" not in capsys.readouterr().out


def test_a_run_posts_every_ready_story_and_pages_through_the_partition(table3):
    table3.page_size = 1                       # the partition comes back one row per page
    store, cyclotron = combined_setup(table3)
    result = go(table3, store, cyclotron)
    assert result["status"] == "complete" and result["stoppedBy"] is None and result["counts"]["routed"] == 3
    assert len(combined_posts(cyclotron)) == 3


def test_no_run_stops_for_a_ceiling_of_its_own(table3):
    store, cyclotron = combined_setup(table3)
    table3.put_item(router_config(ceilings={"decisionsTotal": 1, "decisionsPerDay": 1, "items": 1}))
    result = go(table3, store, cyclotron)
    assert result["stoppedBy"] is None and result["counts"]["routed"] == 3


# --- backing off from the lab ------------------------------------------------------------------------------

BACKOFF_KEY = ("MONITOR#hn", "STATE#labBackoff")


def lab_gets(cyclotron):
    return [c for c in cyclotron.combined_calls if c[0] == "GET"]


def waiting_jobs(table3, polls=10_000):
    """Three stories posted and still running at the lab; returns the store and the fake lab."""
    store, cyclotron = combined_setup(table3)
    cyclotron.polls_needed = polls
    run_with(table3, store, cyclotron, now=2000)
    return store, cyclotron


def test_parse_retry_after_reads_seconds_and_http_dates_and_ignores_junk():
    assert mr.parse_retry_after("90") == 90 and mr.parse_retry_after(7) == 7
    assert mr.parse_retry_after(None) is None and mr.parse_retry_after("soon") is None and mr.parse_retry_after("0") is None
    assert 3500 < mr.parse_retry_after("Fri, 01 Jan 2100 00:00:00 GMT") and mr.parse_retry_after(True) is None


def test_a_429_with_retry_after_pauses_every_lab_call_until_then(table3):
    store, cyclotron = waiting_jobs(table3)
    cyclotron.combined_poll_override = (429, {"retryAfter": 90})
    result = run_with(table3, store, cyclotron, now=3000, task="collect")
    assert result["stoppedBy"] == "http_429"
    assert table3.items[BACKOFF_KEY]["until"] == 3090 and table3.items[BACKOFF_KEY]["retryAfter"] == 90
    calls = len(cyclotron.combined_calls) + len(cyclotron.calls)
    for task in ("collect", "route"):
        paused = run_with(table3, store, cyclotron, now=3060, task=task)
        assert paused["status"] == "stopped" and paused["stoppedBy"] == "lab_backoff"
    assert len(cyclotron.combined_calls) + len(cyclotron.calls) == calls      # not one call while paused
    cyclotron.combined_poll_override = None
    cyclotron.polls_needed = 0
    done = run_with(table3, store, cyclotron, now=3091, task="collect")
    assert done["status"] == "complete" and BACKOFF_KEY not in table3.items   # the lab answered: the pause is cleared


def test_a_503_without_retry_after_backs_off_exponentially_and_a_clean_run_resets_it(table3):
    store, cyclotron = waiting_jobs(table3)
    cyclotron.combined_poll_override = (503, {})
    run_with(table3, store, cyclotron, now=3000, task="collect")
    assert table3.items[BACKOFF_KEY]["until"] == 3060 and table3.items[BACKOFF_KEY]["strikes"] == 1
    run_with(table3, store, cyclotron, now=3061, task="collect")
    assert table3.items[BACKOFF_KEY]["until"] == 3061 + 120 and table3.items[BACKOFF_KEY]["strikes"] == 2
    run_with(table3, store, cyclotron, now=3200, task="collect")
    assert table3.items[BACKOFF_KEY]["until"] == 3200 + 240
    cyclotron.combined_poll_override = None
    run_with(table3, store, cyclotron, now=3500, task="collect")
    assert BACKOFF_KEY not in table3.items
    cyclotron.combined_poll_override = (503, {})
    run_with(table3, store, cyclotron, now=4000, task="collect")
    assert table3.items[BACKOFF_KEY]["until"] == 4060     # back to the first step


def test_the_pause_is_capped_so_it_never_grows_without_bound(table3):
    store, cyclotron = waiting_jobs(table3)
    cyclotron.combined_poll_override = (503, {})
    now, waits = 3000, []
    for _ in range(12):
        run_with(table3, store, cyclotron, now=now, task="collect")
        waits.append(int(table3.items[BACKOFF_KEY]["until"]) - now)
        now = int(table3.items[BACKOFF_KEY]["until"]) + 1
    assert waits[:6] == [60, 120, 240, 480, 960, 1800] and set(waits[5:]) == {mr.LAB_BACKOFF_MAX}


def test_the_collector_stops_at_the_first_429_having_asked_about_the_oldest_job_first(table3):
    store, cyclotron = waiting_jobs(table3)
    cyclotron.combined_poll_override = (429, {"retryAfter": 30})
    seen = len(lab_gets(cyclotron))
    result = run_with(table3, store, cyclotron, now=3000, task="collect")
    assert result["status"] == "stopped" and len(lab_gets(cyclotron)) == seen + 1     # one question, then the pass stops
    jobs = [table3.items[("MONITOR#hn", f"ROUTE#{n}#000001")]["combinedJob"] for n in (101, 102, 103)]
    assert lab_gets(cyclotron)[-1][1].endswith(min(jobs, key=lambda job: (job["postedAt"], job["jobId"]))["jobId"])
    assert all("combinedJob" in table3.items[("MONITOR#hn", f"ROUTE#{n}#000001")] for n in (101, 102, 103))   # no job dropped


def test_a_job_that_is_still_running_waits_longer_each_time_and_is_not_asked_inside_its_wait(table3):
    store, cyclotron = waiting_jobs(table3)
    route = lambda: table3.items[("MONITOR#hn", "ROUTE#101#000001")]["combinedJob"]
    before = len(lab_gets(cyclotron))
    run_with(table3, store, cyclotron, now=3000, task="collect")
    assert route()["nextPollAt"] == 3030 and route()["pollBackoffs"] == 1
    assert len(lab_gets(cyclotron)) == before + 3                      # each job asked once in the pass, not once per window round
    run_with(table3, store, cyclotron, now=3010, task="collect")
    assert len(lab_gets(cyclotron)) == before + 3                      # inside its wait: no calls at all
    run_with(table3, store, cyclotron, now=3031, task="collect")
    assert route()["nextPollAt"] == 3031 + 60 and route()["pollBackoffs"] == 2
    for now in (3200, 3400, 3700, 4200, 5000, 6000):
        run_with(table3, store, cyclotron, now=now, task="collect")
    assert route()["nextPollAt"] - 6000 == mr.POLL_BACKOFF_MAX          # grows to the cap, never past it
    assert mr.POLL_BACKOFF_MAX == mr.COLLECT_CADENCE_SECONDS * mr.POLL_BACKOFF_CADENCES


def test_a_completed_job_is_delivered_and_its_backoff_is_cleared(table3):
    store, cyclotron = waiting_jobs(table3)
    run_with(table3, store, cyclotron, now=3000, task="collect")
    cyclotron.polls_needed = 0
    run_with(table3, store, cyclotron, now=3100, task="collect")
    assert set(routing_of(table3).values()) == {"routed"}
    for n in (101, 102, 103):
        row = table3.items[("MONITOR#hn", f"ROUTE#{n}#000001")]
        assert "combinedJob" not in row
        assert all("nextPollAt" not in job and "pollBackoffs" not in job for job in row["jobs"].values())


def test_a_decision_ready_doorbell_bypasses_the_wait_of_the_job_it_names(table3):
    store, cyclotron = waiting_jobs(table3)
    run_with(table3, store, cyclotron, now=3000, task="collect")
    job = table3.items[("MONITOR#hn", "ROUTE#101#000001")]["combinedJob"]["jobId"]
    seen = len(lab_gets(cyclotron))
    run_with(table3, store, cyclotron, now=3005, task="collect", rung_job_ids=[job])
    assert [c[1].rsplit("/", 1)[1] for c in lab_gets(cyclotron)[seen:]] == [job]


def test_the_per_publication_path_backs_off_the_same_way(table):
    store, cyclotron = setup_router(table)
    cyclotron.pending_polls = 10_000
    go(table, store, cyclotron, now=2000)
    run_with(table, store, cyclotron, now=3000, task="collect")
    job = table.items[("MONITOR#hn", "ROUTE#101#000001")]["jobs"]["anth-us"]
    assert job["nextPollAt"] == 3030
    seen = len(cyclotron.calls)
    run_with(table, store, cyclotron, now=3010, task="collect")
    assert len(cyclotron.calls) == seen


def test_feedback_posts_wait_for_the_pause_too(table):
    store, cyclotron = setup_router(table, feedback=True)
    table.put_item({"pk": "MONITOR#hn", "sk": "STATE#labBackoff", "until": 6000, "strikes": 1})
    result = feedback_run(table, store, cyclotron, {}, now=5000)
    assert result["feedback"]["status"] == "stopped" and result["feedback"]["stoppedBy"] == "lab_backoff"
    assert cyclotron.calls == []


def combined_ids(cyclotron):
    return [c[2]["requestId"] for c in cyclotron.combined_calls if c[0] == "POST"]


def test_same_content_gets_the_same_combined_id_across_runs(table):
    store, cyclotron = combined_setup(table)
    cyclotron.combined_post_override = (409, {"code": "run_busy"})
    go(table, store, cyclotron)
    cyclotron.combined_post_override = None
    go(table, store, cyclotron, now=3000)
    ids = combined_ids(cyclotron)
    assert len(ids) == 2 and ids[0] == ids[1]


def test_changed_bindings_do_not_repost_a_stored_job_under_the_old_id(table):
    store, cyclotron = combined_setup(table)
    cyclotron.combined_poll_override = (202, {"status": "running"})
    go(table, store, cyclotron)
    route = table.items[("MONITOR#hn", "ROUTE#101#000001")]
    old_job = route["combinedJob"]["jobId"]
    cyclotron.combined_poll_override = None
    table.put_item({**table.items[("MONITOR#hn", "CONFIG#router")], "publications": [
        p for p in table.items[("MONITOR#hn", "CONFIG#router")]["publications"] if p["publicationId"] != "p-apyr-us"]})
    go(table, store, cyclotron, now=3000)
    assert len(combined_ids(cyclotron)) == 1
    assert any(c[0] == "GET" and c[1].endswith(old_job) for c in cyclotron.combined_calls)
    assert routing_of(table)["DISC#101#000001"] == "routed"


def test_a_request_conflict_discards_the_job_and_reposts_once_under_a_new_id(table):
    store, cyclotron = combined_setup(table)
    cyclotron.combined_post_queue = [(409, {"code": "request_conflict", "detail": "command identity has different content"})]
    result = go(table, store, cyclotron)
    ids = combined_ids(cyclotron)
    assert len(ids) == 2 and ids[0] != ids[1]
    assert routing_of(table)["DISC#101#000001"] == "routed" and result["stoppedBy"] is None


def test_a_second_request_conflict_is_not_reposted_again(table):
    store, cyclotron = combined_setup(table)
    cyclotron.combined_post_override = (409, {"code": "request_conflict"})
    go(table, store, cyclotron)
    assert len(combined_ids(cyclotron)) == 2
    assert "combinedJob" not in table.items[("MONITOR#hn", "ROUTE#101#000001")]
    assert routing_of(table)["DISC#101#000001"] == "collected"


def test_a_per_publication_request_conflict_reposts_once_under_a_new_id(table):
    store, cyclotron = setup_router(table)
    real = cyclotron.http
    seen = {"n": 0}

    def http(method, url, headers, body, timeout):
        if method == "POST" and "/anth-us/operations" in url and seen["n"] == 0:
            seen["n"] += 1
            cyclotron.calls.append((method, url.split("amazonaws.com", 1)[1], json.loads(body)))
            return 409, {"code": "request_conflict"}
        return real(method, url, headers, body, timeout)
    cyclotron.http = http
    go(table, store, cyclotron)
    ids = [c[2]["requestId"] for c in cyclotron.calls if c[0] == "POST" and "/anth-us/" in c[1] and c[2]["payload"]["item"]["id"] == "hn-101"]
    assert len(ids) == 2 and ids[0] != ids[1]
    assert routing_of(table)["DISC#101#000001"] == "routed"


def test_a_failed_single_publication_job_is_reposted_once_and_a_repeat_errors_the_story(table):
    store, cyclotron = setup_router(table)
    cyclotron.poll_override["p-apyr-us"] = (200, {"status": "failed"})
    go(table, store, cyclotron)
    ids = [c[2]["requestId"] for c in cyclotron.calls if c[0] == "POST" and "/p-apyr-us/" in c[1] and c[2]["payload"]["item"]["id"] == "hn-101"]
    assert len(ids) == 2 and ids[0] != ids[1]
    assert routing_of(table)["DISC#101#000001"] == "error"


# --- pacing under the API Gateway stage limit ------------------------------------------------------------

class Clocked:
    """A fake clock: sleep advances it, and every call the lab receives is stamped with the time it arrived."""

    def __init__(self):
        self.t, self.arrivals = 0.0, []

    def sleep(self, seconds):
        self.t += seconds

    def clock(self):
        return self.t


def paced_client(table, cyclotron, fake, **overrides):
    config = validate_router_config(table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"])

    def http(method, url, headers, body, timeout):
        fake.arrivals.append(fake.t)
        return cyclotron.http(method, url, headers, body, timeout)
    return CyclotronClient(config, sign=lambda m, u, b: {}, http=http, sleep=fake.sleep, clock=fake.clock,
                           jitter=lambda lo, hi: lo, **overrides)


def test_the_default_pacing_is_four_requests_a_second_and_is_configurable(table3):
    assert validate_router_config(router_config())["cyclotron"]["maxRequestsPerSecond"] == 4
    raw = router_config()
    raw["cyclotron"]["maxRequestsPerSecond"] = 2
    assert validate_router_config(raw)["cyclotron"]["maxRequestsPerSecond"] == 2
    raw["cyclotron"]["maxRequestsPerSecond"] = 0
    with pytest.raises(ValueError):
        validate_router_config(raw)


def test_lab_calls_leave_at_most_four_a_second_whatever_their_kind(table3):
    store, cyclotron = combined_setup(table3)
    fake = Clocked()
    client = paced_client(table3, cyclotron, fake)
    cyclotron.polls_needed = 10_000
    for _ in range(3):
        client.post_combined({"payload": {"bindings": ["anth-us"], "item": {"id": "x"}}})
    for _ in range(5):
        try:
            client.poll_combined("cjob-0", wait=False)
        except Exception:
            pass
    gaps = [round(b - a, 6) for a, b in zip(fake.arrivals, fake.arrivals[1:])]
    assert len(fake.arrivals) == 8 and min(gaps) >= 0.25
    assert all(second_count <= 4 for second_count in
               [sum(1 for t in fake.arrivals if start <= t < start + 1) for start in fake.arrivals])


def test_a_bare_429_is_retried_after_a_short_wait_without_pausing_the_monitor(table3):
    store, cyclotron = combined_setup(table3)
    fake = Clocked()
    cyclotron.combined_poll_queue = [(429, {"message": "Too Many Requests"}), (429, {"message": "Too Many Requests"})]
    client = paced_client(table3, cyclotron, fake)
    cyclotron.polls_needed = 0
    run_router(store, "hn", now=2000, cyclotron=client, appsync=lambda e: object(), deliver=Delivery(),
               context_receipt=lambda c, p: {})
    assert client.throttled == 2 and client.rate_limited is None
    assert BACKOFF_KEY not in table3.items
    assert set(routing_of(table3).values()) == {"routed"}          # the run carried on and delivered
    assert fake.t >= 2.0                                            # it waited 1 s (jitter fixed at the low end) per bare 429
    assert client.interval > 0.25                                   # and kept slowing the pacing for the rest of the run


def test_a_bare_429_that_never_clears_stops_the_run_without_a_monitor_pause(table3):
    store, cyclotron = waiting_jobs(table3)
    cyclotron.combined_poll_override = (429, {"message": "Too Many Requests"})
    result = run_with(table3, store, cyclotron, now=3000, task="collect")
    assert result["status"] == "stopped" and BACKOFF_KEY not in table3.items


def test_a_503_with_retry_after_pauses_until_then(table3):
    store, cyclotron = waiting_jobs(table3)
    cyclotron.combined_poll_override = (503, {"retryAfter": 45})
    run_with(table3, store, cyclotron, now=3000, task="collect")
    assert table3.items[BACKOFF_KEY]["until"] == 3045 and table3.items[BACKOFF_KEY]["status"] == 503


def test_an_old_429_pause_without_retry_after_is_cleared_on_the_next_run(table3):
    store, cyclotron = waiting_jobs(table3)
    table3.put_item({"pk": "MONITOR#hn", "sk": "STATE#labBackoff", "until": 9000, "strikes": 4, "status": 429, "retryAfter": None})
    seen = len(lab_gets(cyclotron))
    result = run_with(table3, store, cyclotron, now=3000, task="collect")
    assert result["stoppedBy"] != "lab_backoff" and len(lab_gets(cyclotron)) > seen
    assert BACKOFF_KEY not in table3.items


# --- criteria fingerprint ------------------------------------------------------------------------

def fingerprint_row(table, pub="anth-us", ref_id="reference-anth-us-101"):
    return table.items[("MONITOR#hn", f"DELIV#{pub}#{ref_id}")]


def test_decision_stores_the_criteria_fingerprint_and_remembers_the_latest_per_publication(table):
    store, cyclotron = setup_router(table, feedback=True)
    cyclotron.output_extra = {"anth-us": {"criteriaFingerprint": "c-1"}}
    go(table, store, cyclotron, deliver=Delivery())
    assert fingerprint_row(table)["criteriaFingerprint"] == "c-1"
    assert table.items[("MONITOR#hn", "CRIT#anth-us")]["criteriaFingerprint"] == "c-1"
    assert "criteriaFingerprint" not in fingerprint_row(table, "p-apyr-us", "reference-p-apyr-us-101")
    assert ("MONITOR#hn", "CRIT#p-apyr-us") not in table.items


def test_criteria_fingerprint_falls_back_to_sha256_of_the_question():
    from hashlib import sha256
    fp = mr.criteria_fingerprint({"outputs": [{"id": "o", "question": "Is it relevant?"}]}, "o")
    assert fp == sha256(b"Is it relevant?").hexdigest()
    assert mr.criteria_fingerprint({"outputs": [{"id": "o", "question": "q", "criteriaFingerprint": "given"}]}, "o") == "given"
    assert mr.criteria_fingerprint({"outputs": [{"id": "o"}]}, "o") is None
    assert mr.criteria_fingerprint({"outputs": [{"id": "x", "criteriaFingerprint": "z"}]}, "o") is None


def set_fingerprints(table, voted, current):
    if voted:
        fingerprint_row(table)["criteriaFingerprint"] = voted
    if current:
        table.items[("MONITOR#hn", "CRIT#anth-us")] = {"pk": "MONITOR#hn", "sk": "CRIT#anth-us", "criteriaFingerprint": current}


def test_feedback_is_sent_when_the_fingerprint_matches_even_if_criteria_since_says_changed(table):
    store, cyclotron = delivered_table(table)
    rebind(table, "4", since="4")
    set_fingerprints(table, "c-1", "c-1")
    refs = {"reference-anth-us-101": ref("accepted", "user:s")}
    assert feedback_run(table, store, cyclotron, refs)["feedback"]["sent"] == 1


def test_feedback_is_stale_when_the_fingerprint_differs_even_if_criteria_since_says_unchanged(table):
    store, cyclotron = delivered_table(table)
    rebind(table, "4", since="1")
    set_fingerprints(table, "c-1", "c-2")
    refs = {"reference-anth-us-101": ref("accepted", "user:s")}
    assert feedback_run(table, store, cyclotron, refs)["feedback"]["skipped"] == 1
    assert fingerprint_row(table)["feedback"] == "stale"
    outcome = [v for k, v in table.items.items() if k[1].startswith("FB#") and v["publicationId"] == "anth-us"][0]
    assert outcome["outcome"] == "stale" and outcome["votedFingerprint"] == "c-1" and outcome["currentFingerprint"] == "c-2"


def test_feedback_falls_back_to_criteria_since_when_a_fingerprint_is_unknown(table):
    store, cyclotron = delivered_table(table)
    rebind(table, "4", since="4")
    set_fingerprints(table, None, "c-2")           # a vote stored before fingerprints existed
    refs = {"reference-anth-us-101": ref("accepted", "user:s")}
    assert feedback_run(table, store, cyclotron, refs)["feedback"]["skipped"] == 1
