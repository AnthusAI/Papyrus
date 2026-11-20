"""A translated page says what it is, and never claims AI for copy a person wrote (features_backend/translation-notice-kind.feature).

Machine translations come from the scripted run of story_localize_steps.py, imported ones from the real ``stories import-translation`` of
translation_import_steps.py; both are published through the real ``publish_item`` and projected by the real standard projector on the synthetic site of
language_serving_steps.py. Everything runs on the in-memory fake backend; no model, network or AWS."""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from features_backend.steps.translation_publishing_steps import ENGLISH, PERSON, SPANISH, _ld, _site, _text, _translation  # noqa: E402
from papyrus_content.projection.engine import project  # noqa: E402
from papyrus_content.publishing import publish_item  # noqa: E402

STORY = "story-waymo"
ENGLISH_URL = "https://machines.example.test/articles/waymo-crashes-fall/"


def _version(context, language: str) -> dict:
    lineage = f"{STORY}--{language}"
    versions = sorted((row for row in context.client.tables["Item"].values() if row.get("lineageId") == lineage), key=lambda row: row["versionNumber"])
    assert versions, f"no {language} translation was saved"
    return versions[-1]


def _publish(context, language: str) -> None:
    version = _version(context, language)
    publish_item(context.client, version["id"], actor=PERSON, by_person=PERSON)
    context.draw_error = None
    try:
        report = project(_site(context).context, version["id"])
    except ValueError as error:   # the projection refuses a page it cannot say truthfully; the scenario reads the refusal
        context.draw_error = str(error)
        return
    context.draw_error = "; ".join(str(error) for error in report.errors) if not report.ok else None


def _chinese_page(context) -> str:
    keys = [key for key in _site(context).keys() if re.fullmatch(r"zh/articles/[^/]+/index\.html", key)]
    assert len(keys) == 1, keys
    return keys[0]


def _twin(context, prefix: str) -> str:
    key = next(key for key in _site(context).keys() if key.startswith(f"{prefix}/articles/") and key.endswith(".md") and key != f"{prefix}/articles/index.md")
    return _text(context, key)


@given("the copy has the two paragraphs the site shows and no picture")
def step_copy_without_picture(context):
    context.copy["blocks"] = context.copy["blocks"][:2]


@when('a person publishes the "{language}" translation')
def step_publish_language(context, language):
    _publish(context, language)


def _line(html_text: str) -> str:
    lines = re.findall(r'<p class="markus-translation">.*?</p>', html_text)
    assert len(lines) == 1, lines
    return lines[0]


def _link(words: str, hreflang: str = "en") -> str:
    return f'<a href="/articles/waymo-crashes-fall/" hreflang="{hreflang}">{words}</a>'


@then('the Spanish page says "{line}" and links the English page to its "{words}"')
def step_spanish_line(context, line, words):
    assert context.draw_error is None, context.draw_error
    assert _line(_text(context, SPANISH)) == f'<p class="markus-translation">{line} {_link(words)}</p>', _line(_text(context, SPANISH))


@then('the Spanish page\'s translation line is only the link to the English page, "{words}"')
def step_spanish_only_link(context, words):
    assert context.draw_error is None, context.draw_error
    assert _line(_text(context, SPANISH)) == f'<p class="markus-translation">{_link(words)}</p>', _line(_text(context, SPANISH))


@then('the Chinese page\'s translation line is only the link to the English page, "{words}"')
def step_chinese_only_link(context, words):
    assert context.draw_error is None, context.draw_error
    line = _line(_text(context, _chinese_page(context)))
    assert line == f'<p class="markus-translation">{_link(words)}</p>', line


@then("the Spanish page does not say an AI translated it or who wrote it")
def step_spanish_no_ai(context):
    line = _line(_text(context, SPANISH))
    assert "IA" not in line and "Escrito" not in line and "Traducido" not in line, line


@then("the Chinese page does not say an AI translated it")
def step_chinese_no_ai(context):
    line = _line(_text(context, _chinese_page(context)))
    assert "AI" not in line and "翻译" not in line, line


@then('the Spanish Markdown twin says language "{tag}" and the English page it was translated from, and names no translation kind and no writer')
def step_twin_neutral(context, tag):
    twin = _twin(context, "es")
    assert f"Language: {tag}" in twin and f"Translated from: {ENGLISH_URL}" in twin, twin
    assert "Translation:" not in twin and "Written by" not in twin, twin


@then("the Spanish page's JSON-LD names no translator")
def step_no_translator(context):
    assert "translator" not in _ld(_text(context, SPANISH))


@then('the Spanish page\'s JSON-LD names no translator and is a translationOfWork of the English page in "{original}"')
def step_translation_of_work(context, original):
    data = _ld(_text(context, SPANISH))
    assert "translator" not in data, data
    assert data["translationOfWork"] == {"@type": data["@type"], "url": ENGLISH_URL, "inLanguage": original}, data
