"""`papyrus stories suggest-associations`: lexical concept matching, seeding the graph pass, Reference input, read only, no key."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
for entry in (HERE.parents[2] / "src", HERE.parents[2], HERE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import link_suggestions_commands  # noqa: E402
from papyrus_content.association_suggestions import lexical_matches, suggest_associations  # noqa: E402
from papyrus_content.link_suggestions import suggest_links  # noqa: E402
from test_link_suggestions import site  # noqa: E402


def text(title="", summary="", body=""):
    return {"title": title, "summary": summary, "body": body}


def node(name, key=None, aliases=()):
    return {"id": f"{name}-v1", "lineageId": name, "nodeKey": key or f"editor_concept--{name.lower().replace(' ', '-')}", "displayName": name, "aliases": list(aliases)}


def retitled(client, lineage, title, body=""):
    client.tables["Item"][f"{lineage}-v1"].update({"headline": title, "title": title, "body": [body] if body else []})
    return client


def ask(client, kind, ref):
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
        return suggest_associations(client, kind, ref)


class LexicalTests(unittest.TestCase):
    def test_whole_words_only(self):
        ai = node("AI")
        self.assertEqual(lexical_matches([ai], text("He said it was paid for", body="said paid")), {})
        self.assertIn("AI", lexical_matches([ai], text("The AI debate")))
        self.assertEqual(lexical_matches([ai], text("the ai debate")), {})   # a three-letter name keeps its letter case

    def test_aliases_and_hashtags_match(self):
        voice = node("Voice Cloning", "editor_concept--voice-cloning", ["synthetic voices"])
        self.assertEqual(lexical_matches([voice], text(body="Synthetic Voices are rising"))["Voice Cloning"]["matched"], "synthetic voices")
        self.assertIn("Voice Cloning", lexical_matches([voice], text(body="about voice cloning")))

    def test_position_orders_title_summary_body(self):
        a, b, c = node("Alpha"), node("Beta"), node("Gamma")
        found = lexical_matches([a, b, c], text("Alpha", "Beta", "Gamma"))
        self.assertGreater(found["Alpha"]["position"], found["Beta"]["position"])
        self.assertGreater(found["Beta"]["position"], found["Gamma"]["position"])


class SuggestTests(unittest.TestCase):
    def test_an_untagged_story_gets_concepts_and_related_items(self):
        client = retitled(site(), "s9", "Privacy risks of voice cloning")
        result = ask(client, "item", "s9")
        names = [entry["name"] for entry in result["concepts"]]
        self.assertIn("Privacy", names)
        self.assertIn("Voice Cloning", names)
        self.assertTrue(all(entry["command"].startswith("papyrus stories link-concept --story s9 --concept") for entry in result["concepts"]))
        articles = result["candidates"]["articles"]
        self.assertTrue(articles and articles[0]["command"].startswith("papyrus stories link-story --story s9 --to"))
        self.assertTrue(any("name only" in note for note in result["notes"]))
        self.assertEqual([call for call in client.calls if call[0] in ("create", "update", "delete", "upsert")], [])

    def test_a_tagged_story_keeps_the_suggest_links_ranking(self):
        result = ask(site(), "item", "s0")
        plain = suggest_links(site(), "s0")
        self.assertEqual([item["id"] for item in result["candidates"]["articles"]][:1], [item["id"] for item in plain["candidates"]["articles"]][:1])
        self.assertTrue(all(entry["command"] is None for entry in result["concepts"] if entry["alreadyTagged"]))

    def test_a_reference_is_a_reference_and_commands_point_at_it(self):
        client = site()
        client.tables["Reference"]["ref-1"]["title"] = "Privacy and voice cloning in speech"
        result = ask(client, "reference", "ref-1")
        self.assertEqual(result["item"]["kind"], "reference")
        stories = result["candidates"]["articles"] + result["candidates"]["posts"]
        self.assertTrue(stories and all(item["command"].endswith("--reference ref-1") for item in stories))
        self.assertTrue(all("references link-concept --reference ref-1" in entry["command"] for entry in result["concepts"] if entry["command"]))
        self.assertTrue(all(item["id"] != "ref-1" for item in result["candidates"]["references"]))
        self.assertEqual([call for call in client.calls if call[0] in ("create", "update", "delete", "upsert")], [])

    def test_unknown_items_are_errors(self):
        with self.assertRaises(ValueError):
            ask(site(), "reference", "nope")
        with self.assertRaises(ValueError):
            ask(site(), "item", "nope")


class CommandTests(unittest.TestCase):
    def run_command(self, *flags):
        out = io.StringIO()
        client = retitled(site(), "s9", "Privacy risks of voice cloning")
        with contextlib.redirect_stdout(out), mock.patch.object(link_suggestions_commands, "create_authoring_client", return_value=(client, {})), \
                mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            link_suggestions_commands.stories_suggest_associations(list(flags))
        return out.getvalue()

    def test_text_and_json(self):
        text_out = self.run_command("--story", "s9")
        self.assertIn("papyrus stories link-concept --story s9", text_out)
        self.assertIn("papyrus stories link-story --story s9 --to", text_out)
        data = json.loads(self.run_command("--story", "s9", "--json"))
        self.assertTrue(data["ok"] and data["concepts"])

    def test_exactly_one_target(self):
        for flags in ((), ("--story", "s9", "--reference", "ref-1")):
            with self.assertRaises(ValueError):
                self.run_command(*flags)


if __name__ == "__main__":
    unittest.main()
