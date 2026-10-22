"""The reader feedback export: comments, with the rating each one explains, as JSON Lines for the Cyclotron loop."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content import reader_commands  # noqa: E402
from papyrus_content.reader_steering.feedback_export import SCHEMA, encode_lines, feedback_records, list_comments  # noqa: E402
from reader_privacy import scan_files  # noqa: E402

READER = str(uuid.UUID(int=7))


def comment(number: int, **changes) -> dict:
    base = {
        "id": f"cmt-{number:032x}", "subjectKey": "item-one", "readerId": READER, "body": f"Because {number}", "parentId": None, "ratingContext": None,
        "state": "visible", "createdAt": f"2026-10-22T0{number}:00:00.000Z", "updatedAt": f"2026-10-22T0{number}:00:00.000Z",
    }
    return {**base, **changes}


class RecordTests(unittest.TestCase):
    def test_a_rationale_comes_out_next_to_the_rating_it_explains_attributed_by_reader_id(self) -> None:
        (record,) = feedback_records([comment(1, ratingContext='{"dimension":"real","value":4}')])
        self.assertEqual(
            record,
            {
                "schema": SCHEMA, "source": "reader", "status": "active", "commentId": comment(1)["id"], "readerId": READER, "subject": "item-one", "subjectKind": "item",
                "parentId": None, "createdAt": comment(1)["createdAt"], "updatedAt": comment(1)["updatedAt"], "rating": {"dimension": "real", "value": 4}, "rationale": "Because 1",
            },
        )

    def test_a_plain_comment_has_no_rating_and_a_toggle_context_is_kept(self) -> None:
        records = list(feedback_records([comment(1), comment(2, ratingContext={"dimension": "up", "value": 1}), comment(3, ratingContext="not json"), comment(4, ratingContext='{"dimension":"real"}')]))
        self.assertEqual([record["rating"] for record in records], [None, {"dimension": "up", "value": 1}, None, None])

    def test_submissions_are_marked_and_replies_keep_their_parent(self) -> None:
        records = list(feedback_records([comment(1, subjectKey="sub-" + "a" * 24), comment(2, parentId=comment(1)["id"])]))
        self.assertEqual([(record["subjectKind"], record["parentId"]) for record in records], [("submission", None), ("item", comment(1)["id"])])

    def test_hidden_and_deleted_comments_are_retracted_without_their_text(self) -> None:
        for state in ("hidden", "deleted"):
            (record,) = feedback_records([comment(1, state=state, body="", ratingContext='{"dimension":"real","value":4}')])
            self.assertEqual((record["status"], "rationale" in record, "rating" in record), ("retracted", False, False), state)
            self.assertEqual(record["readerId"], READER)

    def test_since_is_exclusive_and_the_order_is_by_update_time(self) -> None:
        comments = [comment(3), comment(1), comment(2, updatedAt="2026-10-22T09:00:00.000Z")]
        self.assertEqual([record["commentId"] for record in feedback_records(comments)], [comment(1)["id"], comment(3)["id"], comment(2)["id"]])
        self.assertEqual([record["commentId"] for record in feedback_records(comments, "2026-10-22T01:00:00.000Z")], [comment(3)["id"], comment(2)["id"]])
        self.assertEqual(list(feedback_records(comments, "2026-10-22T09:00:00.000Z")), [])

    def test_lines_are_compact_json_and_hold_no_site_subject_person_id_or_email(self) -> None:
        text = encode_lines(feedback_records([comment(1, ratingContext='{"dimension":"real","value":4}'), comment(2, state="hidden")]))
        self.assertEqual(len(text.splitlines()), 2)
        for line in text.splitlines():
            json.loads(line)
        self.assertEqual(scan_files({"feedback.jsonl": text}, allowed_reader_ids=[READER]), {})
        self.assertNotIn("handle", text, "attribution is the public readerId only")


class Pages:
    def __init__(self, *pages: list[dict]) -> None:
        self.pages = list(pages)
        self.queries: list[dict] = []

    def graphql(self, query: str, variables: dict) -> dict:
        self.queries.append(variables)
        index = len(self.queries) - 1
        return {"listReaderComments": {"items": self.pages[index], "nextToken": f"t{index}" if index + 1 < len(self.pages) else None}}


class CommandTests(unittest.TestCase):
    def test_every_page_is_read(self) -> None:
        client = Pages([comment(1), None], [comment(2)])
        self.assertEqual([row["id"] for row in list_comments(client)], [comment(1)["id"], comment(2)["id"]])
        self.assertEqual([call["nextToken"] for call in client.queries], [None, "t0"])

    def run_command(self, flags: list[str], pages: Pages) -> str:
        with mock.patch.object(reader_commands, "create_authoring_client", return_value=(pages, None)):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                reader_commands.reader_feedback(flags)
            return buffer.getvalue()

    def test_export_since_prints_json_lines(self) -> None:
        out = self.run_command(["export", "--since", "2026-10-22T01:00:00Z"], Pages([comment(1), comment(2, ratingContext='{"dimension":"useful","value":5}')]))
        (line,) = out.splitlines()
        self.assertEqual((json.loads(line)["commentId"], json.loads(line)["rating"]), (comment(2)["id"], {"dimension": "useful", "value": 5}))

    def test_export_writes_a_file_with_out(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "feedback.jsonl"
            self.run_command(["export", "--out", str(target)], Pages([comment(1)]))
            self.assertEqual(len(target.read_text(encoding="utf-8").splitlines()), 1)

    def test_bad_usage_is_refused(self) -> None:
        for flags in ([], ["import"], ["export", "--since", "yesterday"]):
            with self.assertRaises(ValueError):
                self.run_command(flags, Pages([]))

    def test_the_command_is_ported(self) -> None:
        from papyrus_content.cli import is_ported_command

        self.assertTrue(is_ported_command("reader", "feedback"))


if __name__ == "__main__":
    unittest.main()
