"""The editing window of a Delivery (features_backend/delivery-*.feature, PPY-e8ec54): versions, pinned human edits, candidates, the lock and the unlock, and soft review at the lock time.

The catalog, the Story and the Deliveries are made by announcement_records_steps.py; the attempts and the channel by delivery_attempts_steps.py. A person's and an agent's calls that go
through the operation table are made with ``execute``, the one door, over the real handlers. The follow-up timers run on the fake scheduler and wake queue of
follow_up_timers_steps.py. No network, no AWS.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, step, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, Path(__file__).resolve().parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from announcement_records_steps import attempt, decide, delivery_row, plans_from  # noqa: E402
from papyrus_content import agent_wakes, follow_up_timers  # noqa: E402
from papyrus_content.agent_definitions import schedules  # noqa: E402
from papyrus_content.agent_gate import GateRun  # noqa: E402
from papyrus_content.agent_policy import AgentPolicyStore  # noqa: E402
from papyrus_content.announcements import delivery_lock, delivery_text, edit_handlers, edit_windows, review_policy  # noqa: E402
from papyrus_content.announcements.deliveries import Deliveries  # noqa: E402
from papyrus_content.announcements.delivery_timers import DeliveryTimers  # noqa: E402
from papyrus_content.announcements.delivery_versions import Versions  # noqa: E402
from papyrus_content.announcements.records import attempt_log  # noqa: E402
from papyrus_content.announcements.settings import AnnouncementSettings  # noqa: E402
from papyrus_content.announcements.x_account import AnnouncementError  # noqa: E402
from papyrus_content.images.handlers import Caller, execute  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402
from schedule_fakes import ACCOUNT, ENDPOINT, REGION, TimerScheduler, WakeQueue, utc  # noqa: E402

TENANT = "alpha"
EDITOR = Caller(kind="person", subject="ellie", is_admin=False)
ADMIN = Caller(kind="person", subject="ada", is_admin=True)


def versions_of(context):
    return Versions(context.deliveries)


def row_of(context, channel, account):
    row = delivery_row(context, channel, account)
    context.last_delivery_id = row["id"]   # the Delivery the last step named, for the steps that read it again through the door
    return row


def text_of_version(context, channel, account, number):
    row = row_of(context, channel, account)
    return versions_of(context).text_of_version(row, number)


def entry_of(context, channel, account, number):
    entry = delivery_text.entry_of(row_of(context, channel, account), number)
    assert entry is not None, f"no version {number} in the log of {channel} {account}"
    return entry


def words_of(context):
    """The words a step gives: a doc string when it has one, else the quoted text with ``\\n`` read as a line break."""
    return context.text if context.text is not None else None


# --- the site's edit windows -------------------------------------------------------------------------------------------------------------------------


def _windows(table) -> list[dict]:
    entries = []
    for row in table:
        entry = {"windowMinutes": int(row["window minutes"]), "lockLeadMinutes": int(row["lock lead minutes"] or 0)}
        if row["kind"]:
            entry["kind"] = row["kind"]
        if row["channel"]:
            entry["channel"] = row["channel"]
        entries.append(entry)
    return entries


@given("the site's edit windows are")
def site_windows(context):
    context.settings = {edit_windows.KEY: edit_windows.validate(_windows(context.table))}


@given("the site has no edit windows")
def no_windows(context):
    context.settings = {edit_windows.KEY: []}


@when('the site\'s edit windows are changed to')
def windows_changed(context):
    context.settings = {edit_windows.KEY: edit_windows.validate(_windows(context.table))}


@when("the site's edit windows are saved as")
def windows_saved(context):
    context.error = None
    try:
        context.settings = {edit_windows.KEY: edit_windows.validate(_windows(context.table))}
    except AnnouncementError as error:
        context.error = error


@then('the edit windows are refused saying "{text:Q}"')
def windows_refused(context, text):
    assert isinstance(context.error, AnnouncementError) and text in context.error.message, repr(context.error)


@then('the site\'s announcement settings keep the edit windows as data under "{key:Q}"')
def windows_are_data(context, key):
    store = {}

    class Store:
        def get(self):
            return dict(store) or None

        def put(self, document):
            store.clear()
            store.update(document)

    settings = AnnouncementSettings(Store(), lambda: 0.0)
    saved = settings.save({"mode": "off", "rules": {"minStars": 5, "storyTypes": ["article"], "sections": []}, "budget": None, "billingCycleDay": None, key: context.settings[edit_windows.KEY]}, "connected")
    assert saved[key] == context.settings[edit_windows.KEY] and settings.read()[key] == context.settings[edit_windows.KEY]


@step('the decision "{key:Q}" of kind "{kind:Q}" is made for the Story "{lineage:Q}" under the site\'s edit windows with these Deliveries')
def decision_under_windows(context, key, kind, lineage):
    plans = plans_from(context, context.table)
    release, placed = edit_windows.apply(context.settings, kind, plans, now=context.now)
    decide(context, key, kind, lineage, placed, release)


@step('the decision "{key:Q}" of kind "{kind:Q}" is made for the Story "{lineage:Q}" under the site\'s edit windows with the release time "{release:Q}" and these Deliveries')
def decision_under_windows_at(context, key, kind, lineage, release):
    plans = plans_from(context, context.table)
    release, placed = edit_windows.apply(context.settings, kind, plans, now=context.now, release_at=release)
    decide(context, key, kind, lineage, placed, release)


# --- saving ------------------------------------------------------------------------------------------------------------------------------------------


@step('the person "{who:Q}" saves version {number:d} of the Delivery "{channel:Q}" "{account:Q}" with the words "{words:Q}"')
def person_saves(context, who, number, channel, account, words):
    context.saved = attempt(context, lambda: versions_of(context).save(row_of(context, channel, account)["id"], replaces=number, text=words.replace("\\n", "\n"), by=who, now=context.now))


@step('the person "{who:Q}" saves version {number:d} of the Delivery "{channel:Q}" "{account:Q}" with these words')
def person_saves_block_text(context, who, number, channel, account):
    context.saved = attempt(context, lambda: versions_of(context).save(row_of(context, channel, account)["id"], replaces=number, text=context.text, by=who, now=context.now))


@step('the machine redrafts version {number:d} of the Delivery "{channel:Q}" "{account:Q}" with these words')
def machine_redrafts_block_text(context, number, channel, account):
    context.saved = attempt(context, lambda: versions_of(context).redraft(row_of(context, channel, account)["id"], replaces=number, text=context.text, by="announce", now=context.now))


@step('the decision "{key:Q}" of kind "{kind:Q}" is made for the Story "{lineage:Q}" with an "{channel:Q}" Delivery for "{account:Q}" under "{approval:Q}" review drafted as')
def decision_with_drafted_text(context, key, kind, lineage, channel, account, approval):
    from papyrus_content.announcements.deliveries import Plan

    decide(context, key, kind, lineage, [Plan(channel=channel, account_id=account, approval=approval, approval_policy="publication default", text=context.text)])


@step('the machine redrafts version {number:d} of the Delivery "{channel:Q}" "{account:Q}" with the words "{words:Q}"')
def machine_redrafts(context, number, channel, account, words):
    context.saved = attempt(context, lambda: versions_of(context).redraft(row_of(context, channel, account)["id"], replaces=number, text=words.replace("\\n", "\n"), by="announce", now=context.now))


@step('the person "{who:Q}" saves version {number:d} of the Delivery "{channel:Q}" "{account:Q}" with the words "{words:Q}" after "{other:Q}" saved first')
def two_saves(context, who, number, channel, account, words, other):
    """Two people read the same version; the one named first saves, then the second. Each save is a call of its own against the one version they both read."""
    row_id = row_of(context, channel, account)["id"]
    versions_of(context).save(row_id, replaces=number, text="Words from " + other, by=other, now=context.now)
    context.saved = attempt(context, lambda: versions_of(context).save(row_id, replaces=number, text=words, by=who, now=context.now))


@then("the Delivery save is refused as stale")
def refused_as_stale(context):
    from papyrus_content.announcements.delivery_versions import StaleVersion

    assert isinstance(context.error, StaleVersion), repr(context.error)


@then('the refusal names version {number:d} saved by "{who:Q}" as the one that replaced version {named:d}')
def refusal_names(context, number, who, named):
    error = context.error
    assert error.named == named and error.replaced_by["number"] == number and error.replaced_by["by"] == who, (error.named, error.replaced_by)
    assert f"version {number}, saved by {who}" in str(error), str(error)


@then('the Delivery "{channel:Q}" "{account:Q}" is at version {number:d}')
def is_at_version(context, channel, account, number):
    assert int(row_of(context, channel, account)["version"]) == number


@then('version {number:d} of the Delivery "{channel:Q}" "{account:Q}" has the words "{words:Q}"')
def version_has_words(context, number, channel, account, words):
    assert text_of_version(context, channel, account, number) == words.replace("\\n", "\n")


@then('version {number:d} of the Delivery "{channel:Q}" "{account:Q}" has these words')
def version_has_these_words(context, number, channel, account):
    assert text_of_version(context, channel, account, number) == context.text


@then('version {number:d} of the Delivery "{channel:Q}" "{account:Q}" was saved by "{who:Q}" as {owner:Q} and replaced version {replaced:d}')
def version_saved_by(context, number, channel, account, who, owner, replaced):
    entry = entry_of(context, channel, account, number)
    assert (entry["by"], entry["owner"], entry["replaces"]) == (who, owner, replaced), entry


@then('version {number:d} of the Delivery "{channel:Q}" "{account:Q}" is the first version, drafted by the machine')
def first_version(context, number, channel, account):
    entry = entry_of(context, channel, account, number)
    assert entry["owner"] == "machine" and entry["replaces"] is None, entry


@then('the Delivery "{channel:Q}" "{account:Q}" keeps {count:d} versions, each its own file in S3')
def keeps_versions(context, channel, account, count):
    row = row_of(context, channel, account)
    entries = delivery_text.versions_of(row)
    assert len(entries) == count, [e["number"] for e in entries]
    assert len({e["key"] for e in entries}) == count and len({e["file"] for e in entries}) == count
    for entry in entries:
        assert context.files.get(row["id"], entry["file"]) is not None, entry["file"]


@then('the Delivery row "{channel:Q}" "{account:Q}" holds the key and hash of each version and none of "{words:Q}"')
def row_holds_keys(context, channel, account, words):
    row = row_of(context, channel, account)
    for entry in delivery_text.versions_of(row):
        assert entry["key"].startswith("newsroom/payloads/delivery/") and len(entry["sha256"]) == 64 and len(entry["contentHash"]) == 64, entry
    assert row["textKey"] == delivery_text.head_entry(row)["key"] and row["contentHash"] == delivery_text.head_entry(row)["contentHash"]
    assert words not in json.dumps(row), "the words are in the row"


@then("the save made no new version")
def no_new_version(context):
    assert context.saved.status == "unchanged" and context.saved.entry is None, context.saved


@then('the save was a {status:Q} version')
def save_was(context, status):
    assert context.saved.status == status, context.saved


@then("the redraft was dropped and nothing was written")
def redraft_dropped(context):
    assert context.saved.dropped and context.saved.entry is None, context.saved


@step("the writes so far are remembered")
def remember_writes(context):
    context.writes_before = len(context.backend.writes)


@then("nothing more was written")
def nothing_written(context):
    assert len(context.backend.writes) == context.writes_before, context.backend.writes[context.writes_before:]


@then('the dropped redraft says "{text:Q}"')
def dropped_says(context, text):
    assert text in context.saved.reason, context.saved.reason


# --- blocks and pins ---------------------------------------------------------------------------------------------------------------------------


@then('block {block:d} of version {number:d} of the Delivery "{channel:Q}" "{account:Q}" is owned by "{owner:Q}" and {pin:Q}')
def block_owner(context, block, number, channel, account, owner, pin):
    flags = delivery_text.json_list(entry_of(context, channel, account, number)["blocks"])[block - 1]
    assert flags["owner"] == owner and flags["pinned"] == (pin == "pinned"), flags


@then('version {number:d} of the Delivery "{channel:Q}" "{account:Q}" has {count:d} blocks')
def has_blocks(context, number, channel, account, count):
    assert len(delivery_text.json_list(entry_of(context, channel, account, number)["blocks"])) == count


@step('the person "{who:Q}" changes block {block:d} of the Delivery "{channel:Q}" "{account:Q}" from version {number:d} to "{words:Q}"')
def person_changes_pinned(context, who, block, channel, account, number, words):
    context.saved = attempt(context, lambda: versions_of(context).change_pinned(row_of(context, channel, account)["id"], replaces=number, block=block, text=words, by=who, now=context.now))


@step('the person "{who:Q}" unpins block {block:d} of the Delivery "{channel:Q}" "{account:Q}" from version {number:d}')
def person_unpins(context, who, block, channel, account, number):
    context.saved = attempt(context, lambda: versions_of(context).change_pinned(row_of(context, channel, account)["id"], replaces=number, block=block, unpin=True, by=who, now=context.now))


# --- candidates --------------------------------------------------------------------------------------------------------------------------------


@step('"{who:Q}" keeps the text "{words:Q}" beside the Delivery "{channel:Q}" "{account:Q}" as a candidate')
def keeps_text_candidate(context, who, words, channel, account):
    owner = "machine" if who == "the machine" else "human"
    context.candidate = attempt(context, lambda: versions_of(context).add_candidate(row_of(context, channel, account)["id"], text=words, by=who, owner=owner, now=context.now))


@step('"{who:Q}" keeps the picture "{image:Q}" beside the Delivery "{channel:Q}" "{account:Q}" as a candidate')
def keeps_picture_candidate(context, who, image, channel, account):
    owner = "machine" if who == "the machine" else "human"
    context.candidate = attempt(context, lambda: versions_of(context).add_candidate(row_of(context, channel, account)["id"], image_key=image, by=who, owner=owner, now=context.now))


@step('the person "{who:Q}" chooses candidate "{candidate_id:Q}" of the Delivery "{channel:Q}" "{account:Q}" from version {number:d}')
def person_chooses(context, who, candidate_id, channel, account, number):
    context.saved = attempt(context, lambda: versions_of(context).choose_candidate(row_of(context, channel, account)["id"], candidate_id, replaces=number, by=who, now=context.now))


@step('the machine chooses candidate "{candidate_id:Q}" of the Delivery "{channel:Q}" "{account:Q}" from version {number:d}')
def machine_chooses(context, candidate_id, channel, account, number):
    context.saved = attempt(context, lambda: versions_of(context).choose_candidate(row_of(context, channel, account)["id"], candidate_id, replaces=number, by="announce", owner="machine", now=context.now))


@then('the Delivery "{channel:Q}" "{account:Q}" holds candidate "{candidate_id:Q}" in the state "{state:Q}"')
def candidate_state(context, channel, account, candidate_id, state):
    found = next((c for c in delivery_text.candidates_of(row_of(context, channel, account)) if c["id"] == candidate_id), None)
    assert found is not None and found["state"] == state, found


@then('candidate "{candidate_id:Q}" of the Delivery "{channel:Q}" "{account:Q}" has the words "{words:Q}" in S3')
def candidate_words(context, candidate_id, channel, account, words):
    assert versions_of(context).text_of_candidate(row_of(context, channel, account), candidate_id) == words


@then('candidate "{candidate_id:Q}" of the Delivery "{channel:Q}" "{account:Q}" has the picture "{image:Q}"')
def candidate_picture(context, candidate_id, channel, account, image):
    found = next(c for c in delivery_text.candidates_of(row_of(context, channel, account)) if c["id"] == candidate_id)
    assert found["imageKey"] == image, found


@then('version {number:d} of the Delivery "{channel:Q}" "{account:Q}" was chosen from candidate "{candidate_id:Q}"')
def chosen_from(context, number, channel, account, candidate_id):
    assert entry_of(context, channel, account, number).get("chosenFrom") == candidate_id


@then('the Delivery "{channel:Q}" "{account:Q}" goes out with the picture "{image:Q}"')
def goes_out_with_picture(context, channel, account, image):
    assert delivery_text.sendable_entry(row_of(context, channel, account))["imageKey"] == image


# --- the lock, the unlock and the attempt -------------------------------------------------------------------------------------------------------


@when('the lock time of the Delivery "{channel:Q}" "{account:Q}" is reached at "{when:Q}"')
def lock_time_reached(context, channel, account, when):
    context.now = when
    context.lock = attempt(context, lambda: delivery_lock.lock_at_time(context.deliveries, row_of(context, channel, account)["id"], now=when))


@then('the lock answered "{action:Q}"')
def lock_answered(context, action):
    assert context.error is None, repr(context.error)
    assert context.lock.action == action, (context.lock.action, context.lock.reason)


@then('the lock said "{text:Q}"')
def lock_said(context, text):
    assert text in (context.lock.reason or ""), context.lock.reason


@then("the lock raised one flag")
def lock_flag(context):
    assert context.lock.flag, context.lock
    assert context.backend.get_record("ReviewRequest", context.lock.flag)["mode"] == "flag"


@then('the Delivery "{channel:Q}" "{account:Q}" is locked at "{when:Q}" with version {number:d}')
def is_locked_at(context, channel, account, when, number):
    row = row_of(context, channel, account)
    assert (row.get("lockedAt"), row.get("lockedVersion")) == (when, number), (row.get("lockedAt"), row.get("lockedVersion"))


@then('the Delivery "{channel:Q}" "{account:Q}" is not locked')
def is_not_locked(context, channel, account):
    row = row_of(context, channel, account)
    assert not row.get("lockedAt") and row.get("lockedVersion") is None, row


@then('the Delivery "{channel:Q}" "{account:Q}" was approved by the policy at the lock time "{when:Q}"')
def approved_by_policy(context, channel, account, when):
    row = row_of(context, channel, account)
    assert row["approvedBy"] == "system" and row["approvedAt"] == when and int(row["approvedVersion"]) == int(row["lockedVersion"]), row
    note = next(line["note"] for line in context.deliveries.history(row) if "soft review: nobody acted" in line["note"])
    source = row["approvalPolicy"].rsplit(" (agent policy version", 1)[0]
    assert source in note and "at the lock time (soft review: nobody acted)" in note, note   # the record says which policy approved it, and why


@then('the history of the Delivery "{channel:Q}" "{account:Q}" says "{text:Q}"')
def history_says(context, channel, account, text):
    assert any(text in line["note"] for line in context.deliveries.history(row_of(context, channel, account))), context.deliveries.history(row_of(context, channel, account))


@then('the Delivery "{channel:Q}" "{account:Q}" is due at "{when:Q}" for the lock')
def due_for_lock(context, channel, account, when):
    assert row_of(context, channel, account)["dueAt"] == when


@when('the person "{who:Q}" unlocks the Delivery "{channel:Q}" "{account:Q}" to lock again at "{lock:Q}"')
def person_unlocks(context, who, channel, account, lock):
    context.unlocked = attempt(context, lambda: delivery_lock.unlock(context.deliveries, row_of(context, channel, account)["id"], by=who, now=context.now, lock_at=lock))


@when('the person "{who:Q}" unlocks the Delivery "{channel:Q}" "{account:Q}" to lock again at "{lock:Q}" and release at "{release:Q}"')
def person_unlocks_with_release(context, who, channel, account, lock, release):
    context.unlocked = attempt(context, lambda: delivery_lock.unlock(context.deliveries, row_of(context, channel, account)["id"], by=who, now=context.now, lock_at=lock, release_at=release))


@when('the person "{who:Q}" unlocks the Delivery "{channel:Q}" "{account:Q}"')
def person_unlocks_plain(context, who, channel, account):
    context.unlocked = attempt(context, lambda: delivery_lock.unlock(context.deliveries, row_of(context, channel, account)["id"], by=who, now=context.now))


@step('the Delivery "{channel:Q}" "{account:Q}" is locked by the engine at "{when:Q}"')
def engine_locks(context, channel, account, when):
    context.now = when
    outcome = delivery_lock.lock_at_time(context.deliveries, row_of(context, channel, account)["id"], now=when)
    assert outcome.locked, outcome


@then('the history of the Delivery "{channel:Q}" "{account:Q}" shows who unlocked it')
def history_unlock(context, channel, account):
    line = context.deliveries.history(row_of(context, channel, account))[-1]
    assert line["by"] and "unlocked version" in line["note"], line


@step('the Delivery "{channel:Q}" "{account:Q}" is sent by the worker at "{when:Q}"')
def worker_sends_at(context, channel, account, when):
    context.now = when
    attempt(context, lambda: context.worker.send(row_of(context, channel, account)["id"], by="worker", now=when))
    assert context.error is None, repr(context.error)


@when('the worker tries to send the Delivery "{channel:Q}" "{account:Q}" at "{when:Q}"')
def worker_tries(context, channel, account, when):
    context.now = when
    attempt(context, lambda: context.worker.send(row_of(context, channel, account)["id"], by="worker", now=when))


@then('attempt {number:d} of the Delivery "{channel:Q}" "{account:Q}" records version {version:d}')
def attempt_records_version(context, number, channel, account, version):
    entry = attempt_log(row_of(context, channel, account))[number - 1]
    assert entry["version"] == version, entry


@then('the channel was handed the words "{words:Q}" for attempt {number:d} of the Delivery "{channel:Q}" "{account:Q}"')
def channel_handed(context, words, number, channel, account):
    event = attempt_log(row_of(context, channel, account))[number - 1]["eventId"]
    assert context.fake_channel.texts[event] == words, context.fake_channel.texts.get(event)


@step('an attempt is open on the Delivery "{channel:Q}" "{account:Q}"')
def attempt_open(context, channel, account):
    from papyrus_content.announcements.attempts import Attempts

    attempt(context, lambda: Attempts(context.deliveries).open(row_of(context, channel, account)["id"], by="worker", now=context.now))
    assert context.error is None, repr(context.error)


@then('the Delivery "{channel:Q}" "{account:Q}" has the preferred version {number:d}')
def has_preferred(context, channel, account, number):
    row = row_of(context, channel, account)
    assert row.get("preferredVersion") == number and entry_of(context, channel, account, number).get("preferred") is True, row.get("preferredVersion")


@then('the Delivery "{channel:Q}" "{account:Q}" has no preferred version')
def has_no_preferred(context, channel, account):
    assert row_of(context, channel, account).get("preferredVersion") is None


@then('the Delivery "{channel:Q}" "{account:Q}" is still locked with version {number:d}')
def still_locked(context, channel, account, number):
    assert int(row_of(context, channel, account)["lockedVersion"]) == number


@then('the Delivery "{channel:Q}" "{account:Q}" still sends version {number:d}')
def still_sends(context, channel, account, number):
    assert delivery_text.sendable_number(row_of(context, channel, account)) == number


# --- an edit and a lock at the same moment -----------------------------------------------------------------------------------------------------


@when('the person "{who:Q}" reads version {number:d} of the Delivery "{channel:Q}" "{account:Q}" and the lock time is reached before they save')
def edit_loses_to_lock(context, who, number, channel, account):
    row_id = row_of(context, channel, account)["id"]
    versions = versions_of(context)
    original = context.deliveries._change
    state = {"done": False}

    def racing(row, changes, **kwargs):
        if not state["done"] and "versions" in changes:   # the save is about to write: the engine's lock lands first
            state["done"] = True
            delivery_lock.lock_at_time(context.deliveries, row_id, now=context.now)
        return original(row, changes, **kwargs)

    context.deliveries._change = racing
    try:
        context.saved = attempt(context, lambda: versions.save(row_id, replaces=number, text="A late edit", by=who, now=context.now))
    finally:
        context.deliveries._change = original


@when('the person "{who:Q}" saves version {number:d} of the Delivery "{channel:Q}" "{account:Q}" at the moment the lock time is reached')
def edit_beats_lock(context, who, number, channel, account):
    row_id = row_of(context, channel, account)["id"]
    original = context.deliveries._change
    state = {"done": False}

    def racing(row, changes, **kwargs):
        # the lock reads the row, then the person's save lands, then the lock's write is attempted against the row it read
        if not state["done"] and "lockedAt" in changes:
            state["done"] = True
            versions_of(context).save(row_id, replaces=number, text="Edited at the last moment", by=who, now=context.now)
        return original(row, changes, **kwargs)

    context.deliveries._change = racing
    try:
        context.lock = delivery_lock.lock_at_time(context.deliveries, row_id, now=context.now)
    finally:
        context.deliveries._change = original


@then('exactly one of the edit and the lock won: the Delivery is locked with version {number:d} and the edit was refused as late')
def one_winner_lock(context, number):
    assert isinstance(context.error, Exception) and "locked" in str(context.error), repr(context.error)


# --- the follow-up timer -----------------------------------------------------------------------------------------------------------------------


@given('the site "{site:Q}" holds its Deliveries with follow-up timers')
def deliveries_with_timers(context, site):
    names = schedules.names_for(site)
    context.site_id, context.names = site, names
    context.queue = WakeQueue()
    context.fake_scheduler = TimerScheduler(names.group, context.queue)
    timers = follow_up_timers.FollowUpTimers.for_site(site, account=ACCOUNT, region=REGION, client=context.fake_scheduler)
    base = {"appsyncEndpoint": ENDPOINT, "procedureKey": "newsroom.deliver", "publicationId": site}
    context.deliveries = Deliveries(context.backend, context.files, DeliveryTimers(timers, base))
    context.announcements.deliveries = context.deliveries


@then('the one timer fires at "{when:Q}"')
def timer_fires_at(context, when):
    (entry,) = context.fake_scheduler.entries.values()
    assert entry["ScheduleExpression"] == "at(" + when.rstrip("Z") + ")", entry["ScheduleExpression"]


@step('the time "{moment:Q}" arrives for the site\'s timers')
def timers_time_arrives(context, moment):
    context.fake_scheduler.fire_until(utc(moment))


@then("the wake queue holds {count:d} message")
def wake_count(context, count):
    assert len(context.queue.messages) == count, [m.body for m in context.queue.messages]


@then('the wake says the Delivery "{channel:Q}" "{account:Q}" was waiting for the "{what:Q}"')
def wake_says(context, channel, account, what):
    body = json.loads(context.queue.messages[-1].body)
    assert body["wake"]["why"].endswith(f"({what})"), body["wake"]["why"]
    assert row_of(context, channel, account)["id"] in body["wake"]["why"]


@when("the run for the last wake on the queue reads the Delivery again at \"{when:Q}\"")
def run_for_wake(context, when):
    body = json.loads(context.queue.messages[-1].body)
    request = agent_wakes.request_from_event({"Records": [{"eventSource": "aws:sqs", "body": context.queue.messages[-1].body}]})
    context.now = when
    context.ran = attempt(context, lambda: delivery_lock.on_wake(context.deliveries, request["wakeKey"], now=when))
    assert body


@then('the run locked the Delivery "{channel:Q}" "{account:Q}" and says it may go at "{release:Q}"')
def run_locked(context, channel, account, release):
    assert context.ran["ran"] and context.ran["lock"] in ("locked", "approved_and_locked"), context.ran
    ok, why = context.deliveries.releasable(row_of(context, channel, account), release)
    assert ok, why


@then('the deliver run did nothing and says "{text:Q}"')
def run_does_nothing(context, text):
    assert context.ran["ran"] is False and text in context.ran["reason"], context.ran


# --- the operations through the one door ------------------------------------------------------------------------------------------------------------


def _handlers(context):
    edit_handlers._publication = lambda client: "publication"   # the publication's key is read from the site's own record, which these specs do not build
    return edit_handlers.signed_in_handlers(client_factory=lambda: context.backend, files=context.files, clock=lambda: context.now)


def _policy(context, rung):
    s3, catalogue = FakeS3(), FakeTable()
    clock = iter(f"2026-11-16T00:{minute:02d}:00Z" for minute in range(60))
    store = AgentPolicyStore(SiteStore(s3, "bucket", catalogue, now=lambda: next(clock)))
    store.set_rung(TENANT, ADMIN, review_policy.RESPONSIBILITY, rung, reason="Seed")
    return store


@step('an announce agent working at the rung "{rung:Q}" on the channel "{channel:Q}" for the kind "{kind:Q}"')
def agent_at_rung(context, rung, channel, kind):
    store = _policy(context, rung)
    context.agent_run = GateRun(store.read(TENANT), review_policy.RESPONSIBILITY, "run-1", {"channel": channel, "kind": kind})
    context.agent = Caller(kind="agent", subject="announce", gate_run=context.agent_run)


@when('the announce agent asks the door to unlock the Delivery "{channel:Q}" "{account:Q}"')
def agent_unlocks(context, channel, account):
    context.envelope = execute("announcements_unlock", {"delivery": row_of(context, channel, account)["id"]}, context.agent, _handlers(context))


@when('the announce agent asks the door to save the words "{words:Q}" over version {number:d} of the Delivery "{channel:Q}" "{account:Q}"')
def agent_saves_door(context, words, number, channel, account):
    context.envelope = execute("announcements_draft", {"delivery": row_of(context, channel, account)["id"], "replaces": number, "text": words.replace("\\n", "\n")}, context.agent, _handlers(context))


@when('the announce agent asks the door to change block {block:d} of version {number:d} of the Delivery "{channel:Q}" "{account:Q}" to "{words:Q}"')
def agent_changes_pinned_door(context, block, number, channel, account, words):
    context.envelope = execute("announcements_pinned_change", {"delivery": row_of(context, channel, account)["id"], "replaces": number, "block": block, "text": words}, context.agent, _handlers(context))


@when('the person "{who:Q}" asks the door to save the words "{words:Q}" over version {number:d} of the Delivery "{channel:Q}" "{account:Q}"')
def person_saves_door(context, who, words, number, channel, account):
    context.envelope = execute("announcements_draft", {"delivery": row_of(context, channel, account)["id"], "replaces": number, "text": words.replace("\\n", "\n")},
                               Caller(kind="person", subject=who, is_admin=False), _handlers(context))


@when('the person "{who:Q}" asks the door to unlock the Delivery "{channel:Q}" "{account:Q}" to lock again at "{lock:Q}"')
def person_unlocks_door(context, who, channel, account, lock):
    context.envelope = execute("announcements_unlock", {"delivery": row_of(context, channel, account)["id"], "lockAt": lock}, Caller(kind="person", subject=who, is_admin=False),
                               _handlers(context))


@when('the person "{who:Q}" asks the door for the versions of the Delivery "{channel:Q}" "{account:Q}"')
def person_reads_versions(context, who, channel, account):
    context.envelope = execute("announcements_versions", {"delivery": row_of(context, channel, account)["id"]}, Caller(kind="person", subject=who, is_admin=False), _handlers(context))


@when('the person "{who:Q}" asks the door for version {number:d} of the Delivery "{channel:Q}" "{account:Q}"')
def person_reads_version(context, who, number, channel, account):
    context.envelope = execute("announcements_versions", {"delivery": row_of(context, channel, account)["id"], "version": number}, Caller(kind="person", subject=who, is_admin=False),
                               _handlers(context))


@then('the door answers "{word:Q}"')
def door_answers(context, word):
    envelope = context.envelope
    if word == "allowed":
        assert envelope["ok"], envelope
    else:
        assert envelope["ok"] is False and envelope["error"]["code"] == word, envelope


@then('the door says the Delivery was {status:Q}')
def door_status(context, status):
    assert context.envelope["ok"] and context.envelope["result"]["status"] == status, context.envelope


@then('the door names version {number:d} as the one that replaced the version read')
def door_names_replacing(context, number):
    details = context.envelope["error"]["details"]
    assert details["replacedBy"]["number"] == number, details


@then("the door's listing shows {count:d} versions and {candidates:d} candidates")
def door_listing(context, count, candidates):
    result = context.envelope["result"]
    assert len(result["versions"]) == count and len(result["candidates"]) == candidates, result


@then('the door gives the words "{words:Q}"')
def door_words(context, words):
    assert context.envelope["result"]["text"] == words.replace("\\n", "\n"), context.envelope["result"]


@then("the door's listing carries no words and no S3 keys")
def door_no_words(context):
    text = json.dumps(context.envelope["result"])
    assert "newsroom/payloads" not in text and '"text"' not in text, text


@then("exactly {count:d} review request has been raised for the Deliveries")
def review_requests_raised(context, count):
    assert len(context.backend.rows("ReviewRequest")) == count, context.backend.rows("ReviewRequest")


@then("nothing was posted to the channel")
def nothing_posted(context):
    assert not context.fake_channel.posts and not context.fake_channel.submissions, (context.fake_channel.posts, context.fake_channel.submissions)


@then('the review of the Delivery "{channel:Q}" "{account:Q}" reads "{words:Q}" with the mark "{mark:Q}"')
def review_reads(context, channel, account, words, mark):
    from papyrus_content.announcements.approval_words import approval_label

    label = approval_label(row_of(context, channel, account))
    assert (label["words"], label["mark"]) == (words, mark), label


@then("the channel posted exactly once")
def posted_once(context):
    assert len(context.fake_channel.posts) == 1, context.fake_channel.posts


@when('the person "{who:Q}" asks the door to save the words without naming a version for the Delivery "{channel:Q}" "{account:Q}"')
def person_saves_unnamed(context, who, channel, account):
    context.envelope = execute("announcements_draft", {"delivery": row_of(context, channel, account)["id"], "text": "Words with no version named."},
                               Caller(kind="person", subject=who, is_admin=False), _handlers(context))


@when('the person "{who:Q}" asks the door to keep the text "{words:Q}" for the Delivery "{channel:Q}" "{account:Q}"')
def person_keeps_candidate_door(context, who, words, channel, account):
    context.envelope = execute("announcements_draft", {"delivery": row_of(context, channel, account)["id"], "text": words, "candidate": True},
                               Caller(kind="person", subject=who, is_admin=False), _handlers(context))


@when('the person "{who:Q}" asks the door to choose candidate "{candidate_id:Q}" over version {number:d} of the Delivery "{channel:Q}" "{account:Q}"')
def person_chooses_door(context, who, candidate_id, number, channel, account):
    context.envelope = execute("announcements_candidate_choose", {"delivery": row_of(context, channel, account)["id"], "candidate": candidate_id, "replaces": number},
                               Caller(kind="person", subject=who, is_admin=False), _handlers(context))


@when('the person "{who:Q}" asks the door for the versions of a Delivery that is not there')
def person_reads_missing(context, who):
    context.envelope = execute("announcements_versions", {"delivery": "announcement-none#x#nobody#g1"}, Caller(kind="person", subject=who, is_admin=False), _handlers(context))


@then('the door\'s listing of candidates shows "{candidate_id:Q}" kept open')
def door_candidates_open(context, candidate_id):
    envelope = execute("announcements_versions", {"delivery": context.last_delivery_id}, EDITOR, _handlers(context))
    candidates = envelope["result"]["candidates"]
    assert [(c["id"], c["state"]) for c in candidates] == [(candidate_id, "open")], candidates
