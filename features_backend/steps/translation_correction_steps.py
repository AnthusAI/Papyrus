"""A person's correction of a translation (features_backend/translation-correction.feature). Runs on the shared in-memory fake backend of the translation
procedure's steps; the command's own function is called with the signed-in session faked."""
from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "features_backend" / "steps"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from story_localize_steps import LINEAGE, _latest, _provenance, _publish, _run, _upload, _versions  # noqa: E402

from papyrus_content.localize import desired_state  # noqa: E402

SESSION = "agent-session"


def _body_blocks(row) -> list[str]:
    from papyrus_content.localize.blocks import split_body

    return split_body(row["bodyMarkus"])


def _command(context, edits, *, editor="Pat Editor", reason="the wording reads better", approver=None, extra=()):
    from papyrus_content.story_commands import stories_correct_translation

    context.versions_before = len(_versions(context))
    context.error = None
    context.published_with = None
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "edits.json"
        path.write_text(json.dumps(edits, ensure_ascii=False), encoding="utf-8")
        flags = ["--story", "story-waymo", "--language", "es-419", "--edits-file", str(path), "--edited-by", editor, "--reason", reason, *extra]
        if approver:
            flags += ["--approved-by", approver]
        output = io.StringIO()

        def publish(arguments):
            context.published_with = arguments

        with mock.patch("papyrus_content.story_commands.create_authoring_client", lambda: (context.client, {"sub": SESSION})), \
                mock.patch("papyrus_content.model_attachments.upload_attachment_body", _upload(context)), \
                mock.patch("papyrus_content.model_attachments.download_attachment_buffer", lambda client, row: context.files.get(row["storagePath"])), \
                mock.patch("papyrus_content.publish_commands.content_publish", publish):
            try:
                with redirect_stdout(output):
                    stories_correct_translation(flags)
            except Exception as error:  # noqa: BLE001 - the scenario reads the refusal
                context.error = error
    context.printed = output.getvalue()


@when('a person named "{editor}" corrects "{old}" to "{new}" in the "{language}" translation because "{reason}", approved by "{approver}"')
def step_corrects_approved(context, editor, old, new, language, reason, approver):
    _command(context, [{"from": old, "to": new}], editor=editor, reason=reason, approver=approver)
    assert context.error is None, context.error


@when('a person named "{editor}" corrects "{old}" to "{new}" in the "{language}" translation because "{reason}"')
@given('a person named "{editor}" corrected "{old}" to "{new}" in the "{language}" translation because "{reason}"')
def step_corrects(context, editor, old, new, language, reason):
    _command(context, [{"from": old, "to": new}], editor=editor, reason=reason)
    assert context.error is None, context.error


@when('a person named "{editor}" corrects every "{old}" to "{new}" in the "{language}" translation because "{reason}"')
def step_corrects_every(context, editor, old, new, language, reason):
    _command(context, [{"from": old, "to": new, "every": True}], editor=editor, reason=reason)
    assert context.error is None, context.error


@when('a person corrects "{old}" to "{new}" in the "{language}" translation without saying every')
def step_corrects_plain(context, old, new, language):
    _command(context, [{"from": old, "to": new}])


@when('a person previews correcting "{old}" to "{new}" in the "{language}" translation')
def step_preview(context, old, new, language):
    _command(context, [{"from": old, "to": new}], extra=["--dry-run"])
    assert context.error is None, context.error


@when('a person runs the command correcting "{old}" to "{new}" with "{flags}"')
def step_command_flags(context, old, new, flags):
    _command(context, [{"from": old, "to": new}], extra=flags.split())


@when('the English Story\'s second paragraph says "{text}" in version {number:d} and the translation is run again')
def step_english_changes(context, text, number):
    context.client.tables["Item"][context.primary["id"]]["versionState"] = "superseded"
    context.paragraphs[1] = text
    _publish(context, number)
    desired_state.want(context.client, source=context.primary, language=context.language, requested_by="cli")
    _run(context)


@then('a new version of "{lineage}" exists whose second paragraph says "{text}"')
def step_new_version(context, lineage, text):
    assert len(_versions(context)) == context.versions_before + 1, [row["id"] for row in _versions(context)]
    assert _body_blocks(_latest(context))[1] == text, _body_blocks(_latest(context))


@then('that version is by "{editor}", unpublished and has the earlier version as its predecessor')
def step_by(context, editor):
    row, earlier = _latest(context), _versions(context)[-2]
    assert row["versionCreatedBy"] == editor and row["status"] == "draft" and row["previousVersionId"] == earlier["id"], row
    assert earlier["versionState"] == "superseded", earlier


@then("in its alignment only the second paragraph is human and pinned")
def step_alignment(context):
    alignment = _provenance(context)["alignment"]
    pinned = [index for index, entry in enumerate(alignment) if entry["owner"] == "human" and entry["pinned"]]
    others = [entry for index, entry in enumerate(alignment) if index not in pinned]
    assert [alignment[i]["text"] for i in pinned] == ["El [informe](https://example.test/report) cubre 12 ciudades."], alignment
    assert all(entry["owner"] == "machine" and not entry["pinned"] for entry in others), alignment


@then('its provenance records the editor "{editor}", the applier "{applier}", the reason, and the paragraph before and after')
def step_provenance(context, editor, applier):
    corrections = _provenance(context)["corrections"]
    assert len(corrections) == 1, corrections
    entry = corrections[0]
    assert entry["editedBy"] == editor and entry["appliedBy"] == applier and entry["reason"] == "the verb reads better", entry
    assert [(b["before"], b["after"]) for b in entry["blocks"]] == [("El [informe](https://example.test/report) abarca 12 ciudades.",
                                                                    "El [informe](https://example.test/report) cubre 12 ciudades.")], entry
    assert entry["versionId"] == _latest(context)["id"]


@then('the approver "{approver}" is in the provenance and nowhere in the page\'s text, title, dek or change reason')
def step_approver(context, approver):
    assert _provenance(context)["corrections"][0]["approvedBy"] == approver
    row = _latest(context)
    visible = json.dumps([row["bodyMarkus"], row["title"], row["deck"], row["changeReason"], row["headline"]], ensure_ascii=False)
    assert approver not in visible and "pproved" not in visible, visible


@then('the second paragraph of the newest translation still says "{text}"')
def step_second_still(context, text):
    assert _body_blocks(_latest(context))[1] == text, _body_blocks(_latest(context))


@then("the newest provenance marks that paragraph as a conflict")
def step_conflict(context):
    assert any(entry.get("conflict") for entry in _provenance(context)["alignment"]), _provenance(context)["alignment"]


@then("the newest translation is held saying the person's wording no longer matches the English")
def step_conflict_held(context):
    provenance = _provenance(context)
    assert provenance["outcome"] == "held" and "no longer matches the English" in provenance["reason"], (provenance["outcome"], provenance["reason"])


@then('the title and the first paragraph of the newest translation say "{text}"')
def step_every(context, text):
    row = _latest(context)
    assert text in row["title"] and text in _body_blocks(row)[0], (row["title"], _body_blocks(row)[0])


@then('the correction is refused saying "{text}" occurs more than once')
def step_refused_many(context, text):
    assert context.error is not None and f'"{text}" occurs' in str(context.error), context.error


@then("the correction is refused saying it would change a fixed part")
def step_refused_fixed(context):
    assert context.error is not None and "fixed part" in str(context.error), context.error


@then('the correction is refused saying "{text}" is not in the translation')
def step_refused_absent(context, text):
    assert context.error is not None and f'"{text}" is not in the translation' in str(context.error), context.error


@then('no new version of "{lineage}" is saved')
def step_no_new(context, lineage):
    assert len(_versions(context)) == context.versions_before


@then("the preview shows the second paragraph before and after")
def step_preview_shows(context):
    assert "before\tEl [informe](https://example.test/report) abarca 12 ciudades." in context.printed, context.printed
    assert "after\tEl [informe](https://example.test/report) cubre 12 ciudades." in context.printed, context.printed


@then("the ordinary publish of the new version is run with verification")
def step_published(context):
    assert context.error is None, context.error
    assert context.published_with == ["--id", _latest(context)["id"], "--verify"], context.published_with


@then("the command is refused because verification goes with publishing")
def step_verify_alone(context):
    assert context.error is not None and "--publish" in str(context.error), context.error
    assert context.published_with is None
