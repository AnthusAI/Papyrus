import json
from datetime import date
from types import SimpleNamespace

from papyrus_content.projection.standard.knowledge import KnowledgeSource
from papyrus_content.projection.standard.knowledge_lookup import KnowledgeLookup
from papyrus_content.projection.writers import LocalDirectoryWriter

from .archive import HISTORY_DIRECTORY, entry_file
from .builder import CLUSTERS_HISTORY_FILE, build_files
from .cluster_history import events_of, history_file, identity_of, valid_weeks, week_entry, weeks_from_archive
from .commands import previous_cluster_history
from .model import Cluster, KnowledgeData, SnapshotOptions, UNACCEPTED_UNNAMED


def cluster(uid, event="continued", predecessors=(), run_id="run", run_as_of="2026-10-19", accepted=True, count=3):
    return Cluster(uid=uid, accepted=accepted, name=f"Name {uid}" if accepted else None, event=event, top_terms=(), weekly_series={},
                   earliest_published_at=None, member_item_keys=(), member_count=count, run_id=run_id, run_as_of=run_as_of,
                   predecessor_uids=tuple(predecessors))


def snapshot(clusters, as_of, previous=None, **options):
    files = build_files(KnowledgeData(clusters=tuple(clusters)), SnapshotOptions(as_of=as_of, **options), previous)
    return files[CLUSTERS_HISTORY_FILE]


def test_events_cover_born_continued_merged_from_and_split_into():
    rows = [
        {"uid": "b", "identity": {"status": "new"}},
        {"uid": "a", "identity": {"status": "continued", "predecessor": "a"}},
        {"uid": "m", "identity": {"status": "merged", "sources": ["y", "x"]}},
        {"uid": "s2", "identity": {"status": "split", "source": "p"}},
        {"uid": "s1", "identity": {"status": "split", "source": "p"}},
    ]
    assert events_of(rows) == [
        {"event": "born", "uid": "b"},
        {"event": "continued", "uid": "a", "from": "a"},
        {"event": "merged_from", "uid": "m", "sources": ["x", "y"]},
        {"event": "split_into", "uid": "p", "into": ["s1", "s2"]},
    ]


def test_an_event_that_cannot_be_described_is_reported_as_born_not_a_failure():
    assert identity_of(cluster("c", "merged")) == {"status": "new"}
    assert identity_of(cluster("c", "split", ["a", "b"])) == {"status": "new"}
    assert identity_of(cluster("c", "renamed", ["a"])) == {"status": "new"}


def test_the_week_is_filed_under_its_monday_and_clusters_are_sorted():
    entry = week_entry("2026-10-22", "r", [{"uid": "z", "label": None, "itemCount": 1, "identity": {"status": "new"}},
                                          {"uid": "a", "label": "A", "itemCount": 2, "identity": {"status": "new"}}])
    assert entry["asOf"] == "2026-10-19"
    assert [row["uid"] for row in entry["clusters"]] == ["a", "z"]


def test_the_history_carries_earlier_weeks_forward_and_replaces_the_same_week():
    first = snapshot([cluster("a", "new", run_as_of="2026-10-12")], date(2026, 10, 12))
    second = snapshot([cluster("a", count=5)], date(2026, 10, 19), first)
    again = snapshot([cluster("a", count=7)], date(2026, 10, 21), second)
    assert [week["asOf"] for week in again["weeks"]] == ["2026-10-12", "2026-10-19"]
    assert again["weeks"][0] == first["weeks"][0]
    assert again["weeks"][1]["clusters"][0]["itemCount"] == 7
    assert again["asOf"] == "2026-10-21"


def test_a_run_from_an_earlier_week_is_not_filed_under_this_week():
    first = snapshot([cluster("a", "new", run_as_of="2026-10-12")], date(2026, 10, 12))
    stale = snapshot([cluster("a", "new", run_as_of="2026-10-12")], date(2026, 10, 19), first)
    assert [week["asOf"] for week in stale["weeks"]] == ["2026-10-12"]


def test_no_cluster_run_gives_an_empty_history_and_a_foreign_previous_file_is_ignored():
    assert snapshot([], date(2026, 10, 19))["weeks"] == []
    assert valid_weeks({"schemaVersion": 2, "weeks": []}, 1) is None
    assert valid_weeks({"schemaVersion": 1, "weeks": ["x"]}, 1) is None
    assert snapshot([cluster("a")], date(2026, 10, 19), {"schemaVersion": 9})["weeks"][0]["asOf"] == "2026-10-19"


def test_unnamed_clusters_follow_the_clusters_file_rule():
    clusters = [cluster("n"), cluster("u", accepted=False)]
    assert [row["uid"] for row in snapshot(clusters, date(2026, 10, 19))["weeks"][0]["clusters"]] == ["n"]
    unnamed = snapshot(clusters, date(2026, 10, 19), unaccepted_clusters=UNACCEPTED_UNNAMED)["weeks"][0]["clusters"]
    assert [(row["uid"], row["label"]) for row in unnamed] == [("n", "Name n"), ("u", None)]


def test_history_carries_no_identity_data():
    text = json.dumps(snapshot([cluster("a")], date(2026, 10, 19)))
    for forbidden in ("@", "reader", "handle", "email", "acceptedBy"):
        assert forbidden not in text


def archive_entry_of(as_of, rows):
    return {"asOf": as_of, "runId": f"run-{as_of}", "clusters": rows}


def test_weeks_are_backfilled_from_archive_entries():
    entries = [
        archive_entry_of("2026-10-12", [{"uid": "a", "name": "A", "itemCount": 4, "identity": {"status": "new"}},
                                         {"uid": "h", "name": None, "itemCount": 1, "identity": {"status": "new"}}]),
        archive_entry_of("2026-10-19", [{"uid": "a", "name": "A", "itemCount": 6, "identity": {"status": "continued", "predecessor": "a"}}]),
    ]
    weeks = weeks_from_archive(entries, include_unnamed=False)
    assert [week["asOf"] for week in weeks] == ["2026-10-12", "2026-10-19"]
    assert [row["uid"] for row in weeks[0]["clusters"]] == ["a"]
    assert weeks[1]["events"] == [{"event": "continued", "uid": "a", "from": "a"}]
    assert history_file(1, date(2026, 10, 19), weeks, None)["weeks"] == weeks


def context_over(tmp_path):
    return SimpleNamespace(writer=LocalDirectoryWriter(tmp_path), projector=None)


def test_the_command_backfills_from_the_archive_when_no_history_file_is_stored(tmp_path):
    context = context_over(tmp_path)
    options = SnapshotOptions(as_of=date(2026, 10, 19))
    assert previous_cluster_history(context, options) is None
    context.writer.put(entry_file("2026-10-12"), json.dumps(archive_entry_of("2026-10-12", [{"uid": "a", "name": "A", "itemCount": 4, "identity": {"status": "new"}}])).encode())
    context.writer.put(f"{HISTORY_DIRECTORY}/index.json", b"{}")
    backfilled = previous_cluster_history(context, options)
    assert [week["asOf"] for week in backfilled["weeks"]] == ["2026-10-12"]


def test_the_command_prefers_the_stored_file_and_survives_a_corrupt_one(tmp_path):
    context = context_over(tmp_path)
    options = SnapshotOptions(as_of=date(2026, 10, 19))
    stored = snapshot([cluster("a", "new", run_as_of="2026-10-12")], date(2026, 10, 12))
    context.writer.put(CLUSTERS_HISTORY_FILE, json.dumps(stored).encode())
    assert previous_cluster_history(context, options) == stored
    context.writer.put(CLUSTERS_HISTORY_FILE, b"{broken")
    assert previous_cluster_history(context, options) is None


def test_the_source_reads_history_and_a_site_without_it_keeps_its_digest(tmp_path):
    (tmp_path / "index.json").write_text(json.dumps({"schemaVersion": 1}))
    source = KnowledgeSource()
    source.use_directory(tmp_path)
    assert source.history() is None
    before = source.digest()
    (tmp_path / "clusters-history.json").write_text(json.dumps({"schemaVersion": 1, "asOf": "2026-10-19", "weeks": []}))
    source.reset()
    assert source.history() == {"schemaVersion": 1, "asOf": "2026-10-19", "weeks": []}
    assert KnowledgeLookup(source).history() == source.history()
    assert source.digest() != before


def test_reconcile_treats_the_file_as_task_owned():
    from papyrus_content.projection.plugins import is_plugin_runtime_key

    assert is_plugin_runtime_key("_data/knowledge/clusters-history.json")
    assert is_plugin_runtime_key("posts/_data/knowledge/clusters-history.json")
