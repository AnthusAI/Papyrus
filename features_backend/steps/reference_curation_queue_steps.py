import contextlib
import io
import json
import shlex
from contextlib import ExitStack
from unittest.mock import Mock, patch

from behave import then, when

from papyrus_content import references_commands
from papyrus_newsroom import cli as newsroom_cli
from reference_curation_preview_steps import name_of_reference, names_listed_in, reference_id_for  # noqa: E402


def run_curate_recent(context, extra_arguments: list[str]):
    context.references_queued_for_curation = []
    context.curate_recent_refusal = None
    context.curate_recent_output = None

    def queue_a_curation_assignment(*, reference_id, actor_label, curation_policy):
        context.references_queued_for_curation.append(name_of_reference(reference_id))
        return {"referenceId": reference_id, "assignmentId": f"assignment-for-{reference_id}", "status": "queued"}

    printed = io.StringIO()
    with ExitStack() as stand_ins:
        stand_ins.enter_context(patch.object(newsroom_cli, "papyrus_reference_curation_start", queue_a_curation_assignment))
        stand_ins.enter_context(contextlib.redirect_stdout(printed))
        try:
            context.curate_recent_exit_status = context.publication.run_with_stand_ins(
                lambda: newsroom_cli._run_with_arguments(["references", "curate-recent", "--corpus-key", "test-corpus", *extra_arguments])
            )
        except ValueError as refusal:
            context.curate_recent_refusal = str(refusal)
            return
    context.curate_recent_output = json.loads(printed.getvalue().strip().splitlines()[-1])


@when("an operator runs curate-recent for real")
def operator_runs_curate_recent_for_real(context):
    run_curate_recent(context, [])


@when('an operator runs curate-recent with "{arguments}"')
def operator_runs_curate_recent_with(context, arguments):
    run_curate_recent(context, shlex.split(arguments))


@then('a curation assignment is queued for "{names}"')
def curation_assignment_is_queued_for(context, names):
    assert context.curate_recent_refusal is None, context.curate_recent_refusal
    assert sorted(context.references_queued_for_curation) == sorted(names_listed_in(names)), context.references_queued_for_curation
    assert context.curate_recent_output["dispatchCount"] == len(names_listed_in(names)), context.curate_recent_output


@then("no curation assignment is queued")
def no_curation_assignment_is_queued(context):
    assert context.references_queued_for_curation == [], context.references_queued_for_curation


@then("no curation stage was tried")
def no_curation_stage_was_tried(context):
    assert context.publication.stages_tried == [], context.publication.stages_tried
    assert context.curate_recent_output["previewedEveryStage"] is False, context.curate_recent_output


@then('every curation stage was tried for "{names}"')
def every_curation_stage_was_tried_for(context, names):
    for name in names_listed_in(names):
        tried = [stage for reference_name, stage in context.publication.stages_tried if reference_name == name]
        assert tried == ["identifier", "title and subtitle", "summary", "quality"], (name, tried)
    assert context.curate_recent_output["previewedEveryStage"] is True, context.curate_recent_output


@then('the run lists "{names}" as the References it would queue')
def run_lists_references_it_would_queue(context, names):
    listed = context.curate_recent_output["selectedReferenceIds"]
    assert listed == sorted(reference_id_for(name) for name in names_listed_in(names)), listed


@then('the run reports that "{name}" could not be picked and exits as degraded')
def run_reports_reference_could_not_be_picked(context, name):
    failures = context.curate_recent_output["selectionFailures"]
    assert [failure["referenceId"] for failure in failures] == [reference_id_for(name)], failures
    assert context.curate_recent_output["degraded"] is True and context.curate_recent_exit_status == 2, context.curate_recent_output


@then('the curation run is refused with "{reason}"')
def run_is_refused_with(context, reason):
    assert context.curate_recent_refusal == reason, context.curate_recent_refusal


def build_the_operator_request(context, flags: list[str]):
    answer_from_the_newsroom_command = Mock(returncode=0, stdout='{"ok": true, "selectedReferenceIds": []}\n', stderr="")
    with patch.object(references_commands.subprocess, "run", return_value=answer_from_the_newsroom_command) as newsroom_command, contextlib.redirect_stdout(io.StringIO()):
        references_commands.references_curate_recent(["--corpus-key", "test-corpus", *flags])
    context.operator_request = newsroom_command.call_args.args[0]


@when("the operator command builds its request for a real run")
def operator_command_builds_request_for_real_run(context):
    build_the_operator_request(context, [])


@when("the operator command builds its request for a dry run")
def operator_command_builds_request_for_dry_run(context):
    build_the_operator_request(context, ["--dry-run"])


@then('the request asks for "{flags}"')
def request_asks_for(context, flags):
    for flag in shlex.split(flags):
        assert flag in context.operator_request, context.operator_request


@then('the request asks for the preview with "{flag}" and never "{absent_flag}"')
def request_asks_for_without(context, flag, absent_flag):
    assert flag in context.operator_request and absent_flag not in context.operator_request, context.operator_request
