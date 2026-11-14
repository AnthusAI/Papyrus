"""Guideline documents: the store and the writing resolver (features_backend/guidelines-store.feature, guidelines-writing-resolve.feature). A fake
backend that fails on any table scan; no network."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import yaml
from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.guidelines import (Field, GuidelineError, GuidelineStore, KindSpec, register_kind, resolve_guidelines, resolve_writing,  # noqa: E402
                                        unregister_kind, validate_document)
from papyrus_content.guidelines.document import PROSE, digest, texts  # noqa: E402
from papyrus_content.guidelines.fakes import FakeBackend, FakeFiles  # noqa: E402

SITE = {"schemaVersion": 1, "voice": {"name": "House"}, "tone": ["Warm."], "voicePatterns": ["Opens plainly."], "lexicon": {"prefer": ["inspect"], "avoid": ["synergy"]},
        "bodyMarkus": "Write plainly.", "constraints": [{"id": "no-hype", "text": "No hype."}], "locked": ["headline"], "headline": {"order": ["title"]},
        "audience": "General readers"}


def fresh(context):
    context.backend = FakeBackend()
    context.store = GuidelineStore(context.backend, FakeFiles(context.backend))
    context.error = None


def save(context, document, section=None, *, kind="writing", reason="First guidelines", expected=None):
    current = context.store.current_row(kind, section)
    guard = expected if expected is not None else (current["id"] if current else "none")
    try:
        context.result = context.store.save(kind, document, section=section, expected_current_version_id=guard, actor="Ada Admin", reason=reason,
                                            now="2026-11-10T10:00:00Z")
        context.error = None
    except GuidelineError as error:
        context.error = error
        context.result = None


def counts(context):
    return len(context.backend.items), len(context.backend.attachments)


# --- the store ----------------------------------------------------------------------------------------------------------------------------------

@given("a publication with no guidelines")
def step_none(context):
    fresh(context)


@given("a publication with saved writing guidelines")
def step_saved(context):
    fresh(context)
    save(context, SITE)


@when('an admin saves a writing document whose body says "{text}" with the reason "{reason}"')
def step_save_writing(context, text, reason):
    save(context, {**SITE, "bodyMarkus": text}, reason=reason)
    context.saved = {**SITE, "bodyMarkus": text}


@then('exactly one catalog row is stored, for the slug "{slug}", with an empty body and no metadata')
def step_one_row(context, slug):
    assert len(context.backend.items) == 1, context.backend.items
    row = context.backend.items[0]
    assert row["slug"] == slug and row["bodyMarkus"] == "" and json.loads(row["metadata"]) == {} and row["body"] == []


@then('exactly one file is stored in S3 as the "{role}" of that row')
def step_one_file(context, role):
    assert len(context.backend.attachments) == 1 and len(context.backend.bodies) == 1
    attachment = context.backend.attachments[0]
    assert attachment["role"] == role and attachment["ownerId"] == context.backend.items[0]["id"] and attachment["ownerKind"] == "item"


@then("reading the writing guidelines returns the same document, and the row's content hash matches it")
def step_read_same(context):
    read = context.store.read("writing")
    assert read["document"] == context.saved
    assert context.backend.items[0]["contentHash"] == digest(context.saved) == read["reference"]["contentHash"]


@when("an admin saves the same document again naming the current version")
def step_same(context):
    context.before = counts(context)
    save(context, copy.deepcopy(SITE))


@then("no new row and no new file are stored")
def step_nothing_new(context):
    assert counts(context) == context.before and context.error is None and context.result["changed"] is False


@then("the writing guidelines are still at version {number:d}")
def step_still_version(context, number):
    assert context.store.read("writing")["reference"]["versionNumber"] == number


@when("an admin saves a change naming a version that is no longer current")
def step_stale(context):
    context.before = counts(context)
    save(context, {**SITE, "audience": "Someone else"}, expected="item-editorial-doctrine-writing-v0")


@then("the save is refused as stale")
def step_refused_stale(context):
    assert context.error is not None and context.error.code == "stale_version"


@then("no new guideline row or file is stored")
def step_nothing_stored(context):
    assert counts(context) == context.before


@when('an admin changes the audience to "{audience}" with the reason "{reason}"')
def step_change_audience(context, audience, reason):
    save(context, {**SITE, "audience": audience}, reason=reason)


@then('the writing guidelines are at version {number:d} and say the audience is "{audience}"')
def step_at_version(context, number, audience):
    read = context.store.read("writing")
    assert read["reference"]["versionNumber"] == number and read["document"]["audience"] == audience


@then('version {number:d} can still be read and says the audience is "{audience}"')
def step_old_version(context, number, audience):
    assert context.store.read("writing", version=number)["document"]["audience"] == audience


@then('the guideline history lists version 2 with the reason "{newer}" before version 1 with the reason "{older}"')
def step_history(context, newer, older):
    history = context.store.history("writing")
    assert [(h["versionNumber"], h["reason"]) for h in history] == [(2, newer), (1, older)]


@when('an admin saves a writing document with an empty tone sentence and an unknown field "{field}"')
def step_bad_document(context, field):
    context.before = counts(context)
    save(context, {"schemaVersion": 1, "tone": [""], field: 1})


@then("the save is refused as invalid")
def step_refused_invalid(context):
    assert context.error is not None and context.error.code == "invalid_input"


@then('the problems name the fields "{first}" and "{second}"')
def step_problem_fields(context, first, second):
    assert {p["path"] for p in context.error.details["problems"]} == {first, second}


@then("no guideline row or file is stored")
def step_nothing(context):
    assert counts(context) == (0, 0)


@then('the style profile of "{name}" validates as a writing document without changes')
def step_profile_valid(context, name):
    document = yaml.safe_load((REPO_ROOT / "publications" / name / "style-profile.yml").read_text())
    assert validate_document("writing", document) == []


@when("the writing guidelines, their history and a section's resolved guidelines are read")
def step_reads(context):
    context.backend.reads.clear()
    context.store.read("writing")
    context.store.history("writing")
    resolve_writing(context.store, "news")   # the fake raises on any list or scan


@then("every read was a query on the slug index or the attachment owner index")
def step_index_reads(context):
    assert context.backend.reads and {index for index, _ in context.backend.reads} <= {"itemBySlug", "modelAttachmentsByOwnerRoleAndSortKey"}


@given('a new kind "{name}" is registered with a hosts field and no other change')
def step_register(context, name):
    fresh(context)
    register_kind(KindSpec(name, name, 1, {"hosts": Field(texts, PROSE)}))
    context.add_cleanup(unregister_kind, name)


@when("an admin saves podcast guidelines for the publication and for the section \"{section}\"")
def step_save_podcast(context, section):
    save(context, {"schemaVersion": 1, "hosts": ["Ada"]}, kind="podcast")
    save(context, {"schemaVersion": 1, "hosts": ["Bo"]}, section, kind="podcast")


@then('they are stored under the slugs "{first}" and "{second}"')
def step_podcast_slugs(context, first, second):
    assert [row["slug"] for row in context.backend.items] == [first, second]


@then('each is one catalog row and one "{role}" file, exactly as for writing guidelines')
def step_podcast_shape(context, role):
    assert counts(context) == (2, 2)
    assert all(a["role"] == role and a["storagePath"].endswith("/doctrine-document/guidelines.json") for a in context.backend.attachments)
    assert all(row["bodyMarkus"] == "" for row in context.backend.items)


@then("the section's podcast guidelines resolve over the publication's with the hosts of both")
def step_podcast_resolve(context):
    assert resolve_guidelines(context.store, "podcast", "weekly")["document"]["hosts"] == ["Ada", "Bo"]


@when('an admin saves a video document whose body says "{text}" with the reason "{reason}"')
def step_save_video(context, text, reason):
    save(context, {"schemaVersion": 1, "bodyMarkus": text}, kind="video", reason=reason)


@then('the video guidelines resolve to that body')
def step_video_resolve(context):
    assert resolve_guidelines(context.store, "video")["document"]["bodyMarkus"] == "Cut on motion."


@then('the stored slug is "{slug}"')
def step_stored_slug(context, slug):
    assert context.backend.items[0]["slug"] == slug


# --- the writing resolver -----------------------------------------------------------------------------------------------------------------------

@given('a publication whose writing guidelines have the tone "Warm.", avoid the word "synergy", have the audience open and lock the headline')
def step_site(context):
    fresh(context)
    document = {key: value for key, value in SITE.items() if key != "audience"}
    save(context, document)


def section_document(context, section, **fields):
    save(context, {"schemaVersion": 1, **fields}, section)


@given('the section "{section}" has writing guidelines with the tone "{tone}" and the voice pattern "{pattern}"')
def step_section_tone_pattern(context, section, tone, pattern):
    section_document(context, section, tone=[tone], voicePatterns=[pattern])


@given('the section "{section}" has writing guidelines that avoid "{word}" and prefer nothing')
def step_section_avoid(context, section, word):
    section_document(context, section, lexicon={"avoid": [word], "prefer": []})


@given('the section "{section}" has writing guidelines with the audience "{audience}"')
def step_section_audience(context, section, audience):
    section_document(context, section, audience=audience)


@given('the section "{section}" has writing guidelines with a different headline order')
def step_section_headline(context, section):
    section_document(context, section, headline={"order": ["subtitle"]})


@given('the section "{section}" has writing guidelines with a binding constraint')
def step_section_constraint(context, section):
    section_document(context, section, constraints=[{"id": "x", "text": "Anything."}])


@given('the section "{section}" has writing guidelines with the tone "{tone}" and the audience "{audience}"')
def step_section_tone_audience(context, section, tone, audience):
    section_document(context, section, tone=[tone], audience=audience)


@when('the writing guidelines are resolved for the section "{section}"')
def step_resolve(context, section):
    context.answer = resolve_writing(context.store, section)


@then('the tone reads "{first}" then "{second}"')
def step_tone_two(context, first, second):
    assert context.answer["document"]["tone"] == [first, second]


@then('the tone reads "{only}"')
def step_tone_one(context, only):
    assert context.answer["document"]["tone"] == [only]


@then('the voice patterns end with "{pattern}"')
def step_patterns(context, pattern):
    assert context.answer["document"]["voicePatterns"][-1] == pattern


@then('the words to avoid are "{first}" then "{second}"')
def step_avoid(context, first, second):
    assert context.answer["document"]["lexicon"]["avoid"] == [first, second]


@then('the audience is "{audience}"')
def step_audience(context, audience):
    assert context.answer["document"]["audience"] == audience


@then("there are no warnings")
def step_no_warnings(context):
    assert context.answer["warnings"] == []


@then("the headline order is the site's")
def step_headline(context):
    assert context.answer["document"]["headline"] == {"order": ["title"]}


@then('the warning "{code}" names the field "{field}"')
def step_warning_field(context, code, field):
    assert [(w["code"], w.get("field")) for w in context.answer["warnings"]] == [(code, field)]


@then("the constraints are the site's alone")
def step_constraints(context):
    assert context.answer["document"]["constraints"] == SITE["constraints"]


@then('the warning "{code}" is given')
def step_warning(context, code):
    assert code in [w["code"] for w in context.answer["warnings"]]


@then("nothing was found and the document is empty")
def step_empty(context):
    assert context.answer["found"] is False and context.answer["document"] == {}


@then("one layer was used, the publication's")
def step_one_layer(context):
    assert [layer["scope"] for layer in context.answer["layers"]] == ["publication"]


def parse_layers(text):
    return text


@then('the source of "{field}" is the publication at version {a:d} and the section at version {b:d}')
def step_source_both(context, field, a, b):
    assert context.answer["fieldSources"][field] == [{"layer": "publication", "version": a}, {"layer": "section", "version": b}]


@then('the source of "{field}" is the section at version {number:d}')
def step_source_section(context, field, number):
    assert context.answer["fieldSources"][field] == [{"layer": "section", "version": number}]


@then('the source of "{field}" is the publication at version {number:d}')
def step_source_publication(context, field, number):
    assert context.answer["fieldSources"][field] == [{"layer": "publication", "version": number}]


@then("every field of the answer has a source")
def step_every_source(context):
    assert set(context.answer["fieldSources"]) == set(context.answer["document"])


@then('the layers list the slugs "{first}" and "{second}" with their content hashes')
def step_layers(context, first, second):
    layers = context.answer["layers"]
    assert [layer["slug"] for layer in layers] == [first, second] and all(layer["contentHash"].startswith("sha256:") for layer in layers)


# --- the order of a save: row, then document -------------------------------------------------------------------------------------------------------

import papyrus_content.guidelines.byline, papyrus_content.guidelines.figure_rules, papyrus_content.guidelines.procedure  # noqa: E402,F401  (register their kinds)


class FailingOnce(FakeFiles):
    """The S3 side whose next upload fails, as a dropped connection would."""

    def __init__(self, backend):
        super().__init__(backend)
        self.fail_next = True

    def put(self, attachment, body):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("Upload failed with status 503")
        return super().put(attachment, body)


@when('an admin saves a minimal "{kind}" document with the reason "{reason}"')
def step_minimal(context, kind, reason):
    context.saved = {"schemaVersion": 1}
    save(context, context.saved, kind=kind, reason=reason)
    assert context.error is None, context.error


@then("the row was created before its document was attached")
def step_row_first(context):
    created = [i for i, w in enumerate(context.backend.writes) if w[0] == "create"]
    assert created, context.backend.writes
    # the fake refuses a file for a missing Item, so a document that is stored proves the order; and no version is left pending
    assert context.backend.attachments and all(row["versionState"] != "pending" for row in context.backend.items)


@then('the "{kind}" guidelines are at version {number:d} with their document attached')
def step_kind_attached(context, kind, number):
    read = context.store.read(kind)
    assert read["reference"]["versionNumber"] == number and read["document"] == context.saved


@when("the upload of a first writing document fails")
def step_upload_fails(context):
    context.backend = FakeBackend()
    context.files = FailingOnce(context.backend)
    context.store = GuidelineStore(context.backend, context.files)
    context.upload_error = None
    try:
        save(context, SITE)
    except RuntimeError as error:
        context.upload_error = error
    context.saved = SITE


@then("the save is refused with the upload's message")
def step_upload_message(context):
    assert context.upload_error is not None and "503" in str(context.upload_error)


@then("the interrupted version is not visible: there are no writing guidelines and no history")
def step_not_visible(context):
    assert context.store.read("writing") is None and context.store.history("writing") == []


@when("the same save is made again")
def step_again(context):
    save(context, SITE)
    assert context.error is None, context.error


@then("exactly one catalog row and one file are stored")
def step_one_and_one(context):
    assert counts(context) == (1, 1), counts(context)
