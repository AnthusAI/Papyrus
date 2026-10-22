import json
from types import SimpleNamespace

import pytest

from papyrus_content.projection.writers import LocalDirectoryWriter

from .archive import ArchiveError, HISTORY_INDEX_FILE, archive_entry, identity_of
from .model import Cluster


def cluster(event, predecessors=(), uid="c1"):
    return Cluster(uid=uid, accepted=False, name=None, event=event, top_terms=(), weekly_series={}, earliest_published_at=None,
                   member_item_keys=(), member_count=0, run_id="r", predecessor_uids=tuple(predecessors))


def test_identity_statuses():
    assert identity_of(cluster("new")) == {"status": "new"}
    assert identity_of(cluster("continued", ["old"])) == {"status": "continued", "predecessor": "old"}
    assert identity_of(cluster("continued")) == {"status": "continued", "predecessor": "c1"}
    assert identity_of(cluster("merged", ["b", "a"])) == {"status": "merged", "sources": ["a", "b"]}
    assert identity_of(cluster("split", ["a"])) == {"status": "split", "source": "a"}


@pytest.mark.parametrize("event,predecessors", [("merged", []), ("split", ["a", "b"]), ("split", []), ("renamed", ["a"]), (None, [])])
def test_identity_refuses_what_it_cannot_describe(event, predecessors):
    with pytest.raises(ArchiveError):
        identity_of(cluster(event, predecessors))


def entry(as_of, run_id="r"):
    return {"asOf": as_of, "runId": run_id, "runAsOf": as_of, "archivedAt": "2026-10-19T06:00:00Z",
            "counts": {"entities": 1, "topics": 0, "clusters": 1}, "clusters": [{"uid": "c1", "identity": {"status": "new"}}]}


def test_the_index_heals_from_entries_it_misses_and_a_corrupt_entry_is_never_overwritten(tmp_path):
    writer = LocalDirectoryWriter(tmp_path)
    context = SimpleNamespace(writer=writer, projector=None, invalidate=None)
    archive_entry(context, entry("2026-10-12"))
    writer.delete(HISTORY_INDEX_FILE)
    archive_entry(context, entry("2026-10-19"))
    index = [row["asOf"] for row in json.loads(writer.get(HISTORY_INDEX_FILE))["entries"]]
    assert index == ["2026-10-12", "2026-10-19"]
    writer.put("_data/knowledge/history/2026-10-26.json", b"{not json")
    with pytest.raises(ArchiveError, match="not valid JSON"):
        archive_entry(context, entry("2026-10-26"), replace=False)
    assert writer.get("_data/knowledge/history/2026-10-26.json") == b"{not json"


def test_the_edge_purge_covers_what_was_written_and_a_failure_is_reported(tmp_path):
    purged = []
    def invalidate(keys):
        purged.extend(keys)
        raise RuntimeError("down")
    context = SimpleNamespace(writer=LocalDirectoryWriter(tmp_path), projector=None, invalidate=invalidate)
    result = archive_entry(context, entry("2026-10-19"))
    assert result["purgeError"] == "RuntimeError" and len(purged) == 2
