from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_snapshot.archive import archive_entry, build_entry  # noqa: E402
from papyrus_content.knowledge_snapshot.builder import CLUSTERS_HISTORY_FILE, build_files  # noqa: E402
from papyrus_content.knowledge_snapshot.commands import previous_cluster_history, write_files  # noqa: E402
from papyrus_content.knowledge_snapshot.model import Cluster, KnowledgeData, SnapshotOptions  # noqa: E402
from papyrus_content.projection.standard.knowledge import KnowledgeSource  # noqa: E402
from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402

WEEKS = ("2026-10-12", "2026-10-19", "2026-10-26")


def _names(text):
    return [part.strip() for part in text.split(",") if part.strip()]


def _context(context):
    if not hasattr(context, "ch_context"):
        context.ch_directory = tempfile.TemporaryDirectory()
        context.ch_context = SimpleNamespace(writer=LocalDirectoryWriter(Path(context.ch_directory.name)), projector=None, invalidate=None)
    return context.ch_context


def _data(context, week):
    clusters = []
    for row in context.ch_rows:
        if row["week"] == week:
            sources = tuple(_names(row["from"]))
            clusters.append(Cluster(uid=row["cluster"], accepted=True, name=f"Name {row['cluster']}", event=row["event"], top_terms=(), weekly_series={},
                                    earliest_published_at=None, member_item_keys=(), member_count=3, run_id=f"run-{week}", run_as_of=week,
                                    predecessor_uids=sources))
    return KnowledgeData(clusters=tuple(clusters))


def _snapshot(context, week):
    holder = _context(context)
    options = SnapshotOptions(as_of=date.fromisoformat(week))
    data = _data(context, week)
    files = build_files(data, options, previous_cluster_history(holder, options))
    write_files(holder, files)
    return data, options


def _history(context):
    return json.loads(_context(context).writer.get(CLUSTERS_HISTORY_FILE))


def _week(context, day):
    return next(week for week in _history(context)["weeks"] if week["asOf"] == day)


@given("a publication whose weekly cluster runs are")
def step_runs(context):
    context.ch_rows = [dict(zip(context.table.headings, row.cells)) for row in context.table]


@when("the snapshot is taken for each of the three weeks in order")
def step_all(context):
    for week in WEEKS:
        _snapshot(context, week)


@given("the snapshots of the first two weeks were taken")
def step_two(context):
    for week in WEEKS[:2]:
        _snapshot(context, week)
    context.ch_stored = _history(context)


@when('the snapshot is taken for the week of "{week}" from only that week\'s run')
@when('the snapshot is taken for the week of "{week}" again')
def step_one(context, week):
    _snapshot(context, week)


@given("the first two weeks were archived and no clusters-history.json was ever written")
def step_archived(context):
    holder = _context(context)
    for week in WEEKS[:2]:
        data = _data(context, week)
        options = SnapshotOptions(as_of=date.fromisoformat(week))
        archive_entry(holder, build_entry(build_files(data, options), data, options.as_of, f"{week}T09:00:00Z"))
    assert holder.writer.get(CLUSTERS_HISTORY_FILE) is None


@then('clusters-history.json lists the weeks "{weeks}" oldest first')
def step_weeks(context, weeks):
    assert [week["asOf"] for week in _history(context)["weeks"]] == _names(weeks), _history(context)["weeks"]


@then('in the week of "{day}" the event "born" applies to "{uids}"')
def step_born_all(context, day, uids):
    assert sorted(e["uid"] for e in _week(context, day)["events"] if e["event"] == "born") == sorted(_names(uids))


@then('in the week of "{day}" the cluster "{uid}" is "merged_from" "{sources}"')
def step_merged(context, day, uid, sources):
    assert {"event": "merged_from", "uid": uid, "sources": sorted(_names(sources))} in _week(context, day)["events"]


@then('in the week of "{day}" the cluster "{uid}" is born')
def step_born(context, day, uid):
    assert {"event": "born", "uid": uid} in _week(context, day)["events"]


@then('in the week of "{day}" the cluster "{uid}" has "split_into" "{children}"')
def step_split(context, day, uid, children):
    assert {"event": "split_into", "uid": uid, "into": sorted(_names(children))} in _week(context, day)["events"]


@then('in the week of "{day}" the cluster "{uid}" continued from "{source}"')
def step_continued(context, day, uid, source):
    assert {"event": "continued", "uid": uid, "from": source} in _week(context, day)["events"]


@then('in the week of "{day}" the cluster "{uid}" is labelled "{label}" with {count:d} items')
def step_label(context, day, uid, label, count):
    row = next(row for row in _week(context, day)["clusters"] if row["uid"] == uid)
    assert row == {"uid": uid, "label": label, "itemCount": count}, row


@then('the week of "{day}" lists "{uids}"')
def step_lists(context, day, uids):
    assert [row["uid"] for row in _week(context, day)["clusters"]] == sorted(_names(uids))


@then("the first two weeks are exactly as they were stored")
def step_unchanged(context):
    assert _history(context)["weeks"][:2] == context.ch_stored["weeks"]


@then('the knowledge source reads a history with the weeks "{weeks}"')
def step_source(context, weeks):
    source = KnowledgeSource()
    # the writer stores under _data/knowledge; the source reads that directory
    source.use_directory(Path(context.ch_directory.name) / "_data" / "knowledge")
    assert [week["asOf"] for week in source.history()["weeks"]] == _names(weeks)


@then("a knowledge source over an empty snapshot reads no history")
def step_empty(context):
    with tempfile.TemporaryDirectory() as empty:
        source = KnowledgeSource()
        source.use_directory(empty)
        assert source.history() is None


@then("clusters-history.json holds no email, reader or handle")
def step_private(context):
    text = json.dumps(_history(context))
    assert not any(word in text for word in ("@", "reader", "handle", "email")), text


@then("the page reconcile treats clusters-history.json as owned by the snapshot task")
def step_owned(context):
    from papyrus_content.projection.plugins import is_plugin_runtime_key

    assert is_plugin_runtime_key(CLUSTERS_HISTORY_FILE) and is_plugin_runtime_key("posts/" + CLUSTERS_HISTORY_FILE)
