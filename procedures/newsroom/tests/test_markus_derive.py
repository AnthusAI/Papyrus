from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from papyrus_content.markus_renderer.content_markup import split_front_matter
from papyrus_content.markus_renderer.derive import (
    MAX_BODY_IR_BYTES,
    compose_source,
    derive_body,
    plain_paragraphs,
)

FIXTURES = Path(__file__).parent / "fixtures" / "markus-derive"


def derive_fixture(name: str):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    front_matter_yaml, body = split_front_matter(text)
    return derive_body(front_matter_yaml, body)


class MarkusDeriveTests(unittest.TestCase):
    def test_plain_article_derives_an_envelope(self) -> None:
        result = derive_fixture("plain.md")
        self.assertTrue(result.ok, result.errors)
        document = result.body_ir["document"]
        self.assertEqual(document["children"][0]["type"], "paragraph")
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(result.body_ir["schemaVersion"], 1)
        self.assertEqual(result.body_ir["markus"]["version"], "0.5.1")

    def test_plain_paragraphs_match_the_source(self) -> None:
        result = derive_fixture("plain.md")
        self.assertEqual(
            plain_paragraphs(result.body_ir),
            ["First paragraph here.", "Second paragraph wraps a line."],
        )

    def test_image_and_citation_fixture(self) -> None:
        result = derive_fixture("image-and-citation.md")
        self.assertTrue(result.ok, result.errors)
        papyrus = result.body_ir["papyrus"]
        self.assertEqual(len(papyrus["images"]), 1)
        image = next(iter(papyrus["images"].values()))
        self.assertEqual(image["src"], "images/a.png")
        self.assertEqual(image["layout"], "full")
        key_groups = list(papyrus["citations"].values())
        self.assertEqual(key_groups, [["a"], ["a"], ["b", "a"]])
        self.assertEqual(len(papyrus["bibliography"]), 2)
        self.assertIn("Source A", papyrus["bibliography"][0])
        self.assertEqual(list(papyrus["citationLists"].values()), ["apa"])

    def test_pull_quote_directive_is_valid(self) -> None:
        result = derive_fixture("pull-quote.md")
        self.assertTrue(result.ok, result.errors)
        names = [block.get("name") for block in result.body_ir["document"]["children"]]
        self.assertIn("pull-quote", names)

    def test_bad_fixtures_report_their_codes(self) -> None:
        expected = {
            "bad-directive.md": "markus-validation",
            "bad-citation.md": "citation-key",
            "bad-image.md": "image-src",
        }
        for name, code in expected.items():
            with self.subTest(name=name):
                result = derive_fixture(name)
                self.assertFalse(result.ok)
                self.assertIsNone(result.body_ir)
                self.assertEqual(result.errors[0].code, code)

    def test_invalid_front_matter_is_reported(self) -> None:
        result = derive_body("title: [unclosed", "Body.\n")
        self.assertEqual(result.errors[0].code, "front-matter")

    def test_unknown_image_attribute_is_reported(self) -> None:
        result = derive_body("", '::image{src="a.png" bogus="1"}\n')
        self.assertEqual(result.errors[0].code, "image-attrs")

    def test_unclosed_fence_is_a_syntax_error(self) -> None:
        result = derive_body("", ":::pull-quote\nnever closed\n")
        self.assertFalse(result.ok)
        self.assertIn(result.errors[0].code, {"markus-syntax", "markus-validation"})

    def test_oversized_body_is_rejected(self) -> None:
        body = ("A paragraph of filler text for the size guard.\n\n" * 50_000)
        self.assertGreater(len(body), 2_000_000)
        result = derive_body("", body)
        self.assertFalse(result.ok)
        self.assertEqual(result.errors[0].code, "too-large")
        self.assertGreater(MAX_BODY_IR_BYTES, 0)

    def test_compose_source_is_verbatim_for_the_body(self) -> None:
        self.assertEqual(compose_source("title: T\n", "\nBody\n"), "---\ntitle: T\n---\n\nBody\n")
        self.assertEqual(compose_source("", "Body\n"), "Body\n")
        self.assertEqual(compose_source(None, "Body\n"), "Body\n")

    def test_derive_does_not_shell_out(self) -> None:
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("subprocess used")):
            self.assertTrue(derive_fixture("plain.md").ok)


if __name__ == "__main__":
    unittest.main()
