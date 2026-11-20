"""Writing guidelines as guideline files in the cloud, and the one-time conversion from JSON (features_backend/guidelines-cloud-*.feature). An in-memory backend and
files that fail on any table scan; no network, no live site."""
from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.guidelines import GuidelineStore, field_files, resolve_guidelines  # noqa: E402
from papyrus_content.guidelines import files as guideline_files  # noqa: E402
from papyrus_content.guidelines import convert_v1  # noqa: E402
from papyrus_content.guidelines.layering import lay_over  # noqa: E402
from papyrus_content.images.handlers import Caller  # noqa: E402
from papyrus_content.guidelines.document import digest  # noqa: E402
from papyrus_content.guidelines.fakes import FakeBackend, FakeFiles  # noqa: E402
from papyrus_content.guidelines.handlers import with_client  # noqa: E402
from papyrus_content.guidelines.operations_test import ADMIN, door, read, run, save, world  # noqa: E402
from papyrus_content.guidelines.store import ROLE  # noqa: E402
from papyrus_content.model_attachments import build_json_model_payload_attachment, semantic_version_key  # noqa: E402

WORDS = {"tone": ["Warm."], "voicePatterns": ["Opens plainly."], "editorialAim": "Help readers decide.", "bodyMarkus": "Write plainly.\n\nCut every extra word.",
         "lexicon": {"prefer": ["inspect"], "avoid": ["synergy"]}, "glossary": [{"term": "Papyrus", "use": "the newsroom", "avoid": ["PPY"]}],
         "headline": {"when": "afterBody", "order": ["title", "subtitle"]}, "constraints": [{"id": "no-hype", "text": "No hype."}], "voice": {"name": "House"}}


# --- fixtures --------------------------------------------------------------------------------------------------------------------------------------

def rule_text(name, *, severity="error", avoid=None, pattern=None, max_length=None, body="Say it plainly.", scope="publication", language=None, kind="writing", extra=None, uid=None):
    lines = [f"id: urn:uuid:{uid or uuid.uuid5(uuid.NAMESPACE_URL, 'https://example.org/' + name)}", "type: papyrus:Guideline", f"name: {name}", f"description: The rule {name}.",
             f"kind: {kind}", f"scope: {scope}", f"severity: {severity}"]
    lines += ([f"language: {language}"] if language else []) + ([f"avoid: {json.dumps(avoid)}"] if avoid else []) + ([f"pattern: {json.dumps(pattern)}"] if pattern else [])
    lines += ([f"maxLength: {max_length}"] if max_length else []) + (extra or [])
    return "---\n" + "\n".join(lines) + "\n---\n" + body + "\n"


def tone_files(tone, *, section=None):
    slug = "editorial-doctrine-writing" if not section else f"desk-doctrine-{section}-writing"
    return field_files.files_from_document({"schemaVersion": 2, "tone": [tone]}, slug=slug, section=section)


def fresh(context):
    context.backend, context.files = world(saved=False)
    context.store = GuidelineStore(context.backend, context.files)
    context.folder = None
    context.error = None
    context.answer = None
    context.status = None


def write_folder(context, files):
    context.tmp = getattr(context, "tmp", None) or tempfile.TemporaryDirectory()
    folder = Path(context.tmp.name) / f"set-{len(list(Path(context.tmp.name).iterdir()))}"
    folder.mkdir()
    for path, text in files.items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(text.encode("utf-8"))
    return folder


def guard_of(context, section=None, language=None):
    found = read(context.backend, **({"section": section} if section else {}), **({"language": language} if language else {}))
    return found["result"]["expectedCurrentVersionId"] if found["ok"] else found["error"]["details"]["expectedCurrentVersionId"]


def save_folder(context, folder, *, reason="Files", section=None, guard=None):
    argv = ["save", "--kind", "writing", "--dir", str(folder), "--reason", reason, "--expected-current-version-id", guard or guard_of(context, section)]
    argv += ["--section", section] if section else []
    context.status, context.answer = run(context.backend, context.files, argv)
    return context.answer


def names_of(context):
    return sorted({a["sortKey"] for a in context.backend.attachments})


def policy(context, scoped_key):
    scope, key = scoped_key.rsplit("#", 1)
    return next((row for row in context.backend.policies.rows if (row["scope"], row["policyKey"]) == (scope, key)), None)


def resolved(context, section=None, language=None):
    return resolve_guidelines(GuidelineStore(context.backend, context.files), "writing", section, language)


# --- save and export -------------------------------------------------------------------------------------------------------------------------------

@given("a site with no writing guidelines yet")
def step_site(context):
    fresh(context)


@given('a folder with the tone "{tone}" and the rule "{name}" at severity {severity} that avoids "{word}"')
def step_folder(context, tone, name, severity, word):
    context.files_in = {**tone_files(tone), f"{name}/GUIDELINE.md": rule_text(name, severity=severity, avoid=[word])}
    context.folder = write_folder(context, context.files_in)


@given("the folder is saved as the first version")
def step_saved(context):
    assert save_folder(context, context.folder, guard="none")["ok"], context.answer


@when('an admin saves the folder with the reason "{reason}"')
def step_save(context, reason):
    context.before = (len(context.backend.items), len(context.backend.attachments))
    save_folder(context, context.folder, reason=reason, guard="none")


@when('an admin saves a changed folder naming "none" as the version it replaces')
def step_stale(context):
    context.before = (len(context.backend.items), len(context.backend.attachments))
    folder = write_folder(context, {**context.files_in, "plain-claims/GUIDELINE.md": rule_text("plain-claims", avoid=["arguably"])})
    save_folder(context, folder, guard="none")


@when("an admin saves the same folder again naming the current version")
def step_same(context):
    save_folder(context, context.folder)
    assert context.answer["ok"] and context.answer["result"].get("unchanged"), context.answer


@then("the writing guidelines are at version {number:d} with one stored file for each file of the folder")
def step_version_files(context, number):
    assert context.answer["ok"] and context.answer["result"]["versionNumber"] == number, context.answer
    assert names_of(context) == sorted(context.files_in)


@then("exporting the writing guidelines to a new folder gives every file byte for byte as it was in the folder")
def step_export(context):
    target = Path(context.tmp.name) / "exported"
    status, answer = run(context.backend, context.files, ["export", "--kind", "writing", "--dir", str(target)])
    assert status == 0 and answer["ok"], answer
    exported = {path.relative_to(target).as_posix(): path.read_bytes() for path in target.rglob("*") if path.is_file()}
    assert exported == {path: text.encode("utf-8") for path, text in context.files_in.items()}


@then("the catalog row holds the hash over the set and no text")
def step_row(context):
    row = context.backend.items[0]
    assert row["contentHash"] == field_files.set_digest(context.files_in) and row["bodyMarkus"] == "" and row["body"] == [] and set(json.loads(row["metadata"])) <= {"savedBy"}


@then("the save of the folder is refused as stale")
def step_folder_refused_stale(context):
    assert not context.answer["ok"] and context.answer["error"]["code"] == "stale_version", context.answer


@then("the folder's writing guidelines are still at version {number:d}")
def step_folder_still(context, number):
    assert context.store.read("writing")["reference"]["versionNumber"] == number
    assert len(context.backend.items) == number


# --- refused sets ---------------------------------------------------------------------------------------------------------------------------------

@given("the folder has {problem}")
def step_problem(context, problem):
    files = dict(context.files_in)
    if problem == 'a rule with the unknown key "voice"':
        files["plain-claims/GUIDELINE.md"] = rule_text("plain-claims", extra=["voice: House"])
    elif problem == "a rule written for the scope section/news":
        files["plain-claims/GUIDELINE.md"] = rule_text("plain-claims", scope="section/news")
    elif problem == "a rule written for the language es":
        files["plain-claims/GUIDELINE.md"] = rule_text("plain-claims", language="es")
    elif problem == "a rule of the kind image":
        files["plain-claims/GUIDELINE.md"] = rule_text("plain-claims", kind="video")
    elif problem == "a tone file whose body is not a list of lines":
        files["tone/GUIDELINE.md"] = files["tone/GUIDELINE.md"].split("---\n")[0] + "---\n" + files["tone/GUIDELINE.md"].split("---\n")[1] + "---\nWarm, not a list.\n"
    elif problem == "a tone file with the severity error":
        files["tone/GUIDELINE.md"] = files["tone/GUIDELINE.md"].replace('severity: "guidance"', 'severity: "error"')
    elif problem == "a second rule with the id of the first":
        files["twin/GUIDELINE.md"] = rule_text("twin", uid=str(uuid.uuid5(uuid.NAMESPACE_URL, "https://example.org/plain-claims")))
    elif problem == "a file outside any guideline folder":
        files["stray.md"] = "Not in a folder.\n"
    else:
        raise AssertionError(problem)
    context.folder = write_folder(context, files)


@then('the save is refused naming the guideline "{guideline}" and the code "{code}"')
def step_refused(context, guideline, code):
    assert not context.answer["ok"], context.answer
    problems = context.answer["error"]["details"]["problems"]
    assert any(item.get("guideline") == guideline and item["code"] == code for item in problems), problems


@then("nothing is stored from the folder")
def step_nothing(context):
    assert (len(context.backend.items), len(context.backend.attachments)) == context.before


# --- structured fields -----------------------------------------------------------------------------------------------------------------------------

def console_save(context, document, section=None):
    guard = guard_of(context, section)
    context.answer = save(context.backend, ADMIN, {"schemaVersion": 2, **document}, section=section, guard=guard, reason="Console", request=f"c{len(context.backend.items)}")
    assert context.answer["ok"], context.answer
    return context.answer


@when("an admin saves the structured field {field} through the console")
def step_field(context, field):
    context.field = field
    console_save(context, {field: copy.deepcopy(WORDS[field])})


@when('an admin changes the structured tone to "{tone}" through the console')
def step_tone(context, tone):
    console_save(context, {"tone": [tone]})


@then('the stored files include "{path}" with the severity guidance')
def step_has_file(context, path):
    files = context.store.read("writing")["files"]
    assert path in files, sorted(files)
    assert guideline_files.parse_text(path.split("/")[0], files[path])[0].severity == "guidance"


@then("reading the writing guidelines gives the field {field} exactly as it was saved")
def step_field_back(context, field):
    assert context.store.read("writing")["document"][field] == WORDS[field]


@then("the writing guidelines are at version {number:d}")
def step_at(context, number):
    assert context.store.read("writing")["reference"]["versionNumber"] == number


@then('the rule file "{name}" is stored exactly as it was')
def step_rule_same(context, name):
    assert context.store.read("writing")["files"][f"{name}/GUIDELINE.md"] == context.files_in[f"{name}/GUIDELINE.md"]


@then('the stored tone reads "{tone}"')
def step_tone_reads(context, tone):
    assert context.store.read("writing")["document"]["tone"] == [tone]


@when('an admin saves a folder for the section "{section}" with the tone "{tone}"')
def step_section_folder(context, section, tone):
    folder = write_folder(context, tone_files(tone, section=section))
    assert save_folder(context, folder, section=section, guard="none")["ok"], context.answer


@then('the section "{section}" has its own writing guidelines at version {number:d}')
def step_section_has(context, section, number):
    assert context.store.read("writing", section)["reference"]["versionNumber"] == number


@then("the publication's writing guidelines are still at version {number:d}")
def step_pub_still(context, number):
    assert context.store.read("writing")["reference"]["versionNumber"] == number


# --- layering --------------------------------------------------------------------------------------------------------------------------------------

@given('the site\'s writing guidelines are saved from a folder with the rule "{name}" at severity {severity} that avoids "{word}"')
def step_site_rule(context, name, severity, word):
    context.files_in = {**tone_files("Warm."), f"{name}/GUIDELINE.md": rule_text(name, severity=severity, avoid=[word])}
    assert save_folder(context, write_folder(context, context.files_in), guard="none")["ok"], context.answer


def section_files(section, rules):
    slug = f"desk-doctrine-{section}-writing"
    files = field_files.files_from_document({"schemaVersion": 2, "tone": ["Brisk."]}, slug=slug, section=section)
    for name, kwargs in rules.items():
        files[f"{name}/GUIDELINE.md"] = rule_text(name, scope=f"section/{section}", **kwargs)
    return files


@given('the section "{section}" saves a folder with the rule "{name}" at severity {severity} limited to {limit:d} characters')
def step_section_limit(context, section, name, severity, limit):
    assert save_folder(context, write_folder(context, section_files(section, {name: {"severity": severity, "max_length": limit}})), section=section, guard="none")["ok"], context.answer


@given('the section "{section}" saves a folder with the rule "{name}" at severity {severity} that avoids "{word}"')
def step_section_avoid(context, section, name, severity, word):
    assert save_folder(context, write_folder(context, section_files(section, {name: {"severity": severity, "avoid": [word]}})), section=section, guard="none")["ok"], context.answer


@given('the section "{section}" saves the structured fields tone "{tone}" and avoids "{word}"')
def step_section_fields(context, section, tone, word):
    console_save(context, {"tone": [tone], "lexicon": {"avoid": [word]}}, section)


@when('the rule files and fields are resolved for the section "{section}"')
def step_resolve(context, section):
    context.resolved = resolved(context, section)


@then("the resolved rule files are {listing}")
def step_rule_files(context, listing):
    expected = [(name, layer) for name, layer in (part.split(" from the ") for part in listing.replace('"', "").replace(" then ", "|").split("|"))]
    got = [(item["name"], item["layer"]) for item in context.resolved["document"]["guidelineFiles"]]
    assert got == expected, got


@then('the rule "{name}" has the severity {severity}')
def step_rule_severity(context, name, severity):
    assert next(item for item in context.resolved["document"]["guidelineFiles"] if item["name"] == name)["severity"] == severity


@then('the resolved answer gives the warning "{code}"')
def step_warning(context, code):
    assert code in {warning["code"] for warning in context.resolved["warnings"]}, context.resolved["warnings"]


@then('the words to avoid include "{word}"')
def step_avoid(context, word):
    assert word in context.resolved["document"]["lexicon"]["avoid"]


# --- derived checks --------------------------------------------------------------------------------------------------------------------------------

@given("a site with no writing guidelines and with no editorial checks yet")
def step_no_checks(context):
    fresh(context)


def rules_folder(context, rules):
    files = {**tone_files("Warm."), **{f"{name}/GUIDELINE.md": rule_text(name, **kwargs) for name, kwargs in rules.items()}}
    return write_folder(context, files)


def save_rules(context, rules):
    context.writes_before = len(context.backend.policies.writes)
    context.last_folder = rules_folder(context, rules)
    context.answer = save_folder(context, context.last_folder, guard=guard_of(context))
    assert context.answer["ok"], context.answer


@when('an admin saves a folder with the rule "plain-claims" at severity error that avoids "we believe" and the rule "short-leads" at severity warn with a pattern')
@given('an admin saved a folder with the rule "plain-claims" at severity error that avoids "we believe" and the rule "short-leads" at severity warn with a pattern')
def step_two_rules(context):
    save_rules(context, {"plain-claims": {"avoid": ["we believe"]}, "short-leads": {"severity": "warn", "pattern": ["^In today's"]}})


@when('an admin saves a folder with the rule "tone-notes" at severity guidance that avoids "arguably" and the rule "say-it-plainly" at severity error with only prose')
def step_guidance_prose(context):
    save_rules(context, {"tone-notes": {"severity": "guidance", "avoid": ["arguably"]}, "say-it-plainly": {"body": "Say it plainly."}})


@when('an admin saves a folder with the rule "plain-claims" at severity error that avoids "we believe"')
def step_one_rule(context):
    save_rules(context, {"plain-claims": {"avoid": ["we believe"]}})


@when('an admin saves a folder with only the rule "short-leads" at severity warn with a pattern')
def step_only_short(context):
    save_rules(context, {"short-leads": {"severity": "warn", "pattern": ["^In today's"]}})


@when('an admin saves the structured lexicon avoiding "{word}" through the console')
def step_lexicon(context, word):
    console_save(context, {"lexicon": {"avoid": [word]}})


@then('the check "{key}" exists with severity {severity} and the phrase "{phrase}"')
def step_check_phrase(context, key, severity, phrase):
    row = policy(context, key)
    assert row and row["severity"] == severity and phrase in [p for d in row["detectors"] for p in d.get("phrases", [])], row


@then('the check "{key}" exists with severity {severity} and a pattern detector')
def step_check_pattern(context, key, severity):
    row = policy(context, key)
    assert row and row["severity"] == severity and any(d["kind"] == "regex" for d in row["detectors"]), row


@then('the check "{key}" exists with no detector')
def step_check_none(context, key):
    row = policy(context, key)
    assert row and row["detectors"] == [] and row["severity"] == "error", row


@then('there is no check "{key}"')
def step_no_check(context, key):
    assert policy(context, key) is None


@then("both checks name the writing guidelines of the site as their source")
def step_source(context):
    for key in ("publication#guideline-plain-claims", "publication#guideline-short-leads"):
        assert policy(context, key)["source"].startswith("writing-guidelines:editorial-doctrine-writing:v"), policy(context, key)


@given('a hand-written check "{key}" for the publication')
def step_hand_written(context, key):
    context.hand = {"id": f"publication#en#{key}", "policyKey": key, "scope": "publication", "language": "en", "version": 1, "title": "Mine", "guidance": "Mine.",
                    "severity": "error", "enabled": True, "detectors": [], "source": "custom"}
    context.backend.policies.rows.append(copy.deepcopy(context.hand))


@then("the hand-written check is exactly as it was")
def step_hand_same(context):
    assert next(row for row in context.backend.policies.rows if row["id"] == context.hand["id"]) == context.hand


@then("a diff of the same folder lists the check as skipped because it is not drawn from these guidelines")
def step_skipped(context):
    status, answer = run(context.backend, context.files, ["diff", "--kind", "writing", "--dir", str(context.last_folder)])
    plan = answer["result"]["policyPlan"]
    assert any(step["policy"] == "guideline-plain-claims" and step["action"] == "skipped" for step in plan), plan


@then('the check "{key}" is disabled')
def step_disabled(context, key):
    assert policy(context, key)["enabled"] is False


@then('the check "{key}" is enabled')
def step_enabled(context, key):
    assert policy(context, key)["enabled"] is True


# --- the conversion --------------------------------------------------------------------------------------------------------------------------------

LEGACY = {
    None: {"schemaVersion": 1, "voice": {"name": "House"}, "audience": "General readers", "tone": ["Warm."], "voicePatterns": ["Opens plainly."],
           "lexicon": {"prefer": ["inspect"], "avoid": ["synergy"]}, "glossary": [{"term": "Papyrus", "use": "the newsroom", "avoid": ["PPY"]}],
           "headline": {"when": "afterBody", "order": ["title", "subtitle"]}, "constraints": [{"id": "no-hype", "text": "No hype."}], "locked": ["headline"],
           "bodyMarkus": "Write plainly.\n\nCut every extra word.", "density": {"minWords": 400, "minLexicalDensity": 0.45}, "rules": {"bannedPhrases": ["this article"]}},
    "news": {"schemaVersion": 1, "tone": ["Brisk."], "lexicon": {"avoid": ["leverage"]}, "audience": "Engineers"},
    "es": {"schemaVersion": 1, "tone": ["Formal."], "register": "usted", "lexicon": {"avoid": ["sinergia"]}},
}


def put_legacy(context, document, section=None, language=None):
    """A version saved the way the JSON shape was saved: the catalog row, then one JSON document attached to it. Test fixture only; the product no longer writes this."""
    from papyrus_content.guidelines.document import slug_for
    from papyrus_content.guidelines.store import next_record

    backend = context.backend
    slug = slug_for("writing", section, language)
    versions = sorted([row for row in backend.items if row["slug"] == slug], key=lambda row: row["versionNumber"], reverse=True)
    record = next_record("writing", section, versions, digest(document), actor="Ada Admin", reason="Legacy", now="2026-11-01T00:00:00Z", language=language)
    for row in versions:
        row["versionState"] = "superseded"
    backend.create_record("Item", record)
    entry = build_json_model_payload_attachment({"ownerKind": "item", "ownerId": record["id"], "ownerLineageId": record["lineageId"], "ownerVersionNumber": record["versionNumber"],
                                                 "ownerVersionKey": semantic_version_key("item", record["id"]), "role": ROLE, "sortKey": "document", "filename": "guidelines.json",
                                                 "content": document, "now": "2026-11-01T00:00:00Z"})
    context.files.put(entry["attachment"], entry["body"])


@given('a site whose writing guidelines are still JSON documents for the publication, the section "news" and the language "es"')
def step_legacy(context):
    fresh(context)
    put_legacy(context, LEGACY[None])
    put_legacy(context, LEGACY["news"], "news")
    put_legacy(context, LEGACY["es"], None, "es")
    layers = lambda *overlays: lay_over("writing", LEGACY[None], 1, [(doc, {"layer": layer, "version": 1}) for doc, layer in overlays])[0]   # noqa: E731
    context.expected = {"publication": strip(LEGACY[None]), "news": layers((LEGACY["news"], "section")), "es": layers((LEGACY["es"], "language"))}


def strip(document):
    return {key: value for key, value in document.items() if key != "schemaVersion"}


def convert(context, *, apply, admin=True):
    caller = Caller(kind="person", subject="Ada Admin" if admin else "Edie Editor", is_admin=admin)
    context.before = (len(context.backend.items), len(context.backend.attachments))
    if apply and not (caller.is_admin and caller.subject):
        context.refusal, context.results = "not_authorized", []
        return
    context.refusal = None
    context.results = convert_v1.convert_site(context.backend, context.files, sections=["news"], languages=["es"], apply=apply, actor=caller.subject)


def state_of(context, section=None, language=None):
    return next(item for item in context.results if item.get("section") == section and item.get("language") == language)


@when("the conversion is run without --apply")
def step_dry(context):
    convert(context, apply=False)


@when("the conversion is run with --apply by an admin")
@given("the conversion has been applied")
def step_apply(context):
    convert(context, apply=True)


@when("the conversion is run with --apply by an editor")
def step_editor(context):
    convert(context, apply=True, admin=False)


@then('it reports the publication, the section "news" and the language "es" as ready with the resolved result unchanged')
def step_ready(context):
    for section, language in ((None, None), ("news", None), (None, "es")):
        found = state_of(context, section, language)
        assert found["state"] == "ready" and found["resolvedUnchanged"] is True, found


@then("the conversion stored nothing new")
def step_nothing_new(context):
    assert (len(context.backend.items), len(context.backend.attachments)) == context.before


@then("it reports each lineage as converted")
def step_converted(context):
    assert {item["state"] for item in context.results} == {"converted"} and len(context.results) == 3, context.results


@then("it reports each lineage as already files")
def step_already(context):
    assert {item["state"] for item in context.results} == {"already_files"} and len(context.results) == 3, context.results


@then("each lineage is at version 2 and is stored as files")
def step_v2(context):
    store = GuidelineStore(context.backend, context.files)
    for section, language in ((None, None), ("news", None), (None, "es")):
        found = store.read("writing", section, language=language)
        assert found["reference"]["versionNumber"] == 2 and found["files"], (section, language)


@then('the guidelines resolved for the section "news" and for the language "es" are the same documents as before')
def step_same_resolved(context):
    without_rules = lambda answer: {k: v for k, v in answer["document"].items() if k != "guidelineFiles"}   # noqa: E731
    assert without_rules(resolved(context)) == context.expected["publication"]
    assert without_rules(resolved(context, "news")) == context.expected["news"]
    assert without_rules(resolved(context, None, "es")) == context.expected["es"]


@then("it is refused as not authorised and nothing is stored")
def step_unauthorised(context):
    assert context.refusal == "not_authorized" and (len(context.backend.items), len(context.backend.attachments)) == context.before


@given("the publication's JSON document has a body with Windows line endings")
def step_spaces(context):
    put_legacy(context, {**LEGACY[None], "bodyMarkus": "Write plainly.\r\nCut every extra word."})


@then('the publication is reported as refused naming the field "{field}"')
def step_refused_field(context, field):
    found = state_of(context)
    assert found["state"] == "refused" and any(field in reason for reason in found["reasons"]), found


@then("the publication's current version is still its JSON document at version {number:d}")
def step_still_json(context, number):
    from papyrus_content.guidelines.document import GuidelineError

    store = GuidelineStore(context.backend, context.files)
    current = store.current_row("writing")
    assert int(current["versionNumber"]) == number
    try:
        store._set_of(current)
    except GuidelineError as error:
        assert error.code == "legacy_version"
    else:
        raise AssertionError("the publication was converted")


@when("version 1 of the publication's writing guidelines is read")
def step_read_old(context):
    context.old = read(context.backend, version=1)


@then("it is refused as saved before guidelines became files")
def step_old_refused(context):
    assert not context.old["ok"] and "before guidelines became files" in context.old["error"]["message"], context.old


# --- a rule scoped to a channel (features_backend/guidelines/guidelines-channel-layering.feature, PPY-9c6b89) -----------------------------------------------------

@given('the site\'s writing guidelines also hold the rule "{name}" scoped to the channel "{channel}" at severity {severity} limited to {limit:d} characters')
def step_site_channel_rule(context, name, channel, severity, limit):
    context.files_in = {**context.files_in, f"{name}/GUIDELINE.md": rule_text(name, scope=f"channel/{channel}", severity=severity, max_length=limit)}
    assert save_folder(context, write_folder(context, context.files_in), guard=context.store.read("writing")["row"]["id"])["ok"], context.answer


@given('the section "{section}" saves a folder with the channel rule "{name}" for "{channel}" at severity {severity} limited to {limit:d} characters')
def step_section_channel_rule(context, section, name, channel, severity, limit):
    files = section_files(section, {})
    files[f"{name}/GUIDELINE.md"] = rule_text(name, scope=f"channel/{channel}", severity=severity, max_length=limit)
    assert save_folder(context, write_folder(context, files), section=section, guard="none")["ok"], context.answer


@when('the rule files and fields are resolved for the channel "{channel}"')
def step_resolve_channel(context, channel):
    context.resolved = resolve_guidelines(GuidelineStore(context.backend, context.files), "writing", None, None, channel)


@when("the rule files and fields are resolved for no channel")
def step_resolve_no_channel(context):
    context.resolved = resolve_guidelines(GuidelineStore(context.backend, context.files), "writing", None, None, None)


@when('the rule files and fields are resolved on the channel "{channel}" for the section "{section}"')
def step_resolve_section_channel(context, channel, section):
    context.resolved = resolve_guidelines(GuidelineStore(context.backend, context.files), "writing", section, None, channel)


@then('the resolved answer is for the channel "{channel}"')
def step_answer_channel(context, channel):
    assert context.resolved["channel"] == channel


@when('an admin saves a set whose tone file is scoped to the channel "{channel}"')
def step_tone_in_channel(context, channel):
    files = tone_files("Warm.")
    key = next(path for path in files if path.startswith("tone/"))
    files[key] = files[key].replace('scope: "publication"', f'scope: "channel/{channel}"')
    context.answer = save_folder(context, write_folder(context, files), guard=context.store.read("writing")["row"]["id"])


@then('the guideline save is refused saying "{text}"')
def step_save_refused_saying(context, text):
    assert context.answer["ok"] is False and text in json.dumps(context.answer), context.answer


@then('the writing text for the drafter names the rule "{named}" and not the rule "{other}"')
def step_drafter_text(context, named, other):
    from papyrus_content.guidelines.agent_text import writing_text

    text = writing_text(context.resolved["document"])
    assert f"- {named} (" in text and f"- {other} (" not in text, text
