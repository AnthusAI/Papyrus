"""The knowledge run on any site (features_backend/knowledge-run-any-site.feature). S3 and DynamoDB are moto; the tools are the recording fake shell."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from behave import given, then, when
from moto import mock_aws

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_cloud import stages as stages_module  # noqa: E402
from papyrus_content.knowledge_cloud.config import STAGES  # noqa: E402
from papyrus_content.knowledge_cloud.fakes import make_run  # noqa: E402

AWS = {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1"}
API_ID = "abcdefghij0123456789klmnop"
NEW_SITE = {"KNOWLEDGE_APPSYNC_API_ID": API_ID, "KNOWLEDGE_BEATS_CONFIG": "", "KNOWLEDGE_CONCEPT_KINDS": ""}


def begin(context):
    context.moto = mock_aws()
    context.moto.start()
    context.add_cleanup(context.moto.stop)
    saved = {key: os.environ.get(key) for key in AWS}
    os.environ.update(AWS)
    context.add_cleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v) for k, v in saved.items()])
    context.work = Path(tempfile.mkdtemp())


def start(context, environment, *, seeded, items=1, records=0, execution="manual-1"):
    context.environment, context.seeded = dict(environment), seeded
    context.run_, context.shell = make_run(context.work, context.environment, execution=execution, seeded=seeded)
    context.shell.items, context.shell.records = items, records


@given('a site "{site}" whose References live in the knowledge corpus "{key}", with monitor sources "{sources}"')
def step_corpus_key(context, site, key, sources):
    begin(context)
    start(context, {"KNOWLEDGE_PUBLICATION": site, "KNOWLEDGE_CORPUS_KEY": key, "KNOWLEDGE_MONITOR_SOURCES": sources}, seeded=True)


@given('a site "{site}" with monitor sources "{sources}"')
def step_monitor_sources(context, site, sources):
    begin(context)
    start(context, {"KNOWLEDGE_PUBLICATION": site, "KNOWLEDGE_MONITOR_SOURCES": sources}, seeded=True)


@given('a new site "{site}" with published items and no configuration in its run state')
def step_new_site(context, site):
    begin(context)
    start(context, {**NEW_SITE, "KNOWLEDGE_PUBLICATION": site}, seeded=False)


@given('a new site "{site}" with no published items and no monitor records')
def step_empty_site(context, site):
    begin(context)
    start(context, {**NEW_SITE, "KNOWLEDGE_PUBLICATION": site}, seeded=False, items=0)


@given('a new site "{site}" with no published items and {count:d} monitor records from "{source}"')
def step_records_only(context, site, count, source):
    begin(context)
    start(context, {**NEW_SITE, "KNOWLEDGE_PUBLICATION": site, "KNOWLEDGE_MONITOR_SOURCES": source}, seeded=False, items=0, records=count)


@given('a site "{site}" whose editors wrote their own vocabulary')
def step_own_vocabulary(context, site):
    begin(context)
    start(context, {"KNOWLEDGE_PUBLICATION": site}, seeded=True)


@given('the site names the beats config "{path}"')
def step_beats(context, path):
    start(context, {**context.environment, "KNOWLEDGE_BEATS_CONFIG": path}, seeded=context.seeded, items=context.shell.items)


@when("the whole run goes through all its stages")
def step_whole_run(context):
    context.codes = {stage: stages_module.run_stage(stage, context.run_) for stage in STAGES if stage != "ai-review"}
    context.codes["ai-review"] = stages_module.run_stage("ai-review", context.run_) if context.run_.read_state().get("empty") or context.run_.read_state().get("documents") == 0 else 0


@when('an item is published and the stage "{stage}" runs in execution "{execution}"')
def step_publish_then_run(context, stage, execution):
    start(context, context.environment, seeded=context.seeded, items=1, execution=execution)
    context.code = stages_module.run_stage(stage, context.run_)


def named(shell):
    return [call for call in shell.calls if "--corpus-key" in call]


def called(context, *prefix):
    return [call for call in context.shell.calls if call[: len(prefix)] == list(prefix)]


def item(context, stage):
    key = {"publication": context.run_.config.publication, "runKey": f"2026-W44#{context.run_.config.execution_name}#{stage}"}
    return context.run_.ledger.table.get_item(Key=key)["Item"]


@then('every command that names the corpus names "{key}" and none names "{other}"')
def step_corpus_names(context, key, other):
    keys = [call[call.index("--corpus-key") + 1] for call in named(context.shell)]
    assert keys and set(keys) == {key}, keys
    assert other not in keys


@then('every command that names the corpus names "{key}"')
def step_corpus_names_only(context, key):
    keys = [call[call.index("--corpus-key") + 1] for call in named(context.shell)]
    assert keys and set(keys) == {key}, keys


@then('the run state, the ledger and the actor stay keyed by "{site}"')
def step_keyed(context, site):
    assert context.run_.state.prefix == f"publications/{site}/"
    assert item(context, "projection")["publication"] == site
    assert context.run_.config.actor_name == f"{site.capitalize()} research agent"


@then('the typed extraction was given a vocabulary with the kinds "{a}", "{b}", "{c}" and "{d}"')
def step_kinds(context, a, b, c, d):
    from papyrus_content.knowledge_snapshot.registry import read_vocabulary_kinds

    typed = called(context, "biblicus", "extract", "typed-entities")[0]
    assert read_vocabulary_kinds(Path(typed[typed.index("--vocabulary") + 1])) == [a, b, c, d]


@then('the typed extraction was given a vocabulary with the kind "{kind}"')
def step_kind(context, kind):
    typed = called(context, "biblicus", "extract", "typed-entities")[0]
    assert f"key: {kind}," in Path(typed[typed.index("--vocabulary") + 1]).read_text()


@then('the typed extraction was not given a vocabulary with the kind "{kind}"')
def step_not_kind(context, kind):
    typed = called(context, "biblicus", "extract", "typed-entities")[0]
    assert f"key: {kind}," not in Path(typed[typed.index("--vocabulary") + 1]).read_text()


@then("the run succeeded")
def step_run_ok(context):
    assert set(context.codes.values()) == {0}, context.codes


@then("the snapshot, archive and wiki commands were given no beats config and no concept kinds")
def step_no_beats(context):
    found = [*called(context, "papyrus", "knowledge", "snapshot"), *called(context, "papyrus", "knowledge", "archive"), *called(context, "papyrus", "knowledge", "wiki", "sync")]
    assert len(found) >= 4, found
    assert not [call for call in found if "--beats-config" in call or "--concept-kinds" in call], found


@then("the snapshot command was given no beats config")
def step_snapshot_no_beats(context):
    assert "--beats-config" not in called(context, "papyrus", "knowledge", "snapshot")[0]


@then("a snapshot was written and the site was projected")
def step_snapshot_projected(context):
    assert called(context, "papyrus", "knowledge", "snapshot") and called(context, "papyrus", "ops", "content", "project")


@then("the backend endpoint of the commands is the AppSync address of the API id")
def step_endpoint(context):
    assert context.run_.command_env()["PAPYRUS_GRAPHQL_ENDPOINT"] == f"https://{API_ID}.appsync-api.us-east-1.amazonaws.com/graphql"


@then("every stage's ledger row says \"nothing to do\"")
def step_all_idle(context):
    for stage in STAGES:
        row = item(context, stage)
        assert row["status"] == "succeeded" and row["details"]["status"] == "nothing to do", (stage, row)


@then("no command modelled, extracted, imported, snapshotted or projected anything")
def step_nothing_ran(context):
    for prefix in (("biblicus", "analyze"), ("biblicus", "extract", "typed-entities"), ("papyrus", "knowledge", "publish-run"), ("papyrus", "knowledge", "snapshot"),
                   ("papyrus", "knowledge", "archive"), ("papyrus", "ops", "content", "project")):
        assert not called(context, *prefix), prefix


@then("every stage's ledger row has a cost")
def step_costs(context):
    for stage in STAGES:
        assert item(context, stage)["details"]["cost"]["computeUsd"] > 0, stage


@then("the run's total cost is recorded")
def step_total(context):
    report = json.loads(context.run_.state.read_text(f"runs/2026-W44/cost-{context.run_.config.execution_name}.json"))
    assert report["cost"]["totalUsd"] > 0


@then("the run state says the site has {count:d} document")
def step_documents(context, count):
    state = context.run_.read_state()
    assert state["documents"] == count and state["empty"] is False, state


@then("the records are imported without clusters or extracted entities")
def step_records_import(context):
    imports = called(context, "papyrus", "knowledge", "publish-run")
    assert imports and all("--monitor-records" in call and "--identity" not in call and "--entities" not in call for call in imports), imports


@then("no topic model or typed extraction ran")
def step_no_topics(context):
    assert not called(context, "biblicus", "analyze", "topics") and not called(context, "biblicus", "extract", "typed-entities")
