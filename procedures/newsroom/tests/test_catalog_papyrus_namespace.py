from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_newsroom.reference_curation_signals import apply_title_subtitle_to_catalog_item  # noqa: E402

MIGRATION_SCRIPT_PATH = REPO_ROOT / "scripts" / "migrate_catalog_papyrus_namespace.py"
migration_spec = importlib.util.spec_from_file_location("migrate_catalog_papyrus_namespace", MIGRATION_SCRIPT_PATH)
migration_module = importlib.util.module_from_spec(migration_spec)
migration_spec.loader.exec_module(migration_module)

BIBLICUS_CATALOG_ITEM = {
    "id": "item-1",
    "relpath": "raw/item-1.html",
    "sha256": "abc",
    "bytes": 3,
    "media_type": "text/html",
    "title": "Old title",
    "tags": [],
    "metadata": {},
    "created_at": "2026-01-01T00:00:00Z",
    "source_uri": "https://example.com/a",
}


class CatalogPapyrusNamespaceTests(unittest.TestCase):
    def test_title_subtitle_extension_fields_are_written_under_metadata_papyrus(self) -> None:
        enriched = apply_title_subtitle_to_catalog_item(
            dict(BIBLICUS_CATALOG_ITEM),
            resolution={"title": "New title", "subtitle": "A useful subtitle", "summary": ""},
        )
        self.assertEqual(enriched["title"], "New title")
        self.assertEqual(set(enriched) - set(BIBLICUS_CATALOG_ITEM), set())
        metadata = enriched["metadata"]
        self.assertEqual(set(metadata), {"papyrus"})
        papyrus_extension = metadata["papyrus"]
        self.assertEqual(papyrus_extension["subtitle"], "A useful subtitle")
        self.assertIn("identifiers", papyrus_extension)
        self.assertIn("title_subtitle", papyrus_extension)
        self.assertNotIn("papyrus", papyrus_extension)

    def test_migration_moves_directly_stored_extension_fields_under_papyrus(self) -> None:
        item = {
            **BIBLICUS_CATALOG_ITEM,
            "metadata": {
                "subtitle": "Sub",
                "identifiers": {"doi": "10.1/x"},
                "quality": {"rating": 4},
                "papyrus": {"title_subtitle": {"title": "T"}},
                "unrelated": 1,
            },
        }
        migrated, changed = migration_module.migrate_catalog_item_metadata(item)
        self.assertTrue(changed)
        self.assertEqual(
            migrated["metadata"],
            {
                "unrelated": 1,
                "papyrus": {
                    "subtitle": "Sub",
                    "identifiers": {"doi": "10.1/x"},
                    "quality_rating": {"rating": 4},
                    "title_subtitle": {"title": "T"},
                },
            },
        )
        _, changed_again = migration_module.migrate_catalog_item_metadata(migrated)
        self.assertFalse(changed_again)


if __name__ == "__main__":
    unittest.main()
