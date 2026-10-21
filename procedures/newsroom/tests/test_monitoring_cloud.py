"""Cloud HN collector: DynamoDB-backed store against a hand-rolled fake table, plus template checks."""
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from papyrus_content.monitoring_cloud import DynamoStore, handler, run_collection

FEED = b'''<rss><channel>
<item><title>Real-shaped AI source</title><link>https://example.org/paper?utm_source=hn</link><comments>https://news.ycombinator.com/item?id=123</comments><pubDate>Mon, 19 Oct 2026 10:00:00 +0000</pubDate></item>
<item><title>Security source</title><link>https://example.org/security</link><comments>https://news.ycombinator.com/item?id=124</comments></item>
</channel></rss>'''
CONFIG = {"pk": "MONITOR#hn", "sk": "CONFIG", "sourceUrl": "https://news.ycombinator.com/rss",
          "intervalSeconds": 900, "limit": 30, "enabled": True}
TEMPLATE = Path(__file__).resolve().parents[3] / "infra" / "monitoring" / "papyrus-monitoring.yaml"


class Conditional(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    """Implements exactly the conditional writes DynamoStore issues; round-trips numbers as Decimal."""

    def __init__(self):
        self.items = {}

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
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeValues=None):
        key, existing = (Item["pk"], Item["sk"]), self.items.get((Item["pk"], Item["sk"]))
        if ConditionExpression == "attribute_not_exists(pk)" and existing:
            raise Conditional()
        if ConditionExpression == "attribute_not_exists(pk) OR expiresAt < :now" and existing:
            if not existing["expiresAt"] < ExpressionAttributeValues[":now"]:
                raise Conditional()
        self.items[key] = self._dec(Item)

    def delete_item(self, Key, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        existing = self.items.get((Key["pk"], Key["sk"]))
        if not existing or existing["owner"] != ExpressionAttributeValues[":owner"]:
            raise Conditional()
        del self.items[(Key["pk"], Key["sk"])]

    def by_prefix(self, prefix):
        return [v for k, v in sorted(self.items.items()) if k[1].startswith(prefix)]


@pytest.fixture
def table():
    t = FakeTable()
    t.put_item(CONFIG)
    return t


@pytest.fixture
def store(table):
    return DynamoStore(table)


def run(store, feed=FEED, **kwargs):
    return run_collection(store, "hn", fetch=lambda url: feed, **kwargs)


def test_first_run_collects_and_records_receipt(store, table):
    result = run(store, now=1000)
    assert (result["status"], result["new"], result["unchanged"], result["errorCount"]) == ("complete", 2, 0, 0)
    receipt = table.by_prefix("RUN#")[0]
    assert receipt["runId"] == result["runId"] and receipt["new"] == 2 and receipt["status"] == "complete"
    assert receipt["ttl"] > 1000 and receipt["nextDueAt"] == "1970-01-01T00:31:40Z"
    discoveries = table.by_prefix("DISC#")
    assert [d["sk"] for d in discoveries] == ["DISC#123#000001", "DISC#124#000001"]
    assert all(d["routing"] == "collected" and d["gsi1pk"] == "ROUTING#hn#collected" for d in discoveries)
    assert "utm_source" not in discoveries[0]["canonicalUrl"]
    assert ("MONITOR#hn", "LOCK") not in table.items


def test_second_run_within_interval_is_not_due(store, table):
    run(store, now=1000)
    again = run(store, now=1100)
    assert again["status"] == "not_due" and len(table.by_prefix("RUN#")) == 1
    assert run(store, now=1000 + 900 - 30)["status"] == "complete"  # scheduler jitter slack


def test_forced_run_dedupes_and_revises_changed_title(store, table):
    run(store, now=1000)
    again = run(store, now=1001, force=True)
    assert (again["new"], again["revised"], again["unchanged"]) == (0, 0, 2)
    revised = run(store, FEED.replace(b"AI source", b"AI update"), now=1002, force=True)
    assert (revised["new"], revised["revised"], revised["unchanged"]) == (0, 1, 1)
    assert table.items[("MONITOR#hn", "ITEM#123")]["revision"] == 2
    assert table.items[("MONITOR#hn", "DISC#123#000002")]["title"] == "Real-shaped AI update"
    assert len(table.by_prefix("DISC#")) == 3


def test_event_id_matches_local_collector_digest(store, table):
    from papyrus_content.monitoring import _digest, parse_hn_feed
    run(store, now=1000)
    item = parse_hn_feed(FEED)[0]
    binding = {"monitorId": "hn", "sourceUrl": CONFIG["sourceUrl"]}
    assert table.items[("MONITOR#hn", "DISC#123#000001")]["eventId"] == _digest([binding, "123", item.fingerprint])


def test_live_lease_refuses_and_expired_lease_is_taken_over(store, table):
    assert store.acquire_lock("hn", "other", now=1000)
    assert run(store, now=1010, owner="me")["status"] == "locked"
    assert ("MONITOR#hn", "LOCK") in table.items and not table.by_prefix("RUN#")
    taken = run(store, now=1000 + 151, owner="me")
    assert taken["status"] == "complete" and ("MONITOR#hn", "LOCK") not in table.items


def test_release_does_not_delete_a_lock_owned_by_someone_else(store, table):
    store.acquire_lock("hn", "a", now=1000)
    store.release_lock("hn", "b")
    assert table.items[("MONITOR#hn", "LOCK")]["owner"] == "a"


def test_fetch_failure_is_a_failed_receipt_and_keeps_earlier_items(store, table):
    run(store, now=1000)

    def boom(url):
        raise OSError("network down")

    failed = run_collection(store, "hn", fetch=boom, now=2000)
    assert failed["status"] == "failed" and failed["errors"][0]["stage"] == "fetch"
    receipts = table.by_prefix("RUN#")
    assert [r["status"] for r in receipts] == ["complete", "failed"]
    assert len(table.by_prefix("ITEM#")) == 2 and len(table.by_prefix("DISC#")) == 2
    assert run(store, now=2000 + 900)["unchanged"] == 2


def test_later_item_failure_cannot_erase_earlier_progress(store, table):
    original = table.put_item

    def flaky(Item, **kwargs):
        if Item["sk"] == "ITEM#124":
            raise RuntimeError("throttled")
        return original(Item, **kwargs)

    table.put_item = flaky
    result = run(store, now=1000)
    assert result["status"] == "partial" and result["new"] == 1 and result["errors"][0]["sourceId"] == "124"
    table.put_item = original
    retry = run(store, now=1001, force=True)
    assert (retry["new"], retry["unchanged"]) == (1, 1)  # 123 unchanged; 124 retried, existing discovery tolerated
    assert len(table.by_prefix("DISC#")) == 2


@pytest.mark.parametrize("feed", [b'<!DOCTYPE rss [<!ENTITY x "y">]><rss><channel></channel></rss>',
                                  b"<html>error</html>", b"x" * 2_000_001])
def test_bad_feeds_are_rejected_as_failed_runs(store, table, feed):
    result = run(store, feed, now=1000)
    assert result["status"] == "failed" and not table.by_prefix("DISC#")


def test_missing_disabled_and_invalid_config(store, table):
    assert run_collection(DynamoStore(FakeTable()), "hn", fetch=lambda u: FEED, now=1)["status"] == "not_configured"
    table.put_item({**CONFIG, "enabled": False})
    assert run(store, now=1)["status"] == "disabled"
    table.put_item({**CONFIG, "sourceUrl": "https://example.org/rss"})
    with pytest.raises(ValueError):
        run(store, now=1)
    table.put_item({**CONFIG, "limit": 500})
    with pytest.raises(ValueError):
        run(store, now=1)


def test_limit_bounds_items_collected(store, table):
    table.put_item({**CONFIG, "limit": 1})
    assert run(store, now=1)["new"] == 1


def test_handler_raises_on_failed_run_and_returns_summary(monkeypatch, table):
    import sys
    import types

    class Resource:
        def Table(self, name):
            assert name == "t"
            return table

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(resource=lambda service: Resource()))
    monkeypatch.setenv("TABLE_NAME", "t")
    monkeypatch.setattr("papyrus_content.monitoring_cloud.fetch_hn_feed", lambda url: FEED)
    assert handler({}, None)["status"] == "complete"
    monkeypatch.setattr("papyrus_content.monitoring_cloud.fetch_hn_feed", lambda url: b"<html/>")
    with pytest.raises(RuntimeError):
        handler({"force": True}, None)


def test_dynamodb_store_with_moto_when_available():
    moto = pytest.importorskip("moto")
    import boto3
    with moto.mock_aws():
        boto3.setup_default_session(aws_access_key_id="x", aws_secret_access_key="x", region_name="us-east-1")
        ddb = boto3.resource("dynamodb")
        ddb.create_table(TableName="t", BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}])
        t = ddb.Table("t")
        t.put_item(Item=CONFIG)
        s = DynamoStore(t)
        assert s.acquire_lock("hn", "a", 1000) and not s.acquire_lock("hn", "b", 1001)
        assert s.acquire_lock("hn", "b", 1000 + 151)
        s.release_lock("hn", "a")
        s.release_lock("hn", "b")
        first = run(s, now=5000)
        again = run(s, now=5001, force=True)
        assert first["new"] == 2 and again["unchanged"] == 2


# --- template ---------------------------------------------------------------------------------

class Loader(yaml.SafeLoader):
    pass


Loader.add_multi_constructor("!", lambda loader, suffix, node: {
    "Fn::" + suffix if suffix != "Ref" else "Ref":
        loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode)
        else loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node)})


PARAMETERS = yaml.load(TEMPLATE.read_text(), Loader=Loader)["Parameters"]


@pytest.fixture(scope="module")
def template():
    return yaml.load(TEMPLATE.read_text(), Loader=Loader)["Resources"]


def test_template_inventory(template):
    assert {r["Type"] for r in template.values()} == {
        "AWS::DynamoDB::Table", "AWS::Logs::LogGroup", "AWS::IAM::Role", "AWS::Lambda::Function",
        "AWS::SQS::Queue", "AWS::Scheduler::Schedule", "AWS::CloudWatch::Alarm", "AWS::Lambda::EventInvokeConfig",
        "AWS::SSM::Parameter"}


def test_template_function_and_schedule(template):
    function = template["CollectorFunction"]["Properties"]
    assert function["ReservedConcurrentExecutions"]["Fn::If"][:2] == ["ReserveConcurrency", {"Ref": "ReservedConcurrency"}]
    assert PARAMETERS["ReservedConcurrency"]["Default"] == 1 and function["Runtime"] == "python3.13"
    assert function["MemorySize"] == 256 and function["Timeout"] == 120
    schedule = template["CollectSchedule"]["Properties"]
    assert schedule["ScheduleExpression"] == "rate(15 minutes)" and schedule["FlexibleTimeWindow"] == {"Mode": "OFF"}
    assert schedule["Target"]["RetryPolicy"]["MaximumRetryAttempts"] >= 1 and "DeadLetterConfig" in schedule["Target"]
    assert template["MonitoringTable"]["DeletionPolicy"] == "Retain"
    assert template["MonitoringTable"]["UpdateReplacePolicy"] == "Retain"
    assert template["MonitoringTable"]["Properties"]["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"]
    assert template["MonitoringTable"]["Properties"]["SSESpecification"]["SSEEnabled"]
    assert template["MonitoringTable"]["Properties"]["BillingMode"] == "PAY_PER_REQUEST"


def test_template_iam_has_no_wildcard_resources(template):
    for name in ("CollectorRole", "ScheduleRole"):
        for policy in template[name]["Properties"]["Policies"]:
            for statement in policy["PolicyDocument"]["Statement"]:
                resources = statement["Resource"] if isinstance(statement["Resource"], list) else [statement["Resource"]]
                assert resources and all(r != "*" for r in resources)
                assert all("*" not in a for a in (statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]))
    collector = str(template["CollectorRole"]["Properties"]["Policies"])
    assert "appsync" not in collector.lower() and "secretsmanager" not in collector.lower()
