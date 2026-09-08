import pathlib
import re
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.editorial_diagnosis import diagnose_draft
from papyrus_content.editorial_embedders import SentenceEmbedder
from papyrus_content.editorial_semantic_restatement import analyze_semantic_restatement
from papyrus_content.editorial_style import SimilarityThresholds, load_style_profile
from papyrus_content.editorial_text import sentence_spans


class FakeEmbedder(SentenceEmbedder):
    def __init__(self, vectors: list[list[float]], embedder_id: str = "fake-test-embedder") -> None:
        self._vectors = vectors
        self._embedder_id = embedder_id

    @property
    def embedder_id(self) -> str:
        return self._embedder_id

    def embed(self, sentences: tuple[str, ...]) -> list[list[float]]:
        if len(sentences) != len(self._vectors):
            raise ValueError("FakeEmbedder vector count does not match sentence count.")
        return [list(vector) for vector in self._vectors]


def _shared_four_word_shingles(sentences: list[str]) -> set[str]:
    shingles: list[set[str]] = []
    for sentence in sentences:
        words = re.findall(r"[A-Za-z0-9']+", sentence.lower())
        shingles.append({" ".join(words[index : index + 4]) for index in range(len(words) - 3)})
    shared = shingles[0]
    for other in shingles[1:]:
        shared &= other
    return shared


class EditorialSemanticRestatementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
        self.profile = load_style_profile(self.fixture_root / "style-profile.yml")
        self.paraphrase_text = (self.fixture_root / "paraphrase-triple.md").read_text(encoding="utf-8")
        self.verbatim_text = (self.fixture_root / "verbatim-repeat.md").read_text(encoding="utf-8")

    def test_paraphrase_fixture_has_no_shared_four_word_phrase(self) -> None:
        sentences = [sentence for sentence, _, _ in sentence_spans(self.paraphrase_text)]
        self.assertEqual(len(sentences), 3)
        self.assertEqual(_shared_four_word_shingles(sentences), set())

    def test_injected_embedder_clusters_paraphrases(self) -> None:
        sentences = [sentence for sentence, _, _ in sentence_spans(self.paraphrase_text)]
        embedder = FakeEmbedder([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]])
        diagnosis = diagnose_draft(self.paraphrase_text, style_profile=self.profile, embedder=embedder)
        groups = [group for group in diagnosis["repetition_groups"] if group["kind"] == "concept_restatement"]
        self.assertEqual(len(groups), 1)
        self.assertGreaterEqual(len(groups[0]["members"]), 3)
        self.assertEqual(diagnosis["similarity"]["embedder"], "fake-test-embedder")
        self.assertEqual(diagnosis["similarity"]["clusterCount"], 1)

    def test_verbatim_repeat_uses_redundancy_not_concept_restatement(self) -> None:
        diagnosis = diagnose_draft(self.verbatim_text, style_profile=self.profile)
        redundancy = [group for group in diagnosis["repetition_groups"] if group["kind"] == "redundancy"]
        concept = [group for group in diagnosis["repetition_groups"] if group["kind"] == "concept_restatement"]
        self.assertEqual(len(redundancy), 1)
        self.assertEqual(len(concept), 0)

    def test_semantic_restatement_disabled_skips_groups(self) -> None:
        profile = load_style_profile(self.fixture_root / "semantic-restatement-off-profile.yml")
        embedder = FakeEmbedder([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]])
        diagnosis = diagnose_draft(self.paraphrase_text, style_profile=profile, embedder=embedder)
        concept = [group for group in diagnosis["repetition_groups"] if group["kind"] == "concept_restatement"]
        self.assertEqual(concept, [])
        self.assertNotIn("similarity", diagnosis)

    @patch("papyrus_content.editorial_semantic_restatement.resolve_local_embedder", return_value=None)
    def test_missing_fastembed_is_no_op(self, _mock_resolve) -> None:
        result = analyze_semantic_restatement(
            self.paraphrase_text,
            thresholds=SimilarityThresholds(
                cosine_threshold=0.72,
                restatement_min_sentences=3,
                embedder="local",
            ),
            redundancy_groups=[],
            embedder=None,
        )
        self.assertEqual(result.groups, [])
        self.assertIsNone(result.similarity)

    def test_similarity_embedder_off_is_no_op(self) -> None:
        embedder = FakeEmbedder([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]])
        result = analyze_semantic_restatement(
            self.paraphrase_text,
            thresholds=SimilarityThresholds(
                cosine_threshold=0.72,
                restatement_min_sentences=3,
                embedder="off",
            ),
            redundancy_groups=[],
            embedder=embedder,
        )
        self.assertEqual(result.groups, [])
        self.assertIsNone(result.similarity)

    def test_concept_restatement_not_duplicated_when_redundancy_covers_spans(self) -> None:
        diagnosis = diagnose_draft(self.verbatim_text, style_profile=self.profile, embedder=FakeEmbedder(
            [[1.0, 0.0], [1.0, 0.0]]
        ))
        concept = [group for group in diagnosis["repetition_groups"] if group["kind"] == "concept_restatement"]
        self.assertEqual(concept, [])


if __name__ == "__main__":
    unittest.main()
