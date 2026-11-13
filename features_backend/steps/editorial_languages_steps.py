"""Each language checked against its own rules (features_backend/editorial-languages.feature) and the language overlay of the writing guidelines
(features_backend/guidelines-language-overlay.feature). In-memory stores; the rules lane only; no model, no network."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path

import humanus
from behave import given, then, when
from humanus.packs import builtin_pack

from papyrus_content import editorial_checks as editorial
from papyrus_content.editorial_languages import story_language
from papyrus_content.guidelines.operations_test import ADMIN, EDITOR, door, world


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "editorial-checks"
RULES_ONLY = {"lanes": {"rules": True, "classifier": False}}


class LanguageSiteStore:
    """The editorial models of one site, in memory, with the GraphQL store's contract (JSON fields as strings)."""

    def __init__(self) -> None:
        self.policies: dict[str, dict] = {}
        self.settings: dict | None = None

    def list_policies(self):
        return [dict(record) for record in self.policies.values()]

    def get_settings(self):
        return self.settings

    def put_settings(self, values, *, exists):
        self.settings = {"id": "settings", "settings": json.dumps(values)}

    def list_feedback(self):
        return []

    def create_policy(self, record):
        self.policies[record["id"]] = json.loads(json.dumps(editorial.policy_input(record)))

    def update_policy(self, record):
        self.policies[record["id"]] = json.loads(json.dumps(editorial.policy_input(record)))

    def get_editorial_context(self, section):
        from papyrus_content.editorial_context import build_context

        entries = [{"scope": "publication", "kind": "mission", "text": "Synthetic mission", "source": {"id": "synthetic-mission"}},
                   {"scope": "publication", "kind": "policy", "text": "Synthetic private guidance", "source": {"id": "synthetic-policy"}}]
        return build_context({"key": "synthetic"}, {"sectionId": section}, entries, mode="cloud")


class FakeGenerator:
    def generate(self, **_kwargs):
        return {"options": []}


def _settings(context) -> dict:
    return json.loads(context.store.settings["settings"]) if context.store.settings else {}


def _set_settings(context, **values) -> None:
    context.store.settings = {"id": "settings", "settings": json.dumps({**_settings(context), **values})}


def _policy(key: str, phrase: str) -> dict:
    return {"id": key, "version": 1, "title": key, "guidance": f"Avoid {phrase}.", "severity": "warn", "enabled": True,
            "detectors": [{"id": f"{key}-phrase", "lane": "rules", "kind": "phrase", "phrases": [phrase]}]}


def _add(context, key: str, phrase: str, language: str, scope: str = "publication") -> None:
    context.store.create_policy(editorial.record_from_policy(_policy(key, phrase), scope=scope, language=language, source="test"))


def _check(context, body: str, language: str | None, section: str | None = None) -> None:
    context.services = editorial.Services(store=context.store, decision_model=None, generator=FakeGenerator())
    arguments = {"body": body, "format": "markus", "section": section, **({"language": language} if language is not None else {})}
    context.check_error = None
    try:
        context.check_result = editorial.handle("checkEditorial", arguments, context.services)
    except ValueError as error:
        context.check_error = error
        context.check_result = None


# --- the site ---------------------------------------------------------------------------------------------------------------------------------

@given('a site that writes in "{tags}" with English as its primary language')
def step_site_languages(context, tags):
    context.store = LanguageSiteStore()
    context.generator = FakeGenerator()
    _set_settings(context, **RULES_ONLY, languages={"primary": "en", "enabled": [tag.strip() for tag in tags.split(",")]})


@given("the site's starter rules for every language it writes in")
def step_starter_rules(context):
    context.ensured = editorial.ensure_default_policies(context.store)


@given("the site's settings enable \"{tags}\"")
def step_enable(context, tags):
    _set_settings(context, languages={"primary": "en", "enabled": [tag.strip() for tag in tags.split(",")]})


@given('a language-neutral policy "{key}" that flags "{phrase}"')
def step_neutral_policy(context, key, phrase):
    _add(context, key, phrase, "*")


@given('a Spanish policy "{key}" that flags "{phrase}"')
def step_spanish_policy(context, key, phrase):
    _add(context, key, phrase, "es")


@given('a Latin American Spanish policy "{key}" that flags "{phrase}"')
def step_latin_american_policy(context, key, phrase):
    _add(context, key, phrase, "es-419")


@given('a Chinese policy "{key}" that flags "{phrase}"')
def step_chinese_policy(context, key, phrase):
    _add(context, key, phrase, "zh-Hans")


@given('the section "{section}" has a Chinese policy "{key}" that flags "{phrase}"')
def step_chinese_section_policy(context, key, section, phrase):
    _add(context, key, phrase, "zh-Hans", scope=section)


@given('an older policy "{key}" from the panel with no language')
def step_older_policy(context, key):
    record = editorial.record_from_policy(_policy(key, "game-changing"), scope="publication", language="en", source="custom")
    record.pop("language")
    record["id"] = f"publication#{key}"   # the id a policy was given before policies had a language
    record["version"] = 4
    context.store.policies[record["id"]] = json.loads(json.dumps(editorial.policy_input(record)))
    context.store.policies[record["id"]].pop("language", None)


@given('an older policy "{key}" from the starter pack "{pack}" with no language')
def step_older_starter_policy(context, key, pack):
    policy = next(policy for policy in builtin_pack(pack)["policies"] if policy["id"] == key)
    record = editorial.record_from_policy(policy, scope="publication", language="en", source=f"starter:{pack}")
    record["id"] = f"publication#{key}"
    stored = json.loads(json.dumps(editorial.policy_input(record)))
    stored.pop("language", None)
    # the starter rules of the Background already hold this key for English; an older site had only the older record
    for record_id in [rid for rid, row in context.store.policies.items() if row["policyKey"] == key and row.get("language")]:
        del context.store.policies[record_id]
    context.store.policies[record["id"]] = stored


# --- checks ------------------------------------------------------------------------------------------------------------------------------------

@given("the site's English policies of the regression story, with the rules lane only")
def step_regression_policies(context):
    """What the baseline was recorded with: the ai-writing-tells starter pack (already imported) and one section policy."""
    _add(context, "jargon", "synergy", "en", scope="engineering")
    record = next(row for row in context.store.policies.values() if row["policyKey"] == "jargon")
    record["guidance"] = "Avoid synergy."
    record["severity"] = "info"


@when("the English regression story is checked as a saved Story")
def step_check_regression(context):
    body = (FIXTURES / "english-story.md").read_text(encoding="utf-8")
    item = {"id": "story-v1", "lineageId": "story", "versionNumber": 1, "section": "engineering", "bodyMarkus": body}
    _check(context, body, story_language(item, editorial.settings_from(context.store)), "engineering")
    assert context.check_error is None, context.check_error


@when('a Chinese localization saying "{text}" is checked')
def step_check_chinese(context, text):
    _check(context, text, "zh-Hans")


@when('a Chinese localization saying "{text}" is checked in the section "{section}"')
def step_check_chinese_section(context, text, section):
    _check(context, text, "zh-Hans", section)


@when('English text saying "{text}" is checked')
def step_check_english(context, text):
    context.previous_result = context.check_result if getattr(context, "check_result", None) else None
    _check(context, text, "en")


@when('Spanish text saying "{text}" is checked as "{language}"')
def step_check_spanish(context, text, language):
    _check(context, text, language)


@when('text is checked as "{language}"')
def step_check_as(context, language):
    _check(context, "Some text.", language)


@when("text is checked without a language")
def step_check_without(context):
    _check(context, "Some text.", None)


@then('Humanus was asked to read it as "{language}"')
def step_read_as(context, language):
    request = context.services.last_check_request
    assert request["content"]["language"] == language and request["pack"]["language"] == language, (request["content"].get("language"), request["pack"].get("language"))


@then("the findings are exactly those recorded with Humanus 0.34 before Stories had a language")
def step_same_findings(context):
    before = json.loads((FIXTURES / "english-story-findings-humanus-0.34.json").read_text(encoding="utf-8"))
    after = context.check_result["findings"]
    assert json.dumps(after, sort_keys=True, ensure_ascii=False) == json.dumps(before, sort_keys=True, ensure_ascii=False), (after, before)


@then("only Chinese and language-neutral policies ran")
def step_only_chinese(context):
    sent = {policy["id"] for policy in context.services.last_check_request["pack"]["policies"]}
    rows = list(context.store.policies.values())
    chinese_or_neutral = {row["policyKey"] for row in rows if row["language"] in ("zh-Hans", "*")}
    english_only = {row["policyKey"] for row in rows if row["language"] == "en"} - chinese_or_neutral
    assert sent and sent <= chinese_or_neutral, sent - chinese_or_neutral
    assert english_only and not sent & english_only, sent & english_only


@then('the check result names the language pack "{tag}" and its version')
def step_names_pack(context, tag):
    language = context.check_result["language"]
    assert language["tag"] == tag and language["version"], language
    assert context.check_result["pack"]["version"].startswith(f"{tag}-"), context.check_result["pack"]


@then('both checks have a "{key}" finding')
def step_both(context, key):
    assert key in {f["policyId"] for f in context.previous_result["findings"]}, context.previous_result["findings"]
    assert key in {f["policyId"] for f in context.check_result["findings"]}, context.check_result["findings"]


@then("the findings are, by policy, excerpt and replacement:")
def step_findings_table(context):
    actual = [(f["policyId"], f["excerpt"], f.get("replacement")) for f in context.check_result["findings"]]
    assert actual == [(row["policy"], row["excerpt"], row["replacement"]) for row in context.table], actual


@then('the check is refused and the message names "{name}"')
def step_refused_naming(context, name):
    assert context.check_error is not None and f"{name}" in str(context.check_error), context.check_error


@then('the check is refused because the site does not write in "{tag}"')
def step_refused_not_enabled(context, tag):
    assert context.check_error is not None and f"does not write in {tag} " in str(context.check_error), context.check_error


@then("the check is refused because the language was not given")
def step_refused_language(context):
    assert context.check_error is not None and "never assumed" in str(context.check_error), context.check_error


# --- starter rules and the backfill -------------------------------------------------------------------------------------------------------------

@then("the site has policies from these starter packs, each written for its pack's language:")
def step_starter_languages(context):
    rows = list(context.store.policies.values())
    for row in context.table:
        mine = [policy for policy in rows if policy["source"] == f"starter:{row['pack']}"]
        assert mine and {policy["language"] for policy in mine} == {row["language"]}, (row["pack"], {policy["language"] for policy in mine})
    assert {policy["source"].removeprefix("starter:") for policy in rows} == {row["pack"] for row in context.table}
    context.starter_packs = {row["pack"] for row in context.table}


@then('the starter pack catalog marks those packs as defaults and "{other}" as not')
def step_catalog_defaults(context, other):
    catalog = {pack["name"]: pack for pack in editorial.list_starter_packs({}, editorial.Services(store=context.store))["packs"]}
    defaults = {name for name, pack in catalog.items() if pack["isDefault"]}
    assert defaults == context.starter_packs, defaults
    assert not catalog[other]["isDefault"]


@when("the deploy ensures the default policies")
def step_deploy_ensures(context):
    context.ensured = editorial.ensure_default_policies(context.store)


@then('the policy "{key}" is written for "{language}" and keeps its id and version')
def step_written_kept(context, key, language):
    row = context.store.policies[f"publication#{key}"]
    assert row["language"] == language and row["version"] == 4, row


@then('the starter policy "{key}" is written for "{language}"')
def step_written(context, key, language):
    assert context.store.policies[f"publication#{key}"]["language"] == language


@then("running it again writes no language")
def step_again(context):
    assert editorial.ensure_default_policies(context.store)["policyLanguagesWritten"] == 0


# --- the command line ---------------------------------------------------------------------------------------------------------------------------

@when('an operator checks a "{language}" draft saying "{text}" with papyrus editorial check')
def step_cli_language(context, language, text):
    from papyrus_content.editorial_commands import editorial_check

    pack = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(builtin_pack("ai-writing-tells-zh-hans"), pack, ensure_ascii=False)
    pack.close()
    draft = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    draft.write(text)
    draft.close()
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        editorial_check(["--draft", draft.name, "--pack", pack.name, "--language", language])
    context.cli_result = json.loads(output.getvalue())


@then('the printed result names the language pack "{tag}"')
def step_cli_pack(context, tag):
    assert context.cli_result["language"]["tag"] == tag, context.cli_result["language"]


@then('the printed result has a "{key}" finding')
def step_cli_has(context, key):
    assert key in {f["policyId"] for f in context.cli_result["findings"]}, context.cli_result["findings"]


# --- the writing guidelines' language overlay ---------------------------------------------------------------------------------------------------

def _guard(context, *, section=None, language=None) -> str:
    found = door(context.backend, "guidelinesRead", EDITOR, "guidelines_get",
                 input={"kind": "writing", **({"section": section} if section else {}), **({"language": language} if language else {})})
    return found["result"]["expectedCurrentVersionId"] if found["ok"] else found["error"]["details"]["expectedCurrentVersionId"]


def _save(context, document, *, section=None, language=None, request="r"):
    body = {"kind": "writing", "document": document, "reason": "Change", "expectedCurrentVersionId": _guard(context, section=section, language=language),
            **({"section": section} if section else {}), **({"language": language} if language else {})}
    return door(context.backend, "guidelinesWrite", ADMIN, "guidelines_save", requestId=request, input=body)


def _resolve(context, section, language):
    answer = door(context.backend, "guidelinesRead", EDITOR, "guidelines_resolve", input={"kind": "writing", "section": section, "language": language})
    assert answer["ok"], answer
    context.answer = answer["result"]


@given('the publication\'s writing guidelines set the audience "{audience}", the tone "{tone}" and the binding rule "{rule}"')
def step_publication_guidelines(context, audience, tone, rule):
    context.backend, context.files = world(saved=False)
    context.publication_document = {"schemaVersion": 1, "audience": audience, "tone": [tone], "lexicon": {"avoid": ["synergy"]},
                                    "constraints": [{"id": rule, "text": "No hype."}]}
    assert _save(context, context.publication_document, request="publication")["ok"]


@given('the section "{section}" writing guidelines add the tone "{tone}"')
def step_section_guidelines(context, section, tone):
    assert _save(context, {"schemaVersion": 1, "tone": [tone]}, section=section, request="section")["ok"]


@given('a Chinese overlay adds the tone "{tone}" and avoids the word "{word}"')
def step_chinese_overlay(context, tone, word):
    context.overlay = {"schemaVersion": 1, "tone": [tone], "lexicon": {"avoid": [word]}}
    answer = _save(context, context.overlay, language="zh-Hans", request="overlay")
    assert answer["ok"], answer


@given('the Chinese overlay records the approved Chinese form "{target}" of the organisation "{term}"')
def step_overlay_glossary(context, target, term):
    context.overlay = {**context.overlay, "glossary": [{"term": term, "use": target, "note": "Approved Chinese form; the English name follows in brackets on first mention."}]}
    assert _save(context, context.overlay, language="zh-Hans", request="overlay-glossary")["ok"]


@given('the Chinese overlay also tries to set the binding rule "{rule}"')
def step_overlay_constraint(context, rule):
    context.overlay = {**context.overlay, "constraints": [{"id": rule, "text": "No numbers."}]}
    answer = _save(context, context.overlay, language="zh-Hans", request="overlay-constraint")
    assert answer["ok"], answer


@when('the guidelines are resolved for a Chinese Story in the "{section}" section')
def step_resolve_chinese(context, section):
    _resolve(context, section, "zh-Hans")


@when('the guidelines are resolved for an English Story in the "{section}" section')
def step_resolve_english(context, section):
    _resolve(context, section, "en")


@then('the resolved tone is "{tones}"')
def step_tone(context, tones):
    assert context.answer["document"]["tone"] == [part.strip() for part in tones.split("|")], context.answer["document"]["tone"]


@then('the resolved audience is "{audience}" and the binding rule "{rule}" is there')
def step_audience_rule(context, audience, rule):
    document = context.answer["document"]
    assert document["audience"] == audience and [c["id"] for c in document["constraints"]] == [rule], document


def _layer_names(entries) -> list[str]:
    return [" ".join(part for part in (entry.get("layer") or entry.get("scope"), entry.get("language")) if part) for entry in entries]


@then('the tone came from the layers "{layers}"')
def step_tone_layers(context, layers):
    assert _layer_names(context.answer["fieldSources"]["tone"]) == [part.strip() for part in layers.split(",")], context.answer["fieldSources"]["tone"]


@then("the audience and the binding rule came from the publication alone")
def step_publication_alone(context):
    for field in ("audience", "constraints"):
        assert _layer_names(context.answer["fieldSources"][field]) == ["publication"], context.answer["fieldSources"][field]


@then('the layers used are "{layers}"')
def step_layers(context, layers):
    assert _layer_names(context.answer["layers"]) == [part.strip() for part in layers.split(",")], context.answer["layers"]


@then('the resolved glossary gives "{target}" for "{term}"')
def step_glossary(context, target, term):
    assert [entry["use"] for entry in context.answer["document"].get("glossary") or [] if entry["term"] == term] == [target], context.answer["document"]


@then('the resolved glossary has no entry for "{term}"')
def step_no_glossary(context, term):
    assert term not in [entry["term"] for entry in context.answer["document"].get("glossary") or []]


@then('the binding rules are only "{rule}"')
def step_only_rule(context, rule):
    assert [c["id"] for c in context.answer["document"]["constraints"]] == [rule]


def _drawn(context, language):
    return next(row for row in context.backend.policies.rows if row["policyKey"] == "avoid-lexicon" and row["scope"] == "publication" and row["language"] == language)


def _words(row) -> list[str]:
    return [phrase for detector in row["detectors"] for phrase in (detector.get("phrases") or [])]


@then('a publication check "{key}" written for "{language}" detects "{word}" with the source "{source}"')
def step_drawn_chinese(context, key, language, word, source):
    row = _drawn(context, language)
    assert row["policyKey"] == key and word in _words(row) and row["source"] == source, row


@then('the English check "{key}" still detects only "{word}"')
def step_drawn_english(context, key, word):
    assert _words(_drawn(context, "en")) == [word]


@then('checking Chinese text "{chinese}" finds "{word}" and checking English text "{english}" does not run the Chinese check')
def step_drawn_checks(context, chinese, word, english):
    rows = [{**row, "detectors": json.dumps(row["detectors"])} for row in context.backend.policies.rows]
    for language, text in (("zh-Hans", chinese), ("en", english)):
        pack = editorial.compose_pack(rows, None, {}, language)
        result = humanus.check({"schemaVersion": 1, "content": {"format": "markus", "text": text, "language": language}, "pack": pack,
                                "options": {"lanes": {"rules": True, "classifier": False}}})
        excerpts = [f["excerpt"] for f in result["findings"] if f["policyId"] == "avoid-lexicon"]
        if language == "zh-Hans":
            assert excerpts == [word], result["findings"]
        else:
            english = next(policy for policy in pack["policies"] if policy["id"] == "avoid-lexicon")
            assert word not in excerpts and _words(english) == ["synergy"], (excerpts, english)


@when('an admin reads the writing guidelines overlay for "{tag}"')
def step_read_overlay(context, tag):
    context.read_answer = door(context.backend, "guidelinesRead", EDITOR, "guidelines_get", input={"kind": "writing", "language": tag})


@then('it is the overlay stored under the slug "{slug}"')
def step_overlay_slug(context, slug):
    assert context.read_answer["ok"], context.read_answer
    result = context.read_answer["result"]
    row = next(item for item in context.backend.items if item["id"] == result["itemId"])
    assert row["slug"] == slug and result["language"] == "zh-Hans" and result["document"] == context.overlay, (row["slug"], result)


@when('an admin saves a writing guidelines overlay for "{tag}"')
def step_save_unknown(context, tag):
    body = {"kind": "writing", "language": tag, "document": {"schemaVersion": 1, "tone": ["Formal."]}, "reason": "Change", "expectedCurrentVersionId": "none"}
    context.save_answer = door(context.backend, "guidelinesWrite", ADMIN, "guidelines_save", requestId="unknown", input=body)


@then('the save is refused as invalid input naming "{tag}"')
def step_refused_unknown(context, tag):
    answer = context.save_answer
    assert not answer["ok"] and answer["error"]["code"] == "invalid_input" and tag in answer["error"]["message"], answer


# --- the language pack version is part of the pack version --------------------------------------------------------------------------------------

@when("the English pack is composed under the installed Humanus English language pack")
def step_compose_installed(context):
    context.pack_versions = [editorial.compose_pack(context.store.list_policies(), None, {}, "en")["version"]]


@when("the English pack is composed again after Humanus's English language pack changes version")
def step_compose_changed(context):
    from dataclasses import replace
    from unittest import mock

    real = humanus.resolve_language

    def newer(tag):
        language = real(tag)
        return replace(language, version=language.version + "-next") if language.tag == "en" else language

    with mock.patch.object(humanus, "resolve_language", newer):
        context.pack_versions.append(editorial.compose_pack(context.store.list_policies(), None, {}, "en")["version"])


@then("the two pack versions differ")
def step_versions_differ(context):
    first, second = context.pack_versions
    assert first != second and first.startswith("en-publication-") and second.startswith("en-publication-"), context.pack_versions
