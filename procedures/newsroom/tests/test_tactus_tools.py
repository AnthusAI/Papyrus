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
                "papyrus_create_story",
                "papyrus_editorial_context",
                "papyrus_fetch_pdf_text",
                "papyrus_find_or_register_source",
                "papyrus_link_story_reference",
                "papyrus_save_story_version",
                "papyrus_story_versions",
            ],
        )

    def test_save_story_version_keeps_the_latest_front_matter_when_none_is_given(self):
        client = client_with_one_story()
        with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, None)):
            saved = tactus_tools.papyrus_save_story_version(LINEAGE, "Second draft.", "Revise", "Ruling analyst")
            versions = tactus_tools.papyrus_story_versions(LINEAGE)
        self.assertEqual(saved["versionNumber"], 2)
        record = client.tables["Item"][saved["versionId"]]
        self.assertEqual(json.loads(record["metadata"])["frontMatterYaml"], 'title: "Sandbox escape"')
        self.assertEqual(record["status"], "draft")
        self.assertEqual([version["versionNumber"] for version in versions][0], 2)

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


if __name__ == "__main__":
    unittest.main()
