"""The public JSON files: valid, bounded, opt-in, and rewritten only when their content moves."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from papyrus_content.projection.projector import (
    MarkusProjectorSettings,
    MarkusSiteProjector,
    read_static_files,
    settings_from_mapping,
)
from papyrus_content.projection.public_data import (
    LATEST_KEY,
    SEARCH_INDEX_KEY,
    PublicDataSettings,
    clipped,
    public_data_settings_from_mapping,
    public_static_files,
    tags_of,
)
from papyrus_content.projection.writers import cache_control_for, content_type_for
from procedures.newsroom.tests.incremental_site import Draft, Site, add_item, seeded_site


class PublicDataTests(unittest.TestCase):
    def test_a_site_that_does_not_opt_in_has_no_data_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("generic", Path(temporary))
            keys = {entry.key for entry in site.store.list("")}
            self.assertFalse([key for key in keys if key.startswith("_data/")])

    def test_search_index_and_latest_are_valid_and_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("public", Path(temporary), count=6)
            index = json.loads(site.store.get(SEARCH_INDEX_KEY))
            latest = json.loads(site.store.get(LATEST_KEY))
            self.assertEqual(len(index), 6)
            self.assertEqual([entry["date"] for entry in index], sorted((entry["date"] for entry in index), reverse=True))
            self.assertEqual(latest, index[:4])
            first = index[0]
            self.assertEqual(set(first), {"title", "url", "summary", "tags", "date"})
            self.assertTrue(first["url"].startswith("/articles/"))
            self.assertIn("month-01", first["tags"])

    def test_a_body_edit_writes_only_the_item_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("public", Path(temporary))
            site.touched.clear()
            site.drafts["item-1"].body = "A different body.\n"
            site.publish("item-1")
            site.project_item("item-1")
            self.assertEqual(site.touched, {"articles/seed-1.html"})

    def test_a_title_edit_rewrites_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("public", Path(temporary))
            site.touched.clear()
            site.drafts["item-2"].title = "Brand new title"
            site.publish("item-2")
            site.project_item("item-2")
            self.assertLessEqual({SEARCH_INDEX_KEY, LATEST_KEY}, site.touched)
            titles = [entry["title"] for entry in json.loads(site.store.get(SEARCH_INDEX_KEY))]
            self.assertIn("Brand new title", titles)

    def test_an_unpublished_item_leaves_the_index_and_hidden_items_are_not_listed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("public", Path(temporary))
            site.drafts["item-0"].hidden = True
            site.publish("item-0")
            site.project_item("item-0")
            urls = [entry["url"] for entry in json.loads(site.store.get(SEARCH_INDEX_KEY))]
            self.assertNotIn("/articles/seed-0.html", urls)
            self.assertEqual(len(urls), 2)

    def test_projection_settings_accept_public_data_and_reject_unknown_names(self) -> None:
        settings = settings_from_mapping({"publicData": {"latestCount": 5}})
        self.assertEqual(settings.public_data, PublicDataSettings(latest_count=5))
        with self.assertRaises(ValueError):
            public_data_settings_from_mapping({"searchindex": True})
        with self.assertRaises(ValueError):
            public_data_settings_from_mapping({"latestCount": 0})
        self.assertIsNone(settings_from_mapping({}).public_data)

    def test_files_can_be_switched_off_one_by_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = Site("generic", Path(temporary))
            projector = MarkusSiteProjector(
                MarkusProjectorSettings(public_data=PublicDataSettings(latest=False)), read_static_files(None, None)
            )
            self.assertEqual(set(projector.public_data_pages(site.context.source.site_index())), {SEARCH_INDEX_KEY})
            add_item(site, "item-0", "only")
            pages = projector.public_data_pages(site.context.source.site_index())
            self.assertEqual(set(pages), {SEARCH_INDEX_KEY})

    def test_the_search_component_ships_only_with_the_search_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIn("_plugins/papyrus-search@1.js", Site("public", Path(temporary)).projector.static_files())
        with tempfile.TemporaryDirectory() as temporary:
            self.assertNotIn("_plugins/papyrus-search@1.js", Site("generic", Path(temporary)).projector.static_files())
        self.assertEqual(public_static_files(PublicDataSettings(search_index=False)), {})

    def test_helpers_and_headers(self) -> None:
        self.assertEqual(clipped("a  b\n c", 20), "a b c")
        self.assertEqual(len(clipped("x" * 500, 40)), 40)
        self.assertEqual(tags_of("a, b ,a"), ("a", "b"))
        self.assertEqual(tags_of(["x", " "]), ("x",))
        self.assertEqual(tags_of(None), ())
        self.assertEqual(content_type_for(SEARCH_INDEX_KEY), "application/json")
        self.assertEqual(cache_control_for(SEARCH_INDEX_KEY), "public, max-age=0, s-maxage=300, stale-while-revalidate=60")


if __name__ == "__main__":
    unittest.main()
