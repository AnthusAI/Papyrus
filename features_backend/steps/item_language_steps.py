"""Every Story version knows its language (features_backend/item-language.feature).

The client's language rule runs through the real authoring client with a recording transport; the backfill and the group index run on the
shared in-memory fake. Nothing here reaches a network."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.editorial_languages import story_language  # noqa: E402
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient  # noqa: E402
from papyrus_content.item_language import ItemLanguageMissing, localization_lineage_id  # noqa: E402
from papyrus_content.item_language_backfill import run_languages  # noqa: E402
from fake_client import FakeAuthoringClient  # noqa: E402

SETTINGS = {"languages": {"primary": "en", "enabled": ["en", "es-419", "zh-Hans"]}}


class RecordingClient(PapyrusGraphQLAuthoringClient):
    """The real authoring client with the transport replaced: answers the settings and row reads, records every mutation."""

    def __init__(self, *, tenant_id: str, stored: dict[str, dict]) -> None:
        super().__init__(endpoint=f"https://{uuid.uuid4().hex}.appsync.example.test/graphql", header_factory=lambda body: {}, tenant_id=tenant_id)
        self.stored = stored
        self.sent: list[dict] = []

    def _send_graphql(self, query, variables=None):
        variables = variables or {}
        if "GetEditorialCheckSettings" in query:
            return {"getEditorialCheckSettings": {"id": "editorial-check-settings", "settings": json.dumps(SETTINGS)}}
        if query.lstrip().startswith("query") and "getItem" in query:
            return {"getItem": self.stored.get(variables.get("id"))}
        if "mutation" in query:
            self.sent.append(json.loads(json.dumps(variables)))
        return {}


@given("the site writes in English, Latin American Spanish and Simplified Chinese, with English as its primary language")
def step_site(context):
    context.settings = SETTINGS


@given('an authoring client for the tenant "{tenant}"')
def step_client(context, tenant):
    context.stored = {}
    context.recording = RecordingClient(tenant_id=tenant, stored=context.stored)
    context.tenant = tenant


@given('the Story "{lineage}" is stored in "{language}" in the language group "{group}"')
def step_stored(context, lineage, language, group):
    stored_id = f"{lineage}-v1"   # Item ids are not tenant-prefixed (tenancy.TENANT_SCOPED_RECORD_ID_MODELS)
    context.stored[stored_id] = {"id": stored_id, "tenantId": context.tenant, "lineageId": lineage, "versionNumber": 1, "language": language,
                                 "languageGroupId": group}


def _story(lineage: str, **extra) -> dict:
    return {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "type": "article", "status": "draft",
            "slug": lineage, "title": "Rivers", **extra}


@when('a writer creates the Story "{lineage}" without naming a language')
def step_create(context, lineage):
    context.recording.create_record("Item", _story(lineage))


@when('a writer saves the Story "{lineage}" again without naming a language')
def step_save_again(context, lineage):
    context.recording.upsert("Item", _story(lineage))


@when('a writer creates the Story "{lineage}" in "{language}" without a language group')
def step_create_translation(context, lineage, language):
    try:
        context.recording.create_record("Item", _story(lineage, language=language))
        context.error = None
    except ValueError as error:
        context.error = error


def _written(context) -> dict:
    (sent,) = context.recording.sent
    return sent["input"]


@then('the Item written has the language "{language}"')
def step_written_language(context, language):
    assert _written(context)["language"] == language, _written(context)


@then('its language group is "{group}"')
def step_written_group(context, group):
    assert _written(context)["languageGroupId"] == group, _written(context)


@then("the write is refused because a translation names the primary Story's lineage as its language group")
def step_refused(context):
    assert context.error is not None and "language group" in str(context.error), context.error


@then("no Item was sent to the data API")
def step_nothing_sent(context):
    assert context.recording.sent == []


@then("the backfill wrote no row")
def step_backfill_nothing(context):
    assert context.client.updates == []


@then('the translation of "{lineage}" into "{language}" has the lineage "{expected}"')
def step_derived(context, lineage, language, expected):
    assert localization_lineage_id(lineage, language) == expected


@then("a translation lineage cannot itself be translated")
def step_not_twice(context):
    try:
        localization_lineage_id("story-rivers--zh-Hans", "es-419")
    except ValueError:
        return
    raise AssertionError("a translation of a translation was accepted")


@given('the Story "{lineage}" in "{language}" and its translations into "{first}" and "{second}"')
def step_group(context, lineage, language, first, second):
    context.client = FakeAuthoringClient()
    rows = context.client.tables.setdefault("Item", {})
    for tag, story in ((language, lineage), (first, f"{lineage}--{first}"), (second, f"{lineage}--{second}")):
        for number in (1, 2):
            rows[f"{story}-v{number}"] = {"id": f"{story}-v{number}", "lineageId": story, "versionNumber": number, "language": tag,
                                          "languageGroupId": lineage, "versionState": "current" if number == 2 else "superseded"}


@when('the language group "{group}" is read for "{language}"')
def step_read_group(context, group, language):
    context.client.calls.clear()
    context.found = context.client.list_by_index("itemsByLanguageGroup", group, sort_eq=language)


@then('only the rows of "{lineage}" are returned')
def step_only(context, lineage):
    assert {row["lineageId"] for row in context.found} == {lineage} and len(context.found) == 2, context.found


@then("they were read with one query on the language group index")
def step_one_query(context):
    assert context.client.calls == [("list_by_index", "itemsByLanguageGroup", "story-rivers")], context.client.calls


@given('a saved Story version in "{language}"')
def step_saved_in(context, language):
    context.version = {"id": "story-rivers--zh-Hans-v1", "language": language}


@then('the language the checks use for it is "{language}"')
def step_checks_use(context, language):
    assert story_language(context.version, context.settings) == language


@then('a Story not saved yet is checked in "{language}"')
def step_new_story(context, language):
    assert story_language(None, context.settings) == language


@given("a saved Story version with no language")
def step_no_language(context):
    context.version = {"id": "story-old-v1"}


@then('asking its language is refused, naming "{command}"')
def step_refused_naming(context, command):
    try:
        story_language(context.version, context.settings)
    except ItemLanguageMissing as error:
        assert command in str(error), error
        return
    raise AssertionError("a row without a language was read as some language")


@given("three Item rows written before the language fields existed, one of them superseded")
def step_old_rows(context):
    context.client = FakeAuthoringClient()
    rows = context.client.tables.setdefault("Item", {})
    for row_id, lineage, number, state in (("story-a-v1", "story-a", 1, "superseded"), ("story-a-v2", "story-a", 2, "current"),
                                           ("story-b-v1", "story-b", 1, "draft")):
        rows[row_id] = {"id": row_id, "lineageId": lineage, "versionNumber": number, "versionState": state, "updatedAt": f"2026-10-0{number}T00:00:00Z"}
    context.old_ids = ["story-a-v1", "story-a-v2", "story-b-v1"]
    context.printed = []


@given('one row of the Story "{lineage}" already stored in "{language}" in the group "{group}"')
def step_translated_row(context, lineage, language, group):
    context.client.tables["Item"][f"{lineage}-v1"] = {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current",
                                                      "language": language, "languageGroupId": group, "updatedAt": "2026-11-01T00:00:00Z"}
    context.translated_id = f"{lineage}-v1"


def _run(context, dry_run: bool) -> None:
    context.client.calls.clear()
    context.client.updates.clear()
    context.printed = []
    run_languages(context.client, primary="en", dry_run=dry_run, rate=1000, sleep=lambda seconds: None, echo=context.printed.append)


@when('the operator backfills the languages with "papyrus stories languages"')
def step_run(context):
    _run(context, dry_run=False)


@when("the operator backfills the languages again")
def step_run_again(context):
    _run(context, dry_run=False)


@when('the operator previews the language backfill with "--dry-run"')
def step_run_dry(context):
    _run(context, dry_run=True)


@then("the three older rows have the language \"en\" and their own lineage as their group")
def step_old_written(context):
    for row_id in context.old_ids:
        row = context.client.tables["Item"][row_id]
        assert row["language"] == "en" and row["languageGroupId"] == row["lineageId"], row


@then("each keeps its own update time")
def step_kept_time(context):
    for row_id in context.old_ids:
        number = context.client.tables["Item"][row_id]["versionNumber"]
        assert context.client.tables["Item"][row_id]["updatedAt"] == f"2026-10-0{number}T00:00:00Z"


@then('the "zh-Hans" row is not written')
def step_translated_untouched(context):
    assert context.translated_id not in {payload["id"] for _, payload in context.client.updates}
    assert context.client.tables["Item"][context.translated_id]["language"] == "zh-Hans"


@then("the rows were read through the version-state index, with no table scan")
def step_index_reads(context):
    reads = [call for call in context.client.calls if call[0] not in ("update",) and call[1] != "PublishedItemSummary"]
    assert reads and all(call[0] == "list_by_index" and call[1] == "itemLanguageFieldsByVersionState" for call in reads), reads


@then('the summary says "{text}"')
def step_summary(context, text):
    line = next(line for line in context.printed if line.startswith("stories\tlanguages\tItem\t") and ("dry run" in line or "\twrite\t" in line))
    assert text in line, line


@then('the published summary says "{text}"')
def step_published_summary(context, text):
    line = next(line for line in context.printed if line.startswith("stories\tlanguages\tPublishedItem\t") and ("dry run" in line or "\twrite\t" in line))
    assert text in line, line


@given("two published rows written before the language fields existed")
def step_old_published(context):
    rows = context.client.tables.setdefault("PublishedItem", {})
    for lineage in ("story-a", "story-b"):
        rows[f"published-{lineage}"] = {"id": f"published-{lineage}", "itemLineageId": lineage, "sourceItemId": f"{lineage}-v1", "status": "published"}
    context.old_published = ["published-story-a", "published-story-b"]


@given('the published row of "{lineage}" already in "{language}" in the group "{group}"')
def step_translated_published(context, lineage, language, group):
    context.client.tables["PublishedItem"][f"published-{lineage}"] = {"id": f"published-{lineage}", "itemLineageId": lineage, "sourceItemId": f"{lineage}-v1",
                                                                      "status": "published", "language": language, "languageGroupId": group}
    context.translated_published = f"published-{lineage}"


@then('the two older published rows have the language "en" and their own lineage as their group')
def step_old_published_written(context):
    for row_id in context.old_published:
        row = context.client.tables["PublishedItem"][row_id]
        assert row["language"] == "en" and row["languageGroupId"] == row["itemLineageId"], row


@then("the translated published row is not written")
def step_translated_published_untouched(context):
    assert ("PublishedItem", context.translated_published) not in {(model, payload["id"]) for model, payload in context.client.updates}
    assert context.client.tables["PublishedItem"][context.translated_published]["language"] == "zh-Hans"


@then("the second backfill wrote no row")
def step_second_nothing(context):
    assert context.client.updates == []


@then('it printed one "would write" line per older row')
def step_would_write(context):
    assert len([line for line in context.printed if line.endswith("would write") and "\tItem\t" in line]) == len(context.old_ids), context.printed
