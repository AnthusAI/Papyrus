"""Finished copy attached as a Story's translation (features_backend/translation-import.feature). Runs on the shared in-memory fake backend of the
translation procedure's steps; the command's own function is called with the signed-in session faked. No model is scripted for the import: it calls none."""
from __future__ import annotations

import io
import json
import re
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import yaml
from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "features_backend" / "steps"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from story_localize_steps import STORY, _collect, _upload  # noqa: E402

from papyrus_content.localize import backfill, desired_state  # noqa: E402
from papyrus_content.publishing import published_item_id_for  # noqa: E402

SESSION = "agent-session"
SLUG_POLICIES = {"es-419": "translated", "zh-Hans": "characters"}
IMAGE = '::image{src="assets/waymo.png" alt="Un auto sin conductor" credit="Image: Jane Doe, CC BY 2.0"}'
COPIES = {
    "es-419": {"title": "Bajan los choques de Waymo", "deck": "Un informe de doce ciudades.",
               "blocks": ["Los autos de Waymo pueden chocar un 68 % menos, según la empresa.",
                          "El [informe](https://example.test/report) abarca 12 ciudades.", IMAGE]},
    "zh-Hans": {"title": "Waymo 事故减少", "deck": "一份来自十二个城市的报告。",
                "blocks": ["据该公司称，Waymo 汽车发生事故的可能性可能降低 68%。", "这份[报告](https://example.test/report)涵盖 12 个城市。",
                           '::image{src="assets/waymo.png" alt="一辆无人驾驶汽车" credit="Image: Jane Doe, CC BY 2.0"}']},
}


def _lineage(context) -> str:
    return f"{STORY}--{context.copy_language}"


def _versions(context):
    return sorted((row for row in context.client.tables.get("Item", {}).values() if row.get("lineageId") == _lineage(context)), key=lambda r: r["versionNumber"])


def _latest(context):
    versions = _versions(context)
    assert versions, "no translation was saved"
    return versions[-1]


def _provenance(context):
    attachments = context.client.tables["ModelAttachment"].values()
    row = next(value for value in attachments if value["ownerId"] == _latest(context)["id"] and value["role"] == "localization_provenance")
    return json.loads(context.files[row["storagePath"]])


@given('finished Spanish copy for "{story}" written for the "{language}" edition')
@given('finished Chinese copy for "{story}" written for the "{language}" edition')
def step_copy(context, story, language):
    context.copy_language = language
    context.copy = json.loads(json.dumps(COPIES[language]))
    context.copy_embedded = False
    context.copy_extra_front = {}
    context.copy_without = set()
    context.language = language


def _vary(context, new, old):
    def replaced(value):
        if isinstance(value, str):
            return value.replace(old, new)
        return [replaced(item) for item in value] if isinstance(value, list) else {key: replaced(item) for key, item in value.items()}

    before = context.copy
    context.copy = replaced(before)
    assert context.copy != before, f"the copy never says {old!r}"


@given('the copy says "{new}" where it says "{old}"')
def step_copy_says(context, new, old):
    _vary(context, new, old)


@given('the copy has the extra paragraph "{text}" after its first paragraph')
def step_copy_extra(context, text):
    context.copy["blocks"].insert(1, text)


@given("the copy joins its first two paragraphs")
def step_copy_joined(context):
    first, second = context.copy["blocks"][:2]
    context.copy["blocks"][:2] = [first + " " + second]


@given("the copy's front matter has no dek")
def step_copy_no_dek(context):
    context.copy_without.add("deck")


@given('the copy\'s front matter also has "{line}"')
def step_copy_extra_front(context, line):
    key, value = line.split(": ", 1)
    context.copy_extra_front[key] = value


@given("the copy's front matter is the opening block of its body file")
def step_copy_embedded(context):
    context.copy_embedded = True


@given('the English Story is not published')
def step_unpublished(context):
    context.client.tables.get("PublishedItem", {}).pop(published_item_id_for(STORY), None)


@given('"{lineage}" is a published translation of "{story}"')
def step_is_translation(context, lineage, story):
    row = {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "type": "article", "status": "published",
           "stage": None, "slug": "bajan-los-choques", "section": "machines", "title": "Bajan los choques de Waymo", "bodyMarkus": "Cuerpo.\n",
           "contentHash": "hash-es", "language": "es-419", "languageGroupId": story, "metadata": "{}"}
    context.client.tables.setdefault("Item", {})[row["id"]] = row
    context.client.tables.setdefault("PublishedItem", {})[published_item_id_for(lineage)] = {
        "id": published_item_id_for(lineage), "sourceItemId": row["id"], "itemLineageId": lineage, "versionNumber": 1, "type": "article", "status": "published",
        "language": "es-419", "languageGroupId": story, "metadata": "{}"}


@given('a translation run for "{language}" is in progress for "{story}"')
def step_in_progress(context, language, story):
    record = desired_state.want(context.client, source=context.primary, language=language, requested_by="cli")
    desired_state.record_outcome(context.client, record, state="started", run_key="run-1")


# --- running the command ------------------------------------------------------------------------------------------------------------------


def _files(context, scratch: Path) -> tuple[Path, Path | None]:
    import yaml

    copy = context.copy
    front = {"title": copy["title"], **({} if "deck" in context.copy_without else {"deck": copy["deck"]}), **context.copy_extra_front}
    body = "\n\n".join(copy["blocks"]) + "\n"
    body_file = scratch / "copy.md"
    if context.copy_embedded:
        body_file.write_text("---\n" + yaml.safe_dump(front, allow_unicode=True, sort_keys=False) + "---\n\n" + body, encoding="utf-8")
        return body_file, None
    body_file.write_text(body, encoding="utf-8")
    front_file = scratch / "front.yaml"
    front_file.write_text(yaml.safe_dump(front, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return body_file, front_file


def _settings(tags):
    return {"languages": {"primary": "en", "enabled": list(tags)}}


def _import(context, writer, language, *, story=STORY, reason="Beijing draft", extra=(), drop=(), body_file=None):
    from papyrus_content import editorial_checks, story_commands

    context.error, context.printed, context.collect_judge = None, "", "unset"
    site = getattr(context, "site", None)
    real = site is not None

    def fake_collect(client, *, story, language, judge, procedure_version, **rest):
        context.collect_judge = judge
        request = _collect(context)(client, story=story, language=language, judge=judge, procedure_version=procedure_version, **rest)
        request.slug_policy = SLUG_POLICIES.get(language, "translated")
        return request

    class Quiet:
        def __init__(self, *args, **kwargs):
            pass

    output = io.StringIO()
    with tempfile.TemporaryDirectory() as scratch:
        body, front = _files(context, Path(scratch))
        flags = ["--story", story, "--language", language, "--body-file", str(body_file or body), "--written-by", writer, "--reason", reason, *extra]
        if front is not None:
            flags += ["--front-matter-file", str(front)]
        for name in drop:
            index = flags.index(name)
            del flags[index:index + 2]
        patches = [mock.patch("papyrus_content.story_commands.create_authoring_client", lambda: (context.client, {"sub": SESSION})),
                   mock.patch("papyrus_content.model_attachments.upload_attachment_body", _upload(context)),
                   mock.patch("papyrus_content.model_attachments.download_attachment_buffer", lambda client, row: context.files.get(row["storagePath"]))]
        if real:   # the real collect, for the refusals that are its own: an unpublished Story, a translation, a language the site does not write in
            settings = _settings(site)
            patches += [mock.patch.object(editorial_checks, "GraphQLEditorialStore", Quiet), mock.patch.object(editorial_checks, "settings_from", lambda store: settings)]
        else:
            patches.append(mock.patch("papyrus_content.localize.import_copy.collect", fake_collect))
        for patch in patches:
            patch.start()
        try:
            with redirect_stdout(output):
                story_commands.stories_import_translation(flags)
        except Exception as error:  # noqa: BLE001 - the scenario reads the refusal
            context.error = error
        finally:
            for patch in patches:
                patch.stop()
    context.printed = output.getvalue()


@given('"{writer}" imported the copy as the "{language}" translation of "{story}" because "{reason}"')
def step_imported(context, writer, language, story, reason):
    _import(context, writer, language, story=story, reason=reason)
    assert context.error is None, context.error


@when('"{writer}" imports the copy as the "{language}" translation of "{story}" because "{reason}"')
def step_import(context, writer, language, story, reason):
    _import(context, writer, language, story=story, reason=reason)   # a scenario about a refusal reads context.error


@when('"{writer}" imports the copy as the "{language}" translation of "{story}" because "{reason}" saying bots helped')
def step_import_with_bots(context, writer, language, story, reason):
    _import(context, writer, language, story=story, reason=reason, extra=["--drafting-by-ai"])
    assert context.error is None, context.error


@given('the English Story is drafted by AI and names the author "{author}"')
def step_english_byline(context, author):
    context.primary["metadata"] = json.dumps({"frontMatterYaml": f"title: Waymo\nauthor: {author}\ndrafting:\n  by: AI\n"})


@given("the English Story has no front matter")
def step_english_no_front_matter(context):
    context.primary["metadata"] = json.dumps({})


@then('the saved version\'s front matter has the author "{author}" and no drafting by AI')
def step_front_matter_human(context, author):
    front = yaml.safe_load(_localization_front(context))
    assert front["author"] == author and "drafting" not in front and "authors" not in front, front


@then('the saved version\'s front matter has the author "{author}" and drafting by AI')
def step_front_matter_bots(context, author):
    front = yaml.safe_load(_localization_front(context))
    assert front["author"] == author and front["drafting"] == {"by": "AI"}, front


def _localization_front(context) -> str:
    return json.loads(_latest(context)["metadata"])["frontMatterYaml"]


@given('the site writes in {tags}')
def step_site_writes(context, tags):
    context.site = [part.strip().strip('"') for part in re.split(r",| and ", tags)]


@when('"{writer}" previews importing the copy as the "{language}" translation of "{story}"')
def step_preview(context, writer, language, story):
    _import(context, writer, language, story=story, extra=["--dry-run"])
    assert context.error is None, context.error


@when('"{writer}" runs the command without --written-by')
def step_without_writer(context, writer):
    _import(context, writer, "es-419", drop=["--written-by"])


@when("\"{writer}\" runs the command with a body file that does not exist")
def step_missing_file(context, writer):
    _import(context, writer, "es-419", body_file="/nonexistent/copy.md")


# --- what was saved -----------------------------------------------------------------------------------------------------------------------


def _localization(row) -> dict:
    return json.loads(row["metadata"])["localization"]


@then('the saved copy is written in "{language}" in the language group "{group}" and its address is made of the title\'s characters')
def step_zh(context, language, group):
    row = _latest(context)
    assert row["lineageId"] == f"{group}--{language}" and row["language"] == language and row["languageGroupId"] == group, row
    assert row["slug"] == "waymo-事故减少", row["slug"]


@then("the import is saved, not held")
def step_saved(context):
    assert context.error is None, context.error
    assert _localization(_latest(context))["outcome"] == "saved" and "held:" not in context.printed, (context.printed, _latest(context)["metadata"])


@then('that version is by "{writer}", unpublished, has no board stage and its change reason names the writer and the reason')
def step_by(context, writer):
    row = _latest(context)
    assert row["versionCreatedBy"] == writer and row["status"] == "draft" and not row.get("stage") and not row.get("headStageKey"), row
    assert row["syncState"] == "current", row
    assert row["changeReason"] == f"imported copy written by {writer}: Beijing draft, reviewed by the Madrid editors", row["changeReason"]


@then("its title, dek and body are the copy's")
def step_text(context):
    row = _latest(context)
    assert row["title"] == context.copy["title"] and row["deck"] == context.copy["deck"], (row["title"], row["deck"])
    assert row["bodyMarkus"] == "\n\n".join(context.copy["blocks"]) + "\n", row["bodyMarkus"]


@then("its address was drafted by the language's slug policy")
def step_slug(context):
    assert _latest(context)["slug"] == "bajan-los-choques-de-waymo", _latest(context)["slug"]


@then("the imported copy is not published")
def step_nothing_published(context):
    live = [row for row in context.client.tables.get("PublishedItem", {}).values() if row.get("itemLineageId") == _lineage(context)]
    assert not live and all(row["status"] == "draft" for row in _versions(context)), live


@then('the version says it is an imported translation written by "{writer}", imported by "{applier}"')
def step_kind(context, writer, applier):
    localization = _localization(_latest(context))
    assert localization["translation"] == "imported" and localization["writtenBy"] == writer and localization["importedBy"] == applier, localization


@then('its provenance says the copy was written by "{writer}" and was not machine-generated')
def step_authorship(context, writer):
    authorship = _provenance(context)["authorship"]
    assert authorship["kind"] == "written" and authorship["machineGenerated"] is False and authorship["writtenBy"] == writer, authorship
    assert authorship["reason"] == "Beijing draft" and authorship["importedBy"] == SESSION, authorship


@then("its provenance names no model and no cost, and no judge was given to the checks")
def step_no_model(context):
    provenance = _provenance(context)
    assert provenance["models"] is None and provenance["cost"]["totalUsd"] == 0.0 and provenance["rounds"] == [], provenance
    assert context.collect_judge is None, context.collect_judge
    assert provenance["procedure"]["key"] == "papyrus.story.import-translation", provenance["procedure"]


@then("in its alignment all {count:d} blocks are human and pinned and name the English blocks they pair with")
def step_alignment(context, count):
    from papyrus_content.localize.blocks import blocks_of

    alignment = _provenance(context)["alignment"]
    english = blocks_of(context.primary["bodyMarkus"], title=context.primary["title"], deck=context.primary["deck"])
    assert len(alignment) == count and all(entry["owner"] == "human" and entry["pinned"] for entry in alignment), alignment
    assert [entry["sourceBlock"] for entry in alignment] == [block.id for block in english], alignment
    assert [entry["text"] for entry in alignment][:2] == [context.copy["title"], context.copy["deck"]], alignment


@then('the request for "{language}" is saved for source version 3 and names no automation')
def step_request_saved(context, language):
    row = context.client.tables["LocalizationRequest"][desired_state.request_id(STORY, language)]
    assert row["state"] == "saved" and row["sourceVersionNumber"] == 3 and row["sourceContentHash"] == "hash-v3", row
    assert not row.get("automationId") and row["publish"] is False and row["runKey"] == _localization(_latest(context))["runKey"], row


@then('the request for "{language}" is held for source version 3')
def step_request_held(context, language):
    row = context.client.tables["LocalizationRequest"][desired_state.request_id(STORY, language)]
    assert row["state"] == "held" and row["sourceVersionNumber"] == 3 and row["reason"], row


@given("the English Story is published as the site lists it")
def step_listed(context):
    context.client.tables.setdefault("PublishedItem", {})[published_item_id_for(STORY)] = {
        "id": published_item_id_for(STORY), "sourceItemId": context.primary["id"], "itemLineageId": STORY, "versionNumber": 3, "type": "article",
        "status": "published", "slug": "waymo-crashes-fall", "section": "machines", "title": context.primary["title"],
        "metadata": json.dumps({"sourceContentHash": "hash-v3"}), "language": "en", "languageGroupId": STORY}


@then('surveying the whole site for "{language}" finds the Story up to date')
def step_survey(context, language):
    step_listed(context)
    jobs = backfill.survey(context.client, _settings(["en", "es-419", "zh-Hans"]), [language])
    assert [(job.story, job.status) for job in jobs] == [(STORY, backfill.UP_TO_DATE)], [(job.story, job.status, job.detail) for job in jobs]
    context.client.tables["PublishedItem"].pop(published_item_id_for(STORY))


@then("the import is held and the output names the number finding")
def step_held(context):
    assert context.error is None, context.error
    assert "held: flag review request" in context.printed and "error faithfulness" in context.printed and "numbers" in context.printed, context.printed


@then("the version is saved with the outcome held and a flag review request says why")
def step_held_saved(context):
    localization = _localization(_latest(context))
    assert localization["outcome"] == "held" and localization["translation"] == "imported", localization
    (review,) = context.client.tables["ReviewRequest"].values()
    assert review["id"].startswith("localize-") and "held" in review["reason"] and "numbers" in review["reason"], review
    assert review["id"] == f"localize-{localization['runKey'][:24]}", review["id"]
    assert _provenance(context)["authorship"]["machineGenerated"] is False


@then("the output prints a finding that is not an error")
def step_advice(context):
    assert "\twarn " in context.printed or "\tinfo " in context.printed, context.printed


@then("the preview shows the title, the dek and every body block paired with its English block")
def step_preview_alignment(context):
    rows = [line.split("\t") for line in context.printed.splitlines() if "\taligned\t" in line]
    assert [row[3] for row in rows] == ["block 1", "block 2", "block 3", "block 4", "block 5"], rows
    assert [row[4] for row in rows] == ["title", "deck", "prose", "prose", "directive"], rows
    assert "Waymo crashes fall" in rows[0][6] and "Bajan los choques de Waymo" in rows[0][8], rows[0]
    assert "dry run\t5 block(s) aligned" in context.printed, context.printed


@then("the preview names the number finding")
def step_preview_finding(context):
    assert "error faithfulness\tnumbers" in context.printed, context.printed


@then('no version of "{lineage}" is saved and no request is written')
def step_nothing_written(context, lineage):
    assert len(_versions(context)) == 0 and not context.client.tables.get("LocalizationRequest"), (_versions(context), context.client.tables.get("LocalizationRequest"))
    assert not context.client.tables.get("ModelAttachment") and not context.client.tables.get("ReviewRequest")


@then('no version of "{lineage}" is saved')
def step_no_version(context, lineage):
    assert len(_versions(context)) == 0


@then("the import is refused saying the English body has {english:d} blocks and the copy has {copy:d}")
def step_refused_count(context, english, copy):
    assert context.error is not None and f"The English body has {english} blocks and the copy has {copy}" in str(context.error), context.error


@then("the refusal says they first stop matching at block {number:d}")
def step_refused_position(context, number):
    assert f"first stop matching at block {number}" in str(context.error) or f"first differ at block {number}" in str(context.error), context.error


@then("the import is refused saying a link target, address, citation, credit or other fixed part is not the English's")
def step_refused_fixed(context):
    assert context.error is not None and "fixed part is not the English's" in str(context.error), context.error


@then("the import is refused saying the front matter lacks a dek")
def step_refused_dek(context):
    assert context.error is not None and "front matter lacks a dek" in str(context.error), context.error


@then("the import is refused saying the front matter has {key}")
def step_refused_front(context, key):
    assert context.error is not None and f"front matter has {key}" in str(context.error), context.error


@then("the import saved nothing new")
def step_unchanged(context):
    assert context.error is None and "unchanged" in context.printed, (context.error, context.printed)


@then('the translation lineage "{lineage}" holds {count:d} version')
@then('the translation lineage "{lineage}" holds {count:d} versions')
def step_count(context, lineage, count):
    assert len(_versions(context)) == count, [row["id"] for row in _versions(context)]


@then('the second version is by "{writer}", has the first as its predecessor and the first is superseded')
def step_second(context, writer):
    first, second = _versions(context)
    assert second["versionCreatedBy"] == writer and second["previousVersionId"] == first["id"] and first["versionState"] == "superseded", (first, second)


@then("the output says it replaces version 1, an imported copy")
def step_replaces(context):
    assert "replaces\tversion 1\timported copy" in context.printed, context.printed


@then("the import is refused saying a translation run is in progress")
def step_in_progress_refused(context):
    assert context.error is not None and "is in progress" in str(context.error), context.error


@then('the import is refused saying there is no language pack for "{tag}"')
def step_no_pack(context, tag):
    assert context.error is not None and f"no language pack for '{tag}'" in str(context.error), context.error


@then('the import is refused saying the site does not write in "{tag}"')
def step_not_enabled(context, tag):
    assert context.error is not None and f"does not write in {tag}" in str(context.error), context.error


@then("the import is refused saying the Story is not published and to publish the English Story first")
def step_not_published(context):
    assert context.error is not None and "is not published" in str(context.error) and "publish the English Story first" in str(context.error), context.error


@then("the import is refused saying the Story is itself a translation")
def step_is_translation_refused(context):
    assert context.error is not None and "is itself a translation of story-waymo" in str(context.error), context.error


@then("the command is refused saying --written-by is required")
def step_writer_required(context):
    assert context.error is not None and "--written-by is required" in str(context.error), context.error


@then("the command is refused saying the body file is not a file")
def step_body_missing(context):
    assert context.error is not None and "--body-file /nonexistent/copy.md is not a file" in str(context.error), context.error
