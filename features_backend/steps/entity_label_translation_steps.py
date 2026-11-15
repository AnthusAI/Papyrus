"""features_backend/entity-label-translation.feature: the label procedure with an in-memory site and a scripted model."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.entity_labels.entity_labels_test import ANSWER, Glossary, NAMES, ScriptedModels  # noqa: E402
from papyrus_content.entity_labels.fakes import FakeSite  # noqa: E402
from papyrus_content.entity_labels.keys import name_key  # noqa: E402
from papyrus_content.entity_labels.store import LabelStore  # noqa: E402
from papyrus_content.entity_labels.translate import LabelSource, localize_label  # noqa: E402

NOW = "2026-11-15T12:00:00Z"


def _name(context, language: str, description: str | None = None):
    source = LabelSource("section", "agents", "en", "Agents", description or context.description)
    context.models = ScriptedModels({"Agents": context.answer})
    context.outcome = localize_label(context.site, context.models, source, language, glossary=context.glossary, checker=None, register_notes=[], language_names=NAMES, now=NOW)
    context.row = context.site.tables["EntityLabel"].get(f"section#agents#{language}")


@given('a site with the section "{name}" described as "{description}"')
def step_site(context, name, description):
    context.site, context.description, context.answer, context.glossary = FakeSite(), description, dict(ANSWER), Glossary()


@given('the model names it "{name}"')
def step_model_names(context, name):
    context.answer["name"] = name


@given('another section already has the "{language}" name "{name}"')
def step_other(context, language, name):
    LabelStore(context.site).create({"id": f"section#tools#{language}", "entityKind": "section", "entityId": "tools", "entityKey": "section#tools", "language": language,
                                     "role": "preferred", "text": name, "nameKey": name_key(language, name, None, "section"), "sortKey": f"{language}#preferred#{name.lower()}", "origin": "machine"})


@given('the model finds no equivalent term, saying "{reason}"')
def step_none(context, reason):
    context.answer.update(equivalence="none", reason=reason)


@given('the glossary renders "{term}" as "{rendering}"')
def step_glossary(context, term, rendering):
    context.glossary = Glossary({"term": term, "translations": [rendering]})


@when('the section is named in "{language}"')
def step_named(context, language):
    _name(context, language)


@given('the section was named in "{language}" and a person pinned the wording')
def step_pinned(context, language):
    _name(context, language)
    context.site.tables["EntityLabel"][f"section#agents#{language}"].update(pinned=True, text="Agentes (a person's)")


@when('the section\'s description changes and it is named again in "{language}"')
def step_again(context, language):
    _name(context, language, "Changed words.")


@then('the label "{name}" is current, made by the machine, with exact equivalence')
def step_current(context, name):
    assert context.outcome.state == "current" and context.row["text"] == name and context.row["origin"] == "machine" and context.row["equivalence"] == "exact" and "workKey" not in context.row


@then("naming it again asks the model nothing")
def step_again_nothing(context):
    _name(context, "es-419")
    assert context.outcome.state == "unchanged" and context.models.calls == []


@then('the label is held because "{name}" is already the name of the other section')
def step_collision(context, name):
    assert context.outcome.state == "held" and any(f"{name!r} is already the name of section#tools" in reason for reason in context.outcome.reasons), context.outcome.reasons


@then('the label is in the work list of "{language}" as held')
def step_work(context, language):
    assert [row["id"] for row in LabelStore(context.site).needing_work(language, "held", "section")] == [f"section#agents#{language}"]


@then('the label is held because there is no equivalent term in "{language}"')
def step_no_equivalent(context, language):
    assert context.outcome.state == "held" and context.outcome.reasons == [f"no equivalent term in {language}: no settled term"], context.outcome.reasons


@then('the label "{name}" is current, made from the glossary')
def step_glossary_made(context, name):
    assert context.outcome.state == "current" and context.row["text"] == name and context.row["origin"] == "glossary"


@then("the label stays as the person wrote it and the model was not asked")
def step_kept(context):
    assert context.outcome.state == "pinned" and context.models.calls == [] and context.row["text"] == "Agentes (a person's)"
