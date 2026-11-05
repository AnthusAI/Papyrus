"""The private Story rating store (``story_stars.py``): one read to load, one request per Story not seen before, and entries that never overwrite each other."""

from __future__ import annotations

from papyrus_content.projection.story_stars import DynamoStarStore, MemoryStarStore, known_stars, scope_of, star_store_from_environment, state_key, stars_of_lineage


class FakeTable:
    """Enough of a DynamoDB table for ``get_item`` and the two ``update_item`` forms the store uses."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.calls: list[str] = []

    def get_item(self, Key, ConsistentRead=False):
        self.calls.append("get")
        assert ConsistentRead is True
        item = self.items.get(Key["publication"])
        return {"Item": item} if item is not None else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None):
        self.calls.append("update")
        item = self.items.setdefault(Key["publication"], {"publication": Key["publication"]})
        if UpdateExpression.startswith("SET stars = if_not_exists"):
            item.setdefault("stars", dict(ExpressionAttributeValues[":empty"]))
            return
        names = ExpressionAttributeNames or {}
        for assignment in UpdateExpression.removeprefix("SET ").split(", "):
            target, value = assignment.split(" = ")
            item["stars"][names[target.removeprefix("stars.")]] = ExpressionAttributeValues[value]


def test_the_dynamo_store_loads_in_one_read_and_records_each_entry_under_its_own_key():
    table = FakeTable()
    store = DynamoStarStore(table, "abcd1234")
    assert store.load() == {} and table.calls == ["get"]
    store.record({"lineage-a": 4, "lineage-b": 0})
    store.record({"lineage-a": 5})
    assert table.items[state_key("abcd1234")]["stars"] == {"lineage-a": 5, "lineage-b": 0}
    assert store.load() == {"lineage-a": 5, "lineage-b": 0}
    store.record({})
    assert table.calls.count("update") == 4, "an empty record asks for nothing"


def test_the_store_is_scoped_to_the_site_so_two_sites_never_share_an_entry():
    assert state_key(scope_of("site-one-content-actions")) != state_key(scope_of("site-two-content-actions"))
    assert state_key(scope_of("site-one-content-actions")) == state_key(scope_of("site-one-content-actions"))


def test_a_lineage_the_store_has_not_seen_is_read_once_and_remembered():
    store = MemoryStarStore({"seen": 3})
    reads: list[str] = []

    def read(lineage: str) -> int:
        reads.append(lineage)
        return {"new-rated": 5}.get(lineage, 0)

    first = known_stars(store, ["seen", "new-rated", "new-unrated", "seen", ""], read)
    assert first == {"seen": 3, "new-rated": 5}
    assert reads == ["new-rated", "new-unrated"]
    assert known_stars(store, ["seen", "new-rated", "new-unrated"], read) == first
    assert reads == ["new-rated", "new-unrated"], "a Story known as unrated is not read again"


def test_stars_of_lineage_reads_the_current_version_and_unrated_means_zero():
    class Client:
        def list_by_index(self, index, lineage):
            assert index == "itemsByLineageAndVersion"
            return {
                "rated": [
                    {"id": "r1", "versionNumber": 1, "versionState": "superseded", "versionCreatedAt": "2026-01-01", "starRating": 2},
                    {"id": "r2", "versionNumber": 2, "versionState": "current", "versionCreatedAt": "2026-01-02", "starRating": 4},
                ],
                "cleared": [
                    {"id": "c1", "versionNumber": 1, "versionState": "superseded", "versionCreatedAt": "2026-01-01", "starRating": 5},
                    {"id": "c2", "versionNumber": 2, "versionState": "current", "versionCreatedAt": "2026-01-02", "starRating": None},
                ],
            }.get(lineage, [])

    assert stars_of_lineage(Client(), "rated") == 4
    assert stars_of_lineage(Client(), "cleared") == 0, "an older version's stale rating does not count once the working record is cleared"
    assert stars_of_lineage(Client(), "missing") == 0


def test_without_a_function_name_or_a_lock_table_there_is_no_store_and_listings_stay_newest_first():
    assert star_store_from_environment({}) is None
    store = star_store_from_environment({"AWS_LAMBDA_FUNCTION_NAME": "site-content-actions"}, table=FakeTable())
    assert isinstance(store, DynamoStarStore) and store.scope == scope_of("site-content-actions")
    operator = star_store_from_environment({"PAPYRUS_CONTENT_ACTIONS_FUNCTION": "site-content-actions"}, table=FakeTable())
    assert operator is not None and operator.scope == store.scope, "an operator's local run finds the same entry the Lambda writes"
