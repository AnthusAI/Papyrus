"""`papyrus stories note` (a person's note) and `papyrus stories agent-note` (an AI agent's note, never a Message)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from fake_client import FakeAuthoringClient  # noqa: E402
from tenant_support import IAM_IDENTITY  # noqa: E402

from papyrus_content import story_commands  # noqa: E402
from papyrus_content.operator_errors import GraphQLRequestError, OperatorError  # noqa: E402
from papyrus_content.story_agent_notes import AGENT_NOTE_ROLE, save_agent_note, story_agent_notes  # noqa: E402
from papyrus_content.story_reporting import story_thread_id  # noqa: E402

HANDLER_PATH = Path(__file__).resolve().parents[3] / "amplify/functions/content-actions/handler.py"
specification = importlib.util.spec_from_file_location("content_actions_handler_notes", HANDLER_PATH)
handler_module = importlib.util.module_from_spec(specification)
specification.loader.exec_module(handler_module)

NOW = "2026-11-03T12:00:00Z"
LINEAGE = "item-story"


def story_client() -> FakeAuthoringClient:
    first = {"id": LINEAGE, "lineageId": LINEAGE, "versionNumber": 1, "versionState": "superseded", "headline": "A story", "title": "A story", "stage": "reporting"}
    second = {"id": f"{LINEAGE}-v2", "lineageId": LINEAGE, "versionNumber": 2, "versionState": "current", "headline": "A story", "title": "A story", "stage": "reporting"}
    return FakeAuthoringClient({"Item": [first, second]})


class StoredBodies:
    """Stands in for the upload slot: keeps the body and writes the ModelAttachment row the upload Lambda would write."""

    def __init__(self, client: FakeAuthoringClient) -> None:
        self.client = client
        self.bodies: dict[str, bytes] = {}

    def upload(self, _client, attachment, body):
        self.bodies[attachment["id"]] = bytes(body)
        self.client.tables.setdefault("ModelAttachment", {})[attachment["id"]] = {**attachment, "status": "active"}
        return attachment

    def read(self, attachment):
        return self.bodies[attachment["id"]]


def run_note(client, *flags, signed_in: bool) -> tuple[str, str, BaseException | None]:
    out, err, failure = io.StringIO(), io.StringIO(), None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
            mock.patch.object(story_commands, "create_authoring_client", return_value=(client, {})), \
            mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=signed_in):
        try:
            story_commands.stories_note(list(flags))
        except BaseException as error:  # noqa: BLE001
            failure = error
    return out.getvalue(), err.getvalue(), failure


def graphql_posting(client, *, refuse: str | None = None, calls: list | None = None):
    def graphql(query, variables=None):
        if calls is not None:
            calls.append(variables)
        if refuse:
            raise GraphQLRequestError(f"GraphQL request failed: {refuse}\nCheck your newsroom identity with `papyrus auth status`.")
        client.tables.setdefault("Message", {})[variables["id"]] = {"id": variables["id"], "threadId": variables["threadId"], "sequenceNumber": variables["sequenceNumber"]}
        return {"postMessage": {"id": variables["id"], "authorSub": "sub-1", "authorLabel": "editor@example.test", "role": "human", "createdAt": NOW, "sequenceNumber": variables["sequenceNumber"]}}
    return graphql


class PersonNoteTests(unittest.TestCase):
    def test_a_signed_in_note_is_stamped_by_the_backend_and_ignores_a_supplied_label(self):
        client, calls = story_client(), []
        client.graphql = graphql_posting(client, calls=calls)
        out, err, failure = run_note(client, "--story", LINEAGE, "--body", "Corroborated.", "--author-label", "ChatGPT", signed_in=True)
        self.assertIsNone(failure)
        self.assertNotIn("authorLabel", calls[0])
        self.assertIn("is ignored", err)
        lines = out.splitlines()
        self.assertEqual(lines[0], f"stories\tnote\t{LINEAGE}\tnote\twrite")
        self.assertTrue(lines[1].startswith("stories\tnote\tposted\t"))

    def test_a_failed_save_prints_no_write_line_and_fails_in_one_honest_line(self):
        client = story_client()
        client.graphql = graphql_posting(client, refuse="Not Authorized to access postMessage on type Mutation")
        out, _err, failure = run_note(client, "--story", LINEAGE, "--body", "x", signed_in=True)
        self.assertNotIn("write", out)
        self.assertNotIn("posted", out)
        self.assertIsInstance(failure, OperatorError)
        self.assertEqual(str(failure), "The note was not saved: GraphQL request failed: Not Authorized to access postMessage on type Mutation")

    def test_a_dry_run_prints_its_dry_run_line_and_writes_nothing(self):
        client = story_client()
        out, _err, failure = run_note(client, "--story", LINEAGE, "--body", "x", "--dry-run", signed_in=True)
        self.assertIsNone(failure)
        self.assertEqual(out.strip(), f"stories\tnote\t{LINEAGE}\tnote\tdry run")
        self.assertEqual(client.write_calls(), [])

    def test_the_iam_lane_needs_a_label_and_writes_a_system_message_not_a_person(self):
        client = story_client()
        _out, _err, failure = run_note(client, "--story", LINEAGE, "--body", "x", signed_in=False)
        self.assertIsInstance(failure, ValueError)
        out, _err, failure = run_note(client, "--story", LINEAGE, "--body", "x", "--author-label", "ops", signed_in=False)
        self.assertIsNone(failure)
        message = next(iter(client.tables["Message"].values()))
        self.assertEqual((message["role"], message["authorKind"]), ("system", "operator"))
        self.assertIn("\twrite", out)

    def test_every_message_kind_a_person_can_write_goes_through_post_message(self):
        client, calls = story_client(), []
        client.graphql = graphql_posting(client, calls=calls)
        for kind in story_commands.STORY_MESSAGE_KINDS:
            _out, _err, failure = run_note(client, "--story", LINEAGE, "--body", "x", "--kind", kind, signed_in=True)
            self.assertIsNone(failure)
        self.assertEqual([call["messageKind"] for call in calls], list(story_commands.STORY_MESSAGE_KINDS))
        self.assertEqual([call["sequenceNumber"] for call in calls], [1, 2, 3, 4, 5])
        self.assertIn(story_thread_id(LINEAGE), client.tables["MessageThread"])


class AgentNoteTests(unittest.TestCase):
    def save(self, client, stored, **changes):
        values = {"agent": "ChatGPT", "body": "Vercel corroborates the disclosure.\nSecond line.", "by_sub": "sub-1", "now": NOW}
        values.update(changes)
        with mock.patch("papyrus_content.story_agent_notes.upload_attachment_body", side_effect=stored.upload):
            return save_agent_note(client, LINEAGE, **values)

    def test_an_agent_note_is_an_attachment_owned_by_the_story_and_never_a_message(self):
        client = story_client()
        stored = StoredBodies(client)
        result = self.save(client, stored, reference_lineage_id="reference-a", version_number=2)
        self.assertNotIn("Message", client.tables)
        self.assertNotIn("MessageThread", client.tables)
        attachment = client.tables["ModelAttachment"][result["attachmentId"]]
        self.assertEqual((attachment["ownerKind"], attachment["ownerId"], attachment["ownerLineageId"], attachment["role"]), ("item", LINEAGE, LINEAGE, AGENT_NOTE_ROLE))
        body = json.loads(stored.bodies[result["attachmentId"]])
        self.assertEqual((body["ai"], body["agent"], body["runBy"]), (True, "ChatGPT", {"kind": "user", "sub": "sub-1"}))
        self.assertEqual((body["summary"], body["referenceLineageId"], body["versionNumber"]), ("Vercel corroborates the disclosure.", "reference-a", 2))

    def test_notes_are_read_back_oldest_first_with_the_agent_label(self):
        client = story_client()
        stored = StoredBodies(client)
        self.save(client, stored, agent="Claude", body="Later.", now="2026-11-03T13:00:00Z")
        self.save(client, stored, agent="ChatGPT", body="Earlier.")
        notes = story_agent_notes(client, LINEAGE, read_body=stored.read)
        self.assertEqual([(note["agent"], note["body"]) for note in notes], [("ChatGPT", "Earlier."), ("Claude", "Later.")])

    def test_an_empty_note_an_unnamed_agent_and_a_missing_version_are_refused(self):
        client = story_client()
        stored = StoredBodies(client)
        for changes in ({"body": "  "}, {"agent": " "}, {"version_number": 9}):
            with self.assertRaises(ValueError):
                self.save(client, stored, **changes)
        self.assertNotIn("ModelAttachment", client.tables)

    def test_a_missing_story_is_refused(self):
        with self.assertRaises(ValueError):
            save_agent_note(FakeAuthoringClient(), "nope", agent="a", body="b")

    def test_the_mutation_stamps_the_signed_in_sub_and_refuses_a_caller_without_one(self):
        client = story_client()
        stored = StoredBodies(client)
        event = {"fieldName": "addStoryAgentNote", "arguments": {"input": json.dumps({"lineageId": LINEAGE, "agent": "ChatGPT", "body": "A note.", "runBy": {"sub": "forged"}})},
                 "identity": {"username": "editor-one", "sub": "sub-1", "issuer": "https://cognito.example.test/pool", "claims": {}}}
        with mock.patch.object(handler_module, "create_authoring_client", return_value=(client, {})), \
                mock.patch("papyrus_content.story_agent_notes.upload_attachment_body", side_effect=stored.upload):
            result = handler_module.handler(event, None)
            self.assertTrue(result["ok"])
            self.assertEqual(json.loads(next(iter(stored.bodies.values())))["runBy"], {"kind": "user", "sub": "sub-1"})
            anonymous = handler_module.handler({**event, "identity": IAM_IDENTITY}, None)
            self.assertFalse(anonymous["ok"])
            self.assertEqual(anonymous["errors"][0]["code"], "not-signed-in")
            refused = handler_module.handler({**event, "arguments": {"input": json.dumps({"lineageId": LINEAGE, "agent": "x", "body": ""})}}, None)
            self.assertEqual(refused["errors"][0]["code"], "agent-note-rejected")
        self.assertEqual(len(stored.bodies), 1)
        self.assertNotIn("Message", client.tables)

    def test_the_cli_on_the_signed_in_lane_calls_the_mutation_and_prints_write_only_when_it_saved(self):
        client, sent = story_client(), []

        def graphql(query, variables=None):
            sent.append(json.loads(variables["input"]))
            return {"addStoryAgentNote": json.dumps({"ok": True, "attachmentId": "model-attachment-1"})}

        client.graphql = graphql
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(story_commands, "create_authoring_client", return_value=(client, {})), \
                mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=True):
            story_commands.stories_agent_note(["--story", LINEAGE, "--agent", "ChatGPT", "--body", "A note.", "--reference", "reference-a"])
        self.assertEqual(sent[0]["agent"], "ChatGPT")
        self.assertEqual(sent[0]["referenceLineageId"], "reference-a")
        self.assertEqual(out.getvalue().splitlines()[0], f"stories\tagent-note\t{LINEAGE}\tChatGPT\twrite")

        client.graphql = lambda query, variables=None: {"addStoryAgentNote": json.dumps({"ok": False, "errors": [{"message": "Story nope has no version 9."}]})}
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(story_commands, "create_authoring_client", return_value=(client, {})), \
                mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=True):
            with self.assertRaises(OperatorError) as raised:
                story_commands.stories_agent_note(["--story", LINEAGE, "--agent", "ChatGPT", "--body", "A note."])
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(str(raised.exception), "The agent note was not saved: Story nope has no version 9.")

    def test_show_lists_the_agent_notes_labelled_as_ai(self):
        client = story_client()
        stored = StoredBodies(client)
        self.save(client, stored)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(story_commands, "create_authoring_client", return_value=(client, {})), \
                mock.patch("papyrus_content.story_agent_notes.download_attachment_buffer", side_effect=lambda _client, attachment: stored.read(attachment)):
            story_commands.stories_show(["--story", LINEAGE])
        line = next(line for line in out.getvalue().splitlines() if "\tagent-note\t" in line)
        self.assertEqual(line.split("\t")[3:], [NOW, "AI agent ChatGPT", "Vercel corroborates the disclosure."])


if __name__ == "__main__":
    unittest.main()
