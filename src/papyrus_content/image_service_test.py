"""The image-service door: who may call it, which door runs which operation, and that a write repeated with the same id is answered once."""
from __future__ import annotations

import json

from papyrus_content.image_service import caller_from_identity, handle
from papyrus_content.images.profile_fakes import FakeBackend, profile_copy

EDITOR = {"claims": {"name": "Edie Editor", "cognito:groups": ["editor"]}, "groups": ["editor"], "username": "edie"}
ADMIN = {"claims": {"name": "Ada Admin"}, "groups": ["admin"], "username": "ada"}
READER = {"claims": {"name": "Rae Reader"}, "groups": [], "username": "rae"}


def call(backend, door, identity, **arguments):
    if "input" in arguments and not isinstance(arguments["input"], str):
        arguments["input"] = json.dumps(arguments["input"])
    return handle({"info": {"fieldName": door}, "identity": identity, "arguments": arguments}, client_factory=lambda: backend)


def test_only_staff_may_use_the_door():
    backend = FakeBackend("ours", profile=profile_copy())
    assert call(backend, "imageRead", READER, op="image_profile_get")["error"]["code"] == "not_authorized"
    assert call(backend, "imageRead", {}, op="image_profile_get")["error"]["code"] == "not_authorized"
    assert call(backend, "imageRead", EDITOR, op="image_profile_get")["ok"] is True


def test_the_wrong_door_and_bad_input_are_refused_in_plain_words():
    backend = FakeBackend("ours", profile=profile_copy())
    wrong = call(backend, "imageRead", EDITOR, op="image_profile_save", input={})
    assert wrong["error"]["code"] == "invalid_input" and "imageWrite" in wrong["error"]["message"]
    wrong = call(backend, "imageWrite", EDITOR, op="image_profile_get", requestId="r1")
    assert wrong["error"]["code"] == "invalid_input" and "imageRead" in wrong["error"]["message"]
    assert call(backend, "imageRead", EDITOR, op="image_nothing")["error"]["code"] == "unknown_operation"
    assert call(backend, "imageRead", EDITOR, op="image_profile_get", input="{not json")["error"]["code"] == "invalid_input"
    assert call(backend, "imageSomething", EDITOR, op="image_profile_get")["error"]["code"] == "invalid_input"


def test_identity_comes_from_the_token_not_the_input_and_admin_comes_from_the_group():
    assert caller_from_identity(EDITOR).subject == "Edie Editor" and caller_from_identity(EDITOR).is_admin is False
    assert caller_from_identity(ADMIN).is_admin is True
    assert caller_from_identity(ADMIN, actor_kind="agent").kind == "agent" and caller_from_identity(ADMIN).kind == "person"
    backend = FakeBackend("ours", profile=profile_copy())
    guard = call(backend, "imageRead", EDITOR, op="image_profile_get")["result"]["itemId"]
    spoof = call(backend, "imageWrite", EDITOR, op="image_profile_save", requestId="r1",
                 input={"document": {"constraints": []}, "reason": "Drop", "expectedCurrentVersionId": guard, "isAdmin": True})
    assert spoof["error"]["code"] == "invalid_input"   # the input has no such property
    denied = call(backend, "imageWrite", EDITOR, op="image_profile_save", requestId="r2",
                  input={"document": {"constraints": []}, "reason": "Drop", "expectedCurrentVersionId": guard})
    assert denied["error"]["code"] == "not_authorized"
    allowed = call(backend, "imageWrite", ADMIN, op="image_profile_save", requestId="r3",
                   input={"document": {"constraints": []}, "reason": "Drop", "expectedCurrentVersionId": guard})
    assert allowed["ok"] and allowed["result"]["versionNumber"] == 2


def test_a_caller_who_declares_itself_an_agent_cannot_change_a_constraint_even_as_an_admin():
    backend = FakeBackend("ours", profile=profile_copy())
    guard = call(backend, "imageRead", ADMIN, op="image_profile_get")["result"]["itemId"]
    answer = call(backend, "imageWrite", ADMIN, op="image_profile_save", requestId="r1", actorKind="agent",
                  input={"document": {"constraints": []}, "reason": "Drop", "expectedCurrentVersionId": guard})
    assert answer["error"]["code"] == "human_required"


def test_a_write_repeated_with_the_same_request_id_gets_the_first_answer():
    backend = FakeBackend("ours", profile=profile_copy())
    guard = call(backend, "imageRead", EDITOR, op="image_profile_get")["result"]["itemId"]
    body = {"document": {"identity": {"mood": ["calm", "dry"]}}, "reason": "Mood", "expectedCurrentVersionId": guard}
    first = call(backend, "imageWrite", EDITOR, op="image_profile_save", requestId="same", input=body)
    second = call(backend, "imageWrite", EDITOR, op="image_profile_save", requestId="same", input=body)
    assert first["result"]["versionNumber"] == 2 and second["result"]["versionNumber"] == 2 and second["result"]["repeated"] is True
    assert len([w for w in backend.writes if w[0] == "create"]) == 2   # the first profile and one new version
    other = call(backend, "imageWrite", EDITOR, op="image_profile_save", requestId="different", input=body)
    assert other["error"]["code"] == "stale_version"


def test_the_section_style_is_read_from_the_site_with_its_own_field():
    backend = FakeBackend("ours", profile=profile_copy())
    backend.add_story("story-1", section="security")
    backend.add_section("security", visualStyle=json.dumps({"avoid": ["padlocks"]}))
    asked = []
    original = backend.get_record_with_fields

    def get_record_with_fields(model, record_id, extra):
        asked.append((model, extra))
        return original(model, record_id, extra)

    backend.get_record_with_fields = get_record_with_fields
    answer = call(backend, "imageRead", EDITOR, op="image_profile_resolve", input={"target": {"kind": "story", "lineageId": "story-1"}, "use": "cover", "imageType": "cover-illustration"})
    assert asked == [("NewsroomSection", "visualStyle")] and "padlocks" in answer["result"]["effective"]["avoid"]


def test_an_unexpected_failure_is_a_state_and_the_cause_is_not_returned():
    def broken():
        raise RuntimeError("secret detail")

    answer = handle({"info": {"fieldName": "imageRead"}, "identity": EDITOR, "arguments": {"op": "image_profile_get"}}, client_factory=broken)
    assert answer["error"]["code"] == "service_unavailable" and "secret" not in json.dumps(answer)


def test_the_function_imports_with_only_the_standard_library():
    """The function is bundled without third-party packages (like the other core functions), so nothing it imports may need one."""
    import subprocess
    import sys
    from pathlib import Path

    source = str(Path(__file__).resolve().parents[1])
    result = subprocess.run([sys.executable, "-S", "-c", f"import sys; sys.path.insert(0, {source!r}); import papyrus_content.image_service"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr[-400:]
