"""The Story procedure (features_backend/story-procedure.feature). The backend is the in-memory fake; nothing here calls AWS or a model."""

from __future__ import annotations

import io
import json
import shlex
import sys
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from fake_client import FakeAuthoringClient  # noqa: E402
from papyrus_content import newsroom_process as process  # noqa: E402
from papyrus_content import story_commands  # noqa: E402
from papyrus_content.story_reporting import current_story_version  # noqa: E402

LINEAGE = "story-1"
NOW = "2026-11-03T09:00:00.000000Z"
FRONT_MATTER = 'title: "Board refuses"'


class World:
    def __init__(self, stage: str | None):
        self.stage = stage
        self.version_number = 1
        self.outline_version = None
        self.body = ""
        self.assignments: list[dict] = []
        self.packets: set[str] = set()
        self.check_run = None
        self.check_error = False
        self.review = None
        self.fail_reminder = False
        self.client = None

    def build(self) -> FakeAuthoringClient:
        rows = []
        for number in range(1, self.version_number + 1):
            current = number == self.version_number
            metadata = {"frontMatterYaml": FRONT_MATTER}
            if current and self.outline_version is not None:
                metadata["outline"] = {"versionId": f"{LINEAGE}-v{self.outline_version}", "versionNumber": self.outline_version, "at": NOW, "by": "AI"}
            if current and self.review:
                metadata["editorReview"] = {"versionId": f"{LINEAGE}-v{self.review['version']}", "verdict": self.review["verdict"]}
            rows.append({
                "id": f"{LINEAGE}-v{number}", "lineageId": LINEAGE, "versionNumber": number, "versionState": "current" if current else "superseded",
                "type": "article", "slug": "board", "section": None, "status": "draft", "stage": self.stage, "headline": "Board refuses",
                "title": "Board refuses", "aliases": [], "metadata": json.dumps(metadata), "bodyMarkus": self.body or "First.",
                "createdAt": NOW, "updatedAt": NOW, "versionCreatedAt": f"2026-11-03T09:0{number}:00Z",
            })
        if self.stage is None:
            rows = []
        assignments = [{"id": a["id"], "itemLineageId": a["lineage"], "title": "Research", "createdAt": NOW, **a["fields"]} for a in self.assignments]
        self.client = FakeAuthoringClient({"Item": rows, "Assignment": assignments})
        return self.client


def world(context) -> World:
    return context.world


def client_of(context) -> FakeAuthoringClient:
    current = world(context)
    return current.client or current.build()


def read_check_run(context):
    def read(item_id):
        if world(context).check_error:
            raise RuntimeError("the check store is unreachable")
        return world(context).check_run

    return read


def patched(context) -> ExitStack:
    stack = ExitStack()
    current, client = world(context), client_of(context)
    stack.enter_context(patch.object(story_commands, "create_authoring_client", lambda: (client, None)))
    stack.enter_context(patch("papyrus_content.graphql_authoring.create_authoring_client", lambda: (client, None)))
    stack.enter_context(patch("papyrus_content.editorial_commands.read_item_check_run", read_check_run(context)))
    stack.enter_context(patch("papyrus_content.assignments_workflow.load_assignment_research_packet_entries",
                              lambda _client, assignment_id: [{}] if assignment_id in current.packets else []))
    if current.fail_reminder:
        def broken(*_args, **_kwargs):
            raise RuntimeError("the records could not be read")

        stack.enter_context(patch.object(process, "story_facts", broken))
    return stack


def assessment_of(context) -> dict:
    with patched(context):
        return process.assess(process.story_facts(client_of(context), LINEAGE, read_check_run(context)))


def step_row(context, key: str) -> dict:
    return next(row for row in context.assessment["steps"] if row["key"] == key)


@given('a Story at the "{stage}" stage')
def story_at_stage(context, stage):
    context.world = World(stage)


@given("an empty newsroom")
def empty_newsroom(context):
    context.world = World(None)


@given("an Assignment with no Story")
def assignment_without_story(context):
    context.world = World("idea")
    context.world.assignments.append({"id": "a1", "lineage": None, "fields": {}})


@given("an Assignment on the Story with a direction")
def assignment_with_direction(context):
    world(context).assignments.append({"id": "a1", "lineage": LINEAGE, "fields": {"metadata": json.dumps({"direction": "Look into the board."})}})
    world(context).client = None


@given("an Assignment on the Story with instructions but no direction")
def assignment_with_instructions(context):
    world(context).assignments.append({"id": "a1", "lineage": LINEAGE, "fields": {"metadata": "{}", "instructions": "Look into the board."}})
    world(context).client = None


@given("the Assignment has a research packet")
def assignment_with_packet(context):
    world(context).packets.add("a1")


@given("the current version is number {number:d} and the outline marker is on version {outline:d}")
def versions_and_outline(context, number, outline):
    world(context).version_number, world(context).outline_version = number, outline
    world(context).client = None


@given('the current body is "{body}"')
def current_body(context, body):
    world(context).body = body
    world(context).client = None


def finished_run(findings):
    return {"id": f"{LINEAGE}-v1", "lanes": {"humanus": {"status": "ran"}}, "findings": findings}


@given("a finished check of the current version with no violation")
def check_clean(context):
    world(context).check_run = finished_run([])


@given("a finished check of the current version with an error-level violation")
def check_error_level(context):
    world(context).check_run = finished_run([{"status": "violation", "severity": "error", "policyId": "p1"}])


@given("a finished check of the current version with a warning-level violation")
def check_warning_level(context):
    world(context).check_run = finished_run([{"status": "violation", "severity": "warn", "policyId": "p1"}])


@given("a check of the current version whose lanes have not finished")
def check_unfinished(context):
    world(context).check_run = {"id": f"{LINEAGE}-v1", "lanes": {"humanus": {"status": "pending"}}, "findings": []}


@given("the check record cannot be read")
def check_unreadable(context):
    world(context).check_error = True


@given('an editor review of the current version with the verdict "{verdict}"')
def review_of_current(context, verdict):
    world(context).review = {"version": world(context).version_number, "verdict": verdict}
    world(context).client = None


@given('an editor review of an earlier version with the verdict "{verdict}"')
def review_of_earlier(context, verdict):
    world(context).review = {"version": 0, "verdict": verdict}
    world(context).client = None


@given("a Reference \"{reference}\" exists")
def reference_exists(context, reference):
    context.reference = reference


@given("computing the reminder fails")
def reminder_fails(context):
    world(context).fail_reminder = True


@when("the procedure is assessed")
def procedure_assessed(context):
    context.assessment = assessment_of(context)


@when("the next lines are written")
def next_lines_written(context):
    context.assessment = assessment_of(context)
    context.lines = process.next_lines(context.assessment)


@when('I run "{command}" with "{flags}"')
def run_command(context, command, flags):
    handlers = {
        "stories next": story_commands.stories_next,
        "stories save-version": story_commands.stories_save_version,
        "stories move": story_commands.stories_move,
        "stories link-reference": story_commands.stories_link_reference,
        "stories assign-research": story_commands.stories_assign_research,
        "stories create": story_commands.stories_create,
        "stories step": story_commands.stories_step,
        "stories checklist-backfill": story_commands.stories_checklist_backfill,
    }
    out, err = io.StringIO(), io.StringIO()
    context.succeeded, context.error = True, None
    with ExitStack() as stack:
        stack.enter_context(patched(context))
        client = client_of(context)
        stack.enter_context(patch.object(story_commands, "link_reference_to_story", lambda *a, **k: {"outcome": "linked", "relationId": "r1", "referenceLineageId": "ref-1"}))
        stack.enter_context(patch("papyrus_content.assignments_workflow.create_research_assignment", assign_research_fake(client)))
        stack.enter_context(redirect_stdout(out))
        stack.enter_context(redirect_stderr(err))
        try:
            handlers[command](shlex.split(flags))
        except Exception as error:
            context.succeeded, context.error = False, error
    context.output, context.errors = out.getvalue(), err.getvalue()


def assign_research_fake(client):
    def create(_client, options):
        client.create_record("Assignment", {"id": "a-new", "itemLineageId": options["content-item"], "title": "Research", "createdAt": NOW,
                                            "metadata": json.dumps({"direction": options.get("direction")})})
        return {"assignmentId": "a-new"}

    return create


def report_research(context, flags, action="completed"):
    from papyrus_content.multi_search_research import research_multi_command

    result = {"action": action, "assignmentId": "a1", "queries": [], "sourceCount": 0, "contribution": {}, "error": "provider failed"}
    out = io.StringIO()
    with patched(context), patch("papyrus_content.multi_search_research.research_multi", lambda client, options: result), redirect_stdout(out):
        research_multi_command(flags)
    context.output = out.getvalue()


@when("the research of that Assignment is reported")
def research_reported(context):
    report_research(context, ["--assignment", "a1"])


@when("the failed research of that Assignment is reported")
def research_failed(context):
    report_research(context, ["--assignment", "a1"], action="failed")


@when("the research of that Assignment is reported as JSON")
def research_reported_json(context):
    report_research(context, ["--assignment", "a1", "--json"])


@then('the procedure step "{key}" is "{state}"')
def step_is(context, key, state):
    assert step_row(context, key)["state"] == state, (key, step_row(context, key))


@then('the procedure step "{key}" has the status "{status}"')
def step_status(context, key, status):
    assert step_row(context, key)["status"] == status


@then('the next step is "{key}"')
def next_is(context, key):
    assert context.assessment["next"]["key"] == key, context.assessment["next"]


@then("the Story has no next step")
def no_next(context):
    assert context.assessment["next"] is None and context.assessment["skipped"] == []


def lines_of(context):
    return [line.split("\t") for line in context.output.splitlines()]


@then('the procedure output has a line starting "skipped" for "{key}"')
def output_skipped(context, key):
    assert ["skipped", key] == next((line[:2] for line in lines_of(context) if line[:2] == ["skipped", key]), None), context.output


@then('the procedure output has no line starting "skipped" for "{key}"')
def output_not_skipped(context, key):
    assert not [line for line in lines_of(context) if line[:2] == ["skipped", key]], context.output


@then("the procedure output has a step line for each of the {count:d} steps")
def output_step_lines(context, count):
    assert len([line for line in lines_of(context) if line[:1] == ["step"]]) == count == len(process.STEPS)


@then('the procedure output has a "next" line for "{key}"')
def output_next_for(context, key):
    assert any(line[:2] == ["next", key] for line in lines_of(context)), context.output


@then('the procedure output has a "next" line')
def output_has_next(context):
    assert any(line[:1] == ["next"] for line in lines_of(context)), context.output


@then('the procedure output has no "next" line')
def output_no_next(context):
    assert not any(line[:1] == ["next"] for line in lines_of(context)), context.output


@then('no next line offers a command for "{key}"')
def no_command_for(context, key):
    row = step_row(context, key)
    assert row["command"] == "" and row["status"] != "live"
    assert all("papyrus" not in line for line in context.lines if line.split("\t")[1:2] == [key])


@then("the procedure command wrote no records")
def nothing_written(context):
    assert client_of(context).write_calls() == []


@then("the new version was saved")
def version_saved(context):
    assert current_story_version(client_of(context), LINEAGE)["versionNumber"] == 2


@then("the procedure command succeeded")
def command_succeeded(context):
    assert context.succeeded, repr(context.error)


@then('the Story is at the "{stage}" stage')
def story_is_at(context, stage):
    assert current_story_version(client_of(context), LINEAGE)["stage"] == stage


@then("one line about the reminder is written to the error output")
def one_error_line(context):
    lines = context.errors.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("next\tnot computed"), context.errors


@then('the warning names the skipped step "{key}"')
def warning_names(context, key):
    assert any(line.startswith("warning:") and f"'{key}'" in line for line in context.errors.splitlines()), context.errors


@then("the procedure error output has no warning")
def no_warning(context):
    assert "warning:" not in context.errors, context.errors


@then("the JSON result carries the next step")
def json_carries_next(context):
    payload = json.loads(context.output)
    assert payload["next"]["key"], payload


@then("the Story's current version carries the outline marker for version {number:d}")
def outline_marker(context, number):
    metadata = json.loads(current_story_version(client_of(context), LINEAGE)["metadata"])
    assert metadata["outline"]["versionNumber"] == number and metadata["outline"]["by"] == "AI", metadata


@then('the procedure step "{key}" reads "{state}" for the Story')
def step_reads(context, key, state):
    context.assessment = assessment_of(context)
    assert step_row(context, key)["state"] == state, step_row(context, key)


@then("every step key appears in the table of docs/story-procedure.md")
def docs_table_lists_steps(context):
    text = (REPO_ROOT / "docs" / "story-procedure.md").read_text(encoding="utf-8")
    rows = {line.split("|")[1].strip() for line in text.splitlines() if line.startswith("|")}
    missing = [step.key for step in process.STEPS if step.key not in rows]
    assert not missing, missing
