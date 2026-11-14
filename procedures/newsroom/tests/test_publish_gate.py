from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contextlib
import io
import json
import unittest
from unittest import mock

from papyrus_content import publish_gate
from papyrus_content.publishing import DryRunClient, ItemFields, PublishError, publish_item, save_item
from fake_client import FakeAuthoringClient  # noqa: E402

ITEM = "item-articles-gate"


def draft_client(approval: str | None = None) -> FakeAuthoringClient:
    client = FakeAuthoringClient()
    save_item(client, ItemFields(type="article", slug="gate", section="articles", front_matter_yaml="title: Gate\n", body_markus="Hi.\n", aliases=[], id=ITEM), actor="t")
    if approval:
        publish_gate.set_publish_approval(client, approval, by="t")
    return client


class PublishGateTests(unittest.TestCase):
    def test_default_is_not_required_and_garbage_falls_back(self):
        client = FakeAuthoringClient()
        self.assertEqual(publish_gate.read_settings(client)["approval"], "not_required")
        client.tables["EditorialCheckSettings"] = {"publish-gate": {"id": "publish-gate", "settings": "{not json"}}
        self.assertEqual(publish_gate.publish_approval(client), "not_required")

    def test_setting_round_trips_as_json_text_in_site_data(self):
        client = FakeAuthoringClient()
        publish_gate.set_publish_approval(client, "required", by="op", now="2026-10-31T00:00:00Z")
        row = client.tables["EditorialCheckSettings"]["publish-gate"]
        self.assertEqual(json.loads(row["settings"])["approval"], "required")
        self.assertEqual(publish_gate.read_settings(client)["updatedBy"], "op")

    def test_dry_run_plans_the_request_and_writes_nothing(self):
        client = draft_client("required")
        target = DryRunClient(client)
        with self.assertRaises(PublishError) as raised:
            publish_item(target, ITEM, actor="cli")
        self.assertEqual(raised.exception.code, "approval-required")
        self.assertEqual([entry["model"] for entry in target.planned], ["ReviewRequest"])
        self.assertEqual(client.tables.get("ReviewRequest", {}), {})

    def test_withdrawn_request_is_raised_again_with_a_new_id(self):
        client = draft_client("required")
        with self.assertRaises(PublishError):
            publish_item(client, ITEM, actor="cli")
        (first,) = client.tables["ReviewRequest"]
        from papyrus_content import review_requests

        review_requests.withdraw_review(client, first, by="op")
        with self.assertRaises(PublishError):
            publish_item(client, ITEM, actor="cli")
        self.assertEqual(len(client.tables["ReviewRequest"]), 2)

    def test_cli_show_and_set_with_dry_run(self):
        client = FakeAuthoringClient()
        from papyrus_content.cli import dispatch

        def run(*flags):
            out = io.StringIO()
            with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, {"sub": "me"})), contextlib.redirect_stdout(out):
                dispatch("content", "publish-gate", list(flags))
            return out.getvalue()

        self.assertIn("approval=not_required", run("show"))
        self.assertIn("dry run", run("set", "--approval", "required", "--dry-run"))
        self.assertEqual(publish_gate.publish_approval(client), "not_required")
        self.assertIn("written", run("set", "--approval", "required"))
        self.assertEqual(publish_gate.publish_approval(client), "required")
        self.assertEqual(json.loads(run("show", "--json"))["approval"], "required")
        with self.assertRaises(ValueError):
            run("set", "--approval", "maybe")


if __name__ == "__main__":
    unittest.main()
