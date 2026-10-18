import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_newsroom import tactus_runtime
from papyrus_newsroom.semantic import PapyrusSemanticClient
from papyrus_web.locations import build_web_ui_context, papyrus_uri_to_web_path, web_path_to_papyrus_location


class WebLocationTests(unittest.TestCase):
    def test_web_path_maps_newsroom_tabs_and_object_details(self):
        cases = [
            ("/newsroom", "papyrus://newsroom/overview"),
            ("/newsroom/references", "papyrus://newsroom/references/index"),
            ("/newsroom/references/reference-1", "papyrus://reference/reference-1"),
            ("/newsroom/messages/message-1", "papyrus://message/message-1"),
            ("/newsroom/assignments/assignment-1", "papyrus://assignment/assignment-1"),
            ("/newsroom/topics?category=category-1", "papyrus://category/category-1"),
            ("/newsroom/concepts?node=node-1", "papyrus://semanticNode/node-1"),
            ("/newsroom/assignments?view=budget", "papyrus://newsroom/assignments/index/view/budget"),
            ("/newsroom/administration/users", "papyrus://newsroom/administration/users"),
        ]
        for web_path, expected_uri in cases:
            with self.subTest(web_path=web_path):
                location = web_path_to_papyrus_location(web_path)
                self.assertEqual(location["papyrusLocationUri"], expected_uri)

    def test_papyrus_uri_maps_back_to_web_paths(self):
        cases = [
            ("papyrus://newsroom/overview", "/newsroom"),
            ("papyrus://newsroom/references", "/newsroom/references"),
            ("papyrus://reference/reference-1", "/newsroom/references/reference-1"),
            ("papyrus://category/category-1", "/newsroom/topics?category=category-1"),
            ("papyrus://semanticNode/node-1", "/newsroom/concepts?node=node-1"),
            ("papyrus://newsroom/assignments/budget", "/newsroom/assignments?view=budget"),
            ("papyrus://newsroom/references/index/status/pending", "/newsroom/references?status=pending"),
        ]
        for uri, expected_path in cases:
            with self.subTest(uri=uri):
                mapped = papyrus_uri_to_web_path(uri)
                self.assertEqual(mapped["webPath"], expected_path)

    def test_build_web_ui_context_includes_focused_object_uri(self):
        context = build_web_ui_context("/newsroom/references/reference-1")
        self.assertEqual(context["papyrusLocationUri"], "papyrus://reference/reference-1")
        self.assertEqual(context["papyrusObjectUri"], "papyrus://reference/reference-1")
        self.assertEqual(context["webPath"], "/newsroom/references/reference-1")

    def test_execute_tactus_web_navigate_returns_navigation_intent(self):
        web_ui = build_web_ui_context("/newsroom/references")
        result = tactus_runtime.execute_tactus(
            'return papyrus.web.navigate{ uri = "papyrus://reference/reference-2" }',
            web_ui_context=web_ui,
        )
        self.assertTrue(result["ok"], result.get("error"))
        navigation = result["value"]["navigation"]
        self.assertEqual(navigation["papyrusLocationUri"], "papyrus://reference/reference-2")
        self.assertEqual(navigation["webPath"], "/newsroom/references/reference-2")
        self.assertIn("papyrus.web.navigate", result["api_calls"])

    def test_index_page_maps_filters_in_uri_and_web_path(self):
        location = web_path_to_papyrus_location("/newsroom/references?status=pending&processing=processed")
        self.assertEqual(location["viewMode"], "index")
        self.assertEqual(location["indexFilters"]["status"], "pending")
        self.assertEqual(location["indexFilters"]["processing"], "processed")
        self.assertIn("/index/", location["papyrusLocationUri"])

        imported_location = web_path_to_papyrus_location("/newsroom/references?order=imported")
        self.assertEqual(imported_location["indexFilters"]["order"], "imported")
        self.assertEqual(imported_location["indexFilters"]["status"], "")
        imported_mapped = papyrus_uri_to_web_path("papyrus://newsroom/references/index/order/imported")
        self.assertEqual(imported_mapped["webPath"], "/newsroom/references?order=imported")

        reviewed_imported = web_path_to_papyrus_location("/newsroom/references?order=imported&status=exclude-pending")
        self.assertEqual(reviewed_imported["indexFilters"]["status"], "exclude-pending")

        mapped = papyrus_uri_to_web_path("papyrus://newsroom/messages/index/kind/note")
        self.assertEqual(mapped["webPath"], "/newsroom/messages?kind=note")
        self.assertEqual(mapped["viewMode"], "index")
        self.assertEqual(mapped["indexFilters"]["kind"], "note")

    def test_execute_tactus_set_index_filters_navigates_to_filtered_index(self):
        result = tactus_runtime.execute_tactus(
            'return papyrus.web.set_index_filters{ tab = "references", status = "pending" }'
        )
        self.assertTrue(result["ok"], result.get("error"))
        navigation = result["value"]["navigation"]
        self.assertEqual(navigation["webPath"], "/newsroom/references?status=pending")
        self.assertIn("papyrus://newsroom/references/index/status/pending", navigation["papyrusLocationUri"])

    def test_execute_tactus_web_current_location_reads_harness_snapshot(self):
        web_ui = build_web_ui_context("/newsroom/assignments/assignment-9")
        result = tactus_runtime.execute_tactus(
            "return papyrus.web.current_location{}",
            web_ui_context=web_ui,
        )
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["value"]["available"])
        self.assertEqual(
            result["value"]["location"]["papyrusLocationUri"],
            "papyrus://assignment/assignment-9",
        )

    def test_get_reference_resolves_lineage_id_from_newsroom_url(self):
        lineage_id = "reference-knowledge-corpus-ai-ml-research-context-rot-4"
        version_id = f"{lineage_id}-v1"
        current = {
            "id": version_id,
            "lineageId": lineage_id,
            "versionState": "current",
            "title": "Contextual Drag",
        }

        def fake_graphql(query, variables):
            if "getReference" in query:
                self.assertEqual(variables["id"], lineage_id)
                return {"getReference": None}
            self.assertEqual(variables["lineageId"], lineage_id)
            return {
                "listReferencesByLineageAndVersion": {
                    "items": [current],
                    "nextToken": None,
                }
            }

        client = PapyrusSemanticClient(fake_graphql)
        result = client.get_reference(lineage_id)
        self.assertEqual(result["reference"]["id"], version_id)
        self.assertEqual(result["reference"]["lineageId"], lineage_id)


if __name__ == "__main__":
    unittest.main()
