"""`papyrus stories link-story --reference`: a story points a reader to an accepted Reference with the directional `see_also` edge."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for entry in (HERE.parents[2] / "src", HERE.parents[2], HERE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import story_commands  # noqa: E402
from papyrus_content.concept_tags import audit_story_links  # noqa: E402
from papyrus_content.reference_links import ITEM_REFERENCE_LINK_KIND, link_item_reference_see_also  # noqa: E402
from papyrus_content.relation_types import load_relation_type_lookup  # noqa: E402
from papyrus_content.story_links import references_of_story, related_references  # noqa: E402
from story_reference_role_site import SignedInSite  # noqa: E402
from test_story_cli_live_test_edges import run  # noqa: E402
from test_story_links import story  # noqa: E402


def reference(identifier: str, status: str = "accepted", **extra) -> dict:
    return {"id": identifier, "lineageId": f"lin-{identifier}", "versionNumber": 1, "versionState": "current", "curationStatus": status, "title": f"Title {identifier}",
            "sourceUri": f"https://www.example.org/{identifier}", **extra}


def site() -> SignedInSite:
    return SignedInSite({
        "Item": [story("item-big", "A big story", "article", "published", "big"), story("item-post-1", "First post", "post", "published", "post-1")],
        "PublishedItem": [{"id": "published-item-big"}],
        "Reference": [reference("ref-a"), reference("ref-b"), reference("ref-pending", "pending"), reference("ref-rejected", "rejected")],
    }, groups=["editor"], label="Grace Editor")


def link(client, *flags):
    return run(story_commands.stories_link_story, client, *flags, signed_in=True, label="Grace Editor")


def rows(client) -> list[dict]:
    return list(client.tables.get("SemanticRelation", {}).values())


class LinkStoryToReferenceTests(unittest.TestCase):
    def test_the_command_links_several_references_and_prints_title_host_and_status(self):
        client = site()
        out, err, failure = link(client, "--story", "item-big", "--reference", "ref-a", "--reference", "lin-ref-b", "--note", "read this too")
        self.assertIsNone(failure, err)
        lines = [line.split("\t") for line in out.splitlines()]
        self.assertEqual(lines[0], ["stories", "link-story", "item-big", "ref-a", "see_also", "Title ref-a", "host example.org", "status accepted", "write"])
        self.assertEqual(lines[1][3], "ref-b")
        written = rows(client)
        self.assertEqual(len(written), 2)
        row = written[0]
        metadata = json.loads(row["metadata"])
        self.assertEqual((row["predicate"], row["subjectKind"], row["subjectLineageId"], row["objectKind"], row["objectLineageId"], row["relationState"]),
                         ("see_also", "item", "item-big", "reference", "lin-ref-a", "current"))
        self.assertEqual((metadata["kind"], metadata["provenance"], metadata["addedBy"], metadata["note"]), (ITEM_REFERENCE_LINK_KIND, "human", "Grace Editor", "read this too"))
        self.assertEqual(row["subjectStateKey"], "item#item-big#current")

    def test_a_reference_that_is_not_accepted_or_missing_refuses_everything(self):
        for bad, message in (("ref-pending", "pending"), ("ref-rejected", "rejected"), ("ref-none", "not found")):
            client = site()
            out, _err, failure = link(client, "--story", "item-big", "--reference", "ref-a", "--reference", bad)
            self.assertIn(message, str(failure))
            self.assertEqual(rows(client), [])
            self.assertNotIn("write", out)

    def test_a_repeat_writes_nothing_and_a_rejected_edge_is_not_revived(self):
        client = site()
        link(client, "--story", "item-big", "--reference", "ref-a")
        before = len(client.calls)
        out, _err, failure = link(client, "--story", "item-big", "--reference", "ref-a")
        self.assertIsNone(failure)
        self.assertTrue(out.rstrip().endswith("\texists"), out)
        self.assertFalse([call for call in client.calls[before:] if call[0] == "upsert"])
        row = rows(client)[0]
        row.update({"relationState": "rejected", "subjectStateKey": "item#item-big#rejected", "objectStateKey": "reference#lin-ref-a#rejected"})
        snapshot = json.dumps(client.tables["SemanticRelation"], sort_keys=True)
        result = link_item_reference_see_also(client, "item-big", "ref-a", "human", actor="Grace Editor")
        self.assertEqual(result["outcome"], "rejected")
        self.assertEqual(json.dumps(client.tables["SemanticRelation"], sort_keys=True), snapshot)

    def test_the_writer_refuses_a_reference_that_is_not_accepted(self):
        client = site()
        with self.assertRaisesRegex(ValueError, "only accepted References"):
            link_item_reference_see_also(client, "item-big", "ref-pending", "human", actor="x")
        self.assertEqual(rows(client), [])

    def test_stories_and_references_can_be_linked_in_one_call_and_dry_run_writes_nothing(self):
        client = site()
        out, _err, failure = link(client, "--story", "item-big", "--to", "item-post-1", "--reference", "ref-a", "--dry-run")
        self.assertIsNone(failure)
        self.assertEqual(len([line for line in out.splitlines() if line.endswith("dry run")]), 2)
        self.assertEqual(rows(client), [])
        _out, _err, failure = link(client, "--story", "item-big", "--to", "item-post-1", "--reference", "ref-a")
        self.assertIsNone(failure)
        self.assertEqual(sorted(row["objectKind"] for row in rows(client)), ["item", "reference"])

    def test_one_of_to_or_reference_is_required(self):
        _out, _err, failure = link(site(), "--story", "item-big")
        self.assertIn("--to or --reference", str(failure))

    def test_show_lists_the_see_also_references(self):
        client = site()
        link(client, "--story", "item-big", "--reference", "ref-a", "--note", "primary filing")
        out, _err, failure = run(story_commands.stories_show, client, "--story", "item-big")
        self.assertIsNone(failure)
        lines = [line.split("\t") for line in out.splitlines() if line.startswith("stories\tshow\tsee-also-reference")]
        self.assertEqual(lines, [["stories", "show", "see-also-reference", "ref-a", "Title ref-a", "host example.org", "status accepted", "primary filing"]])
        out, _err, _failure = run(story_commands.stories_show, client, "--story", "item-big", "--json")
        self.assertEqual([entry["referenceId"] for entry in json.loads(out)["relatedReferences"]], ["ref-a"])
        self.assertEqual(json.loads(out)["related"], [])
        self.assertEqual([entry["referenceLineageId"] for entry in references_of_story(client, "item-big")], ["lin-ref-a"])
        self.assertEqual(related_references(client, "item-post-1"), [])

    def test_the_tools_take_see_also_references(self):
        from unittest import mock

        from papyrus_content.story_signals_mcp import call_story_signal_tool, story_signal_tools
        from papyrus_newsroom import tactus_tools

        schema = story_signal_tools()["papyrus_link_stories"][1]
        self.assertIn("see_also_references", schema["properties"])
        self.assertEqual(schema["required"], ["story"])
        client = site()
        done = call_story_signal_tool("papyrus_link_stories", {"story": "big", "see_also_references": ["ref-a"]}, client, actor="Grace Editor")
        self.assertEqual([(row["title"], row["outcome"]) for row in done["referenceLinks"]], [("Title ref-a", "write")])
        self.assertEqual(json.loads(rows(client)[0]["metadata"])["provenance"], "derived")
        with self.assertRaisesRegex(ValueError, "pending"):
            call_story_signal_tool("papyrus_link_stories", {"story": "big", "see_also_references": ["ref-b", "ref-pending"]}, client, actor="Grace Editor")
        self.assertEqual(len(rows(client)), 1)
        with self.assertRaisesRegex(ValueError, "Give see_also_stories or see_also_references"):
            call_story_signal_tool("papyrus_link_stories", {"story": "big"}, client, actor="Grace Editor")
        with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, None)):
            again = tactus_tools.papyrus_link_stories("big", [], "Ruling analyst", see_also_references=["ref-a", "ref-b"])
        self.assertEqual([row["outcome"] for row in again["referenceLinks"]], ["exists", "write"])

    def test_the_seed_allows_a_reference_object_and_the_audit_judges_the_edges(self):
        see_also = load_relation_type_lookup()["see_also"]
        self.assertIn("reference", see_also["allowedObjectKinds"])
        self.assertEqual(see_also["allowedSubjectKinds"], ["item"])
        client = site()
        link(client, "--story", "item-big", "--reference", "ref-a", "--reference", "ref-b")
        self.assertEqual(audit_story_links(client, ["item-big"]), [])
        client.tables["Reference"]["ref-b"]["curationStatus"] = "rejected"
        good = rows(client)[0]
        client.tables["SemanticRelation"]["hand"] = {**good, "id": "hand", "predicate": "supersedes", "objectLineageId": "lin-ref-a"}
        client.tables["SemanticRelation"]["evidence"] = {**good, "id": "evidence", "predicate": "uses_evidence", "objectLineageId": "lin-ref-a"}
        problems = sorted((f["relationId"], f["problem"]) for f in audit_story_links(client, ["item-big"]))
        self.assertEqual([problem for _id, problem in problems], ["wrong predicate", "reference not accepted"])   # the uses_evidence edge is fine
        self.assertEqual(problems[0][0], "hand")


if __name__ == "__main__":
    unittest.main()
