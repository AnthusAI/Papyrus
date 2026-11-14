"""People's notes and AI agents' notes on a Story (features_backend/story-notes.feature and messages-only-from-people-writers.feature). The backend is a fake."""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import story_commands  # noqa: E402
from papyrus_content.story_agent_notes import save_agent_note, story_agent_notes  # noqa: E402
from tenant_support import IAM_IDENTITY  # noqa: E402
from test_story_notes import LINEAGE, StoredBodies, graphql_posting, handler_module, run_note, story_client  # noqa: E402


@given("a Story with two saved versions")
def _story(context):
    context.client = story_client()
    context.stored = StoredBodies(context.client)
    context.calls = []
    context.out = context.err = ""
    context.failure = None


@when('a signed-in editor adds the note "{text}" and supplies the author label "{label}"')
def _note_with_label(context, text, label):
    context.client.graphql = graphql_posting(context.client, calls=context.calls)
    context.out, context.err, context.failure = run_note(context.client, "--story", LINEAGE, "--body", text, "--author-label", label, signed_in=True)


@then("the note is posted through the postMessage mutation, which has no author argument")
def _posted(context):
    assert context.failure is None, context.failure
    assert len(context.calls) == 1 and "authorSub" not in context.calls[0] and "createdAt" not in context.calls[0]
    assert "Message" in context.client.tables
    assert not any(call[:2] == ("create", "Message") for call in context.client.calls), "a Message was created directly"


@then("no author label was sent to the newsroom")
def _no_label(context):
    assert "authorLabel" not in context.calls[0]


@then("the command warns that the label is ignored")
def _warns(context):
    assert "is ignored" in context.err


@then("the command prints its write line after the note was saved")
def _write_line(context):
    lines = context.out.splitlines()
    assert lines[0].endswith("\twrite") and lines[1].startswith("stories\tnote\tposted\t"), lines


@when("a signed-in editor adds a note and the newsroom refuses it as not authorized")
def _refused(context):
    context.client.graphql = graphql_posting(context.client, refuse="Not Authorized to access postMessage on type Mutation")
    context.out, context.err, context.failure = run_note(context.client, "--story", LINEAGE, "--body", "x", signed_in=True)


@then("the command prints no write line")
def _no_write(context):
    assert "write" not in context.out and "posted" not in context.out, context.out


@then('the command fails with the one-line message "{message}"')
def _fails(context, message):
    assert context.failure is not None and str(context.failure) == message, repr(context.failure)
    assert "\n" not in str(context.failure)


@when("a signed-in editor adds a note as a dry run")
def _dry(context):
    context.out, context.err, context.failure = run_note(context.client, "--story", LINEAGE, "--body", "x", "--dry-run", signed_in=True)


@then("the command prints a dry run line")
def _dry_line(context):
    assert context.failure is None and context.out.strip().endswith("\tdry run"), context.out


@then("no record is written")
def _nothing(context):
    assert context.client.write_calls() == [], context.client.write_calls()


@when('an operator adds a note with the author label "{label}" on the IAM lane')
def _iam(context, label):
    context.out, context.err, context.failure = run_note(context.client, "--story", LINEAGE, "--body", "Checked.", "--author-label", label, signed_in=False)


@then('the message is a system message from an operator labelled "{label}"')
def _system(context, label):
    assert context.failure is None, context.failure
    message = next(iter(context.client.tables["Message"].values()))
    assert (message["role"], message["authorKind"], message["authorLabel"]) == ("system", "operator", label)


def _save(context, agent, body):
    with mock.patch("papyrus_content.story_agent_notes.upload_attachment_body", side_effect=context.stored.upload):
        return save_agent_note(context.client, LINEAGE, agent=agent, body=body, by_sub="sub-1", now="2026-11-03T12:00:00Z")


@given('an AI agent named "{agent}" has saved the note "{text}"')
@when('an AI agent named "{agent}" saves a note on the Story')
def _agent_note(context, agent, text="A finding from the agent."):
    context.written_before = [call for call in context.client.write_calls()]
    context.saved = _save(context, agent, text)


@then('the only record written is a model attachment owned by the Story with the role "{role}"')
def _attachment_only(context, role):
    attachment = context.client.tables["ModelAttachment"][context.saved["attachmentId"]]
    assert attachment["ownerKind"] == "item" and attachment["ownerLineageId"] == LINEAGE and attachment["role"] == role
    assert set(context.client.tables) <= {"Item", "ModelAttachment"}, list(context.client.tables)


@then("no Message and no conversation thread is written")
def _no_message(context):
    assert "Message" not in context.client.tables and "MessageThread" not in context.client.tables


@then('the note names "{agent}" as a label and the signed-in editor who ran the agent')
def _names(context, agent):
    body = json.loads(context.stored.bodies[context.saved["attachmentId"]])
    assert body["agent"] == agent and body["ai"] is True and body["runBy"] == {"kind": "user", "sub": "sub-1"}, body


@then("the Story's agent notes list the note labelled as AI")
def _listed(context):
    notes = story_agent_notes(context.client, LINEAGE, read_body=context.stored.read)
    assert len(notes) == 1 and notes[0]["agent"] == "ChatGPT"


@when("a signed-in editor shows the Story")
def _show(context):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), mock.patch.object(story_commands, "create_authoring_client", return_value=(context.client, {})), \
            mock.patch("papyrus_content.story_agent_notes.download_attachment_buffer", side_effect=lambda _client, attachment: context.stored.read(attachment)):
        story_commands.stories_show(["--story", LINEAGE])
    context.out = out.getvalue()


@then('the show output has an "{kind}" line for "{who}"')
def _show_line(context, kind, who):
    line = next(line for line in context.out.splitlines() if f"\t{kind}\t" in line)
    assert who in line.split("\t"), line


@then("the addStoryAgentNote mutation is authorized for the editor and admin groups and no others")
def _schema_groups(context):
    schema = (REPO_ROOT / "amplify/data/schema.ts").read_text()
    block = re.search(r"  addStoryAgentNote: a\n(.*?)\n\n", schema, re.DOTALL).group(1)
    assert "allow.groups(contentWriteGroups)" in block and "allow.guest" not in block and "allow.publicApiKey" not in block, block
    assert re.search(r'const contentWriteGroups = \["editor", "admin"\];', (REPO_ROOT / "amplify/data/resource.ts").read_text())
    assert 'functionHandler("contentActions", contentActions)' in block


@then("an agent note from a caller with no sign-in is refused")
def _anonymous(context):
    event = {"fieldName": "addStoryAgentNote", "arguments": {"input": json.dumps({"lineageId": LINEAGE, "agent": "ChatGPT", "body": "x"})}, "identity": IAM_IDENTITY}
    with mock.patch.object(handler_module, "create_authoring_client", return_value=(context.client, {})):
        answer = handler_module.handler(event, None)
    assert answer["ok"] is False and answer["errors"][0]["code"] == "not-signed-in"
    assert "ModelAttachment" not in context.client.tables


@when("an AI agent saves an empty note")
def _empty(context):
    context.refused = None
    try:
        _save(context, "ChatGPT", "   ")
    except ValueError as error:
        context.refused = error


@then("the agent note is refused and nothing is written")
def _empty_refused(context):
    assert context.refused is not None
    assert "ModelAttachment" not in context.client.tables
