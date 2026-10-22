from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

import boto3
from behave import given, then, when
from moto import mock_aws

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_cloud import ai_review as review  # noqa: E402
from papyrus_content.knowledge_snapshot.actors import decode_review  # noqa: E402
from papyrus_content.knowledge_cloud import stages as stages_module  # noqa: E402
from papyrus_content.knowledge_cloud.ai_review_test import ACTOR, NOW, TEXT, TYPED, Model, node, relation  # noqa: E402
from papyrus_content.knowledge_cloud.config import STAGES  # noqa: E402
from papyrus_content.knowledge_cloud.fakes import make_run  # noqa: E402
from papyrus_content.knowledge_cloud.stages_test import FakeServices  # noqa: E402

AWS = {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1"}


def names(text: str) -> list[str]:
    return [part.strip().strip('"') for part in text.replace(" and ", ",").split(",") if part.strip()]


def start(context, execution="manual-1", extra=None):
    context.environment = {**(extra or {})}
    context.run_, context.shell = make_run(context.work, context.environment, execution=execution)


@given('the cloud run for the publication "{publication}" in execution "{execution}" started on {day}')
def step_background(context, publication, execution, day):
    context.mock = mock_aws()
    context.mock.start()
    context.add_cleanup(context.mock.stop)
    import os

    context.saved = {key: os.environ.get(key) for key in AWS}
    os.environ.update(AWS)
    context.add_cleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v) for k, v in context.saved.items()])
    context.work = Path(tempfile.mkdtemp())
    context.execution, context.extra, context.applied = execution, {}, []
    start(context, execution)


@then("the stages are, in order: {listing}")
def step_stages(context, listing):
    assert list(STAGES) == [part.strip() for part in listing.split(",")]


def run_named(context, stage, execution=None):
    if execution:
        start(context, execution, context.extra)
    context.code = stages_module.run_stage(stage, context.run_)


@when('the stage "{stage}" runs')
def step_run(context, stage):
    if stage == "ai-review":
        return run_review(context)
    run_named(context, stage)


@when('the stage "{stage}" runs in execution "{execution}"')
def step_run_in(context, stage, execution):
    context.before = len(context.shell.calls)
    context.first_shell = context.shell
    run_named(context, stage, execution)


@when("the stages {stages} run")
@given("the stages {stages} have run")
def step_run_many(context, stages):
    for stage in names(stages):
        assert stages_module.run_stage(stage, context.run_) == 0, stage


@given('the stage "{stage}" has run')
def step_has_run(context, stage):
    assert stages_module.run_stage(stage, context.run_) == 0
    context.before = len(context.shell.calls)


@when('the stage "{stage}" runs and the apply command fails')
def step_run_apply_fails(context, stage):
    context.shell.fail_on = "--apply"
    run_named(context, stage)
    context.shell.fail_on = None


@given('the previous run id "{previous}" is in the state')
def step_previous(context, previous):
    context.run_.state.write_text("corpus/knowledge-run.json", json.dumps({"previousRunId": previous}))


@given("the checkout comes out at a different commit")
def step_stale(context):
    context.shell.head = "b" * 40


@given("the pinned release lacks the projection lease")
def step_no_lease(context):
    context.shell.fail_on = "projection.lease"


@then("the site was fetched at the deployed commit of the Amplify app")
def step_deployed(context):
    fetch = [call for call in context.shell.calls if call[:2] == ["git", "-C"] and "fetch" in call][0]
    assert "d" * 40 in fetch


@then("the pinned release from requirements-publication.txt was installed before the project command")
def step_pinned_installed(context):
    names = [" ".join(call[:2]) for call in context.shell.calls]
    assert names.index("pip install") < names.index("papyrus ops")


@then("the project command ran with the pinned release first on the Python path")
def step_pinned_path(context):
    assert context.shell.envs[-1]["PYTHONPATH"].endswith("/pinned")


@given('the command "{text}" fails')
def step_command_fails(context, text):
    context.shell.fail_on = text


@given('the execution is "{execution}" and asks for a failure in "{stage}"')
def step_inject(context, execution, stage):
    context.extra = {"KNOWLEDGE_FAIL_STAGE": stage}
    start(context, execution, context.extra)


def called(context, text):
    return [call for call in context.shell.calls if text in " ".join(call)]


@then("the stage succeeded")
def step_ok(context):
    assert context.code == 0, context.code


@then("the stage failed")
def step_failed(context):
    assert context.code == 1, context.code


@then('the commands include "{text}"')
def step_include(context, text):
    assert called(context, text), text


@then('no command was given "{text}"')
def step_not_given(context, text):
    assert not called(context, text), called(context, text)


@then('the state in S3 holds "{key}"')
def step_s3_holds(context, key):
    assert context.run_.state.read_text(key) is not None


@then('the state in S3 has no "{key}"')
def step_s3_has_not(context, key):
    assert context.run_.state.read_text(key) is None


@then("the state in S3 records the current topic run as the previous run")
def step_records(context):
    record = json.loads(context.run_.state.read_text("corpus/knowledge-run.json"))
    assert record["previousRunId"] == context.shell.current and record["runOn"] == "2026-10-26"


@then('the identity command was given "{text}"')
def step_identity_given(context, text):
    assert text in " ".join(called(context, "topic-identity")[0])


@then('the identity command was not given "{text}"')
def step_identity_not(context, text):
    assert text not in " ".join(called(context, "topic-identity")[0])


@then("the archive command has the snapshot's options and the Monday of the week \"{monday}\"")
def step_archive(context, monday):
    snapshot = called(context, "knowledge snapshot")[0]
    archive = called(context, "knowledge archive")[0]
    assert snapshot[3:] == archive[3:] and archive[archive.index("--as-of") + 1] == monday


@then('the wiki publish command was given "{flag}"')
def step_wiki(context, flag):
    assert flag in called(context, "knowledge wiki publish")[0]


@then('the ledger says "{stage}" {status} for "{publication}" in "{week}"')
def step_ledger(context, stage, status, publication, week):
    item = context.run_.ledger.table.get_item(Key={"publication": publication, "runKey": f"{week}#{context.run_.config.execution_name}#{stage}"})["Item"]
    assert item["status"] == status, item


@then("the commands were not repeated")
def step_not_repeated(context):
    assert len(context.shell.calls) == context.before


# -- AI review ---------------------------------------------------------------------------------------------------------
@given("the extractor proposed the entities {listing}")
def step_proposed(context, listing):
    context.nodes = [node(name) for name in names(listing)]
    context.answers = {}


@given('the AI reviewer accepts "{name}" quoting "{quote}"')
def step_accept_quote(context, name, quote):
    context.answers[name] = {"verdict": "accept", "evidence": [quote]}


@given('the AI reviewer rejects "{name}" as a size')
def step_reject(context, name):
    context.answers[name] = {"verdict": "reject", "reason": "a size"}


def prepare_review(context):
    run = context.run_
    for stage in ("corpus-sync", "topic-model", "typed-extraction"):
        stages_module.run_stage(stage, run)
    typed_dir = run.run_dir / "typed"
    typed_dir.mkdir(parents=True, exist_ok=True)
    (typed_dir / "output.json").write_text(json.dumps(TYPED))
    texts = run.corpus / "extracted" / "pipeline" / "ext1" / "text"
    texts.mkdir(parents=True, exist_ok=True)
    (texts / "i1.txt").write_text(TEXT)
    run.push(corpus=True, run=True)


def run_review(context):
    import papyrus_content.records as records

    prepare_review(context)
    context.applied = []
    original = records.apply_record_changes
    records.apply_record_changes = lambda client, changes: context.applied.extend(changes)
    context.add_cleanup(lambda: setattr(records, "apply_record_changes", original))
    context.run_.services = FakeServices(context.nodes, context.answers)
    context.code = stages_module.run_stage("ai-review", context.run_)
    assert context.code == 0


@then('"{name}" was accepted by "{actor}"')
def step_accepted(context, name, actor):
    assert any(
        change["expected"]["id"] == f"n-{name}" and change["expected"]["status"] == "accepted"
        and decode_review(change["expected"]["changeReason"]).accepted_by.actor == actor
        for change in context.applied
    )


@then('"{name}" was rejected by "{actor}"')
def step_rejected(context, name, actor):
    assert any(change["expected"]["id"] == f"n-{name}" and change["expected"]["status"] == "rejected" for change in context.applied)


@then("the review log records the decisions")
def step_log(context):
    log = json.loads(context.run_.state.read_text("runs/2026-W44/ai-review.json"))
    assert log["decisions"] and log["model"] == "gpt-6-luna"


@then("nothing was accepted or rejected")
def step_nothing(context):
    assert context.applied == []


@then('the key was read from the SSM parameter "{parameter}"')
def step_key(context, parameter):
    assert context.run_.services.key_parameter == parameter


@given('the accepted entities "{subject}" and "{target}" and the proposed relation "{predicate}" between them')
def step_relation_setup(context, subject, target, predicate):
    context.rel_nodes = {f"l-{subject}": node(subject, status="accepted"), f"l-{target}": node(target, kind="model_family", status="accepted")}
    context.relation = relation(predicate, subject, target)


@given('the AI reviewer accepts the relation quoting "{quote}"')
def step_relation_quote(context, quote):
    context.answers = {"VoxCPM2 (model)->MiniCPM-4 (model_family)": {"verdict": "accept", "evidence": [quote]}}


@when("the AI reviews the relations")
def step_review_relations(context):
    context.patches, _ = review.review_relations([context.relation], context.rel_nodes, review.TypedRun(TYPED, {"i1": TEXT}), Model(context.answers), ACTOR, now=NOW)


@then("the relation stays proposed")
def step_relation_proposed(context):
    assert context.patches == []


@then('the relation is accepted by "{actor}"')
def step_relation_accepted(context, actor):
    metadata = json.loads(context.patches[0]["expected"]["metadata"])
    assert metadata["confirmed"] is True and metadata["acceptedBy"]["actor"] == actor


@given("a new cluster whose members are {titles}")
def step_cluster(context, titles):
    from papyrus_content.knowledge_cloud.ai_review_test import cluster

    context.titles = names(titles)
    context.proposal = cluster()
    context.proposal["evidenceItemIds"] = [str(i) for i in range(len(context.titles))]


@given('the AI reviewer names it "{name}" quoting the first three titles')
def step_cluster_name(context, name):
    model = Model({})
    model._transport = lambda *_a: {"output_text": json.dumps({"verdicts": [{"id": "c0", "verdict": "accept", "evidence": context.titles[:3], "name": name, "reason": "all TTS"}]})}
    context.cluster_model = model


@when("the AI reviews the clusters")
def step_review_clusters(context):
    lookup = dict(zip(context.proposal["evidenceItemIds"], context.titles))
    context.patches, _ = review.review_clusters([context.proposal], lambda ids: [lookup[i] for i in ids], context.cluster_model, ACTOR, now=NOW)


@then('the cluster is accepted as "{name}"')
def step_cluster_accepted(context, name):
    expected = context.patches[0]["expected"]
    assert expected["displayName"] == name and expected["status"] == "accepted"


@given('the deployed site enables the plugins "{plugins}" only')
def step_deployed_plugins(context, plugins):
    context.run_.services.variables["PAPYRUS_PLUGINS"] = plugins


@given("the deployed site enables no plugins")
def step_no_plugins(context):
    context.run_.services.variables["PAPYRUS_PLUGINS"] = ""


@then('the ledger error names "{text}"')
def step_ledger_error(context, text):
    item = context.run_.ledger.table.get_item(Key={"publication": "shipped", "runKey": f"2026-W44#{context.run_.config.execution_name}#projection"})["Item"]
    assert text in item["error"], item


@then("the stages {stages} each fail before running any command")
def step_each_fails(context, stages):
    for stage in names(stages):
        start(context, "manual-1", context.extra)
        context.run_.services.variables["PAPYRUS_PLUGINS"] = ""
        assert stages_module.run_stage(stage, context.run_) == 1, stage
        site_calls = [call for call in context.shell.calls if call[:2] == ["papyrus", "knowledge"] or call[:3] == ["papyrus", "ops", "content"]]
        assert site_calls == [], (stage, site_calls)


@then('the project command passes the plugins "{plugins}"')
def step_project_plugins(context, plugins):
    assert context.run_.command_env()["PAPYRUS_PLUGINS"] == plugins


@given('the Amplify jobs "{first}" succeeded with commit "{slow}" at minute {m1:d} and "{second}" succeeded with commit "{fast}" at minute {m2:d}')
def step_jobs(context, first, slow, m1, second, fast, m2):
    from papyrus_content.knowledge_cloud.command import latest_successful_commit  # noqa: F401

    stamp = lambda minute: dt.datetime(2026, 10, 22, 14, minute, tzinfo=dt.timezone.utc)  # noqa: E731
    context.jobs = [
        {"jobId": first, "status": "SUCCEED", "commitId": slow, "endTime": stamp(m1)},
        {"jobId": second, "status": "SUCCEED", "commitId": fast, "endTime": stamp(m2)},
    ]


@then('the deployed commit is "{commit}" in either order of listing')
def step_deployed_order(context, commit):
    from papyrus_content.knowledge_cloud.command import latest_successful_commit

    assert latest_successful_commit(context.jobs, "app", "main") == commit
    assert latest_successful_commit(list(reversed(context.jobs)), "app", "main") == commit
