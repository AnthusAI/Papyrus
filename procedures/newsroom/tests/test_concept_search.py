"""`papyrus knowledge concepts search`: meaning decides the order, popularity never does; duplicates and a stale index are said plainly."""
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

from test_link_suggestions import site  # noqa: E402
from papyrus_content import link_suggestions_commands  # noqa: E402
from papyrus_content.concept_search import DUPLICATE_COSINE, search_concepts  # noqa: E402
from papyrus_content.link_suggestions import _lineage, related_concepts, suggest_links  # noqa: E402
from papyrus_content.story_signals_mcp import call_story_signal_tool, story_signal_tools  # noqa: E402


def with_extra_nodes(client):
    """Adds a second 'Voice Cloning' (a duplicate under another id), a bookkeeping node and a generated one."""
    for key, name, kind, status in (("voice2", "Voice  Cloning", None, "accepted"), ("author", "Some Author", "personAuthor", "accepted"), ("gen", "Generated Thing", None, "generated")):
        client.tables["SemanticNode"][f"{key}-v1"] = {"id": f"{key}-v1", "lineageId": key, "nodeKey": f"editor_concept--{key}", "displayName": name, "aliases": [], "versionState": "current",
                                                      "status": status, "nodeKind": kind}
    return client


class FakeIndex:
    """Embeds once; returns concept vectors by cosine with a tiny hand-made space; knows which concept cards exist."""

    VECTORS = {"voice": [1.0, 0.0, 0.0], "voice2": [0.99, 0.05, 0.0], "privacy": [0.0, 1.0, 0.0], "sound": [0.0, 0.0, 1.0], "hub": [0.5, 0.5, 0.5], "author": [0.0, 0.0, 0.9], "gen": [0.0, 0.0, 0.8]}

    def __init__(self, present=None, query=(0.0, 0.1, 1.0)):
        self.embedded: list[str] = []
        self.queries: list[dict] = []
        self.present = set(self.VECTORS) if present is None else set(present)
        self.query = list(query)

    def embed_text(self, text):
        self.embedded.append(text)
        return self.query

    def query_by_vector(self, vector, top_k, metadata_filter):
        self.queries.append(metadata_filter)
        out = []
        for lineage, data in self.VECTORS.items():
            if lineage in self.present:
                dot = sum(a * b for a, b in zip(vector, data))
                norm = (sum(a * a for a in vector) ** 0.5) * (sum(b * b for b in data) ** 0.5)
                out.append({"key": f"concept_card-{lineage}", "distance": 1 - dot / norm, "metadata": {"lineageId": lineage, "vectorKind": "concept_card"}})
        return sorted(out, key=lambda match: match["distance"])

    def get_vector(self, key):
        return self.VECTORS.get(key.removeprefix("concept_card-"))

    def existing_keys(self, keys):
        return [key for key in keys if key.removeprefix("concept_card-") in self.present]


class SearchTests(unittest.TestCase):
    def test_meaning_decides_the_order_and_popularity_is_only_information(self):
        index = FakeIndex()
        result = search_concepts(with_extra_nodes(site()), index, "acoustic leakage", limit=5)
        names = [entry["name"] for entry in result["results"]]
        self.assertEqual(names[0], "Acoustic Side Channel")          # nearest to the query; "AI" is carried by the most stories and still comes later
        self.assertLess(names.index("Acoustic Side Channel"), names.index("AI"))
        self.assertTrue(all(entry["reason"] == "meaning" for entry in result["results"]))
        self.assertEqual(len(index.embedded), 1)                       # one embedding for the whole search
        self.assertEqual(index.queries, [{"vectorKind": {"$in": ["concept_card", "ontology_concept_profile"]}}])   # concept vectors only
        hub = next(entry for entry in result["results"] if entry["name"] == "AI")
        self.assertGreater(hub["stories"], 5)                          # shown, never used to rank

    def test_only_accepted_concepts_are_returned(self):
        names = [entry["name"] for entry in search_concepts(with_extra_nodes(site()), FakeIndex(), "acoustic leakage", limit=20)["results"]]
        self.assertNotIn("Some Author", names)       # bookkeeping kind
        self.assertNotIn("Generated Thing", names)   # generated, not accepted
        self.assertNotIn("Spam", names)              # rejected

    def test_a_typed_exact_name_always_comes_first_then_prefix(self):
        result = search_concepts(with_extra_nodes(site()), FakeIndex(query=(0.0, 0.0, 1.0)), "Privacy", limit=5)
        first = result["results"][0]
        self.assertEqual((first["name"], first["reason"]), ("Privacy", "name match (exact)"))
        self.assertIsNotNone(first["similarity"])
        prefix = search_concepts(with_extra_nodes(site()), FakeIndex(), "voice", limit=5)["results"]
        self.assertTrue(prefix[0]["reason"].startswith("name match"))

    def test_duplicates_are_flagged_by_name_and_by_vector(self):
        result = search_concepts(with_extra_nodes(site()), FakeIndex(query=(1.0, 0.0, 0.0)), "voice", limit=5)
        flagged = [entry for entry in result["results"] if entry.get("duplicates")]
        self.assertEqual({entry["lineageId"] for entry in flagged}, {"voice", "voice2"})
        self.assertIn("same name", {d["why"] for entry in flagged for d in entry["duplicates"]})
        self.assertEqual(result["duplicateCosine"], {"likely": 0.90, "possible": DUPLICATE_COSINE})
        close = search_concepts(site(), FakeIndex(query=(1.0, 0.0, 0.0)), "something", limit=5)
        self.assertFalse(any(entry.get("duplicates") for entry in close["results"]))

    def test_an_empty_index_is_reported_with_the_command(self):
        result = search_concepts(site(), FakeIndex(present=[]), "Privacy", limit=5)
        self.assertEqual(result["health"]["status"], "empty")
        self.assertIn("knowledge-vector-index --action sync", result["health"]["message"])
        self.assertEqual(result["results"][0]["name"], "Privacy")   # the name match still works

    def test_a_stale_index_is_reported_with_counts(self):
        result = search_concepts(site(), FakeIndex(present=["voice", "privacy"]), "anything", limit=5)
        self.assertEqual(result["health"]["status"], "stale")
        self.assertEqual((result["health"]["withVector"], result["health"]["acceptedConcepts"]), (2, 5))

    def test_list_is_alphabetical_accepted_only_and_needs_no_index(self):
        result = search_concepts(with_extra_nodes(site()), None, None, list_all=True, limit=100)
        names = [entry["name"] for entry in result["results"]]
        self.assertEqual(names, sorted(names, key=str.lower))
        self.assertNotIn("Spam", names)
        self.assertNotIn("Generated Thing", names)

    def test_no_index_matches_names_only_and_says_so(self):
        result = search_concepts(site(), None, "privacy")
        self.assertIn("only names were matched", result["indexNote"])
        self.assertEqual(result["results"][0]["name"], "Privacy")

    def test_nothing_is_written(self):
        client = site()
        search_concepts(client, FakeIndex(), "Privacy")
        self.assertEqual([call for call in client.calls if call[0] in ("create", "update", "delete", "upsert")], [])


class CommandAndToolTests(unittest.TestCase):
    def run_command(self, *flags):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(link_suggestions_commands, "create_authoring_client", return_value=(with_extra_nodes(site()), {})), \
                mock.patch("papyrus_content.concept_search.default_provider", return_value=FakeIndex()):
            link_suggestions_commands.relations_search(list(flags))
        return out.getvalue()

    def test_text_and_json_carry_the_same_results(self):
        text = self.run_command("acoustic leakage")
        self.assertIn("concepts\tsearch\t1\tAcoustic Side Channel", text)
        data = json.loads(self.run_command("acoustic leakage", "--json", "--limit", "3"))
        self.assertEqual(len(data["results"]), 3)
        self.assertEqual(data["results"][0]["name"], "Acoustic Side Channel")
        self.assertIn("accepted concepts", self.run_command("--list"))

    def test_a_missing_query_is_an_error(self):
        with self.assertRaises(ValueError):
            self.run_command()

    def test_the_agent_tool_is_closed_and_read_only(self):
        self.assertIs(story_signal_tools()["papyrus_search_concepts"][1]["additionalProperties"], False)
        with self.assertRaises(ValueError):
            call_story_signal_tool("papyrus_search_concepts", {"query": "x", "state": "accepted"}, site())


def add_nodes(client, *pairs):
    for key, name in pairs:
        client.tables["SemanticNode"][f"{key}-v1"] = {"id": f"{key}-v1", "lineageId": key, "nodeKey": f"editor_concept--{key}", "displayName": name, "aliases": [], "versionState": "current",
                                                      "status": "accepted", "nodeKind": None}


class WikiPageTests(unittest.TestCase):
    def wiki_row(self, slug, indexed):
        row = {"id": f"published-wiki-{slug}", "sourceItemId": f"wiki-{slug}", "itemLineageId": f"wiki-{slug}", "type": "wiki_page", "status": "published", "slug": slug, "section": "wiki",
               "title": slug, "publishedAt": "2026-11-07T00:00:00Z", "metadata": json.dumps({"frontMatterYaml": f"title: {slug}\nentityKey: {slug}\nkind: editor-concept\n"})}
        if indexed:
            row["typeStatus"] = "wiki_page#published"
        return row

    def check(self, indexed):
        client = site()
        client.tables["PublishedItem"]["published-wiki-privacy"] = self.wiki_row("privacy", indexed)   # entityKey is the bare slug; the node key is editor_concept--privacy
        result = search_concepts(client, FakeIndex(), "Privacy", limit=5)
        pages = {entry["name"]: entry["publicPage"] for entry in result["results"]}
        self.assertTrue(pages["Privacy"])
        self.assertFalse(any(value for name, value in pages.items() if name != "Privacy"))
        self.assertTrue(related_concepts(client, "privacy")["concept"]["publicPage"])
        suggested = suggest_links(client, "s0")
        self.assertEqual({c["name"]: c["publicPage"] for c in suggested["concepts"]}["Privacy"], True)

    def test_a_page_found_by_the_published_index_counts(self):
        self.check(indexed=True)

    def test_a_page_found_only_in_the_published_summaries_counts(self):
        self.check(indexed=False)   # the live index returned no rows although the pages are published


class DuplicateTierTests(unittest.TestCase):
    def run_pair(self, left, right, cosine):
        client = site()
        add_nodes(client, ("left", left), ("right", right))
        index = FakeIndex(present=["left", "right"], query=(1.0, 0.0, 0.0))
        index.VECTORS = {"left": [1.0, 0.0, 0.0], "right": [cosine, (1 - cosine * cosine) ** 0.5, 0.0]}
        result = search_concepts(client, index, "zzz", limit=5)
        return {entry["lineageId"]: entry.get("duplicates") for entry in result["results"]}.get("left") or []

    def test_the_known_pairs(self):
        self.assertEqual(self.run_pair("Contextual integrity", "contextual integrity", 0.66)[0]["why"], "same name")
        self.assertEqual(self.run_pair("Re-identification", "Reidentification", 0.5)[0]["why"], "same name")
        self.assertEqual(self.run_pair("Training data", "Data training", 0.5)[0]["why"], "same name")
        possible = self.run_pair("Prompt injection", "Prompt injection attacks", 0.66)
        self.assertTrue(possible[0]["why"].startswith("possible duplicate (a suggestion)"), possible)

    def test_likely_needs_a_close_card_and_possible_needs_a_shared_word(self):
        self.assertTrue(self.run_pair("Sandbox", "Isolation boundary", 0.95)[0]["why"].startswith("likely duplicate"))
        self.assertEqual(self.run_pair("Sandbox", "Isolation boundary", 0.66), [])     # alike, but no shared word of 4+ letters
        self.assertEqual(self.run_pair("Prompt injection", "Prompt design", 0.5), [])   # shared word, cards too far apart


class MissingKeyTests(unittest.TestCase):
    def test_a_401_says_what_is_needed_and_the_command_fails_with_it(self):
        class Broken(FakeIndex):
            def embed_text(self, text):
                raise RuntimeError("HTTP Error 401: Unauthorized")

        result = search_concepts(site(), Broken(), "no such name")
        self.assertTrue(result["embeddingKeyProblem"])
        for phrase in ("OPENAI_API_KEY", "signed-in editor lane has no embedding key", "references search", "follow-up"):
            self.assertIn(phrase, result["indexNote"])
        with mock.patch.object(link_suggestions_commands, "create_authoring_client", return_value=(site(), {})), \
                mock.patch("papyrus_content.concept_search.default_provider", return_value=Broken()):
            with self.assertRaises(ValueError) as caught:
                link_suggestions_commands.relations_search(["no such name"])
        self.assertIn("OPENAI_API_KEY", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
