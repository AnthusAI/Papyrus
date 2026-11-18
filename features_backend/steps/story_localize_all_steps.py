"""Translating a whole site, and translating on publish (features_backend/story-localize-all.feature, story-localize-on-publish.feature).

A synthetic site on the shared in-memory fake backend: published Stories, their desired-state records, saved translations and the monitoring table the
automations use. The translation procedure itself is not run here (its own feature does that): a run is a function that records what the real run
records. Nothing reaches a network."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from fake_client import FakeAuthoringClient  # noqa: E402
from papyrus_content.language_serving import checked_serving  # noqa: E402
from papyrus_content.localize import auto, backfill, desired_state, dispatch  # noqa: E402
from papyrus_content.localize.publish import publishable  # noqa: E402
from papyrus_content.publishing import PublishResult  # noqa: E402

AUTOMATION = "mom.story-localize"
TENANT = "machines-on-machines"


# --- the site ------------------------------------------------------------------------------------------------------------------


def _languages(context, tags, auto_setting=None):
    languages = {"primary": "en", "enabled": ["en", *tags]}
    if auto_setting is not None:
        languages["auto"] = auto_setting
    context.settings = {"languages": languages}


@given('a site written in "{primary}" that also writes in "{tag}"')
def step_site(context, primary, tag):
    context.client = FakeAuthoringClient()
    context.client.tenant_id = TENANT   # a tenant backend: stored language groups carry the tenant prefix
    context.runs, context.publish_calls, context.invoked = [], [], []
    context.stories = {}
    _languages(context, [tag])


@given('a site written in "{primary}" with the further languages "{first}" and "{second}"')
def step_site_two(context, primary, first, second):
    context.client = FakeAuthoringClient()
    context.client.tenant_id = TENANT   # a tenant backend: stored language groups carry the tenant prefix
    context.runs, context.publish_calls, context.invoked = [], [], []
    context.stories = {}
    _languages(context, [first, second])


@given('the site also writes in "{tag}"')
def step_also(context, tag):
    context.settings["languages"]["enabled"].append(tag)


def _stored_group(story: str) -> str:
    """A stored languageGroupId on a tenant backend (Item and PublishedItem rows): tenant-prefixed. LocalizationRequest rows keep the bare lineage."""
    return f"{TENANT}#{story}"


def _hash(story: str, text: int) -> str:
    return f"hash-{story}-{text}"


def _publish_story(context, story: str, text: int = 1, *, language="en", do_not_localize=False) -> dict:
    """The Story's published version ``text`` as the CMS keeps it: the Item version, the PublishedItem row that names it."""
    group = _stored_group(story)
    metadata = {"doNotLocalize": True} if do_not_localize else {}
    item = {"id": f"{story}-v{text}", "lineageId": story, "versionNumber": text, "versionState": "current", "type": "article", "status": "published",
            "stage": "published", "slug": story, "section": "machines", "title": f"Title of {story}", "bodyMarkus": f"Body {text}\n", "contentHash": _hash(story, text),
            "language": language, "languageGroupId": group, "metadata": json.dumps(metadata), "updatedAt": "2026-11-14T00:00:00Z"}
    for row in context.client.tables.get("Item", {}).values():
        if row.get("lineageId") == story and row["id"] != item["id"]:
            row["versionState"] = "superseded"
    context.client.tables.setdefault("Item", {})[item["id"]] = item
    published = {"id": f"published-{story}", "sourceItemId": item["id"], "itemLineageId": story, "versionNumber": text, "type": "article", "status": "published",
                 "slug": story, "section": "machines", "title": item["title"], "metadata": json.dumps({**metadata, "sourceContentHash": item["contentHash"]}),
                 "language": language, "languageGroupId": group}
    context.client.tables.setdefault("PublishedItem", {})[published["id"]] = published
    context.stories[story] = item
    return item


@given('the published English Stories {names}')
def step_stories(context, names):
    for name in [part.strip().strip('"') for part in names.replace(" and ", ", ").split(",")]:
        _publish_story(context, name)


@given('the published English Story "{story}" at its first text')
def step_story(context, story):
    _publish_story(context, story)


@given('"{story}" is marked do not localize')
def step_dnl(context, story):
    _publish_story(context, story, do_not_localize=True)


def _current_text(context, story) -> int:
    return context.stories[story]["versionNumber"]


def _request(context, story, language, state, *, text=None, automation=None, publish=False, updated="2026-11-14T00:00:00Z", reason=None) -> dict:
    text = text or _current_text(context, story)
    row = {"id": f"{story}#{language}", "languageGroupId": story, "language": language, "sourceVersionId": f"{story}-v{text}", "sourceVersionNumber": text,
           "sourceContentHash": _hash(story, text), "state": state, "requestedBy": "cli", "requestedAt": updated, "runKey": "run-key", "reason": reason,
           "automationId": automation, "publish": publish, "updatedAt": updated}
    context.client.tables.setdefault("LocalizationRequest", {})[row["id"]] = row
    return row


def _translation(context, story, language, outcome, *, text=None, published=False) -> dict:
    text = text or _current_text(context, story)
    lineage = f"{story}--{language}"
    version = {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "type": "article", "status": "draft", "language": language,
               "languageGroupId": _stored_group(story), "sourceLineageId": story, "sourceVersionNumber": text, "sourceContentHash": _hash(story, text),
               "contentHash": f"hash-{lineage}", "metadata": json.dumps({"localization": {"outcome": outcome, "runKey": "run-key", "translation": "machine"}})}
    context.client.tables.setdefault("Item", {})[version["id"]] = version
    if published:
        context.client.tables.setdefault("PublishedItem", {})[f"published-{lineage}"] = {
            "id": f"published-{lineage}", "sourceItemId": version["id"], "itemLineageId": lineage, "status": "published", "language": language,
            "languageGroupId": _stored_group(story), "metadata": json.dumps({"sourceContentHash": version["contentHash"]})}
    return version


@given('"{story}" has a saved Spanish translation of its published text')
def step_saved_translation(context, story):
    _request(context, story, "es-419", "saved")
    _translation(context, story, "es-419", "saved")
    context.client.tables["PublishedItem"][f"published-{story}--es-419"] = {   # a translation that is live is among the published summaries too
        "id": f"published-{story}--es-419", "sourceItemId": f"{story}--es-419-v1", "itemLineageId": f"{story}--es-419", "status": "published", "type": "article",
        "language": "es-419", "languageGroupId": _stored_group(story), "metadata": json.dumps({"sourceContentHash": f"hash-{story}--es-419"})}
    context.client.tables["PublishedItem"].pop(f"published-{story}--es-419")   # saved but not live: the command may publish it


@given('"{story}" has a Spanish request for an older text')
def step_old_request(context, story):
    _publish_story(context, story, 2)
    _request(context, story, "es-419", "saved", text=1)


@given('"{story}" has a Spanish translation that is held')
def step_held_translation(context, story):
    _request(context, story, "es-419", "held")
    _translation(context, story, "es-419", "held")


@given('"{story}" has a Spanish translation that is held, though its request says only that a run started')
def step_held_but_started(context, story):
    _request(context, story, "es-419", "started")   # the run saved and held the translation, then ended before it wrote its outcome on the request
    _translation(context, story, "es-419", "held")


@given('"{story}" has a Spanish translation that is held, though its request was written again and not yet run')
def step_held_but_wanted(context, story):
    _request(context, story, "es-419", "wanted")
    _translation(context, story, "es-419", "held")


@given('"{story}" has a Spanish translation that is held, though its request says its run failed after saving it')
def step_held_but_failed(context, story):
    _request(context, story, "es-419", "failed", reason="URLError: <urlopen error [Errno 54] Connection reset by peer>")
    _translation(context, story, "es-419", "held")


@given('the Spanish request for "{story}" names this text and its run failed')
def step_failed_request(context, story):
    _request(context, story, "es-419", "failed", reason="ModelUnavailable: the model service could not be reached")


@given('the Spanish request for "{story}" names this text and its run is queued on an automation')
def step_queued_request(context, story):
    _request(context, story, "es-419", "started", automation=AUTOMATION, updated=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


# --- surveying -----------------------------------------------------------------------------------------------------------------


def _survey(context, languages):
    context.client.calls.clear()
    context.jobs = backfill.survey(context.client, context.settings, languages)


def _job(context, story, language="es-419"):
    return next((job for job in context.jobs if job.story == story and job.language == language), None)


@when('the whole site is surveyed for "{language}"')
def step_survey(context, language):
    _survey(context, [language])


@when("the whole site is surveyed for every enabled language")
def step_survey_all(context):
    _survey(context, [tag for tag in context.settings["languages"]["enabled"] if tag != "en"])


@then('"{story}" is up to date')
def step_up_to_date(context, story):
    assert _job(context, story).status == backfill.UP_TO_DATE, _job(context, story)


@then('"{story}" is up to date, held for a person')
def step_up_to_date_held(context, story):
    job = _job(context, story)
    assert job.status == backfill.UP_TO_DATE and job.state == "held" and "person" in job.detail, job


@then('"{story}" is up to date, held for a person, and its request record is left as it was')
def step_held_vouched(context, story):
    job = _job(context, story)
    assert job.status == backfill.UP_TO_DATE and job.state == "held" and "person" in job.detail and "request record says" in job.detail, job
    assert not [call for call in context.client.calls if call[0] in ("create", "update", "upsert")], context.client.calls


@then('"{story}" is to do because nothing was ever requested')
def step_todo_none(context, story):
    job = _job(context, story)
    assert job.status == backfill.PLANNED and job.state is None, job


@then('"{story}" is to do because its request is for older text')
def step_todo_older(context, story):
    job = _job(context, story)
    assert job.status == backfill.PLANNED and job.state is None, job


@then('"{story}" is to do, with the reason its last run gave')
def step_todo_reason(context, story):
    job = _job(context, story)
    assert job.status == backfill.PLANNED and "could not be reached" in job.detail, job


@then('"{story}" is queued')
def step_queued(context, story):
    assert _job(context, story).status == backfill.QUEUED, _job(context, story)


@then('"{story}" is not listed')
def step_not_listed(context, story):
    assert _job(context, story) is None


@then("the Spanish translations themselves are not listed as Stories to translate")
def step_no_translations(context):
    assert not [job for job in context.jobs if "--" in job.story], context.jobs


@then("the survey read the published summaries once and the requests through their state index, never a table per Story")
def step_listings_once(context):
    listings = [call for call in context.client.calls if call[0] == "list"]
    assert [call[1] for call in listings] == ["PublishedItemSummary"], listings
    indexes = [call for call in context.client.calls if call[0] == "list_by_index"]
    assert {call[1] for call in indexes} == {"localizationRequestsByState"} and len(indexes) == len(desired_state.STATES), indexes


@given("the stored language group of every published row is the tenant prefix and the Story's lineage")
def step_prefixed_groups(context):
    assert context.client.tenant_id == TENANT
    for row in context.client.tables["PublishedItem"].values():
        assert row["languageGroupId"].startswith(f"{TENANT}#"), row


@then('"{story}" is listed exactly once')
def step_listed_once(context, story):
    assert len([job for job in context.jobs if job.story == story and job.language == "es-419"]) == 1, context.jobs


@then('"{story}" is to do in "{first}" and in "{second}"')
def step_todo_both(context, story, first, second):
    assert _job(context, story, first).status == backfill.PLANNED and _job(context, story, second).status == backfill.PLANNED


# --- running -------------------------------------------------------------------------------------------------------------------


def _scripted_run(context):
    """What a run does to the site, as the real one records it: a request outcome, a saved translation, a result with its cost."""
    def run(client, *, story, language, ceiling_usd, procedure_key, key):
        context.runs.append((story, language))
        if story in context.failing:
            raise ValueError(context.failing[story])
        outcome = context.outcomes.get(story, "saved")
        row = client.tables["LocalizationRequest"][f"{story}#{language}"]
        row.update(state=outcome, runKey="run-key")
        _translation(context, story, language, outcome)
        return {"runId": f"run-{story}", "runStatus": "completed", "costUsd": 0.02, "output": {"outcome": outcome, "reason": "" if outcome == "saved" else "a number is missing"}}
    return run


def _publish_stub(context):
    def publish_item(client, item_id, *, actor, **_):
        context.publish_calls.append(item_id)
        lineage = item_id.rsplit("-v", 1)[0]
        client.tables.setdefault("PublishedItem", {})[f"published-{lineage}"] = {
            "id": f"published-{lineage}", "sourceItemId": item_id, "itemLineageId": lineage, "status": "published",
            "metadata": json.dumps({"sourceContentHash": client.tables["Item"][item_id]["contentHash"]})}
        return PublishResult(True, item_id, f"published-{lineage}", 1)
    return publish_item


def _translate(context, language, *, publish=False, runs_again=False, window=None):
    context.failing = getattr(context, "failing", {})
    context.outcomes = getattr(context, "outcomes", {})
    context.runs.clear()
    jobs = backfill.survey(context.client, context.settings, [language], window=window)
    with mock.patch("papyrus_content.publishing.publish_item", _publish_stub(context)):
        backfill.run_all(context.client, jobs, client_factory=lambda: context.client, run=_scripted_run(context), settings=context.settings,
                         publish_clean_results=publish, concurrency=2, ceiling_usd=None, procedure_key="mom.story-localize", key="key",
                         project=lambda client, version, published: {"ok": True})
    context.jobs = jobs
    context.lines = backfill.table(jobs)


@given('the translation of "{story}" fails in the model service')
def step_fails(context, story):
    context.failing = {**getattr(context, "failing", {}), story: "ModelUnavailable: the model service could not be reached"}


@when('the whole site is translated in this process for "{language}"')
def step_translate(context, language):
    _translate(context, language)


@given('the whole site was translated in this process for "{language}", and "{story}" failed')
def step_translated_once(context, language, story):
    context.failing = {story: "ModelUnavailable: the model service could not be reached"}
    _translate(context, language)
    context.failing = {}


@when('the whole site is translated in this process for "{language}" again')
def step_translate_again(context, language):
    _translate(context, language)


@when('the whole site is translated in this process for "{language}" with --publish-clean')
def step_translate_publish(context, language):
    _translate(context, language, publish=True)


@then('"{story}" is saved with its cost')
def step_saved_cost(context, story):
    job = _job(context, story)
    assert job.status == backfill.SAVED and job.costUsd == 0.02, job


@then('"{story}" is failed, saying the model service could not be reached')
def step_failed_reason(context, story):
    job = _job(context, story)
    assert job.status == backfill.FAILED and "could not be reached" in job.detail, job


@then('"{first}" and "{second}" are not run')
def step_not_run(context, first, second):
    assert not {first, second} & {story for story, _ in context.runs}, context.runs


@then("the table has one row for each of the four Stories and a totals row")
def step_table(context):
    rows = [line.split("\t") for line in context.lines]
    assert [row[1] for row in rows[:-1]] == ["story-a", "story-b", "story-c", "story-d"], rows
    assert rows[-1][0] == "total" and "1 failed" in rows[-1][1] and "1 saved" in rows[-1][1], rows[-1]


@then('only "{story}" is run')
def step_only(context, story):
    assert context.runs == [(story, "es-419")], context.runs


@given('the Spanish run of "{saved}" saves cleanly and the Spanish run of "{held}" is held')
def step_outcomes(context, saved, held):
    context.outcomes = {saved: "saved", held: "held"}


@then('the Spanish translation of "{story}" is published through the ordinary publish path')
def step_published(context, story):
    assert f"{story}--es-419-v1" in context.publish_calls, context.publish_calls
    assert _job(context, story).status == backfill.PUBLISHED, _job(context, story)


@then('the Spanish translation of "{story}" is not published and its row says a person answers its review request')
def step_held_not_published(context, story):
    assert f"{story}--es-419-v1" not in context.publish_calls, context.publish_calls
    assert _job(context, story).status == backfill.HELD and "review request" in _job(context, story).detail, _job(context, story)


@then('the Spanish translation of "{story}", which was already held, is not published')
def step_old_held(context, story):
    assert f"{story}--es-419-v1" not in context.publish_calls, context.publish_calls


@then('the Spanish translation of "{story}" is not published')
def step_not_published(context, story):
    assert f"{story}--es-419-v1" not in context.publish_calls, context.publish_calls


@then('"{story}" is run again for its new text')
def step_run_again_new(context, story):
    assert (story, "es-419") in context.runs, context.runs


@then('the Spanish translation published for "{story}" is the one of its new text')
def step_published_new(context, story):
    version = context.client.tables["Item"][f"{story}--es-419-v1"]
    assert version["sourceContentHash"] == _hash(story, 2) and f"{story}--es-419-v1" in context.publish_calls, (version, context.publish_calls)


@given('"{story}" was published again after its translation was saved')
def step_republished_after(context, story):
    _publish_story(context, story, 2)


# --- the plan ------------------------------------------------------------------------------------------------------------------


@given("the procedure has measured Spanish runs")
def step_history(context):
    context.history = [{"language": "es-419", "sourceCharacters": 1000, "costUsd": 0.02}]


def _plan(context, language):
    from papyrus_content.localize.budget import predict

    context.jobs = backfill.survey(context.client, context.settings, [language])
    context.client.calls.clear()
    history = getattr(context, "history", [])

    class Request:
        def __init__(self, story, language):
            self.language, self.localization_lineage = language, f"{story}--{language}"
            self.source = type("Source", (), {"version_number": 1, "body": "One paragraph.\n", "title": "T", "deck": "", "fields": (), "language": "en"})()
            self.previous = None
            self.glossary = type("Glossary", (), {"entries_in": staticmethod(lambda texts, language: [])})()
            self.prediction = predict(language, 1000, history)

    def collect(client, *, story, language, **_):
        return Request(story, language)

    context.summary = backfill.plan_cost(context.client, context.jobs, procedure_key=None, ceiling_usd=None, collect=collect)


@when('the whole site is planned for "{language}"')
def step_plan(context, language):
    context.before = json.dumps(context.client.tables, sort_keys=True, default=str)
    with mock.patch("papyrus_content.localize.record.spend_history", lambda client, key: getattr(context, "history", [])):
        _plan(context, language)


@then('the plan lists "{first}" and "{second}" with a predicted cost each')
def step_plan_lists(context, first, second):
    assert _job(context, first).costUsd == 0.02 and _job(context, second).costUsd == 0.02, context.jobs
    assert context.summary["predictedUsd"] == 0.04 and context.summary["withoutPrediction"] == 0, context.summary


@then('"{story}" has a predicted cost and no reason it cannot be planned')
def step_planned(context, story):
    job = _job(context, story)
    assert job.costUsd == 0.02 and "cannot be planned" not in job.detail, job


@then("no request, translation or publish was written")
def step_nothing_written(context):
    assert json.dumps(context.client.tables, sort_keys=True, default=str) == context.before
    assert not [call for call in context.client.calls if call[0] in ("create", "update", "upsert")], context.client.calls


@then("the rows to do say that no run of the language has been measured")
def step_unmeasured(context):
    todo = [job for job in context.jobs if job.status == backfill.PLANNED]
    assert todo and all(job.costUsd is None and "no measured run" in job.detail for job in todo), todo
    assert context.summary["withoutPrediction"] == len(todo)


@when('the whole site is queued on the automation "{automation}" for "{language}" with --publish-clean')
def step_queue(context, automation, language):
    jobs = backfill.survey(context.client, context.settings, [language])
    backfill.queue_all(context.client, jobs, automation_id=automation, publish=True)
    context.jobs = jobs


@then('the Spanish requests of "{first}" and "{second}" are wanted, name that automation and ask for a clean result to be published')
def step_queued_rows(context, first, second):
    for story in (first, second):
        row = context.client.tables["LocalizationRequest"][f"{story}#es-419"]
        assert row["state"] == "wanted" and row["automationId"] == AUTOMATION and row["publish"] is True and row["sourceContentHash"] == _hash(story, 2 if story == "story-c" else 1), row


@then("no procedure was run here")
def step_none_run(context):
    assert not context.runs


# --- translate on publish: the request side ------------------------------------------------------------------------------------


@given("the site has not turned on translate on publish")
def step_off(context):
    context.settings["languages"].pop("auto", None)


@given('the site turned on translate on publish with the automation "{automation}" and publishing clean translations')
def step_on(context, automation):
    context.settings["languages"]["auto"] = {"enabled": True, "automation": automation, "publish": True}
    context.automation_exists = automation == AUTOMATION   # "mom.missing" names an Automation nobody created


@given('the site turned on translate on publish with the automation "{automation}" and saving translations for a person to publish')
def step_on_saving(context, automation):
    context.settings["languages"]["auto"] = {"enabled": True, "automation": automation, "publish": False}


def _request_translations(context, item_id):
    context.client.calls.clear()
    context.result = auto.request_translations(context.client, item_id, settings=context.settings, now="2026-11-15T00:00:00Z")


@when('"{story}" is published')
def step_publish(context, story):
    _request_translations(context, context.stories[story]["id"])


@given('"{story}" was published and its translations requested')
def step_requested(context, story):
    _request_translations(context, context.stories[story]["id"])


@when('the publish of "{story}" is announced again')
def step_announce_again(context, story):
    context.before = json.dumps(context.client.tables.get("LocalizationRequest", {}), sort_keys=True)
    _request_translations(context, context.stories[story]["id"])


@when('"{story}" is published again with new text')
def step_new_text(context, story):
    item = _publish_story(context, story, 2)
    _request_translations(context, item["id"])


@given('the "{language}" run failed')
def step_run_failed(context, language):
    context.client.tables["LocalizationRequest"][f"story-a#{language}"].update(state="failed", reason="the run failed")


@when('a translation of "{story}" is published')
def step_publish_translation(context, story):
    version = _translation(context, story, "es-419", "saved")
    _request_translations(context, version["id"])


@when('a Story written in "{language}" is published')
def step_publish_other_language(context, language):
    item = _publish_story(context, "story-es", language=language)
    item["languageGroupId"] = "story-es"
    _request_translations(context, item["id"])


@when("a Story marked do not localize is published")
def step_publish_dnl(context):
    item = _publish_story(context, "story-dnl", do_not_localize=True)
    _request_translations(context, item["id"])


@then("no translation request is written")
def step_no_request(context):
    assert not context.client.tables.get("LocalizationRequest"), context.client.tables.get("LocalizationRequest")


@then('requests exist for "{first}" and "{second}" naming source version {number:d}, the automation "{automation}" and the publish choice')
def step_requests_exist(context, first, second, number, automation):
    for language in (first, second):
        row = context.client.tables["LocalizationRequest"][f"story-a#{language}"]
        assert row["sourceVersionNumber"] == number and row["automationId"] == automation and row["publish"] is True, row


@then("both requests are wanted")
def step_both_wanted(context):
    assert {row["state"] for row in context.client.tables["LocalizationRequest"].values()} == {"wanted"}


@then("no model was called and no run was started")
def step_no_run(context):
    assert not context.runs and not context.invoked


@then("no request was written again")
def step_not_again(context):
    assert context.result["requested"] == [] and json.dumps(context.client.tables["LocalizationRequest"], sort_keys=True) == context.before
    assert not [call for call in context.client.calls if call[0] in ("create", "update", "upsert")], context.client.calls


@then("there is one request per language and each names source version {number:d}")
def step_one_per_language(context, number):
    rows = list(context.client.tables["LocalizationRequest"].values())
    assert sorted(row["language"] for row in rows) == ["es-419", "zh-Hans"] and {row["sourceVersionNumber"] for row in rows} == {number}, rows


@then('the "{language}" request is wanted again and the "{other}" request is left alone')
def step_wanted_again(context, language, other):
    assert context.result["requested"] == [f"story-a#{language}"], context.result
    assert context.client.tables["LocalizationRequest"][f"story-a#{language}"]["state"] == "wanted"


# --- the dispatcher -----------------------------------------------------------------------------------------------------------


class Monitor:
    """The monitoring table as the automations see it: the router's publication and the rows runs leave."""

    def __init__(self):
        self.rows = []

    def router_config(self, monitor_id):
        return {"publications": [{"publicationId": "mom", "appsyncEndpoint": "https://site.test/graphql", "openaiKeyParameter": "/key", "tenantId": "mom", "siteBucket": "mom-site-bucket"}]}

    def trigger_rows(self, monitor_id, publication_id, procedure_key):
        return [row for row in self.rows if row["sk"].startswith("TRIGGER#")]

    def manual_rows(self, monitor_id, automation_id):
        return [row for row in self.rows if row["sk"].startswith("MANUAL#")]

    def put(self, row):
        self.rows.append(row)


def _automation(context, *, limit=None, exists=True):
    context.monitor = getattr(context, "monitor", Monitor())
    if exists:
        context.client.tables.setdefault("Automation", {})[AUTOMATION] = {
            "id": AUTOMATION, "enabled": True, "trigger": json.dumps({"kind": "monitor", "config": {"monitorId": "mom", "publicationId": "mom"}}),
            "procedureKey": AUTOMATION, "inputTemplate": "{}", "limits": json.dumps({"maxConcurrent": limit} if limit else {})}


@given("the automation allows one run at a time")
def step_one_at_a_time(context):
    _automation(context, limit=1)


def _dispatch(context, images):
    if "Automation" not in context.client.tables and getattr(context, "automation_exists", True):
        _automation(context)
    context.monitor = getattr(context, "monitor", Monitor())
    context.client.calls.clear()
    context.outcome = dispatch.handle_changes(images, context.client, reader=context.monitor, writer=context.monitor, invoke=lambda request: context.invoked.append(request),
                                              invoke_publish=lambda task: context.publish_asked.append(task), site_endpoint="https://site.test/graphql",
                                              now="2026-11-15T01:00:00Z")


def _new_images(context):
    return [{"old": None, "new": dict(row)} for row in context.client.tables.get("LocalizationRequest", {}).values()]


@when("the dispatcher sees the new requests")
def step_dispatch(context):
    context.publish_asked = getattr(context, "publish_asked", [])
    _dispatch(context, _new_images(context))


@given("the dispatcher saw the new requests")
def step_dispatched(context):
    context.publish_asked = getattr(context, "publish_asked", [])
    _dispatch(context, _new_images(context))


@when("two dispatcher batches see the same requests")
def step_two_batches(context):
    context.publish_asked = []
    images = _new_images(context)
    _dispatch(context, images)
    _dispatch(context, images)


@given('a person asked for the "{language}" translation of "{story}" from the command line')
def step_person_request(context, language, story):
    desired_state.want(context.client, source=context.stories[story], language=language, requested_by="cli")


@when("the dispatcher sees the new request")
def step_dispatch_one(context):
    context.publish_asked = []
    context.before = json.dumps(context.client.tables["LocalizationRequest"], sort_keys=True)
    _dispatch(context, _new_images(context))


@then('a run of "{automation}" is started for each of the two languages, with the Story, the language and the source version')
def step_runs_started(context, automation):
    inputs = sorted((request["input"]["language"], request["input"]["story"], request["input"]["source_version"]) for request in context.invoked)
    assert inputs == [("es-419", "story-a", 1), ("zh-Hans", "story-a", 1)], (context.invoked, context.outcome)
    assert {request["procedureKey"] for request in context.invoked} == {automation}


@then("each request is started, not wanted")
def step_started(context):
    assert {row["state"] for row in context.client.tables["LocalizationRequest"].values()} == {"started"}


@then("each language has exactly one run")
def step_one_run_each(context):
    assert sorted(request["input"]["language"] for request in context.invoked) == ["es-419", "zh-Hans"], context.invoked


@then("one language is started and the other is still wanted")
def step_one_started(context):
    states = sorted(row["state"] for row in context.client.tables["LocalizationRequest"].values())
    assert states == ["started", "wanted"] and len(context.invoked) == 1, (states, context.invoked)


@when("the dispatcher sees the started run end saved")
def step_run_ended(context):
    started = next(row for row in context.client.tables["LocalizationRequest"].values() if row["state"] == "started")
    for row in context.monitor.rows:
        row["status"] = "completed"
    old = dict(started)
    started["state"] = "saved"
    context.publish_asked = []
    _dispatch(context, [{"old": old, "new": dict(started)}])


@then("the other language is started")
def step_other_started(context):
    states = sorted(row["state"] for row in context.client.tables["LocalizationRequest"].values())
    assert states == ["saved", "started"] and len(context.invoked) == 2, (states, context.invoked)


@when("the dispatcher sees the change that put the waiting request back")
def step_putback(context):
    waiting = next(row for row in context.client.tables["LocalizationRequest"].values() if row["state"] == "wanted")
    context.invoked.clear()
    _dispatch(context, [{"old": {**waiting, "state": "started"}, "new": dict(waiting)}])


@then("it starts nothing and reads nothing")
def step_nothing(context):
    assert not context.invoked and not context.client.calls, (context.invoked, context.client.calls)


@then("no run is started and the request is unchanged")
def step_unchanged(context):
    assert not context.invoked and json.dumps(context.client.tables["LocalizationRequest"], sort_keys=True) == context.before


@then("both requests are failed, saying the automation does not exist")
def step_failed_missing(context):
    rows = list(context.client.tables["LocalizationRequest"].values())
    assert {row["state"] for row in rows} == {"failed"} and all("does not exist" in row["reason"] for row in rows), rows
    assert not context.invoked


@when('the "{language}" run saves its translation cleanly')
def step_run_saves(context, language):
    context.publish_asked = []
    row = context.client.tables["LocalizationRequest"][f"story-a#{language}"]
    context.old_row = dict(row, state="started")
    row["state"] = "saved"
    _translation(context, "story-a", language, "saved")


@when("the dispatcher sees the request become saved")
def step_saw_saved(context):
    saved = next(row for row in context.client.tables["LocalizationRequest"].values() if row["state"] == "saved")
    _dispatch(context, [{"old": context.old_row, "new": dict(saved)}])


@then('the content-actions function is asked to publish the "{language}" translation')
def step_publish_asked(context, language):
    assert context.publish_asked == [{"task": dispatch.PUBLISH_TASK, "requestId": f"story-a#{language}"}], context.publish_asked


@then('the "{language}" translation is not asked for')
def step_not_asked(context, language):
    assert all(task["requestId"] != f"story-a#{language}" for task in context.publish_asked)


@then("the content-actions function is not asked to publish anything")
def step_asked_nothing(context):
    assert context.publish_asked == [], context.publish_asked


# --- what may be published -----------------------------------------------------------------------------------------------------


@given('the "{language}" translation {situation}')
def step_situation(context, language, situation):
    request = context.client.tables["LocalizationRequest"][f"story-a#{language}"]
    if situation == "was held":
        _translation(context, "story-a", language, "held")
    else:
        _translation(context, "story-a", language, "saved", published=situation == "was saved cleanly and is already live at this text")
    if situation == "was saved cleanly but the site stopped writing in it":
        context.settings["languages"]["enabled"] = ["en", "zh-Hans"]
    if situation == "was saved cleanly but the Story was published again":
        _publish_story(context, "story-a", 2)
    if situation == "was saved cleanly but the Story is no longer published":
        del context.client.tables["PublishedItem"]["published-story-a"]
    if situation.startswith("was saved cleanly"):
        request["state"] = "saved"
    context.request = request


@when("the publishable translation is asked for")
def step_ask(context):
    context.answer = publishable(context.client, context.request, context.settings)


@then("the answer is {answer}")
def step_answer(context, answer):
    found = context.answer
    expected = {
        "ready to publish": found.version is not None and not found.done,
        "not publishable, waiting for a person": found.version is None and found.held,
        "already published": found.done and found.version is not None,
        "not publishable, the site does not write in it": found.version is None and "does not write in" in found.reason,
        "not publishable, the original has moved on": found.version is None and "published again" in found.reason,
        "not publishable, the original is not published": found.version is None and "is not published" in found.reason,
    }[answer]
    assert expected, found


# --- the command ---------------------------------------------------------------------------------------------------------------


def _command(context, words, *, iam: bool):
    import contextlib
    import io
    import shlex

    from papyrus_content import story_commands

    flags = shlex.split(words)[3:]
    assert shlex.split(words)[:3] == ["papyrus", "stories", "localize"], words
    context.failing = getattr(context, "failing", {})
    context.outcomes = getattr(context, "outcomes", {})
    context.client.endpoint = "https://mom.example.test/graphql"
    context.before = json.dumps(context.client.tables.get("LocalizationRequest", {}), sort_keys=True)
    out, context.refusal = io.StringIO(), None
    from papyrus_content import editorial_checks

    class Quiet:
        def __init__(self, *args, **kwargs):
            pass

    from papyrus_content import request_meter

    context.units_before = request_meter.current_run().units
    with mock.patch.object(story_commands, "create_authoring_client", lambda *a, **k: (context.client, None)), \
            mock.patch.object(editorial_checks, "GraphQLEditorialStore", Quiet), \
            mock.patch.object(editorial_checks, "settings_from", lambda store: context.settings), \
            mock.patch("papyrus_content.user_auth_mode.iam_requested", lambda: iam), \
            mock.patch("papyrus_content.site_selection.host_for", lambda endpoint: "mom.example.test"), \
            mock.patch("papyrus_content.localize.start.openai_key", lambda parameter: "key"), \
            mock.patch("papyrus_content.localize.start.run_from_cli", _scripted_run(context)), \
            mock.patch("papyrus_content.localize.record.spend_history", lambda client, key: getattr(context, "history", [])), \
            mock.patch("papyrus_content.localize.record.collect", _planning_collect(context)), \
            mock.patch("papyrus_content.projection_trigger.trigger_projection", lambda task: {"ok": True}), \
            mock.patch("papyrus_content.publishing.publish_item", _publish_stub(context)), \
            contextlib.redirect_stdout(out):
        try:
            story_commands.stories_localize(flags)
        except ValueError as error:
            context.refusal = str(error)
    context.output_lines = out.getvalue().splitlines()


def _planning_collect(context):
    from papyrus_content.localize.budget import predict

    def collect(client, *, story, language, shared=None, **_):
        context.shared_seen = [*getattr(context, "shared_seen", []), shared]

        class Request:
            pass

        request = Request()
        request.language, request.localization_lineage = language, f"{story}--{language}"
        request.source = type("Source", (), {"version_number": 1, "body": "One paragraph.\n", "title": "T", "deck": "", "fields": (), "language": "en"})()
        request.previous = None
        request.glossary = type("Glossary", (), {"entries_in": staticmethod(lambda texts, language: [])})()
        request.prediction = predict(language, 1000, getattr(context, "history", []))
        return request
    return collect


@when('an operator signed in with AWS credentials runs "{words}"')
def step_operator(context, words):
    _command(context, words, iam=True)


@when('a person signed in without AWS credentials runs "{words}"')
def step_person(context, words):
    _command(context, words, iam=False)


@then('the output has a "saved" row for "{saved}" and a "failed" row for "{failed}" and a totals row')
def step_output_rows(context, saved, failed):
    rows = [line.split("\t") for line in context.output_lines]
    assert any(row[2] == "saved" and row[3] == saved for row in rows) and any(row[2] == "failed" and row[3] == failed for row in rows), rows
    assert rows[-1][2] == "total", rows[-1]


@then("the command fails saying {count:d} of {total:d} translations failed and that running it again does only what remains")
def step_command_failed(context, count, total):
    assert context.refusal and f"{count} of {total} translations failed" in context.refusal and "does only what remains" in context.refusal, context.refusal


@then("it is refused saying --all translates every Story")
def step_refused_story(context):
    assert context.refusal and "--all translates every Story" in context.refusal, context.refusal


@then("it is refused saying --all needs exactly one of --language and --all-languages")
def step_refused_language(context):
    assert context.refusal and "exactly one of --language TAG and --all-languages" in context.refusal, context.refusal


@then("it is refused saying en is the primary language")
def step_refused_primary(context):
    assert context.refusal and "primary language" in context.refusal, context.refusal


@then("it is refused naming the operator lane and --automation")
def step_refused_lane(context):
    assert context.refusal and "papyrus --auth iam" in context.refusal and "--automation" in context.refusal, context.refusal


@then("no request was written by the command")
def step_command_wrote_nothing(context):
    assert json.dumps(context.client.tables.get("LocalizationRequest", {}), sort_keys=True) == context.before and not context.runs


@then("every Story of the plan was planned with the same shared reads")
def step_shared(context):
    seen = context.shared_seen
    assert len(seen) >= 2 and seen[0] is not None and all(entry is seen[0] for entry in seen), seen


@then("the request budget of the command allows for the {count:d} translations to do")
def step_units(context, count):
    from papyrus_content import request_meter

    assert request_meter.current_run().units - context.units_before == count, request_meter.current_run().units


@then("the output ends with a plan line for {count:d} Stories to do")
def step_plan_line(context, count):
    plan = context.output_lines[-1].split("\t")
    assert plan[2] == "plan" and plan[3].startswith(f"{count} to do, predicted ${count * 0.02:.4f}"), plan


# --- the content-actions function --------------------------------------------------------------------------------------------


def _handler(context):
    if getattr(context, "handler", None) is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("content_actions_for_localize", REPO_ROOT / "amplify/functions/content-actions/handler.py")
        context.handler = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(context.handler)
    return context.handler


@when('the content-actions function announces that "{story}" is live')
def step_announce(context, story):
    handler = _handler(context)
    context.announced = []
    context.logged = []
    with mock.patch.object(handler, "announce_published", lambda item, published: context.announced.append((item, published))), \
            mock.patch("papyrus_content.localize.auto.settings_from", lambda store: context.settings), \
            mock.patch("builtins.print", lambda *args, **kwargs: context.logged.append(args[0] if args else "")):
        handler.announce_published_story(context.client, context.stories[story]["id"], f"published-{story}")


@when('the translation requests cannot be written and the function announces that "{story}" is live')
def step_announce_failing(context, story):
    handler = _handler(context)
    context.announced, context.logged = [], []

    def broken(*args, **kwargs):
        raise RuntimeError("the table is unavailable")

    with mock.patch.object(handler, "announce_published", lambda item, published: context.announced.append((item, published))), \
            mock.patch("papyrus_content.localize.auto.request_translations", broken), \
            mock.patch("builtins.print", lambda *args, **kwargs: context.logged.append(args[0] if args else "")):
        handler.announce_published_story(context.client, context.stories[story]["id"], f"published-{story}")


@then("the newsletter and notifications announcement is made")
def step_announced(context):
    assert context.announced == [("story-a-v1", "published-story-a")], context.announced


@then("the announcement is still made and the failure is logged with its cause")
def step_announced_logged(context):
    assert context.announced and any("papyrus_translation_request_failed" in line and "the table is unavailable" in line for line in context.logged), context.logged


@given("the site requires a person's approval to publish")
def step_gate(context):
    context.gate = True


@when('the content-actions function runs the publish task for the "{language}" request')
def step_publish_task(context, language):
    from papyrus_content.publishing import PublishError

    handler = _handler(context)
    context.publish_calls = []

    def publish_item_action(arguments, actor, approved_by=None):
        if getattr(context, "gate", False):
            raise PublishError("publish-gate", "This site needs a person's approval to publish.")
        context.publish_calls.append((arguments, actor))
        return {"ok": True, "changed": True}

    with mock.patch.object(handler, "publish_item_action", publish_item_action), \
            mock.patch("papyrus_content.editorial_checks.settings_from", lambda store: context.settings):
        context.task_answer = handler.publish_localization_action(context.client, {"task": dispatch.PUBLISH_TASK, "requestId": f"story-a#{language}"})


@then('the translation is published by "{actor}" through the ordinary publish path')
def step_task_published(context, actor):
    assert context.publish_calls == [({"id": "story-a--es-419-v1", "async": True}, actor)], context.publish_calls
    assert context.task_answer["published"] is True, context.task_answer


@then('the "{language}" request is published')
def step_request_published(context, language):
    assert context.client.tables["LocalizationRequest"][f"story-a#{language}"]["state"] == "published"


@then("the task answers that nothing was published, with the reason")
def step_task_nothing(context):
    assert context.task_answer["published"] is False and context.task_answer["reason"], context.task_answer


@then('the "{language}" request keeps its state and says why it was not published')
def step_request_reason(context, language):
    row = context.client.tables["LocalizationRequest"][f"story-a#{language}"]
    assert row["state"] == "saved" and "not published [publish-gate]" in row["reason"], row


@then("nothing was published")
def step_nothing_published(context):
    assert not context.publish_calls


# --- the range of source updates -----------------------------------------------------------------------------------------------


def _published_row(context, story) -> dict:
    return context.client.tables["PublishedItem"][f"published-{story}"]


@given('"{story}" was last published at "{when}"')
def step_last_published(context, story, when):
    _published_row(context, story)["versionPublishedAt"] = when


@given('"{story}" was first published at "{first}" and last published at "{when}"')
def step_first_last_published(context, story, first, when):
    _published_row(context, story).update(publishedAt=first, versionPublishedAt=when)


@when('the Stories updated since "{since}" and before "{before}" are surveyed for "{language}"')
def step_survey_range(context, language, since, before):
    context.window = backfill.UpdatedWindow.parse(since, before)
    _survey_in(context, [language])


@when('the Stories updated since "{since}" are surveyed for "{language}"')
def step_survey_since(context, language, since):
    context.window = backfill.UpdatedWindow.parse(since, None)
    _survey_in(context, [language])


@when('the Stories updated before "{before}" are surveyed for "{language}"')
def step_survey_before(context, language, before):
    context.window = backfill.UpdatedWindow.parse(None, before)
    _survey_in(context, [language])


def _survey_in(context, languages):
    context.client.calls.clear()
    context.jobs = backfill.survey(context.client, context.settings, languages, window=context.window)


@then("the range reports {count:d} Stories left out for having no publish time")
def step_undated(context, count):
    assert context.window.undated == count, context.window.undated


@when('the range "{text}" is read as the start at "{now}"')
def step_read_range(context, text, now):
    from datetime import datetime

    context.window = backfill.UpdatedWindow.parse(text, None, now=datetime.fromisoformat(now.replace("Z", "+00:00")))


@then('the range starts at "{when}"')
def step_range_starts(context, when):
    assert context.window.since.strftime("%Y-%m-%dT%H:%M:%SZ") == when, context.window.since


@when('the Stories updated since "{since}" are translated in this process for "{language}"')
def step_translate_range(context, language, since):
    _translate(context, language, window=backfill.UpdatedWindow.parse(since, None))


@when('the Stories updated since "{since}" are translated in this process for "{language}" with --publish-clean')
def step_translate_range_publish(context, language, since):
    _translate(context, language, publish=True, window=backfill.UpdatedWindow.parse(since, None))


@when('the Stories updated since "{since}" are queued on the automation "{automation}" for "{language}" with --publish-clean')
def step_queue_range(context, since, automation, language):
    jobs = backfill.survey(context.client, context.settings, [language], window=backfill.UpdatedWindow.parse(since, None))
    backfill.queue_all(context.client, jobs, automation_id=automation, publish=True)
    context.jobs = jobs


@then('the Spanish request of "{story}" is wanted and names that automation')
def step_one_queued(context, story):
    row = context.client.tables["LocalizationRequest"][f"{story}#es-419"]
    assert row["state"] == "wanted" and row["automationId"] == AUTOMATION, row


@then('"{story}" has no new Spanish request')
def step_no_new_request(context, story):
    row = context.client.tables.get("LocalizationRequest", {}).get(f"{story}#es-419")
    assert row is None or row["state"] != "wanted", row


@then("it is refused saying --updated-since must be an ISO date or a duration")
def step_refused_malformed(context):
    assert context.refusal and "--updated-since must be an ISO date or datetime" in context.refusal and "or a duration" in context.refusal, context.refusal


@then("it is refused saying --updated-before must be longer than zero")
def step_refused_zero(context):
    assert context.refusal and "--updated-before must be longer than zero" in context.refusal, context.refusal


@then("it is refused saying --updated-since must be earlier than --updated-before")
def step_refused_backwards(context):
    assert context.refusal and "--updated-since" in context.refusal and "must be earlier than --updated-before" in context.refusal, context.refusal


@then("it is refused saying the range narrows --all")
def step_refused_single(context):
    assert context.refusal and "narrow --all" in context.refusal, context.refusal


@then("the output says no published Story was updated since {date} and there is nothing to translate")
def step_empty_range(context, date):
    line = next(row for row in context.output_lines if "No published Story was updated" in row)
    assert f"since {date}" in line and "nothing to translate" in line, line


@then('the output lists "{listed}" and not "{unlisted}"')
def step_output_lists(context, listed, unlisted):
    text = "\n".join(context.output_lines)
    assert listed in text and unlisted not in text, text
