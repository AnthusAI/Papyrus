from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor
LINEAGE = "story-1"

class FakeClient:
    def __init__(self):
        self.tables = {"Item": {LINEAGE: {"id": LINEAGE, "lineageId": LINEAGE, "versionNumber": 1, "versionState": "current", "type": "article", "slug": "story", "section": None, "status": "draft", "stage": "reporting", "title": "Story", "aliases": [], "metadata": "{}", "bodyMarkus": "Original."}}}
    def list_by_index(self, index, key, **kwargs):
        if index == "itemsByLineageAndVersion": return list(self.tables["Item"].values())
        raise AssertionError(index)

def client_with_one_story(): return FakeClient()
from papyrus_content.story_reporting import save_story_version


def test_two_same_version_saves_have_one_winner():
    client = client_with_one_story()
    lock = threading.Lock()
    barrier = threading.Barrier(2)
    original_list = client.list_by_index
    def snapshot(index, key, **kwargs):
        result = copy.deepcopy(original_list(index, key, **kwargs))
        if index == "itemsByLineageAndVersion": barrier.wait(timeout=5)
        return result
    client.list_by_index = snapshot
    def persist(lineage, expected, record):
        with lock:
            items = client.tables["Item"]
            if items[expected]["versionState"] != "current" or record["id"] in items:
                raise ValueError("stale_version")
            items[expected]["versionState"] = "superseded"
            items[record["id"]] = record
    def save(body):
        try:
            return save_story_version(client, LINEAGE, front_matter_yaml="title: Story", body_markus=body,
                                      actor="AI", change_reason="draft", expected_current_id=LINEAGE, atomic_persist=persist)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ("First draft.", "Second draft.")))
    assert sum(value is not None for value in results) == 1
    assert sum(row["versionState"] == "current" for row in client.tables["Item"].values()) == 1
    assert next(value for value in results if value)["versionCreatedBy"] == "AI"


def test_conflicting_new_id_is_not_overwritten():
    client = client_with_one_story()
    def persist(lineage, expected, record):
        # Another writer wins the ID after the initial snapshot, before this transaction.
        claimed = dict(record, bodyMarkus="Other writer", versionState="superseded")
        client.tables["Item"][record["id"]] = claimed
        if record["id"] in client.tables["Item"]:
            raise ValueError("new ID already exists")

    before = copy.deepcopy(client.tables)
    try:
        save_story_version(client, LINEAGE, front_matter_yaml="title: Story", body_markus="Draft.", actor="AI",
                           change_reason="draft", expected_current_id=LINEAGE, atomic_persist=persist)
        assert False, "save should fail"
    except ValueError as error:
        assert str(error) == "new ID already exists"
    assert client.tables["Item"][LINEAGE] == before["Item"][LINEAGE]
    assert client.tables["Item"][f"{LINEAGE}-v2"]["bodyMarkus"] == "Other writer"


def test_stale_version_and_missing_atomic_hook_fail_before_writing():
    client = client_with_one_story()
    before = copy.deepcopy(client.tables)
    for expected, hook in (("older", lambda *_: (_ for _ in ()).throw(AssertionError("must not persist"))), (LINEAGE, None)):
        try:
            save_story_version(client, LINEAGE, front_matter_yaml="title: Story", body_markus="Draft.", actor="AI",
                               change_reason="draft", expected_current_id=expected, atomic_persist=hook)
            assert False, "unsafe save was accepted"
        except ValueError:
            pass
    assert client.tables == before
