"""A translated page says who wrote the translation (features_backend/translation-notice-kind.feature).

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
    publish_item(context.client, version["id"], actor=PERSON)
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


@given('the Spanish imported-translation line is "{text}"')
def step_imported_line(context, text):
    site = _site(context)
    site.strings["es-419"]["translation.importedLabel"] = text
    site.build()


@given("the copy has the two paragraphs the site shows and no picture")
def step_copy_without_picture(context):
    context.copy["blocks"] = context.copy["blocks"][:2]


@when('a person publishes the "{language}" translation')
def step_publish_language(context, language):
    _publish(context, language)


def _says(html_text: str, line: str, link_words: str, original_url: str, hreflang: str) -> None:
    pattern = rf'<p class="markus-translation">{re.escape(line)} <a href="{re.escape(original_url)}" hreflang="{hreflang}">{re.escape(link_words)}</a></p>'
    if not re.search(pattern, html_text):
        pattern = rf'<p class="markus-translation">{re.escape(line)}<a href="{re.escape(original_url)}" hreflang="{hreflang}">{re.escape(link_words)}</a></p>'   # no space in Chinese
    assert re.search(pattern, html_text), re.findall(r'<p class="markus-translation">.*?</p>', html_text)


@then('the Spanish page says "{line}" and links the English page to its "{words}"')
def step_spanish_line(context, line, words):
    assert context.draw_error is None, context.draw_error
    _says(_text(context, SPANISH), line, words, "/articles/waymo-crashes-fall/", "en")


@then('the Chinese page says "{line}" and links the English page to its "{words}"')
def step_chinese_line(context, line, words):
    assert context.draw_error is None, context.draw_error
    _says(_text(context, _chinese_page(context)), line, words, "/articles/waymo-crashes-fall/", "en")


@then("the Spanish page does not say who wrote the copy")
def step_no_writer_line(context):
    assert "Escrito por" not in _text(context, SPANISH)


@then("the Spanish page does not say an AI translated it")
def step_spanish_no_ai(context):
    assert "IA" not in re.search(r'<p class="markus-translation">.*?</p>', _text(context, SPANISH)).group(0)


@then("the Chinese page does not say an AI translated it")
def step_chinese_no_ai(context):
    assert "AI" not in re.search(r'<p class="markus-translation">.*?</p>', _text(context, _chinese_page(context))).group(0)


@then('the Spanish Markdown twin says it was written by "{writer}"')
def step_twin_writer(context, writer):
    assert f"Written by: {writer}" in _twin(context, "es"), _twin(context, "es")


@then('the Chinese Markdown twin says it was written by "{writer}"')
def step_twin_writer_zh(context, writer):
    text = _twin(context, "zh")
    assert "Language: zh-Hans" in text and "Translation: imported" in text and f"Written by: {writer}" in text, text


@then("the Spanish Markdown twin names no writer")
def step_twin_no_writer(context):
    assert "Written by" not in _twin(context, "es")


@then("the Spanish page's JSON-LD names no translator")
def step_no_translator(context):
    assert "translator" not in _ld(_text(context, SPANISH))


@then('the Spanish page\'s JSON-LD names "{writer}" as translator and is a translationOfWork of the English page in "{original}"')
def step_translator(context, writer, original):
    data = _ld(_text(context, SPANISH))
    assert data["translator"] == {"@type": "Person", "name": writer}, data
    assert data["translationOfWork"] == {"@type": data["@type"], "url": ENGLISH_URL, "inLanguage": original}, data


@then('drawing the Spanish page is refused naming "{text}"')
def step_refused(context, text):
    assert context.draw_error and text in html.unescape(context.draw_error), context.draw_error
    assert not _site(context).exists(SPANISH), "the page was drawn anyway"
