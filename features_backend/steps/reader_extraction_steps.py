from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

from reader_fixtures import subject_for  # noqa: E402
from test_reader_extraction import NODES, REFERENCES, Setup  # noqa: E402


def ensure_started(context):
    """The backend the reader steps started (behave runs each step file on its own, so the helper is not imported)."""
    return context.reader_backend if context.reader_backend is not None else _start(context)


def _start(context):
    from reader_fixtures import ReaderBackend

    backend = ReaderBackend(dimensions=context.reader_dimensions, actions_per_hour=context.reader_allowance, **context.reader_options)
    backend.__enter__()
    context.reader_backend = backend
    context.add_cleanup(lambda: backend.__exit__(None, None, None))
    for subject in context.reader_published:
        backend.publish(subject)
    return backend


def call(context, name: str, action: str, payload: dict) -> dict:
    answer = ensure_started(context).call(subject_for(name), action, payload, staff=name in context.reader_staff)
    context.reader_answers.setdefault(name, []).append(answer)
    return answer


def last_answer(context, name: str) -> dict:
    return context.reader_answers[name][-1]


def first_submission_subject(context) -> str:
    answers = context.reader_answers[context.reader_first_submitter]
    return next(answer["body"]["subject"] for answer in answers if answer["statusCode"] == 201)


def setup_of(context) -> Setup:
    return context.reader_extraction_setup


@given("extraction is on for the publication")
def extraction_on(context) -> None:
    context.reader_extraction_setup = Setup(nodes=[], references=REFERENCES)
    context.reader_extraction = context.reader_extraction_setup.setup


@given("extraction is off for the publication")
def extraction_off(context) -> None:
    context.reader_extraction = None


@given('the knowledge base has the accepted model "{model}" and the accepted maker "{maker}"')
def knowledge_base(context, model: str, maker: str) -> None:
    keep = {model: "model", maker: "maker"}
    nodes = [node for node in NODES if node["displayName"] in keep and node["nodeKind"] == keep[node["displayName"]]]
    setup_of(context).setup.knowledge.entities = lambda: nodes


@given('the first link is a page about the model "{model}" by the maker "{maker}" for the task "{task}"')
def page_about(context, model: str, maker: str, task: str) -> None:
    setup_of(context).answer = {"model": model, "maker": maker, "task": task}


@given("the first link is a dead page")
def dead_page(context) -> None:
    setup_of(context).page = "!http_4xx"


@when('"{name}" reads the extraction of the first submission')
def reads(context, name: str) -> None:
    call(context, name, "extraction", {"subject": first_submission_subject(context)})


@when('"{name}" confirms what was pulled out of the first submission')
def confirms(context, name: str) -> None:
    call(context, name, "extraction-confirm", {"subject": first_submission_subject(context), "decision": "confirm"})


@when('"{name}" corrects the {field} of the first submission to "{value}"')
def corrects(context, name: str, field: str, value: str) -> None:
    call(context, name, "extraction-confirm", {"subject": first_submission_subject(context), "decision": "correct", field: value})


def body_of(context, name: str) -> dict:
    return last_answer(context, name)["body"]


@then('"{name}" sees the extraction state "{state}"')
def sees_state(context, name: str, state: str) -> None:
    assert body_of(context, name)["extraction"]["state"] == state, body_of(context, name)


@then('"{name}" sees that the link could not be read: "{reason}"')
def sees_state_reason(context, name: str, reason: str) -> None:
    extraction = body_of(context, name)["extraction"]
    assert (extraction["state"], extraction["reason"]) == ("failed", reason), extraction


@then('"{name}" sees the {field} "{value}" matched to "{entity}"')
def sees_match(context, name: str, field: str, value: str, entity: str) -> None:
    found = body_of(context, name)["extraction"][field]
    assert found["name"] == value and found["match"]["name"] == entity, found


@then('"{name}" sees the {field} "{value}" with no match')
def sees_no_match(context, name: str, field: str, value: str) -> None:
    found = body_of(context, name)["extraction"][field]
    assert found == {"name": value, "match": None}, found


@then('"{name}" has not confirmed anything yet')
def not_confirmed(context, name: str) -> None:
    assert body_of(context, name)["confirmation"] is None


@then('"{name}" sees her confirmation as "{status}"')
def sees_confirmation(context, name: str, status: str) -> None:
    assert body_of(context, name)["confirmation"]["status"] == status, body_of(context, name)


@then('her confirmation names the {field} "{value}" with no match')
def confirmation_names_unmatched(context, field: str, value: str) -> None:
    name = next(iter(context.reader_answers))
    assert body_of(context, name)["confirmation"][field] == {"name": value, "match": None}, body_of(context, name)


@then('her confirmation still names the {field} "{value}"')
def confirmation_still_names(context, field: str, value: str) -> None:
    name = next(iter(context.reader_answers))
    assert body_of(context, name)["confirmation"][field]["name"] == value, body_of(context, name)


@then("nobody has confirmed the first submission")
def nobody_confirmed(context) -> None:
    (row,) = ensure_started(context).submissions()
    assert row.get("extractionConfirmation") is None, row


@then("the public files say nothing of what was pulled out")
def public_files_clean(context) -> None:
    text = "".join(context.reader_site.get(entry.key).decode() for entry in context.reader_site.list())
    for private in ("whisper", "Whisper", "Some Lab", "extraction", "knownReference"):
        assert private not in text, private


@then("the link was not fetched")
def not_fetched(context) -> None:
    assert setup_of(context).explored == [], setup_of(context).explored


@then("the snapshot run reports {count:d} failed extraction")
def run_reports_failed(context, count: int) -> None:
    assert context.reader_report.extraction.failed == count, context.reader_report.extraction.to_dict()
