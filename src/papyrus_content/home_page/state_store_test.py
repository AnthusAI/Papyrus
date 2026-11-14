"""The private state and the list of changed rows in the projection lock table, against an in-memory table."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from papyrus_content.home_page.export import Standing
from papyrus_content.home_page.incremental import StoredState
from papyrus_content.home_page.state_store import DirtyBatch, DirtyStore, DynamoStateStore, dirty_key, full_key, shard_key, state_key


class ConditionFailed(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    """Just enough of a boto3 Table: whole-item get and put, and the three update expressions the stores use."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []

    def get_item(self, *, Key: dict, ConsistentRead: bool = False) -> dict:
        self.calls.append("get")
        item = self.items.get(Key["publication"])
        return {"Item": copy.deepcopy(item)} if item is not None else {}

    def put_item(self, *, Item: dict) -> None:
        self.calls.append("put")
        self.items[Item["publication"]] = copy.deepcopy(Item)

    def update_item(self, *, Key: dict, UpdateExpression: str, ExpressionAttributeValues: dict, ConditionExpression: str | None = None) -> None:
        self.calls.append("update")
        item = self.items.setdefault(Key["publication"], {"publication": Key["publication"]})
        if UpdateExpression == "DELETE ids :read":
            item["ids"] = set(item.get("ids") or ()) - ExpressionAttributeValues[":read"]
            if not item["ids"]:
                del item["ids"]
            return
        attribute = UpdateExpression.removeprefix("REMOVE ")
        if item.get(attribute) != ExpressionAttributeValues[":seen"]:
            raise ConditionFailed()
        del item[attribute]


def state(count: int = 40) -> StoredState:
    entries = {f"{index:012x}": Standing(f"reference-{index}-v1", index % 6 or None, index / 100, f"2026-10-{1 + index % 28:02d}T00:00:00.000Z", None) for index in range(count)}
    return StoredState("fingerprint", "sha", entries)


def test_state_round_trips_through_the_table():
    table, saved = FakeTable(), state()
    DynamoStateStore(table, "site").save(saved)
    assert DynamoStateStore(table, "site").load() == saved
    assert DynamoStateStore(table, "another").load() is None


def test_only_the_shards_that_changed_are_written_again():
    table, saved = FakeTable(), state(200)
    store = DynamoStateStore(table, "site")
    store.save(saved)
    store.load()
    table.calls.clear()
    changed = dict(saved.entries)
    key = next(iter(changed))
    changed[key] = Standing("reference-x-v1", 5, 0.9, None, None)
    store.save(StoredState("fingerprint", "sha2", changed))
    assert table.calls.count("put") == 2, "one shard and the header"


def test_a_half_written_state_is_not_trusted():
    table = FakeTable()
    store = DynamoStateStore(table, "site")
    store.save(state())
    del table.items[shard_key("site", next(digit for digit in "0123456789abcdef" if shard_key("site", digit) in table.items))]
    assert DynamoStateStore(table, "site").load() is None


def test_the_state_never_holds_a_public_key_beside_its_stars_in_one_readable_attribute():
    table = FakeTable()
    DynamoStateStore(table, "site").save(state())
    assert all(isinstance(item.get("entries", b""), bytes) for item in table.items.values()), "shards are compressed, not readable text"


def test_a_run_takes_out_exactly_the_changes_it_read():
    table = FakeTable()
    table.items[dirty_key("site")] = {"publication": dirty_key("site"), "ids": {"a", "b"}, "messageSeq": 2}
    table.items[full_key("site")] = {"publication": full_key("site"), "seq": 1}
    store = DirtyStore(table, "site")
    batch = store.read()
    assert batch == DirtyBatch(ids=frozenset({"a", "b"}), message_seq=2, full_seq=1) and batch.full and batch.messages
    table.items[dirty_key("site")]["ids"].add("c")        # a change lands while the run works
    table.items[dirty_key("site")]["messageSeq"] = 3
    store.acknowledge(batch)
    after = store.read()
    assert after.ids == {"c"} and after.message_seq == 3 and not after.full


def test_nothing_changed_is_an_empty_batch():
    batch = DirtyStore(FakeTable(), "site").read()
    assert batch == DirtyBatch() and not batch.full and not batch.messages
    DirtyStore(FakeTable(), "site").acknowledge(batch)


def test_a_counter_that_is_not_the_one_read_is_left_alone():
    table = FakeTable()
    table.items[dirty_key("site")] = {"publication": dirty_key("site"), "messageSeq": 5}
    store = DirtyStore(table, "site")
    with pytest.raises(ConditionFailed):
        table.update_item(Key={"publication": dirty_key("site")}, UpdateExpression="REMOVE messageSeq", ConditionExpression="messageSeq = :seen", ExpressionAttributeValues={":seen": 4})
    store.acknowledge(DirtyBatch(message_seq=4))
    assert table.items[dirty_key("site")]["messageSeq"] == 5


def test_the_header_key_names_one_site():
    assert state_key("a") != state_key("b") and shard_key("a", "0") != shard_key("a", "1")
