"""A story has exactly one row in the stage head index (features_backend/story-head-stage-index.feature).

The writers run against the shared in-memory fake; the tenant prefix and the capability check run through the real authoring client with a
recording transport. Nothing here reaches a network."""

from __future__ import annotations

import io
import json
import sys
import uuid
from contextlib import redirect_stderr
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient  # noqa: E402
from papyrus_content.publishing import ItemFields, publish_item, save_item, unpublish_item  # noqa: E402
from papyrus_content.story_head_index import run_head_index  # noqa: E402
from papyrus_content.story_reporting import create_story, move_story_stage, repair_story_versions, save_story_version  # noqa: E402
from fake_client import FakeAuthoringClient  # noqa: E402

NOW = "2026-11-09T12:00:00Z"
FRONT = "title: {title}\n"


def lineage_of(title: str) -> str:
    return f"story-{title.lower()}"


def rows_of(context, title: str) -> list[dict]:
    lineage = context.lineages.get(title, lineage_of(title))
    return sorted((row for row in context.client.tables.get("Item", {}).values() if (row.get("lineageId") or row["id"]) == lineage),
                  key=lambda row: int(row.get("versionNumber") or 0))


def version_row(context, title: str, number: int) -> dict:
    return next(row for row in rows_of(context, title) if int(row.get("versionNumber") or 0) == int(number))


def heads_of(context, title: str) -> list[dict]:
    return [row for row in rows_of(context, title) if row.get("headStageKey")]


def item_writes(context) -> list[tuple[str, str, str]]:
    return [call for call in context.client.write_calls() if call[1] == "Item"]


# ---- the writers ------------------------------------------------------------------------------------------------------------------------

@given("an empty newsroom backend")
def step_empty(context):
    context.client = FakeAuthoringClient()
    context.lineages = {}


def seed_story(context, title: str, versions: int = 1, updated_at: str | None = None) -> None:
    lineage = lineage_of(title)
    context.lineages[title] = lineage
    save_item(context.client, ItemFields(type="article", slug=title.lower(), section="news", front_matter_yaml=FRONT.format(title=title),
                                         body_markus=f"{title}, version 1.\n", aliases=[], id=lineage), actor="editor", now=NOW)   # the first row's id is the lineage id
    if updated_at:
        context.client.tables["Item"][lineage]["updatedAt"] = updated_at   # how the row was stored, not a write
    for number in range(2, versions + 1):
        save_story_version(context.client, lineage, front_matter_yaml=FRONT.format(title=title), body_markus=f"{title}, version {number}.\n",
                           actor="editor", change_reason="edit", now=f"2026-11-09T12:0{number}:00Z")


@when('an editor creates the story "{title}" at the idea stage')
def step_create(context, title):
    item = create_story(context.client, title=title, section_key=None, stage="idea", actor="editor", now=NOW)
    context.lineages[title] = item["lineageId"]


@given('the story "{title}" in copywriting with one saved version')
def step_one_version(context, title):
    seed_story(context, title)


@given('the story "{title}" in copywriting with one saved version last changed at "{when_}"')
def step_one_version_at(context, title, when_):
    seed_story(context, title, updated_at=when_)


@given('the story "{title}" in copywriting with two saved versions')
def step_two_versions(context, title):
    seed_story(context, title, versions=2)


@given('the published story "{title}"')
def step_published(context, title):
    seed_story(context, title)
    publish_item(context.client, lineage_of(title), actor="editor", now=NOW)


@given('an editor gave "{title}" {stars:d} stars')
def step_stars(context, title, stars):
    head = heads_of(context, title)[0]
    # What the setItemStars mutation writes: the star fields on the current row, nothing else.
    context.client.update_record("Item", {"id": head["id"], "starRating": stars, "starRatedAt": NOW, "starRatedBy": "editor"})


@given('the story "{title}" whose two versions are both marked current')
def step_muddled(context, title):
    lineage = lineage_of(title)
    context.lineages[title] = lineage
    rows = [{"id": f"{lineage}-v{number}", "lineageId": lineage, "versionNumber": number, "versionState": "current", "stage": "copywriting",
             "type": "article", "status": "draft", "slug": title.lower(), "createdAt": f"2026-11-0{number}T09:00:00Z",
             "versionCreatedAt": f"2026-11-0{number}T09:00:00Z", "updatedAt": f"2026-11-0{number}T09:00:00Z"} for number in (1, 2)]
    for row in rows:
        context.client.tables.setdefault("Item", {})[row["id"]] = row


@when('an editor saves a new version of "{title}"')
def step_save(context, title):
    context.writes_before = len(item_writes(context))
    context.updates_before = len(context.client.updates)
    save_story_version(context.client, context.lineages[title], front_matter_yaml=FRONT.format(title=title), body_markus=f"{title}, again.\n",
                       actor="editor", change_reason="edit", now="2026-11-09T13:00:00Z")


@when('an editor moves "{title}" to the {stage} stage')
def step_move(context, title, stage):
    move_story_stage(context.client, context.lineages[title], stage, actor="editor", now=NOW)


@when('an editor publishes the current version of "{title}"')
def step_publish_current(context, title):
    current = next(row for row in rows_of(context, title) if row.get("versionState") == "current")
    publish_item(context.client, current["id"], actor="editor", now=NOW)


@when('an editor publishes version {number:d} of "{title}"')
def step_publish_version(context, number, title):
    publish_item(context.client, version_row(context, title, number)["id"], actor="editor", now=NOW)


@when('an editor unpublishes "{title}"')
def step_unpublish(context, title):
    unpublish_item(context.client, lineage_of(title), actor="editor", now=NOW)


@when('an operator repairs the versions of "{title}"')
def step_repair(context, title):
    repair_story_versions(context.client, context.lineages[title], apply=True)


@then('the story "{title}" has exactly one head row, in the {stage} stage')
def step_one_head(context, title, stage):
    heads = heads_of(context, title)
    assert len(heads) == 1, [(row["id"], row.get("headStageKey")) for row in rows_of(context, title)]
    assert heads[0]["headStageKey"] == stage and heads[0]["stage"] == stage, heads[0]
    assert heads[0].get("versionState") != "superseded", heads[0]


@then('the head row of "{title}" carries the head stage key "{key}"')
def step_head_key(context, title, key):
    heads = heads_of(context, title)
    assert [row["headStageKey"] for row in heads] == [key], [(row["id"], row.get("headStageKey")) for row in rows_of(context, title)]


@then('the head row of "{title}" is version {number:d}')
def step_head_version(context, title, number):
    heads = heads_of(context, title)
    assert len(heads) == 1 and int(heads[0]["versionNumber"]) == number, [(row["id"], row.get("headStageKey")) for row in rows_of(context, title)]


@then('the head row of "{title}" has {stars:d} stars')
def step_head_stars(context, title, stars):
    assert heads_of(context, title)[0].get("starRating") == stars


@then('version {number:d} of "{title}" is superseded and carries no head stage key')
def step_superseded_no_key(context, number, title):
    row = version_row(context, title, number)
    assert row.get("versionState") == "superseded" and not row.get("headStageKey"), row


@then('version {number:d} of "{title}" carries no head stage key')
def step_no_key(context, number, title):
    row = version_row(context, title, number)
    assert not row.get("headStageKey"), row


@then("saving the version wrote one new Item row and updated one Item row")
def step_same_writes(context):
    writes = item_writes(context)[context.writes_before:]
    assert [kind for kind, _model, _id in writes] == ["create", "update"], writes


@then('the update that superseded version 1 of "{title}" kept its update time "{when_}"')
def step_kept_time(context, title, when_):
    supersede = [payload for model, payload in context.client.updates[context.updates_before:]
                 if model == "Item" and payload["id"] == version_row(context, title, 1)["id"] and payload.get("versionState") == "superseded"]
    assert len(supersede) == 1, context.client.updates
    assert supersede[0].get("updatedAt") == when_, supersede[0]
    assert "headStageKey" in supersede[0] and supersede[0]["headStageKey"] is None, supersede[0]


# ---- the authoring client: tenant prefix and sites without the field ---------------------------------------------------------------

class RecordingClient(PapyrusGraphQLAuthoringClient):
    """The real authoring client with the transport replaced: answers the schema check and records every mutation."""

    def __init__(self, *, tenant_id: str | None, item_fields: list[str]) -> None:
        super().__init__(endpoint=f"https://{uuid.uuid4().hex}.appsync.example.test/graphql", header_factory=lambda body: {}, tenant_id=tenant_id)
        self.item_fields = item_fields
        self.sent: list[dict] = []
        self.schema_checks = 0

    def _send_graphql(self, query, variables=None):
        if "GetEditorialCheckSettings" in query:
            return {"getEditorialCheckSettings": None}   # no stored settings: an English site (the client writes its primary language on new Items)
        if "PapyrusSchemaCheck" in query:
            self.schema_checks += 1
            return {"__type": {"name": "Item", "fields": [{"name": name} for name in self.item_fields]}}
        if "headStageKey" in json.dumps((variables or {}).get("input") or {}) and "headStageKey" not in self.item_fields:
            raise AssertionError("a site without the field would refuse this write")
        self.sent.append(json.loads(json.dumps(variables or {})))
        return {}


ITEM_FIELDS = ["id", "lineageId", "stage", "versionState", "tenantId", "typeStatus", "sectionStatus", "tenantSlug", "updatedAt"]


@given('an authoring client for the tenant "{tenant}" on a site whose data API has the head stage key')
def step_tenant_client(context, tenant):
    context.recording = RecordingClient(tenant_id=tenant, item_fields=[*ITEM_FIELDS, "headStageKey"])


@given("an authoring client on a site whose data API has no head stage key")
def step_old_site_client(context):
    context.recording = RecordingClient(tenant_id=None, item_fields=ITEM_FIELDS)


def head_row(number: int = 1) -> dict:
    return {"id": f"story-x-v{number}", "lineageId": "story-x", "versionNumber": number, "versionState": "current", "stage": "copywriting",
            "type": "article", "status": "draft", "typeStatus": "article#draft", "slug": f"story-x-{number}", "headStageKey": "copywriting"}


@when("the client creates the head row of a story in copywriting")
def step_tenant_create(context):
    context.recording.create_record("Item", head_row())


@when("the client writes two story rows that carry head stage keys")
def step_old_site_writes(context):
    context.stderr = io.StringIO()
    with redirect_stderr(context.stderr):
        context.recording.create_record("Item", head_row(1))
        context.recording.create_record("Item", head_row(2))


@then('the row it sends carries the head stage key "{key}"')
def step_sent_key(context, key):
    sent = [entry["input"] for entry in context.recording.sent if "input" in entry]
    assert sent and sent[-1]["headStageKey"] == key, sent


@then('the row keeps its plain stage "{stage}"')
def step_plain_stage(context, stage):
    assert context.recording.sent[-1]["input"]["stage"] == stage


@then("neither row it sends names the head stage key")
def step_no_key_sent(context):
    sent = [entry["input"] for entry in context.recording.sent if "input" in entry]
    assert len(sent) == 2 and all("headStageKey" not in row for row in sent), sent


@then("the CLI said once that the site has no head stage key yet")
def step_said_once(context):
    text = context.stderr.getvalue()
    assert text.count("has no headStageKey yet") == 1, text


@then("it asked the site for the Item fields only once")
def step_asked_once(context):
    assert context.recording.schema_checks == 1, context.recording.schema_checks


# ---- the backfill -------------------------------------------------------------------------------------------------------------------

@given("a site with stories written before the head stage key existed:")
def step_old_stories(context):
    context.client = FakeAuthoringClient()
    context.lineages = {}
    for record in context.table:
        title, versions, stage = record["story"], int(record["versions"]), record["stage"]
        lineage = lineage_of(title)
        context.lineages[title] = lineage
        for number in range(1, versions + 1):
            head = number == versions
            context.client.tables.setdefault("Item", {})[f"{lineage}-v{number}"] = {
                "id": f"{lineage}-v{number}", "lineageId": lineage, "versionNumber": number, "versionState": "current" if head else "superseded",
                "stage": stage if head else "copywriting", "type": "article", "status": "published" if head and stage == "published" else "draft",
                "versionCreatedAt": f"2026-10-{10 + number}T09:00:00Z", "updatedAt": f"2026-10-{10 + number}T09:3{number}:00Z",
            }


@given('version {number:d} of "{title}" carries the stale head stage key "{key}"')
def step_stale_key(context, number, title, key):
    version_row(context, title, number)["headStageKey"] = key   # stored that way, not written by this scenario


@given("the site's data API has no head stage key yet")
def step_backfill_old_site(context):
    context.client.has_head_stage_key = lambda: False


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def run_backfill(context, *, apply: bool, rate: float = 5.0) -> None:
    context.before_rows = json.loads(json.dumps(context.client.tables.get("Item", {})))
    context.updates_before = len(context.client.updates)
    context.writes_before = len(context.client.write_calls())
    context.output, context.warnings, context.error = [], [], None
    context.clock = FakeClock()
    context.write_times = []
    original = context.client.update_record

    def timed_update(model_name, payload):
        context.write_times.append(context.clock())
        original(model_name, payload)

    context.client.update_record = timed_update
    try:
        context.plan = run_head_index(context.client, apply=apply, rate=rate, sleep=context.clock.sleep, clock=context.clock,
                                      echo=context.output.append, warn=context.warnings.append)
    except ValueError as error:
        context.error = error
    finally:
        context.client.update_record = original


@when("an operator runs the head-index backfill without --apply")
def step_backfill_dry(context):
    run_backfill(context, apply=False)


@when("an operator runs the head-index backfill with --apply at {rate:d} writes a second")
def step_backfill_apply(context, rate):
    run_backfill(context, apply=True, rate=float(rate))


@then("it reports {stories:d} stories, {sets:d} heads to set, {removals:d} keys to remove and {right:d} already right")
def step_counts(context, stories, sets, removals, right):
    counts = context.plan.counts()
    assert (counts["stories"], counts["heads to set"], counts["keys to remove"], counts["already right"]) == (stories, sets, removals, right), counts
    assert any(line.startswith("stories\thead-index\t") and f"stories {stories}" in line for line in context.output), context.output


@then("it lists the head row of each story it would change")
def step_lists(context):
    listed = {line.split("\t")[4] for line in context.output if "\tset\t" in line and "would write" in line}
    heads = {f"{lineage}-v{max(int(row['versionNumber']) for row in context.client.tables['Item'].values() if row['lineageId'] == lineage)}"
             for lineage in context.lineages.values()}
    assert listed == heads, (listed, heads)


@then("it wrote nothing")
def step_wrote_nothing(context):
    assert context.client.write_calls()[context.writes_before:] == []


@then("it updated exactly the head row of each story")
def step_updated_heads(context):
    updated = [payload["id"] for model, payload in context.client.updates[context.updates_before:] if model == "Item"]
    heads = [row["id"] for row in context.before_rows.values() if row.get("versionState") == "current"]
    assert sorted(updated) == sorted(heads), (updated, heads)


@then("every update kept the row's own update time")
def step_kept_times(context):
    for model, payload in context.client.updates[context.updates_before:]:
        assert payload.get("updatedAt") == context.before_rows[payload["id"]]["updatedAt"], payload


@then("no superseded row was written")
def step_no_superseded(context):
    superseded = {row_id for row_id, row in context.before_rows.items() if row.get("versionState") == "superseded"}
    assert not superseded & {payload["id"] for _model, payload in context.client.updates[context.updates_before:]}


@then("it paced the writes at no more than {rate:d} a second")
def step_paced(context, rate):
    gaps = [later - earlier for earlier, later in zip(context.write_times, context.write_times[1:])]
    assert gaps and all(gap >= 1.0 / rate - 1e-9 for gap in gaps), gaps


@then("every story has exactly one head row")
def step_every_story(context):
    for title in context.lineages:
        heads = heads_of(context, title)
        assert len(heads) == 1 and heads[0]["headStageKey"] == heads[0]["stage"], (title, heads)


@then('it reports "{title}" as a lineage for stories repair-versions')
def step_reports_muddled(context, title):
    lineage = context.lineages[title]
    assert [entry["lineageId"] for entry in context.plan.muddled] == [lineage], context.plan.muddled
    assert any(f"repair-versions --story {lineage}" in line for line in context.output), context.output


@then("it did not change the version state of any row")
def step_no_state_change(context):
    for _model, payload in context.client.updates[context.updates_before:]:
        assert "versionState" not in payload, payload


@then("it says the site's data API needs the deploy that adds the head stage index first")
def step_says_deploy(context):
    assert any("needs the deploy that adds the head stage index" in line for line in context.warnings), context.warnings


@then("the backfill refused to write and wrote nothing")
def step_refused(context):
    assert context.error is not None and "needs the deploy" in str(context.error), context.error
    assert context.client.write_calls()[context.writes_before:] == []
