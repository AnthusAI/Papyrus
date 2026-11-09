"""`papyrus stories link-story`: related_to links between stories, symmetric, create-only, listed by `stories show`."""
from __future__ import annotations

import inspect
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for entry in (HERE.parents[2] / "src", HERE.parents[2], HERE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import story_commands  # noqa: E402
from papyrus_content.story_links import STORY_LINK_RELATION, link_stories, links_of_story, resolve_story, story_link_relation_id  # noqa: E402
from story_reference_role_site import SignedInSite  # noqa: E402
from test_story_cli_live_test_edges import run  # noqa: E402


def story(lineage: str, title: str, kind: str, stage: str, slug: str) -> dict:
    return {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "headline": title, "title": title,
            "stage": stage, "slug": slug, "type": kind, "section": "news"}


def site() -> SignedInSite:
    return SignedInSite({
        "Item": [story("item-big", "A big story", "article", "published", "big"), story("item-post-1", "First post", "post", "published", "post-1"),
                 story("item-post-2", "Second post", "post", "draft", "post-2"), story("item-page", "A page", "wiki_page", "published", "page")],
        "PublishedItem": [{"id": "published-item-big"}, {"id": "published-item-post-1"}],
    }, groups=["editor"], label="Grace Editor")


def link(client, *flags, signed_in=True, label="Grace Editor"):
    return run(story_commands.stories_link_story, client, *flags, signed_in=signed_in, label=label)


class LinkStoryTests(unittest.TestCase):
    def test_one_command_links_several_stories_and_prints_title_type_stage(self):
        client = site()
        out, err, failure = link(client, "--story", "item-big", "--to", "item-post-1", "--to", "post-2", "--note", "goes with")
        self.assertIsNone(failure, err)
        lines = [line.split("\t") for line in out.splitlines()]
        self.assertEqual(lines[0], ["stories", "link-story", "item-big", "item-post-1", "related_to", "First post", "type post", "stage published", "write"])
        self.assertEqual(lines[1][3:], ["item-post-2", "related_to", "Second post", "type post", "stage draft", "write"])
        self.assertIn("Second post is not published yet", err)
        self.assertNotIn("First post is not", err)
        rows = list(client.tables["SemanticRelation"].values())
        self.assertEqual(len(rows), 2)
        meta = json.loads(rows[0]["metadata"])
        self.assertEqual((meta["addedBy"], meta["note"], rows[0]["predicate"]), ("Grace Editor", "goes with", "related_to"))

    def test_either_direction_is_the_same_link_and_a_repeat_writes_nothing(self):
        client = site()
        self.assertEqual(story_link_relation_id("a", "b"), story_link_relation_id("b", "a"))
        link(client, "--story", "item-big", "--to", "item-post-1")
        for flags in (["--story", "item-big", "--to", "item-post-1"], ["--story", "item-post-1", "--to", "item-big"]):
            before = len(client.calls)
            out, _err, failure = link(client, *flags)
            self.assertIsNone(failure)
            self.assertTrue(out.rstrip().endswith("\texists"), out)
            self.assertNotIn("write", out)
            self.assertFalse([call for call in client.calls[before:] if call[0] == "upsert"])
        self.assertEqual(len(client.tables["SemanticRelation"]), 1)

    def test_self_link_unknown_story_and_non_story_are_refused_before_any_write(self):
        client = site()
        for target, message in (("item-big", "itself"), ("big", "itself"), ("nope", "No story found"), ("item-page", "not a story")):
            _out, _err, failure = link(client, "--story", "item-big", "--to", "item-post-1", "--to", target)
            self.assertIn(message, str(failure))
        self.assertEqual(client.tables.get("SemanticRelation", {}), {})

    def test_dry_run_prints_dry_run_and_writes_nothing(self):
        client = site()
        out, _err, failure = link(client, "--story", "item-big", "--to", "item-post-1", "--dry-run")
        self.assertIsNone(failure)
        self.assertTrue(out.rstrip().endswith("\tdry run"), out)
        self.assertEqual(client.tables.get("SemanticRelation", {}), {})

    def test_no_write_line_when_the_save_fails(self):
        client = site()
        client.groups = ["viewer"]
        out, _err, failure = link(client, "--story", "item-big", "--to", "item-post-1")
        self.assertIn("Not Authorized", str(failure))
        self.assertNotIn("write", out)

    def test_author_is_the_signed_in_person_and_the_iam_lane_needs_a_label(self):
        client = site()
        link(client, "--story", "item-big", "--to", "item-post-1", "--author-label", "Someone Else")
        self.assertEqual(json.loads(next(iter(client.tables["SemanticRelation"].values()))["metadata"])["addedBy"], "Grace Editor")
        _out, _err, failure = link(client, "--story", "item-big", "--to", "item-post-1", signed_in=False, label=None)
        self.assertIn("--author-label is required", str(failure))

    def test_no_relation_name_can_be_chosen(self):
        client = site()
        _out, _err, failure = link(client, "--story", "item-big", "--to", "item-post-1", "--relation", "expands_on")
        self.assertIn("Allowed values: related_to", str(failure))
        self.assertEqual(client.tables.get("SemanticRelation", {}), {})
        _out, _err, failure = link(client, "--story", "item-big", "--to", "item-post-1", "--relation", STORY_LINK_RELATION)
        self.assertIsNone(failure)

    def test_the_written_row_uses_the_one_official_name_everywhere(self):
        client = site()
        link(client, "--story", "item-big", "--to", "item-post-1")
        row = next(iter(client.tables["SemanticRelation"].values()))
        self.assertEqual((row["predicate"], row["relationTypeKey"], row["relationTypeId"]), (STORY_LINK_RELATION, STORY_LINK_RELATION, "semantic-relation-type-related-to"))
        self.assertTrue(row["predicateObjectStateKey"].startswith(STORY_LINK_RELATION + "#"))

    def test_the_writer_refuses_a_wrong_relation_type_record(self):
        from unittest import mock

        client = site()
        with mock.patch("papyrus_content.story_links.STORY_LINK_RELATION", "related-to"):
            with self.assertRaises(ValueError):
                link_stories(client, resolve_story(client, "item-big"), resolve_story(client, "item-post-1"), actor="x")
        self.assertEqual(client.tables.get("SemanticRelation", {}), {})

    def test_a_hand_written_link_under_another_name_is_listed_not_shown(self):
        client = site()
        link(client, "--story", "item-big", "--to", "item-post-1")
        good = next(iter(client.tables["SemanticRelation"].values()))
        for relation_id, predicate in (("hand-1", "relatedto"), ("hand-2", "supersedes")):
            client.tables["SemanticRelation"][relation_id] = {**good, "id": relation_id, "predicate": predicate, "objectLineageId": "item-post-2",
                                                              "objectStateKey": "item#item-post-2#current"}
        out, _err, failure = run(story_commands.stories_show, client, "--story", "item-big")
        self.assertIsNone(failure)
        self.assertEqual(len([line for line in out.splitlines() if line.startswith("stories\tshow\trelated\t")]), 1)
        odd = {line.split("\t")[4]: line.split("\t")[6] for line in out.splitlines() if line.startswith("stories\tshow\tunofficial-relation")}
        self.assertEqual(odd["relatedto"], "unknown name")
        self.assertIn("supersedes", odd)
        out, _err, _failure = run(story_commands.stories_show, client, "--story", "item-post-2", "--json")
        payload = json.loads(out)
        self.assertEqual(payload["related"], [])
        self.assertEqual(sorted(entry["predicate"] for entry in payload["unofficialRelations"]), ["relatedto", "supersedes"])

    def test_the_agent_tools_have_no_relation_field(self):
        from papyrus_content.story_signals_mcp import call_story_signal_tool, story_signal_tools

        schema = story_signal_tools()["papyrus_link_stories"][1]
        self.assertNotIn("relation", " ".join(schema["properties"]).lower())
        self.assertFalse(schema["additionalProperties"])
        client = site()
        with self.assertRaisesRegex(ValueError, "no relation to choose"):
            call_story_signal_tool("papyrus_link_stories", {"story": "big", "related_to_stories": ["post-1"], "relation": "x"}, client, actor="Grace Editor")
        done = call_story_signal_tool("papyrus_link_stories", {"story": "big", "related_to_stories": ["post-1", "post-2"], "note": "n"}, client, actor="Grace Editor")
        self.assertEqual([(row["title"], row["outcome"]) for row in done["links"]], [("First post", "write"), ("Second post", "write")])
        self.assertIn("not published yet", done["links"][1]["warning"])
        again = call_story_signal_tool("papyrus_link_stories", {"story": "post-1", "related_to_stories": ["big"]}, client, actor="Grace Editor")
        self.assertEqual(again["links"][0]["outcome"], "exists")
        with self.assertRaisesRegex(ValueError, "itself"):
            call_story_signal_tool("papyrus_link_stories", {"story": "big", "related_to_stories": ["big"]}, client, actor="Grace Editor")

    def test_the_tactus_tool_links_with_the_same_rules(self):
        from unittest import mock

        from papyrus_newsroom import tactus_tools

        client = site()
        with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, None)):
            done = tactus_tools.papyrus_link_stories("big", ["post-1", "post-2"], "Ruling analyst", note="n")
            again = tactus_tools.papyrus_link_stories("post-1", "big", "Ruling analyst")
        self.assertEqual([row["outcome"] for row in done["links"]], ["write", "write"])
        self.assertEqual(again["links"][0]["outcome"], "exists")
        self.assertNotIn("relation", inspect.signature(tactus_tools.papyrus_link_stories).parameters)

    def test_json_output(self):
        out, _err, failure = link(site(), "--story", "item-big", "--to", "item-post-2", "--json")
        self.assertIsNone(failure)
        payload = json.loads(out)
        self.assertEqual((payload["dryRun"], payload["links"][0]["outcome"], payload["links"][0]["published"]), (False, "write", False))

    def test_show_lists_related_stories_from_both_ends(self):
        client = site()
        link(client, "--story", "item-big", "--to", "item-post-2", "--note", "goes deeper")
        for lineage, other in (("item-big", "Second post"), ("item-post-2", "A big story")):
            out, _err, failure = run(story_commands.stories_show, client, "--story", lineage)
            self.assertIsNone(failure)
            related = [line.split("\t") for line in out.splitlines() if line.startswith("stories\tshow\trelated")]
            self.assertEqual(len(related), 1, out)
            self.assertEqual(related[0][4], other)
        self.assertEqual(related[0][-1], "goes deeper")
        self.assertEqual(len(links_of_story(client, "item-big")), 1)


if __name__ == "__main__":
    unittest.main()
