"""The guideline operations: the table they are generated from, the handlers, the door and the command line (features_backend/guidelines-door.feature and
guidelines-cli.feature have the narrative). A fake backend and in-memory files; no network, no AWS."""
from __future__ import annotations

import io
import json
import re
from dataclasses import replace

import pytest

from papyrus.operator.command_usage import usage_for_path
from papyrus_content.guidelines import cli as guidelines_cli
from papyrus_content.guidelines import register_kind, unregister_kind, KindSpec, Field
from papyrus_content.guidelines.document import PROSE, texts
from papyrus_content.guidelines.fakes import FakeBackend, FakeFiles
from papyrus_content.guidelines.handlers import GUIDELINE_HANDLERS, with_client
from papyrus_content.guidelines.s3_files import PAYLOAD_PREFIX, S3DocumentFiles
from papyrus_content.image_service import handle
from papyrus_content.images import generate, mcp
from papyrus_content.images.cli_generated import COMMANDS as ALL_COMMANDS
from papyrus_content.images.handlers import Caller, Outcome, execute
from papyrus_content.images.operations import BY_NAME, OPERATIONS
from papyrus_content.images.profile_fakes import FakeBackend as ImageBackend, profile_copy

GUIDELINES = [item for item in OPERATIONS if item.group == "guidelines"]
NAMES = [item.name for item in GUIDELINES]
COMMANDS = [entry for entry in ALL_COMMANDS if entry["group"] == "guidelines"]

EDITOR = {"claims": {"name": "Edie Editor"}, "groups": ["editor"], "username": "edie"}
ADMIN = {"claims": {"name": "Ada Admin"}, "groups": ["admin"], "username": "ada"}
READER = {"claims": {"name": "Rae Reader"}, "groups": [], "username": "rae"}
WRITING = {"schemaVersion": 1, "audience": "General readers", "tone": ["Warm and plain."], "constraints": [{"id": "no-hype", "text": "No hype."}], "locked": ["headline"]}
VIDEO = {"schemaVersion": 1, "bodyMarkus": "Show the screen, not the speaker."}


def world(*, saved=True):
    backend = FakeBackend(publication="ours")
    files = FakeFiles(backend)
    if saved:
        door(backend, "guidelinesWrite", ADMIN, "guidelines_save", requestId="seed", input={"kind": "writing", "document": WRITING, "reason": "First", "expectedCurrentVersionId": "none"})
    return backend, files


def door(backend, name, identity, op, **arguments):
    if "input" in arguments and not isinstance(arguments["input"], str):
        arguments["input"] = json.dumps(arguments["input"])
    return handle({"fieldName": name, "identity": identity, "arguments": {"op": op, **arguments}}, client_factory=lambda: backend,
                  files_factory=lambda client: getattr(backend, "document_files", None) or FakeFiles(backend))


def read(backend, identity=EDITOR, **input):
    return door(backend, "guidelinesRead", identity, "guidelines_get", input={"kind": "writing", **input})


def created(backend):
    return len([write for write in backend.writes if write[0] == "create"])


def save(backend, identity, document, *, reason="Change", kind="writing", section=None, request="r", guard=None, **extra):
    guard = guard or read(backend, kind=kind, **({"section": section} if section else {}))["result"]["expectedCurrentVersionId"]
    body = {"kind": kind, "document": document, "reason": reason, "expectedCurrentVersionId": guard, **({"section": section} if section else {})}
    return door(backend, "guidelinesWrite", identity, "guidelines_save", requestId=request, input=body, **extra)


# --- the table ---------------------------------------------------------------------------------------------------------------------------------

def test_the_table_has_the_five_guideline_operations_and_they_are_staff_operations_of_the_guidelines_group():
    assert NAMES == ["guidelines_get", "guidelines_resolve", "guidelines_diff", "guidelines_save", "guidelines_history"]
    assert [item.command for item in GUIDELINES] == [f"papyrus guidelines {word}" for word in ("show", "resolve", "diff", "save", "history")]
    assert [item.effect for item in GUIDELINES] == ["read", "read", "read", "write", "read"]
    assert all(item.audience == "staff" and item.agent_allowed and item.summary.endswith(".") for item in GUIDELINES)
    assert set(GUIDELINE_HANDLERS) == set(NAMES)


def test_the_kind_is_any_registered_kind_not_a_fixed_pair():
    for item in GUIDELINES:
        assert "enum" not in item.input["properties"]["kind"]
    envelope = execute("guidelines_get", {"kind": "poetry"}, Caller(), with_client(FakeBackend(publication="ours"), None))
    assert envelope["error"]["code"] == "unknown_kind" and {"image", "video", "writing"} <= set(envelope["error"]["details"]["kinds"])


def test_the_command_spec_the_mcp_tools_and_the_typescript_client_are_generated_from_the_same_entries():
    assert [entry["op"] for entry in COMMANDS] == NAMES
    assert all(entry["group"] == "guidelines" for entry in COMMANDS)
    assert [name for name in mcp.image_tools() if name.startswith("guidelines_")] == NAMES
    ts = generate.TS_TYPES.read_text(encoding="utf-8")
    assert re.findall(r"^  (guidelines_[a-z_]+): \{ input:", ts, re.M) == NAMES
    assert re.findall(r"^  (guidelines_[a-z_]+): \{ effect: [^\n]*group: \"guidelines\"", ts, re.M) == NAMES
    assert generate.stale() == []
    schemas = {tool["name"]: tool["inputSchema"] for tool in json.loads(generate.MCP_SCHEMA.read_text(encoding="utf-8"))["tools"]}
    for item in GUIDELINES:
        assert schemas[item.name] == item.input
        flags = {entry["field"] for entry in next(c for c in COMMANDS if c["op"] == item.name)["flags"]} | set(next(c for c in COMMANDS if c["op"] == item.name)["positional"])
        assert flags | ({item.file_field} if item.file_field else set()) <= set(item.input["properties"])


def test_the_hand_written_usage_names_every_flag_the_generated_spec_has():
    for entry in COMMANDS:
        usage = usage_for_path(["guidelines", *entry["words"]])
        assert usage is not None and usage.guide == "guidelines"
        for flag in re.findall(r"--[a-z-]+", entry["usage"]):
            assert flag in usage.usage, (entry["words"], flag)
    assert usage_for_path(["guidelines", "save"]).writes == "dry-run"


def argv_for(item, arguments, tmp_path):
    spec = next(entry for entry in COMMANDS if entry["op"] == item.name)
    argv, left = list(spec["words"]), dict(arguments)
    if spec["file"] in left:
        path = tmp_path / "document.json"
        path.write_text(json.dumps(left.pop(spec["file"])), encoding="utf-8")
        argv += ["--file", str(path)]
    for entry in spec["flags"]:
        if entry["field"] in left:
            argv += [entry["flag"], str(left.pop(entry["field"]))]
    assert not left, left
    return argv


@pytest.mark.parametrize("item", GUIDELINES, ids=NAMES)
def test_every_example_fits_its_schemas_and_the_cli_and_the_mcp_tool_give_identical_json(item, tmp_path):
    from papyrus_content.images.handlers import check

    example = item.examples[0]
    assert check(item.input, example.input) is None and check(item.result, example.result) is None
    handlers = {item.name: lambda arguments, caller: (arguments == example.input or pytest.fail(str(arguments))) and Outcome(example.result, "ours")}
    out = io.StringIO()
    status = guidelines_cli.command(argv_for(item, example.input, tmp_path), handlers=handlers, environ={}, stdout=out)
    from_mcp = mcp.call_image_tool(item.name, example.input, Caller(), handlers)
    assert status == 0 and json.loads(out.getvalue()) == from_mcp == {"ok": True, "op": item.name, "publication": "ours", "result": example.result, "warnings": []}


# --- the handlers -----------------------------------------------------------------------------------------------------------------------------

def test_an_admin_saves_writing_guidelines_and_the_text_goes_to_the_files_not_the_row():
    backend, _ = world(saved=False)
    first = door(backend, "guidelinesWrite", ADMIN, "guidelines_save", requestId="r1",
                 input={"kind": "writing", "document": WRITING, "reason": "First", "expectedCurrentVersionId": "none"})
    assert first["ok"] and first["result"]["versionNumber"] == 1 and first["publication"] == "ours"
    assert backend.items[0]["bodyMarkus"] == "" and backend.items[0]["versionCreatedBy"] == "Ada Admin" and len(backend.bodies) == 1
    shown = read(backend)["result"]
    assert shown["document"] == WRITING and shown["isCurrent"] is True and shown["expectedCurrentVersionId"] == first["result"]["itemId"]
    second = save(backend, ADMIN, {**WRITING, "audience": "Engineers"}, reason="Narrowed", request="r2")
    assert second["result"]["versionNumber"] == 2
    history = door(backend, "guidelinesRead", EDITOR, "guidelines_history", input={"kind": "writing"})["result"]["versions"]
    assert [(v["versionNumber"], v["by"], v["byKind"], v["reason"], v["isCurrent"]) for v in history] == [(2, "Ada Admin", "human", "Narrowed", True), (1, "Ada Admin", "human", "First", False)]
    assert read(backend, version=1)["result"]["document"]["audience"] == "General readers"


def test_nothing_stored_is_not_found_and_says_what_the_first_save_passes():
    backend, _ = world(saved=False)
    answer = read(backend)
    assert answer["error"]["code"] == "not_found" and answer["error"]["details"]["expectedCurrentVersionId"] == "none"
    assert door(backend, "guidelinesRead", EDITOR, "guidelines_history", input={"kind": "writing"})["result"]["versions"] == []


def test_an_editor_can_read_but_not_save_and_nothing_is_stored():
    backend, _ = world()
    before = created(backend)
    assert read(backend, EDITOR)["ok"]
    denied = save(backend, EDITOR, {**WRITING, "audience": "Engineers"}, request="e1")
    assert denied["error"]["code"] == "not_authorized" and created(backend) == before


def test_an_agent_cannot_change_a_binding_constraint_even_with_an_admins_session():
    backend, _ = world()
    before = created(backend)
    for change in ([], [{"id": "no-hype", "text": "Less hype."}], [{"id": "no-hype", "text": "No hype."}, {"id": "no-jargon", "text": "No jargon."}]):
        answer = save(backend, ADMIN, {**WRITING, "constraints": change}, request=f"a{len(change)}", actorKind="agent")
        assert answer["error"]["code"] == "human_required", change
    assert created(backend) == before
    allowed = save(backend, ADMIN, {**WRITING, "tone": ["Plain."]}, request="a-ok", actorKind="agent")   # an agent may change what is not a binding rule
    assert allowed["ok"] and allowed["result"]["versionNumber"] == 2
    assert door(backend, "guidelinesRead", EDITOR, "guidelines_history", input={"kind": "writing"})["result"]["versions"][0]["byKind"] == "agent"
    person = save(backend, ADMIN, {**WRITING, "tone": ["Plain."], "constraints": []}, request="p1")
    assert person["ok"] and person["result"]["versionNumber"] == 3


def test_a_write_repeated_with_the_same_request_id_gets_the_first_answer():
    backend, _ = world()
    guard = read(backend)["result"]["expectedCurrentVersionId"]
    document = {**WRITING, "audience": "Engineers"}
    first = save(backend, ADMIN, document, guard=guard, request="same")
    second = save(backend, ADMIN, document, guard=guard, request="same")
    assert first["result"]["versionNumber"] == 2 == second["result"]["versionNumber"] and second["result"]["repeated"] is True and created(backend) == 2
    assert save(backend, ADMIN, document, guard=guard, request="different")["error"]["code"] == "stale_version"
    assert save(backend, EDITOR, document, guard=guard, request="same")["error"]["code"] == "not_authorized"


def test_a_stale_version_an_invalid_document_and_an_unchanged_document_save_nothing():
    backend, _ = world()
    before = created(backend)
    assert save(backend, ADMIN, {**WRITING, "audience": "X"}, guard="item-editorial-doctrine-writing-v0", request="s1")["error"]["code"] == "stale_version"
    bad = save(backend, ADMIN, {"schemaVersion": 1, "tone": ["ok", ""], "mystery": 1}, request="s2")
    assert bad["error"]["code"] == "invalid_input" and {p["path"] for p in bad["error"]["details"]["problems"]} == {"tone", "mystery"}
    same = save(backend, ADMIN, WRITING, request="s3")
    assert same["ok"] and same["result"]["unchanged"] is True and same["result"]["versionNumber"] == 1
    assert created(backend) == before


def test_video_guidelines_work_through_the_same_operations_and_a_new_kind_needs_nothing_here():
    backend, _ = world(saved=False)
    first = save(backend, ADMIN, VIDEO, kind="video", guard="none", request="v1")
    assert first["ok"] and first["result"]["kind"] == "video"
    assert read(backend, kind="video")["result"]["document"] == VIDEO
    assert backend.items[0]["slug"] == "editorial-doctrine-video"
    register_kind(KindSpec("podcast", "podcast", 1, {"bodyMarkus": Field(lambda v: None if isinstance(v, str) else "must be text", PROSE), "tone": Field(texts, PROSE)}))
    try:
        answer = save(backend, ADMIN, {"schemaVersion": 1, "tone": ["Chatty."]}, kind="podcast", guard="none", request="p1")
        assert answer["ok"] and backend.items[-1]["slug"] == "editorial-doctrine-podcast"
        assert door(backend, "guidelinesRead", EDITOR, "guidelines_resolve", input={"kind": "podcast"})["result"]["document"] == {"tone": ["Chatty."]}
    finally:
        unregister_kind("podcast")
    assert read(backend, kind="podcast")["error"]["code"] == "unknown_kind"


def test_resolve_prints_each_field_with_where_it_came_from_and_a_missing_site_is_a_warning():
    backend, _ = world()
    save(backend, ADMIN, {"schemaVersion": 1, "tone": ["Dry."], "audience": "Specialists"}, section="security", guard="none", request="sec")
    answer = door(backend, "guidelinesRead", EDITOR, "guidelines_resolve", input={"kind": "writing", "section": "security"})
    result = answer["result"]
    assert result["found"] and result["section"] == "security" and result["document"]["tone"] == ["Warm and plain.", "Dry."]
    assert result["fieldSources"]["tone"] != result["fieldSources"]["constraints"] and len(result["layers"]) == 2 and answer["warnings"] == []
    empty, _ = world(saved=False)
    missing = door(empty, "guidelinesRead", EDITOR, "guidelines_resolve", input={"kind": "writing"})
    assert missing["ok"] and missing["result"]["found"] is False and missing["warnings"][0]["code"] == "writing_guidelines_missing"


def test_diff_shows_the_change_and_binding_rule_changes_and_stores_nothing():
    backend, _ = world()
    before, reads = created(backend), len(backend.writes)
    answer = door(backend, "guidelinesRead", EDITOR, "guidelines_diff",
                  input={"kind": "writing", "document": {**WRITING, "audience": "Engineers", "constraints": []}})["result"]
    assert {c["path"] for c in answer["changes"]} == {"audience", "constraints"} and answer["constraintChanges"][0]["change"] == "removed" and answer["wouldCreateVersion"] == 2
    unchanged = door(backend, "guidelinesRead", EDITOR, "guidelines_diff", input={"kind": "writing", "document": WRITING})["result"]
    assert unchanged["changes"] == [] and unchanged["wouldCreateVersion"] == 1
    assert door(backend, "guidelinesRead", EDITOR, "guidelines_diff", input={"kind": "writing", "document": {"schemaVersion": 1, "x": 1}})["error"]["code"] == "invalid_input"
    assert created(backend) == before and len(backend.writes) == reads


def test_the_image_kind_runs_the_image_profile_operations_and_resolves_elsewhere():
    backend = ImageBackend("ours", profile=profile_copy())
    handlers = with_client(backend, backend.document_files)
    got = execute("guidelines_get", {"kind": "image"}, Caller(), handlers)
    assert got["ok"] and got["result"]["kind"] == "image" and got["result"]["document"]["schemaVersion"] == 2
    assert execute("guidelines_history", {"kind": "image"}, Caller(), handlers)["result"]["versions"][0]["versionNumber"] == 1
    assert execute("guidelines_diff", {"kind": "image", "document": {"identity": {"mood": ["calm"]}}}, Caller(), handlers)["ok"]
    resolved = execute("guidelines_resolve", {"kind": "image"}, Caller(), handlers)
    assert resolved["ok"] and resolved["result"]["found"] and resolved["result"]["document"]["schemaVersion"] == 2
    assert execute("guidelines_get", {"kind": "image", "section": "news"}, Caller(), handlers)["error"]["code"] == "not_found"
    guard = got["result"]["itemId"]
    save_input = {"kind": "image", "document": {"identity": {"mood": ["calm", "dry"]}}, "reason": "Mood", "expectedCurrentVersionId": guard}
    assert execute("guidelines_save", save_input, Caller(subject="Edie"), handlers)["error"]["code"] == "not_authorized"
    saved = execute("guidelines_save", save_input, Caller(subject="Ada", is_admin=True), handlers)
    assert saved["ok"] and saved["result"]["versionNumber"] == 2


def test_the_other_family_s_operations_and_the_wrong_door_are_refused_in_plain_words():
    backend, _ = world()
    wrong = door(backend, "guidelinesRead", EDITOR, "guidelines_save", input={})
    assert wrong["error"]["code"] == "invalid_input" and "guidelinesWrite" in wrong["error"]["message"]
    wrong = door(backend, "guidelinesWrite", ADMIN, "guidelines_get", requestId="r", input={"kind": "writing"})
    assert wrong["error"]["code"] == "invalid_input" and "guidelinesRead" in wrong["error"]["message"]
    wrong = door(backend, "imageRead", EDITOR, "guidelines_get", input={"kind": "writing"})
    assert wrong["error"]["code"] == "invalid_input" and "guidelinesRead" in wrong["error"]["message"]
    wrong = door(backend, "guidelinesRead", EDITOR, "image_profile_get")
    assert wrong["error"]["code"] == "invalid_input" and "imageRead" in wrong["error"]["message"]
    assert door(backend, "guidelinesRead", READER, "guidelines_get", input={"kind": "writing"})["error"]["code"] == "not_authorized"
    assert door(backend, "guidelinesWrite", {}, "guidelines_save", requestId="r", input={})["error"]["code"] == "not_authorized"


def test_identity_comes_from_the_token_never_from_the_input():
    backend, _ = world()
    spoof = door(backend, "guidelinesWrite", EDITOR, "guidelines_save", requestId="x",
                 input={"kind": "writing", "document": WRITING, "reason": "x", "expectedCurrentVersionId": "none", "isAdmin": True})
    assert spoof["error"]["code"] == "invalid_input"   # the input has no such property


def test_an_unexpected_failure_is_a_state_and_the_cause_is_not_returned():
    def broken():
        raise RuntimeError("secret detail")

    answer = handle({"fieldName": "guidelinesRead", "identity": EDITOR, "arguments": {"op": "guidelines_get", "input": json.dumps({"kind": "writing"})}}, client_factory=broken)
    assert answer["error"]["code"] == "service_unavailable" and "secret" not in json.dumps(answer)


# --- the command line -------------------------------------------------------------------------------------------------------------------------

def run(backend, files, argv, *, admin=True, environ=None):
    handlers = with_client(backend, files, lambda caller: replace(caller, subject="Ada Admin" if admin else "Edie Editor", is_admin=admin))
    out = io.StringIO()
    status = guidelines_cli.command(argv, handlers=handlers, environ=environ or {}, stdout=out)
    return status, json.loads(out.getvalue())


def test_save_writes_unless_dry_run_and_a_dry_run_shows_the_diff_and_stores_nothing(tmp_path):
    backend, files = world()
    path = tmp_path / "writing.json"
    path.write_text(json.dumps({**WRITING, "audience": "Engineers"}), encoding="utf-8")
    guard = read(backend)["result"]["expectedCurrentVersionId"]
    flags = ["--kind", "writing", "--file", str(path), "--reason", "Narrowed", "--expected-current-version-id", guard]
    before = created(backend)
    status, dry = run(backend, files, ["save", *flags, "--dry-run"])
    assert status == 0 and dry["result"]["dryRun"] is True and dry["result"]["preview"]["changes"] == [{"path": "audience", "from": "General readers", "to": "Engineers"}]
    assert created(backend) == before
    status, written = run(backend, files, ["save", *flags])
    assert status == 0 and written["result"]["versionNumber"] == 2 and created(backend) == before + 1
    status, shown = run(backend, files, ["show", "--kind", "writing"])
    assert shown["result"]["document"]["audience"] == "Engineers"


def test_the_command_line_refuses_an_editor_and_an_agent_changing_a_rule(tmp_path):
    backend, files = world()
    path = tmp_path / "writing.json"
    path.write_text(json.dumps({**WRITING, "constraints": []}), encoding="utf-8")
    guard = read(backend)["result"]["expectedCurrentVersionId"]
    flags = ["save", "--kind", "writing", "--file", str(path), "--reason", "Drop", "--expected-current-version-id", guard]
    assert run(backend, files, flags, admin=False)[1]["error"]["code"] == "not_authorized"
    status, answer = run(backend, files, flags, environ={"PAPYRUS_ACTOR_KIND": "agent"})
    assert status == 2 and answer["error"]["code"] == "human_required" and created(backend) == 1
    assert run(backend, files, flags)[1]["ok"]


def test_diff_resolve_and_history_on_the_command_line_send_no_writes(tmp_path):
    backend, files = world()
    path = tmp_path / "writing.json"
    path.write_text(json.dumps({**WRITING, "tone": ["Brisk."]}), encoding="utf-8")
    writes = len(backend.writes)
    assert run(backend, files, ["diff", "--kind", "writing", "--file", str(path)])[1]["result"]["changes"][0]["path"] == "tone"
    assert run(backend, files, ["resolve", "--kind", "writing"])[1]["result"]["fieldSources"]
    assert run(backend, files, ["history", "--kind", "writing"])[1]["result"]["versions"][0]["versionNumber"] == 1
    assert len(backend.writes) == writes


def test_bad_flags_and_missing_flags_are_plain_errors():
    backend, files = world()
    assert run(backend, files, ["show"])[1]["error"]["code"] == "invalid_input"
    status, answer = run(backend, files, ["show", "--kind", "writing", "--bogus", "1"])
    assert status == 2 and "papyrus guidelines show" in answer["error"]["message"]
    assert run(backend, files, ["nonsense"])[1]["error"]["code"] == "unknown_operation"


def test_image_commands_are_not_reachable_through_the_guidelines_group():
    backend, files = world()
    assert run(backend, files, ["profile", "get"])[1]["error"]["code"] == "unknown_operation"


# --- the S3 files of the door -----------------------------------------------------------------------------------------------------------------

class FakeS3:
    def __init__(self):
        self.objects, self.calls = {}, []

    def put_object(self, **kwargs):
        self.calls.append(("put", kwargs["Key"]))
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs):
        self.calls.append(("get", kwargs["Key"]))
        if kwargs["Key"] not in self.objects:
            raise type("NoSuchKey", (Exception,), {})()
        body = self.objects[kwargs["Key"]]
        return {"Body": type("Body", (), {"read": lambda self: body})()}


def test_the_door_s_files_write_the_object_then_the_attachment_row_and_stay_under_the_item_prefix():
    backend = FakeBackend(publication="ours")
    created_models = []
    backend.create_record = lambda model, record: created_models.append((model, record["storagePath"]))
    s3 = FakeS3()
    files = S3DocumentFiles(backend, bucket="b", s3=s3)
    attachment = {"id": "a", "storagePath": PAYLOAD_PREFIX + "item-x/doctrine-document/guidelines.json", "mediaType": "application/json"}
    assert files.put(attachment, b"{}") == attachment
    assert s3.calls == [("put", attachment["storagePath"])] and created_models == [("ModelAttachment", attachment["storagePath"])]
    assert files.get(attachment) == b"{}" and files.get({**attachment, "storagePath": PAYLOAD_PREFIX + "missing.json"}) is None
    for outside in ("newsroom/payloads/reference/x.json", PAYLOAD_PREFIX + "../story/x.json", ""):
        with pytest.raises(ValueError):
            files.put({**attachment, "storagePath": outside}, b"{}")
        with pytest.raises(ValueError):
            files.get({**attachment, "storagePath": outside})


def test_the_bucket_comes_from_the_functions_environment():
    assert S3DocumentFiles(None, env={"papyrusMedia_BUCKET_NAME": "site-bucket"}).bucket == "site-bucket"
    with pytest.raises(RuntimeError):
        S3DocumentFiles(None, env={}).bucket
