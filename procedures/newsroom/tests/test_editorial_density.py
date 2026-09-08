import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.editorial_density import (
    FUNCTION_WORDS,
    analyze_density,
    density_summary_as_dict,
    gzip_ratio,
    lexical_density,
)
from papyrus_content.editorial_style import DensityThresholds
from papyrus_content.editorial_text import tokenize, word_count


class EditorialDensityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.thresholds = DensityThresholds(min_words=400, min_lexical_density=0.45, max_gzip_ratio=0.35)
        self.fluff_path = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis" / "low-density-fluff.md"
        self.house_path = (
            REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis" / "house-voice-density-excerpt.md"
        )
        self.short_path = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis" / "short-density-draft.md"

    def test_function_words_exclude_content_tokens(self) -> None:
        tokens = tokenize("latency repository inspect verify")
        self.assertEqual(lexical_density(tokens), 1.0)

    def test_function_words_reduce_lexical_density(self) -> None:
        tokens = tokenize("it is the case that there are many ways")
        self.assertLess(lexical_density(tokens), 0.45)
        self.assertIn("it", FUNCTION_WORDS)
        self.assertIn("the", FUNCTION_WORDS)
        self.assertNotIn("ways", FUNCTION_WORDS)

    def test_gzip_ratio_is_between_zero_and_one(self) -> None:
        ratio = gzip_ratio("repeat repeat repeat repeat repeat")
        self.assertGreater(ratio, 0.0)
        self.assertLessEqual(ratio, 1.0)

    def test_density_summary_dict_uses_camel_case(self) -> None:
        analysis = analyze_density("Concrete nouns beat filler.", self.thresholds)
        rendered = density_summary_as_dict(analysis.summary)
        self.assertEqual(set(rendered), {"wordCount", "sentenceCount", "lexicalDensity", "gzipRatio"})

    def test_long_fluff_flags_density_findings(self) -> None:
        text = self.fluff_path.read_text(encoding="utf-8")
        self.assertGreaterEqual(word_count(text), self.thresholds.min_words)
        analysis = analyze_density(text, self.thresholds)
        kinds = {finding["kind"] for finding in analysis.findings}
        self.assertTrue({"low_lexical_density", "high_compressibility"} & kinds)

    def test_house_voice_excerpt_passes_thresholds(self) -> None:
        text = self.house_path.read_text(encoding="utf-8")
        analysis = analyze_density(text, self.thresholds)
        self.assertEqual(analysis.findings, ())

    def test_short_draft_skips_document_level_findings(self) -> None:
        text = self.short_path.read_text(encoding="utf-8")
        self.assertLess(word_count(text), self.thresholds.min_words)
        analysis = analyze_density(text, self.thresholds)
        self.assertEqual(analysis.findings, ())
        self.assertGreater(analysis.summary.sentence_count, 0)


if __name__ == "__main__":
    unittest.main()
