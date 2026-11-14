"""A publication decides how its terms are translated (features_backend/translation-glossary.feature). Humanus runs for real; no model, no network."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import humanus  # noqa: E402

from papyrus_content.guidelines import GuidelineStore, validate_document  # noqa: E402
from papyrus_content.guidelines.fakes import FakeBackend, FakeFiles  # noqa: E402
from papyrus_content.translation_glossary import Glossary, resolve_glossary, starter_glossary  # noqa: E402


def _faithfulness(glossary: Glossary, source: str, target: str) -> list[dict]:
    request = {"schemaVersion": 1, "content": {"text": target, "format": "markdown", "language": glossary.language},
               "source": {"text": source, "format": "markdown", "language": "en"},
               "glossary": glossary.humanus(glossary.entries_in([source])),
               "pack": humanus.builtin_pack("translation-faithfulness"),
               "options": {"lanes": {"classifier": False, "judge": False}}}
    return humanus.check(request, decision_model=None)["findings"]


@given('a glossary of forty entries for "{language}"')
def step_forty(context, language):
    entries = [{"term": f"term{number}", "translations": [f"término{number}"]} for number in range(38)]
    entries += [{"term": "Congress", "translations": ["Congreso"]}, {"term": "White House", "translations": ["Casa Blanca"]}]
    context.glossary = Glossary.of(language, entries)


@given("a block that contains two of the source terms")
def step_block(context):
    context.block = "The White House wrote to Congress on Monday."


@when("the entries for the block are chosen")
def step_choose(context):
    context.chosen = context.glossary.entries_in([context.block])


@then("exactly those two entries are chosen")
def step_two(context):
    assert [entry["term"] for entry in context.chosen] == ["Congress", "White House"], context.chosen


@given("the Latin American Spanish starter glossary")
def step_es(context):
    context.glossary = starter_glossary("es-419")


@given("the Simplified Chinese starter glossary")
def step_zh(context):
    context.glossary = starter_glossary("zh-Hans")


@when('a block saying "{source}" is translated as "{target}"')
def step_translated(context, source, target):
    context.findings = _faithfulness(context.glossary, source, target)


def _messages(context, policy: str) -> list[str]:
    return [finding["message"] for finding in context.findings if finding["policyId"] == policy]


@then('the faithfulness check reports that "{term}" should be "{form}"')
def step_should_be(context, term, form):
    assert any(term in message and form in message for message in _messages(context, "glossary")), context.findings


@then('it reports that "{term}" should be "{form}"')
def step_also(context, term, form):
    step_should_be(context, term, form)


@then("the faithfulness check reports no glossary finding")
def step_no_glossary(context):
    assert _messages(context, "glossary") == [], context.findings


@then('the faithfulness check reports that "{term}" must stay unchanged')
def step_unchanged(context, term):
    assert any(term in message and "do-not-translate" in message for message in _messages(context, "glossary")), context.findings


@then('the faithfulness check reports that the name "{name}" is missing')
def step_name_missing(context, name):
    assert any(name in message for message in _messages(context, "names")), context.findings


@when('an admin saves a glossary entry for "{term}" with neither translations nor doNotTranslate')
def step_bad_entry(context, term):
    context.problems = validate_document("glossary", {"schemaVersion": 1, "entries": [{"term": term}]})


@then("the document is refused, saying the entry needs either translations or doNotTranslate")
def step_refused(context):
    assert context.problems and "either translations or doNotTranslate" in context.problems[0].message, context.problems


@given('the publication\'s glossary keeps "{term}" unchanged')
def step_publication_keeps(context, term):
    backend = FakeBackend()
    context.store = GuidelineStore(backend, FakeFiles(backend))
    context.store.save("glossary", {"schemaVersion": 1, "entries": [{"term": term, "doNotTranslate": True}]}, expected_current_version_id="none",
                       actor="admin", reason="seed")


@given('the "{language}" glossary renders "{term}" as "{form}"')
def step_overlay(context, language, term, form):
    context.store.save("glossary", {"schemaVersion": 1, "entries": [{"term": term, "translations": [form]}]}, expected_current_version_id="none",
                       actor="admin", reason="seed", language=language)
    context.overlay = (language, term)


@when('the glossary is resolved for "{language}"')
def step_resolve(context, language):
    context.resolved = resolve_glossary(context.store, language)


@then('"{term}" is rendered as "{form}"')
def step_rendered(context, term, form):
    (entry,) = [entry for entry in context.resolved.entries if entry["term"] == term]
    assert entry.get("translations") == [form] and not entry.get("doNotTranslate"), entry


@then("the glossary's version changes when any entry changes")
def step_version(context):
    language, term = context.overlay
    current = context.store.current_row("glossary", language=language)
    context.store.save("glossary", {"schemaVersion": 1, "entries": [{"term": term, "translations": ["Congreso de los Estados Unidos"]}]},
                       expected_current_version_id=current["id"], actor="admin", reason="longer form", language=language)
    assert resolve_glossary(context.store, language).version != context.resolved.version


@then('the "es-419" starter glossary renders "AI" as "IA", "Paris" as "París", "Congress" as "Congreso", "Justice Department" as "Departamento de Justicia" and "North Carolina" as "Carolina del Norte"')
def step_es_starter(context):
    entries = {entry["term"]: entry for entry in starter_glossary("es-419").entries}
    for term, form in (("AI", "IA"), ("Paris", "París"), ("Congress", "Congreso"), ("Justice Department", "Departamento de Justicia"),
                       ("North Carolina", "Carolina del Norte")):
        assert entries[term]["translations"][0] == form, entries[term]


@then('the "zh-Hans" starter glossary renders "Paris" as "巴黎" and keeps "AI" and "abliteration" unchanged')
def step_zh_starter(context):
    entries = {entry["term"]: entry for entry in starter_glossary("zh-Hans").entries}
    assert entries["Paris"]["translations"][0] == "巴黎"
    assert entries["AI"].get("doNotTranslate") and entries["abliteration"].get("doNotTranslate")
