"""Public handle (features_backend/public-handle.feature): the Python twin of the rules, and the console's resolver tests."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.home_page.handles import check_public_handle, public_author  # noqa: E402
from reader_privacy import identity_leaks  # noqa: E402

VECTORS = json.loads((REPO_ROOT / "scripts" / "fixtures" / "public-handle-vectors.json").read_text(encoding="utf-8"))


@given('a person who set the public handle "{handle}"')
def step_person_with_handle(context, handle):
    context.public_handle = handle


@given("a person who has no public handle")
def step_person_without_handle(context):
    context.public_handle = None


@given("a person whose profile has an email, a sub and a UUID")
def step_person_with_identity(context):
    context.profile = {
        "email": "someone@example.test",
        "sub": "ss1_abcdefghijklmnop",
        "id": str(uuid.uuid4()),
        "publicHandle": "ryan-p",
    }


@when("their message is prepared for the public threads file")
def step_prepare(context):
    context.author = public_author(context.public_handle, "human")


@when("they clear the handle")
def step_clear(context):
    context.public_handle = None
    context.author = public_author(context.public_handle, "human")


@when('a person tries the handle "{value}"')
def step_try(context, value):
    context.check = check_public_handle(value)


@when("their message is prepared once with a handle and once without")
def step_prepare_both(context):
    context.authors = [public_author(context.profile["publicHandle"], "human"), public_author(None, "human")]
    context.looks_like_email = public_author("you@example.test", "human")


@when("every shared handle vector is checked")
def step_vectors(context):
    context.vector_results = [(vector, check_public_handle(vector["input"])) for vector in VECTORS["vectors"]]


@when('the console\'s resolver tests run for "{pattern}"')
def step_run_resolver_tests(context, pattern):
    context.resolver_run = run_resolver_tests(pattern)


@then('the author is shown as the handle "{handle}"')
def step_shown_handle(context, handle):
    assert context.author == {"handle": handle}, context.author


@then('the author is shown as the label "{label}"')
def step_shown_label(context, label):
    assert context.author == {"label": label}, context.author


@then('their message is shown as the label "{label}"')
def step_message_label(context, label):
    assert context.author == {"label": label}, context.author


@then('a message written by AI is shown as the label "{label}"')
def step_ai_label(context, label):
    assert public_author("ryan-p", "assistant") == {"label": label}


@then('the handle is accepted as "{handle}"')
def step_accepted(context, handle):
    assert context.check.valid and context.check.handle == handle, context.check


@then('the handle is refused as "{reason}"')
def step_refused(context, reason):
    assert not context.check.valid and context.check.reason == reason, context.check


@then("the Python rules give the answer written in the vector")
def step_vectors_agree(context):
    assert context.vector_results
    for vector, result in context.vector_results:
        assert result.valid == vector["valid"], vector
        if vector["valid"]:
            assert result.handle == vector["handle"], vector
        else:
            assert result.reason == vector["reason"], vector


@then("they pass")
def step_they_pass(context):
    assert context.resolver_run.returncode == 0, context.resolver_run.stdout + context.resolver_run.stderr


@then('the console\'s resolver tests for "{pattern}" pass')
def step_named_resolver_tests_pass(context, pattern):
    run = run_resolver_tests(pattern)
    assert run.returncode == 0, run.stdout + run.stderr


@then("neither public author contains an email, a sub or a UUID")
def step_no_identity(context):
    for author in context.authors:
        text = json.dumps(author)
        assert identity_leaks(text) == [], text
        for secret in (context.profile["email"], context.profile["sub"], context.profile["id"]):
            assert secret not in text


@then("a stored handle that looks like an email is shown as Editor")
def step_email_handle(context):
    assert context.looks_like_email == {"label": "Editor"}


def run_resolver_tests(pattern: str) -> subprocess.CompletedProcess:
    run = subprocess.run(
        ["npx", "tsx", "--test", f"--test-name-pattern={pattern}", "scripts/test-public-handle.ts"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if run.returncode == 0 and "ℹ pass 0" in run.stdout:
        run.returncode = 1
        run.stdout += f"\nNo console test matched {pattern!r}."
    return run
