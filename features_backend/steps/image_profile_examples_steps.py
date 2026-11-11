"""Example pictures and the drafted starting profile (features_backend/image-profile-examples.feature). A fake backend; no network, no files."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.images.examples import example_lists, provider_examples  # noqa: E402
from papyrus_content.images.handlers import Caller, execute  # noqa: E402
from papyrus_content.images.profile_handlers import with_client  # noqa: E402
from papyrus_content.images.profile_store import document_store, profile_versions, to_document  # noqa: E402

EDITOR = Caller(kind="person", subject="Edie Editor")
AGENT = Caller(kind="agent", subject="Edie Editor", delegated_by="Edie Editor")


def store(context):
    return context.image_backends["ours"]


def run(context, op, arguments, caller=EDITOR):
    envelope = execute(op, arguments, caller, with_client(store(context)))
    context.example_answer = envelope
    return envelope


def current(context) -> dict:
    return execute("image_profile_get", {}, EDITOR, with_client(store(context)))["result"]


def attachment_id(context, sha):
    return context.uploads[sha]


def uploads(context):
    if not hasattr(context, "uploads"):
        context.uploads = {}
    return context.uploads


@given('a completed upload of a PNG picture "{sha}"')
def step_upload_png(context, sha):
    uploads(context)[sha] = store(context).add_attachment(sha)


@given('a completed upload of a text file "{sha}" that is not a picture')
def step_upload_text(context, sha):
    uploads(context)[sha] = store(context).add_attachment(sha, media_type="text/plain", filename=f"{sha}.txt")


@given('a completed upload of a PNG picture "{sha}" larger than 10 MB')
def step_upload_big(context, sha):
    uploads(context)[sha] = store(context).add_attachment(sha, size=10 * 1024 * 1024 + 1)


@given('a completed upload of a PNG picture "{sha}" meant as an avoid-this picture')
def step_upload_negative(context, sha):
    uploads(context)[sha] = store(context).add_attachment(sha, role="visual_negative")


def add(context, sha, image_type, note, caller=EDITOR, send=False, guard=None):
    arguments = {"attachmentId": attachment_id(context, sha), "imageType": image_type, "kind": "exemplar", "note": note, "reason": "Added an example.",
                 "expectedCurrentVersionId": guard or current(context)["itemId"]}
    if send:
        arguments["sendToProvider"] = True
    return run(context, "image_profile_example_add", arguments, caller)


@when('an editor adds the picture "{sha}" as a good example of "{image_type}" with the note "{note}"')
def step_editor_adds(context, sha, image_type, note):
    add(context, sha, image_type, note)


@when('an editor adds the picture "{sha}" as a good example of "{image_type}" allowing it to go to a provider')
def step_editor_adds_sent(context, sha, image_type):
    add(context, sha, image_type, "Allowed.", send=True)


@when('an agent adds the picture "{sha}" as a good example of "{image_type}" allowing it to go to a provider')
def step_agent_adds_sent(context, sha, image_type):
    context.versions_before = current(context)["versionNumber"]
    add(context, sha, image_type, "Allowed.", caller=AGENT, send=True)


@when('an agent adds the picture "{sha}" as a good example of "{image_type}" with the note "{note}"')
def step_agent_adds(context, sha, image_type, note):
    add(context, sha, image_type, note, caller=AGENT)


@when('an editor adds a picture that was never uploaded as a good example of "{image_type}" with the note "{note}"')
def step_adds_missing(context, image_type, note):
    run(context, "image_profile_example_add", {"attachmentId": "model-attachment-never-uploaded", "imageType": image_type, "kind": "exemplar", "note": note,
                                                "reason": "Added an example.", "expectedCurrentVersionId": current(context)["itemId"]})


@when('an editor adds the picture "{sha}" naming a version that is no longer current')
def step_adds_stale(context, sha):
    context.versions_before = current(context)["versionNumber"]
    first = current(context)["itemId"]
    run(context, "image_profile_save", {"document": {"identity": {"mood": ["calm", "precise"]}}, "reason": "Moved on.", "expectedCurrentVersionId": first})
    context.versions_before = current(context)["versionNumber"] - 1
    add(context, sha, "cover-illustration", "Stale.", guard=first)


@when('an editor removes the picture "{sha}" from the examples with the reason "{reason}"')
def step_remove(context, sha, reason):
    context.removed = attachment_id(context, sha)
    run(context, "image_profile_example_remove", {"attachmentId": context.removed, "reason": reason, "expectedCurrentVersionId": current(context)["itemId"]})
    assert context.example_answer["ok"], context.example_answer


@when("an agent saves the same example with the provider flag switched on")
def step_agent_flips(context):
    context.versions_before = current(context)["versionNumber"]
    examples = [{**example, "sendToProvider": True} for example in example_lists(to_document(profile_versions(store(context))[0], document_store(store(context))))["cover-illustration"]]
    run(context, "image_profile_save", {"document": {"imageTypes": {"cover-illustration": {"examples": examples}}}, "reason": "Flip it.",
                                         "expectedCurrentVersionId": current(context)["itemId"]}, AGENT)


def stored_examples(context, image_type, version=None):
    versions = profile_versions(store(context))
    row = next(row for row in versions if int(row["versionNumber"]) == version) if version else versions[0]
    return example_lists(to_document(row, document_store(store(context))))[image_type]


@then("the profile is at version {number:d}")
def step_version(context, number):
    assert current(context)["versionNumber"] == number, current(context)["versionNumber"]


@then("the profile is still at version {number:d}")
def step_still_version(context, number):
    assert current(context)["versionNumber"] == number
    assert len([w for w in store(context).writes if w[0] == "create"]) == number


@then('the type "{image_type}" lists the picture "{sha}" as an example noting "{note}" and not sent to a provider')
def step_lists(context, image_type, sha, note):
    entries = [e for e in stored_examples(context, image_type) if e["attachmentId"] == attachment_id(context, sha)]
    assert len(entries) == 1, entries
    assert entries[0]["note"] == note and entries[0]["kind"] == "exemplar" and entries[0]["sendToProvider"] is False and entries[0]["sha256"] == sha, entries[0]


@then('the brand lists the picture "{sha}" as an example')
def step_brand_lists(context, sha):
    assert [e["attachmentId"] for e in stored_examples(context, "identity")] == [attachment_id(context, sha)]


@then("the example records who added it and that a person did")
def step_who(context):
    entry = stored_examples(context, "cover-illustration")[0]
    assert entry["addedBy"] == "Edie Editor" and entry["addedByKind"] == "person" and entry["addedAt"], entry


@then("the example is saved as added by an agent and not sent to a provider")
def step_agent_saved(context):
    assert context.example_answer["ok"], context.example_answer
    entry = stored_examples(context, "cover-illustration")[0]
    assert entry["addedByKind"] == "agent" and entry["sendToProvider"] is False, entry


@then("the uploaded file was not touched")
def step_untouched(context):
    assert [w for w in store(context).writes if w[1] != "Item"] == [] and len(store(context).attachments) == len(uploads(context))


@then("there is still one uploaded file")
def step_one_file(context):
    assert len(store(context).attachments) == 1


@then('the type "{image_type}", which extends "{parent}", lists no examples')
def step_child_none(context, image_type, parent):
    document = to_document(profile_versions(store(context))[0], document_store(store(context)))
    assert document["imageTypes"][image_type]["extends"] == parent
    assert example_lists(document)[parent] and example_lists(document)[image_type] == []


@then('no example of "{image_type}" can be sent to a provider')
def step_child_provider(context, image_type):
    assert provider_examples(to_document(profile_versions(store(context))[0], document_store(store(context))), image_type) == []


@then('the type "{image_type}" lists no examples')
def step_none(context, image_type):
    assert stored_examples(context, image_type) == []


@then('version {number:d} of the profile still lists the picture "{sha}" under "{image_type}"')
def step_old_version(context, number, sha, image_type):
    assert [e["attachmentId"] for e in stored_examples(context, image_type, number)] == [attachment_id(context, sha)]


@then("reading version {number:d} of the profile gives the same example list it had when it was saved")
def step_old_read(context, number):
    envelope = execute("image_profile_get", {"version": number}, EDITOR, with_client(store(context)))
    listed = envelope["result"]["profile"]["imageTypes"]["cover-illustration"]["examples"]
    assert [e["note"] for e in listed] == ["The calm we want."] and envelope["result"]["isCurrent"] is False


@then("removing it again is refused as not found")
def step_remove_again(context):
    run(context, "image_profile_example_remove", {"attachmentId": context.removed, "reason": "Again.", "expectedCurrentVersionId": current(context)["itemId"]})
    assert context.example_answer["error"]["code"] == "not_found", context.example_answer


def refused(context, code):
    answer = context.example_answer
    assert not answer["ok"] and answer["error"]["code"] == code, answer
    return answer["error"]


@then("the add is refused as invalid because examples must be PNG, JPEG or WebP")
def step_refused_type(context):
    assert "PNG, JPEG or WebP" in refused(context, "invalid_input")["message"]


@then("the add is refused as invalid because examples must be 10 MB or smaller")
def step_refused_size(context):
    assert "10 MB" in refused(context, "invalid_input")["message"]


@then("the add is refused as invalid because the upload was for a different kind of picture")
def step_refused_kind(context):
    assert "visual_negative" in refused(context, "invalid_input")["message"]


@then("the add is refused as an unknown image type, listing the types available")
def step_refused_unknown(context):
    keys = [choice["key"] for choice in refused(context, "image_type_unknown")["details"]["choices"]]
    assert "cover-illustration" in keys and "neon-poster" not in keys


@then("the add is refused as not found")
def step_refused_missing(context):
    refused(context, "not_found")


@then("the add is refused as stale and the other editor's version stays current")
def step_refused_stale(context):
    refused(context, "stale_version")
    assert current(context)["versionNumber"] == 2   # the other editor's save is version 2; ours made none


@then("the add is refused because a person is required and the profile is still at version {number:d}")
def step_refused_person(context, number):
    refused(context, "human_required")
    assert current(context)["versionNumber"] == number


@then('the provider may be sent only the picture "{sha}" for "{image_type}"')
def step_provider_only(context, sha, image_type):
    document = to_document(profile_versions(store(context))[0], document_store(store(context)))
    assert [e["attachmentId"] for e in provider_examples(document, image_type)] == [attachment_id(context, sha)]


# --- the drafted starting profile -------------------------------------------------------------------------------------------------------------------------

@when('an editor asks for a starting profile with the brand colour "{name}" "{hex_value}"')
def step_init(context, name, hex_value):
    context.versions_before = len(profile_versions(store(context)))
    run(context, "image_profile_init", {"brand": {"name": "Example Daily", "palette": [{"name": name, "hex": hex_value}]}})
    assert context.example_answer["ok"], context.example_answer


@then("the draft is a valid profile document holding that colour and three image types")
def step_draft_valid(context):
    from papyrus_content.images.visual_style import validate_profile

    result = context.example_answer["result"]
    assert validate_profile(result["document"]) == [] and result["document"]["identity"]["palette"][0]["hex"] == "#1f2a44"
    assert len(result["document"]["imageTypes"]) == 3


@then("the draft holds no style wording and the notes say what the editor still has to write")
def step_draft_no_style(context):
    document = context.example_answer["result"]["document"]
    assert "masterPrompt" not in document["identity"] and "summary" not in document["identity"]
    assert all("guidance" not in definition and "avoid" not in definition for definition in document["imageTypes"].values())
    assert any("masterPrompt" in note for note in context.example_answer["result"]["notes"])


@then("nothing was stored and the publication still has no profile")
def step_nothing_stored(context):
    assert profile_versions(store(context)) == [] and store(context).writes == []


@when('an editor saves the draft with the reason "{reason}"')
def step_save_draft(context, reason):
    result = context.example_answer["result"]
    run(context, "image_profile_save", {"document": result["document"], "reason": reason, "expectedCurrentVersionId": result["expectedCurrentVersionId"]})
    assert context.example_answer["ok"], context.example_answer


@then("the answer warns that the publication already has a profile")
def step_exists_warning(context):
    assert context.example_answer["result"]["profileExists"] is True
    assert [warning["code"] for warning in context.example_answer["warnings"]] == ["profile_exists"]
