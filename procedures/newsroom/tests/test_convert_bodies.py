from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from papyrus_content.convert_bodies_commands import (
    content_convert_bodies,
    convert_bodies,
    derive_from_paragraphs,
    escape_markdown,
    normalize_whitespace,
    split_paragraphs,
)
from papyrus_content.markus_renderer.derive import derive_body, plain_paragraphs
from fake_client import FakeAuthoringClient  # noqa: E402

NASTY_PARAGRAPHS = [
    "Cats & dogs: *stars*",
    "# not a heading",
    "*",
    "_emphasis_ and snake_case_word",
    "[x](y)",
    "<b>bold</b>",
    "# h",
    "1. x",
    "2) y",
    "---",
    "|a|b|",
    ":::x",
    "`code` and ``double``",
    "back\\slash and a\\*b",
    "~~struck~~",
    "+ plus",
    "- minus",
    "line one\nline two",
    "> quote",
    "![img](a.png)",
    "***",
    "“quotes” — dash",
]

SKIPPED_PARAGRAPHS = [
    ("line one\n===", "not-lossless"),
    ("&amp; &lt;", "not-lossless"),
    ("[@key]", "derive-failed:citation-key"),
]


def article(record_id: str, body: list[str] | None, **extra) -> dict:
    return {"id": record_id, "slug": record_id, "type": "article", "body": body, **extra}


class EscapeRoundTripTests(unittest.TestCase):
    def test_escaped_paragraphs_derive_back_to_the_original_text(self) -> None:
        for paragraph in NASTY_PARAGRAPHS:
            with self.subTest(paragraph=paragraph):
                body_markus, body_ir, skip_reason = derive_from_paragraphs([paragraph])
                self.assertIsNone(skip_reason)
                self.assertEqual(
                    [normalize_whitespace(text) for text in plain_paragraphs(body_ir)],
                    [normalize_whitespace(paragraph)],
                )
                self.assertEqual(body_ir, derive_body(None, body_markus).body_ir)

    def test_paragraphs_that_cannot_round_trip_are_reported(self) -> None:
        for paragraph, reason in SKIPPED_PARAGRAPHS:
            with self.subTest(paragraph=paragraph):
                body_markus, body_ir, skip_reason = derive_from_paragraphs([paragraph])
                self.assertEqual(skip_reason, reason)
                self.assertIsNone(body_ir)

    def test_documented_example(self) -> None:
        paragraphs = ["Cats & dogs: *stars*", "# not a heading"]
        body_markus, _, skip_reason = derive_from_paragraphs(paragraphs)
        self.assertIsNone(skip_reason)
        self.assertEqual(body_markus, "Cats & dogs: \\*stars\\*\n\n\\# not a heading")

    def test_escape_leaves_plain_text_alone(self) -> None:
        self.assertEqual(escape_markdown("Plain sentence, with punctuation."), "Plain sentence, with punctuation.")

    def test_split_paragraphs_matches_the_reader_rule(self) -> None:
        self.assertEqual(split_paragraphs("One.\r\n\r\n\r\nTwo.\n\n  \n\nThree."), ["One.", "Two.", "Three."])


class ConvertBodiesTests(unittest.TestCase):
    def test_inline_body_is_converted(self) -> None:
        client = FakeAuthoringClient({"Item": [article("a", ["First para.", "Second para."])]})
        rows = convert_bodies(client, ["Item"], apply=True)
        self.assertEqual([row["status"] for row in rows], ["converted"])
        _, update = client.updates[0]
        self.assertEqual(update["bodyMarkus"], "First para.\n\nSecond para.")
        envelope = json.loads(update["bodyIr"])
        self.assertEqual(plain_paragraphs(envelope), ["First para.", "Second para."])
        self.assertEqual(json.loads(update["metadata"]), {"convertedFrom": "body[]"})
        self.assertNotIn("body", update)
        self.assertNotIn("editorial", update)

    def test_existing_metadata_is_preserved(self) -> None:
        client = FakeAuthoringClient({"Item": [article("a", ["Text."], metadata='{"keep":1}')]})
        convert_bodies(client, ["Item"], apply=True)
        self.assertEqual(json.loads(client.updates[0][1]["metadata"]), {"keep": 1, "convertedFrom": "body[]"})

    def test_attachment_backed_body_is_converted(self) -> None:
        attachments = {
            "p": [
                {"id": "att-1", "role": "published_item_excerpt", "status": "ready", "storagePath": "x"},
                {"id": "att-2", "role": "published_item_body", "status": "ready", "storagePath": "y"},
            ]
        }
        client = FakeAuthoringClient({"PublishedItem": [article("p", [])]}, attachments)
        with mock.patch(
            "papyrus_content.convert_bodies_commands.download_attachment_buffer",
            return_value=b"Alpha line.\n\nBeta *line*.\n",
        ) as download:
            rows = convert_bodies(client, ["PublishedItem"], apply=True)
        download.assert_called_once()
        self.assertEqual(download.call_args.args[1]["id"], "att-2")
        self.assertEqual(rows[0]["status"], "converted")
        self.assertEqual(client.updates[0][1]["bodyMarkus"], "Alpha line.\n\nBeta \\*line\\*.")

    def test_unconvertible_record_is_skipped_and_not_written(self) -> None:
        client = FakeAuthoringClient({"Item": [article("a", ["Fine."]), article("b", ["&amp; entity"])]})
        rows = convert_bodies(client, ["Item"], apply=True)
        self.assertEqual([row["status"] for row in rows], ["converted", "skipped:not-lossless"])
        self.assertEqual([update["id"] for _, update in client.updates], ["a"])

    def test_rerun_is_idempotent(self) -> None:
        client = FakeAuthoringClient({"Item": [article("a", ["Text."])]})
        convert_bodies(client, ["Item"], apply=True)
        client.updates.clear()
        rows = convert_bodies(client, ["Item"], apply=True)
        self.assertEqual([row["status"] for row in rows], ["already-converted"])
        self.assertEqual(client.updates, [])

    def test_dry_run_writes_nothing(self) -> None:
        client = FakeAuthoringClient({"Item": [article("a", ["Text."])]})
        rows = convert_bodies(client, ["Item"], apply=False)
        self.assertEqual([row["status"] for row in rows], ["convertible"])
        self.assertEqual(client.updates, [])


class ConvertBodiesCommandTests(unittest.TestCase):
    def run_command(self, flags: list[str], client: FakeAuthoringClient) -> str:
        output = io.StringIO()
        with mock.patch(
            "papyrus_content.convert_bodies_commands.create_authoring_client", return_value=(client, {})
        ), redirect_stdout(output):
            content_convert_bodies(flags)
        return output.getvalue()

    def test_writes_require_apply(self) -> None:
        client = FakeAuthoringClient({"Item": [article("a", ["Text."])]})
        printed = json.loads(self.run_command(["--json"], client))
        self.assertFalse(printed["apply"])
        self.assertEqual(printed["records"][0]["status"], "convertible")
        self.assertEqual(client.updates, [])
        self.run_command(["--apply"], client)
        self.assertEqual(len(client.updates), 1)

    def test_dry_run_and_apply_conflict(self) -> None:
        with self.assertRaises(ValueError):
            self.run_command(["--dry-run", "--apply"], FakeAuthoringClient({}))

    def test_models_option_limits_the_scan(self) -> None:
        client = FakeAuthoringClient({"Item": [article("a", ["T."])], "PublishedItem": [article("p", ["T."])]})
        printed = json.loads(self.run_command(["--models", "PublishedItem", "--json"], client))
        self.assertEqual([row["model"] for row in printed["records"]], ["PublishedItem"])


class SeedWritesMarkusTests(unittest.TestCase):
    def test_seeded_articles_carry_markus_body_and_no_legacy_body(self) -> None:
        from papyrus_content.seed_edition import SEED_CONTENT_PATH, build_seed_edition_records, load_seed_payload

        payload = load_seed_payload(SEED_CONTENT_PATH)
        source_bodies = {article["slug"]: article["body"] for article in payload["articles"]}
        records = build_seed_edition_records(payload)
        items = [entry["expected"] for entry in records if entry["modelName"] in ("Item", "PublishedItem")]
        self.assertTrue(items)
        for item in items:
            with self.subTest(slug=item["slug"], record=item["id"]):
                self.assertNotIn("body", item)
                envelope = json.loads(item["bodyIr"])
                self.assertEqual(
                    [normalize_whitespace(text) for text in plain_paragraphs(envelope)],
                    [normalize_whitespace(text) for text in source_bodies[item["slug"]]],
                )


if __name__ == "__main__":
    unittest.main()
