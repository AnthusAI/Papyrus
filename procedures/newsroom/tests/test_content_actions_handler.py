from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_client import FakeAuthoringClient  # noqa: E402

HANDLER_PATH = Path(__file__).resolve().parents[3] / "amplify/functions/content-actions/handler.py"
specification = importlib.util.spec_from_file_location("content_actions_handler", HANDLER_PATH)
content_actions_handler = importlib.util.module_from_spec(specification)
specification.loader.exec_module(content_actions_handler)

FRONT_MATTER = "title: Hello\n"


def event(field: str, payload, *, as_string: bool = True) -> dict:
    import json

    return {
        "fieldName": field,
        "arguments": {"input": json.dumps(payload) if as_string else payload},
        "identity": {"username": "editor-one", "sub": "sub-1"},
    }


def save_payload(**changes) -> dict:
    values = {
        "id": None,
        "type": "article",
        "slug": "my-post",
        "section": "articles",
        "frontMatterYaml": FRONT_MATTER,
        "bodyMarkus": "Hello **x**\n",
        "aliases": [],
        "expectedContentHash": None,
    }
    values.update(changes)
    return values


class ContentActionsHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeAuthoringClient()
        patcher = mock.patch.object(
            content_actions_handler, "create_authoring_client", return_value=(self.client, {})
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, field: str, payload, **kwargs) -> dict:
        return content_actions_handler.handler(event(field, payload, **kwargs), None)

    def test_derive_ok_reports_size_and_optional_ir(self) -> None:
        result = self.call("deriveMarkus", {"frontMatterYaml": FRONT_MATTER, "bodyMarkus": "Hello **x**\n"})
        self.assertTrue(result["ok"])
        self.assertGreater(result["bodyIrBytes"], 0)
        self.assertNotIn("bodyIr", result)
        with_ir = self.call(
            "deriveMarkus", {"frontMatterYaml": FRONT_MATTER, "bodyMarkus": "Hello\n", "includeIr": True}
        )
        self.assertIn("bodyIr", with_ir)

    def test_derive_accepts_dict_input(self) -> None:
        result = self.call(
            "deriveMarkus", {"frontMatterYaml": FRONT_MATTER, "bodyMarkus": "Hi\n"}, as_string=False
        )
        self.assertTrue(result["ok"])

    def test_derive_bad_body_returns_errors_without_raising(self) -> None:
        result = self.call("deriveMarkus", {"frontMatterYaml": FRONT_MATTER, "bodyMarkus": "::nope\n::\n"})
        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"][0]["code"])

    def test_save_then_stale_hash_conflicts(self) -> None:
        first = self.call("saveItemDraft", save_payload())
        self.assertTrue(first["ok"])
        item = first["item"]
        self.assertEqual(item["status"], "draft")
        self.assertEqual(item["slug"], "my-post")
        self.assertEqual(item["versionNumber"], 1)

        second = self.call(
            "saveItemDraft",
            save_payload(id=item["id"], bodyMarkus="Changed\n", expectedContentHash=item["contentHash"]),
        )
        self.assertTrue(second["ok"])

        stale = self.call(
            "saveItemDraft",
            save_payload(id=item["id"], bodyMarkus="Again\n", expectedContentHash=item["contentHash"]),
        )
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["errors"][0]["code"], "conflict")

    def test_publish_then_unpublish(self) -> None:
        item = self.call("saveItemDraft", save_payload())["item"]
        published = self.call("publishItem", {"id": item["id"]})
        self.assertTrue(published["ok"])
        self.assertTrue(published["changed"])
        self.assertEqual(published["versionNumber"], 1)
        self.assertIn(published["publishedId"], self.client.tables["PublishedItem"])

        unpublished = self.call("unpublishItem", {"id": item["id"]})
        self.assertEqual(unpublished, {"ok": True, "changed": True})
        self.assertNotIn(published["publishedId"], self.client.tables.get("PublishedItem", {}))

    def test_publish_missing_item_is_not_found(self) -> None:
        result = self.call("publishItem", {"id": "item-missing"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["code"], "not-found")

    def test_unexpected_exception_propagates(self) -> None:
        item = self.call("saveItemDraft", save_payload())["item"]
        self.client.fail_after = ("upsert", "PublishedItem")
        with self.assertRaises(RuntimeError):
            self.call("publishItem", {"id": item["id"]})

    def test_unknown_field_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.call("somethingElse", {})

    def test_actor_falls_back_to_unknown(self) -> None:
        self.assertEqual(content_actions_handler.actor_from_event({}), "unknown")
        self.assertEqual(content_actions_handler.actor_from_event({"identity": {"sub": "s"}}), "s")


if __name__ == "__main__":
    unittest.main()
