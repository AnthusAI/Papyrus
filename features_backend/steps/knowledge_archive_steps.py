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

from papyrus_content.knowledge_snapshot.archive import (  # noqa: E402
    ArchiveError, HISTORY_INDEX_FILE, archive_entry, build_entry, entry_file,
)
from papyrus_content.knowledge_snapshot.builder import build_files  # noqa: E402
from papyrus_content.knowledge_snapshot.commands import KNOWLEDGE_COMMANDS  # noqa: E402
from papyrus_content.knowledge_snapshot.model import Cluster, KnowledgeData, SnapshotOptions  # noqa: E402
from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402

ARCHIVED_AT = "2026-10-22T09:00:00Z"


def _cluster(uid, event, run_id, run_as_of, predecessors=()):
    return Cluster(uid=uid, accepted=False, name=None, event=event, top_terms=("term",), weekly_series={}, earliest_published_at=None,
                   member_item_keys=(), member_count=3, run_id=run_id, run_as_of=run_as_of, predecessor_uids=tuple(predecessors))


def _state(context):
    if not hasattr(context, "archive"):
        context.archive = {"events": {}, "run": None, "earlier": [], "error": None, "writes": 0}
    return context.archive


def _data(context):
    state = _state(context)
    if state["run"] is None:
        return KnowledgeData()
    run_id, run_as_of = state["run"]
    events = {"tc-1": ("new", ()), "tc-2": ("continued", ()), **state["events"]}
    return KnowledgeData(clusters=tuple(_cluster(uid, event, run_id, run_as_of, preds) for uid, (event, preds) in events.items()))


def _writer(context):
    if not hasattr(context, "archive_writer"):
        context.archive_directory = tempfile.TemporaryDirectory()
        context.archive_writer = LocalDirectoryWriter(Path(context.archive_directory.name))
    return context.archive_writer


def _archive(context, as_of, replace=False):
    state = _state(context)
    writer = _writer(context)
    day = date.fromisoformat(as_of)
    data = _data(context)
    before = {item.key: writer.get(item.key) for item in writer.list("")}
    try:
        entry = build_entry(build_files(data, SnapshotOptions(as_of=day)), data, day, ARCHIVED_AT)
        archive_entry(SimpleNamespace(writer=writer, projector=None, invalidate=None), entry, replace=replace)
        state["error"] = None
    except ArchiveError as error:
        state["error"] = str(error)
    after = {item.key: writer.get(item.key) for item in writer.list("")}
    state["writes"] = sum(1 for key, body in after.items() if before.get(key) != body)


def _stored(context, as_of):
    body = _writer(context).get(entry_file(as_of))
    return json.loads(body) if body is not None else None


@given('a publication with a cluster run "{run_id}" dated in the week of "{as_of}"')
def step_run(context, run_id, as_of):
    _state(context)["run"] = (run_id, as_of)


@given("a publication with no cluster run")
def step_no_run(context):
    _state(context)["run"] = None


@given('the run reports "{uid}" as "{event}" from "{sources}"')
def step_event(context, uid, event, sources):
    _state(context)["events"][uid] = (event, tuple(part.strip() for part in sources.split(",")))


@given('a later cluster run "{run_id}" in the same week')
def step_later_run(context, run_id):
    _state(context)["run"] = (run_id, _state(context)["run"][1])


@given('an earlier archived week "{as_of}"')
def step_earlier(context, as_of):
    saved = _state(context)["run"]
    _state(context)["run"] = ("run-earlier", as_of)
    _archive(context, as_of)
    _state(context)["run"] = saved


@given('the week of "{as_of}" is archived')
@when('the week of "{as_of}" is archived')
@when('the week of "{as_of}" is archived again')
def step_archive(context, as_of):
    _archive(context, as_of)


@when('the week of "{as_of}" is archived with replace')
def step_replace(context, as_of):
    _archive(context, as_of, replace=True)


@then('the archive holds an entry for "{as_of}" from run "{run_id}"')
def step_entry(context, as_of, run_id):
    entry = _stored(context, as_of)
    assert entry is not None and entry["runId"] == run_id, entry


@then('the archive still holds an entry for "{as_of}"')
def step_still(context, as_of):
    assert _stored(context, as_of) is not None


@then("the entry counts {count:d} clusters")
def step_count(context, count):
    assert _stored(context, "2026-10-19")["counts"]["clusters"] == count


def _identity(context, uid):
    return next(row["identity"] for row in _stored(context, "2026-10-19")["clusters"] if row["uid"] == uid)


@then('the cluster "{uid}" is "{status}"')
def step_status(context, uid, status):
    assert _identity(context, uid) == {"status": status}


@then('the cluster "{uid}" has identity "{status}" from "{sources}"')
def step_status_from(context, uid, status, sources):
    identity = _identity(context, uid)
    wanted = [part.strip() for part in sources.split(",")]
    found = identity.get("sources") or [identity.get("predecessor") or identity.get("source")]
    assert identity["status"] == status and found == wanted, identity


def _index_days(context):
    return [row["asOf"] for row in json.loads(_writer(context).get(HISTORY_INDEX_FILE))["entries"]]


@then('the history index lists "{as_of}"')
def step_index(context, as_of):
    assert as_of in _index_days(context) and len(_index_days(context)) == len(set(_index_days(context)))


@then('the history index lists the weeks "{first}" then "{second}"')
def step_index_two(context, first, second):
    assert _index_days(context) == [first, second]


@then("the stored archive is unchanged")
def step_nothing_written(context):
    assert _state(context)["writes"] == 0, _state(context)["writes"]


@then("the archive step refuses because the entry is immutable")
def step_immutable(context):
    assert "immutable" in (_state(context)["error"] or ""), _state(context)["error"]


@then("the archive step refuses because the run is outside the week")
def step_outside(context):
    assert "outside the week" in (_state(context)["error"] or ""), _state(context)["error"]


@then("the archive step refuses because there is no cluster run")
def step_no_cluster_run(context):
    assert "No cluster run" in (_state(context)["error"] or ""), _state(context)["error"]


@then("the archive store is empty")
def step_nothing_archived(context):
    assert _writer(context).list("") == []


@when('the operator runs "papyrus knowledge archive {arguments}" on the command line')
def step_cli_archive(context, arguments):
    from unittest import mock

    from papyrus import cli

    received = []
    with mock.patch.dict(KNOWLEDGE_COMMANDS, {"archive": lambda flags: received.append(flags)}), \
            mock.patch.object(cli.content_cli, "load_dotenv", lambda: None):
        code = cli.main(["knowledge", "archive", *arguments.split()])
    _state(context)["cli"] = {"code": code, "received": received}


@then('the knowledge archive command receives "{arguments}"')
def step_cli_received(context, arguments):
    cli_run = _state(context)["cli"]
    assert cli_run["code"] == 0
    assert cli_run["received"] == [arguments.split()]


@then("the knowledge help lists the archive command")
def step_cli_help(context):
    from papyrus.operator import help_text

    assert "archive" in help_text.build_knowledge_parser().format_help()
