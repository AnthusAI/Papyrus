"""The publication's visual style profile and image types (features_backend/image-profile.feature, image-types.feature). A fake backend; no network."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.images import prompt_lint  # noqa: E402
from papyrus_content.images.handlers import Caller, execute  # noqa: E402
from papyrus_content.images.profile_fakes import FakeBackend, profile_copy  # noqa: E402
from papyrus_content.images.profile_handlers import with_client  # noqa: E402
from papyrus_content.images.profile_store import profile_versions  # noqa: E402
from papyrus_content.images.prompt_skeleton import compose_plan  # noqa: E402
from papyrus_content.images.visual_style import PROFILE_MISSING  # noqa: E402

EDITOR = Caller(kind="person", subject="Edie Editor")
ADMIN = Caller(kind="person", subject="Ada Admin", is_admin=True)
AGENT = Caller(kind="agent", subject="Edie Editor", delegated_by="Edie Editor")
BRIEF = "A locked filing cabinet"


def backend(context, name="ours"):
    return context.image_backends[name]


def run(context, name, op, arguments, caller=EDITOR):
    envelope = execute(op, arguments, caller, with_client(backend(context, name)))
    context.image_answer = envelope
    return envelope


def guard_of(context, name="ours"):
    return execute("image_profile_get", {}, EDITOR, with_client(backend(context, name)))["result"]["itemId"]


def stored_count(context, name="ours"):
    return len([write for write in backend(context, name).writes if write[0] == "create"])


def profile_with_master(text):
    document = profile_copy()
    document["identity"]["masterPrompt"] = text
    return document


@given('an image publication "{name}" with a saved style profile whose master prompt says "{text}"')
def step_publication_with_profile(context, name, text):
    if not hasattr(context, "image_backends"):
        context.image_backends = {}
    context.image_backends[name] = FakeBackend(name, profile=profile_with_master(text))


@given('an image publication "{name}" with no style profile')
def step_publication_without_profile(context, name):
    if not hasattr(context, "image_backends"):
        context.image_backends = {}
    context.image_backends[name] = FakeBackend(name)


@given('a Story "{lineage}" in each publication')
def step_story_everywhere(context, lineage):
    for store in context.image_backends.values():
        store.add_story(lineage, section=None)


@given('the section "{section}" says "{guidance}" and avoids "{item}"')
def step_section_guidance(context, section, guidance, item):
    backend(context).add_section(section, visualGuidance=guidance, visualStyle=json.dumps({"avoid": [item]}))


@given('the Story "{lineage}" says to avoid "{item}"')
def step_story_avoids(context, lineage, item):
    store = backend(context)
    store.items[:] = [row for row in store.items if row["lineageId"] != lineage or row["versionNumber"] != 1]
    store.add_story(lineage, section="security", image_style={"avoid": [item]})


@given('the Story "{lineage}" tries to clear the constraints and remove "{item}"')
def step_story_attacks(context, lineage, item):
    store = backend(context)
    store.items[:] = [row for row in store.items if row["lineageId"] != lineage]
    store.add_story(lineage, section=None, image_style={"constraints": [], "removeFromParent": {"avoid": [item]}, "never": []})


@given('the section "{section}" allows only the sources "{source}" for the type "{image_type}"')
def step_section_narrows(context, section, source, image_type):
    store = backend(context)
    existing = json.loads(store.sections.get(section, {}).get("visualStyle") or "{}")
    existing.setdefault("imageTypes", {})[image_type] = {"sources": [source]}
    store.add_section(section, visualStyle=json.dumps(existing))


@when('the section "{section}" asks the type "{image_type}" to also allow "{source}"')
def step_section_widens(context, section, image_type, source):
    store = backend(context)
    existing = json.loads(store.sections.get(section, {}).get("visualStyle") or "{}")
    existing.setdefault("imageTypes", {})[image_type] = {"sources": ["stock", source]}
    store.add_section(section, visualStyle=json.dumps(existing))


@given('the section "{section}" asks for the treatment "{treatment}"')
def step_section_treatment(context, section, treatment):
    backend(context).add_section(section, visualStyle=json.dumps({"treatment": treatment}))


@given('the profile record belongs to a different account than the one signed in')
def step_wrong_account(context):
    store = backend(context)
    store.tenant_id = "someone-else"


# --- requests ---------------------------------------------------------------------------------------------------------------------------------------

def request(context) -> dict:
    if not hasattr(context, "image_request"):
        context.image_request = {}
    return context.image_request


@given('the request names the image type "{image_type}"')
@when('the request names the image type "{image_type}"')
def step_request_type(context, image_type):
    request(context)["imageType"] = image_type


@given("the request is for generation")
@when("the request is for generation")
def step_request_generation(context):
    request(context)["operation"] = "generate"


@given('the request is for the section "{section}"')
@when('the request is for the section "{section}"')
def step_request_section(context, section):
    request(context)["sectionId"] = section


@when('the style is resolved for the "{use}" use of "{lineage}" in "{name}"')
def step_resolve(context, use, lineage, name):
    ask = request(context)
    arguments = {"target": {"kind": "story", "lineageId": lineage}, "use": use}
    for key in ("imageType", "sectionId"):
        if ask.get(key):
            arguments[key] = ask[key]
    if not hasattr(context, "image_answers"):
        context.image_answers = {}
    envelope = run(context, name, "image_profile_resolve", arguments)
    if ask.get("operation") == "generate":
        # The operation decides which sources a type must allow; the profile operation is the same resolver asked on behalf of generation.
        from papyrus_content.images.profile_handlers import resolve_for_request
        from papyrus_content.images.handlers import ImageOperationError

        try:
            resolved, warnings = resolve_for_request(backend(context, name), arguments, operation="generate")
            envelope = {"ok": True, "op": "image_profile_resolve", "publication": name, "result": resolved, "warnings": warnings}
        except ImageOperationError as error:
            envelope = {"ok": False, "op": "image_profile_resolve", "error": {"code": error.code, "message": error.message, "details": error.details}}
    context.image_answer = envelope
    context.image_answers[name] = envelope


@then('asking "{name}" for a Story that only exists elsewhere is answered with not found')
def step_not_found(context, name):
    envelope = run(context, name, "image_profile_resolve", {"target": {"kind": "story", "lineageId": "story-elsewhere"}, "use": "cover"})
    assert envelope["error"]["code"] == "not_found", envelope


@then('the answer from "{name}" names the publication "{publication}" and its plan holds "{wanted}" and never "{unwanted}"')
def step_answer_for(context, name, publication, wanted, unwanted):
    envelope = context.image_answers[name]
    assert envelope["ok"] and envelope["publication"] == publication, envelope
    text = compose_plan(envelope["result"], BRIEF)["text"]
    assert wanted in text and unwanted not in text, text


@when("the profile is read")
def step_read_profile(context):
    try:
        run(context, "ours", "image_profile_get", {})
        context.image_error = None
    except ValueError as error:
        context.image_error = str(error)


@then("reading it fails because the record is outside the signed-in account")
def step_tenant_refused(context):
    assert context.image_error and "tenant" in context.image_error, context.image_error


# --- saving -----------------------------------------------------------------------------------------------------------------------------------------

FIRST_DOCUMENT = {"schemaVersion": 2, "identity": {"summary": "Flat and calm."}, "imageReview": "before_publish"}


@when('an editor saves the first style document with the reason "{reason}"')
def step_first_save(context, reason):
    run(context, "ours", "image_profile_save", {"document": copy.deepcopy(FIRST_DOCUMENT), "reason": reason, "expectedCurrentVersionId": "none"})
    assert context.image_answer["ok"], context.image_answer


@when('an editor changes the summary to "{summary}" with the reason "{reason}"')
def step_change_summary(context, summary, reason):
    run(context, "ours", "image_profile_save", {"document": {"identity": {"summary": summary}}, "reason": reason, "expectedCurrentVersionId": guard_of(context)})
    assert context.image_answer["ok"], context.image_answer


@then('the profile is at version {number:d} and says "{summary}"')
def step_profile_at(context, number, summary):
    result = run(context, "ours", "image_profile_get", {})["result"]
    assert result["versionNumber"] == number and result["profile"]["identity"]["summary"] == summary, result


@then('version {number:d} can still be read and says "{summary}"')
def step_old_version(context, number, summary):
    result = run(context, "ours", "image_profile_get", {"version": number})["result"]
    assert result["profile"]["identity"]["summary"] == summary and result["isCurrent"] is False, result


@then('the history lists version 2 with the reason "{newer}" before version 1 with the reason "{older}"')
def step_history(context, newer, older):
    versions = run(context, "ours", "image_profile_history", {})["result"]["versions"]
    assert [(v["versionNumber"], v["reason"]) for v in versions] == [(2, newer), (1, older)], versions


@then("both versions are stored as separate records, the older one marked superseded")
def step_two_records(context):
    rows = profile_versions(backend(context))
    assert [(row["versionNumber"], row["versionState"]) for row in rows] == [(2, "current"), (1, "superseded")], rows


@when("an editor saves a change naming a version that is no longer current")
def step_stale_save(context):
    run(context, "ours", "image_profile_save", {"document": {"identity": {"mood": ["dry"]}}, "reason": "x", "expectedCurrentVersionId": "item-editorial-doctrine-visual-style-v0"})


@then("the save is refused as stale and nothing new is stored")
def step_stale(context):
    assert context.image_answer["error"]["code"] == "stale_version" and stored_count(context) == 1


@when("an editor saves the same mood the profile already has")
def step_same_mood(context):
    run(context, "ours", "image_profile_save", {"document": {"identity": {"mood": ["calm"]}}, "reason": "No change", "expectedCurrentVersionId": guard_of(context)})


@then("the answer says it is unchanged and the profile stays at version 1")
def step_unchanged(context):
    assert context.image_answer["result"]["unchanged"] is True and context.image_answer["result"]["versionNumber"] == 1 and stored_count(context) == 1


def remove_constraint(context, caller):
    run(context, "ours", "image_profile_save", {"document": {"constraints": []}, "reason": "Drop the rule", "expectedCurrentVersionId": guard_of(context)}, caller)


@when("an agent tries to remove the binding constraint")
def step_agent_removes(context):
    remove_constraint(context, AGENT)


@then("the save is refused because a person is required and nothing new is stored")
def step_person_required(context):
    assert context.image_answer["error"]["code"] == "human_required" and stored_count(context) == 1


@when("an editor who is not an admin tries to remove the binding constraint")
def step_editor_removes(context):
    remove_constraint(context, EDITOR)


@then("the save is refused as not authorised and nothing new is stored")
def step_not_authorised(context):
    assert context.image_answer["error"]["code"] == "not_authorized" and stored_count(context) == 1


@when("an admin removes the binding constraint")
def step_admin_removes(context):
    remove_constraint(context, ADMIN)
    assert context.image_answer["ok"], context.image_answer


@then("the profile is at version 2 with no constraints")
def step_no_constraints(context):
    result = run(context, "ours", "image_profile_get", {})["result"]
    assert result["versionNumber"] == 2 and result["profile"]["constraints"] == [], result


@then("version 1 still holds the constraint")
def step_old_constraint(context):
    assert run(context, "ours", "image_profile_get", {"version": 1})["result"]["profile"]["constraints"][0]["id"] == "no-photoreal-generated"


@when('an agent adds a mood word with the reason "{reason}"')
def step_agent_mood(context, reason):
    run(context, "ours", "image_profile_save", {"document": {"identity": {"mood": ["calm", "dry"]}}, "reason": reason, "expectedCurrentVersionId": guard_of(context)}, AGENT)
    assert context.image_answer["ok"], context.image_answer


@then("the profile is at version 2 and the history says the agent made it")
def step_agent_history(context):
    versions = run(context, "ours", "image_profile_history", {})["result"]["versions"]
    assert versions[0]["versionNumber"] == 2 and versions[0]["byKind"] == "agent", versions


@when('an admin adds the binding constraint "{rule}" with the reason "{reason}"')
def step_admin_adds(context, rule, reason):
    constraints = [*profile_copy()["constraints"], {"id": rule, "text": "No logos.", "promptAvoid": ["logo"]}]
    run(context, "ours", "image_profile_save", {"document": {"constraints": constraints}, "reason": reason, "expectedCurrentVersionId": guard_of(context)}, ADMIN)
    assert context.image_answer["ok"], context.image_answer


@then('the constraint "{rule}" is at version 1 with the admin as adopter and the reason "{reason}"')
def step_stamped(context, rule, reason):
    constraint = next(c for c in run(context, "ours", "image_profile_get", {})["result"]["profile"]["constraints"] if c["id"] == rule)
    assert (constraint["version"], constraint["adoptedBy"], constraint["reason"]) == (1, "Ada Admin", reason), constraint
    assert constraint["adoptedAt"]


@then("the existing constraint is stored exactly as before")
def step_existing_constraint(context):
    stored = run(context, "ours", "image_profile_get", {})["result"]["profile"]["constraints"][0]
    assert stored == profile_copy()["constraints"][0], stored


@when("an editor previews dropping the binding constraint and changing the mood")
def step_preview(context):
    run(context, "ours", "image_profile_diff", {"document": {"constraints": [], "identity": {"mood": ["dry"]}}})


@then("the preview lists the mood change and the constraint as removed and says the next version would be 2")
def step_preview_result(context):
    result = context.image_answer["result"]
    assert {"path": "identity.mood", "from": ["calm"], "to": ["dry"]} in result["changes"], result
    assert [change["change"] for change in result["constraintChanges"]] == ["removed"] and result["wouldCreateVersion"] == 2


@then("nothing new is stored")
def step_nothing_stored(context):
    assert stored_count(context) == 1, backend(context).writes


# --- no profile and the review setting --------------------------------------------------------------------------------------------------------------

@then("the answer succeeds with the profile missing warning in the design's words")
def step_missing_warning(context):
    envelope = context.image_answer
    assert envelope["ok"] and envelope["result"]["profile"] is None, envelope
    assert envelope["warnings"] == [{"code": "profile_missing", "message": PROFILE_MISSING}], envelope["warnings"]
    for words in ("undefined and unpredictable", "writing style guidelines", "example images"):
        assert words in PROFILE_MISSING


@then('the plan for the brief "{brief}" is exactly "{text}"')
def step_skeleton_only(context, brief, text):
    assert compose_plan(context.image_answer["result"], brief)["text"] == text


@then("no constraint, style or negative appears in it")
def step_no_style(context):
    plan = compose_plan(context.image_answer["result"], BRIEF)
    assert plan["avoid"] == [] and [segment["slot"] for segment in plan["segments"]] == ["subject"], plan


@then("the profile says pictures are reviewed before publication")
def step_review_default(context):
    assert run(context, "ours", "image_profile_get", {})["result"]["imageReview"] == "before_publish"


@when('an editor changes the review setting to after the fact with the reason "{reason}"')
def step_review_after(context, reason):
    run(context, "ours", "image_profile_save", {"document": {"imageReview": "after_the_fact"}, "reason": reason, "expectedCurrentVersionId": guard_of(context)})
    assert context.image_answer["ok"], context.image_answer


@then("the profile says pictures are reviewed after the fact")
def step_review_after_check(context):
    assert run(context, "ours", "image_profile_get", {})["result"]["imageReview"] == "after_the_fact"


# --- precedence ---------------------------------------------------------------------------------------------------------------------------------------

@then("the layers run publication, treatment, use, the parent image type, the image type, section and Story, in that order")
def step_layers(context):
    result = context.image_answer["result"]
    assert [(layer["layer"], layer.get("key")) for layer in result["layers"]] == [
        ("publication", None), ("treatment", "editorial-illustration"), ("use", "inline"), ("image-type", "cover-illustration"), ("image-type", "inline-illustration"),
        ("section", None), ("story", None)], result["layers"]


@then("the sizes come from the parent image type and the sources from the image type")
def step_size_sources(context):
    sources = context.image_answer["result"]["fieldSources"]
    assert sources["sizes"] == "image-type:cover-illustration" and sources["sources"] == "image-type:inline-illustration", sources


@then("the guidance lines come from the treatment, the parent type, the type and the section, in that order")
def step_guidance_order(context):
    sources = context.image_answer["result"]["fieldSources"]
    assert [sources[f"guidance[{index}]"] for index in range(4)] == [
        "treatment:editorial-illustration", "image-type:cover-illustration", "image-type:inline-illustration", "section:security"], sources


@then('"{first}" and "{second}" are in the things to avoid, from the section and the Story')
def step_avoid_sources(context, first, second):
    result = context.image_answer["result"]
    avoid = result["effective"]["avoid"]
    assert first in avoid and second in avoid
    assert result["fieldSources"][f"avoid[{avoid.index(first)}]"] == "section:security"
    assert result["fieldSources"][f"avoid[{avoid.index(second)}]"].startswith("story:")


@then('"{item}" is no longer avoided and the removal is recorded against the image type')
def step_removed(context, item):
    result = context.image_answer["result"]
    assert item not in result["effective"]["avoid"]
    assert any(item in note and "image-type:inline-illustration" in note for note in result["fieldSources"]["removed"]), result["fieldSources"]


@then('"{item}" is still avoided')
def step_still_avoided(context, item):
    assert item in context.image_answer["result"]["effective"]["avoid"]


def type_edit(context, change):
    document = profile_copy()
    change(document["imageTypes"])
    run(context, "ours", "image_profile_save", {"document": document, "reason": "Try it", "expectedCurrentVersionId": guard_of(context)})
    context.stored_before = 1


@when('an editor tries to save a type that removes "{item}" from its parent')
def step_remove_never(context, item):
    type_edit(context, lambda types: types["inline-illustration"]["removeFromParent"].update({"avoid": [item]}))


@when("an editor tries to save a type that removes the binding constraint from its parent")
def step_remove_constraint(context):
    type_edit(context, lambda types: types["inline-illustration"]["removeFromParent"].update({"constraints": ["no-photoreal-generated"]}))


@then("the save is refused as a conflict with the publication's rules")
def step_conflict_refused(context):
    assert context.image_answer["error"]["code"] == "constraint_conflict" and stored_count(context) == 1, context.image_answer


@then("the binding constraint is still in force and \"{item}\" is still avoided")
def step_constraint_in_force(context, item):
    result = context.image_answer["result"]
    assert [constraint["id"] for constraint in result["constraints"]] == ["no-photoreal-generated"] and item in result["effective"]["avoid"], result


@then("the answer warns that the Story's attempt was ignored")
def step_story_ignored(context):
    assert any(w["code"] == "override_field_ignored" and "A Story" in w["message"] for w in context.image_answer["result"]["warnings"])


@then('the effective sources are "{source}" and they came from the section')
def step_sources_narrowed(context, source):
    result = context.image_answer["result"]
    assert result["effective"]["sources"] == [source] and result["fieldSources"]["sources"].startswith("section:"), result


@then('the effective sources are still "{source}" and the answer warns that a source cannot be added')
def step_sources_not_added(context, source):
    result = context.image_answer["result"]
    assert result["effective"]["sources"] == [source] and any(w["code"] == "choice_not_added" for w in result["warnings"]), result


@then("the answer is a conflict that names the binding constraint")
def step_conflict_named(context):
    error = context.image_answer["error"]
    assert error["code"] == "constraint_conflict" and error["details"]["constraint"]["id"] == "no-photoreal-generated", error


# --- saving the type tree -----------------------------------------------------------------------------------------------------------------------------

@when("an editor tries to save types that extend each other in a circle")
def step_cycle(context):
    context.stored_before = stored_count(context)
    run(context, "ours", "image_profile_save", {"document": {"imageTypes": {"cover-illustration": {"extends": "inline-illustration"}}}, "reason": "Try",
                                                "expectedCurrentVersionId": guard_of(context)})


@then("the save is refused as invalid and the message says the types extend each other in a circle")
def step_cycle_refused(context):
    error = context.image_answer["error"]
    assert error["code"] == "invalid_input" and "circle" in error["message"], error


@when("an editor tries to save a type that extends a type that does not exist")
def step_unknown_parent(context):
    run(context, "ours", "image_profile_save", {"document": {"imageTypes": {"social-card": {"extends": "no-such-type"}}}, "reason": "Try",
                                                "expectedCurrentVersionId": guard_of(context)})


@then("the save is refused as invalid and the message names the missing parent")
def step_missing_parent(context):
    error = context.image_answer["error"]
    assert error["code"] == "invalid_input" and "no-such-type" in error["message"], error


@when("an editor tries to save an image type that carries its own constraints")
def step_type_constraints(context):
    run(context, "ours", "image_profile_save", {"document": {"imageTypes": {"cover-illustration": {"constraints": [{"id": "mine", "text": "Mine."}]}}}, "reason": "Try",
                                                "expectedCurrentVersionId": guard_of(context)})


@then("the save is refused as invalid and the message says binding rules belong to the publication")
def step_type_constraints_refused(context):
    error = context.image_answer["error"]
    assert error["code"] == "invalid_input" and "belong to the publication" in error["message"], error


@when('an editor tries to remove the type "{key}" from the profile')
def step_remove_type(context, key):
    run(context, "ours", "image_profile_save", {"document": {"imageTypes": {key: None}}, "reason": "Try", "expectedCurrentVersionId": guard_of(context)})


@then("the save is refused as invalid and the message says to retire it instead")
def step_retire_instead(context):
    error = context.image_answer["error"]
    assert error["code"] == "invalid_input" and "Retire it" in error["message"], error


@when('an editor retires the type "{key}"')
def step_retire(context, key):
    run(context, "ours", "image_profile_save", {"document": {"imageTypes": {key: {"retired": True}}}, "reason": "Retired", "expectedCurrentVersionId": guard_of(context)})
    assert context.image_answer["ok"], context.image_answer


@then("the type is no longer offered for covers")
def step_not_offered(context):
    result = run(context, "ours", "image_profile_resolve", {"target": {"kind": "story", "lineageId": "story-1"}, "use": "cover", "imageType": "cover-illustration"})["result"]
    assert "cover-photo" not in [choice["key"] for choice in result["availableTypes"]], result["availableTypes"]


@then('asking for "{key}" is refused as an unknown or retired type with the available choices')
def step_retired_refused(context, key):
    envelope = run(context, "ours", "image_profile_resolve", {"target": {"kind": "story", "lineageId": "story-1"}, "use": "cover", "imageType": key})
    assert envelope["error"]["code"] == "image_type_unknown" and envelope["error"]["details"]["choices"], envelope


@then("resolving it for an old picture that used it still works")
def step_retired_resolves(context):
    from papyrus_content.images.profile_handlers import resolve_for_request

    resolved, _ = resolve_for_request(backend(context), {"use": "cover", "imageType": "cover-photo"}, allow_retired=True)
    assert resolved["imageType"] == "cover-photo"


# --- choosing the type ----------------------------------------------------------------------------------------------------------------------------------

@then('the type is "{key}", chosen as the default for the use, and the answer warns which type it picked')
def step_defaulted(context, key):
    result = context.image_answer["result"]
    assert (result["imageType"], result["imageTypeChosenBy"]) == (key, "default-for-use"), result
    assert any(w["code"] == "image_type_defaulted" and key in w["message"] for w in context.image_answer["warnings"]), context.image_answer["warnings"]


@then('the answer is that an image type is required, listing "{first}" and "{second}" with their descriptions')
def step_required(context, first, second):
    error = context.image_answer["error"]
    assert error["code"] == "image_type_required", error
    choices = {choice["key"]: choice for choice in error["details"]["choices"]}
    assert set(choices) == {first, second} and all(choice["description"] for choice in choices.values()), choices


@then("the answer is that the image type is unknown, listing the types available for covers")
def step_unknown(context):
    error = context.image_answer["error"]
    assert error["code"] == "image_type_unknown" and {"cover-diagram", "cover-photo", "cover-illustration", "social-card"} - {c["key"] for c in error["details"]["choices"]} == {"social-card"}


@then('the answer is that the source is not allowed, listing "{source}" as the type\'s source and where its rules live')
def step_not_allowed(context, source):
    error = context.image_answer["error"]
    assert error["code"] == "source_not_allowed" and error["details"]["allowed"] == [source], error
    assert error["details"]["rules"]["figureSystem"]["rules"] == "design/figures/rules.md"


# --- the lint ---------------------------------------------------------------------------------------------------------------------------------------------

@then("the prompt skeleton holds no wording outside its slots, labels and joining words")
def step_lint_passes(context):
    source = Path(prompt_lint.__file__).with_name("prompt_skeleton.py").read_text(encoding="utf-8")
    assert prompt_lint.style_wording_in(source) == []


@then("the lint fails on a sample that puts style wording in code")
def step_lint_style(context):
    assert prompt_lint.style_wording_in('STYLE = "Flat, calm shapes in ink blue"') == ["Flat, calm shapes in ink blue"]


@then("the lint fails on a sample that puts a negative in code")
def step_lint_negative(context):
    assert prompt_lint.style_wording_in('def avoid():\n    return ["photograph", "watermark"]') == ["photograph", "watermark"]


# --- what agents read -------------------------------------------------------------------------------------------------------------------------------------

def style_row(document, number=1, tenant=None):
    from papyrus_content.images.profile_store import next_record

    record = next_record([], document, actor="Ada Admin", reason="Saved", now="2026-11-07T17:51:39Z", saved_by={"sub": "Ada Admin", "kind": "person"})
    record["id"] = f"item-editorial-doctrine-visual-style-v{number}"
    record["versionNumber"] = number
    record["tenantId"] = tenant
    return record


@given("editorial records whose publication has a saved image style")
def step_editorial_with_style(context):
    from procedures.newsroom.tests.test_editorial_context import Records

    context.editorial_records = Records()
    context.editorial_records.records["Item"]["editorial-doctrine-visual-style"] = [style_row(profile_copy())]


def editorial_context(context, **kwargs):
    from papyrus_content.editorial_context import resolve_editorial_context

    return resolve_editorial_context(context.editorial_records, endpoint="https://example.invalid", **kwargs)


@when("the editorial context is resolved including the image style")
def step_editorial_resolve(context):
    context.editorial_pack = editorial_context(context, include_visual_style=True)


@then("it has a visual-style entry from the publication with the version and a content hash")
def step_editorial_entry(context):
    entry = next(entry for entry in context.editorial_pack["entries"] if entry["kind"] == "visual-style")
    assert entry["scope"] == "publication" and entry["source"]["versionNumber"] == 1 and entry["source"]["contentHash"] and entry["source"]["sha256"]


@then("its text lists the image types")
def step_editorial_types(context):
    entry = next(entry for entry in context.editorial_pack["entries"] if entry["kind"] == "visual-style")
    assert "`cover-illustration`" in entry["text"] and "Choose an image type" in entry["text"], entry["text"]


@when("the image style is edited and the editorial context is resolved again")
def step_editorial_edit(context):
    context.first_context_hash = context.editorial_pack["contextHash"]
    edited = profile_copy()
    edited["identity"]["summary"] = "Loud and bright."
    rows = context.editorial_records.records["Item"]["editorial-doctrine-visual-style"]
    rows[0]["versionState"] = "superseded"
    rows.append(style_row(edited, number=2))
    context.editorial_pack = editorial_context(context, include_visual_style=True)


@then("the context hash is different")
def step_editorial_hash(context):
    assert context.editorial_pack["contextHash"] != context.first_context_hash


@then("an editorial context resolved without asking for the style has no visual-style entry")
def step_editorial_without(context):
    assert all(entry["kind"] != "visual-style" for entry in editorial_context(context)["entries"])


@given("a newsroom whose publication has a saved image style")
def step_newsroom_with_style(context):
    from newsroom_context_pack_steps import TENANT, build_newsroom

    context.store = build_newsroom()
    context.store.doctrine["editorial-doctrine-visual-style"] = [style_row(profile_copy(), tenant=TENANT)]


@given("a newsroom whose publication has no saved image style")
def step_newsroom_without_style(context):
    from newsroom_context_pack_steps import build_newsroom

    context.store = build_newsroom()


@when("the {profile} agent's context pack is built for the Story")
def step_build_profile_pack(context, profile):
    from newsroom_context_pack_steps import profile_pack

    context.pack = profile_pack(context, profile, story_lineage_id="story-1")


def style_layer_lines(context):
    from newsroom_context_pack_steps import layer_text

    return layer_text(context, "visual_style")


@then("the visual style layer lists one line for each image type grouped by use")
def step_pack_lines(context):
    text = style_layer_lines(context)
    for key in ("cover-diagram", "cover-photo", "cover-illustration", "social-card", "inline-diagram", "inline-illustration"):
        assert sum(1 for line in text.splitlines() if line.startswith(f"- `{key}`")) == 1, (key, text)
    assert "Cover and cards:" in text and "Inside the article:" in text and "Social cards:" in text


@then("a line says where the pictures of that type may come from and whether it is read as a thumbnail")
def step_pack_sources(context):
    text = style_layer_lines(context)
    diagram = next(line for line in text.splitlines() if line.startswith("- `cover-diagram`"))
    assert "drawn with the figure system" in diagram and "never generated" in diagram and "read as a thumbnail" in diagram and "160px" in diagram, diagram
    technical = next(line for line in text.splitlines() if line.startswith("- `inline-diagram`"))
    assert "never a thumbnail" in technical, technical


@then("the layer tells the agent to choose an image type before asking for a picture")
def step_pack_choose(context):
    assert "Choose an image type before asking for a picture" in style_layer_lines(context)
    assert style_layer_lines(context).index("`cover-diagram`") < style_layer_lines(context).index("`cover-photo`") < style_layer_lines(context).index("`cover-illustration`")


@then("the layer holds the rule that cannot be loosened in full")
def step_pack_rule(context):
    text = style_layer_lines(context)
    assert "Rules that cannot be loosened" in text and profile_copy()["constraints"][0]["text"] in text, text


@then("the visual style layer lists the image types but not the rules or the summary")
def step_editor_pack(context):
    text = style_layer_lines(context)
    assert "`cover-illustration`" in text and "Rules that cannot be loosened" not in text and profile_copy()["identity"]["summary"] not in text, text


@then("the pack has no visual style layer")
def step_no_layer(context):
    assert all(layer["name"] != "visual_style" for layer in context.pack["layers"])


@then("the visual style layer is empty because the publication has no image style guidelines")
def step_empty_layer(context):
    layer = next(layer for layer in context.pack["layers"] if layer["name"] == "visual_style")
    assert layer["entries"] == [] and "no image style guidelines" in layer["emptyReason"], layer


@then("the pack warns that the style of generated images will be undefined and unpredictable")
def step_pack_warns(context):
    assert PROFILE_MISSING in context.pack["warnings"], context.pack["warnings"]
