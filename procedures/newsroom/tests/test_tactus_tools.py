from __future__ import annotations

import inspect
import io
import json
import pathlib
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
TESTS_ROOT = pathlib.Path(__file__).resolve().parent
for path in (SRC_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from papyrus_newsroom import tactus_tools  # noqa: E402
from test_story_reporting import LINEAGE, client_with_one_story  # noqa: E402


def public_tool_names(module) -> list[str]:
    return sorted(
        name for name, obj in inspect.getmembers(module) if inspect.isfunction(obj) and not name.startswith("_") and obj.__module__ == module.__name__
    )


class TactusToolsModuleTests(unittest.TestCase):
    def test_module_exposes_the_procedure_tools_and_nothing_imported(self):
        self.assertEqual(
            public_tool_names(tactus_tools),
            [
                "execute_tactus",
                "papyrus_check_story_version",
                "papyrus_create_story",
                "papyrus_curate_reference",
                "papyrus_editorial_context",
                "papyrus_fetch_pdf_text",
                "papyrus_find_or_register_source",
                "papyrus_link_story_reference",
                "papyrus_save_story_version",
                "papyrus_set_story_slug",
                "papyrus_story_version",
                "papyrus_story_versions",
            ],
        )

    def test_save_story_version_keeps_the_latest_front_matter_when_none_is_given(self):
        client = client_with_one_story()
        client.graphql = lambda *_: {"checkItemVersion": json.dumps(json.dumps({"itemId": "x", "violations": 0}))}
        with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, None)):
            saved = tactus_tools.papyrus_save_story_version(LINEAGE, "Second draft.", "Revise", "Ruling analyst")
            versions = tactus_tools.papyrus_story_versions(LINEAGE)
        self.assertEqual(saved["versionNumber"], 2)
        record = client.tables["Item"][saved["versionId"]]
        self.assertEqual(json.loads(record["metadata"])["frontMatterYaml"], 'title: "Sandbox escape"')
        self.assertEqual(record["status"], "draft")
        self.assertEqual([version["versionNumber"] for version in versions][0], 2)
        with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, None)):
            full = tactus_tools.papyrus_story_version(saved["versionId"])
        self.assertEqual(full["bodyMarkus"], "Second draft.")
        self.assertEqual(full["frontMatterYaml"], 'title: "Sandbox escape"')

    def test_create_story_records_a_new_lineage_in_the_section(self):
        client = client_with_one_story()
        client.tables["NewsroomSection"] = {"rulings": {"id": "rulings"}}
        with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, None)), mock.patch(
            "papyrus_content.records.apply_record_changes", side_effect=lambda store, changes: [store.create_record("Item", change["expected"]) for change in changes]
        ), mock.patch("papyrus_content.records.build_record_changes", side_effect=lambda store, specs: specs):
            created = tactus_tools.papyrus_create_story("A rule, not the parties", "rulings", "Ruling analyst")
        item = client.tables["Item"][created["versionId"]]
        self.assertEqual(item["section"], "rulings")
        self.assertEqual(created["stage"], "reporting")
        self.assertEqual(item["lineageId"], created["lineageId"])

    def test_set_story_slug_refuses_a_published_story(self):
        client = client_with_one_story()
        client.tables["Item"][LINEAGE]["status"] = "published"
        client.list_by_index_original = client.list_by_index
        client.list_by_index = lambda index_name, key_value, **kwargs: [] if index_name == "itemBySlug" else client.list_by_index_original(index_name, key_value, **kwargs)
        with mock.patch("papyrus_content.story_commands.create_authoring_client", return_value=(client, None)):
            with self.assertRaisesRegex(ValueError, "already published"):
                tactus_tools.papyrus_set_story_slug(LINEAGE, "a-better-address", "Ruling analyst")

    def test_create_story_rejects_an_unknown_section(self):
        client = client_with_one_story()
        with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, None)):
            with self.assertRaisesRegex(ValueError, "Unknown NewsroomSection"):
                tactus_tools.papyrus_create_story("Anything", "no-such-section", "Ruling analyst")

    def test_find_or_register_source_registers_once_and_then_finds_it(self):
        client = client_with_one_story()
        client.tables["KnowledgeCorpus"] = {"knowledge-corpus-site": {"id": "knowledge-corpus-site"}}
        client.list_records = lambda model: list(client.tables.get(model, {}).values())
        opinion = "https://ttabvue.uspto.gov/ttabvue/ttabvue-97752244-EXA-26.pdf"
        with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, None)), mock.patch.dict(
            "os.environ", {"PAPYRUS_GRAPHQL_ENDPOINT": "https://example.appsync-api.us-east-1.amazonaws.com/graphql"}
        ), mock.patch("papyrus_content.reference_intake._provenance"):
            first = tactus_tools.papyrus_find_or_register_source(opinion, "In re Wemby Corporation", "knowledge-corpus-site", "Ruling analyst", media_type="application/pdf")
            second = tactus_tools.papyrus_find_or_register_source(opinion, "In re Wemby Corporation", "knowledge-corpus-site", "Ruling analyst", media_type="application/pdf")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["curationStatus"], "pending")
        self.assertEqual(sum(1 for row in client.tables["Reference"].values() if row.get("sourceUri") == opinion), 1)

    def test_fetch_pdf_text_returns_numbered_pages_within_the_range(self):
        from pypdf import PdfWriter

        writer = PdfWriter()
        for _ in range(4):
            writer.add_blank_page(width=612, height=792)
        buffer = io.BytesIO()
        writer.write(buffer)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = buffer.getvalue()
        with mock.patch("urllib.request.urlopen", return_value=response):
            result = tactus_tools.papyrus_fetch_pdf_text("https://ttabvue.uspto.gov/opinion.pdf", first_page=2, last_page=3)
        self.assertEqual(result["pageCount"], 4)
        self.assertEqual([page["page"] for page in result["pages"]], [2, 3])


RUN_FINDINGS = [{"id": "f-1", "policyId": "no-hype", "severity": "warn", "status": "violation", "message": "Avoid game-changing.", "excerpt": "game-changing", "probability": 0.9}]


def checking_client(*, run=None, summary=None, runs_after=0):
    """A story client whose GraphQL answers checkItemVersion and getEditorialCheckRun like the site's function."""
    client = client_with_one_story()
    client.graphql_calls = []
    state = {"reads": 0}

    def graphql(query, variables=None):
        client.graphql_calls.append((query.split("(")[0].split()[-1], variables))
        if "checkItemVersion" in query:
            return {"checkItemVersion": json.dumps(json.dumps(summary or {"itemId": variables["itemId"], "violations": 1, "reviews": 0}))}
        state["reads"] += 1
        if run is None or state["reads"] <= runs_after:
            return {"getEditorialCheckRun": None}
        return {"getEditorialCheckRun": {**run, "findings": json.dumps(run["findings"]), "lanes": json.dumps(run["lanes"])}}

    client.graphql = graphql
    return client


def stored_run(findings, version_id=LINEAGE, number=1):
    violations = sum(1 for f in findings if f["status"] == "violation")
    return {
        "id": version_id, "itemId": version_id, "lineageId": LINEAGE, "versionNumber": number, "section": None, "contentHash": "abc",
        "packVersion": "pack-7", "violations": violations, "reviews": len(findings) - violations, "findings": findings,
        "lanes": {"rules": {"status": "ran"}, "classifier": {"status": "skipped"}}, "checkedAt": "2026-10-24T10:00:00Z",
    }


class CheckStoryVersionTests(unittest.TestCase):
    def check(self, client, **kwargs):
        with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, None)), mock.patch("time.sleep"):
            return tactus_tools.papyrus_check_story_version(**kwargs)

    def test_reports_findings_with_the_version_and_pack_checked(self):
        client = checking_client(run=stored_run(RUN_FINDINGS))
        result = self.check(client, version=LINEAGE)
        self.assertEqual(result["status"], "checked")
        self.assertFalse(result["clean"])
        self.assertEqual((result["versionId"], result["versionNumber"], result["packVersion"], result["contentHash"]), (LINEAGE, 1, "pack-7", "abc"))
        self.assertEqual(result["findings"], [{"id": "f-1", "rule": "no-hype", "severity": "warn", "status": "violation", "message": "Avoid game-changing.", "quote": "game-changing", "scope": "quote", "probability": 0.9}])
        self.assertEqual(result["lanes"]["rules"]["status"], "ran")
        self.assertEqual(client.graphql_calls[0], ("CheckItemVersion", {"itemId": LINEAGE}))

    def test_a_finding_with_no_quote_is_scoped_to_the_whole_document(self):
        whole = {"id": "f-2", "policyId": "general-meaning-first", "severity": "info", "status": "review", "message": "Lead with the meaning.", "excerpt": "", "probability": 0.5}
        blank = {**whole, "id": "f-3", "excerpt": None}
        located = {**whole, "id": "f-4", "paragraph": 2}
        findings = self.check(checking_client(run=stored_run([whole, blank, located, *RUN_FINDINGS])), version=LINEAGE)["findings"]
        self.assertEqual([f["scope"] for f in findings], ["document", "document", "document", "quote"])
        self.assertNotIn("paragraph", findings[0])
        self.assertEqual(findings[2]["paragraph"], 2)

    def test_a_check_with_no_findings_is_clean(self):
        result = self.check(checking_client(run=stored_run([])), version=LINEAGE)
        self.assertTrue(result["clean"])
        self.assertEqual(result["findings"], [])

    def test_a_review_finding_is_not_clean(self):
        review = [{**RUN_FINDINGS[0], "status": "review"}]
        self.assertFalse(self.check(checking_client(run=stored_run(review)), version=LINEAGE)["clean"])

    def test_names_the_version_by_story_and_number_or_newest(self):
        client = checking_client(run=stored_run([]))
        with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, None)):
            saved = tactus_tools.papyrus_save_story_version(LINEAGE, "Second.", "Revise", "Bot")
        self.assertEqual(client.graphql_calls[0][1], {"itemId": saved["versionId"]}, "the save checks the version it wrote")
        client.graphql_calls.clear()
        client.tables["EditorialCheckRun"] = {}
        self.check(client, story=LINEAGE, version_number=1)
        self.assertEqual(client.graphql_calls[0][1], {"itemId": LINEAGE})
        client.graphql_calls.clear()
        self.check(client, story=LINEAGE)
        self.assertEqual(client.graphql_calls[0][1], {"itemId": saved["versionId"]})

    def test_refuses_unknown_or_mismatched_versions(self):
        client = checking_client(run=stored_run([]))
        with self.assertRaisesRegex(ValueError, "not found"):
            self.check(client, version="nope")
        with self.assertRaisesRegex(ValueError, "not a version of story"):
            self.check(client, story="other-story", version=LINEAGE)
        with self.assertRaisesRegex(ValueError, "has no version 9"):
            self.check(client, story=LINEAGE, version_number=9)
        with self.assertRaisesRegex(ValueError, "Give a version id"):
            self.check(client)
        self.assertEqual(client.graphql_calls, [])

    def test_disabled_checks_are_skipped_not_clean(self):
        client = checking_client(summary={"itemId": LINEAGE, "skipped": "disabled"})
        result = self.check(client, version=LINEAGE)
        self.assertEqual((result["status"], result["clean"], result["reason"]), ("skipped", False, "disabled"))

    def test_waits_for_the_stored_result_and_then_returns_it(self):
        client = checking_client(run=stored_run([]), runs_after=2)
        result = self.check(client, version=LINEAGE, wait_seconds=60)
        self.assertEqual(result["status"], "checked")

    def test_returns_pending_when_no_result_appears_in_time(self):
        client = checking_client(run=None)
        with mock.patch("time.monotonic", side_effect=[0, 0, 5, 11]):
            result = self.check(client, version=LINEAGE, wait_seconds=10)
        self.assertEqual((result["status"], result["clean"]), ("pending", False))


if __name__ == "__main__":
    unittest.main()
