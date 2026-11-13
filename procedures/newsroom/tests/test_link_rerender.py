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
        if lineage in self.raises:   # the request to start the re-render got no answer: the command reports it as unknown
            return {"ok": None, "operation": "site_rerender_pages", "status": "unknown", "error": "The read operation timed out", "check": "papyrus ops content rerender --story item-big --no-invalidate --status"}
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

    def test_an_unanswered_request_is_reported_as_unknown_not_failed_and_does_not_fail_the_command(self):
        self.recorder.raises = {"item-big"}
        out, err, failure = link(link_site(), "--story", "item-big", "--to", "item-post-1")
        self.assertIsNone(failure)
        self.assertIn("rerender\titem-big\tno purge\tunknown", out)
        self.assertIn("not a failure", err)
        self.assertIn("rerender --story item-big --no-invalidate --status", err)
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


class AfterMergeTests(WithRecorder):
    """The --reference path and the suggest-links ready commands still work with the re-render in place."""

    def test_link_story_reference_path_still_writes_and_rerenders_only_the_story(self):
        import test_story_reference_links as references

        client = references.site()
        out, err, failure = link(client, "--story", "item-big", "--reference", "ref-a")
        self.assertIsNone(failure, err)
        self.assertEqual(len(references.rows(client)), 1)
        self.assertEqual(self.recorder.asked, ["item-big"])   # a Reference has no page of its own
        self.assertIn("rerender\titem-big\tno purge\tok", out)

    def test_suggest_links_ready_commands_run_as_printed(self):
        import shlex

        import test_link_suggestions as suggestions
        from papyrus_content.link_suggestions import suggest_links

        client = suggestions.site()
        client.endpoint = "https://fake.example/graphql"
        found = suggest_links(client, "s0")["candidates"]
        for command in (found["articles"][0]["command"], found["references"][0]["command"]):
            words = shlex.split(command)
            self.assertEqual(words[:3], ["papyrus", "stories", "link-story"])
            out, err, failure = link(client, *words[3:])
            self.assertIsNone(failure, err)
            self.assertIn("write", out)
        self.assertIn("s0", self.recorder.asked)

    def test_a_progress_line_precedes_each_rerender_and_stays_off_stdout(self):
        out, err, failure = link(link_site(), "--story", "item-big", "--to", "item-post-1")
        self.assertIsNone(failure)
        self.assertIn("rerendering item-big (about a minute)...", err)
        self.assertIn("rerendering item-post-1 (about a minute)...", err)
        self.assertNotIn("rerendering", out)


class TimeoutEnvTests(unittest.TestCase):
    def test_the_operator_lane_waits_as_long_as_the_timeout_variable_says(self):
        import os

        from papyrus_content.page_refresh.cli import run_operator

        seen = []

        def fake_client(_name, config=None):
            seen.append(config.read_timeout)
            return mock.Mock(invoke=mock.Mock(return_value={"Payload": b'{"ok": true}'}))

        for value, expected in ((None, 120), ("300", 300)):
            env = {k: v for k, v in os.environ.items() if k != "PAPYRUS_GRAPHQL_TIMEOUT_SECONDS"}
            if value:
                env["PAPYRUS_GRAPHQL_TIMEOUT_SECONDS"] = value
            with mock.patch.dict(os.environ, env, clear=True), mock.patch("boto3.client", fake_client), \
                    mock.patch("papyrus_content.projection_trigger.content_actions_function", return_value="fn"):
                run_operator("site_rerender_pages", {"scope": "story"})
            self.assertEqual(seen[-1], expected)


if __name__ == "__main__":
    unittest.main()
