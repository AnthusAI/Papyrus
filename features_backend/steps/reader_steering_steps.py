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

from reader_fixtures import ReaderBackend, run_snapshot, subject_for  # noqa: E402
from reader_privacy import scan_files  # noqa: E402
from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402


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


def ensure_started(context) -> ReaderBackend:
    if context.reader_backend is None:
        backend = ReaderBackend(dimensions=context.reader_dimensions, actions_per_hour=context.reader_allowance)
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


@when("a minute passes")
def a_minute_passes(context) -> None:
    ensure_started(context).now += 61


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


@then("{count:d} snapshot run{suffix} requested")
def snapshot_runs(context, count: int, suffix: str) -> None:
    invocations = ensure_started(context).lambda_client.invocations
    assert len(invocations) == count, invocations
    assert all(json.loads(invocation["Payload"]) == {"projectionTask": {"task": "reader-snapshot"}} for invocation in invocations)


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


def run_the_snapshot(context, base_path: str = "") -> None:
    backend = ensure_started(context)
    if getattr(context, "reader_site_directory", None) is None:
        directory = tempfile.TemporaryDirectory()
        context.add_cleanup(directory.cleanup)
        context.reader_site_directory = directory
    context.reader_purged = []
    context.reader_site = LocalDirectoryWriter(Path(context.reader_site_directory.name))
    context.reader_report = run_snapshot(
        backend,
        context.reader_site,
        base_path=base_path,
        invalidate=lambda keys: context.reader_purged.append(list(keys)) or keys,
        dimensions=context.reader_dimensions,
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


@then('the public file "{key}" shows a hype gap of {gap:f} on "{subject}"')
def hype_gap_of(context, key: str, gap: float, subject: str) -> None:
    assert public_file(context, key)["items"][subject]["hypeGap"] == gap


@then("nobody is on the karma list")
def nobody_has_karma(context) -> None:
    assert public_file(context, "_data/reader/readers.json")["readers"] == []


@then('the site store holds "{first}", "{second}" and "{third}"')
def store_holds(context, first: str, second: str, third: str) -> None:
    keys = sorted(entry.key for entry in context.reader_site.list())
    assert keys == sorted([first, second, third]), keys


@then("the edge was asked to purge those three files and nothing else")
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
