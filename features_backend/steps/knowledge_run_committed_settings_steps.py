"""A site's committed knowledge run settings (features_backend/knowledge-run-committed-settings.feature). S3 is moto; the tools are the recording fake shell."""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

import yaml
from behave import given, then, when
from moto import mock_aws

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_cloud import stages as stages_module  # noqa: E402
from papyrus_content.knowledge_cloud.fakes import SETTINGS_KEY, make_run, settings_archive  # noqa: E402

AWS = {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1"}
COMMITTED = {
    "vocabulary.yml": "description: a publication about harbour logistics\nentity_kinds:\n  - {key: vessel, label: ship}\nrelation_types:\n  - {key: berthed_at, label: berthed at}\n",
    "stop-words.txt": "harbour\n",
    "review-guidance.md": "Prefer named vessels.\n",
}
EXAMPLES = REPO_ROOT / "infra" / "amplify-app-shell" / "examples" / "knowledge-run-settings"


def start(context, publication, settings):
    context.settings = dict(settings)
    context.run_, context.shell = make_run(context.work, {"KNOWLEDGE_PUBLICATION": publication}, settings=settings)


@given('a harbour publication "{publication}" whose site commits a vocabulary, stop words and review guidance')
def step_publication(context, publication):
    context.moto = mock_aws()
    context.moto.start()
    context.add_cleanup(context.moto.stop)
    saved = {key: os.environ.get(key) for key in AWS}
    os.environ.update(AWS)
    context.add_cleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v) for k, v in saved.items()])
    context.work = Path(tempfile.mkdtemp())
    context.publication = publication
    start(context, publication, COMMITTED)


@given("the run state still holds an old \"config/vocabulary.yml\" and an old \"config/stop-words.txt\"")
def step_old_copies(context):
    context.run_.state.write_text("config/vocabulary.yml", "entity_kinds:\n  - {key: stale, label: old}\n")
    context.run_.state.write_text("config/stop-words.txt", "stale\n")


@given("the site commits only stop words")
def step_only_stop_words(context):
    start(context, context.publication, {"stop-words.txt": COMMITTED["stop-words.txt"]})


@given("the deployed settings are missing from the asset bucket")
def step_missing(context):
    context.run_.services.assets.pop(SETTINGS_KEY)


@given('the deployed settings hold a file called "{name}"')
def step_stray(context, name):
    context.run_.services.assets[SETTINGS_KEY] = settings_archive({**COMMITTED, name: "x"})


def run_keeping_log(context, stages):
    """Run stages the way a task does, keeping what they print: stdout is the task log, stderr holds a failure."""
    context.stdout, context.stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(context.stdout), contextlib.redirect_stderr(context.stderr):
        context.code = 0
        for stage in stages:
            context.code = stages_module.run_stage(stage, context.run_) or context.code


@when('the stage "{stage}" runs and the task log is kept')
def step_run_logged(context, stage):
    run_keeping_log(context, [stage])


@when('the stages "{first}", "{second}" run and the task log is kept')
def step_run_two_logged(context, first, second):
    run_keeping_log(context, [first, second])


@then('the work directory\'s "{path}" is the committed {what}')
def step_file_is(context, path, what):
    name = Path(path).name
    assert (context.run_.work / path).read_text() == COMMITTED[name]


@then('the work directory has no "{path}"')
def step_file_absent(context, path):
    assert not (context.run_.work / path).exists()


@then('the task log says "{line}" once, however many times the stage pulled its files')
def step_log_once(context, line):
    assert context.stdout.getvalue().count(line) == 1, context.stdout.getvalue()


@then('the task log says "{line}"')
def step_log_says(context, line):
    assert line in context.stdout.getvalue(), context.stdout.getvalue()


@then("the task log says the run state still holds config files that a run no longer reads, naming both")
def step_log_stale(context):
    assert "no longer reads: stop-words.txt, vocabulary.yml" in context.stdout.getvalue(), context.stdout.getvalue()


@then("the topic configuration was given the committed stop words file")
def step_topic(context):
    topic = next(call for call in context.shell.calls if call[:3] == ["papyrus", "knowledge", "topic-config"])
    assert topic[topic.index("--stop-words") + 1] == str(context.run_.config_dir / "stop-words.txt")
    assert (context.run_.config_dir / "stop-words.txt").read_text() == COMMITTED["stop-words.txt"]


@then("the failure says the committed settings are not there and the job stack should be deployed again")
def step_failure_missing(context):
    failure = context.stderr.getvalue()
    assert "are not there" in failure and "deploy the job stack again" in failure, failure


@then("no default vocabulary was used")
def step_no_default(context):
    assert not (context.run_.config_dir / "vocabulary.yml").exists() or "key: organization," not in (context.run_.config_dir / "vocabulary.yml").read_text()


@then('the failure names "{name}" as not a settings file')
def step_failure_stray(context, name):
    failure = context.stderr.getvalue()
    assert name in failure and "not a settings file" in failure, failure


def committed(site):
    return yaml.safe_load((EXAMPLES / site / "vocabulary.yml").read_text())


@then('the committed vocabularies of "{first}" and "{second}" name their publication, their kinds and their relation types')
def step_valid(context, first, second):
    for site in (first, second):
        document = committed(site)
        assert document["publication"] == site and document["entity_kinds"] and document["relation_types"], site


@then("Machines on Machines' vocabulary has a description and a \"what\" and \"not_for\" for every kind")
def step_described(context):
    document = committed("machines-on-machines")
    assert document["description"]
    assert all(kind.get("what") and kind.get("not_for") for kind in document["entity_kinds"])


@then("Shipped's vocabulary has no description, because none has been written")
def step_shipped(context):
    assert "description" not in committed("shipped")
