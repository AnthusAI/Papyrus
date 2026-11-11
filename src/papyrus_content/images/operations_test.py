"""The image operation table, what is generated from it, and the adapters over it (features_backend/image-operations.feature has the narrative)."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from papyrus_content.images import cli as images_cli
from papyrus_content.images import generate, mcp
from papyrus_content.images.cli_generated import COMMANDS as ALL_COMMANDS
from papyrus_content.images.handlers import HANDLERS, Caller, ImageOperationError, Outcome, check, execute
from papyrus_content.images.operations import BY_NAME, COMMON_ERRORS, ERROR_BY_CODE, ERRORS
from papyrus_content.images.operations import OPERATIONS as ALL_OPERATIONS

# This file is about the image operations. The guideline operations share the table and the generators (guidelines/operations_test.py covers them).
OPERATIONS = tuple(item for item in ALL_OPERATIONS if item.group == "images")
COMMANDS = [entry for entry in ALL_COMMANDS if entry["group"] == "images"]
NAMES = [item.name for item in OPERATIONS]
ALL_NAMES = [item.name for item in ALL_OPERATIONS]
DESIGN_NAMES = {
    "image_profile_get", "image_profile_resolve", "image_profile_diff", "image_profile_save", "image_profile_history", "image_profile_example_add",
    "image_profile_example_remove", "image_capabilities", "image_brief_draft", "image_prompt_preview", "image_search", "image_generate", "image_round_get",
    "image_candidate_get", "image_list", "image_retry", "image_iterate", "image_select", "image_unapply", "image_review", "image_review_queue",
    "image_apply", "image_discard", "image_figure_add", "image_profile_init",
}


def fake_handlers():
    """A backend that answers each operation with its example's result, after checking it was sent exactly the example's input."""
    def make(item):
        def handler(arguments, caller):
            example = item.examples[0]
            assert arguments == example.input, (item.name, arguments)
            return Outcome(result=example.result, publication="machines-on-machines")
        return handler
    return {item.name: make(item) for item in OPERATIONS}


def run_cli(argv, handlers=None, environ=None):
    out = io.StringIO()
    status = images_cli.command(argv, handlers=handlers, environ=environ or {}, stdout=out)
    return status, json.loads(out.getvalue())


def argv_for(item, arguments, tmp_path):
    """The command line that says ``arguments``, built only from the generated flag specs."""
    spec = next(entry for entry in COMMANDS if entry["op"] == item.name)
    argv, left = list(spec["words"]), dict(arguments)
    for field in spec["positional"]:
        if field in left:
            argv.append(left.pop(field))
    if spec["file"] in left:
        path = tmp_path / "document.json"
        path.write_text(json.dumps(left.pop(spec["file"])), encoding="utf-8")
        argv += ["--file", str(path)]
    for entry in spec["flags"]:
        field = entry["field"]
        if field not in left:
            continue
        if entry["kind"] == "target":
            if left[field]["kind"] == entry["targetKind"]:
                argv += [entry["flag"], left.pop(field)["lineageId"]]
        elif entry["kind"] == "array":
            for value in left.pop(field):
                argv += [entry["flag"], value]
        elif entry["kind"] == "boolean":
            argv.append(entry["flag"] if left.pop(field) else "--no-" + entry["flag"][2:])
        else:
            argv += [entry["flag"], str(left.pop(field))]
    if left:   # objects have no flag: they go in a file
        path = tmp_path / "input.json"
        path.write_text(json.dumps(left), encoding="utf-8")
        argv += ["--input-file", str(path)]
    return argv


# --- the table ---------------------------------------------------------------------------------------------------------------------------------

def test_the_table_has_every_operation_in_the_design():
    assert set(NAMES) == DESIGN_NAMES and len(NAMES) == len(set(NAMES))


def test_names_and_commands_are_unique_and_well_formed():
    assert all(re.fullmatch(r"image_[a-z_]+", name) for name in NAMES)
    assert len({item.cli for item in OPERATIONS}) == len(OPERATIONS)
    assert all(item.audience == "staff" and item.permission == "editor" and item.summary.endswith(".") for item in OPERATIONS)


def test_every_error_an_operation_names_is_in_the_shared_table():
    for item in OPERATIONS:
        assert set(item.errors) <= set(ERROR_BY_CODE), item.name
        assert not set(item.errors) & set(COMMON_ERRORS), f"{item.name} repeats a common error"
    assert {"capability_unsupported", "set_needs_person", "checks_failed", "batch_expired", "not_implemented"} <= set(ERROR_BY_CODE)
    assert len({error.code for error in ERRORS}) == len(ERRORS)


def test_a_person_only_operation_lists_human_required():
    assert [item.name for item in OPERATIONS if not item.agent_allowed] == ["image_review"]
    assert "human_required" in BY_NAME["image_review"].errors


def test_the_generate_operation_has_the_lane_option():
    assert BY_NAME["image_generate"].input["properties"]["speed"]["enum"] == ["auto", "standard", "batch"]
    assert BY_NAME["image_prompt_preview"].input is BY_NAME["image_generate"].input


def test_cli_fields_point_at_real_input_properties():
    for item in OPERATIONS:
        properties = item.input["properties"]
        assert set(item.positional) <= set(properties) and {field for field, _ in item.flags} <= set(properties), item.name
        assert item.file_field is None or item.file_field in properties


@pytest.mark.parametrize("item", OPERATIONS, ids=NAMES)
def test_every_example_fits_its_schemas(item):
    assert item.examples, "each operation needs an example for the docs and the parity test"
    for example in item.examples:
        assert check(item.input, example.input) is None, check(item.input, example.input)
        assert check(item.result, example.result) is None, check(item.result, example.result)


def test_the_input_checker_names_the_field():
    schema = BY_NAME["image_apply"].input
    assert check(schema, {"target": {"kind": "story", "lineageId": "s"}, "use": "cover", "expectedCurrentVersionId": "v"})[1] == "Give exactly one of: candidateId or candidateRef."
    assert check(schema, {"candidateId": "c", "target": {"kind": "other", "lineageId": "s"}, "use": "cover", "expectedCurrentVersionId": "v"})[0] == "target.kind"
    assert check(schema, {"candidateId": "c", "target": {"kind": "story", "lineageId": "s"}, "use": "cover", "expectedCurrentVersionId": "v", "bogus": 1})[0] == "bogus"


# --- generated files ---------------------------------------------------------------------------------------------------------------------------

def test_generated_files_are_current():
    assert generate.stale() == [], "run: python scripts/generate-image-operations.py"


def test_the_generator_check_exits_nonzero_when_something_is_stale(monkeypatch, capsys):
    monkeypatch.setattr(generate, "stale", lambda: [generate.DOCS])
    assert generate.main(["--check"]) == 1
    assert "docs/images.md" in capsys.readouterr().out


def test_each_front_end_covers_exactly_the_operations_in_the_table():
    assert [entry["op"] for entry in COMMANDS] == NAMES
    assert list(mcp.image_tools()) == ALL_NAMES and list(mcp.image_descriptions()) == ALL_NAMES and list(mcp.image_output_schemas()) == ALL_NAMES
    ts = generate.TS_TYPES.read_text(encoding="utf-8")
    assert re.findall(r"^  ((?:image|guidelines)_[a-z_]+): \{ input:", ts, re.M) == ALL_NAMES
    assert re.findall(r"^  ((?:image|guidelines)_[a-z_]+): \{ effect:", ts, re.M) == ALL_NAMES
    skill = generate.SKILL.read_text(encoding="utf-8")
    block = skill[skill.index(generate.BEGIN):skill.index(generate.END)]
    assert re.findall(r"^\| `(image_[a-z_]+)` \| `papyrus images", block, re.M) == NAMES
    docs = generate.DOCS.read_text(encoding="utf-8")
    assert re.findall(r"^## (image_[a-z_]+)$", docs, re.M) == NAMES


def test_the_skill_keeps_its_prose_and_front_matter():
    skill = generate.SKILL.read_text(encoding="utf-8")
    assert skill.startswith("---\nname: image-work\ndescription: Use when a Story or Reference needs a picture")
    assert generate.BEGIN in skill and generate.END in skill


def test_mcp_tools_have_the_shape_of_the_mcp_servers_table():
    for name, (audience, schema) in mcp.image_tools().items():
        assert audience == "staff" and schema["type"] == "object" and isinstance(schema["properties"], dict) and isinstance(schema["required"], list)
    assert all(text.endswith(".") for text in mcp.image_descriptions().values())


# --- the adapters -------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("item", OPERATIONS, ids=NAMES)
def test_the_cli_and_the_mcp_tool_give_identical_json(item, tmp_path):
    handlers = fake_handlers()
    example = item.examples[0]
    status, from_cli = run_cli(argv_for(item, example.input, tmp_path), handlers)
    from_mcp = mcp.call_image_tool(item.name, example.input, Caller(), handlers)
    assert status == 0
    assert from_cli == from_mcp == {"ok": True, "op": item.name, "publication": "machines-on-machines", "result": example.result, "warnings": []}


def test_every_handler_answers_not_implemented_until_its_step():
    from papyrus_content.images.profile_handlers import PROFILE_HANDLERS   # built in step 2; the rest wait for their own steps

    for item in (item for item in OPERATIONS if item.name not in PROFILE_HANDLERS):
        envelope = execute(item.name, item.examples[0].input, Caller())
        assert envelope["error"]["code"] == "not_implemented" and envelope["error"]["details"] == {"operation": item.name}
    assert set(HANDLERS) == set(ALL_NAMES)


def test_the_cli_exits_with_the_shared_code_and_prints_json():
    status, envelope = run_cli(["round", "round-1"])
    assert status == 2 and envelope["ok"] is False and envelope["error"]["code"] == "not_implemented"


def test_an_agent_is_refused_an_operation_only_a_person_may_call():
    called = []
    handlers = {"image_review": lambda arguments, caller: called.append(1)}
    arguments = {"mediaAssetId": "media-asset-1", "decision": "keep"}
    status, from_cli = run_cli(["review", "media-asset-1", "--decision", "keep"], handlers, {"PAPYRUS_ACTOR_KIND": "agent"})
    from_mcp = mcp.call_image_tool("image_review", arguments, Caller(kind="agent"), handlers)
    assert status == 2 and called == []
    assert from_cli["error"]["code"] == "human_required"
    assert from_cli == from_mcp
    person = {"image_review": lambda a, c: Outcome({"mediaAssetId": "m", "decision": "keep", "reviewStatus": "human-verified"}, "p")}
    assert run_cli(["review", "media-asset-1", "--decision", "keep"], person)[0] == 0


def test_the_mcp_principal_decides_who_is_an_agent():
    class Principal:
        is_agent, subject, delegated_by = True, "account-1", "account-2"

    assert mcp.caller_from_principal(Principal()) == Caller(kind="agent", subject="account-1", delegated_by="account-2")
    assert mcp.caller_from_principal(object()) == Caller(kind="person")


def test_an_unknown_operation_is_an_error_not_a_crash():
    envelope = execute("image_paint", {})
    assert envelope == mcp.call_image_tool("image_paint", {}, Caller()) and envelope["error"]["code"] == "unknown_operation"
    status, from_cli = run_cli(["paint", "everything"])
    assert status == 2 and from_cli["error"]["code"] == "unknown_operation"


@pytest.mark.parametrize("argv, arguments, path", [
    (["round"], {}, "roundId"),
    (["round", "r1", "--bogus", "x"], None, "--bogus"),
    (["round", "r1", "r2"], None, "arguments"),
    (["profile", "get", "--version", "two"], None, "--version"),
    (["profile", "get", "--version", "0"], {"version": 0}, "version"),
    (["generate", "--story", "s", "--use", "banner", "--brief", "x"], {"target": {"kind": "story", "lineageId": "s"}, "use": "banner", "brief": "x"}, "use"),
    (["discard", "--reason", "x"], {"reason": "x"}, ""),
    (["generate", "--story", "s", "--use", "cover", "--brief", "x", "--image-type="], {"target": {"kind": "story", "lineageId": "s"}, "use": "cover", "brief": "x", "imageType": ""}, "imageType"),
    (["search", "--story", "s", "--image-type="], {"target": {"kind": "story", "lineageId": "s"}, "imageType": ""}, "imageType"),
])
def test_bad_arguments_return_invalid_input_the_same_way_from_both(argv, arguments, path):
    status, from_cli = run_cli(argv, fake_handlers())
    assert status == 2 and from_cli["error"]["code"] == "invalid_input" and from_cli["error"]["details"]["path"] == path
    if arguments is not None:
        spec = max((entry for entry in COMMANDS if argv[: len(entry["words"])] == entry["words"]), key=lambda entry: len(entry["words"]))
        assert mcp.call_image_tool(spec["op"], arguments, Caller(), fake_handlers()) == from_cli


def test_image_types_are_in_the_table():
    assert len(NAMES) == 25
    for name in ("image_profile_resolve", "image_brief_draft", "image_search", "image_generate", "image_prompt_preview", "image_apply", "image_profile_example_add"):
        assert "imageType" in BY_NAME[name].input["properties"], name
    assert "imageType" in BY_NAME["image_profile_example_add"].input["required"]
    generate_input = BY_NAME["image_generate"].input["properties"]
    assert generate_input["spread"]["enum"] == ["variations", "types"] and "imageTypes" in generate_input and "treatments" not in generate_input
    assert dict(BY_NAME["image_generate"].flags)["imageTypes"] == "image-types"
    summary = BY_NAME["image_round_get"].result["properties"]["candidates"]["items"]["properties"]
    assert "imageType" in summary and summary["origin"]["enum"] == ["generated", "stock", "figure"]
    for code in ("image_type_required", "image_type_unknown", "source_not_allowed"):
        assert code in ERROR_BY_CODE


def test_the_figure_operation_records_a_figure_and_draws_nothing():
    item = BY_NAME["image_figure_add"]
    assert item.effect == "write" and item.agent_allowed and item.cli == ("figure", "add")
    assert set(item.errors) == {"image_type_unknown", "source_not_allowed", "checks_failed", "not_found"}
    assert check(item.input, {**item.examples[0].input, "imageType": None})[0] == "imageType"
    without_pictures = {key: value for key, value in item.examples[0].input.items() if key != "uploadIds"}
    assert check(item.input, without_pictures)[1] == "Give exactly one of: uploadIds or figureId."


def test_a_property_the_operation_does_not_have_is_refused_over_mcp():
    envelope = mcp.call_image_tool("image_round_get", {"roundId": "r", "extra": 1}, Caller(), fake_handlers())
    assert envelope["error"]["code"] == "invalid_input" and envelope["error"]["details"]["path"] == "extra"


def test_dry_run_checks_the_input_and_calls_nothing():
    called = []
    handlers = {"image_generate": lambda arguments, caller: called.append(arguments)}
    status, envelope = run_cli(["generate", "--story", "s", "--use", "cover", "--brief", "a cabinet", "--speed", "batch", "--dry-run"], handlers)
    assert status == 0 and called == []
    assert envelope["result"] == {"dryRun": True, "input": {"target": {"kind": "story", "lineageId": "s"}, "use": "cover", "brief": "a cabinet", "speed": "batch"}}
    assert run_cli(["round", "r1", "--dry-run"])[1]["error"]["details"]["path"] == "--dry-run"   # reads have nothing to preview
    assert run_cli(["generate", "--dry-run"])[1]["error"]["code"] == "invalid_input"


def test_flags_override_an_input_file_and_booleans_have_a_negative(tmp_path):
    seen = []
    path = tmp_path / "input.json"
    path.write_text(json.dumps({"target": {"kind": "story", "lineageId": "s"}, "mediaAssetId": "m", "reason": "from file", "expectedCurrentVersionId": "v1"}))
    handlers = {"image_unapply": lambda arguments, caller: seen.append(arguments) or Outcome({"patch": {}, "restored": "placeholder"}, "p")}
    assert run_cli(["unapply", "--input-file", str(path), "--reason", "from flag", "--no-save"], handlers)[0] == 0
    assert seen == [{"target": {"kind": "story", "lineageId": "s"}, "mediaAssetId": "m", "reason": "from flag", "expectedCurrentVersionId": "v1", "save": False}]


def test_a_handler_error_keeps_its_code_details_and_retry_flag():
    def busy(arguments, caller):
        raise ImageOperationError("provider_busy", details={"retryAfterSeconds": 30})

    status, envelope = run_cli(["retry", "candidate-3"], {"image_retry": busy})
    assert status == 2 and envelope["error"] == {"code": "provider_busy", "message": ERROR_BY_CODE["provider_busy"].message, "retryable": True,
                                                 "details": {"retryAfterSeconds": 30}}


def test_the_routes_and_their_usage_come_from_the_generated_spec():
    tree = images_cli.route_tree()
    assert set(tree) == {"profile", "capabilities", "brief", "prompt", "search", "generate", "round", "show", "list", "retry", "iterate", "select", "unapply",
                         "review", "review-queue", "apply", "discard", "figure"}
    assert set(tree["figure"]) == {"add"}
    assert set(tree["profile"]) == {"get", "resolve", "diff", "save", "history", "init", "example"} and set(tree["profile"]["example"]) == {"add", "remove"}
    assert images_cli.usage_for(["generate"]).startswith("Usage: papyrus images generate (--story ID | --reference ID)")
    assert "[--dry-run]" in images_cli.usage_for(["generate"]) and "[--dry-run]" not in images_cli.usage_for(["round"])


def test_the_generator_script_exists_where_the_docs_say():
    assert (Path(generate.REPO_ROOT) / "scripts" / "generate-image-operations.py").exists()
