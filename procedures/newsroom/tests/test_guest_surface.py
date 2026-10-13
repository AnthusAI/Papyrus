"""What a guest can reach, pinned: reads on six Published models and media/*, nothing else, no writes."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from papyrus_content.publishing import ItemFields, publish_item, save_item
from procedures.newsroom.tests.fake_client import FakeAuthoringClient

REPOSITORY = Path(__file__).resolve().parents[3]
SCHEMA = (REPOSITORY / "amplify" / "data" / "resource.ts").read_text(encoding="utf-8")
STORAGE = (REPOSITORY / "amplify" / "storage" / "resource.ts").read_text(encoding="utf-8")
GUEST_READABLE_MODELS = {
    "PublishedItem",
    "PublishedMediaAsset",
    "PublishedEdition",
    "PublishedEditionItem",
    "PublishedCategorySet",
    "PublishedCategory",
}
PUBLIC_METADATA_KEYS = {"frontMatterYaml", "source", "sourceContentHash", "projection"}
MODEL_START = re.compile(r"^  ([A-Za-z]+): a$", re.MULTILINE)


def schema_blocks() -> dict[str, str]:
    starts = list(MODEL_START.finditer(SCHEMA))
    return {
        start.group(1): SCHEMA[start.start() : starts[position + 1].start() if position + 1 < len(starts) else len(SCHEMA)]
        for position, start in enumerate(starts)
    }


class GuestSurfaceTests(unittest.TestCase):
    def test_guests_read_exactly_the_six_published_models(self) -> None:
        with_guest = {name for name, block in schema_blocks().items() if "allow.guest" in block}
        self.assertEqual(with_guest, GUEST_READABLE_MODELS)

    def test_guest_rules_only_ever_read(self) -> None:
        rules = re.findall(r"allow\.guest\([^)]*\)([^,\n]*)", SCHEMA)
        self.assertEqual(len(rules), len(GUEST_READABLE_MODELS))
        self.assertTrue(all(rule == '.to(["read"])' for rule in rules), rules)

    def test_the_api_key_and_custom_rules_grant_nothing(self) -> None:
        self.assertNotIn("publicApiKey", SCHEMA)
        self.assertNotIn("allow.custom", SCHEMA)
        self.assertNotIn("allow.public", SCHEMA)

    def test_no_custom_operation_is_open_to_guests(self) -> None:
        for name, block in schema_blocks().items():
            if ".mutation(" in block or ".query(" in block:
                self.assertNotIn("allow.guest", block, name)

    def test_storage_guests_read_media_only(self) -> None:
        guest_paths = re.findall(r'"([^"]+)": \[\s*allow\.guest\.to\(\["read"\]\)', STORAGE)
        self.assertEqual(guest_paths, ["media/*"])
        self.assertEqual(STORAGE.count("allow.guest"), 1)

    def test_a_cms_publish_puts_only_known_keys_in_the_guest_readable_item(self) -> None:
        client = FakeAuthoringClient()
        item_id = "item-guest"
        fields = ItemFields(
            type="article",
            slug="guest-check",
            section="articles",
            front_matter_yaml="title: Guest check\n",
            body_markus="Body.\n",
            aliases=[],
            id=item_id,
            source_path="articles/guest-check.md",
        )
        save_item(client, fields, actor="tester", now="2026-10-05T12:00:00Z")
        publish_item(client, item_id, actor="tester", now="2026-10-05T12:00:00Z")
        published = client.tables["PublishedItem"]["published-" + item_id]
        self.assertLessEqual(set(json.loads(published["metadata"])), PUBLIC_METADATA_KEYS)
        self.assertEqual(json.loads(published["editorial"]), {})
        self.assertEqual(json.loads(published["layout"]), {"source": "cms"})


if __name__ == "__main__":
    unittest.main()
