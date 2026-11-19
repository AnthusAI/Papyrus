"""Steps for the pod load features (PPY-50a7f5): `papyrus pod load` runs through the real CLI against an in-memory newsroom.

The pod steps (``pod_steps.py``) make and edit the pod; these steps load it into a ``FakeAuthoringClient`` and read the Items back. Signing in is the
fake: ``graphql_authoring.create_authoring_client`` hands out the scenario's newsroom and counts the sign-ins, and the network stays closed.
"""
from __future__ import annotations

import io
import json
import shlex
import socket
import subprocess
import sys
import urllib.request
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from behave import given, step, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus import cli  # noqa: E402
from papyrus.pod import load as pod_load  # noqa: E402
from papyrus.pod.notes import parse  # noqa: E402
from papyrus_content import graphql_authoring, publish_gate, story_checklist  # noqa: E402
from papyrus_content.item_stars import effective_rating  # noqa: E402
from papyrus_content.pod_claims import pod_record  # noqa: E402
from papyrus_content.publishing import PublishError, publish_item  # noqa: E402
from papyrus_content.story_reporting import current_story_version, save_story_version, story_versions  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

GIT = ["git", "-c", "user.name=Pod Test", "-c", "user.email=pod-test", "-c", "commit.gpgsign=false"]
NOW = "2026-11-17T12:00:00Z"


def _newsroom(context) -> FakeAuthoringClient:
    if "client" not in context or context.client is None:
        context.client = FakeAuthoringClient()
    return context.client


def _git(context, *arguments: str) -> str:
    done = subprocess.run([*GIT, "-C", str(context.pod), *arguments], check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _note(context, path: str) -> dict:
    front, _, _ = parse((context.pod / path).read_text(encoding="utf-8"))
    return front


def _lineage(context, path: str) -> str:
    return pod_load.lineage_for(str(_note(context, path)["id"]), None)


def _current(context, path: str) -> dict:
    return current_story_version(_newsroom(context), _lineage(context, path))


def _run_load(context, line: str) -> None:
    words = shlex.split(line)
    assert words[:3] == ["papyrus", "pod", "load"], line
    client = _newsroom(context)
    context.sign_ins = 0
    context.page_builds = getattr(context, "page_builds", 0)

    def sign_in(*args, **kwargs):
        context.sign_ins += 1
        return client, {}

    def page_build(client, options, result, **kwargs):
        # The site's page build, faked: it is asked for once for each publish that changed something, and nothing leaves the process.
        context.page_builds += 1 if result.changed else 0
        return {}

    def closed(label):
        def fake(*args, **kwargs):
            raise AssertionError(f"touched {label}")
        return fake

    out, err = io.StringIO(), io.StringIO()
    if getattr(context, "delivery_files", None) is None:
        from papyrus_content.announcements.records_fakes import MemoryDeliveryFiles

        context.delivery_files = MemoryDeliveryFiles()   # a Delivery's words are files in S3; the spec keeps them in memory
    with ExitStack() as stack:
        stack.enter_context(patch("papyrus_content.announcements.deliveries.AttachmentFiles", lambda client: context.delivery_files))
        stack.enter_context(patch.object(graphql_authoring, "create_authoring_client", sign_in))
        stack.enter_context(patch("papyrus_content.publish_commands.run_site_triggers", page_build))
        stack.enter_context(patch.object(urllib.request, "urlopen", closed("urlopen")))
        stack.enter_context(patch.object(socket, "create_connection", closed("network")))
        stack.enter_context(redirect_stdout(out))
        stack.enter_context(redirect_stderr(err))
        try:
            context.status = cli.main([str(context.pod) if word == "POD" else word for word in words[1:]])
        except SystemExit as stop:
            context.status = int(stop.code or 0)
    context.output, context.error = out.getvalue(), err.getvalue()


# ---- Given -----------------------------------------------------------------------------------------------------------

@given("a signed-in newsroom with no stories")
def empty_newsroom(context):
    context.client = FakeAuthoringClient()


@given('the pod has a "{path}" folder of site settings')
def site_settings(context, path):
    target = context.pod / path / "projection.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"site": "Example"}), encoding="utf-8")


@given("the pod has no site settings")
def no_site_settings(context):
    (context.pod / "web" / "projection.json").unlink(missing_ok=True)


@given("the pod's changes are committed")
def changes_committed(context):
    _git(context, "add", "-A")
    _git(context, "commit", "-q", "-m", "More notes")


@given("the pod is loaded")
def pod_is_loaded(context):
    _run_load(context, "papyrus pod load POD")
    assert context.status == 0, (context.output, context.error)


@given('a person saved a new version of the story for the note "{path}"')
def person_saved_version(context, path):
    client = _newsroom(context)
    latest = current_story_version(client, _lineage(context, path))
    save_story_version(client, _lineage(context, path), front_matter_yaml=json.loads(latest["metadata"])["frontMatterYaml"], body_markus="A person rewrote this.\n",
                       actor="Ryan", change_reason="Edited in the newsroom", now=NOW)


@given('a person moved the story for the note "{path}" to the stage "{stage}"')
def person_moved_stage(context, path, stage):
    from papyrus_content.content_item_lifecycle import with_stage

    client = _newsroom(context)
    row = with_stage(current_story_version(client, _lineage(context, path)), stage)
    client.update_record("Item", {"id": row["id"], "stage": stage, "headStageKey": row["headStageKey"]})


@given("the newsroom requires a person's approval before anything publishes")
def site_requires_approval(context):
    publish_gate.set_publish_approval(_newsroom(context), "required", by="behave", now=NOW)


@step('a person closes every required step of the story for the note "{path}" except the rating')
def person_closes_steps(context, path):
    client, lineage = _newsroom(context), _lineage(context, path)
    with ExitStack() as stack:
        stack.enter_context(patch("papyrus_content.editorial_commands.read_item_check_run", lambda _item_id: None))
        stack.enter_context(patch("papyrus_content.assignments_workflow.load_assignment_research_packet_entries", lambda _client, _assignment_id: []))
        story_checklist.sync_checklist(client, lineage, now=NOW)
        person = {"kind": "person", "label": "Editor"}
        for row in story_checklist.read_steps(client, lineage):
            if row["state"] != "open" or row["stepKey"] not in story_checklist.required_keys() or row["stepKey"] == story_checklist.RATED_KEY:
                continue
            if row["stepKey"].startswith("review_"):
                story_checklist.set_step(client, lineage, row["stepKey"], "done", actor=person, note="Read it through.", now=NOW)
            else:
                story_checklist.set_step(client, lineage, row["stepKey"], "skipped", actor=person, reason="Covered elsewhere.", now=NOW)


# ---- When ------------------------------------------------------------------------------------------------------------

@when('I load the pod with "{line}"')
def load_pod(context, line):
    _run_load(context, line)


@when('I load the pod again with "{line}"')
def load_pod_again(context, line):
    _newsroom(context).calls.clear()
    context.page_builds = 0
    _run_load(context, line)


@when('an automation publishes the story for the note "{path}"')
def automation_publishes(context, path):
    context.publish_error = None
    try:
        publish_item(_newsroom(context), _current(context, path)["id"], actor="automation:newsroom", now=NOW)
    except PublishError as error:
        context.publish_error = error


@when('an editor publishes the story for the note "{path}"')
def editor_publishes(context, path):
    context.publish_error = None
    with patch("papyrus_content.editorial_commands.read_item_check_run", lambda _item_id: None):
        try:
            publish_item(_newsroom(context), _current(context, path)["id"], actor="editor", approved_by="editor-sub", now=NOW)
        except PublishError as error:
            context.publish_error = error


@when('I run "papyrus stories show" for the note "{path}"')
def stories_show(context, path):
    from papyrus_content import story_commands

    out = io.StringIO()
    with patch.object(story_commands, "create_authoring_client", lambda *args, **kwargs: (_newsroom(context), {})), redirect_stdout(out):
        story_commands.stories_show(["--story", _lineage(context, path)])
    context.output = out.getvalue()


# ---- Then: the run ---------------------------------------------------------------------------------------------------

@then("the load signed in once")
def signed_in_once(context):
    assert context.sign_ins == 1, context.sign_ins


@then("the load did not sign in")
def did_not_sign_in(context):
    assert context.sign_ins == 0, context.sign_ins


@then("nothing was written to the newsroom")
def nothing_written(context):
    assert _newsroom(context).write_calls() == [], _newsroom(context).write_calls()


@then("the newsroom has no stories")
def no_stories(context):
    assert not _newsroom(context).tables.get("Item"), _newsroom(context).tables.get("Item")


@then("the load output says that nothing was published")
def says_nothing_published(context):
    assert "nothing was published" in context.output, context.output


# ---- Then: what a note became ----------------------------------------------------------------------------------------

@then('the story for the note "{path}" has the {field} "{value}"')
def story_field(context, path, field, value):
    column = {"body": "bodyMarkus"}.get(field, field)
    assert str(_current(context, path).get(column)).strip() == value, (field, _current(context, path).get(column))


@then('the story for the note "{path}" carries the pod key "{key}" with the value "{value}"')
def pod_key(context, path, key, value):
    record = pod_record(_current(context, path))
    assert str(record.get(key)) == value, (key, record)


@then('the story for the note "{path}" carries the pod key "{key}" as the note says it')
def pod_key_as_noted(context, path, key):
    assert pod_record(_current(context, path))[key] == str(_note(context, path)[key]), (key, pod_record(_current(context, path)))


@then('the story for the note "{path}" carries no pod key "{key}"')
def no_pod_key(context, path, key):
    assert key not in pod_record(_current(context, path)), pod_record(_current(context, path))


@then('the story for the note "{path}" records the note\'s id')
def records_id(context, path):
    assert pod_record(_current(context, path))["id"] == _note(context, path)["id"]


@then('the story for the note "{path}" records the commit the pod is at')
def records_commit(context, path):
    assert pod_record(_current(context, path))["commit"] == _git(context, "rev-parse", "HEAD")


@then('the story for the note "{path}" has {count:d} version')
@then('the story for the note "{path}" has {count:d} versions')
def version_count(context, path, count):
    assert len(story_versions(_newsroom(context), _lineage(context, path))) == count, [row["id"] for row in story_versions(_newsroom(context), _lineage(context, path))]


@then('the story for the note "{path}" keeps the note\'s front matter and body word for word')
def keeps_text(context, path):
    from papyrus_content.markus_renderer.content_markup import split_front_matter

    wanted_front, wanted_body = split_front_matter((context.pod / path).read_text(encoding="utf-8"))
    row = _current(context, path)
    assert json.loads(row["metadata"])["frontMatterYaml"] == wanted_front.lstrip("\n")
    assert row["bodyMarkus"] == wanted_body


@then('the story for the note "{path}" is a draft that is not live')
def is_draft(context, path):
    row = _current(context, path)
    client = _newsroom(context)
    assert row["status"] == "draft", row["status"]
    assert not client.tables.get("PublishedItem"), client.tables.get("PublishedItem")


@then('the story for the note "{path}" is published')
def is_published(context, path):
    row = _current(context, path)
    assert row["status"] == "published" and row["stage"] == "published", (row["status"], row["stage"])
    assert _newsroom(context).tables.get("PublishedItem"), "no published row"


@then('the story for the note "{path}" is still a draft with no live page')
def still_a_draft(context, path):
    from papyrus_content.publishing import published_item_id_for

    assert _current(context, path)["status"] == "draft", _current(context, path)["status"]
    assert _newsroom(context).get_record("PublishedItem", published_item_id_for(_lineage(context, path))) is None


@then("the site's page build was asked for {count:d} time")
@then("the site's page build was asked for {count:d} times")
def page_builds_asked(context, count):
    assert getattr(context, "page_builds", 0) == count, getattr(context, "page_builds", 0)


@then("no story is published")
def none_published(context):
    client = _newsroom(context)
    assert not client.tables.get("PublishedItem"), client.tables.get("PublishedItem")
    assert all(row.get("status") != "published" for row in client.tables.get("Item", {}).values())


# ---- Then: claims ----------------------------------------------------------------------------------------------------

@then('the story for the note "{path}" has no star rating in the newsroom')
def no_star_rating(context, path):
    row = _current(context, path)
    assert row.get("starRating") is None and not row.get("starRatedBy"), row
    assert effective_rating(row)["stars"] == 0, effective_rating(row)


@then('the publish was refused with the code "{code}"')
def refused_with_code(context, code):
    assert context.publish_error is not None and context.publish_error.code == code, context.publish_error


@then('the publish was refused saying "{text}"')
def refused_saying(context, text):
    assert context.publish_error is not None and text in context.publish_error.message, context.publish_error


@then('the rating step is still open for the story for the note "{path}"')
def rating_step_open(context, path):
    from papyrus_content.story_checklist import rated_problem

    assert rated_problem(_newsroom(context), _current(context, path)), "the rated step was satisfied"


@then('the load output says "{text}"')
def output_says(context, text):
    assert text in context.output, context.output


# ---- Announcement and Delivery notes as history (features_backend/pod-load-announcements.feature, PPY-e78134) ---------------------------------------------------

def _delivery_rows(context, channel):
    rows = [row for row in _newsroom(context).list_records("Delivery") if row["channel"] == channel]
    assert rows, f"the newsroom has no {channel} Delivery"
    return rows[0]


@then("the newsroom has {announcements:d} Announcement and {deliveries:d} Delivery")
@then("the newsroom has {announcements:d} Announcements and {deliveries:d} Deliveries")
def newsroom_history_counts(context, announcements, deliveries):
    client = _newsroom(context)
    assert (len(client.list_records("AnnouncementDecision")), len(client.list_records("Delivery"))) == (announcements, deliveries)


@then('the loaded Delivery for "{channel}" is "{state}" in manual mode with the words "{words}"')
def loaded_delivery_words(context, channel, state, words):
    row = _delivery_rows(context, channel)
    assert row["state"] == state and row["mode"] == "manual", row
    assert context.delivery_files.get(row["id"], "v1") == words, context.delivery_files.get(row["id"], "v1")


@then('the loaded Delivery for "{channel}" has {count:d} attempt, number {number:d}, "{outcome}" by "{who}"')
def loaded_delivery_attempts(context, channel, count, number, outcome, who):
    from papyrus_content.announcements.records import attempt_log

    log = attempt_log(_delivery_rows(context, channel))
    assert len(log) == count and log[0]["number"] == number and log[0]["outcome"] == outcome and log[0]["by"] == who, log


@then('the loaded Delivery for "{channel}" records its approval as a claim, with no approved version')
def loaded_delivery_claim(context, channel):
    row = _delivery_rows(context, channel)
    assert row["approvalPolicy"].startswith("recorded in a pod") and row.get("approvedVersion") is None and row.get("approvedBy") is None, row


@then('the loaded Delivery for "{channel}" is in no sparse index of work to do')
def loaded_delivery_no_due(context, channel):
    row = _delivery_rows(context, channel)
    assert row.get("dueKey") is None and row.get("dueAt") is None and row.get("exampleKey") is None, row


@then("the load opened no attempt beyond the one the note records")
def load_opened_no_attempt(context):
    from papyrus_content.announcements.records import attempt_log

    assert sum(len(attempt_log(row)) for row in _newsroom(context).list_records("Delivery")) == 1


@then("the newsroom has 1 story, the Article, and no story for the Announcement or the Delivery note")
def only_the_article(context):
    stories = {row["lineageId"] for row in _newsroom(context).list_records("Item") if row.get("lineageId")}
    assert stories == {_lineage(context, "articles/slow-water.md")}, stories
