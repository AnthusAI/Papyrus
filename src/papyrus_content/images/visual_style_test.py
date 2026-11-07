"""The style profile: what a saved document may contain, how layers resolve, and the prompt skeleton. No network; the backend is a fake."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from papyrus_content.images import prompt_lint
from papyrus_content.images.handlers import Caller, execute
from papyrus_content.images.profile_fakes import FakeBackend, profile_copy
from papyrus_content.images.profile_handlers import with_client
from papyrus_content.images.prompt_skeleton import SLOT_ORDER, compose_plan
from papyrus_content.images.visual_style import (PROFILE_MISSING, StyleError, constraint_changes, diff_documents, keys_permanent, merge_document, resolve_visual_style,
                                                 stamp_constraints, validate_profile)

ADMIN = Caller(kind="person", subject="Ada Admin", is_admin=True)
EDITOR = Caller(kind="person", subject="Edie Editor")
AGENT = Caller(kind="agent", subject="Edie Editor", delegated_by="Edie Editor")
STORY = {"kind": "story", "lineageId": "story-1"}


def problems(document):
    return [(p.path, p.code) for p in validate_profile(document)]


def test_the_sample_profile_is_valid():
    assert validate_profile(profile_copy()) == []


def test_cycles_and_unknown_parents_are_refused():
    profile = profile_copy()
    profile["imageTypes"]["cover-illustration"]["extends"] = "inline-illustration"
    assert ("imageTypes.cover-illustration.extends", "invalid_input") in problems(profile)
    profile = profile_copy()
    profile["imageTypes"]["social-card"]["extends"] = "no-such-type"
    assert any("not an image type in this profile" in p.message for p in validate_profile(profile))


def test_constraints_belong_to_the_publication_only():
    profile = profile_copy()
    profile["imageTypes"]["cover-illustration"]["constraints"] = [{"id": "mine", "text": "x"}]
    assert any(p.path == "imageTypes.cover-illustration.constraints" and "publication" in p.message for p in validate_profile(profile))


def test_remove_from_parent_cannot_touch_constraints_or_never_items():
    profile = profile_copy()
    profile["imageTypes"]["inline-illustration"]["removeFromParent"]["avoid"] = ["real people"]
    assert ("imageTypes.inline-illustration.removeFromParent.avoid", "constraint_conflict") in problems(profile)
    profile = profile_copy()
    profile["imageTypes"]["inline-illustration"]["removeFromParent"]["constraints"] = ["no-photoreal-generated"]
    assert ("imageTypes.inline-illustration.removeFromParent.constraints", "constraint_conflict") in problems(profile)
    profile = profile_copy()
    profile["imageTypes"]["inline-illustration"]["removeFromParent"]["avoid"] = ["photograph"]   # a constraint's own avoid item
    assert any(code == "constraint_conflict" for _, code in problems(profile))
    profile = profile_copy()
    profile["imageTypes"]["inline-illustration"]["removeFromParent"]["avoid"] = ["a thing the parent never listed"]
    assert any("not something" in p.message for p in validate_profile(profile))


def test_a_photograph_type_that_allows_generation_breaks_the_publications_rule():
    profile = profile_copy()
    profile["imageTypes"]["cover-photo"]["sources"] = ["stock", "generated"]
    assert ("imageTypes.cover-photo", "constraint_conflict") in problems(profile)


def test_type_keys_are_permanent():
    old = profile_copy()
    new = copy.deepcopy(old)
    new["imageTypes"]["headline"] = new["imageTypes"].pop("cover-illustration")
    assert [p.path for p in keys_permanent(old, new)] == ["imageTypes.cover-illustration"]


def test_merge_diff_and_constraint_changes():
    old = profile_copy()
    merged = merge_document(old, {"identity": {"mood": ["calm", "precise"]}, "imageTypes": {"cover-illustration": {"retired": True}}})
    assert merged["identity"]["summary"] == old["identity"]["summary"] and merged["imageTypes"]["cover-illustration"]["retired"] is True
    assert diff_documents(old, merged) == [{"path": "identity.mood", "from": ["calm"], "to": ["calm", "precise"]},
                                          {"path": "imageTypes.cover-illustration.retired", "from": None, "to": True}]
    assert merge_document(old, {"imageReview": None}).get("imageReview") is None
    assert constraint_changes(old["constraints"], []) == [{"id": "no-photoreal-generated", "change": "removed", "from": old["constraints"][0]}]
    assert constraint_changes(old["constraints"], old["constraints"]) == []


def test_stamping_keeps_unchanged_rules_and_versions_changed_ones():
    old = profile_copy()["constraints"]
    assert stamp_constraints(old, old, by="x", at="t", reason="r") == old
    changed = [{**old[0], "text": "Stricter."}]
    stamped = stamp_constraints(old, changed, by="Ada", at="2026-11-08", reason="Tightened.")[0]
    assert (stamped["version"], stamped["adoptedBy"], stamped["reason"]) == (2, "Ada", "Tightened.")


def resolve(profile=None, **kwargs):
    return resolve_visual_style(profile or profile_copy(), profile_ref={"itemId": "p-v1", "versionNumber": 1, "contentHash": "sha256:x"}, **kwargs)


def test_precedence_runs_identity_treatment_use_type_parents_first_section_story():
    result = resolve(use="inline", image_type="inline-illustration",
                     section={"id": "sec#security", "visualGuidance": "Keep security calm.", "visualStyle": {"avoid": ["padlocks"]}},
                     story_style={"avoid": ["keys"], "notes": "This Story is about a quiet failure.", "source": {"itemId": "story-1-v7"}})
    assert [(layer["layer"], layer.get("key")) for layer in result["layers"]] == [
        ("publication", None), ("treatment", "editorial-illustration"), ("use", "inline"), ("image-type", "cover-illustration"), ("image-type", "inline-illustration"),
        ("section", None), ("story", None)]
    sources = result["fieldSources"]
    assert sources["guidance[0]"] == "treatment:editorial-illustration"
    assert sources["guidance[1]"] == "image-type:cover-illustration" and sources["guidance[2]"] == "image-type:inline-illustration"
    assert sources["guidance[3]"] == "section:security" and sources["guidance[4]"] == "story:story-1-v7"
    assert sources["sizes"] == "image-type:cover-illustration" and sources["sources"] == "image-type:inline-illustration"
    assert "padlocks" in result["effective"]["avoid"] and "keys" in result["effective"]["avoid"]


def test_remove_from_parent_is_recorded_and_publication_items_stay():
    result = resolve(use="inline", image_type="inline-illustration")
    avoid = result["effective"]["avoid"]
    assert "small details" not in avoid and "real people" in avoid and "3D render" in avoid
    assert result["fieldSources"]["removed"] == ["avoid:'small details' by image-type:inline-illustration", "avoid:'more than one subject' by image-type:inline-illustration",
                                                  "safeZones by image-type:inline-illustration"]
    assert result["effective"]["safeZones"] == []
    assert "small details" in resolve(use="cover", image_type="cover-illustration")["effective"]["avoid"]


def test_a_section_or_story_cannot_remove_a_constraint_or_a_never_item():
    attempt = {"constraints": [], "removeFromParent": {"avoid": ["real people"]}, "never": [], "avoid": ["padlocks"]}
    result = resolve(use="cover", image_type="cover-illustration", section={"id": "s", "visualStyle": attempt}, story_style=attempt)
    assert [c["id"] for c in result["constraints"]] == ["no-photoreal-generated"] and "real people" in result["effective"]["avoid"]
    assert {w["code"] for w in result["warnings"]} == {"override_field_ignored"} and len(result["warnings"]) == 6


def test_a_section_may_narrow_sources_but_never_add_one():
    narrowed = resolve(use="cover", image_type="cover-illustration", section={"id": "s", "visualStyle": {"sources": ["stock"]}})
    assert narrowed["effective"]["sources"] == ["stock"] and narrowed["fieldSources"]["sources"] == "section:s"
    widened = resolve(use="cover", image_type="cover-photo", section={"id": "s", "visualStyle": {"sources": ["stock", "generated"]}})
    assert widened["effective"]["sources"] == ["stock"] and widened["warnings"][0]["code"] == "choice_not_added"
    aimed = resolve(use="cover", image_type="cover-illustration", section={"id": "s", "visualStyle": {"imageTypes": {"cover-illustration": {"sources": ["generated"]}}}})
    assert aimed["effective"]["sources"] == ["generated"] and aimed["fieldSources"]["sources"] == "section:s/cover-illustration"


def test_an_override_that_asks_for_a_forbidden_treatment_is_a_constraint_conflict():
    with pytest.raises(StyleError) as caught:
        resolve(use="cover", image_type="cover-illustration", operation="generate", section={"id": "s", "visualStyle": {"treatment": "photo"}})
    assert caught.value.code == "constraint_conflict" and caught.value.details["constraint"]["id"] == "no-photoreal-generated"
    stock = resolve(use="cover", image_type="cover-illustration", operation="search", section={"id": "s", "visualStyle": {"treatment": "photo"}})
    assert stock["effective"]["treatment"] == "photo"   # the rule is about generated pictures; a search is not one


def test_a_locked_field_keeps_the_broadest_value():
    profile = profile_copy()
    profile["locked"] = ["sizes"]
    profile["uses"]["cover"]["sizes"] = {"aspectRatio": "3:2", "width": 1500, "height": 1000}
    profile["imageTypes"]["cover-illustration"]["sizes"] = {"aspectRatio": "16:9", "width": 1920, "height": 1088}
    assert any(p.path == "imageTypes.cover-illustration.sizes" for p in validate_profile(profile))


def test_the_default_type_for_a_cover_depends_on_what_the_operation_needs():
    assert resolve(use="cover")["imageType"] == "cover-diagram"
    chosen = resolve(use="cover", operation="generate")
    assert (chosen["imageType"], chosen["imageTypeChosenBy"]) == ("cover-illustration", "default-for-use")
    assert chosen["warnings"][0]["code"] == "image_type_defaulted"
    assert resolve(use="cover", operation="search")["imageType"] == "cover-photo"
    assert resolve(use="cover", image_type="cover-photo")["imageTypeChosenBy"] == "request"


def test_an_inline_picture_must_name_a_type_and_the_error_lists_choices():
    with pytest.raises(StyleError) as caught:
        resolve(use="inline")
    assert caught.value.code == "image_type_required"
    assert [c["key"] for c in caught.value.details["choices"]] == ["inline-diagram", "inline-illustration"]


def test_unknown_retired_and_wrong_use_types_are_refused():
    for name, use in (("no-such-type", "cover"), ("inline-illustration", "cover")):
        with pytest.raises(StyleError) as caught:
            resolve(use=use, image_type=name)
        assert caught.value.code == "image_type_unknown" and caught.value.details["choices"]
    profile = profile_copy()
    profile["imageTypes"]["cover-photo"]["retired"] = True
    with pytest.raises(StyleError):
        resolve(profile, use="cover", image_type="cover-photo")
    assert resolve(profile, use="cover", image_type="cover-photo", allow_retired=True)["imageType"] == "cover-photo"
    assert "cover-photo" not in [c["key"] for c in resolve(profile, use="cover")["availableTypes"]]


def test_a_figure_system_type_cannot_be_generated_or_searched():
    for operation in ("generate", "search"):
        with pytest.raises(StyleError) as caught:
            resolve(use="cover", image_type="cover-diagram", operation=operation)
        assert caught.value.code == "source_not_allowed" and caught.value.details["allowed"] == ["figure-system"]
        assert caught.value.details["rules"]["figureSystem"]["rules"] == "design/figures/rules.md"
    assert resolve(use="cover", image_type="cover-diagram", operation="figure")["effective"]["sources"] == ["figure-system"]


def test_no_profile_is_a_warning_with_the_designs_words_never_an_error():
    result = resolve_visual_style(None, use="cover")
    assert result["profile"] is None and result["layers"] == [] and result["constraints"] == []
    assert result["warnings"] == [{"code": "profile_missing", "message": PROFILE_MISSING}]
    assert "undefined and unpredictable" in PROFILE_MISSING and "example images" in PROFILE_MISSING
    assert resolve_visual_style({}, use="inline", image_type="anything")["warnings"][0]["code"] == "profile_missing"


def test_the_prompt_skeleton_with_a_profile_orders_every_slot_and_cites_its_layer():
    resolved = resolve(use="cover", image_type="cover-illustration", operation="generate",
                       section={"id": "sec#security", "visualGuidance": "Keep security calm."})
    plan = compose_plan(resolved, "A locked filing cabinet")
    assert [segment["slot"] for segment in plan["segments"]] == ["style", "treatment", "image type", "constraints", "subject", "composition", "colours", "section"]
    assert plan["segments"][3] == {"slot": "constraints", "source": "constraint:no-photoreal-generated", "text": "Unmistakably an illustration."}
    assert "Composition: 16 by 9 (1920x1088). Keep the upper third quiet." in plan["text"]
    assert "Colours: Ink blue (#1f2a44), Cool paper (#f6f7f9)" in plan["text"]
    assert plan["text"].splitlines()[-1].startswith("Avoid: ") and "photograph" in plan["avoid"]
    assert "Avoid:" not in compose_plan(resolved, "x", native_negative=True)["text"] and set(SLOT_ORDER) >= {s["slot"] for s in plan["segments"]}


def test_with_no_profile_the_plan_is_the_skeleton_and_the_brief_only():
    plan = compose_plan(resolve_visual_style(None, use="cover"), "A locked filing cabinet")
    assert plan["text"] == "Subject: A locked filing cabinet" and [s["slot"] for s in plan["segments"]] == ["subject"] and plan["avoid"] == []


def test_the_lint_passes_the_skeleton_and_fails_style_wording_in_code():
    source = Path(prompt_lint.__file__).with_name("prompt_skeleton.py").read_text(encoding="utf-8")
    assert prompt_lint.style_wording_in(source) == []
    sneaky = source.replace('"Subject: "', '"Subject: a flat, calm, photorealistic "', 1) if '"Subject: "' in source else source + '\nSTYLE = "flat calm shapes"\n'
    assert prompt_lint.style_wording_in(sneaky) or prompt_lint.style_wording_in(source + '\nSTYLE = "flat calm shapes"\n')
    assert prompt_lint.style_wording_in('NEGATIVE = ["blurry", "watermark"]') == ["blurry", "watermark"]


# --- the operations on a fake backend ---------------------------------------------------------------------------------------------------------------

def run(backend, name, arguments, caller=EDITOR):
    return execute(name, arguments, caller, with_client(backend))


def test_get_with_no_profile_is_not_found_and_says_how_to_save_the_first():
    envelope = run(FakeBackend(), "image_profile_get", {})
    assert envelope["error"]["code"] == "not_found" and envelope["error"]["details"]["expectedCurrentVersionId"] == "none"


def test_the_first_save_then_an_edit_make_versions_and_old_ones_stay():
    backend = FakeBackend()
    first = run(backend, "image_profile_save", {"document": {"schemaVersion": 2, "identity": {"summary": "Calm."}}, "reason": "First.", "expectedCurrentVersionId": "none"})
    assert first["ok"] and first["result"]["versionNumber"] == 1
    second = run(backend, "image_profile_save", {"document": {"identity": {"summary": "Calmer."}}, "reason": "Tuned.", "expectedCurrentVersionId": first["result"]["itemId"]})
    assert second["result"]["versionNumber"] == 2
    old = run(backend, "image_profile_get", {"version": 1})["result"]
    now = run(backend, "image_profile_get", {})["result"]
    assert old["profile"]["identity"]["summary"] == "Calm." and now["profile"]["identity"]["summary"] == "Calmer."
    assert (old["isCurrent"], now["isCurrent"]) == (False, True)
    history = run(backend, "image_profile_history", {})["result"]["versions"]
    assert [(v["versionNumber"], v["reason"], v["by"]) for v in history] == [(2, "Tuned.", "Edie Editor"), (1, "First.", "Edie Editor")]


def test_a_stale_save_is_refused_and_an_unchanged_save_makes_no_version():
    backend = FakeBackend(profile=profile_copy())
    stale = run(backend, "image_profile_save", {"document": {"identity": {"mood": ["calm", "dry"]}}, "reason": "x", "expectedCurrentVersionId": "old"})
    assert stale["error"]["code"] == "stale_version"
    current = run(backend, "image_profile_get", {})["result"]["itemId"]
    same = run(backend, "image_profile_save", {"document": {"identity": {"mood": ["calm"]}}, "reason": "no-op", "expectedCurrentVersionId": current})
    assert same["result"]["unchanged"] is True and same["result"]["versionNumber"] == 1
    assert len([w for w in backend.writes if w[0] == "create"]) == 1


def test_constraint_edits_need_a_person_who_is_an_admin():
    backend = FakeBackend(profile=profile_copy())
    guard = run(backend, "image_profile_get", {})["result"]["itemId"]
    edit = {"document": {"constraints": []}, "reason": "Drop the rule.", "expectedCurrentVersionId": guard}
    agent = run(backend, "image_profile_save", edit, AGENT)
    editor = run(backend, "image_profile_save", edit, EDITOR)
    assert agent["error"]["code"] == "human_required" and editor["error"]["code"] == "not_authorized"
    assert len([w for w in backend.writes if w[0] == "create"]) == 1
    admin = run(backend, "image_profile_save", edit, ADMIN)
    assert admin["ok"] and run(backend, "image_profile_get", {})["result"]["profile"]["constraints"] == []
    assert run(backend, "image_profile_get", {"version": 1})["result"]["profile"]["constraints"][0]["id"] == "no-photoreal-generated"


def test_an_admin_adding_a_rule_gets_it_stamped_and_an_agent_may_edit_everything_else():
    backend = FakeBackend(profile=profile_copy())
    guard = run(backend, "image_profile_get", {})["result"]["itemId"]
    rule = {"id": "no-logos", "text": "No logos.", "promptAvoid": ["logo"]}
    added = run(backend, "image_profile_save", {"document": {"constraints": [*profile_copy()["constraints"], rule]}, "reason": "New rule.", "expectedCurrentVersionId": guard}, ADMIN)
    stored = run(backend, "image_profile_get", {})["result"]
    new_rule = stored["profile"]["constraints"][1]
    assert (new_rule["version"], new_rule["adoptedBy"], new_rule["reason"]) == (1, "Ada Admin", "New rule.") and added["result"]["versionNumber"] == 2
    tweak = run(backend, "image_profile_save", {"document": {"identity": {"mood": ["calm", "dry"]}}, "reason": "Mood.", "expectedCurrentVersionId": stored["itemId"]}, AGENT)
    assert tweak["ok"] and run(backend, "image_profile_history", {})["result"]["versions"][0]["byKind"] == "agent"


def test_diff_shows_changes_and_constraint_changes_without_saving():
    backend = FakeBackend(profile=profile_copy())
    envelope = run(backend, "image_profile_diff", {"document": {"identity": {"mood": ["dry"]}, "constraints": []}})
    assert envelope["result"]["changes"][0] == {"path": "identity.mood", "from": ["calm"], "to": ["dry"]}
    assert [c["change"] for c in envelope["result"]["constraintChanges"]] == ["removed"] and envelope["result"]["wouldCreateVersion"] == 2
    assert len(backend.items) == 1
    bad = run(backend, "image_profile_diff", {"document": {"imageTypes": {"cover-illustration": {"extends": "social-card"}}}})
    assert bad["error"]["code"] == "invalid_input" and "circle" in bad["error"]["message"]


def test_resolve_reads_the_story_and_its_section_and_two_publications_never_leak():
    ours = FakeBackend("ours", profile=profile_copy())
    ours.add_section("security", visualGuidance="Security calm.")
    ours.add_story("story-1", section="security", image_style={"avoid": ["keys"]})
    other_profile = profile_copy()
    other_profile["identity"]["masterPrompt"] = "Loud neon posters."
    theirs = FakeBackend("theirs", profile=other_profile)
    theirs.add_story("story-1", section=None)
    mine = run(ours, "image_profile_resolve", {"target": STORY, "use": "inline", "imageType": "inline-illustration"})
    other = run(theirs, "image_profile_resolve", {"target": STORY, "use": "inline", "imageType": "inline-illustration"})
    assert mine["publication"] == "ours" and other["publication"] == "theirs"
    assert mine["result"]["effective"]["masterPrompt"] != other["result"]["effective"]["masterPrompt"]
    assert "Loud neon" not in compose_plan(mine["result"], "x")["text"] and "Security calm." in compose_plan(mine["result"], "x")["text"]
    assert "Security calm." not in compose_plan(other["result"], "x")["text"]
    assert run(ours, "image_profile_resolve", {"target": {"kind": "story", "lineageId": "elsewhere"}, "use": "cover"})["error"]["code"] == "not_found"


def test_resolve_with_no_profile_gives_the_warning_and_a_skeleton_only_plan():
    backend = FakeBackend()
    backend.add_story("story-1")
    envelope = run(backend, "image_profile_resolve", {"target": STORY, "use": "cover"})
    assert envelope["ok"] and envelope["result"]["profile"] is None
    assert envelope["warnings"][0]["code"] == "profile_missing" and envelope["result"]["warnings"] == envelope["warnings"]
    assert compose_plan(envelope["result"], "A cabinet")["text"] == "Subject: A cabinet"


def test_resolve_errors_come_through_the_envelope():
    backend = FakeBackend(profile=profile_copy())
    backend.add_story("story-1")
    required = run(backend, "image_profile_resolve", {"target": STORY, "use": "inline"})
    assert required["error"]["code"] == "image_type_required" and len(required["error"]["details"]["choices"]) == 2
    unknown = run(backend, "image_profile_resolve", {"target": STORY, "use": "cover", "imageType": "nope"})
    assert unknown["error"]["code"] == "image_type_unknown"
    defaulted = run(backend, "image_profile_resolve", {"target": STORY, "use": "cover"})
    assert defaulted["result"]["imageType"] == "cover-diagram" and defaulted["result"]["imageTypeChosenBy"] == "default-for-use"
    assert defaulted["warnings"][0]["code"] == "image_type_defaulted"


def test_the_tenant_of_every_record_is_checked():
    backend = FakeBackend(tenant_id="a", profile=profile_copy())
    backend.tenant_id = "b"
    with pytest.raises(ValueError, match="tenant"):
        run(backend, "image_profile_get", {})


# --- the command line over the same handlers ------------------------------------------------------------------------------------------------------------

def command(backend, argv, environ=None, document=None, tmp_path=None):
    import io
    import json

    from papyrus_content.images import cli

    out = io.StringIO()
    status = cli.command(argv, handlers=with_client(backend, lambda caller: Caller(kind=caller.kind, subject="Edie Editor")), environ=environ or {}, stdout=out)
    return status, json.loads(out.getvalue())


def test_the_profile_commands_save_diff_and_resolve_through_the_same_handlers(tmp_path):
    import json

    backend = FakeBackend("ours")
    backend.add_story("story-1")
    document = tmp_path / "style.json"
    document.write_text(json.dumps({"schemaVersion": 2, "identity": {"masterPrompt": "Flat."}}), encoding="utf-8")
    status, saved = command(backend, ["profile", "save", "--file", str(document), "--reason", "First", "--expected-current-version-id", "none"])
    assert status == 0 and saved["result"]["versionNumber"] == 1
    status, diff = command(backend, ["profile", "diff", "--file", str(document)])
    assert status == 0 and diff["result"]["changes"] == []
    status, resolved = command(backend, ["profile", "resolve", "--story", "story-1", "--use", "cover"])
    assert status == 2 and resolved["error"]["code"] == "image_type_required"   # a profile with no types has no default
    status, history = command(backend, ["profile", "history"], {"PAPYRUS_ACTOR_KIND": "agent"})
    assert status == 0 and history["result"]["versions"][0]["by"] == "Edie Editor"


def test_an_agent_on_the_command_line_cannot_edit_constraints(tmp_path):
    import json

    backend = FakeBackend("ours", profile=profile_copy())
    document = tmp_path / "style.json"
    document.write_text(json.dumps({"constraints": []}), encoding="utf-8")
    guard = run(backend, "image_profile_get", {})["result"]["itemId"]
    status, answer = command(backend, ["profile", "save", "--file", str(document), "--reason", "Drop", "--expected-current-version-id", guard], {"PAPYRUS_ACTOR_KIND": "agent"})
    assert status == 2 and answer["error"]["code"] == "human_required"


def test_the_groups_an_id_token_names_are_read_without_trusting_it():
    import base64
    import json

    from papyrus_content.images.profile_handlers import groups_from_token

    payload = base64.urlsafe_b64encode(json.dumps({"cognito:groups": ["admin"]}).encode()).decode().rstrip("=")
    assert groups_from_token(f"Bearer header.{payload}.signature") == ("admin",)
    assert groups_from_token("not a token") == () and groups_from_token(None) == ()


def test_the_signed_in_lane_fills_in_who_signed_in_and_whether_they_are_an_admin(monkeypatch):
    import base64
    import json

    from papyrus_content import cli_user_auth
    from papyrus_content.images.profile_handlers import signed_in_handlers

    backend = FakeBackend("ours", profile=profile_copy())
    backend.endpoint = "https://example.invalid/graphql"
    payload = base64.urlsafe_b64encode(json.dumps({"cognito:groups": ["admin"]}).encode()).decode().rstrip("=")
    monkeypatch.setattr(cli_user_auth, "signed_in_label", lambda endpoint: "Ada Admin")
    monkeypatch.setattr(cli_user_auth, "selected_headers", lambda endpoint: {"Authorization": f"header.{payload}.sig"})
    handlers = signed_in_handlers(lambda: backend)
    guard = run(backend, "image_profile_get", {})["result"]["itemId"]
    answer = execute("image_profile_save", {"document": {"constraints": []}, "reason": "Drop", "expectedCurrentVersionId": guard}, Caller(), handlers)
    assert answer["ok"] and run(backend, "image_profile_history", {})["result"]["versions"][0]["by"] == "Ada Admin"
