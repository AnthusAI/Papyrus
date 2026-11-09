"""A signed-in editor changes a Story source's role through the site's route; the IAM lane keeps writing the row directly."""
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

from papyrus_content import story_commands  # noqa: E402
from papyrus_content.story_reporting import link_reference_to_story, set_story_reference_role, story_reference_relation_id  # noqa: E402
from story_reference_role_site import SignedInSite  # noqa: E402
from test_story_cli_live_test_edges import run  # noqa: E402

LINEAGE = "item-edge-story"
REFERENCE = "reference-edge"
RELATION = story_reference_relation_id(LINEAGE, REFERENCE)
RECORDS = {
    "Item": [{"id": f"{LINEAGE}-v1", "lineageId": LINEAGE, "versionNumber": 1, "versionState": "current", "headline": "A story", "title": "A story", "stage": "idea", "slug": "a-story", "type": "untyped", "section": "news"}],
    "Reference": [{"id": REFERENCE, "lineageId": REFERENCE, "versionNumber": 1, "versionState": "current", "title": "A source"}],
}


def metadata(site) -> dict:
    return json.loads(site.tables["SemanticRelation"][RELATION]["metadata"])


class SignedInRoleChangeTests(unittest.TestCase):
    def test_an_editor_marks_a_consulted_source_cited_through_the_route_after_the_direct_update_is_refused(self):
        site = SignedInSite(RECORDS, groups=["editor"])
        link_reference_to_story(site, LINEAGE, REFERENCE, role="consulted", actor="Grace Editor", now="2026-11-01T00:00:00Z")
        result = link_reference_to_story(site, LINEAGE, REFERENCE, role="cited", actor="Grace Editor", citation_key="smith2026")
        self.assertEqual((result["outcome"], result["role"]), ("updated", "cited"))
        self.assertEqual(site.refused, ["updateSemanticRelation"])   # refused before anything was written; the route made the change
        self.assertEqual(site.route_calls, [{"relationId": RELATION, "role": "cited", "citationKey": "smith2026", "note": None}])
        self.assertEqual((metadata(site)["role"], metadata(site)["citationKey"], metadata(site)["addedAt"]), ("cited", "smith2026", "2026-11-01T00:00:00Z"))

    def test_a_first_attachment_is_still_a_plain_create(self):
        site = SignedInSite(RECORDS, groups=["editor"])
        result = link_reference_to_story(site, LINEAGE, REFERENCE, role="cited", actor="Grace Editor", citation_key="k")
        self.assertEqual(result["outcome"], "created")
        self.assertEqual((site.refused, site.route_calls), ([], []))

    def test_the_cli_command_marks_the_source_cited_end_to_end(self):
        site = SignedInSite(RECORDS, groups=["editor"])
        link_reference_to_story(site, LINEAGE, REFERENCE, role="consulted", actor="Grace Editor")
        out, _err, failure = run(story_commands.stories_link_reference, site, "--story", LINEAGE, "--reference", REFERENCE, "--role", "cited", "--citation-key", "smith2026", signed_in=True, label="Grace Editor")
        self.assertIsNone(failure, failure)
        self.assertIn(f"stories\tlink-reference\tupdated\t{RELATION}", out)
        self.assertEqual(metadata(site)["role"], "cited")

    def test_a_viewer_is_refused_and_nothing_changes(self):
        site = SignedInSite(RECORDS, groups=["editor"])
        link_reference_to_story(site, LINEAGE, REFERENCE, role="consulted", actor="Grace Editor")
        site.groups = ["viewer"]
        out, _err, failure = run(story_commands.stories_link_reference, site, "--story", LINEAGE, "--reference", REFERENCE, "--role", "cited", signed_in=True, label="Val Viewer")
        self.assertIn("Not Authorized to access setStoryReferenceRole", str(failure))
        self.assertNotIn("write", out)
        self.assertEqual(metadata(site)["role"], "consulted")

    def test_a_site_without_the_route_says_what_to_do_instead(self):
        site = SignedInSite(RECORDS, groups=["editor"], has_route=False)
        link_reference_to_story(site, LINEAGE, REFERENCE, role="consulted", actor="Grace Editor")
        with self.assertRaisesRegex(RuntimeError, "predates the setStoryReferenceRole route.*PAPYRUS_GRAPHQL_AUTH=iam"):
            link_reference_to_story(site, LINEAGE, REFERENCE, role="cited", actor="Grace Editor")

    def test_any_other_failure_of_the_write_is_raised_as_it_was(self):
        site = SignedInSite(RECORDS, groups=["editor"])
        link_reference_to_story(site, LINEAGE, REFERENCE, role="consulted", actor="Grace Editor")
        with mock.patch.object(site, "upsert", side_effect=RuntimeError("GraphQL request failed: throttled")):
            with self.assertRaisesRegex(RuntimeError, "throttled"):
                link_reference_to_story(site, LINEAGE, REFERENCE, role="cited", actor="Grace Editor")
        self.assertEqual(site.route_calls, [])

    def test_an_unknown_role_is_refused_before_anything_is_sent(self):
        site = SignedInSite(RECORDS, groups=["editor"])
        with self.assertRaisesRegex(ValueError, "role must be one of"):
            set_story_reference_role(site, RELATION, role="quoted")
        self.assertEqual(site.route_calls, [])


class IamLaneTests(unittest.TestCase):
    def test_the_iam_lane_keeps_writing_the_row_directly(self):
        from fake_client import FakeAuthoringClient

        client = FakeAuthoringClient(RECORDS)
        client.graphql = mock.Mock(side_effect=AssertionError("the IAM lane must not call the route"))
        link_reference_to_story(client, LINEAGE, REFERENCE, role="consulted", actor="operator", assignment_id="assignment-1")
        result = link_reference_to_story(client, LINEAGE, REFERENCE, role="cited", actor="operator", citation_key="k")
        self.assertEqual(result["outcome"], "updated")
        stored = json.loads(client.tables["SemanticRelation"][RELATION]["metadata"])
        self.assertEqual((stored["role"], stored["assignmentId"]), ("cited", "assignment-1"))


if __name__ == "__main__":
    unittest.main()
