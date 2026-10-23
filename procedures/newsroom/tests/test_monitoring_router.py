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
                    "intervalSeconds": 900, "limit": 30, "enabled": True}
ENDPOINT = "https://abc123.appsync-api.us-east-1.amazonaws.com/graphql"
PUBS = ("anth-us", "p-apyr-us", "threat-intelligence")


def router_config(mode="live", **overrides):
    config = {"pk": "MONITOR#hn", "sk": "CONFIG#router", "mode": mode, "maxItemsPerRun": 5, "feedback": False,
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
            return {"Items": [deepcopy(v) for k, v in sorted(self.items.items())
                              if k[0] == ExpressionAttributeValues[":pk"] and k[1].startswith(ExpressionAttributeValues[":prefix"])]}
        assert IndexName == "routing" and KeyConditionExpression == "gsi1pk = :p"
        rows = sorted((v for v in self.items.values() if v.get("gsi1pk") == ExpressionAttributeValues[":p"]),
                      key=lambda v: v["gsi1sk"], reverse=not ScanIndexForward)
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

    def http(self, method, url, headers, body, timeout):
        path = url.split("amazonaws.com", 1)[1]
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
        _, item = self.jobs[job]
        return 200, {"contractVersion": mr.CONTRACT_VERSION, "publicationId": pub, "bindingRevision": "1",
                     "decision": {"decisionId": f"dec-{item}", "itemId": item, "classifiers": {
                         f"{pub}-relevance": {"label": self.labels.get((item, pub), "include"),
                                              "fingerprint": f"fp-{pub}", "version": 3,
                                              **({"confidence": self.confidence[(item, pub)]} if (item, pub) in self.confidence else {})}}},
                     "outputs": [{"id": f"{pub}-relevance"}], "source": {"id": item, "revision": 2, "fingerprint": "sfp"}}

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


@pytest.fixture
def table():
    t = FakeTable()
    t.put_item(COLLECTOR_CONFIG)
    run_collection(DynamoStore(t), "hn", fetch=lambda url: FEED, now=1000)
    return t


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
    assert parsed["maxItemsPerRun"] == 5 and parsed["feedback"] is False and parsed["mode"] == "live"
    assert parsed["publications"][1]["corpusKey"] == "ai-ml-research"
    assert parsed["publications"][0]["output"] == "anth-us-relevance"
    for bad in ({"mode": "maybe"}, {"maxItemsPerRun": 0}, {"publications": []},
                {"cyclotron": {**router_config()["cyclotron"], "endpoint": "https://example.org"}},
                {"cyclotron": {**router_config()["cyclotron"], "roleArn": ""}},
                {"publications": [{**router_config()["publications"][0], "appsyncEndpoint": "https://evil.example/graphql"}]},
                {"publications": [router_config()["publications"][0]] * 2}):
        with pytest.raises(ValueError):
            validate_router_config({**router_config(), **bad})
    assert validate_router_config(router_config("dry-run", cyclotron={**router_config()["cyclotron"], "roleArn": ""}))["mode"] == "dry-run"


def test_request_ids_are_deterministic_and_bound_to_every_input():
    base = request_id("a", "r", "p", "1", "hn-1", "fp")
    assert base == request_id("a", "r", "p", "1", "hn-1", "fp") and len(base) == 64
    assert len({base, request_id("b", "r", "p", "1", "hn-1", "fp"), request_id("a", "s", "p", "1", "hn-1", "fp"),
                request_id("a", "r", "q", "1", "hn-1", "fp"), request_id("a", "r", "p", "2", "hn-1", "fp"),
                request_id("a", "r", "p", "1", "hn-2", "fp"), request_id("a", "r", "p", "1", "hn-1", "fx")}) == 7


def test_decide_request_has_the_exact_contract_shape(table):
    config = validate_router_config(router_config())
    disc = table.items[("MONITOR#hn", "DISC#101#000001")]
    built = build_decide_request(config, config["publications"][0], disc)
    body = built["body"]
    assert built["path"] == "/machine/publications/anth-us/operations"
    assert body["contractVersion"] == "cyclotron-publication/v1" and body["operation"] == "decide"
    assert body["requestId"] == request_id("acct-1", "run-1", "anth-us", "1", "hn-101", disc["fingerprint"])
    assert body["payload"] == {"bindingRevision": "1", "item": {"id": "hn-101", "values": {
        "title": "Alpha source", "url": "https://example.org/alpha", "source": "hacker-news",
        "sourceItemUrl": "https://news.ycombinator.com/item?id=101", "text": "Alpha source\nhttps://example.org/alpha"}}}


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(contractVersion="v0"), lambda b: b.update(operation="delete"),
    lambda b: b.update(requestId="short"), lambda b: b["payload"].update(extra=1),
    lambda b: b["payload"]["item"]["values"].update(text="mismatch"),
    lambda b: b["payload"]["item"]["values"].pop("url"),
    lambda b: b["payload"]["item"].update(id="other-1"),
    lambda b: b["payload"]["item"]["values"].update(title="x" * 40_000, text="x" * 40_000 + "\nhttps://example.org/alpha")])
def test_validation_rejects_off_contract_bodies(table, mutate):
    config = validate_router_config(router_config())
    body = deepcopy(build_decide_request(config, config["publications"][0], table.items[("MONITOR#hn", "DISC#101#000001")])["body"])
    mutate(body)
    with pytest.raises(ValueError):
        validate_request(body)


# --- dry run ------------------------------------------------------------------------------------------

def test_dry_run_builds_validates_and_records_receipts_without_any_cyclotron_call(table):
    store, _ = setup_router(table, mode="dry-run", maxItemsPerRun=2)
    contexts = {"anth-us": {"contextHash": None, "reason": "no stored policy"},
                "p-apyr-us": {"contextHash": None, "reason": "no stored policy"},
                "threat-intelligence": {"contextHash": "abc", "reason": None}}
    result = go(table, store, None, context_receipt=lambda client, pub: contexts[pub["publicationId"]])
    assert result["status"] == "complete" and result["mode"] == "dry-run" and result["counts"]["dryRunValidated"] == 2
    assert routing_of(table) == {"DISC#101#000001": "dry-run-validated", "DISC#102#000001": "dry-run-validated",
                                 "DISC#103#000001": "collected"}
    route = table.items[("MONITOR#hn", "ROUTE#101#000001")]
    assert set(route["dryRun"]["requests"]) == set(PUBS) and route["dryRun"]["count"] == 1
    assert route["dryRun"]["contexts"]["anth-us"] == {"contextHash": None, "reason": "no stored policy"}
    assert route["dryRun"]["contexts"]["threat-intelligence"]["contextHash"] == "abc"
    request = route["dryRun"]["requests"]["p-apyr-us"]
    assert request["path"] == "/machine/publications/p-apyr-us/operations" and request["body"]["operation"] == "decide"
    receipt = table.by_prefix("ROUTERUN#")[0]
    assert receipt["mode"] == "dry-run" and receipt["counts"]["dryRunValidated"] == 2
    # the next dry-run advances through the backlog instead of revalidating the same items
    go(table, store, None, now=3000)
    assert routing_of(table)["DISC#103#000001"] == "dry-run-validated"
    assert table.items[("MONITOR#hn", "ROUTE#101#000001")]["dryRun"]["count"] == 1


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
    store, cyclotron = setup_router(table, mode="dry-run", maxItemsPerRun=1)
    go(table, store, None)
    dry_ids = {p: r["requestId"] for p, r in table.items[("MONITOR#hn", "ROUTE#101#000001")]["dryRun"]["requests"].items()}
    table.put_item(router_config("live", maxItemsPerRun=1))
    delivery = Delivery()
    go(table, store, cyclotron, now=3000, deliver=delivery)
    assert {c[2]["requestId"] for c in cyclotron.posts()} == set(dry_ids.values())
    assert routing_of(table)["DISC#101#000001"] == "routed"


# --- live ---------------------------------------------------------------------------------------------

def test_live_happy_path_one_shared_decision_and_per_publication_delivery(table):
    store, cyclotron = setup_router(table, maxItemsPerRun=1)
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
    store, cyclotron = setup_router(table, maxItemsPerRun=1)
    cyclotron.confidence = {("hn-101", "anth-us"): 0.91234, ("hn-101", "p-apyr-us"): 1.7, ("hn-101", "threat-intelligence"): "high"}
    go(table, store, cyclotron)
    publications = table.items[("MONITOR#hn", "ROUTE#101#000001")]["decision"]["publications"]
    assert publications["anth-us"]["confidence"] == Decimal("0.9123")
    assert "confidence" not in publications["p-apyr-us"] and "confidence" not in publications["threat-intelligence"]


def test_ceilings_are_display_data_validated_and_ignored_by_routing():
    base = router_config()
    assert validate_router_config({**base, "ceilings": {"decisionsTotal": 300, "decisionsPerDay": 100, "items": 300}})["mode"] == "live"
    for bad in ({"decisionsTotal": 0}, {"decisionsPerDay": "many"}, {"items": -1}, {"surprise": 1}, "300"):
        with pytest.raises(ValueError):
            validate_router_config({**base, "ceilings": bad})


def test_all_exclude_routes_without_delivery(table):
    store, cyclotron = setup_router(table, maxItemsPerRun=1)
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
    store, cyclotron = setup_router(table, maxItemsPerRun=3)
    cyclotron.post_override["anth-us"] = (409, {"code": "source_refused"})
    go(table, store, cyclotron)
    assert set(routing_of(table).values()) == {"refused"}
    disc = table.items[("MONITOR#hn", "DISC#101#000001")]
    assert "gsi1pk" not in disc and table.items[("MONITOR#hn", "ROUTE#101#000001")]["final"]["reason"] == "source_refused"


def test_uncertain_post_is_never_repeated(table):
    store, cyclotron = setup_router(table, maxItemsPerRun=1)
    cyclotron.post_override["anth-us"] = (500, {})
    go(table, store, cyclotron)
    assert routing_of(table)["DISC#101#000001"] == "uncertain"
    cyclotron.post_override.clear()
    go(table, store, cyclotron, now=3000)
    assert [c for c in cyclotron.posts() if c[2]["payload"]["item"]["id"] == "hn-101"] == [cyclotron.posts()[0]]


def test_pending_job_is_resumed_by_polling_only(table):
    store, cyclotron = setup_router(table, maxItemsPerRun=1)
    cyclotron.pending_polls = 10_000
    state = {"t": 0}
    config = validate_router_config(table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"])
    ticking = CyclotronClient(config, sign=lambda m, u, b: {}, http=cyclotron.http,
                              sleep=lambda s: state.__setitem__("t", state["t"] + s), clock=lambda: state["t"])
    result = run_router(store, "hn", now=2000, cyclotron=ticking, appsync=lambda e: object(), deliver=Delivery(),
                        context_receipt=lambda c, p: {})
    assert result["stoppedBy"] == "pending" and routing_of(table)["DISC#101#000001"] == "collected"
    job = table.items[("MONITOR#hn", "ROUTE#101#000001")]["jobs"]["anth-us"]
    assert job["jobId"] and len(cyclotron.posts()) == 1
    cyclotron.pending_polls = 0
    go(table, store, cyclotron, now=2600)
    assert len(cyclotron.posts()) == 3          # one per publication in total: the anth-us POST was not repeated
    assert routing_of(table)["DISC#101#000001"] == "routed"


def test_divergent_decisions_are_an_error_not_a_delivery(table):
    store, cyclotron = setup_router(table, maxItemsPerRun=1)
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


def test_delivery_failure_is_isolated_per_publication_and_retried_with_backoff(table):
    store, cyclotron = setup_router(table, maxItemsPerRun=1)
    delivery = Delivery()
    delivery.fail = {"p-apyr-us"}
    go(table, store, cyclotron, deliver=delivery)
    route = table.items[("MONITOR#hn", "ROUTE#101#000001")]
    assert route["publications"]["anth-us"]["delivered"] and route["publications"]["threat-intelligence"]["delivered"]
    assert not route["publications"]["p-apyr-us"]["delivered"] and route["publications"]["p-apyr-us"]["attempts"] == 1
    assert "backend unavailable" in route["publications"]["p-apyr-us"]["lastError"]
    disc = table.items[("MONITOR#hn", "DISC#101#000001")]
    assert disc["routing"] == "decided" and disc["gsi1pk"] == "ROUTING#hn#decided"
    # not due yet: the decided item is skipped, new items proceed
    go(table, store, cyclotron, now=2100, deliver=delivery)
    assert route["publications"]["p-apyr-us"]["attempts"] == 1
    assert routing_of(table)["DISC#102#000001"] == "decided"    # a new item was decided and delivered to the healthy publications
    assert table.items[("MONITOR#hn", "ROUTE#102#000001")]["publications"]["anth-us"]["delivered"]
    delivery.fail = set()
    before = list(delivery.calls)
    go(table, store, cyclotron, now=2000 + 301, deliver=delivery)
    new_calls = delivery.calls[len(before):]
    assert ("p-apyr-us", "101") in {(p, s) for p, s, *_ in new_calls}
    assert not {(p, s) for p, s, *_ in new_calls} & {("anth-us", "101"), ("threat-intelligence", "101")}
    assert routing_of(table)["DISC#101#000001"] == "routed"
    assert len([k for k in table.items if k[1].startswith("DELIV#") and "-101" in k[1]]) == 3


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
    store, cyclotron = setup_router(table, maxItemsPerRun=1, feedback=True)
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
    store, cyclotron = setup_router(table, maxItemsPerRun=1, feedback=False)
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
    assert build.MODULES == ("__init__.py", "monitoring.py", "monitoring_cloud.py")
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
    assert {r.split("apis/")[1].split("/")[0] for r in relation_resources} == {"${AnthUsApiId}", "${PapyrusApiId}", "${ThreatIntelApiId}", "${DataParadeApiId}"}
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


def test_seed_script_sets_and_clears_ceilings():
    import importlib.util
    spec = importlib.util.spec_from_file_location("seed_router_config", ROOT / "infra" / "monitoring" / "seed_router_config.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    assert seed.coerce("ceilings", "decisionsTotal=300,decisionsPerDay=100,items=300") == {"decisionsTotal": 300, "decisionsPerDay": 100, "items": 300}
    assert seed.coerce("ceilings", "none") is None
    for bad in ("300", "decisionsTotal=many", "=5"):
        with pytest.raises(ValueError):
            seed.coerce("ceilings", bad)


# --- not-ready outputs (criteria_pending) --------------------------------------------------------------

def test_not_ready_binding_must_not_halt_the_sweep(table):
    """Reproduces the halt: one binding answers 409 criteria_pending; the others must still decide and deliver."""
    store, cyclotron = setup_router(table)
    cyclotron.post_override["threat-intelligence"] = (409, {"detail": "publication criteria are pending"})
    delivery = Delivery()
    result = go(table, store, cyclotron, deliver=delivery)
    assert result["status"] == "complete" and result["stoppedBy"] is None
    assert result["counts"]["routed"] == 3                      # every candidate item reached the ready bindings
    assert {c[0] for c in delivery.calls} == {"anth-us", "p-apyr-us"}
    assert result["counts"]["skippedNotReady"] == 3
    assert result["waitingForClassifier"] == ["threat-intelligence"]
    assert [c for c in cyclotron.posts() if c[1].split("/")[3] == "threat-intelligence"][0:1]   # probed once, not per item
    assert len([c for c in cyclotron.posts() if c[1].split("/")[3] == "threat-intelligence"]) == 1


def test_not_ready_binding_is_parked_probed_after_backoff_and_backfilled_when_ready(table):
    store, cyclotron = setup_router(table, maxItemsPerRun=1)
    cyclotron.post_override["threat-intelligence"] = (409, {"detail": "publication criteria are pending"})
    delivery = Delivery()
    ti = lambda: [c for c in cyclotron.posts() if c[1].split("/")[3] == "threat-intelligence"]
    first = go(table, store, cyclotron, now=2000, deliver=delivery)
    assert first["status"] == "complete" and len(ti()) == 1
    park = table.items[("MONITOR#hn", "PARK#threat-intelligence")]
    assert park["ready"] is False and park["nextProbeAt"] == 2000 + 1800 and len(park["items"]) == 1
    # inside the backoff window: no call at all for the waiting binding, other bindings carry on
    second = go(table, store, cyclotron, now=2300, deliver=delivery)
    assert len(ti()) == 1 and second["waitingForClassifier"] == ["threat-intelligence"]
    assert second["counts"]["decided"] == 1 and second["counts"]["skippedNotReady"] == 1
    # backoff elapsed and still pending: exactly one probe, backoff doubles
    third = go(table, store, cyclotron, now=3900, deliver=delivery)
    assert len(ti()) == 2 and third["status"] == "complete"
    park = table.items[("MONITOR#hn", "PARK#threat-intelligence")]
    assert park["backoffSeconds"] == 3600 and park["probes"] == 1 and len(park["items"]) == 3
    # classifier ready: the next item's probe succeeds, then parked items are decided one budget at a time
    cyclotron.post_override.clear()
    run_collection(DynamoStore(table), "hn", fetch=lambda url: FEED.replace(b"</channel>", b"<item><title>Delta source</title><link>https://example.org/delta</link><comments>https://news.ycombinator.com/item?id=104</comments></item></channel>"), now=7000)
    fourth = go(table, store, cyclotron, now=8000, deliver=delivery)
    assert fourth["waitingForClassifier"] == [] and fourth["status"] == "complete"
    for n in range(1, 6):
        go(table, store, cyclotron, now=8000 + 900 * n, deliver=delivery)
    assert {"101", "102", "103", "104"} == {c[1] for c in delivery.calls if c[0] == "threat-intelligence"}
    assert ("MONITOR#hn", "PARK#threat-intelligence") not in table.items


def test_other_409_and_ceiling_refusals_still_stop_the_sweep(table):
    store, cyclotron = setup_router(table)
    cyclotron.post_override["anth-us"] = (409, {"error": {"code": "something_else"}})
    result = go(table, store, cyclotron)
    assert result["status"] == "stopped" and result["stoppedBy"] == "something_else"
    assert ("MONITOR#hn", "PARK#anth-us") not in table.items


def test_typed_criteria_pending_code_is_also_not_ready(table):
    store, cyclotron = setup_router(table)
    cyclotron.post_override["anth-us"] = (409, {"error": {"code": "criteria_pending"}})
    assert go(table, store, cyclotron)["waitingForClassifier"] == ["anth-us"]


def test_all_bindings_not_ready_parks_the_item_without_looping(table):
    store, cyclotron = setup_router(table)
    for pub in PUBS:
        cyclotron.post_override[pub] = (409, {"code": "criteria_pending"})
    result = go(table, store, cyclotron)
    assert result["status"] == "complete" and result["counts"]["parked"] == 3
    assert sorted(result["waitingForClassifier"]) == sorted(PUBS)
    assert set(routing_of(table).values()) == {"parked"}


def test_resumed_route_with_a_stored_confidence_saves_without_float_errors(table):
    """A sweep that stops mid-item leaves checked jobs with confidence; the next run reads them back as floats."""
    store, cyclotron = setup_router(table, maxItemsPerRun=1)
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
    store, cyclotron = setup_router(table, maxItemsPerRun=1)
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
    lab.table.put_item(router_config(maxItemsPerRun=1, decisions="direct", cyclotron=None))
    mr_result = go(lab.table, lab.store, None, now=2000, deliver=mr.deliver_reference,
                   appsync=lambda endpoint: lab.clients.setdefault(endpoint, LabAppSync(endpoint, "knowledge-corpus-" + (
                       "ai-ml-research" if "api1" in endpoint else "anth-us" if "api0" in endpoint else "threat-intelligence"))))
    assert mr_result["counts"]["delivered"] == 3
    assert not any(c.relations() for c in lab.clients.values())
