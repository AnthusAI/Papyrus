"""Story CLI edges found in a live test: the Story's lineage id on `stories create`, `write` lines printed only after success,
`stories link-reference` naming the signed-in person, and Messages listed by `stories show`."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from fake_client import FakeAuthoringClient  # noqa: E402

from papyrus_content import story_commands  # noqa: E402
from papyrus_content.operator_errors import OperatorError  # noqa: E402
from papyrus_content.story_reporting import story_anchor_key, story_thread_id  # noqa: E402

LINEAGE = "item-edge-story"
REFERENCE = "reference-edge"


def fresh_client() -> FakeAuthoringClient:
    client = FakeAuthoringClient({
        "Item": [{"id": f"{LINEAGE}-v1", "lineageId": LINEAGE, "versionNumber": 1, "versionState": "current", "headline": "A story", "title": "A story", "stage": "idea", "slug": "a-story", "type": "untyped", "section": "news"}],
        "Reference": [{"id": REFERENCE, "lineageId": REFERENCE, "versionNumber": 1, "versionState": "current", "title": "A source"}],
    })
    client.endpoint = "https://example.test/graphql"
    return client


def run(command, client, *flags, signed_in: bool = False, label: str | None = "Ada Example"):
    out, err, failure = io.StringIO(), io.StringIO(), None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
            mock.patch.object(story_commands, "create_authoring_client", return_value=(client, {})), \
            mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=signed_in), \
            mock.patch("papyrus_content.cli_user_auth.signed_in_label", return_value=label), \
            mock.patch("papyrus_content.story_triggers.deliver_from_environment"), \
            mock.patch.object(story_commands, "print_reminder"), \
            mock.patch.object(story_commands, "reminder_assessment", return_value=None):
        try:
            command(list(flags))
        except BaseException as error:  # noqa: BLE001
            failure = error
    return out.getvalue(), err.getvalue(), failure


def relation_metadata(client) -> dict:
    relation = next(iter(client.tables["SemanticRelation"].values()))
    return json.loads(relation["metadata"])


class CreateTests(unittest.TestCase):
    def test_create_prints_the_lineage_id_on_its_own_labelled_line_and_keeps_the_created_line(self):
        client = fresh_client()
        out, _err, failure = run(story_commands.stories_create, client, "--title", "A new story")
        self.assertIsNone(failure)
        lines = [line.split("\t") for line in out.splitlines()]
        created = next(line for line in lines if line[2] == "created")
        lineage = next(line for line in lines if line[2] == "lineage")
        self.assertEqual(len(created), 4)
        self.assertEqual(created[3], f"{lineage[3]}-v1")
        self.assertEqual(lineage[:3], ["stories", "create", "lineage"])
        self.assertTrue(lines[0][-1] == "write" and lines.index(lines[0]) < lines.index(created))

    def test_a_failed_create_prints_no_write_line(self):
        out, _err, failure = run(story_commands.stories_create, fresh_client(), "--title", "x", "--stage", "bogus")
        self.assertIsNotNone(failure)
        with mock.patch.object(story_commands, "create_story", side_effect=RuntimeError("boom")):
            out, _err, failure = run(story_commands.stories_create, fresh_client(), "--title", "x")
        self.assertIsInstance(failure, RuntimeError)
        self.assertNotIn("write", out)

    def test_a_dry_run_prints_its_dry_run_line_and_writes_nothing(self):
        client = fresh_client()
        out, _err, failure = run(story_commands.stories_create, client, "--title", "x", "--dry-run")
        self.assertIsNone(failure)
        self.assertEqual(out.strip(), "stories\tcreate\tx\tstage idea\ttype site default\tdry run")
        self.assertEqual(client.write_calls(), [])


class WriteLineTests(unittest.TestCase):
    def test_move_prints_write_after_success_and_not_after_failure(self):
        out, _err, failure = run(story_commands.stories_move, fresh_client(), "--story", LINEAGE, "--stage", "reporting")
        self.assertIsNone(failure)
        self.assertEqual(out.splitlines()[0], f"stories\tmove\t{LINEAGE}\treporting\twrite")
        with mock.patch.object(story_commands, "move_story_stage", side_effect=RuntimeError("Not Authorized")):
            out, _err, failure = run(story_commands.stories_move, fresh_client(), "--story", LINEAGE, "--stage", "reporting")
        self.assertIsInstance(failure, RuntimeError)
        self.assertNotIn("write", out)
        self.assertEqual(out, "")

    def test_move_dry_run_keeps_its_line_and_the_published_warning(self):
        client = fresh_client()
        out, err, failure = run(story_commands.stories_move, client, "--story", LINEAGE, "--stage", "published", "--dry-run")
        self.assertIsNone(failure)
        self.assertEqual(out.strip(), f"stories\tmove\t{LINEAGE}\tpublished\tdry run")
        self.assertIn("nothing goes live", err)
        self.assertEqual(client.write_calls(), [])

    def test_link_reference_prints_write_only_after_the_link_was_saved(self):
        with mock.patch.object(story_commands, "link_reference_to_story", side_effect=RuntimeError("Not Authorized")):
            out, _err, failure = run(story_commands.stories_link_reference, fresh_client(), "--story", LINEAGE, "--reference", REFERENCE, "--role", "consulted", "--author-label", "ops")
        self.assertIsInstance(failure, RuntimeError)
        self.assertEqual(out, "")
        out, _err, failure = run(story_commands.stories_link_reference, fresh_client(), "--story", LINEAGE, "--reference", REFERENCE, "--role", "consulted", "--author-label", "ops")
        self.assertIsNone(failure)
        self.assertEqual(out.splitlines()[0], f"stories\tlink-reference\t{LINEAGE}\t{REFERENCE}\tconsulted\twrite")

    def test_set_slug_and_save_version_print_write_after_the_save(self):
        client = fresh_client()
        with mock.patch("papyrus_content.publishing.save_item", side_effect=RuntimeError("boom")):
            out, _err, failure = run(story_commands.stories_set_slug, client, "--story", LINEAGE, "--slug", "new-slug")
        self.assertIsInstance(failure, RuntimeError)
        self.assertNotIn("write", out)
        out, _err, failure = run(story_commands.stories_set_slug, fresh_client(), "--story", LINEAGE, "--slug", "new-slug", "--dry-run")
        self.assertIsNone(failure)
        self.assertTrue(out.strip().endswith("dry run"))
        with mock.patch.object(story_commands, "save_story_version", side_effect=RuntimeError("boom")):
            out, _err, failure = run(story_commands.stories_save_version, fresh_client(), "--story", LINEAGE, "--body", "text", "--reason", "r", "--author-label", "ops")
        self.assertIsInstance(failure, RuntimeError)
        self.assertNotIn("write", out)
        out, _err, failure = run(story_commands.stories_save_version, fresh_client(), "--story", LINEAGE, "--body", "text", "--reason", "r", "--author-label", "ops", "--dry-run")
        self.assertIsNone(failure)
        self.assertEqual(out.strip(), f"stories\tsave-version\t{LINEAGE}\tversion 2\tdry run")


class LinkReferenceActorTests(unittest.TestCase):
    def test_signed_in_the_label_is_optional_and_the_link_names_the_signed_in_person(self):
        client = fresh_client()
        out, err, failure = run(story_commands.stories_link_reference, client, "--story", LINEAGE, "--reference", REFERENCE, "--role", "consulted", signed_in=True)
        self.assertIsNone(failure)
        self.assertEqual(relation_metadata(client)["addedBy"], "Ada Example")
        self.assertEqual(relation_metadata(client)["updatedBy"], "Ada Example")
        self.assertEqual(err, "")
        self.assertIn("\twrite", out.splitlines()[0])

    def test_signed_in_a_supplied_label_cannot_name_someone_else(self):
        client = fresh_client()
        _out, err, failure = run(story_commands.stories_link_reference, client, "--story", LINEAGE, "--reference", REFERENCE, "--role", "cited", "--author-label", "Someone Else", signed_in=True)
        self.assertIsNone(failure)
        self.assertEqual(relation_metadata(client)["addedBy"], "Ada Example")
        self.assertIn("is ignored", err)

    def test_signed_in_with_a_session_that_names_no_one_fails_and_writes_nothing(self):
        client = fresh_client()
        out, _err, failure = run(story_commands.stories_link_reference, client, "--story", LINEAGE, "--reference", REFERENCE, "--role", "consulted", signed_in=True, label=None)
        self.assertIsInstance(failure, OperatorError)
        self.assertEqual(out, "")
        self.assertNotIn("SemanticRelation", client.tables)

    def test_the_iam_lane_still_requires_the_label_and_records_it_as_given(self):
        client = fresh_client()
        _out, _err, failure = run(story_commands.stories_link_reference, client, "--story", LINEAGE, "--reference", REFERENCE, "--role", "consulted")
        self.assertIsInstance(failure, ValueError)
        _out, _err, failure = run(story_commands.stories_link_reference, client, "--story", LINEAGE, "--reference", REFERENCE, "--role", "consulted", "--author-label", "ChatGPT")
        self.assertIsNone(failure)
        self.assertEqual(relation_metadata(client)["addedBy"], "ChatGPT")

    def test_a_dry_run_needs_no_session_and_writes_nothing(self):
        client = fresh_client()
        out, _err, failure = run(story_commands.stories_link_reference, client, "--story", LINEAGE, "--reference", REFERENCE, "--role", "consulted", "--dry-run", signed_in=True)
        self.assertIsNone(failure)
        self.assertTrue(out.strip().endswith("dry run"))
        self.assertEqual(client.write_calls(), [])


class ShowMessagesTests(unittest.TestCase):
    def thread_with(self, client, kind="story_reporting", thread_id=None):
        thread_id = thread_id or story_thread_id(LINEAGE)
        client.tables.setdefault("MessageThread", {})[thread_id] = {"id": thread_id, "threadKind": kind, "primaryAnchorKey": story_anchor_key(LINEAGE)}
        return thread_id

    def message(self, client, thread_id, number, **fields):
        row = {"id": f"message-{number}", "threadId": thread_id, "sequenceNumber": number, "messageKind": "note", "status": "active",
               "authorLabel": "Ada Example", "createdAt": f"2026-11-0{number}T10:00:00Z", "summary": f"Summary {number}", "content": f"Body {number}"}
        row.update(fields)
        client.tables.setdefault("Message", {})[row["id"]] = row

    def test_show_lists_a_persons_note_oldest_first_and_skips_deleted_ones(self):
        client = fresh_client()
        thread = self.thread_with(client)
        self.message(client, thread, 2, summary="Second")
        self.message(client, thread, 1, summary="First")
        self.message(client, thread, 3, deletedAt="2026-11-04T00:00:00Z")
        self.message(client, thread, 4, status="removed")
        out, _err, failure = run(story_commands.stories_show, client, "--story", LINEAGE)
        self.assertIsNone(failure)
        rows = [line.split("\t") for line in out.splitlines() if line.split("\t")[2:3] == ["message"]]
        self.assertEqual([row[5] for row in rows], ["First", "Second"])
        self.assertEqual(rows[0][:5], ["stories", "show", "message", "2026-11-01T10:00:00Z", "Ada Example (note)"])

    def test_show_ignores_other_threads_and_prints_no_message_line_when_there_are_none(self):
        client = fresh_client()
        other = self.thread_with(client, kind="forum", thread_id="thread-other")
        self.message(client, other, 1)
        out, _err, _failure = run(story_commands.stories_show, client, "--story", LINEAGE)
        self.assertNotIn("\tmessage\t", out)


if __name__ == "__main__":
    unittest.main()
