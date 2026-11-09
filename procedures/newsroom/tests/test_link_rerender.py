"""The link commands and agent tools re-render the story pages a new link changes, with no purge; a failure is a warning, never a failed command."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
for entry in (HERE.parents[2] / "src", HERE.parents[2], HERE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import concept_tags_commands, story_commands, story_rerender  # noqa: E402
from papyrus_content.story_signals_mcp import call_story_signal_tool, story_signal_descriptions  # noqa: E402
from story_reference_role_site import SignedInSite  # noqa: E402
import test_concept_tags as _concept_tests  # noqa: E402
from test_concept_tags import Site as ConceptSite  # noqa: E402
from test_story_cli_live_test_edges import run  # noqa: E402
from test_story_links import site as link_site  # noqa: E402

CONCEPT = concept_tags_commands.stories_link_concept
REFERENCE_CONCEPT = concept_tags_commands.references_link_concept


class Recorder:
    """Stands in for the page-refresh request: records each story asked for and answers ok, fails, or times out for the stories named."""

    def __init__(self, fail=(), raises=()):
        self.asked, self.fail, self.raises = [], set(fail), set(raises)

    def __call__(self, client, lineage, **_kw):
        self.asked.append(lineage)
        if lineage in self.raises:
            raise TimeoutError("Read timeout on endpoint URL")
        if lineage in self.fail:
            return {"ok": False, "operation": "site_rerender_pages", "rendered": {"ok": False, "errors": ["render failed"]}}
        return {"ok": True, "operation": "site_rerender_pages", "invalidate": False, "rendered": {"ok": True}}


def link(client, *flags):
    return run(story_commands.stories_link_story, client, *flags, signed_in=True, label="Grace Editor")


class WithRecorder(unittest.TestCase):
    def setUp(self):
        self.recorder = Recorder()
        patcher = mock.patch.object(story_rerender, "request_story_rerender", self.recorder)
        patcher.start()
        self.addCleanup(patcher.stop)


class LinkStoryRerenderTests(WithRecorder):
    def test_both_ends_of_a_story_link_are_rerendered_once_with_the_lines(self):
        out, err, failure = link(link_site(), "--story", "item-big", "--to", "item-post-1")
        self.assertIsNone(failure, err)
        self.assertEqual(self.recorder.asked, ["item-big", "item-post-1"])
        self.assertIn("rerender\titem-big\tno purge\tok", out)
        self.assertIn("rerender\titem-post-1\tno purge\tok", out)
        self.assertEqual(out.splitlines()[-1], story_rerender.VISIBLE_LINE)

    def test_an_unpublished_end_is_skipped(self):
        _out, _err, failure = link(link_site(), "--story", "item-big", "--to", "item-post-1", "--to", "item-post-2")
        self.assertIsNone(failure)
        self.assertEqual(self.recorder.asked, ["item-big", "item-post-1"])   # item-post-2 is a draft with no PublishedItem

    def test_a_dry_run_rerenders_nothing(self):
        _out, _err, failure = link(link_site(), "--story", "item-big", "--to", "item-post-1", "--dry-run")
        self.assertIsNone(failure)
        self.assertEqual(self.recorder.asked, [])

    def test_nothing_new_written_rerenders_nothing(self):
        client = link_site()
        link(client, "--story", "item-big", "--to", "item-post-1")
        self.recorder.asked.clear()
        out, _err, failure = link(client, "--story", "item-post-1", "--to", "item-big")
        self.assertIsNone(failure)
        self.assertEqual(self.recorder.asked, [])
        self.assertNotIn("rerender", out)

    def test_no_rerender_skips_it(self):
        out, _err, failure = link(link_site(), "--story", "item-big", "--to", "item-post-1", "--no-rerender")
        self.assertIsNone(failure)
        self.assertEqual(self.recorder.asked, [])
        self.assertNotIn(story_rerender.VISIBLE_LINE, out)

    def test_a_failure_is_a_warning_naming_the_story_and_the_manual_command_and_the_link_stays(self):
        self.recorder.fail = {"item-post-1"}
        client = link_site()
        out, err, failure = link(client, "--story", "item-big", "--to", "item-post-1")
        self.assertIsNone(failure)
        self.assertEqual(len(client.tables["SemanticRelation"]), 1)
        self.assertIn("rerender\titem-post-1\tno purge\tfailed", out)
        self.assertIn("papyrus ops content rerender --story item-post-1 --no-invalidate", err)

    def test_a_timeout_warns_that_it_may_have_completed_and_does_not_fail(self):
        self.recorder.raises = {"item-big"}
        out, err, failure = link(link_site(), "--story", "item-big", "--to", "item-post-1")
        self.assertIsNone(failure)
        self.assertIn("may still have completed", err)
        self.assertIn("rerender\titem-post-1\tno purge\tok", out)

    def test_json_carries_rerendered_and_no_text_lines(self):
        out, _err, failure = link(link_site(), "--story", "item-big", "--to", "item-post-1", "--json")
        self.assertIsNone(failure)
        payload = json.loads(out)
        self.assertEqual([row["lineageId"] for row in payload["rerendered"]], ["item-big", "item-post-1"])
        self.assertEqual({row["purged"] for row in payload["rerendered"]}, {False})


class CapTests(unittest.TestCase):
    def test_over_the_cap_the_rest_are_listed_as_exact_commands(self):
        client = SignedInSite({"PublishedItem": [{"id": f"published-s{n}"} for n in range(25)]}, groups=["editor"], label="Grace Editor")
        recorder = Recorder()
        done = story_rerender.rerender_after_write(client, [f"s{n}" for n in range(25)], request=recorder)
        self.assertEqual(len(recorder.asked), 20)
        self.assertEqual(done["notRun"], [f"s{n}" for n in range(20, 25)])
        self.assertIn("papyrus ops content rerender --story s24 --no-invalidate", done["warnings"][0])

    def test_duplicates_are_asked_once(self):
        client = SignedInSite({"PublishedItem": [{"id": "published-a"}]}, groups=["editor"], label="Grace Editor")
        recorder = Recorder()
        story_rerender.rerender_after_write(client, ["a", "a"], request=recorder)
        self.assertEqual(recorder.asked, ["a"])

    def test_the_request_is_a_no_invalidate_story_rerender(self):
        calls = []
        with mock.patch("papyrus_content.page_refresh.cli.run_operator", side_effect=lambda name, args: calls.append((name, args)) or {"ok": True}), \
                mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=False):
            story_rerender.request_story_rerender(object(), "item-big")
        name, args = calls[0]
        self.assertEqual((name, args["scope"], args["storyLineageId"], args["invalidate"]), ("site_rerender_pages", "story", "item-big", False))


class ToolTests(WithRecorder):
    def test_link_stories_tool_returns_rerendered(self):
        done = call_story_signal_tool("papyrus_link_stories", {"story": "big", "see_also_stories": ["post-1"]}, link_site(), actor="Grace Editor")
        self.assertEqual([row["lineageId"] for row in done["rerendered"]], ["item-big", "item-post-1"])
        self.assertNotIn("rerenderWarnings", done)

    def test_link_stories_tool_dry_run_and_repeat_rerender_nothing(self):
        client = link_site()
        dry = call_story_signal_tool("papyrus_link_stories", {"story": "big", "see_also_stories": ["post-1"], "dryRun": True}, client, actor="Grace Editor")
        self.assertEqual(dry["rerendered"], [])
        call_story_signal_tool("papyrus_link_stories", {"story": "big", "see_also_stories": ["post-1"]}, client, actor="Grace Editor")
        again = call_story_signal_tool("papyrus_link_stories", {"story": "big", "see_also_stories": ["post-1"]}, client, actor="Grace Editor")
        self.assertEqual(again["rerendered"], [])

    def test_link_stories_tool_failure_is_in_rerender_warnings(self):
        self.recorder.fail = {"item-big"}
        done = call_story_signal_tool("papyrus_link_stories", {"story": "big", "see_also_stories": ["post-1"]}, link_site(), actor="Grace Editor")
        self.assertEqual(done["rerendered"][0]["status"], "failed")
        self.assertIn("--story item-big --no-invalidate", done["rerenderWarnings"][0])

    def test_link_concepts_tool_rerenders_a_story_but_not_a_reference(self):
        site = ConceptSite()
        done = call_story_signal_tool("papyrus_link_concepts", {"target_kind": "story", "target": "big", "concepts": ["#voice-cloning"]}, site, actor="Grace Editor")
        self.assertEqual([row["lineageId"] for row in done["rerendered"]], ["item-big"])
        refs = call_story_signal_tool("papyrus_link_concepts", {"target_kind": "reference", "target": "reference-a", "concepts": ["#voice-cloning"]}, site, actor="Grace Editor")
        self.assertNotIn("rerendered", refs)
        again = call_story_signal_tool("papyrus_link_concepts", {"target_kind": "story", "target": "big", "concepts": ["#voice-cloning"]}, site, actor="Grace Editor")
        self.assertEqual(again["rerendered"], [])

    def test_tool_descriptions_mention_the_rerender(self):
        for name in ("papyrus_link_stories", "papyrus_link_concepts"):
            self.assertIn("no purge", story_signal_descriptions()[name])


class ConceptCommandRerenderTests(WithRecorder):
    link = _concept_tests.CommandTests.link
    _run = _concept_tests.CommandTests._run

    def test_stories_link_concept_rerenders_the_story_once(self):
        out, err, failure = self.link(ConceptSite(), CONCEPT, "--story", "big", "--concept", "#voice-cloning", "--concept", "editor_concept--translation")
        self.assertIsNone(failure, err)
        self.assertEqual(self.recorder.asked, ["item-big"])
        self.assertIn("rerender\titem-big\tno purge\tok", out)
        self.assertEqual(out.splitlines()[-1], story_rerender.VISIBLE_LINE)

    def test_dry_run_repeat_and_no_rerender_skip_it(self):
        site = ConceptSite()
        self.link(site, CONCEPT, "--story", "big", "--concept", "#voice-cloning", "--dry-run")
        self.link(site, CONCEPT, "--story", "big", "--concept", "#voice-cloning", "--no-rerender")
        self.assertEqual(self.recorder.asked, [])
        self.link(site, CONCEPT, "--story", "big", "--concept", "#voice-cloning")   # exists: nothing new
        self.assertEqual(self.recorder.asked, [])

    def test_a_reference_has_no_page_to_rerender(self):
        _out, err, failure = self.link(ConceptSite(), REFERENCE_CONCEPT, "--reference", "reference-a", "--concept", "#voice-cloning")
        self.assertIsNone(failure, err)
        self.assertEqual(self.recorder.asked, [])

    def test_a_failure_is_a_warning(self):
        self.recorder.fail = {"item-big"}
        _out, err, failure = self.link(ConceptSite(), CONCEPT, "--story", "big", "--concept", "#voice-cloning")
        self.assertIsNone(failure)
        self.assertIn("--story item-big --no-invalidate", err)


if __name__ == "__main__":
    unittest.main()
