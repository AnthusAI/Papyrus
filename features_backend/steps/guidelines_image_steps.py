"""Image guidelines in the guideline store (features_backend/image-profile.feature, guidelines-image-sections.feature). An in-memory backend and files; no network."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.guidelines.handlers import with_client as guidelines_with_client  # noqa: E402
from papyrus_content.images.handlers import Caller, execute  # noqa: E402
from papyrus_content.images.profile_fakes import profile_copy  # noqa: E402
from papyrus_content.images.profile_handlers import SECTION_STYLE_FIELD, signed_in_handlers, with_client  # noqa: E402
from papyrus_content.images.profile_store import IMAGE_KIND, document_store  # noqa: E402

EDITOR = Caller(kind="person", subject="Edie Editor")
ADMIN = Caller(kind="person", subject="Ada Admin", is_admin=True)


def ours(context):
    return context.image_backends["ours"]


def run_ours(context, op, arguments, caller=EDITOR):
    return execute(op, arguments, caller, with_client(ours(context)))


def current_guard(context):
    return run_ours(context, "image_profile_get", {})["result"]["itemId"]


def ensure_section(context, section):
    if section not in ours(context).sections:
        ours(context).add_section(section)


def section_document(context, section):
    found = document_store(ours(context)).read(IMAGE_KIND, section)
    return dict(found["document"]) if found else {"schemaVersion": 2}


def save_section_document(context, section, document):
    ensure_section(context, section)
    ours(context).save_profile_version(document, by="Ada Admin", reason="Section guidelines", section=section)


# --- the profile in S3 and in the old shape -----------------------------------------------------------------------------------------------------------

@then("the profile's catalog row holds no style text and the style document is one file in S3")
def step_catalog_row(context):
    store = ours(context)
    row = next(item for item in store.items if item["versionState"] == "current")
    assert row["slug"] == "editorial-doctrine-visual-style" and row["bodyMarkus"] == "", row
    assert "visualStyle" not in json.loads(row["metadata"] or "{}"), row["metadata"]
    assert len(store.document_attachments) == 1 and store.document_attachments[0]["role"] == "doctrine_document" and store.document_attachments[0]["ownerId"] == row["id"]
    assert json.loads(store.document_bodies[store.document_attachments[0]["storagePath"]])["identity"]["summary"] == "Flat and calm."


@then("reading the profile returns the document that was saved")
def step_reads_back(context):
    result = run_ours(context, "image_profile_get", {})["result"]
    assert result["profile"]["identity"]["summary"] == "Flat and calm." and result["versionNumber"] == 1, result


@given('an image publication "{name}" whose style profile was saved in the old inline shape with the master prompt "{text}"')
def step_old_shape(context, name, text):
    from papyrus_content.images.profile_fakes import FakeBackend

    if not hasattr(context, "image_backends"):
        context.image_backends = {}
    document = profile_copy()
    document["identity"]["masterPrompt"] = text
    backend = FakeBackend(name)
    backend.save_inline_profile_version(document, by="admin-account", reason="Saved before the move.")
    context.image_backends[name] = backend


@then("the old profile is read from its row with no file in S3")
def step_old_row(context):
    store = ours(context)
    assert store.document_attachments == [] and store.document_bodies == {}
    assert "visualStyle" in json.loads(store.items[0]["metadata"])


@when('an editor saves the profile as it is with the reason "{reason}"')
def step_resave(context, reason):
    context.effective_before = context.image_answer["result"]["effective"]
    context.sources_before = context.image_answer["result"]["fieldSources"]
    got = run_ours(context, "image_profile_get", {})["result"]
    answer = run_ours(context, "image_profile_save", {"document": got["profile"], "reason": reason, "expectedCurrentVersionId": got["itemId"]})
    assert answer["ok"], answer


@then("the profile is at version {number:d} and its text is in S3")
def step_version_in_s3(context, number):
    store = ours(context)
    result = run_ours(context, "image_profile_get", {})["result"]
    assert result["versionNumber"] == number, result
    row = next(item for item in store.items if item["id"] == result["itemId"])
    assert "visualStyle" not in json.loads(row["metadata"] or "{}") and len(store.document_attachments) == 1


@then("version {number:d} can still be read as the old shape")
def step_old_version(context, number):
    result = run_ours(context, "image_profile_get", {"version": number})["result"]
    assert result["isCurrent"] is False and result["profile"]["identity"]["masterPrompt"] == "Old flat shapes.", result


@then('resolving the "{use}" use of "{lineage}" again gives the same effective guidance as before the move')
def step_same_effective(context, use, lineage):
    arguments = {"target": {"kind": "story", "lineageId": lineage}, "use": use, **({"imageType": context.image_request["imageType"]} if context.image_request.get("imageType") else {})}
    after = run_ours(context, "image_profile_resolve", arguments)["result"]
    assert after["effective"] == context.effective_before and after["fieldSources"] == context.sources_before, after


# --- a section's image document -------------------------------------------------------------------------------------------------------------------------

@given('the section "{section}" has an image document that keeps only the palette colour "{colour}"')
def step_section_palette(context, section, colour):
    document = section_document(context, section)
    document["palette"] = [colour]
    save_section_document(context, section, document)


@given('the section "{section}" has an image document that asks the type "{image_type}" to allow the sources "{first}" and "{second}"')
def step_section_sources(context, section, image_type, first, second):
    document = section_document(context, section)
    document.setdefault("imageTypes", {})[image_type] = {"sources": [first, second]}
    save_section_document(context, section, document)


@given('the section "{section}" has an image document that adds the guidance "{guidance}" and avoids "{item}"')
def step_section_guidance(context, section, guidance, item):
    document = section_document(context, section)
    document["bodyMarkus"] = guidance
    document["avoid"] = [item]
    save_section_document(context, section, document)


@then('the palette of the answer is only "{colour}"')
def step_palette_only(context, colour):
    names = [entry["name"] for entry in context.image_answers["ours"]["result"]["effective"]["palette"]]
    assert names == [colour], names


@then('the palette is credited to the section "{section}" at its image document version {number:d}')
def step_palette_credit(context, section, number):
    result = context.image_answers["ours"]["result"]
    layer = next(item for item in result["layers"] if item["layer"] == "section")
    assert result["fieldSources"]["palette"] == f"section:{section}" and layer["source"]["versionNumber"] == number, result


@then("the section's image document is stored as a catalog row and one file in S3")
def step_section_stored(context):
    store = ours(context)
    row = next(item for item in store.items if item.get("slug") == "desk-doctrine-security-visual-style")
    assert row["bodyMarkus"] == "" and row["section"] == "security"
    assert [a for a in store.document_attachments if a["ownerId"] == row["id"] and a["role"] == "doctrine_document"]


@then('the sources of the answer are only "{source}"')
def step_sources_only(context, source):
    assert context.image_answers["ours"]["result"]["effective"]["sources"] == [source], context.image_answers["ours"]["result"]["effective"]


@then("the answer warns that a section cannot add a choice")
def step_warns(context):
    assert "choice_not_added" in [w["code"] for w in context.image_answers["ours"]["result"]["warnings"]]


@when('an admin saves a section image document for "{section}" that sets a constraint')
def step_section_constraint(context, section):
    ensure_section(context, section)
    handlers = guidelines_with_client(ours(context), ours(context).document_files)
    context.guidelines_answer = execute("guidelines_save", {"kind": "image", "section": section, "reason": "Try a rule",
                                                            "document": {"schemaVersion": 2, "constraints": [{"id": "x", "text": "Nothing."}]}, "expectedCurrentVersionId": "none"},
                                        ADMIN, handlers)


@then("the save is refused because a section cannot set that")
def step_refused(context):
    answer = context.guidelines_answer
    assert not answer["ok"] and answer["error"]["code"] == "invalid_input" and "constraints" in answer["error"]["message"], answer
    assert not [row for row in ours(context).items if row.get("slug") == "desk-doctrine-security-visual-style"]


@then('the guidance of the answer holds "{guidance}" and the avoid list holds "{item}"')
def step_old_fields_applied(context, guidance, item):
    effective = context.image_answers["ours"]["result"]["effective"]
    assert guidance in effective["guidance"] and item in effective["avoid"], effective


@then("no file was read for the section")
def step_no_file(context):
    owners = ours(context).document_files.downloads
    assert owners and all(owner.startswith("item-editorial-doctrine-visual-style") for owner in owners), owners


# --- the command line and the door --------------------------------------------------------------------------------------------------------------------

@when('the command line and the door each resolve the "{use}" use of "{lineage}" for the section "{section}" and the type "{image_type}"')
def step_both_lanes(context, use, lineage, section, image_type):
    backend = ours(context)
    backend.add_story(lineage, section=section)
    arguments = {"target": {"kind": "story", "lineageId": lineage}, "use": use, "imageType": image_type, "sectionId": section}
    cli = execute("image_profile_resolve", arguments, EDITOR, signed_in_handlers(client_factory=lambda: backend))
    door = execute("image_profile_resolve", arguments, EDITOR, with_client(backend, section_fields=SECTION_STYLE_FIELD, files=backend.document_files))
    assert cli["ok"] and door["ok"], (cli, door)
    context.lane_answers = {"command line": cli["result"], "door": door["result"]}


@then("both answers give the same effective guidance, sources and layers")
def step_same_lanes(context):
    cli, door = context.lane_answers["command line"], context.lane_answers["door"]
    for key in ("effective", "fieldSources", "layers", "warnings", "resolutionHash"):
        assert cli[key] == door[key], (key, cli[key], door[key])


@then('both answers hold the guidance "{guidance}" and the palette "{colour}" only')
def step_both_hold(context, guidance, colour):
    for name, result in context.lane_answers.items():
        assert guidance in result["effective"]["guidance"] and [c["name"] for c in result["effective"]["palette"]] == [colour], (name, result["effective"])


# --- a section's own image types ---------------------------------------------------------------------------------------------------------------------------

PROCESS_DIAGRAM = {"label": "Process diagram", "description": "A step by step diagram for security stories.", "treatment": "diagram", "use": "inline", "sources": ["generated"],
                   "display": {"smallestWidthPx": 343, "thumbnail": False}}


def save_section_through_door(context, section, document):
    ensure_section(context, section)
    backend = ours(context)
    handlers = guidelines_with_client(backend, backend.document_files)
    read = execute("guidelines_get", {"kind": "image", "section": section}, EDITOR, handlers)
    guard = read["result"]["expectedCurrentVersionId"] if read["ok"] else read["error"]["details"].get("expectedCurrentVersionId", "none")
    context.section_save = execute("guidelines_save", {"kind": "image", "section": section, "document": document, "reason": "Section types", "expectedCurrentVersionId": guard},
                                   ADMIN, handlers)
    return context.section_save


@given('the section "{section}" has an image document with its own image type "{key}"')
def step_section_own_type(context, section, key):
    answer = save_section_through_door(context, section, {"schemaVersion": 2, "imageTypes": {key: dict(PROCESS_DIAGRAM)}})
    assert answer["ok"], answer


@given('the section "{section}" exists without an image document')
def step_section_without_document(context, section):
    ensure_section(context, section)


@when('an admin saves a section image document for "{section}" that redefines the publication\'s image type "{key}"')
def step_section_shadow(context, section, key):
    save_section_through_door(context, section, {"schemaVersion": 2, "imageTypes": {key: {"label": "Mine", "use": "cover", "sources": ["generated"], "treatment": "diagram"}}})


@when('an admin saves a section image document for "{section}" with an image type "{key}" that has no use and no sources')
def step_section_incomplete(context, section, key):
    save_section_through_door(context, section, {"schemaVersion": 2, "imageTypes": {key: {"label": "Sketch", "treatment": "diagram"}}})


@when('an admin saves a section image document for "{section}" with a generated photograph type "{key}"')
def step_section_photo(context, section, key):
    save_section_through_door(context, section, {"schemaVersion": 2, "imageTypes": {key: {"label": "Staged", "treatment": "photo", "use": "cover", "sources": ["generated"]}}})


@when('an admin saves a section image document for "{section}" that drops its image type "{key}"')
def step_section_drop(context, section, key):
    save_section_through_door(context, section, {"schemaVersion": 2, "avoid": ["clutter"]})


@when('an admin saves a section image document for "{section}" that retires its image type "{key}"')
def step_section_retire(context, section, key):
    save_section_through_door(context, section, {"schemaVersion": 2, "imageTypes": {key: {**PROCESS_DIAGRAM, "retired": True}}})


@then('the section save is refused as "{code}" naming "{key}"')
def step_section_refused(context, code, key):
    answer = context.section_save
    assert not answer["ok"] and answer["error"]["code"] == code and key in json.dumps(answer["error"]), answer


@then("the section save is accepted")
def step_section_accepted(context):
    assert context.section_save["ok"], context.section_save


@then('the answer resolves the image type "{key}" and says it came from the section layer')
def step_resolves_section_type(context, key):
    answer = context.image_answers["ours"]
    assert answer["ok"], answer
    result = answer["result"]
    assert result["imageType"] == key
    assert {"layer": "image-type", "key": key, "origin": "section"} in result["layers"], result["layers"]
    assert any(str(where).startswith(f"section-image-type:{key}") for where in result["fieldSources"].values()), result["fieldSources"]
    assert [row for row in result["availableTypes"] if row["key"] == key][0]["origin"] == "section"


@then('the answer refuses the image type "{key}" as unknown')
def step_unknown_type(context, key):
    answer = context.image_answers["ours"]
    assert not answer["ok"] and answer["error"]["code"] == "image_type_unknown", answer


@when('an editor resolves the image guidelines for the section "{section}"')
def step_guidelines_resolve_section(context, section):
    backend = ours(context)
    context.resolved_image = execute("guidelines_resolve", {"kind": "image", "section": section}, EDITOR, guidelines_with_client(backend, backend.document_files))
    assert context.resolved_image["ok"], context.resolved_image


@when("an editor resolves the image guidelines for the publication alone")
def step_guidelines_resolve_publication(context):
    backend = ours(context)
    context.resolved_image = execute("guidelines_resolve", {"kind": "image"}, EDITOR, guidelines_with_client(backend, backend.document_files))
    assert context.resolved_image["ok"], context.resolved_image


@then('the resolved image guidelines list "{key}" as an image type of the section layer')
def step_resolved_lists(context, key):
    result = context.resolved_image["result"]
    assert key in result["document"]["imageTypes"] and result["fieldSources"][f"imageTypes.{key}"][0]["layer"] == "section", result["fieldSources"]


@then("the resolved image guidelines name the publication's version and the section's version as layers")
def step_resolved_layers(context):
    layers = context.resolved_image["result"]["layers"]
    assert [(layer["scope"], layer["versionNumber"]) for layer in layers] == [("publication", 1), ("section", 1)], layers


@then('the resolved image guidelines do not list "{key}"')
def step_resolved_without(context, key):
    assert key not in context.resolved_image["result"]["document"]["imageTypes"]
