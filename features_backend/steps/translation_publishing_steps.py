"""A translation is published as a person's act (features_backend/translation/translation-publishing.feature).

The Story is translated by the scripted run of story_localize_steps.py (its given and when steps are used as written), then published through the real
``publish_item`` and projected by the real standard projector on the synthetic site of language_serving_steps.py. Everything runs on the in-memory fake
backend; no model, network or AWS."""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from features_backend.steps.language_serving_steps import NOW, LanguageSite  # noqa: E402
from papyrus_content import review_requests, story_checklist as checklist  # noqa: E402
from papyrus_content.newsletter.issues_test import rig_context  # noqa: E402
from papyrus_content.newsletter.roundup import candidates  # noqa: E402
from papyrus_content.publishing import PublishError, project_item_to_published, publish_item, published_item_id_for, unpublish_item  # noqa: E402

STORY = "story-waymo"
LINEAGE = "story-waymo--es-419"
ENGLISH = "articles/waymo-crashes-fall/index.html"
SPANISH = "es/articles/bajan-los-choques-de-waymo/index.html"
PERSON = "An Editor"


def _site(context) -> LanguageSite:
    return context.language_site


def _text(context, key: str) -> str:
    return _site(context).text(key)


def _hreflang(html: str) -> list[tuple[str, str]]:
    return re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">', html)


def _translation(context) -> dict:
    versions = sorted((row for row in context.client.tables["Item"].values() if row.get("lineageId") == LINEAGE), key=lambda row: row["versionNumber"])
    assert versions, "no translation was saved"
    return versions[-1]


def _hold_request(context) -> str:
    (request_id,) = [key for key in context.client.tables.get("ReviewRequest", {})]
    return request_id


def _publish_english(context) -> None:
    site, primary = _site(context), context.primary
    primary["status"] = "published"
    media = [row for row in context.client.tables.get("MediaAsset", {}).values() if row["itemId"] == primary["id"]]
    published, _ = project_item_to_published(primary, media, published_at=NOW, version_published_at=NOW, version_published_by="t", version_number=3)
    context.client.tables.setdefault("PublishedItem", {})[published["id"]] = published
    site.project(primary["id"])


@given("the English Story is served by a site that publishes Spanish under \"es\"")
def step_site(context):
    work = tempfile.TemporaryDirectory()
    context.add_cleanup(work.cleanup)
    site = LanguageSite(Path(work.name))
    site.client = context.client
    context.language_site = site
    context.primary["section"] = "articles"
    context.primary["bodyMarkus"] = "\n\n".join(context.paragraphs[:2]) + "\n"   # the synthetic site has no media store, so its pages show no picture
    site.build()
    site.deploy()
    _publish_english(context)


@given('the Spanish translation line is "{text}"')
def step_line(context, text):
    site = _site(context)
    site.strings["es-419"]["translation.label"] = text
    site.build()


@given('the translation run for "{language}" has finished held')
def step_finished_held(context, language):
    from story_localize_steps import _run   # noqa: PLC0415 - the run of the localize feature, as it is
    _run(context)
    assert context.output and context.output["outcome"] == "held", (context.output, context.error)


@given("a person publishes the translation")
@when("a person publishes the translation")
def step_publish(context):
    version = _translation(context)
    context.publish_error = None
    try:
        publish_item(context.client, version["id"], actor=PERSON)
    except PublishError as error:
        context.publish_error = error
        return
    _site(context).project(version["id"])


@when("an automation publishes the translation")
def step_automation_publish(context):
    context.publish_error = None
    try:
        publish_item(context.client, _translation(context)["id"], actor="AI (translation on publish)")
    except PublishError as error:
        context.publish_error = error


@then("the translation is still a ready draft")
def step_ready_draft(context):
    version = _translation(context)
    assert version["status"] != "published", version
    assert context.client.get_record("PublishedItem", published_item_id_for(LINEAGE)) is None


@when("a person unpublishes the translation")
def step_unpublish(context):
    version = _translation(context)
    unpublish_item(context.client, version["id"], actor=PERSON)
    _site(context).project(version["id"], )


@when('a person answers the review request with "{decision}"')
def step_answer(context, decision):
    review_requests.answer_review(context.client, _hold_request(context), decision=decision, by=PERSON)


@given("the English Story is taken down")
@when("the English Story is taken down")
def step_take_down(context):
    site = _site(context)
    site.unpublish(context.primary["id"])
    site.project(context.primary["id"])


@when("the English Story is published again")
def step_republish_english(context):
    _publish_english(context)


@then("the translation is published as \"{lineage}\" at \"{key}\"")
def step_published(context, lineage, key):
    assert context.publish_error is None, context.publish_error
    row = context.client.tables["PublishedItem"][published_item_id_for(lineage)]
    assert row["language"] == "es-419" and row["languageGroupId"] == STORY, row
    assert _site(context).exists(key), _site(context).keys()


@then('the Spanish page says "{text}" and links the English page')
def step_label(context, text):
    html = _text(context, SPANISH)
    assert re.search(rf'<p class="markus-translation">{re.escape(text.split(" original")[0])} <a href="/articles/waymo-crashes-fall/" hreflang="en">original en inglés</a></p>', html), html
    assert '<html lang="es-419"' in html


@then('the Story\'s own text does not contain "{text}"')
def step_not_in_body(context, text):
    assert text not in _translation(context)["bodyMarkus"] and text not in json.dumps(_translation(context).get("metadata"), ensure_ascii=False)


@then('the Waymo English page lists hreflang "en" and "es" and x-default pointing at itself')
def step_english_alternates(context):
    links = dict(_hreflang(_text(context, ENGLISH)))
    english = "https://machines.example.test/articles/waymo-crashes-fall/"
    assert links == {"en": english, "es": "https://machines.example.test/es/articles/bajan-los-choques-de-waymo/", "x-default": english}, links


@then("the English listings do not list the translation")
def step_listing(context):
    assert "bajan-los-choques" not in _text(context, "articles/index.html") and "bajan-los-choques" not in _text(context, "index.html")


@then("the translation has its own checklist steps and no rating of its own")
def step_own_checklist(context):
    items = context.client.tables["Item"].values()
    assert {row["stepKey"] for row in checklist.read_steps(context.client, LINEAGE)} == {"translate", "faithfulness", "copy_edit", "human_review", "publish"}
    assert not any(row.get(field) for row in items if row.get("lineageId") == LINEAGE for field in ("starRating", "starRatedBy"))


def _ld(html: str) -> dict:
    return next(json.loads(match) for match in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html) if '"translationOfWork"' in match)


@then('the Spanish page\'s JSON-LD says inLanguage "{language}" and is a translationOfWork of the English page in "{original}"')
def step_json_ld(context, language, original):
    data = _ld(_text(context, SPANISH))
    assert data["inLanguage"] == language and data["translationOfWork"] == {
        "@type": data["@type"], "url": "https://machines.example.test/articles/waymo-crashes-fall/", "inLanguage": original}, data


@then('the Spanish Markdown twin says language "{language}", translation "{kind}" and the English page it was translated from')
def step_twin(context, language, kind):
    twin = next(key for key in _site(context).keys() if key.startswith("es/articles/bajan-los-choques-de-waymo") and key.endswith(".md"))
    text = _text(context, twin)
    assert f"Language: {language}" in text and f"Translation: {kind}" in text and "Translated from: https://machines.example.test/articles/waymo-crashes-fall/" in text, text


@then('publishing is refused as "{code}" naming the review request')
def step_refused_held(context, code):
    error = context.publish_error
    assert error is not None and error.code == code and _hold_request(context) in error.message, error


@then('publishing is refused as "{code}" naming "{lineage}"')
def step_refused_original(context, code, lineage):
    error = context.publish_error
    assert error is not None and error.code == code and lineage in error.message, error


def _spanish_story_pages(context) -> list[str]:
    """Every Spanish page that is not one of the Spanish indexes (home, section listings, their Markdown twins) or its 404 page, which a public language has from its first day."""
    indexes = ("es/index.html", "es/articles/index.html", "es/concepts/index.html", "es/index.md", "es/articles/index.md", "es/concepts/index.md", "es/404.html")
    return [key for key in _site(context).keys() if key.startswith("es/") and key not in indexes]


@then("no Spanish page is served")
def step_no_page(context):
    assert not _spanish_story_pages(context), _site(context).keys()


@then("no Spanish page and no Spanish listing is served")
def step_no_page_or_listing(context):
    step_no_page(context)
    for key in (key for key in _site(context).keys() if key.startswith("es/") and key.endswith(".html")):   # an index left over lists no Story
        assert "bajan-los-choques" not in _text(context, key), key


@then("the Waymo English page is published and has no Spanish alternate")
def step_english_alone(context):
    assert _site(context).exists(ENGLISH) and not _hreflang(_text(context, ENGLISH))


@then("the Waymo English page lists no hreflang links")
def step_english_no_links(context):
    assert not _hreflang(_text(context, ENGLISH))


@then("the Waymo English page is still published")
def step_english_published(context):
    assert _site(context).exists(ENGLISH) and published_item_id_for(STORY) in context.client.tables["PublishedItem"]


@then("no review request is about the English Story")
def step_no_review(context):
    subjects = [json.loads(row["subject"]) if isinstance(row["subject"], str) else row["subject"] for row in context.client.tables.get("ReviewRequest", {}).values()]
    assert subjects and all(subject["id"] != STORY for subject in subjects), subjects


@then("the translation's own record is still published")
def step_record_published(context):
    assert published_item_id_for(LINEAGE) in context.client.tables["PublishedItem"]
    assert _translation(context)["status"] == "published"


@then('the Spanish page is back at "{key}"')
def step_back(context, key):
    assert _site(context).exists(key), _site(context).keys()


# -- announcements: a translation is no new Story -------------------------------------------------------------------------------------------


def _translated_row(lineage: str, **row) -> dict:
    return {"itemLineageId": lineage + "--es-419", "languageGroupId": lineage, "language": "es-419", **row}


@then("the new-story alert for the translation is ignored as a translation")
def step_alert(context):
    from unittest import mock

    from papyrus_content.list_cadence import story_wake

    original = {"id": "published-" + STORY, "status": "published", "type": "article", "section": "news", "slug": "waymo", "title": "Waymo", "itemLineageId": STORY,
                "languageGroupId": STORY, "language": "en", "versionNumber": 1}
    translated = {**original, "id": "published-" + LINEAGE, "slug": "bajan-los-choques-de-waymo", **_translated_row(STORY)}

    class Client:
        """The published copy and the lineage's current version, as the announce agent reads them."""

        def get_record(self, _model, row_id):
            return {original["id"]: original, translated["id"]: translated}.get(row_id)

        def list_by_index(self, _index, lineage):
            return [{"id": lineage + "-v1", "versionState": "current", "stage": "published", "starRating": 4, "starRatedBy": "ada", "starRatedAt": "2026-11-17T09:00:00Z"}]

    with mock.patch("papyrus_content.announcements.intake.ChecklistReviewStamps.reviewed", return_value=False):
        assert story_wake.read_candidate(Client(), STORY).translation is False
        assert story_wake.read_candidate(Client(), LINEAGE).translation is True


@then("the roundup of the week names the English Story and not the translation")
def step_roundup(context):
    with rig_context() as rig:
        rig.content.publish(slug="waymo", title="Waymo", section="articles", at=rig.now)
        rig.content.published.append({**rig.content.published[0], "id": "published-" + LINEAGE, "slug": "bajan", **_translated_row(STORY)})
        found = [entry.row["slug"] for entry in candidates(rig.service)]
    assert found == ["waymo"], found
