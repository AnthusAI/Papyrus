from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

from reader_fixtures import ReaderBackend, subject_for  # noqa: E402


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
