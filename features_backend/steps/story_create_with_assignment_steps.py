from __future__ import annotations

import io
import contextlib
from unittest.mock import patch

from behave import then, when

from papyrus_content import story_commands

REFERENCE = "reference-lineage-1"


def _run(context, flags, *, assignment_error=None):
    context.assignment_options = None
    context.linked = []

    def fake_assignment(client, options):
        context.assignment_options = options
        if assignment_error:
            raise ValueError(assignment_error)
        return {}

    def fake_link(client, lineage_id, reference_id, **kwargs):
        context.linked.append((lineage_id, reference_id, kwargs.get("role")))
        return {"referenceLineageId": reference_id}

    out, err = io.StringIO(), io.StringIO()
    context.exit_code = 0
    with patch.object(story_commands, "create_authoring_client", return_value=(context.client, {})), \
            patch.object(story_commands, "link_reference_to_story", fake_link), \
            patch.object(story_commands, "print_reminder", lambda *_: None), \
            patch("papyrus_content.assignments_workflow.create_reporting_assignment", fake_assignment), \
            patch("papyrus_content.story_triggers.deliver_from_environment", lambda *_: None), \
            patch.dict("os.environ", {"PAPYRUS_SITE_STATIC_DIR": str(context.folder)}), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            story_commands.stories_create(flags)
        except SystemExit as exit_:
            context.exit_code = exit_.code
    context.stdout, context.stderr = out.getvalue(), err.getvalue()


@when('an editor creates a post "{title}" with a reference and --with-assignment')
def step_ok(context, title):
    _run(context, ["--title", title, "--type", "post", "--reference", REFERENCE, "--with-assignment"])


@when('an editor creates a post "{title}" with a reference and --with-assignment but the assignment step fails with "{reason}"')
def step_fail(context, title, reason):
    _run(context, ["--title", title, "--type", "post", "--reference", REFERENCE, "--with-assignment"], assignment_error=reason)


@when('an editor dry-runs creating a post "{title}" with a reference and --with-assignment')
def step_dry(context, title):
    _run(context, ["--title", title, "--type", "post", "--reference", REFERENCE, "--with-assignment", "--dry-run"])


@then('the assignment was requested with the type "{kind}"')
def step_type(context, kind):
    assert context.assignment_options and context.assignment_options["type"] == kind, context.assignment_options


@then("the command succeeds and the reference is attached")
def step_success(context):
    assert context.exit_code == 0 and [r for _, r, _ in context.linked] == [REFERENCE], (context.exit_code, context.linked, context.stderr)


@then("the command exits non-zero")
def step_nonzero(context):
    assert context.exit_code == 1, context.exit_code


@then("the reference is attached to the story")
def step_attached(context):
    assert [r for _, r, role in context.linked] == [REFERENCE] and context.linked[0][2] == "based_on", context.linked


@then('the summary says "{a}" and "{b}" and a retry command')
def step_summary(context, a, b):
    assert "Story created (lineage " in context.stderr and a in context.stderr and b in context.stderr, context.stderr
    assert "assignments create-reporting" in context.stderr, context.stderr


@then("the output mentions one reference and a reporting.candidate Assignment")
def step_dry_out(context):
    assert "1 reference(s) would be attached" in context.stdout and "reporting.candidate" in context.stdout, context.stdout


@then("no reference or assignment is written")
def step_nothing(context):
    assert not context.linked and context.assignment_options is None
