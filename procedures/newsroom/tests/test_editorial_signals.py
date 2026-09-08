import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.editorial_signals import (
    EditorialSignalsCatalog,
    catalog_as_dict,
    implemented_signals,
    load_editorial_signals_catalog,
    signal_by_id,
)
from papyrus_content.editorial_style import StyleProfileValidationError


class EditorialSignalsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog_path = REPO_ROOT / "publications" / "anthus" / "editorial-signals.yml"

    def test_load_catalog_has_all_issue_rows(self) -> None:
        catalog = load_editorial_signals_catalog(self.catalog_path)
        self.assertEqual(catalog.publication_key, "anthus-blog")
        self.assertEqual(len(catalog.signals), 14)

    def test_lexical_density_and_gzip_are_implemented(self) -> None:
        catalog = load_editorial_signals_catalog(self.catalog_path)
        lexical = signal_by_id(catalog, "lexical_density")
        gzip = signal_by_id(catalog, "gzip_ratio")
        self.assertIsNotNone(lexical)
        self.assertIsNotNone(gzip)
        assert lexical is not None
        assert gzip is not None
        self.assertTrue(lexical.implemented)
        self.assertTrue(gzip.implemented)
        self.assertEqual(lexical.finding_kind, "low_lexical_density")
        self.assertEqual(gzip.finding_kind, "high_compressibility")

    def test_sentence_embedding_paraphrase_not_implemented(self) -> None:
        catalog = load_editorial_signals_catalog(self.catalog_path)
        signal = signal_by_id(catalog, "sentence_embedding_paraphrase")
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertFalse(signal.implemented)
        self.assertEqual(signal.finding_kind, "concept_restatement")

    def test_implemented_signals_excludes_later_entries(self) -> None:
        catalog = load_editorial_signals_catalog(self.catalog_path)
        implemented_ids = {signal.id for signal in implemented_signals(catalog)}
        self.assertIn("lexical_density", implemented_ids)
        self.assertNotIn("type_token_ratio", implemented_ids)
        self.assertNotIn("sentence_embedding_paraphrase", implemented_ids)

    def test_catalog_round_trip_dict(self) -> None:
        catalog = load_editorial_signals_catalog(self.catalog_path)
        rendered = catalog_as_dict(catalog)
        self.assertEqual(rendered["schemaVersion"], 1)
        self.assertEqual(len(rendered["signals"]), len(catalog.signals))

    def test_duplicate_signal_id_rejected(self) -> None:
        invalid = (
            "schemaVersion: 1\n"
            "publicationKey: anthus-blog\n"
            "signals:\n"
            "  - id: lexical_density\n"
            "    establishedAs: test\n"
            "    findingKind: low_lexical_density\n"
            "    implemented: true\n"
            "  - id: lexical_density\n"
            "    establishedAs: test\n"
            "    findingKind: low_lexical_density\n"
            "    implemented: true\n"
        )
        path = self.catalog_path.parent / "invalid-signals.yml"
        path.write_text(invalid, encoding="utf-8")
        try:
            with self.assertRaises(StyleProfileValidationError):
                load_editorial_signals_catalog(path)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
