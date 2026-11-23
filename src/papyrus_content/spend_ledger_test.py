from __future__ import annotations

from datetime import datetime, timezone

from botocore.exceptions import ClientError


class FakeLedgerTable:
    """The monitoring table as far as the ledger uses it: transactional puts with a not-exists condition, and numeric ADD updates."""

    name = "monitoring"

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}
        self.transactions = 0
        self.meta = type("Meta", (), {"client": self})()

    def transact_write_items(self, TransactItems):
        self.transactions += 1
        for item in TransactItems:
            put = item.get("Put")
            if put and (put["Item"]["pk"], put["Item"]["sk"]) in self.rows:
                raise ClientError({"Error": {"Code": "TransactionCanceledException", "Message": "cancelled"},
                                   "CancellationReasons": [{"Code": "ConditionalCheckFailed"}]}, "TransactWriteItems")
        for item in TransactItems:
            if "Put" in item:
                self.rows[(item["Put"]["Item"]["pk"], item["Put"]["Item"]["sk"])] = dict(item["Put"]["Item"])
            else:
                update = item["Update"]
                row = self.rows.setdefault((update["Key"]["pk"], update["Key"]["sk"]), dict(update["Key"]))
                values = update["ExpressionAttributeValues"]
                additions, setting = update["UpdateExpression"].removeprefix("ADD ").split(" SET ")
                for addition in additions.split(", "):
                    field, name = addition.split()
                    row[field] = row.get(field, 0) + values[name]
                field, name = setting.split(" = ")
                row[field] = values[name]

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ReturnValues=None):
        """The one update the X counter makes: ADD microUsd :cost, calls :one SET updatedAt = :stamp."""
        assert UpdateExpression == "ADD microUsd :cost, calls :one SET updatedAt = :stamp", UpdateExpression
        row = self.rows.setdefault((Key["pk"], Key["sk"]), dict(Key))
        row["microUsd"] = row.get("microUsd", 0) + ExpressionAttributeValues[":cost"]
        row["calls"] = row.get("calls", 0) + ExpressionAttributeValues[":one"]
        row["updatedAt"] = ExpressionAttributeValues[":stamp"]
        return {"Attributes": dict(row)} if ReturnValues == "ALL_NEW" else {}

    def get_item(self, Key, ConsistentRead=False):
        row = self.rows.get((Key["pk"], Key["sk"]))
        return {"Item": dict(row)} if row else {}


MOMENT = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)   # a Wednesday


def test_a_run_with_no_model_call_adds_nothing():
    from papyrus_content.procedure_runner import record_spend, spend_of

    class Decision:
        responsibility, state = "rate", None

    assert spend_of({"tenantId": "alpha"}, Decision(), {"toolsUsed": {"x": 1}}, None) is None
    assert spend_of({"tenantId": "alpha"}, Decision(), None, None) is None
    table = FakeLedgerTable()
    record_spend(table, None, {"runId": "run-1", "spend": None})
    assert table.rows == {} and table.transactions == 0


def test_a_site_with_no_budget_is_counted_by_the_month():
    from papyrus_content.procedure_runner import spend_of

    class Decision:
        responsibility, state = None, None

    spend = spend_of({"tenantId": "alpha"}, Decision(), {"calls": 2, "unpricedCalls": 0}, 0.01)
    assert spend["period"] == "month" and spend["responsibility"] is None


def test_the_cycle_is_the_day_the_monday_or_the_first():
    from papyrus_content.spend_ledger import cycle_start

    assert cycle_start("day", MOMENT).isoformat() == "2026-11-18"
    assert cycle_start("week", MOMENT).isoformat() == "2026-11-16"
    assert cycle_start("month", MOMENT).isoformat() == "2026-11-01"
