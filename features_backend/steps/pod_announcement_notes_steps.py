"""Steps for the Announcement and Delivery notes of a pod (features_backend/pod-announcement-delivery-notes.feature).

The pod is the folder pod_steps.py makes. A load goes through ``papyrus.pod.announcement_notes.read`` and ``PodHistory.load`` against the in-memory records backend
and the in-memory store for the words, and the send path is the real ``AccountWorker`` over a channel that records every event handed to it. No network, no AWS, no
real address or account.
"""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, step, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus.pod import announcement_notes, pages  # noqa: E402
from papyrus.pod.notes import walk  # noqa: E402
from papyrus_content.announcements import links, records  # noqa: E402
from papyrus_content.announcements.attempts import AccountWorker, NotReleasable  # noqa: E402
from papyrus_content.announcements.attempts_fakes import FakeChannel  # noqa: E402
from papyrus_content.announcements.deliveries import Deliveries  # noqa: E402
from papyrus_content.announcements.links import StoryRef  # noqa: E402
from papyrus_content.announcements.pod_history import PodHistory  # noqa: E402
from papyrus_content.announcements.records_fakes import MemoryDeliveryFiles, RecordsBackend  # noqa: E402

from pod_steps import _write  # noqa: E402

LOAD_TIME = "2026-11-17T09:00:00Z"
LOADER = "pod-load"


def _newsroom(context) -> None:
    if getattr(context, "newsroom", None) is None:
        context.newsroom = RecordsBackend()
        context.newsroom_files = MemoryDeliveryFiles(context.newsroom)
        context.newsroom_deliveries = Deliveries(context.newsroom, context.newsroom_files)


def _rows(context, model: str) -> list[dict]:
    _newsroom(context)
    return context.newsroom.rows(model)


def _delivery(context, channel: str, account: str, generation: int | None = None) -> dict:
    rows = [row for row in _rows(context, "Delivery") if (row["channel"], row["accountId"]) == (channel, account)]
    assert rows, f"no Delivery for {channel} {account}"
    if generation is not None:
        rows = [row for row in rows if int(row["generation"]) == generation]
        assert rows, f"no generation {generation} of {channel} {account}"
    return dict(max(rows, key=lambda row: int(row["generation"])) if generation is None else rows[0])


def _load(context) -> None:
    _newsroom(context)
    context.error = None
    before = len(context.newsroom.writes)
    try:
        history = PodHistory(context.newsroom, context.newsroom_files)
        context.loaded = [history.load(announcement, by=LOADER, now=LOAD_TIME)
                          for announcement in announcement_notes.read(context.pod, getattr(context, "story_refs", {}))]
    except Exception as error:   # noqa: BLE001 - the specs ask what the load said
        context.error = error
    context.load_writes = len(context.newsroom.writes) - before


# ---- Given ------------------------------------------------------------------------------------------------------------------------

@given('a corrected Delivery note')
def corrected_delivery(context):
    old = context.pod / "deliveries/slow-water-x.md"
    old.write_text(old.read_text(encoding="utf-8").replace("state: sent", "state: superseded"), encoding="utf-8")
    _write(context, "deliveries/slow-water-x-corrected.md", """---
id: https://example.org/id/sample-0105
type: papyrus:Delivery
announcement: "[[slow-water-published]]"
channel: x
account: "@example"
mode: manual
state: sent
supersedes: "[[slow-water-x]]"
resultUrl: https://example.org/status/456
attempts:
  - "1 2026-11-16T18:00Z sent by ryan"
---
Rain kept on the land a little longer. Slow water, corrected. #water
""")


@given('the newsroom has the Story note "{note_id}" as the lineage "{lineage}" at version {version:d}')
def newsroom_has_story(context, note_id, lineage, version):
    if getattr(context, "story_refs", None) is None:
        context.story_refs = {}
    context.story_refs[note_id] = StoryRef(lineage, f"item-{lineage}-v{version}", version)


@step("the pod's Announcement notes are loaded into an empty newsroom")
def load_into_empty(context):
    context.newsroom = None
    _load(context)


@step("the pod's Announcement notes are loaded again")
def load_again(context):
    _load(context)


@given('the newsroom withdraws the loaded Delivery for "{channel}" "{account}"')
def newsroom_withdraws(context, channel, account):
    row = _delivery(context, channel, account)
    context.newsroom_deliveries.finish(row, "withdrawn", by="ryan", note="taken down in the newsroom", now="2026-11-17T10:00:00Z")


# ---- When -------------------------------------------------------------------------------------------------------------------------

@when("the pages of the pod are listed")
def list_pages(context):
    context.pages = [note.path for note in pages.pages(walk(context.pod))]


@when('the worker for "{channel}" "{account}" is asked to send each loaded Delivery')
def worker_sends(context, channel, account):
    _newsroom(context)
    context.channel = FakeChannel(context.newsroom_deliveries)
    worker = AccountWorker(context.newsroom_deliveries, context.channel, channel, account)
    context.refusals, context.sent = [], []
    for row in _rows(context, "Delivery"):
        try:
            worker.send(row["id"], by="ryan", now="2026-11-18T09:00:00Z")
            context.sent.append(row["id"])
        except NotReleasable as refused:
            context.refusals.append(refused.reason)


# ---- Then: pages ------------------------------------------------------------------------------------------------------------------

@then('the pages are "{path}"')
def pages_are(context, path):
    assert context.pages == [path], context.pages


# ---- Then: a load -----------------------------------------------------------------------------------------------------------------

@then('the load is refused with "{text}"')
def load_refused(context, text):
    assert context.error is not None and text in str(context.error), (text, context.error)


@then("the newsroom holds no record")
def holds_nothing(context):
    _newsroom(context)
    assert context.newsroom.writes == [] and not any(context.newsroom.records.values()), context.newsroom.writes


@then('the newsroom has {count:d} Announcement that is {state}, decided by the pod load for the key "{key}"')
def has_announcement(context, count, state, key):
    assert context.error is None, context.error
    rows = _rows(context, "AnnouncementDecision")
    assert len(rows) == count, rows
    row = rows[0]
    assert row["state"] == state and row["trigger"] == "pod load" and row["createdBy"] == LOADER, row
    assert row["dedupeKey"] == records.stored_dedupe_key(key) and row["id"] == records.announcement_id(key), row


@then("the newsroom has {count:d} Announcement")
def count_announcements(context, count):
    assert len(_rows(context, "AnnouncementDecision")) == count


@then('the Announcement announces the Story "{lineage}" at version {version:d}')
def announces_story(context, lineage, version):
    row = _rows(context, "AnnouncementDecision")[0]
    found = links.stories_of_announcement(context.newsroom, row["id"])
    assert [(item["objectLineageId"], item["objectVersionNumber"]) for item in found] == [(lineage, version)], found


@then('the newsroom has {count:d} Delivery for "{channel}" "{account}" that is {state}, in manual mode, at generation {generation:d}')
def has_delivery(context, count, channel, account, state, generation):
    assert context.error is None, context.error
    rows = [row for row in _rows(context, "Delivery") if (row["channel"], row["accountId"]) == (channel, account)]
    assert len(rows) == count, rows
    row = _delivery(context, channel, account, generation)
    assert row["state"] == state and row["mode"] == "manual", row


@then('the newsroom has {count:d} Deliveries for "{channel}" "{account}"')
def has_deliveries(context, count, channel, account):
    assert context.error is None, context.error
    rows = [row for row in _rows(context, "Delivery") if (row["channel"], row["accountId"]) == (channel, account)]
    assert len(rows) == count, rows


@then('the Delivery has the words "{text}" exactly')
def delivery_words(context, text):
    row = _rows(context, "Delivery")[0]
    assert context.newsroom_deliveries.text(row) == text, context.newsroom_deliveries.text(row)
    assert not any(row.get(name) for name in records.TEXT_FIELDS), "the catalog row holds text"


@then('the Delivery has the result address "{url}"')
def delivery_result(context, url):
    assert _rows(context, "Delivery")[0]["resultUrl"] == url


@then('the Delivery has {count:d} attempt, number {number:d}, {outcome} at "{at}" by "{by}"')
def delivery_attempt(context, count, number, outcome, at, by):
    log = records.attempt_log(_rows(context, "Delivery")[0])
    assert len(log) == count and (log[0]["number"], log[0]["outcome"], log[0]["at"], log[0]["by"]) == (number, outcome, at, by), log


@then("the Delivery carries no approved version and says its approval was recorded in a pod")
def delivery_claim(context):
    row = _rows(context, "Delivery")[0]
    assert row.get("approvedVersion") is None and row.get("approvedBy") is None, row
    assert "recorded in a pod" in row["approvalPolicy"] and "not a newsroom approval" in row["approvalPolicy"], row["approvalPolicy"]


@then("generation 1 is superseded and points forward to generation 2")
def first_superseded(context):
    first, second = _delivery(context, "x", "@example", 1), _delivery(context, "x", "@example", 2)
    assert first["state"] == "superseded" and first["supersededBy"] == second["id"], first


@then("generation 2 is sent and supersedes generation 1")
def second_supersedes(context):
    first, second = _delivery(context, "x", "@example", 1), _delivery(context, "x", "@example", 2)
    assert second["state"] == "sent" and second["supersedes"] == first["id"], second


@then("the newsroom has a supersedes link from generation 2 to generation 1")
def supersedes_link(context):
    first, second = _delivery(context, "x", "@example", 1), _delivery(context, "x", "@example", 2)
    found = [row for row in _rows(context, "SemanticRelation") if row["predicate"] == "supersedes"]
    assert [(row["subjectId"], row["objectId"]) for row in found] == [(second["id"], first["id"])], found


# ---- Then: nothing is sent ----------------------------------------------------------------------------------------------------------

@then("no Delivery is due")
def none_due(context):
    _newsroom(context)
    assert context.newsroom_deliveries.due("2030-01-01T00:00:00Z") == []


@then("no Delivery is waiting for a time")
def none_waiting(context):
    rows = _rows(context, "Delivery")
    assert rows and all(not records.pending_times(row) and not any(row.get(name) for name in ("dueAt", "dueKey", "nextAttemptAt", "waitingFor")) for row in rows), rows


@then("the worker sends none of them")
def sends_none(context):
    assert context.sent == [] and len(context.refusals) == len(_rows(context, "Delivery")), (context.sent, context.refusals)


@then("the channel received no event")
def channel_silent(context):
    assert context.channel.submissions == [] and context.channel.posts == [], (context.channel.submissions, context.channel.posts)


@then("the second load wrote nothing")
def wrote_nothing(context):
    assert context.error is None, context.error
    assert context.load_writes == 0, context.newsroom.writes[-context.load_writes:]
