"""The image operation table and its generated front ends (features_backend/image-operations.feature). Nothing here calls a model or the network."""

from __future__ import annotations

import io
import json
import re
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.images import cli as images_cli  # noqa: E402
from papyrus_content.images import generate, mcp  # noqa: E402
from papyrus_content.images.cli_generated import COMMANDS as ALL_COMMANDS  # noqa: E402
from papyrus_content.images.handlers import Caller, Outcome  # noqa: E402
from papyrus_content.images.operations import BY_NAME  # noqa: E402
from papyrus_content.images.operations import OPERATIONS as ALL_OPERATIONS  # noqa: E402
from papyrus_content.images.operations_test import argv_for, fake_handlers  # noqa: E402

OPERATIONS = [item for item in ALL_OPERATIONS if item.group == "images"]   # the guideline operations share the table; their specs are guidelines-cli.feature
COMMANDS = [entry for entry in ALL_COMMANDS if entry["group"] == "images"]
NAMES = [item.name for item in OPERATIONS]


def run_command(context, line, environ=None):
    out = io.StringIO()
    status = images_cli.command(line.split(), handlers=getattr(context, "handlers", None), environ=environ or {}, stdout=out)
    context.cli_status, context.cli_answer = status, json.loads(out.getvalue())


@then("the generated command spec, MCP schema, TypeScript types, skill reference block and docs are all current")
def step_current(context):
    assert generate.stale() == []


@then("the generator's check mode reports nothing out of date")
def step_check_mode(context):
    assert generate.main(["--check"]) == 0


@then("the command spec, the MCP tool schema, the TypeScript types, the skill block and the docs each list the same operations as the table, in the same order")
def step_cover(context):
    assert [entry["op"] for entry in COMMANDS] == NAMES
    assert list(mcp.image_tools()) == [item.name for item in ALL_OPERATIONS]
    assert re.findall(r"^  (image_[a-z_]+): \{ input:", generate.TS_TYPES.read_text(encoding="utf-8"), re.M) == NAMES
    skill = generate.SKILL.read_text(encoding="utf-8")
    assert re.findall(r"^\| `(image_[a-z_]+)` \| `papyrus images", skill[skill.index(generate.BEGIN):skill.index(generate.END)], re.M) == NAMES
    assert re.findall(r"^## (image_[a-z_]+)$", generate.DOCS.read_text(encoding="utf-8"), re.M) == NAMES


@then("the table has the 25 operations the design describes")
def step_count(context):
    assert len(NAMES) == 25


@then("the generate operation offers a speed of auto, standard or batch")
def step_speed(context):
    assert BY_NAME["image_generate"].input["properties"]["speed"]["enum"] == ["auto", "standard", "batch"]


@given("a backend that answers {name} with its documented example")
def step_backend_example(context, name):
    context.handlers = fake_handlers()
    context.item = BY_NAME[name]


@when("the example input for {name} is given as a command line")
def step_example_command(context, name):
    out = io.StringIO()
    argv = argv_for(BY_NAME[name], BY_NAME[name].examples[0].input, Path(tempfile.mkdtemp()))
    context.cli_status = images_cli.command(argv, handlers=context.handlers, environ={}, stdout=out)
    context.cli_answer = json.loads(out.getvalue())


@when("the same input is sent as the MCP tool {name}")
def step_example_mcp(context, name):
    context.mcp_answer = mcp.call_image_tool(name, BY_NAME[name].examples[0].input, Caller(), context.handlers)


@then("both answer with the same JSON")
def step_same(context):
    assert context.cli_answer == context.mcp_answer


@then("that JSON is a success from the backend's publication carrying the documented example result")
def step_success(context):
    assert context.cli_status == 0
    assert context.cli_answer == {"ok": True, "op": context.item.name, "publication": "machines-on-machines", "result": context.item.examples[0].result, "warnings": []}


@given("a backend that would answer {name}")
def step_backend_counting(context, name):
    context.calls = []

    def handler(arguments, caller):
        context.calls.append(arguments)
        return Outcome({"mediaAssetId": "media-asset-1", "decision": "keep", "reviewStatus": "human-verified"}, "machines-on-machines")

    context.handlers = {name: handler}


@when('an agent runs the command "{line}"')
def step_agent_command(context, line):
    run_command(context, line, {"PAPYRUS_ACTOR_KIND": "agent"})


@when('a person runs the command "{line}"')
def step_person_command(context, line):
    run_command(context, line)


@when("an agent calls the MCP tool image_review for media-asset-1 with the decision keep")
def step_agent_mcp(context):
    context.mcp_answer = mcp.call_image_tool("image_review", {"mediaAssetId": "media-asset-1", "decision": "keep"}, Caller(kind="agent"), context.handlers)


@then("both answer that a person is required")
def step_person_required(context):
    assert context.cli_answer["error"]["code"] == context.mcp_answer["error"]["code"] == "human_required"
    assert context.cli_answer == context.mcp_answer


@then("the backend was never called")
def step_never_called(context):
    assert context.calls == []


@then("the command exits with the error code")
def step_error_code(context):
    assert context.cli_status == 2


@then("the command succeeds and the backend was called once")
def step_succeeds_once(context):
    assert context.cli_status == 0 and len(context.calls) == 1


@when("the MCP tool image_paint is called")
def step_unknown_tool(context):
    context.mcp_answer = mcp.call_image_tool("image_paint", {}, Caller())


@then("both answer that the operation is unknown")
def step_unknown(context):
    assert context.cli_answer["error"]["code"] == context.mcp_answer["error"]["code"] == "unknown_operation"


@when("the MCP tool image_generate is called with the use banner")
def step_bad_use_mcp(context):
    context.mcp_answer = mcp.call_image_tool("image_generate", {"target": {"kind": "story", "lineageId": "story-1"}, "use": "banner", "brief": "x"}, Caller())


@then('both answer that the input is invalid, naming the field "{field}"')
def step_invalid_both(context, field):
    for answer in (context.cli_answer, context.mcp_answer):
        assert answer["error"]["code"] == "invalid_input" and answer["error"]["details"]["path"] == field


@then("the answers are identical")
def step_identical(context):
    assert context.cli_answer == context.mcp_answer


@when('the MCP tool image_round_get is called with an extra property "{name}"')
def step_extra(context, name):
    context.mcp_answer = mcp.call_image_tool("image_round_get", {"roundId": "round-1", name: 1}, Caller())


@then('it answers that the input is invalid, naming the field "{field}"')
def step_invalid_one(context, field):
    assert context.mcp_answer["error"]["code"] == "invalid_input" and context.mcp_answer["error"]["details"]["path"] == field


@when("every operation that is not built is run with its example input and the default handlers")
def step_all_default(context):
    from papyrus_content.images.generation_binding import OPERATION_METHODS   # generation is built (step 5)
    from papyrus_content.images.profile_handlers import PROFILE_HANDLERS   # the style profile operations are built (step 2)

    context.answers = [(item, mcp.call_image_tool(item.name, item.examples[0].input, Caller())) for item in OPERATIONS
                       if item.name not in PROFILE_HANDLERS and item.name not in OPERATION_METHODS]
    run_command(context, "show candidate-1")


@then("each answers not_implemented and names its operation")
def step_not_implemented(context):
    for item, answer in context.answers:
        assert answer["error"]["code"] == "not_implemented" and answer["error"]["details"] == {"operation": item.name}


@when("the MCP tool image_generate is called with an empty image type")
def step_empty_type_mcp(context):
    context.mcp_answer = mcp.call_image_tool(
        "image_generate", {"target": {"kind": "story", "lineageId": "story-1"}, "use": "cover", "imageType": "", "brief": "x"}, Caller())


@when("the MCP tool image_figure_add is called without an image type")
def step_figure_without_type(context):
    figure = BY_NAME["image_figure_add"].examples[0].input
    context.mcp_answer = mcp.call_image_tool("image_figure_add", {key: value for key, value in figure.items() if key != "imageType"}, Caller())


@then("image_type_required, image_type_unknown and source_not_allowed are in the shared error table")
def step_type_errors(context):
    from papyrus_content.images.operations import ERROR_BY_CODE
    assert {"image_type_required", "image_type_unknown", "source_not_allowed"} <= set(ERROR_BY_CODE)


@then("image_figure_add names image_type_unknown, source_not_allowed, checks_failed and not_found")
def step_figure_errors(context):
    assert set(BY_NAME["image_figure_add"].errors) == {"image_type_unknown", "source_not_allowed", "checks_failed", "not_found"}
