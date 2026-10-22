from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

from reader_fixtures import START_SECONDS, ReaderBackend, reader_handler, ScriptedRetirementPoll, run_snapshot, subject_for  # noqa: E402
from reader_privacy import scan_files  # noqa: E402
from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402
from papyrus_content.reader_steering.retirement import RetiredPage, RetiredSubject  # noqa: E402


def backend_of(context) -> ReaderBackend:
    return context.reader_backend


def close_backend(context) -> None:
    backend = getattr(context, "reader_backend", None)
    if backend is not None:
        backend.__exit__(None, None, None)
        context.reader_backend = None


@given('a publication whose readers rate "{first}" and "{second}"')
def publication(context, first: str, second: str) -> None:
    close_backend(context)
    context.reader_dimensions = (first, second)
    context.reader_allowance = 120
    context.reader_staff = set()
    context.reader_answers = {}
    context.reader_backend = None
    context.reader_published = []
    context.reader_names = []
    context.reader_hype_gap = None
    context.reader_options = {}


def ensure_started(context) -> ReaderBackend:
    if context.reader_backend is None:
        backend = ReaderBackend(dimensions=context.reader_dimensions, actions_per_hour=context.reader_allowance, **context.reader_options)
        backend.__enter__()
        context.reader_backend = backend
        context.add_cleanup(close_backend, context)
        for subject in context.reader_published:
            backend.publish(subject)
    return context.reader_backend


@given('the published items "{first}" and "{second}"')
def published_items(context, first: str, second: str) -> None:
    context.reader_published = [first, second]


@given('the signed-in readers "{first}" and "{second}"')
def signed_in_readers(context, first: str, second: str) -> None:
    context.reader_names = [first, second]


@given('"{name}" is also on the staff')
def staff(context, name: str) -> None:
    context.reader_staff.add(name)


@given("the allowance is {limit:d} actions an hour")
def allowance(context, limit: int) -> None:
    context.reader_allowance = limit


def call(context, name: str, action: str, payload: dict | None = None) -> dict:
    backend = ensure_started(context)
    answer = backend.call(subject_for(name), action, payload, staff=name in context.reader_staff)
    context.reader_answers.setdefault(name, []).append(answer)
    return answer


@when('"{name}" picks the handle "{handle}"')
def pick_handle(context, name: str, handle: str) -> None:
    call(context, name, "handle", {"handle": handle})


@when('"{name}" upvotes "{subject}" {count:d} times')
def upvote_many(context, name: str, subject: str, count: int) -> None:
    for _ in range(count):
        call(context, name, "vote", {"subject": subject, "dimension": "up", "on": True})


@when('"{name}" upvotes "{subject}"')
def upvote(context, name: str, subject: str) -> None:
    call(context, name, "vote", {"subject": subject, "dimension": "up", "on": True})


@when('"{name}" removes the upvote on "{subject}"')
def remove_upvote(context, name: str, subject: str) -> None:
    call(context, name, "vote", {"subject": subject, "dimension": "up", "on": False})


@when('"{name}" rates "{subject}" "{dimension}" {value:d}')
def rate(context, name: str, subject: str, dimension: str, value: int) -> None:
    call(context, name, "rating", {"subject": subject, "dimension": dimension, "value": value})


@when("{seconds:d} seconds pass")
def seconds_pass(context, seconds: int) -> None:
    ensure_started(context).now += seconds


def last_answer(context, name: str) -> dict:
    return context.reader_answers[name][-1]


@then('"{name}" is answered with status {status:d}')
def answered_with_status(context, name: str, status: int) -> None:
    assert last_answer(context, name)["statusCode"] == status, last_answer(context, name)


@then('"{name}" is answered with status {status:d} "{error}"')
def answered_with_error(context, name: str, status: int, error: str) -> None:
    answer = last_answer(context, name)
    assert (answer["statusCode"], answer["body"].get("error")) == (status, error), answer


def reader_state(context, name: str, subjects: list[str]) -> dict:
    backend = ensure_started(context)
    return backend.call(subject_for(name), "me", {"subjects": subjects}, staff=name in context.reader_staff)["body"]


@then('"{name}" sees the handle "{handle}" in the reader state')
def sees_handle(context, name: str, handle: str) -> None:
    assert reader_state(context, name, [])["handle"] == handle


@then('"{name}" sees "{dimension}" on "{subject}" in the reader state')
def sees_toggle(context, name: str, dimension: str, subject: str) -> None:
    assert reader_state(context, name, [subject])["votes"][subject][dimension] == 1


@then('"{name}" sees "{dimension}" at {value:d} on "{subject}" in the reader state')
def sees_rating(context, name: str, dimension: str, value: int, subject: str) -> None:
    assert reader_state(context, name, [subject])["votes"][subject][dimension] == value


@then("there is {count:d} stored vote")
def one_stored_vote(context, count: int) -> None:
    votes = ensure_started(context).votes()
    assert len(votes) == count, votes


@then("there are {count:d} stored votes")
def stored_votes(context, count: int) -> None:
    votes = ensure_started(context).votes()
    assert len(votes) == count, votes


@then('the stored voter roles are "{first}" and "{second}"')
def voter_roles(context, first: str, second: str) -> None:
    roles = sorted(vote["voterRole"] for vote in ensure_started(context).votes())
    assert roles == sorted([first, second]), roles


@then('"{name}" was refused {count:d} times with status {status:d}')
def refused_times(context, name: str, count: int, status: int) -> None:
    refused = [answer for answer in context.reader_answers[name] if answer["statusCode"] == status]
    assert len(refused) == count, context.reader_answers[name]
    context.reader_refusal = refused[-1]


@then("the refusal says when to retry")
def says_when_to_retry(context) -> None:
    assert 0 < context.reader_refusal["body"]["retryAfter"] <= 3600, context.reader_refusal


@then("{count:d} snapshot run{suffix} scheduled")
def snapshot_runs(context, count: int, suffix: str) -> None:
    schedules = ensure_started(context).schedules()
    assert len(schedules) == count, schedules
    assert all(json.loads(schedule["Target"]["Input"]) == {"projectionTask": {"task": "reader-snapshot"}} for schedule in schedules)


@then("{count:d} snapshot run is scheduled for {seconds:d} seconds after the first vote")
def snapshot_run_at_window_end(context, count: int, seconds: int) -> None:
    schedules = ensure_started(context).schedules()
    assert len(schedules) == count, schedules
    assert schedules[0]["Name"] == f"papyrus-reader-snapshot-{int(START_SECONDS) + seconds}", schedules[0]["Name"]


@then("the reader state of \"{name}\" contains neither her site subject nor her person id")
def no_identity(context, name: str) -> None:
    text = json.dumps(reader_state(context, name, ["item-one"]))
    assert subject_for(name) not in text and subject_for(name)[4:] not in text
    assert "person" not in text.lower()


@when("{count:d} more readers rate \"{subject}\" \"{dimension}\" {value:d}")
def more_readers_rate(context, count: int, subject: str, dimension: str, value: int) -> None:
    backend = ensure_started(context)
    start = getattr(context, "reader_extra_readers", 0)
    for number in range(start, start + count):
        backend.call(subject_for(f"extra-{number}"), "rating", {"subject": subject, "dimension": dimension, "value": value})
    context.reader_extra_readers = start + count


def prospectus_reports(context, record: RetiredSubject) -> None:
    context.reader_retired = [*getattr(context, "reader_retired", []), record]


@when('Prospectus reports "{name}" deleted')
def reports_deleted(context, name: str) -> None:
    prospectus_reports(context, RetiredSubject(subject_for(name), "deleted"))


@when('Prospectus reports "{name}" merged into "{survivor}"')
def reports_merged(context, name: str, survivor: str) -> None:
    prospectus_reports(context, RetiredSubject(subject_for(name), "merged", subject_for(survivor)))


@when("the scheduled snapshot runs")
def scheduled_snapshot_runs(context) -> None:
    run_the_snapshot(context, scheduled=True)


@then("Prospectus was not asked")
def prospectus_not_asked(context) -> None:
    assert context.reader_poll.asked == [], context.reader_poll.asked


@then('the handle "{handle}" is free')
def handle_is_free(context, handle: str) -> None:
    assert ensure_started(context).table("handle").get_item(Key={"id": handle}).get("Item") is None


@then('"{name}" has no profile')
def has_no_profile(context, name: str) -> None:
    assert ensure_started(context).table("profile").get_item(Key={"id": subject_for(name)}).get("Item") is None


@when('{count:d} extra readers rate "{subject}" "{dimension}" {value:d}')
def extra_readers_rate(context, count: int, subject: str, dimension: str, value: int) -> None:
    backend = ensure_started(context)
    for number in range(count):
        backend.call(subject_for(f"extra-{number}"), "rating", {"subject": subject, "dimension": dimension, "value": value})


def run_the_snapshot(context, base_path: str = "", scheduled: bool = False) -> None:
    backend = ensure_started(context)
    if getattr(context, "reader_site_directory", None) is None:
        directory = tempfile.TemporaryDirectory()
        context.add_cleanup(directory.cleanup)
        context.reader_site_directory = directory
    context.reader_purged = []
    retired = getattr(context, "reader_retired", None)
    context.reader_poll = ScriptedRetirementPoll(RetiredPage(tuple(retired or ()), "cursor-1", False), RetiredPage((), "cursor-1", False))
    context.reader_site = LocalDirectoryWriter(Path(context.reader_site_directory.name))
    context.reader_report = run_snapshot(
        backend,
        context.reader_site,
        base_path=base_path,
        invalidate=lambda keys: context.reader_purged.append(list(keys)) or keys,
        dimensions=context.reader_dimensions,
        retirement_poll=context.reader_poll if getattr(context, "reader_retired", None) is not None else None,
        poll_retirements=scheduled,
        hype_gap=getattr(context, "reader_hype_gap", None),
    )


@when("the snapshot runs")
def snapshot_runs_step(context) -> None:
    run_the_snapshot(context)


@when('the snapshot runs under the base path "{base_path}"')
def snapshot_runs_under_base_path(context, base_path: str) -> None:
    run_the_snapshot(context, base_path)


def public_file(context, key: str) -> dict:
    body = context.reader_site.get(key)
    assert body is not None, f"{key} was not written; the store holds {sorted(entry.key for entry in context.reader_site.list())}"
    return json.loads(body)


@then('the public file "{key}" shows {count:d} upvote on "{subject}"')
def public_upvotes(context, key: str, count: int, subject: str) -> None:
    assert public_file(context, key)["items"][subject]["up"] == count


@then('it shows readers rating "{subject}" "{dimension}" at {mean:f} from {n:d} rating and editors at {editor:f}')
def public_ratings(context, subject: str, dimension: str, mean: float, n: int, editor: float) -> None:
    ratings = public_file(context, "_data/reader/items.json")["items"][subject]["ratings"][dimension]
    assert (ratings["reader"]["mean"], ratings["reader"]["n"], ratings["editor"]["mean"]) == (mean, n, editor), ratings


@then('the public file "{key}" ranks "{subject}" first on the front')
def front_first(context, key: str, subject: str) -> None:
    assert public_file(context, key)["front"][0]["subject"] == subject


@then('the public file "{key}" lists "{subject}" as rising with {count:d} upvote')
def rising_with(context, key: str, subject: str, count: int) -> None:
    assert {"subject": subject, "upvotes": count} in public_file(context, key)["rising"]


@then('the public file "{key}" shows no hype gap on "{subject}"')
def no_hype_gap(context, key: str, subject: str) -> None:
    assert public_file(context, key)["items"][subject]["hypeGap"] is None


@then('the public file "{key}" shows no {who} hype gap on "{subject}"')
def no_hype_gap_for(context, key: str, who: str, subject: str) -> None:
    assert public_file(context, key)["items"][subject]["hypeGap"][who] is None


@then('the public file "{key}" shows the {who} hype gap at {gap:f} on "{subject}"')
def hype_gap_of(context, key: str, who: str, gap: float, subject: str) -> None:
    assert public_file(context, key)["items"][subject]["hypeGap"][who] == gap


@given('the publication also rates "{first}" and "{second}"')
def also_rates(context, first: str, second: str) -> None:
    context.reader_dimensions = (*context.reader_dimensions, first, second)


@given('the hype gap adds "{plus_first}" and "{plus_second}" and subtracts "{minus_first}" and "{minus_second}"')
def hype_gap_groups(context, plus_first: str, plus_second: str, minus_first: str, minus_second: str) -> None:
    context.reader_hype_gap = {"plus": [plus_first, plus_second], "minus": [minus_first, minus_second]}


@then("nobody is on the karma list")
def nobody_has_karma(context) -> None:
    assert public_file(context, "_data/reader/readers.json")["readers"] == []


@then('the site store holds the four reader files under "{base}"')
def store_holds(context, base: str) -> None:
    keys = sorted(entry.key for entry in context.reader_site.list())
    expected = sorted(f"{base}/_data/reader/{name}.json" for name in ("items", "board", "readers", "submissions"))
    assert keys == expected, keys


@then("the edge was asked to purge those four files and nothing else")
def edge_purged(context) -> None:
    written = context.reader_report.written
    assert context.reader_purged == [written], (context.reader_purged, written)
    assert not any("*" in key for call in context.reader_purged for key in call)


@then("the public files hold no site subject, person id or email address")
def public_files_clean(context) -> None:
    backend = ensure_started(context)
    reader_ids = [item["readerId"] for item in backend.table("profile").scan()["Items"]]
    files = {entry.key: context.reader_site.get(entry.key) for entry in context.reader_site.list()}
    assert files and scan_files(files, reader_ids) == {}, scan_files(files, reader_ids)


SUBMISSION_URLS = {"first": "https://Example.com/post/1#intro", "second": "https://example.com/post/2", "third": "https://other.example/x"}


def link(context, which: str) -> str:
    return SUBMISSION_URLS.get(which, which)


@when('"{name}" submits the {which} link titled "{title}"')
def submits_link(context, name: str, which: str, title: str) -> None:
    call(context, name, "submit", {"url": link(context, which), "title": title})


@when('"{name}" submits the {which} link with the note "{note}" titled "{title}"')
def submits_link_with_note(context, name: str, which: str, note: str, title: str) -> None:
    call(context, name, "submit", {"url": link(context, which), "title": title, "note": note})


@when('"{name}" submits {count:d} different links')
def submits_many(context, name: str, count: int) -> None:
    for number in range(count):
        call(context, name, "submit", {"url": f"https://site{number}.example/post", "title": f"Post {number}"})


def first_submission_subject(context) -> str:
    answers = context.reader_answers[context.reader_first_submitter]
    return next(answer["body"]["subject"] for answer in answers if answer["statusCode"] == 201)


@when('"{name}" upvotes the first submission')
def upvotes_first_submission(context, name: str) -> None:
    subject = first_submission_subject(context)
    call(context, name, "vote", {"subject": subject, "dimension": "up", "on": True})


@given('"{name}" is the submitter of the first link')
def first_submitter(context, name: str) -> None:
    context.reader_first_submitter = name


@then("there is {count:d} stored submission")
def stored_submissions_one(context, count: int) -> None:
    assert len(ensure_started(context).submissions()) == count


@then("there are {count:d} stored submissions")
def stored_submissions(context, count: int) -> None:
    assert len(ensure_started(context).submissions()) == count


@then('the answer to "{name}" says the submission is pending with extraction pending')
def pending_answer(context, name: str) -> None:
    body = last_answer(context, name)["body"]
    assert (body["state"], body["extraction"]) == ("pending", "pending"), body


@then('the refusal to "{name}" names the existing submission')
def refusal_names_existing(context, name: str) -> None:
    body = last_answer(context, name)["body"]
    assert body["existing"]["subject"] == first_submission_subject(context), body


@then('the answer to "{name}" warns about {count:d} similar link')
def similar_warning(context, name: str, count: int) -> None:
    assert len(last_answer(context, name)["body"]["similar"]) == count, last_answer(context, name)


@then('the public file "{key}" lists {count:d} submission by "{handle}" as pending')
def public_submissions(context, key: str, count: int, handle: str) -> None:
    rows = public_file(context, key)["submissions"]
    assert len(rows) == count and rows[0]["handle"] == handle and rows[0]["state"] == "pending", rows


@then('"{handle}" is on the karma list with {karma:d}')
def on_karma_list(context, handle: str, karma: int) -> None:
    rows = public_file(context, "_data/reader/readers.json")["readers"]
    assert [(row["handle"], row["karma"]) for row in rows] == [(handle, karma)], rows


@then("the stored submission has humanus signals")
def stored_signals(context) -> None:
    (stored,) = ensure_started(context).submissions()
    detectors = {signal["detector"] for signal in json.loads(stored["signals"])}
    assert {"buy-now", "url-shortener"} <= detectors, detectors


@when('"{name}" submits the link "{url}" titled "{title}"')
def submits_given_link(context, name: str, url: str, title: str) -> None:
    call(context, name, "submit", {"url": url, "title": title})


@then('the public file "{key}" shows {count:d} upvote on the first submission')
def public_upvotes_on_submission(context, key: str, count: int) -> None:
    assert public_file(context, key)["items"][first_submission_subject(context)]["up"] == count


def last_comment_id(context, name: str) -> str:
    answers = context.reader_answers[name]
    return next(answer["body"]["id"] for answer in reversed(answers) if answer["statusCode"] == 201 and str(answer["body"].get("id", "")).startswith("cmt-"))


@when('"{name}" comments "{body}" on "{subject}"')
def comments_on(context, name: str, body: str, subject: str) -> None:
    call(context, name, "comment", {"subject": subject, "body": body})


@when('"{name}" comments "{body}" on "{subject}" explaining "{dimension}" {value:d}')
def comments_explaining(context, name: str, body: str, subject: str, dimension: str, value: int) -> None:
    call(context, name, "comment", {"subject": subject, "body": body, "ratingContext": {"dimension": dimension, "value": value}})


@when('"{name}" replies "{body}" to the last comment of "{author}"')
def replies_to(context, name: str, body: str, author: str) -> None:
    call(context, name, "comment", {"subject": "item-one", "body": body, "parent": last_comment_id(context, author)})


@when('"{name}" edits the last comment to "{body}"')
def edits_last_comment(context, name: str, body: str) -> None:
    call(context, name, "comment-edit", {"id": last_comment_id(context, name), "body": body})


@when("{minutes:d} minutes pass")
def minutes_pass(context, minutes: int) -> None:
    ensure_started(context).now += minutes * 60


@when('"{name}" deletes her last comment')
def deletes_last_comment(context, name: str) -> None:
    call(context, name, "comment-delete", {"id": last_comment_id(context, name)})


@when('"{name}" posts {count:d} comments on "{subject}"')
def posts_many_comments(context, name: str, count: int, subject: str) -> None:
    for number in range(count):
        call(context, name, "comment", {"subject": subject, "body": f"Comment {number}"})


def comment_entries(context, subject: str) -> list[dict]:
    return public_file(context, f"_data/reader/comments/{subject}.json")["comments"]


@then('the comment file of "{subject}" lists "{body}" by "{handle}"')
def comment_file_lists(context, subject: str, body: str, handle: str) -> None:
    entries = comment_entries(context, subject)
    assert any(entry.get("body") == body and entry.get("handle") == handle for entry in entries), entries


@then('the comment file of "{subject}" marks "{body}" as edited')
def comment_file_edited(context, subject: str, body: str) -> None:
    assert any(entry.get("body") == body and entry["edited"] for entry in comment_entries(context, subject))


@then('the comment file of "{subject}" nests "{reply}" under "{top}"')
def comment_file_nests(context, subject: str, reply: str, top: str) -> None:
    entries = comment_entries(context, subject)
    parent = next(entry for entry in entries if entry.get("body") == top)
    assert any(entry.get("body") == reply and entry["parent"] == parent["id"] for entry in entries), entries


@then('the comment file of "{subject}" shows a removed comment with the reply "{reply}" under it')
def comment_file_stub(context, subject: str, reply: str) -> None:
    entries = comment_entries(context, subject)
    stub = next(entry for entry in entries if entry.get("stub"))
    assert "body" not in stub and "readerId" not in stub, stub
    assert any(entry.get("body") == reply and entry["parent"] == stub["id"] for entry in entries), entries


@then('the comment file of "{subject}" is empty')
def comment_file_empty(context, subject: str) -> None:
    body = context.reader_site.get(f"_data/reader/comments/{subject}.json")
    assert body is None or json.loads(body)["comments"] == [], body


@then('the public file "{key}" shows {count:d} comment on "{subject}"')
def public_comment_count(context, key: str, count: int, subject: str) -> None:
    assert public_file(context, key)["items"][subject]["comments"] == count


def exported(context) -> list[dict]:
    from papyrus_content.reader_steering.feedback_export import feedback_records

    return list(feedback_records(ensure_started(context).comments()))


@then('the reader feedback export holds a rationale "{text}" for "{dimension}" {value:d} by "{name}"')
def export_holds_rationale(context, text: str, dimension: str, value: int, name: str) -> None:
    reader_id = ensure_started(context).call(subject_for(name), "me")["body"]["readerId"]
    records = [record for record in exported(context) if record.get("rationale") == text]
    assert len(records) == 1, records
    record = records[0]
    assert (record["source"], record["status"], record["readerId"], record["rating"]) == ("reader", "active", reader_id, {"dimension": dimension, "value": value}), record


@then('the reader feedback export retracts the last comment of "{name}"')
def export_retracts(context, name: str) -> None:
    comment_id = last_comment_id(context, name)
    record = next(record for record in exported(context) if record["commentId"] == comment_id)
    assert record["status"] == "retracted" and "rationale" not in record, record


@given("pre-moderation is on")
def pre_moderation_on(context) -> None:
    context.reader_options["pre_moderation"] = True


@given("moderation is off")
def moderation_off(context) -> None:
    context.reader_options["moderation_mode"] = "off"


def staff_call(context, action: str, target_type: str, target: str, **extra) -> dict:
    receipt = ensure_started(context).staff_call(action, target_type, target, **extra)
    context.reader_receipt = receipt
    context.reader_receipts = [*getattr(context, "reader_receipts", []), receipt]
    ensure_started(context).now += 1
    return receipt


@when("a moderator {action} the first submission")
def moderator_acts_on_first_submission(context, action: str) -> None:
    verbs = {"approves": "approve", "hides": "hide", "shows again": "unhide", "promotes": "promote"}
    staff_call(context, verbs[action], "submission", first_submission_subject(context))


@when('a moderator {action} the last comment of "{name}"')
def moderator_acts_on_comment(context, action: str, name: str) -> None:
    verbs = {"approves": "approve", "hides": "hide", "shows again": "unhide"}
    staff_call(context, verbs[action], "comment", last_comment_id(context, name))


@when('a moderator {action} "{name}"')
def moderator_acts_on_reader(context, action: str, name: str) -> None:
    verbs = {"bans": "ban", "limits": "limit", "unbans": "unban"}
    reader_id = ensure_started(context).call(subject_for(name), "me")["body"]["readerId"]
    staff_call(context, verbs[action], "reader", reader_id)


@when("a moderator undoes the last action")
def moderator_undoes(context) -> None:
    last = context.reader_receipts[-1]
    action = ensure_started(context).store.get_action(last["id"])
    staff_call(context, "undo", action["targetType"], action["target"], undo_of=last["id"])


@when("someone who is not an editor tries to hide the first submission")
def non_staff_hides(context) -> None:
    staff_call(context, "hide", "submission", first_submission_subject(context), groups=("reader",))


@when('"{name}" reports the last comment of "{author}" saying "{reason}"')
def reports_comment(context, name: str, author: str, reason: str) -> None:
    call(context, name, "report", {"target": last_comment_id(context, author), "reason": reason})


@then("the moderator is told it is done")
def moderator_told_done(context) -> None:
    assert context.reader_receipt["status"] == "ok", context.reader_receipt


@then('the moderator is refused with "{error}"')
def moderator_refused(context, error: str) -> None:
    assert (context.reader_receipt["status"], context.reader_receipt["error"]) == ("refused", error), context.reader_receipt


@then('the first submission has state "{state}"')
def first_submission_state(context, state: str) -> None:
    stored = ensure_started(context).table("submission").get_item(Key={"id": first_submission_subject(context)})["Item"]
    assert stored["state"] == state, stored


@then("the first submission is in the review queue")
def first_submission_queued(context) -> None:
    stored = ensure_started(context).table("submission").get_item(Key={"id": first_submission_subject(context)})["Item"]
    assert stored["moderation"] == "new", stored


@then("the first submission is not in the review queue")
def first_submission_not_queued(context) -> None:
    stored = ensure_started(context).table("submission").get_item(Key={"id": first_submission_subject(context)})["Item"]
    assert stored["moderation"] == "approved", stored


@then('the last comment of "{name}" is in the review queue with {count:d} report')
def comment_queued_with_reports(context, name: str, count: int) -> None:
    stored = ensure_started(context).table("comment").get_item(Key={"id": last_comment_id(context, name)})["Item"]
    assert (stored["moderation"], int(stored.get("reportCount", 0))) == ("new", count), stored


@then('the public file "{key}" lists no submissions')
def public_no_submissions(context, key: str) -> None:
    assert public_file(context, key)["submissions"] == []


@then("the moderation log holds {count:d} entries, the last marked by a human")
def moderation_log(context, count: int) -> None:
    log = ensure_started(context).actions()
    assert len(log) == count and log[-1]["by"] == "human", log


@then("a draft item was created from the first submission")
def draft_item_created(context) -> None:
    (item,) = ensure_started(context).items()
    stored = ensure_started(context).table("submission").get_item(Key={"id": first_submission_subject(context)})["Item"]
    assert (item["versionState"], item["stage"], stored["itemId"]) == ("draft", "idea", item["lineageId"]), (item, stored)


@then('"{name}" cannot {what}')
def banned_cannot(context, name: str, what: str) -> None:
    backend = ensure_started(context)
    payloads = {
        "vote": ("vote", {"subject": "item-one", "dimension": "up", "on": True}),
        "comment": ("comment", {"subject": "item-one", "body": "Hello"}),
        "submit": ("submit", {"url": "https://example.com/new", "title": "New"}),
        "report": ("report", {"target": first_submission_subject(context), "reason": "x"}),
    }
    action, payload = payloads[what]
    answer = backend.call(subject_for(name), action, payload)
    assert answer["statusCode"] == 403, answer
    context.reader_answers.setdefault(name, []).append(answer)


@given('moderation is by an AI model that hides anything mentioning "{word}"')
def moderation_by_ai(context, word: str) -> None:
    context.reader_options["moderation_mode"] = "ai"
    context.reader_options["ai_key_parameter"] = "/papyrus/test/openai-api-key"
    context.reader_ai_word = word


@when("the AI moderator reviews the new content")
def ai_reviews(context) -> None:
    import sys as _sys

    backend = ensure_started(context)
    ai_module = _sys.modules["ai_moderation"]
    word = context.reader_ai_word
    seen: list[dict] = []

    class ScriptedModel:
        def judge(self, item: dict):
            seen.append(item)
            if word in json.dumps(item):
                return ai_module.Verdict("hide", f"Mentions {word}.")
            return ai_module.Verdict("allow", "Looks fine.")

    context.reader_ai_seen = seen
    context.reader_ai_result = reader_handler.run_ai_worker(
        store=backend.store,
        settings=backend.settings,
        now=lambda: backend.now,
        deadline=backend.now + 1000,
        read_key=lambda: "sk-test-never-used",
        model_factory=lambda key, name: ScriptedModel(),
        invoke_snapshot=lambda: None,
    )
    backend.now += 1


@then("the AI moderator allowed {allowed:d} and hid {hidden:d}")
def ai_counts(context, allowed: int, hidden: int) -> None:
    result = context.reader_ai_result
    assert (result["allowed"], result["hidden"]) == (allowed, hidden), result


@then('the moderation log shows the AI moderator hid the last comment of "{name}" because it mentions "{word}"')
def ai_log(context, name: str, word: str) -> None:
    entry = next(entry for entry in ensure_started(context).actions() if entry["target"] == last_comment_id(context, name))
    assert (entry["by"], entry["action"], entry["reason"]) == ("ai", "hide", f"AI: Mentions {word}."), entry


@then("the model was never shown a reader's identity")
def ai_saw_no_identity(context) -> None:
    backend = ensure_started(context)
    text = json.dumps(context.reader_ai_seen)
    reader_ids = [item["readerId"] for item in backend.table("profile").scan()["Items"]]
    handles = [item.get("handle") for item in backend.table("profile").scan()["Items"] if item.get("handle")]
    assert not any(secret in text for secret in [*reader_ids, *handles, *[subject_for(name) for name in ("alice", "bob")]]), text
