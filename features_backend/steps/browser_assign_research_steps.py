"""features_backend/browser-assign-research.feature: the proofs are the functions of procedures/newsroom/tests/test_browser_assign_research.py."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

for entry in (Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests",):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import test_browser_assign_research as proof  # noqa: E402


@given("the research assignment as the browser stored it")
def step_stored(context):
    context.written = proof.written_by_the_browser()
    context.store = proof.store_of(context.written)


@given("the research assignment as the browser stored it, but without its metadata attachment")
def step_without(context):
    context.written = proof.written_by_the_browser()
    context.store = proof.store_of(context.written, attachments=False)


@when("the reporter context pack is built for the Story and that assignment")
def step_pack(context):
    context.pack = proof.pack_of(context.store)


@then("the pack's user text holds the editor's direction under \"Editor's direction (it outranks the Story)\"")
def step_holds(context):
    assert context.written["metadata"]["direction"] in context.pack["user"]
    assert "Editor's direction (it outranks the Story)" in context.pack["user"]


@then("the pack's user text does not hold the editor's direction")
def step_not_holds(context):
    assert context.written["metadata"]["direction"] not in context.pack["user"]


@then("stripping the columns the model lacks changes nothing in the row")
def step_columns(context):
    proof.test_the_assignment_row_has_only_columns_the_model_has()


@when("the research run is made on it with fake providers and a fake model")
def step_run(context):
    proof.test_the_research_run_accepts_the_browser_assignment_and_records_a_packet_built_from_the_direction()
    context.ran = True


@then("the run completed and the model that planned the searches was given the editor's direction")
def step_ran(context):
    assert context.ran


@when("the command makes the same research assignment")
def step_command(context):
    context.compared = False


@then("both have the same Assignment columns, event fields and metadata keys, with the same values")
def step_same(context):
    proof.test_the_browser_stores_what_the_command_stores()
