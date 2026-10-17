from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

from signup_fixtures import FakeSignupBackend, valid_arguments  # noqa: E402


@given('a site whose signup plugin accepts the form "{form}"')
def site_with_form(context, form: str) -> None:
    context.backend = FakeSignupBackend(forms=(form,))
    context.answers = []


@when('a guest submits "{value}" to "{form}" {count:d} times')
def submit_many(context, value: str, form: str, count: int) -> None:
    for _ in range(count):
        context.answers.append(context.backend.submit(valid_arguments(form=form, value=value))["status"])


@when('a guest submits "{value}" to "{form}"')
def submit_once(context, value: str, form: str) -> None:
    context.answers.append(context.backend.submit(valid_arguments(form=form, value=value))["status"])


@when('a guest submits "{value}" to "{form}" with the hidden field filled')
def submit_with_honeypot(context, value: str, form: str) -> None:
    context.answers.append(context.backend.submit(valid_arguments(form=form, value=value, website="filled"))["status"])


@when('a guest submits "{value}" to "{form}" half a second after the page rendered')
def submit_instantly(context, value: str, form: str) -> None:
    rendered = str(int((context.backend.now - 0.5) * 1000))
    context.answers.append(context.backend.submit(valid_arguments(form=form, value=value, renderedAt=rendered))["status"])


@when('a guest submits a value of {size:d} characters to "{form}"')
def submit_oversized(context, size: int, form: str) -> None:
    value = "a@" + "b" * (size - 7) + ".test"
    context.answers.append(context.backend.submit(valid_arguments(form=form, value=value))["status"])


def submit_distinct_from_one_address(context, count: int) -> None:
    for number in range(count):
        arguments = valid_arguments(value=f"person{number}@example.test")
        context.answers.append(context.backend.submit(arguments, identity_id=f"identity-{number}")["status"])


@when("one address makes {count:d} submissions of different addresses in one minute")
def one_address_many(context, count: int) -> None:
    submit_distinct_from_one_address(context, count)


@given("one address has made {count:d} submissions in one minute")
def one_address_already_many(context, count: int) -> None:
    submit_distinct_from_one_address(context, count)
    context.answers = []


@when('the next minute begins and the same address submits "{value}" to "{form}"')
def next_minute(context, value: str, form: str) -> None:
    context.backend.now += 61
    rendered = str(int((context.backend.now - 60) * 1000))
    context.answers.append(context.backend.submit(valid_arguments(form=form, value=value, renderedAt=rendered), identity_id="identity-new")["status"])


@then('every answer says "{status}"')
def every_answer(context, status: str) -> None:
    assert context.answers and all(answer == status for answer in context.answers), context.answers


@then('the first {count:d} answers say "{status}"')
def first_answers(context, count: int, status: str) -> None:
    assert context.answers[:count] == [status] * count, context.answers


@then('the last {count:d} answers say "{status}"')
def last_answers(context, count: int, status: str) -> None:
    assert context.answers[-count:] == [status] * count, context.answers


@then("{count:d} signup entr{suffix} stored")
def entries_stored(context, count: int, suffix: str) -> None:
    assert len(context.backend.entries) == count, context.backend.entries
