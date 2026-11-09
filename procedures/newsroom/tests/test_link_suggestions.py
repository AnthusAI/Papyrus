"""`papyrus stories suggest-links` and `papyrus knowledge concepts related`: read only, two hops, rarity weighted, exclusions, closed agent tools."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
for entry in (HERE.parents[2] / "src", HERE.parents[2], HERE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from fake_client import FakeAuthoringClient  # noqa: E402
from papyrus_content import link_suggestions_commands  # noqa: E402
from papyrus_content.link_suggestions import related_concepts, suggest_links  # noqa: E402
from papyrus_content.story_signals_mcp import call_story_signal_tool, story_signal_tools  # noqa: E402

NODES = {"voice": "Voice Cloning", "privacy": "Privacy", "sound": "Acoustic Side Channel", "hub": "AI", "rejected": "Spam", "speech": "Speech Synthesis"}


def relation(rid, subject_kind, subject, object_kind, obj, predicate, state="current", metadata=None, created="2026-11-01T00:00:00Z"):
    return {"id": rid, "relationState": state, "predicate": predicate, "subjectKind": subject_kind, "subjectId": f"{subject}-v1" if subject_kind != "reference" else subject,
            "subjectLineageId": subject, "objectKind": object_kind, "objectId": f"{obj}-v1" if object_kind != "reference" else obj, "objectLineageId": obj,
            "subjectStateKey": f"{subject_kind}#{subject}#{state}", "objectStateKey": f"{object_kind}#{obj}#{state}", "createdAt": created,
            "metadata": json.dumps(metadata or {})}


def story(lineage, title, kind="article", published=True):
    return {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "headline": title, "title": title, "stage": "published" if published else "draft",
            "slug": lineage, "type": kind, "section": "news"}


def site():
    items = [story("s0", "The sound that gives you away"), story("s1", "Voice clones and your privacy"), story("s2", "Hubs only", "post"), story("s3", "Already linked"),
             story("s4", "Via the neighbour", "article"), story("s5", "Draft story", published=False), story("s9", "Untagged")]
    for index in range(6, 14):
        items.append(story(f"h{index}", f"Hub story {index}"))
    published = [{"id": f"published-{row['lineageId']}", "itemLineageId": row["lineageId"], "type": row["type"], "title": row["title"], "status": "published",
                  "publishedAt": "2026-10-20T00:00:00Z", "slug": row["slug"]} for row in items if row["stage"] == "published"]
    nodes = [{"id": f"{key}-v1", "lineageId": key, "nodeKey": f"editor_concept--{key}", "displayName": name, "aliases": [], "versionState": "current",
              "status": "rejected" if key == "rejected" else "accepted"} for key, name in NODES.items()]
    references = [{"id": f"ref-{n}", "lineageId": f"ref-{n}", "title": f"Source {n}", "sourceUri": f"https://www.example{n}.org/a", "curationStatus": "accepted" if n != 3 else "pending",
                   "createdAt": "2026-10-30T00:00:00Z", "versionState": "current"} for n in range(1, 5)]
    rows = [
        relation("r1", "item", "s0", "semanticNode", "sound", "tagged_with"), relation("r2", "item", "s0", "semanticNode", "privacy", "tagged_with"),
        relation("r3", "item", "s0", "semanticNode", "hub", "tagged_with"), relation("r4", "item", "s0", "semanticNode", "rejected", "mentions"),
        relation("r5", "item", "s0", "semanticNode", "voice", "mentions"),
        relation("c1", "item", "s1", "semanticNode", "privacy", "tagged_with"), relation("c2", "item", "s1", "semanticNode", "voice", "tagged_with"),
        relation("c3", "item", "s2", "semanticNode", "hub", "tagged_with"), relation("c4", "item", "s3", "semanticNode", "privacy", "tagged_with"),
        relation("c5", "item", "s4", "semanticNode", "speech", "tagged_with"), relation("c6", "item", "s5", "semanticNode", "privacy", "tagged_with"),
        relation("d1", "reference", "ref-1", "semanticNode", "sound", "tagged_with"), relation("d2", "reference", "ref-2", "semanticNode", "privacy", "mentions"),
        relation("d3", "reference", "ref-3", "semanticNode", "sound", "tagged_with"), relation("d4", "reference", "ref-4", "semanticNode", "privacy", "tagged_with"),
        relation("l1", "item", "s0", "item", "s3", "see_also"), relation("l2", "item", "s0", "reference", "ref-4", "uses_evidence", metadata={"role": "cited"}),
        # a confirmed concept link with its explanation, and co-occurrence: voice with speech on s4/s1-like carriers
        relation("k1", "semanticNode", "sound", "semanticNode", "speech", "related_to", metadata={"kind": "concept.link", "decision": "accepted", "decidedBy": "Grace", "note": "Sound is what speech synthesis emits"}),
    ]
    for n in range(6, 14):
        rows.append(relation(f"x{n}", "item", f"h{n}", "semanticNode", "hub", "tagged_with"))
    # co-occurrence: privacy and voice are together on s1 and ref-2 (two carriers)
    rows.append(relation("co1", "reference", "ref-2", "semanticNode", "voice", "tagged_with"))
    client = FakeAuthoringClient({"Item": items, "PublishedItem": published, "SemanticNode": nodes, "Reference": references, "SemanticRelation": rows})
    client.safe_list_records = client.list_records
    return client


class SuggestTests(unittest.TestCase):
    def test_ranks_by_shared_concepts_and_excludes_linked_unpublished_and_non_accepted(self):
        result = suggest_links(site(), "s0")
        articles = result["candidates"]["articles"]
        self.assertEqual([item["id"] for item in articles][:1], ["s1"])
        everything = {item["id"] for kind in result["candidates"].values() for item in kind}
        self.assertTrue({"s0", "s3", "s5", "ref-3", "ref-4"}.isdisjoint(everything), everything)
        self.assertEqual(result["linkedStories"], 1)
        self.assertIn("papyrus stories link-story --story s0 --to s1", articles[0]["command"])
        self.assertEqual({item["id"] for item in result["candidates"]["references"]}, {"ref-1", "ref-2"})
        self.assertIn("--reference ref-1", result["candidates"]["references"][0]["command"])

    def test_rejected_concepts_never_count_and_a_hub_concept_is_capped(self):
        result = suggest_links(site(), "s0")
        self.assertNotIn("Spam", [concept["name"] for concept in result["concepts"]])
        posts = result["candidates"]["posts"]
        hub = next(item for item in posts if item["id"] == "s2")
        self.assertLess(hub["score"], result["candidates"]["articles"][0]["score"])

    def test_the_second_hop_reports_the_path(self):
        result = suggest_links(site(), "s0", kinds=("articles",))
        via = next(item for item in result["candidates"]["articles"] if item["id"] == "s4")
        self.assertEqual(via["path"], "via Acoustic Side Channel, then Speech Synthesis")
        self.assertEqual(via["shared"], ["Speech Synthesis"])

    def test_nothing_is_written(self):
        client = site()
        suggest_links(client, "s0")
        self.assertEqual([call for call in client.calls if call[0] in ("create", "update", "delete", "upsert")], [])

    def test_a_story_with_no_concepts_says_so(self):
        result = suggest_links(site(), "s9")
        self.assertIn("no accepted concepts", result["note"])


class RelatedTests(unittest.TestCase):
    def test_confirmed_link_comes_first_with_its_explanation(self):
        result = related_concepts(site(), "#sound")
        first = result["related"][0]
        self.assertEqual((first["reason"], first["name"], first["explanation"]), ("confirmed", "Speech Synthesis", "Sound is what speech synthesis emits"))

    def test_co_occurrence_has_counts_and_unknown_concepts_are_never_guessed(self):
        result = related_concepts(site(), "privacy")
        voice = next(entry for entry in result["related"] if entry["name"] == "Voice Cloning")
        self.assertEqual((voice["reason"], voice["count"]), ("cooccurrence", 3))   # s0 (a mention), s1 and ref-2
        with self.assertRaises(ValueError):
            related_concepts(site(), "privac")


class CommandAndToolTests(unittest.TestCase):
    def run_command(self, command, *flags):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(link_suggestions_commands, "create_authoring_client", return_value=(site(), {})):
            command(list(flags))
        return out.getvalue()

    def test_the_text_table_and_json_carry_the_same_candidates(self):
        text = self.run_command(link_suggestions_commands.stories_suggest_links, "--story", "s0")
        self.assertIn("See also (articles)", text)
        self.assertIn("Related findings (references)", text)
        self.assertIn("papyrus stories link-story --story s0 --to s1", text)
        data = json.loads(self.run_command(link_suggestions_commands.stories_suggest_links, "--story", "s0", "--json", "--kinds", "articles"))
        self.assertEqual(list(data["candidates"]), ["articles"])
        self.assertIn("request", self.run_command(link_suggestions_commands.relations_related, "--concept", "privacy"))

    def test_the_agent_tools_are_closed_and_read_only(self):
        for name in ("papyrus_suggest_links", "papyrus_related_concepts"):
            self.assertIs(story_signal_tools()[name][1]["additionalProperties"], False)
        client = site()
        with self.assertRaises(ValueError):
            call_story_signal_tool("papyrus_suggest_links", {"story": "s0", "predicate": "x"}, client)
        self.assertTrue(call_story_signal_tool("papyrus_suggest_links", {"story": "s0", "limit": 2}, client)["candidates"]["articles"])
        self.assertTrue(call_story_signal_tool("papyrus_related_concepts", {"concept": "privacy"}, client)["related"])


if __name__ == "__main__":
    unittest.main()
