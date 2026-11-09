"""Tagging a story or a Reference with a concept, rigidly: exact resolution, no creation, one predicate, idempotence, rejected stays rejected, and the audit."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for entry in (HERE.parents[2] / "src", HERE.parents[2], HERE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from fake_client import FakeAuthoringClient  # noqa: E402
from papyrus_content import concept_tags_commands  # noqa: E402
from papyrus_content.concept_link_predicates import CONCEPT_LINK_PREDICATES  # noqa: E402
from papyrus_content.concept_tags import audit_reference_links, audit_story_links, resolve_concept_exact, tag_with_concepts  # noqa: E402
from papyrus_content.reference_links import CONCEPT_TAG_PREDICATE, CONCEPT_TAG_PREDICATES, ITEM_CONCEPT_KIND, REFERENCE_CONCEPT_KIND  # noqa: E402
from test_story_cli_live_test_edges import run  # noqa: E402


class Site(FakeAuthoringClient):
    safe_list_records = FakeAuthoringClient.list_records

    def __init__(self):
        def node(key, name, status="accepted", aliases=None):
            return {"id": f"{key}-v1", "lineageId": f"semantic-node-{key}", "versionNumber": 1, "versionState": "current", "nodeKey": key, "displayName": name,
                    "aliases": aliases or [], "status": status}
        super().__init__({
            "Item": [{"id": "item-big-v1", "lineageId": "item-big", "versionNumber": 1, "versionState": "current", "headline": "A big story", "title": "A big story",
                      "stage": "published", "slug": "big", "type": "article", "section": "news"}],
            "Reference": [{"id": "reference-a", "lineageId": "reference-a", "versionNumber": 1, "versionState": "current", "title": "A source", "corpusId": "corpus-1",
                           "curationStatus": "accepted", "curationStatusKey": "corpus-1#accepted"}],
            "PublishedItem": [
                {"id": "published-item-big", "itemLineageId": "item-big", "type": "article"},
                {"id": "wiki-1", "itemLineageId": "wiki-1", "type": "wiki_page", "typeStatus": "wiki_page#published",
                 "metadata": json.dumps({"frontMatterYaml": "entityKey: voice-cloning\n"})}],
            "SemanticNode": [
                node("editor_concept--voice-cloning", "Voice Cloning", aliases=["TTS cloning"]),
                node("editor_concept--translation", "Translation"), node("task--translation", "Translation task"), node("concept--translation", "Translation concept"),
                node("concept--spam", "Spam", status="rejected"), node("concept--maybe", "Maybe", status="suggested"),
                node("editor_concept--unpublished", "Unpublished idea")],
        })
        self.endpoint = "https://example.test/graphql"


def nodes(site):
    return site.tables["SemanticNode"].values()


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.nodes = list(nodes(Site()))

    def key(self, text):
        return resolve_concept_exact(self.nodes, text)["nodeKey"]

    def test_exact_node_key_hashtag_name_and_alias_each_resolve_case_insensitively(self):
        for text in ("editor_concept--voice-cloning", "EDITOR_CONCEPT--Voice-Cloning", "#voice-cloning", "voice-cloning", "Voice Cloning", "voice  cloning", "tts CLONING"):
            self.assertEqual(self.key(text), "editor_concept--voice-cloning", text)

    def test_a_hashtag_that_several_kinds_share_lists_them_and_a_node_key_picks_one(self):
        with self.assertRaises(ValueError) as caught:
            self.key("#translation")
        message = str(caught.exception)
        for key in ("editor_concept--translation", "task--translation", "concept--translation"):
            self.assertIn(key, message)
        self.assertEqual(self.key("task--translation"), "task--translation")

    def test_no_fuzzy_matching_and_the_error_lists_the_closest_accepted_concepts(self):
        with self.assertRaises(ValueError) as caught:
            self.key("voice cloner")
        self.assertIn("No accepted concept is named", str(caught.exception))
        self.assertIn("editor_concept--voice-cloning", str(caught.exception))
        for near_miss in ("voicecloning", "voice", "clon"):
            with self.assertRaises(ValueError):
                self.key(near_miss)

    def test_a_rejected_or_suggested_concept_is_refused_by_name_even_though_it_exists(self):
        for text, status in (("concept--spam", "rejected"), ("#maybe", "suggested")):
            with self.assertRaisesRegex(ValueError, f"status {status}"):
                self.key(text)


class TaggingTests(unittest.TestCase):
    def tag(self, site, kind="story", target="big", concepts=("#voice-cloning",), **kwargs):
        return tag_with_concepts(site, kind, target, list(concepts), actor="Ada", provenance="human", **kwargs)

    def test_a_story_is_tagged_with_the_one_predicate_kind_and_provenance_and_never_creates_a_node(self):
        site = Site()
        before = json.dumps(site.tables["SemanticNode"], sort_keys=True)
        done = self.tag(site, note="n")
        row = next(iter(site.tables["SemanticRelation"].values()))
        meta = json.loads(row["metadata"])
        self.assertEqual((row["predicate"], row["relationState"], row["objectKind"], row["subjectKind"], row["relationTypeKey"]), (CONCEPT_TAG_PREDICATE, "current", "semanticNode", "item", "tagged_with"))
        self.assertEqual((meta["kind"], meta["provenance"], meta["addedBy"], meta["note"]), (ITEM_CONCEPT_KIND, "human", "Ada", "n"))
        self.assertEqual((done["concepts"][0]["outcome"], done["concepts"][0]["publicPage"]), ("write", True))
        self.assertEqual(json.dumps(site.tables["SemanticNode"], sort_keys=True), before)

    def test_a_reference_is_tagged_the_same_way(self):
        site = Site()
        self.tag(site, "reference", "reference-a")
        row = next(iter(site.tables["SemanticRelation"].values()))
        self.assertEqual((row["subjectKind"], row["predicate"], json.loads(row["metadata"])["kind"]), ("reference", "tagged_with", REFERENCE_CONCEPT_KIND))

    def test_repeating_writes_nothing_and_a_legacy_or_mention_edge_counts_as_tagged(self):
        site = Site()
        self.tag(site)
        again = self.tag(site)
        self.assertEqual(again["concepts"][0]["outcome"], "exists")
        self.assertEqual(len(site.tables["SemanticRelation"]), 1)
        for predicate in ("related_to", "mentions"):
            other = Site()
            self.tag(other)
            row = next(iter(other.tables["SemanticRelation"].values()))
            other.tables["SemanticRelation"] = {"legacy": {**row, "id": "legacy", "predicate": predicate}}
            done = self.tag(other)
            self.assertEqual((done["concepts"][0]["outcome"], done["concepts"][0]["predicate"], bool(done["concepts"][0].get("legacy"))), ("exists", predicate, predicate == "related_to"))
            self.assertEqual(list(other.tables["SemanticRelation"]), ["legacy"])

    def test_a_rejected_tag_is_never_flipped_back(self):
        site = Site()
        self.tag(site)
        row = next(iter(site.tables["SemanticRelation"].values()))
        row.update({"relationState": "rejected", "subjectStateKey": "item#item-big#rejected"})
        before = json.dumps(site.tables["SemanticRelation"], sort_keys=True)
        done = self.tag(site)
        self.assertEqual(done["concepts"][0]["outcome"], "rejected")
        self.assertIn("Use the newsroom", done["concepts"][0]["warning"])
        self.assertEqual(json.dumps(site.tables["SemanticRelation"], sort_keys=True), before)

    def test_a_concept_without_a_public_page_is_warned_about_and_a_dry_run_writes_nothing(self):
        site = Site()
        done = self.tag(site, concepts=("#unpublished",), apply=False)
        self.assertEqual((done["concepts"][0]["outcome"], done["concepts"][0]["publicPage"]), ("dry run", False))
        self.assertIn("no public wiki page", done["concepts"][0]["warning"])
        self.assertEqual(site.tables.get("SemanticRelation", {}), {})

    def test_one_bad_concept_stops_everything_before_any_write(self):
        site = Site()
        with self.assertRaises(ValueError):
            self.tag(site, concepts=("#voice-cloning", "#nope-nope"))
        self.assertEqual(site.tables.get("SemanticRelation", {}), {})

    def test_target_kind_and_missing_targets_are_refused(self):
        site = Site()
        with self.assertRaisesRegex(ValueError, "target_kind"):
            self.tag(site, "category")
        with self.assertRaisesRegex(ValueError, "No story found"):
            self.tag(site, target="missing")
        with self.assertRaisesRegex(ValueError, "Reference not found"):
            self.tag(site, "reference", "missing")

    def test_the_predicate_names_live_in_one_place_and_every_reader_accepts_the_tag_and_its_legacy_name(self):
        self.assertEqual(CONCEPT_TAG_PREDICATES, ("tagged_with", "related_to"))
        self.assertEqual(set(CONCEPT_LINK_PREDICATES), {"mentions", "tagged_with", "related_to"})


class CommandTests(unittest.TestCase):
    def link(self, site, command, *flags, signed_in=True):
        return self._run(command, site, flags, signed_in)

    def _run(self, command, site, flags, signed_in):
        import contextlib
        import io
        from unittest import mock

        out, err, failure = io.StringIO(), io.StringIO(), None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(concept_tags_commands, "create_authoring_client", return_value=(site, {})), \
                mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=signed_in), \
                mock.patch("papyrus_content.cli_user_auth.signed_in_label", return_value="Grace Editor"):
            try:
                command(list(flags))
            except BaseException as error:  # noqa: BLE001
                failure = error
        return out.getvalue(), err.getvalue(), failure

    def test_stories_link_concept_prints_a_line_per_concept_and_records_the_signed_in_person(self):
        site = Site()
        out, err, failure = self.link(site, concepts_cmd("stories_link_concept"), "--story", "big", "--concept", "#voice-cloning", "--concept", "#unpublished")
        self.assertIsNone(failure, err)
        lines = [line.split("\t") for line in out.splitlines()]
        self.assertEqual([line[-2:] for line in lines], [["public page", "write"], ["no public page", "write"]])
        self.assertIn("no public wiki page", err)
        self.assertEqual({json.loads(row["metadata"])["addedBy"] for row in site.tables["SemanticRelation"].values()}, {"Grace Editor"})

    def test_no_option_can_choose_a_predicate_a_state_or_a_new_concept(self):
        for flag in ("--predicate", "--relation", "--state", "--create"):
            site = Site()
            _out, _err, failure = self.link(site, concepts_cmd("stories_link_concept"), "--story", "big", "--concept", "#voice-cloning", flag, "x")
            self.assertIn("is not accepted", str(failure), flag)
            self.assertEqual(site.tables.get("SemanticRelation", {}), {})

    def test_the_iam_lane_needs_a_label_and_records_derived_provenance(self):
        site = Site()
        _out, _err, failure = self.link(site, concepts_cmd("references_link_concept"), "--reference", "reference-a", "--concept", "#voice-cloning", signed_in=False)
        self.assertIn("--author-label is required", str(failure))
        _out, _err, failure = self.link(site, concepts_cmd("references_link_concept"), "--reference", "reference-a", "--concept", "#voice-cloning", "--author-label", "Codex", signed_in=False)
        self.assertIsNone(failure)
        self.assertEqual(json.loads(next(iter(site.tables["SemanticRelation"].values()))["metadata"])["provenance"], "derived")


def concepts_cmd(name):
    return getattr(concept_tags_commands, name)


class AuditTests(unittest.TestCase):
    def relation(self, site, relation_id, **fields):
        base = {"id": relation_id, "relationState": "current", "predicate": "tagged_with", "subjectKind": "item", "subjectLineageId": "item-big", "objectKind": "semanticNode",
                "objectId": "editor_concept--voice-cloning-v1", "objectLineageId": "semantic-node-editor_concept--voice-cloning", "subjectStateKey": "item#item-big#current",
                "metadata": json.dumps({"kind": ITEM_CONCEPT_KIND})}
        row = {**base, **fields}
        row["subjectStateKey"] = f"{row['subjectKind']}#{row['subjectLineageId']}#{row['relationState']}"
        site.tables.setdefault("SemanticRelation", {})[relation_id] = row

    def problems(self, site, lineage="item-big"):
        return sorted((f["relationId"], f["problem"]) for f in audit_story_links(site, [lineage]))

    def test_the_official_shapes_pass_including_mentions(self):
        site = Site()
        self.relation(site, "ok")
        self.relation(site, "mention", predicate="mentions", objectId="editor_concept--translation-v1", objectLineageId="semantic-node-editor_concept--translation")
        self.assertEqual(self.problems(site), [])

    def test_every_non_official_shape_is_listed(self):
        site = Site()
        self.relation(site, "legacy", predicate="related_to")
        self.relation(site, "wrong", predicate="about", objectId="task--translation-v1", objectLineageId="semantic-node-task--translation")
        self.relation(site, "rej", relationState="rejected", objectId="editor_concept--translation-v1", objectLineageId="semantic-node-editor_concept--translation")
        self.relation(site, "spam", objectId="concept--spam-v1", objectLineageId="semantic-node-concept--spam")
        self.relation(site, "nopage", objectId="editor_concept--unpublished-v1", objectLineageId="semantic-node-editor_concept--unpublished")
        self.relation(site, "gone", objectId="nothing-v1", objectLineageId="semantic-node-nothing")
        self.relation(site, "kind", objectId="concept--translation-v1", objectLineageId="semantic-node-concept--translation", metadata=json.dumps({"kind": "x"}))
        found = set(self.problems(site))
        for expected in (("legacy", "legacy: migrate"), ("wrong", "wrong predicate"), ("rej", "state not current"), ("spam", "concept not accepted"),
                         ("nopage", "concept has no public page"), ("gone", "concept missing"), ("kind", "wrong kind")):
            self.assertIn(expected, found)

    def test_story_links_wrong_predicate_unpublished_target_and_duplicate_pairs(self):
        site = Site()
        site.tables["Item"]["item-post-v1"] = {"id": "item-post-v1", "lineageId": "item-post", "versionNumber": 1, "versionState": "current", "type": "post", "stage": "draft"}
        item_edge = dict(subjectKind="item", objectKind="item", objectId="item-post-v1", objectLineageId="item-post", metadata=json.dumps({"kind": "item.link"}))
        self.relation(site, "good", predicate="see_also", **item_edge)
        self.relation(site, "reverse", predicate="see_also", **{**item_edge, "subjectLineageId": "item-post", "objectLineageId": "item-big", "objectId": "item-big-v1"})
        self.relation(site, "old", predicate="related_to", **item_edge)
        found = {problem for _id, problem in self.problems(site)}
        self.assertTrue({"target not published", "duplicate pair", "wrong predicate"} <= found, found)

    def test_reference_audit_reads_only_indexed_keys(self):
        site = Site()
        self.relation(site, "ref-legacy", predicate="related_to", subjectKind="reference", subjectLineageId="reference-a", metadata=json.dumps({"kind": REFERENCE_CONCEPT_KIND}))
        found = audit_reference_links(site, ["reference-a"])
        self.assertEqual([f["problem"] for f in found], ["legacy: migrate"])
        self.assertFalse([call for call in site.calls if call[0] == "list" and call[1] in ("SemanticRelation", "Reference", "SemanticNode")])


class AgentToolTests(unittest.TestCase):
    def test_the_mcp_tool_has_an_enum_target_kind_and_no_relation_or_state_field(self):
        from papyrus_content.story_signals_mcp import call_story_signal_tool, story_signal_tools

        schema = story_signal_tools()["papyrus_link_concepts"][1]
        self.assertEqual(sorted(schema["properties"]), ["concepts", "dryRun", "note", "target", "target_kind"])
        self.assertEqual(schema["properties"]["target_kind"]["enum"], ["story", "reference"])
        self.assertFalse(schema["additionalProperties"])
        site = Site()
        with self.assertRaisesRegex(ValueError, "no relation or state"):
            call_story_signal_tool("papyrus_link_concepts", {"target_kind": "story", "target": "big", "concepts": ["#voice-cloning"], "predicate": "x"}, site, actor="Codex")
        done = call_story_signal_tool("papyrus_link_concepts", {"target_kind": "story", "target": "big", "concepts": ["#voice-cloning"]}, site, actor="Codex")
        self.assertEqual(done["concepts"][0]["outcome"], "write")
        meta = json.loads(next(iter(site.tables["SemanticRelation"].values()))["metadata"])
        self.assertEqual((meta["provenance"], meta["addedBy"]), ("derived", "Codex"))

    def test_the_tactus_tool_tags_with_the_same_rules(self):
        import inspect
        from unittest import mock

        from papyrus_newsroom import tactus_tools

        site = Site()
        with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(site, None)):
            done = tactus_tools.papyrus_link_concepts("reference", "reference-a", "#voice-cloning,editor_concept--translation", "Codex")
        self.assertEqual([row["outcome"] for row in done["concepts"]], ["write", "write"])
        self.assertEqual(sorted(inspect.signature(tactus_tools.papyrus_link_concepts).parameters), ["author_label", "concepts", "note", "target", "target_kind"])


if __name__ == "__main__":
    unittest.main()
